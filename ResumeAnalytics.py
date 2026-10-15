import os
import re
import json
import logging
from typing import Dict, Any, Optional

from dotenv import load_dotenv, find_dotenv

# Document loaders
try:
    from langchain_community.document_loaders import PyMuPDFLoader, TextLoader, Docx2txtLoader
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

# Groq client
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def ExceptionHandler(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"[Error] in {func.__name__}: {e}")
            return None
    return wrapper


class ResumeAnalytics:

    def __init__(self) -> None:
        load_dotenv(find_dotenv())

        self.GROQ_API_KEY = os.getenv("GROQ_API_KEY")
        if not self.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY not found in .env file.\n"
                "Get your FREE key at: https://console.groq.com\n"
                "Then add to .env:  GROQ_API_KEY=your_key_here"
            )

        if not GROQ_AVAILABLE:
            raise ImportError("groq package not installed. Run: pip install groq")

        self.client = Groq(api_key=self.GROQ_API_KEY)

        # Groq retired llama-3.3-70b-versatile and llama-3.1-8b-instant on 16 Aug 2026.
        # Override on Render with a GROQ_MODEL env var if Groq retires these too.
        self.model_name = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        self.fallback_models = ["openai/gpt-oss-20b", "qwen/qwen3.6-27b"]

        self.outputsFOLDER = "outputs"
        os.makedirs(self.outputsFOLDER, exist_ok=True)
        logger.info(f"Groq client initialized. Model: {self.model_name}")

    # ────────────────────────────────────────────
    #  SINGLE place that talks to Groq (with model fallback)
    # ────────────────────────────────────────────
    def _chat(self, messages, temperature=0.3, max_tokens=4096) -> str:
        """Call Groq. If a model is retired/not found, try the next one."""
        models = [self.model_name] + [m for m in self.fallback_models if m != self.model_name]
        last_err = None
        for model in models:
            try:
                resp = self.client.chat.completions.create(
                    messages=messages, model=model,
                    temperature=temperature, max_tokens=max_tokens,
                )
                if model != self.model_name:
                    logger.warning(f"Switched to working model: {model}")
                    self.model_name = model
                return (resp.choices[0].message.content or "").strip()
            except Exception as e:
                err = str(e).lower()
                last_err = e
                retired = any(k in err for k in ("decommission", "deprecat", "model_not_found",
                                                 "does not exist", "no longer supported", "404"))
                logger.error(f"Groq call failed on model {model}: {e}")
                if not retired:
                    raise          # key invalid / rate limit / network -> real error, don't hide it
        raise last_err

    # ────────────────────────────────────────────
    #  CORE: call AI and always return a dict
    # ────────────────────────────────────────────
    def getResponse(self, prompt: str) -> Dict[str, Any]:
        """Always returns a dict. On failure the dict has an 'error' key with the REAL reason."""
        try:
            text = self._chat(
                [
                    {"role": "system", "content": (
                        "You are an expert resume screening assistant. "
                        "Always return ONLY valid JSON - no markdown, no explanation, "
                        "no code fences, just the raw JSON object.")},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3, max_tokens=8192,
            )
            text = re.sub(r"^```json|^```|```$", "", text, flags=re.MULTILINE).strip()
            m = re.search(r"\{.*\}", text, flags=re.DOTALL)   # grab the JSON object if extra text exists
            return json.loads(m.group(0) if m else text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return {"error": "AI returned invalid JSON. Please try again."}
        except Exception as e:
            err = str(e)
            logger.error(f"Groq API error: {err}")
            if "401" in err or "invalid_api_key" in err.lower():
                return {"error": "Groq API key is invalid or missing on the server."}
            if "429" in err or "rate" in err.lower():
                return {"error": "AI rate limit hit. Please wait a moment and try again."}
            return {"error": err}

    # ────────────────────────────────────────────
    #  TEXT CLEANING
    # ────────────────────────────────────────────
    def datacleaning(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[^\x00-\x7F]+", " ", text)
        return text.strip()

    # ────────────────────────────────────────────
    #  DOCUMENT PARSER
    # ────────────────────────────────────────────
    @ExceptionHandler
    def documentParser(self, filepath: str) -> Optional[Dict[str, Any]]:
        if not filepath or not os.path.exists(filepath):
            logger.error(f"File not found: {filepath}")
            return None

        ext = os.path.splitext(filepath)[1].lower()

        if not LANGCHAIN_AVAILABLE:
            # Fallback: plain text read
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    return {"content": self.datacleaning(f.read()), "pages": 1}
            except Exception as e:
                logger.error(f"Fallback read failed: {e}")
                return None

        if ext == ".pdf":
            loader = PyMuPDFLoader(filepath)
        elif ext == ".docx":
            loader = Docx2txtLoader(filepath)
        elif ext == ".txt":
            loader = TextLoader(filepath)
        else:
            logger.error(f"Unsupported file type: {ext}")
            return None

        docs = loader.load()
        content = " ".join(d.page_content for d in docs)
        return {"content": self.datacleaning(content), "pages": len(docs)}

    # ────────────────────────────────────────────
    #  MAIN: RESUME ANALYTICS (ATS + scores)
    # ────────────────────────────────────────────
    @ExceptionHandler
    def resumeanalytics(self, resumepath: str, jobdescription: str,
                        prompt_file: str = "prompt.txt") -> Optional[Dict[str, Any]]:

        resume = self.documentParser(resumepath)
        jd = self.documentParser(jobdescription)

        if not resume or not jd:
            logger.error("Could not parse resume or JD file.")
            return self._default_result()

        if not os.path.exists(prompt_file):
            raise FileNotFoundError(f"{prompt_file} not found")

        with open(prompt_file, "r", encoding="utf-8") as f:
            base_prompt = f.read()

        final_prompt = (
            f"{base_prompt}\n\n"
            f"Resume:\n{resume['content']}\n\n"
            f"Job Description:\n{jd['content']}"
        )

        result = self.getResponse(final_prompt)

        if "error" in result:
            logger.error(f"AI returned error: {result['error']}")
            return self._default_result(result["error"])

        # Save output
        out_path = os.path.join(self.outputsFOLDER,
                                os.path.basename(resumepath) + ".json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4)

        logger.info(f"Analysis saved to {out_path}")
        return result

    # ────────────────────────────────────────────
    #  JOB RECOMMENDATIONS
    # ────────────────────────────────────────────
    @ExceptionHandler
    def getJobRecommendations(self, resume: str) -> Optional[Dict[str, Any]]:
        resume_data = self.documentParser(resume)
        if not resume_data:
            return {}

        prompt = (
            "Based on the resume below, recommend top 5 job roles with a relevance score (0-100).\n"
            "Return ONLY valid JSON like: "
            '{"ROLEMATCHES": [{"role": "Data Scientist", "score": 92}]}\n\n'
            f"Resume:\n{resume_data['content']}"
        )

        result = self.getResponse(prompt)
        if "error" in result:
            return {}

        out_path = os.path.join(self.outputsFOLDER, "JobRecommendations.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4)

        return result

    # ────────────────────────────────────────────
    #  COVER LETTER
    # ────────────────────────────────────────────
    @ExceptionHandler
    def getCoverLetter(self, resumepath: str, jdpath: str) -> str:
        resume = self.documentParser(resumepath)
        jd = self.documentParser(jdpath)

        if not resume or not jd:
            return "Could not generate cover letter — file parsing failed."

        prompt = (
            "Write a professional cover letter for the candidate based on their resume "
            "and the job description below. Return ONLY the cover letter text, no JSON.\n\n"
            f"Resume:\n{resume['content']}\n\n"
            f"Job Description:\n{jd['content']}"
        )

        try:
            return self._chat([{"role": "system", "content": "You are a professional cover letter writer."}, {"role": "user", "content": prompt}], temperature=0.5, max_tokens=1024)
        except Exception as e:
            logger.error(f"Cover letter generation failed: {e}")
            return "Cover letter generation failed. Please try again."

    # ────────────────────────────────────────────
    #  CUSTOM COVER LETTER
    # ────────────────────────────────────────────
    @ExceptionHandler
    def getCustomCoverLetter(self, job_title: str, company_name: str,
                              your_name: str, additional_info: str) -> str:
        prompt = (
            f"Write a professional cover letter for {your_name} applying for the role of "
            f"{job_title} at {company_name}.\n"
            f"Additional info: {additional_info}\n\n"
            "Return ONLY the cover letter text."
        )

        try:
            return self._chat([{"role": "system", "content": "You are a professional cover letter writer."}, {"role": "user", "content": prompt}], temperature=0.5, max_tokens=1024)
        except Exception as e:
            logger.error(f"Custom cover letter failed: {e}")
            return "Cover letter generation failed."

    # ────────────────────────────────────────────
    #  CHATBOT
    # ────────────────────────────────────────────
    @ExceptionHandler
    def chatbot(self, query: str) -> str:
        try:
            return self._chat([{"role": "system", "content": (
                            "You are a helpful career assistant. Help users with resume tips, "
                            "ATS optimization, job search advice, and interview preparation. "
                            "Be concise and friendly."
                        )}, {"role": "user", "content": query}], temperature=0.5, max_tokens=512)
        except Exception as e:
            logger.error(f"Chatbot error: {e}")
            return "Sorry, I'm having trouble right now. Please try again."

    # ────────────────────────────────────────────
    #  PDF CHATBOT
    # ────────────────────────────────────────────
    @ExceptionHandler
    def pdfchatbot(self, filepaths: list, query: str) -> str:
        all_content = []
        for fp in filepaths:
            doc = self.documentParser(fp)
            if doc:
                all_content.append(doc["content"])

        combined = "\n\n".join(all_content)

        prompt = (
            f"Based on the following document(s), answer the user's question.\n\n"
            f"Documents:\n{combined[:6000]}\n\n"  # Limit to avoid token overflow
            f"Question: {query}"
        )

        try:
            return self._chat([{"role": "system", "content": "You are a helpful document assistant."}, {"role": "user", "content": prompt}], temperature=0.3, max_tokens=1024)
        except Exception as e:
            logger.error(f"PDF chatbot error: {e}")
            return "Error processing your documents. Please try again."

    # ────────────────────────────────────────────
    #  SAFE DEFAULT (prevents AttributeError)
    # ────────────────────────────────────────────
    def _default_result(self, error: str = "") -> Dict[str, Any]:
        """Return safe empty result so app.py never gets None."""
        return {
            "ERROR": error,
            "ATS_SCORE": 0,
            "RESUME_RELEVANCE_SCORE": 0,
            "ROLE_FIT_SCORE": 0,
            "KEYWORD_MATCH_SCORE": 0,
            "MATCHED_KEYWORDS": [],
            "MISSING_KEYWORDS": [],
            "MISSING_SKILLS": [],
            "RESUME_TIPS": ["Could not analyze. Please check your files and try again."],
            "COURSE_RECOMMENDATIONS": {}
        }
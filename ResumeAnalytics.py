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
        self.model_name = "llama-3.3-70b-versatile"   # Free, fast, very capable

        self.outputsFOLDER = "outputs"
        os.makedirs(self.outputsFOLDER, exist_ok=True)
        self.model_name = "llama-3.3-70b-versatile"
        self.fallback_model = "llama-3.1-8b-instant"   # ← add this line
        logger.info("Groq (Llama3-70b) model initialized successfully.")

    # ────────────────────────────────────────────
    #  CORE: call AI and always return a dict
    # ────────────────────────────────────────────
    def getResponse(self, prompt: str) -> Dict[str, Any]:
        """Always returns a dict — never None, never a string."""
        try:
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert resume screening assistant. "
                            "Always return ONLY valid JSON — no markdown, no explanation, "
                            "no code fences, just the raw JSON object."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                model=self.model_name,
                temperature=0.3,
                max_tokens=4096,
            )

            text = chat_completion.choices[0].message.content.strip()
            # Strip accidental markdown fences
            text = re.sub(r"^```json|^```|```$", "", text, flags=re.MULTILINE).strip()
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return {"error": "Invalid JSON returned by AI"}
        except Exception as e:
            err = str(e)
            if "decommissioned" in err or "model_decommissioned" in err:
                logger.warning(f"Model decommissioned! Switching to fallback: {self.fallback_model}")
                self.model_name = self.fallback_model
                return self.getResponse(prompt)   # retry once with fallback
            if "429" in err or "rate" in err.lower():
                return {"error": "AI rate limit hit. Please wait a moment and try again."}
            logger.error(f"Groq API error: {e}")
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
            return self._default_result()

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
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a professional cover letter writer."},
                    {"role": "user", "content": prompt},
                ],
                model=self.model_name,
                temperature=0.5,
                max_tokens=1024,
            )
            return chat_completion.choices[0].message.content.strip()
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
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a professional cover letter writer."},
                    {"role": "user", "content": prompt},
                ],
                model=self.model_name,
                temperature=0.5,
                max_tokens=1024,
            )
            return chat_completion.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Custom cover letter failed: {e}")
            return "Cover letter generation failed."

    # ────────────────────────────────────────────
    #  CHATBOT
    # ────────────────────────────────────────────
    @ExceptionHandler
    def chatbot(self, query: str) -> str:
        try:
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a helpful career assistant. Help users with resume tips, "
                            "ATS optimization, job search advice, and interview preparation. "
                            "Be concise and friendly."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                model=self.model_name,
                temperature=0.5,
                max_tokens=512,
            )
            return chat_completion.choices[0].message.content.strip()
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
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a helpful document assistant."},
                    {"role": "user", "content": prompt},
                ],
                model=self.model_name,
                temperature=0.3,
                max_tokens=1024,
            )
            return chat_completion.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"PDF chatbot error: {e}")
            return "Error processing your documents. Please try again."

    # ────────────────────────────────────────────
    #  SAFE DEFAULT (prevents AttributeError)
    # ────────────────────────────────────────────
    def _default_result(self) -> Dict[str, Any]:
        """Return safe empty result so app.py never gets None."""
        return {
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
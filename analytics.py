# analytics.py  (or the file that contains resumeanalytics)
import os
import re

# optional: pip install docx2txt PyPDF2
try:
    import docx2txt
except Exception:
    docx2txt = None

try:
    from PyPDF2 import PdfReader
except Exception:
    PdfReader = None

# small stopwords list to avoid trivial matches
STOPWORDS = {
    "the","and","for","with","this","that","a","an","to","of","in","on","is","are","be","by","as","at","from"
}

def extract_text(path):
    if not path or not os.path.exists(path):
        print("DEBUG: extract_text - file not found:", path)
        return ""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".docx" and docx2txt:
            return docx2txt.process(path) or ""
        if ext == ".pdf" and PdfReader:
            text = ""
            reader = PdfReader(path)
            for page in reader.pages:
                try:
                    ptext = page.extract_text()
                except Exception:
                    ptext = None
                if ptext:
                    text += ptext + "\n"
            return text or ""
        if ext == ".txt":
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        # fallback tries
        if docx2txt:
            try:
                return docx2txt.process(path) or ""
            except Exception:
                pass
        if PdfReader:
            try:
                text = ""
                reader = PdfReader(path)
                for page in reader.pages:
                    ptext = page.extract_text() or ""
                    text += ptext + "\n"
                return text or ""
            except Exception:
                pass
    except Exception as e:
        print("DEBUG: extract_text error for", path, e)
    return ""

def tokenize_words(text):
    return re.findall(r"\b[a-zA-Z0-9+-]+\b", text.lower())

def extract_keywords_jd(jd_text):
    words = tokenize_words(jd_text)
    # filter short words and stopwords, keep order unique
    seen = set()
    keywords = []
    for w in words:
        if len(w) <= 2 or w in STOPWORDS:
            continue
        if w not in seen:
            seen.add(w)
            keywords.append(w)
    return keywords

def simple_ats_score(resume_text, jd_text):
    jd_keywords = extract_keywords_jd(jd_text)
    resume_lower = resume_text.lower()
    matched = []
    for kw in jd_keywords:
        # word boundary match to avoid substring false positives
        if re.search(r"\b" + re.escape(kw) + r"\b", resume_lower):
            matched.append(kw)
    missing = [kw for kw in jd_keywords if kw not in matched]
    score = 0
    if jd_keywords:
        score = int(round(100.0 * len(matched) / len(jd_keywords)))
    return score, matched, missing

def resumeanalytics(resume_path, jd_path):
    # Extract texts
    resume_text = extract_text(resume_path)
    jd_text = extract_text(jd_path)

    print("DEBUG: resume_text length:", len(resume_text))
    print("DEBUG: jd_text length:", len(jd_text))
    print("DEBUG: resume_text (first 300):", (resume_text[:300] if resume_text else "<empty>"))
    print("DEBUG: jd_text (first 300):", (jd_text[:300] if jd_text else "<empty>"))

    # If JD text empty -> return default zeros and a helpful message
    if not jd_text.strip():
        print("DEBUG: No JD text extracted; ATS will be 0. Check parser or JD file.")
        return {
            'ATS_SCORE': 0,
            'RESUME_RELEVANCE_SCORE': 0,
            'ROLE_FIT_SCORE': 0,
            'RESUME_TIPS': [],
            'COURSE_RECOMMENDATIONS': [],
            'MISSING_KEYWORDS': [],
            'MISSING_SKILLS': []
        }

    # compute ATS
    ats_score, matched, missing = simple_ats_score(resume_text, jd_text)
    print("DEBUG: jd_keywords_count =", len(extract_keywords_jd(jd_text)))
    print("DEBUG: matched_keywords_count =", len(matched))
    print("DEBUG: matched_keywords =", matched[:50])
    print("DEBUG: missing_keywords_count =", len(missing))
    print("DEBUG: missing_keywords =", missing[:50])

    return {
        'ATS_SCORE': ats_score,
        'RESUME_RELEVANCE_SCORE': ats_score,  # placeholder / you can change
        'ROLE_FIT_SCORE': ats_score,          # placeholder
        'RESUME_TIPS': [],                    # can populate later
        'COURSE_RECOMMENDATIONS': [],
        'MISSING_KEYWORDS': missing,
        'MISSING_SKILLS': []
    }
    print("DEBUG: Final ATS Score =", ats_score)
    print("DEBUG: Final RRS Score =", rrs_score)
    print("DEBUG: Final RFS Score =", rfs_score)
    
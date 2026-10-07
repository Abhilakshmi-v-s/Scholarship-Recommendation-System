import sqlite3
import re
from datetime import date

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _to_float(x, default=0.0):
    try:
        return float(str(x).strip())
    except Exception:
        return default


def _to_int(x, default=0):
    try:
        return int(float(str(x).strip()))
    except Exception:
        return default


def _clean_text(s: str) -> str:
    s = str(s or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_deadline(deadline_str: str):
    if not deadline_str:
        return None
    try:
        d = pd.to_datetime(deadline_str, errors="coerce", dayfirst=True)
        if pd.isna(d):
            return None
        return d.date()
    except Exception:
        return None


def _category_matches(student_cat: str, sch_cat: str) -> bool:
    student_cat = (student_cat or "General").strip().lower()
    sch_cat = (sch_cat or "All").strip().lower()

    if sch_cat in ("all", "general", ""):
        return True
    if student_cat == sch_cat:
        return True
    if sch_cat == "sc/st" and student_cat in ("sc", "st", "sc/st"):
        return True
    return False


def recommend_scholarships(profile: dict, db_path: str = "scholarships.db", top_n=None):
    """
    top_n=None => return all matches
    """

    course = (profile.get("course") or "").strip()
    specialization = (profile.get("specialization") or "").strip()
    category = (profile.get("category") or "General").strip()
    state = (profile.get("state") or "").strip()
    skills = (profile.get("skills") or "").strip()
    gender = (profile.get("gender") or "").strip()

    cgpa = _to_float(profile.get("cgpa"), 0.0)
    income = _to_float(profile.get("income"), 999999999)

    student_text = _clean_text(
        f"course {course} specialization {specialization} "
        f"category {category} state {state} cgpa {cgpa} "
        f"income {income} skills {skills} gender {gender}"
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, amount, deadline, provider, description, eligibility,
               category, min_cgpa, max_income, state, course, raw_url
        FROM scholarships
    """)
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return []

    items = [dict(r) for r in rows]

    today = date.today()
    active = []
    for s in items:
        d = _parse_deadline(s.get("deadline", ""))
        if d is not None and d < today:
            continue
        active.append(s)

    if not active:
        active = items

    eligible = []
    for s in active:
        min_cgpa = _to_float(s.get("min_cgpa"), 0.0)
        max_income = _to_float(s.get("max_income"), 999999999)

        if cgpa > 0 and cgpa < min_cgpa:
            continue

        if income < 999999999 and income > max_income:
            continue

        sch_cat = (s.get("category") or "All").strip()
        sch_state = (s.get("state") or "All").strip()
        sch_course = (s.get("course") or "All").strip()

        if not _category_matches(category, sch_cat):
            continue

        if sch_state.lower() not in ("all", ""):
            if state and state.lower() != sch_state.lower():
                continue

        if sch_course.lower() not in ("all", ""):
            if course and course.lower() not in sch_course.lower():
                continue

        eligible.append(s)

    if not eligible:
        return []

    docs = []
    for s in eligible:
        sch_text = _clean_text(
            f"{s.get('title', '')} {s.get('provider', '')} "
            f"{s.get('description', '')} {s.get('eligibility', '')} "
            f"category {s.get('category', '')} state {s.get('state', '')} "
            f"course {s.get('course', '')}"
        )
        docs.append(sch_text)

    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)
    tfidf = vectorizer.fit_transform([student_text] + docs)
    sims = cosine_similarity(tfidf[0:1], tfidf[1:]).flatten()

    for i, s in enumerate(eligible):
        s["score"] = float(sims[i])

    eligible.sort(
        key=lambda x: (round(x.get("score", 0.0), 3), _to_int(x.get("amount", 0))),
        reverse=True
    )

    if top_n is None or top_n <= 0:
        return eligible

    return eligible[:top_n]
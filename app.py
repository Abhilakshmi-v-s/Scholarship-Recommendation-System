import os
import re
import sqlite3
from datetime import datetime
from functools import wraps

import pandas as pd
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash

from nlp_engine import recommend_scholarships


# ============================================================
# App + Paths
# ============================================================
app = Flask(__name__)
app.secret_key = "change-this-secret-key"

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "scholarships.db")
CSV_PATH = os.path.join(BASE_DIR, "scholarships.csv")


# ============================================================
# DB Helpers
# ============================================================
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn, table: str, col: str) -> bool:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    return col in cols


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Scholarships table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scholarships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            amount INTEGER,
            deadline TEXT,
            provider TEXT,
            description TEXT,
            eligibility TEXT,
            category TEXT DEFAULT 'All',
            min_cgpa REAL DEFAULT 1.0,
            max_income INTEGER DEFAULT 999999999,
            state TEXT DEFAULT 'All',
            course TEXT DEFAULT 'All',
            raw_url TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Student profiles table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS student_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT UNIQUE NOT NULL,
            full_name TEXT,
            phone TEXT,
            gender TEXT,
            dob TEXT,
            state TEXT,
            category TEXT,
            course TEXT,
            specialization TEXT,
            college TEXT,
            year_of_study TEXT,
            cgpa REAL,
            income REAL,
            skills TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Activity table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT,
            activity_type TEXT,
            scholarship_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Safety migration
    if not _column_exists(conn, "scholarships", "raw_url"):
        cur.execute("ALTER TABLE scholarships ADD COLUMN raw_url TEXT DEFAULT ''")

    if not _column_exists(conn, "scholarships", "description"):
        cur.execute("ALTER TABLE scholarships ADD COLUMN description TEXT DEFAULT ''")

    if not _column_exists(conn, "scholarships", "max_income"):
        cur.execute("ALTER TABLE scholarships ADD COLUMN max_income INTEGER DEFAULT 999999999")

    if not _column_exists(conn, "scholarships", "course"):
        cur.execute("ALTER TABLE scholarships ADD COLUMN course TEXT DEFAULT 'All'")

    if not _column_exists(conn, "scholarships", "category"):
        cur.execute("ALTER TABLE scholarships ADD COLUMN category TEXT DEFAULT 'All'")

    if not _column_exists(conn, "scholarships", "state"):
        cur.execute("ALTER TABLE scholarships ADD COLUMN state TEXT DEFAULT 'All'")

    if not _column_exists(conn, "scholarships", "min_cgpa"):
        cur.execute("ALTER TABLE scholarships ADD COLUMN min_cgpa REAL DEFAULT 1.0")

    conn.commit()
    conn.close()


def import_csv_to_db_if_empty(csv_path: str):
    """
    Imports scholarships from CSV into DB ONLY if scholarships table is empty.
    """
    if not os.path.exists(csv_path):
        print(f"⚠️ CSV not found: {csv_path}")
        return

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS c FROM scholarships")
    if cur.fetchone()["c"] > 0:
        conn.close()
        return

    df = pd.read_csv(csv_path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    for _, r in df.iterrows():
        title = str(r.get("name", "")).strip()
        provider = str(r.get("provider", "")).strip()
        deadline = str(r.get("deadline", "")).strip()
        eligibility = str(r.get("eligibility", "")).strip()
        course = str(r.get("course", "All")).strip() or "All"
        category = str(r.get("category", "All")).strip() or "All"
        state = str(r.get("state", "All")).strip() or "All"
        raw_url = str(r.get("application_link", "")).strip()
        description = str(r.get("description", "")).strip()

        if not title:
            continue

        try:
            amount = int(float(str(r.get("amount", 0)).replace(",", "").strip() or 0))
        except Exception:
            amount = 0

        try:
            min_cgpa = float(r.get("min_cgpa", 1.0) or 1.0)
        except Exception:
            min_cgpa = 1.0
        min_cgpa = max(1.0, min(10.0, min_cgpa))

        try:
            max_income = int(float(str(r.get("max_income", 999999999)).replace(",", "").strip() or 999999999))
        except Exception:
            max_income = 999999999

        cur.execute("""
            INSERT INTO scholarships
            (title, amount, deadline, provider, description, eligibility,
             category, min_cgpa, max_income, state, course, raw_url, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            title,
            amount,
            deadline,
            provider,
            description,
            eligibility,
            category,
            min_cgpa,
            max_income,
            state,
            course,
            raw_url,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

    conn.commit()
    conn.close()
    print("✅ Scholarships imported from CSV into database.")


# ============================================================
# Student Profile Save / Load
# ============================================================
def to_float(value, default=0.0):
    try:
        return float(str(value).strip())
    except Exception:
        return default


def save_student_profile(user_email, profile):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id FROM student_profiles WHERE user_email=?", (user_email,))
    existing = cur.fetchone()

    full_name = profile.get("full_name", "").strip()
    phone = profile.get("phone", "").strip()

    if phone and not re.fullmatch(r"\d{10}", phone):
        raise ValueError("Phone number must be exactly 10 digits.")

    gender = profile.get("gender", "").strip()
    dob = profile.get("dob", "").strip()
    state = profile.get("state", "").strip()
    category = profile.get("category", "").strip()
    course = profile.get("course", "").strip()
    specialization = profile.get("specialization", "").strip()
    college = profile.get("college", "").strip()
    year_of_study = profile.get("year_of_study", "").strip()
    cgpa = to_float(profile.get("cgpa", 0))
    income = to_float(profile.get("income", 0))
    skills = profile.get("skills", "").strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if existing:
        cur.execute("""
            UPDATE student_profiles
            SET full_name=?, phone=?, gender=?, dob=?, state=?, category=?, course=?,
                specialization=?, college=?, year_of_study=?, cgpa=?, income=?,
                skills=?, updated_at=?
            WHERE user_email=?
        """, (
            full_name, phone, gender, dob, state, category, course,
            specialization, college, year_of_study, cgpa, income,
            skills, now, user_email
        ))
    else:
        cur.execute("""
            INSERT INTO student_profiles
            (user_email, full_name, phone, gender, dob, state, category, course,
             specialization, college, year_of_study, cgpa, income, skills, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_email, full_name, phone, gender, dob, state, category, course,
            specialization, college, year_of_study, cgpa, income, skills, now
        ))

    conn.commit()
    conn.close()


def get_student_profile(user_email):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM student_profiles WHERE user_email=?", (user_email,))
    row = cur.fetchone()
    conn.close()
    return row


# ============================================================
# Decorators
# ============================================================
def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if "user_email" not in session:
            flash("Please login first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrap


# ============================================================
# Routes
# ============================================================
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not fullname or not email or not password:
            flash("All fields are required.", "error")
            return redirect(url_for("register"))

        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("register"))

        if not re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", email):
            flash("Enter a valid email address.", "error")
            return redirect(url_for("register"))

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email=?", (email,))
        if cur.fetchone():
            conn.close()
            flash("Email already registered. Please login.", "warning")
            return redirect(url_for("login"))

        cur.execute("""
            INSERT INTO users (name, email, password_hash)
            VALUES (?, ?, ?)
        """, (fullname, email, generate_password_hash(password)))

        conn.commit()
        conn.close()

        flash("Registered successfully! Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email=?", (email,))
        user = cur.fetchone()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]

        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    saved_profile = get_student_profile(session["user_email"])
    return render_template(
        "dashboard.html",
        user_name=session.get("user_name", "Student"),
        user_email=session.get("user_email", ""),
        saved_profile=saved_profile
    )


@app.route("/recommendations", methods=["GET", "POST"])
@login_required
def recommendations_page():
    # Back to Matches should show last results, not dashboard
    if request.method == "GET":
        last_results = session.get("last_results", [])
        if last_results:
            return render_template("recommendations.html", results=last_results)

        flash("Fill your profile and click Get Recommendations.", "info")
        return redirect(url_for("dashboard"))

    profile = request.form.to_dict()

    try:
        save_student_profile(session["user_email"], profile)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("dashboard"))

    session["last_profile"] = profile

    try:
        results = recommend_scholarships(profile, db_path=DB_PATH, top_n=None)
    except Exception as e:
        print("Recommendation error:", e)
        results = []

    # Save results in session so Back to Matches works
    session["last_results"] = [dict(r) if hasattr(r, "keys") else dict(r) for r in results]

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_activity (user_email, activity_type)
        VALUES (?, 'search')
    """, (session["user_email"],))
    conn.commit()
    conn.close()

    if not results:
        flash("No scholarships matched your profile.", "warning")

    return render_template("recommendations.html", results=results)


@app.route("/scholarship/<int:sch_id>")
@login_required
def scholarship_detail(sch_id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, amount, deadline, provider, description, eligibility,
               category, min_cgpa, max_income, state, course, raw_url
        FROM scholarships
        WHERE id = ?
    """, (sch_id,))
    sch = cur.fetchone()

    if sch:
        cur.execute("""
            INSERT INTO user_activity (user_email, activity_type, scholarship_id)
            VALUES (?, 'view', ?)
        """, (session["user_email"], sch_id))
        conn.commit()

    conn.close()

    if not sch:
        flash("Scholarship not found.", "error")
        return redirect(url_for("recommendations_page"))

    score = request.args.get("score", "")
    student = session.get("last_profile", {})

    return render_template("scholarship_detail.html", sch=sch, score=score, student=student)


# ============================================================
# Run
# ============================================================
if __name__ == "__main__":
    init_db()
    import_csv_to_db_if_empty(CSV_PATH)
    app.run(debug=True)
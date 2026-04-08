# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AnalysisResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), nullable=False)
    resume_path = db.Column(db.String(200))
    jd_path = db.Column(db.String(200))
    ats_score = db.Column(db.Integer)
    rrs_score = db.Column(db.Integer)
    rfs_score = db.Column(db.Integer)
    matched_keywords = db.Column(db.Text)
    missing_keywords = db.Column(db.Text)
    course_recommendations = db.Column(db.Text)
    raw_result_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
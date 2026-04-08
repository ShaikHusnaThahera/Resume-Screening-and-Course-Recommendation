# create_db.py
from app import db, app

with app.app_context():  # ensure Flask app context
    db.create_all()
    print("DB created: resume_analyzer.db")
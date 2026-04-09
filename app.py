from flask import Flask, render_template, request, jsonify, make_response, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, AnalysisResult
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
import os
import time
import json
import tempfile
import analytics
import pdfkit
import webbrowser
from threading import Timer
from ResumeAnalytics import ResumeAnalytics
from markdown2 import markdown
import re
import shutil
app = Flask(__name__)
app.secret_key="hr@34428"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///resume_analyzer.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
# models.py

users = {}


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return redirect(url_for('login'))
        
        
        new_user = User(name=name, email=email, password=password)
        db.session.add(new_user)
        db.session.commit()
        flash('Signup successfully! Please login', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.name
            flash("Login Successfully!")
            return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.','info')
    return redirect(url_for('login'))




UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt', 'doc', 'jpeg', 'jpg', 'png', 'webp'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Max 16MB
wkhtmltopdf_path = shutil.which('wkhtmltopdf') or r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'
config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

resume_analytics = ResumeAnalytics()
shared_data = {}  


@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'username' not in session:
        flash('Please login first', 'warning')
        return redirect(url_for('login'))

    username = session.get('username','anonymus')
    resume_filename = jd_filename = None
    show_dashboard = False

    ats_score = rrs_score = rfs_score = None
    total_ats_score = breakdown = None
    resume_components = {}
    missing_keywords = missing_skills = None
    resume_tips = course_recommendations = None

    if request.method == 'POST':
        resume = request.files.get('resume')
        jd = request.files.get('jd')
        resume_path = jd_path = None

        if resume and allowed_file(resume.filename):
            resume_filename = secure_filename(resume.filename)
            resume_path = os.path.join(app.config['UPLOAD_FOLDER'], resume_filename)
            resume.save(resume_path)

        if jd and allowed_file(jd.filename):
            jd_filename = secure_filename(jd.filename)
            jd_path = os.path.join(app.config['UPLOAD_FOLDER'], jd_filename)
            jd.save(jd_path)
            print(f"[DEBUG] Job description uploaded: {jd_filename}")
        
        rolematch = resume_analytics.getJobRecommendations(resume_path)
        print(f"[DEBUG] Raw rolematch: {rolematch}")
        
        if isinstance(rolematch, dict):
            if 'ROLEMATCHES' in rolematch:
                raw = rolematch['ROLEMATCHES']
                if isinstance(raw, list):
                    shared_data['rolematch'] = {
                        item.get('role', f'Role {i+1}'): item.get('score', 0)
                        for i, item in enumerate(raw)
                        if isinstance(item, dict)
                    }
                else:
                    shared_data['rolematch'] = raw
            else:
                if isinstance(rolematch, list):
                    shared_data['rolematch'] = {
                        item.get('role', f'Role {i+1}'): item.get('score', 0)
                        for i, item in enumerate(rolematch)
                        if isinstance(item, dict)
                    }
                else:
                    shared_data['rolematch'] = rolematch
        else:
            shared_data['rolematch'] = {}

        result = resume_analytics.resumeanalytics(resume_path, jd_path)
        print("DEBUG: resume_path =", resume_path)
        print("DEBUG: jd_path     =", jd_path)
        print("DEBUG: result type =", type(result))
        print("DEBUG: result repr =", repr(result)[:1000])
        
        username = session.get('username', 'anonymous')
        
        
        new_result = AnalysisResult(
            username = username,
            resume_path =resume_path or '',
            jd_path =jd_path or '',
            ats_score = int(result.get('ATS_SCORE', 0)),
            rrs_score = int(result.get('RESUME_RELEVANCE_SCORE', 0)),
            rfs_score = int(result.get('ROLE_FIT_SCORE', 0)),
            matched_keywords = json.dumps(result.get('MATCHED_KEYWORDS', [])),
            missing_keywords = json.dumps(result.get('MISSING_KEYWORDS', [])),
            course_recommendations = json.dumps(result.get('COURSE_RECOMMENDATIONS', [])),
            raw_result_json = json.dumps(result)
        )
        db.session.add(new_result)
        db.session.commit()
        
        
        if isinstance(result, dict):
            print("DEBUG: result keys =", list(result.keys()))
            print("DEBUG: ATS_SCORE raw=", result.get('ATS_SCORE'))
        global coverletterdata
        coverletterdata = resume_analytics.getCoverLetter(resume_path, jd_path)
        if jd_path and resume_path:
            cover_letter = resume_analytics.getCoverLetter(resume_path, jd_path)
            if isinstance(cover_letter,str) and cover_letter.strip():
                shared_data['cover_letter'] = cover_letter
                shared_data['cover_letter_preview'] = cover_letter[:150] + "..." if len(cover_letter) > 150 else cover_letter
            else:
                shared_data['cover_letter']=""
                shared_data['cover_letter_preview']="No cover letter available."    
        if result is None:
            return render_template('DASHBOARD.html', error="Error in analysis. Please try again.")

        ats_score = result.get('ATS_SCORE')
        rrs_score = result.get('RESUME_RELEVANCE_SCORE')
        rfs_score = result.get('ROLE_FIT_SCORE')
        resume_tips = result.get('RESUME_TIPS', [])
        course_recommendations = result.get('COURSE_RECOMMENDATIONS', {})

        missing_keywordslist = result.get('MISSING_KEYWORDS', [])
        missing_skillslist = result.get('MISSING_SKILLS', [])
        missing_keywords = len(missing_keywordslist)
        missing_skills = len(missing_skillslist)

        # Store in shared_data
        shared_data['missing_keywords'] = missing_keywordslist
        shared_data['missing_skills'] = missing_skillslist
        shared_data['resume_tips'] = resume_tips  
        shared_data['course_recommendations'] = course_recommendations


        print("[DEBUG] Course Recommendations:", course_recommendations)
        atsresult = result   # <--- assign it here
        print("ATSRESULT ===", atsresult)
        if atsresult is None:
            return render_template('DASHBOARD.html', error="Error in ATS analysis. Please try again.")
        if isinstance(atsresult, str):
            try:
                atsresult = json.loads(atsresult)
            except json.JSONDecodeError:
                atsresult = {}
        resume_components = atsresult.get('Extracted Data', {})
        ats_score_data = atsresult.get('ATS Score', {})
        total_ats_score = ats_score_data.get('Total Score')
        breakdown = ats_score_data.get('Breakdown', {})
        shared_data['ats_tips'] = atsresult.get('Recommendations', [])

        show_dashboard = True

        return render_template('DASHBOARD.html',
                               username=username,
                               resume_filename=resume_filename,
                               jd_filename=jd_filename,
                               show_dashboard=show_dashboard,
                               ats_score=ats_score,
                               total_ats_score=total_ats_score,
                               breakdown=breakdown,
                               rrs_score=rrs_score,
                               rfs_score=rfs_score,
                               resume_components=resume_components,
                               missing_keywords=missing_keywordslist,
                               missing_skills=missing_skillslist,
                               missing_keywords_count=len(missing_keywordslist),
                               missing_skills_count=len(missing_skillslist),
                               resume_tips=resume_tips,
                               course_recommendations=course_recommendations)

    return render_template('DASHBOARD.html', username=session.get('username','anonymous'))


@app.route('/chatbot', methods=['POST'])
def chatbot_route():
    data = request.get_json()
    user_query = data.get('query')

    if not user_query:
        return jsonify({'response': 'Please enter a valid message.'})

    try:
        resume_analytics_local = ResumeAnalytics() 
        response = resume_analytics_local.chatbot(query=user_query) 
        return jsonify({'response': response})
    except Exception as e:
        print("Error:", e)
        return jsonify({'response': 'Server busy, please try again later.'})


@app.route('/resume-insights')
def show_course_recommendations():
    missing_technical_skills = shared_data.get('missing_keywords', [])
    missing_soft_skills = shared_data.get('missing_skills', [])
    default_resume_tips= [
        "Use clear section headings like Education, Skills, and Experience.","Keep your resume concise(1-2) pages.","Include keywords from the job description.","Highlight measurable achievements(. g., 'Increased sales by 20%).","Avoid excessive graphics or tables -ATS may not parse them."
    ]
    courseRecommendations = shared_data.get('course_recommendations', {})

    cover_letter_preview = shared_data.get(
        'cover_letter_preview',
        'No cover letter available. Please upload resume and job description to generate one.'
    )
    print("[DEBUG] Course Recommendations:", courseRecommendations)
    print("[DEBUG] Cover Letter Preview:", cover_letter_preview)

    
    resume_tips = shared_data.get('resume_tips', []) + shared_data.get('ats_tips', [])
    import random
    random.shuffle(resume_tips)
    resume_tips_html = [markdown(tip) for tip in resume_tips]
    role_matches = shared_data.get('rolematch', {})
    print("[DEBUG] Role Matches:", role_matches)
    # Render the page
    return render_template(
        'course_recommendations.html',
        missing_technical_skills=missing_technical_skills,
        missing_soft_skills=missing_soft_skills,
        role_matches=role_matches,
        resume_tips=resume_tips_html,
        cover_letter_preview=cover_letter_preview
    )


@app.route('/course-recommendations')
def courseRecommendations():
    raw_course_data = shared_data.get('course_recommendations', {})
    
    paid_course_recommendations = {}
    youtube_course_recommendations = {}

    # Separate YouTube vs paid platforms
    for topic, courses in raw_course_data.items():
        paid_courses = []
        youtube_courses = []

        for course in courses:
            if course['PLATFORM'].lower() == 'youtube':
                youtube_courses.append(course)
            else:
                paid_courses.append(course)

        if paid_courses:
            paid_course_recommendations[topic] = paid_courses
        if youtube_courses:
            youtube_course_recommendations[topic] = youtube_courses 

    return render_template(
        'recommendations.html',  # Make sure this matches your template file name
        paid_course_recommendations=paid_course_recommendations,
        youtube_course_recommendations=youtube_course_recommendations
    )

# === Helper Function ===
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# === Routes ===
current_documents = []  
@app.route('/PDFChatbot', methods=['GET', 'POST'])
def PDFChatbot():
    global current_documents
    
    if request.method == 'POST':
       
        uploaded_files = request.files.getlist('documents')
        query = request.form.get('query', '').strip()
        
        new_files = []
        for file in uploaded_files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                if filepath not in current_documents:  # Avoid duplicates
                    new_files.append(filepath)
        
        current_documents.extend(new_files)  # Add new files to global list
        
        if not query and current_documents:
            query = "Please analyze my resume."
        elif not query:
            return jsonify({"response": "Please upload a resume or ask a question."})
        
        try:
            response = resume_analytics.pdfchatbot(current_documents, query)
            return jsonify({"response": response})
        except Exception as e:
            app.logger.error(f"Error in PDFChatbot: {str(e)}")
            return jsonify({"response": "Error processing request. Please try again."}), 500
    
    return render_template('chatbot.html')

@app.route('/remove-file', methods=['POST'])
def remove_file():
    global current_documents
    data = request.get_json()
    filename = data.get('filename')
    
    if filename in current_documents:
        current_documents.remove(filename)
        try:
            os.remove(filename)
        except OSError:
            pass
    
    return jsonify({"status": "success"})

@app.route('/api/download-cover-letter', methods=['GET'])  # Match the frontend URL and method
def download_cover_letter():
    try:
        global coverletterdata
        cover_letter_text = coverletterdata
        response = make_response(cover_letter_text)
        response.headers['Content-Type'] = 'text/plain'
        response.headers['Content-Disposition'] = 'attachment; filename=CoverLetter.txt'
        return response
    except Exception as e:
        return str(e), 500

@app.route('/customcoverletter', methods=['GET', 'POST'])
def custom_cover_letter():
    if request.method == 'POST':
        # Check if this is a PDF generation request
        if 'html' in request.form:
            html_content = request.form.get('html')
            
            # Create a temporary file
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as output:
                pdfkit.from_string(html_content, output.name)
                output.seek(0)
                
                response = make_response(output.read())
                response.headers['Content-Type'] = 'application/pdf'
                response.headers['Content-Disposition'] = 'attachment; filename=cover_letter.pdf'
                
                # Clean up
                os.unlink(output.name)
                
                return response
        
        # Normal cover letter generation
        job_title = request.form.get('jobTitle')
        company_name = request.form.get('companyName')
        your_name = request.form.get('yourName')
        additional_info = request.form.get('coverLetterContent')

        cover_letter_content = resume_analytics.getCustomCoverLetter(
            job_title, company_name, your_name, additional_info
        )

        if cover_letter_content.startswith('{'):
            try:
                data = json.loads(cover_letter_content)
                if 'cover_letter' in data:
                    cover_letter_content = data['cover_letter']
            except json.JSONDecodeError:
                pass

        return render_template("Cover letter.html", 
                            generated=True,
                            letter_content=cover_letter_content)
    
    return render_template("Cover letter.html", generated=False)
@app.route('/mock-interview', methods=['GET', 'POST'])
def mock_interview():
    if 'username' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        data = request.get_json()
        action = data.get('action')

        if action == 'get_questions':
            role = data.get('role', 'Software Developer')
            prompt = f"""Generate exactly 5 interview questions for {role}.
Return ONLY a JSON array:
["Question 1?", "Question 2?", "Question 3?", "Question 4?", "Question 5?"]"""
            try:
                result = resume_analytics.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=resume_analytics.model_name,
                    max_tokens=500, temperature=0.7,
                )
                text = result.choices[0].message.content.strip()
                text = re.sub(r"^```json|^```|```$", "", text, flags=re.MULTILINE).strip()
                questions = json.loads(text)
                return jsonify({"questions": questions})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        elif action == 'evaluate_answer':
            question = data.get('question', '')
            answer = data.get('answer', '')
            role = data.get('role', 'Software Developer')
            prompt = f"""You are an expert interviewer for {role}.
Evaluate this answer and return ONLY valid JSON:
Question: {question}
Answer: {answer}
Return exactly:
{{
  "score": number 0-10,
  "verdict": "Excellent/Good/Average/Needs Improvement",
  "strengths": "what was good in 1-2 sentences",
  "improvements": "what to improve in 1-2 sentences",
  "ideal_answer": "brief ideal answer in 2-3 sentences"
}}"""
            try:
                result = resume_analytics.client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model=resume_analytics.model_name,
                    max_tokens=600, temperature=0.3,
                )
                text = result.choices[0].message.content.strip()
                text = re.sub(r"^```json|^```|```$", "", text, flags=re.MULTILINE).strip()
                feedback = json.loads(text)
                return jsonify({"feedback": feedback})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    return render_template('mock_interview.html')

@app.route('/')
def landing_page():
    return render_template('Landing Page.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
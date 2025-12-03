import os
import re
import json
import pandas as pd
import pdfplumber
import google.generativeai as genai
from docx import Document
from PIL import Image
import pytesseract
from flask import Flask, render_template, request, redirect, url_for, send_file, session
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# ==========================================
# CONFIGURATION
# ==========================================
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'docx', 'png', 'jpg', 'jpeg', 'webp'}

os.environ["GOOGLE_API_KEY"] = "AIzaSyAAx0Jdk3BBnseO_FJ1UndkNg3S1KEDxIw"
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

model = genai.GenerativeModel('gemini-2.5-flash')

app = Flask(__name__)
app.secret_key = "supersecretkey123"     # <-- REQUIRED FOR LOGIN SYSTEM
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///resumes.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==========================================
# DATABASE MODEL
# ==========================================
class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(150))
    name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    college = db.Column(db.String(200))
    degree = db.Column(db.String(100))
    department = db.Column(db.String(100))
    state = db.Column(db.String(50))
    district = db.Column(db.String(50))
    year_passing = db.Column(db.String(20))
    location = db.Column(db.String(100)) 
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()
    print("Database tables created successfully!")

# ==========================================
# PDF/DOCX PARSING (REGEX)
# ==========================================
def extract_text_traditional(file_path):
    ext = file_path.rsplit('.', 1)[1].lower()
    text = ""
    try:
        if ext == 'pdf':
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
        elif ext == 'docx':
            doc = Document(file_path)
            text = "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        print(f"Error reading document: {e}")
    return text

def extract_name(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines[:10]:
        if re.match(r'^[A-Z][A-Z\s\.]{2,}$', line): return line.title()
        if re.match(r'^[A-Z]\.?( )?[A-Z][a-zA-Z]+$', line): return line.title()
        if re.match(r'^[A-Z][a-zA-Z]+ [A-Z][a-zA-Z]+$', line): return line.strip()
    return "Not Specified"

def extract_email(text):
    m = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    return m.group(0) if m else "Not Specified"

def extract_phone(text):
    m = re.search(r'\b(?:\+?91)?\s*\d{10}\b', text)
    return m.group(0) if m else "Not Specified"

def extract_college(text):
    m = re.search(r'([A-Za-z ]+(University|Institute|College))', text, re.IGNORECASE)
    return m.group(0).strip() if m else "Not Specified"

def extract_degree(text):
    patterns = [r'b\.?tech', r'b\.?e', r'm\.?tech', r'm\.?e', r'bachelor', r'master']
    for p in patterns:
        match = re.search(p, text, re.IGNORECASE)
        if match: return match.group(0).upper()
    return "Not Specified"

def extract_department(text):
    patterns = [
        r"electronics and communication", r"computer science", r"information technology",
        r"electrical and electronics", r"mechanical engineering", r"civil engineering", 
        r"artificial intelligence", r"data science", r"ECE", r"CSE", r"IT", r"EEE", r"MECH"
    ]
    for p in patterns:
        if re.search(p, text, re.IGNORECASE): return p.title()
    return "Not Specified"

def extract_year_of_passing(text):
    matches = re.findall(r'(?:20\d{2})[\s\-\–]+(\d{2,4})', text)
    if matches: return max(matches)
    return "Not Specified"

def parse_with_regex(filepath):
    raw_text = extract_text_traditional(filepath)
    raw_text = raw_text.replace("■", "").replace("●", "")
    return {
        "Name": extract_name(raw_text),
        "Email": extract_email(raw_text),
        "Phone": extract_phone(raw_text),
        "College": extract_college(raw_text),
        "Degree": extract_degree(raw_text),
        "Department": extract_department(raw_text),
        "Year": extract_year_of_passing(raw_text),
        "Location": "Not Specified (Regex)"
    }

# ==========================================
# IMAGE PARSING (GEMINI)
# ==========================================
def parse_with_gemini(file_path):
    try:
        img = Image.open(file_path)

        prompt = """
        You are an expert Resume Parser. Analyze this resume image and extract:
        Name, Contact, Email, College, Degree, Department, Location, Passed Out.
        Return ONLY clean JSON.
        """

        response = model.generate_content([prompt, img])
        clean_text = response.text.strip()

        if clean_text.startswith("```json"): clean_text = clean_text[7:]
        if clean_text.endswith("```"): clean_text = clean_text[:-3]

        data = json.loads(clean_text)

        return {
            "Name": data.get("Name", "Not Specified"),
            "Email": data.get("Email", "Not Specified"),
            "Phone": data.get("Contact", "Not Specified"),
            "College": data.get("College", "Not Specified"),
            "Degree": data.get("Degree", "Not Specified"),
            "Department": data.get("Department", "Not Specified"),
            "Year": data.get("Passed Out", "Not Specified"),
            "Location": data.get("Location", "Not Specified")
        }

    except Exception as e:
        print(f"Gemini Error: {e}")
        return None

# ==========================================
# AUTH ROUTES (ADMIN LOGIN)
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == "admin" and request.form.get('password') == "admin123":
            session['admin'] = True
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Invalid username or password")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('login'))

# ==========================================
# ROUTES
# ==========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'files[]' not in request.files:
        return redirect(request.url)

    files = request.files.getlist('files[]')

    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            ext = filename.rsplit('.', 1)[1].lower()
            data = None

            if ext in ['pdf', 'docx']:
                data = parse_with_regex(filepath)
            else:
                data = parse_with_gemini(filepath)

            if data:
                new_candidate = Candidate(
                    filename=filename,
                    name=data.get('Name'),
                    email=data.get('Email'),
                    phone=data.get('Phone'),
                    college=data.get('College'),
                    degree=data.get('Degree'),
                    department=data.get('Department'),
                    year_passing=data.get('Year'),
                    location=data.get('Location'),
                    state="Not Specified",
                    district="Not Specified"
                )
                db.session.add(new_candidate)

    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if 'admin' not in session:
        return redirect(url_for('login'))

    candidates = Candidate.query.order_by(Candidate.upload_date.desc()).all()
    return render_template('dashboard.html', candidates=candidates)

@app.route('/export/excel')
def export_excel():
    if 'admin' not in session:
        return redirect(url_for('login'))

    candidates = Candidate.query.all()
    data = [{
        "Name": c.name,
        "Contact": c.phone,
        "Email": c.email,
        "Degree": c.degree,
        "Department": c.department,
        "College": c.college,
        "Location": c.location,
        "Passed Out": c.year_passing,
        "File Name": c.filename
    } for c in candidates]

    df = pd.DataFrame(data)
    filename = "Resume_Data.xlsx"
    df.to_excel(filename, index=False)
    return send_file(filename, as_attachment=True)

# ==========================================
# RUN
# ==========================================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

import os
import pandas as pd
import random
import urllib.parse
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
app.secret_key = "hemlig_nyckel_för_sessioner"

# --- DATABAS KOPPLING ---
db_password = os.environ.get("DB_PASSWORD")

if not db_password:
    print("VARNING: Inget lösenord (testläge)")
    db_password = "" 

server_name = "sql-thomas-quiz" # <--- OBS: ÄNDRA TILL DITT NAMN IGEN OM DU RÅKAT SUDDA DET

connection_string = f"Driver={{ODBC Driver 17 for SQL Server}};Server=tcp:{server_name}.database.windows.net,1433;Database=quizdb;Uid=dbadmin;Pwd={db_password};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

quoted = urllib.parse.quote_plus(connection_string)
app.config['SQLALCHEMY_DATABASE_URI'] = f"mssql+pyodbc:///?odbc_connect={quoted}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- NY DATABASSTRUKTUR (One-to-Many) ---

class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    # Relation till frågorna
    questions = db.relationship('Question', backref='quiz', lazy=True, cascade="all, delete-orphan")

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.String(500), nullable=False)
    answer_text = db.Column(db.String(200), nullable=False)
    # Koppling till Quiz-tabellen
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)

class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    quiz_name = db.Column(db.String(100), nullable=False) # Vi sparar vilket quiz de gjorde
    date_taken = db.Column(db.DateTime, default=datetime.now)

# Skapa tabellerna automatiskt om de inte finns
with app.app_context():
    db.create_all()

# --- NY LOGIK FÖR ROUTES ---

@app.route('/')
def index():
    # Hämta alla quiz och senaste resultat
    try:
        quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
        recent_results = Result.query.order_by(Result.date_taken.desc()).limit(5).all()
        return render_template('index.html', quizzes=quizzes, results=recent_results)
    except:
        # Om tabellerna inte finns än (första körningen)
        return render_template('index.html', quizzes=[], results=[])

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        quiz_name = request.form.get('quiz_name')
        file = request.files['file']
        
        if file and quiz_name:
            try:
                # 1. Skapa Quizet
                new_quiz = Quiz(name=quiz_name)
                db.session.add(new_quiz)
                db.session.flush() # Få ett ID direkt

                # 2. Läs CSV och skapa frågor kopplade till ID:t
                df = pd.read_csv(file)
                for index, row in df.iterrows():
                    new_q = Question(
                        question_text=str(row['Fråga']), 
                        answer_text=str(row['Svar']),
                        quiz_id=new_quiz.id
                    )
                    db.session.add(new_q)
                
                db.session.commit()
                flash(f"Quizet '{quiz_name}' skapat!", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Fel vid uppladdning: {e}", "error")
            return redirect(url_for('index'))
            
    return render_template('upload.html')

@app.route('/start/<int:quiz_id>', methods=['POST'])
def start_quiz(quiz_id):
    # Hitta rätt quiz i databasen
    quiz = Quiz.query.get_or_404(quiz_id)
    
    session['username'] = request.form['username']
    session['current_quiz_id'] = quiz.id
    session['current_quiz_name'] = quiz.name
    session['score'] = 0
    session['question_count'] = 0
    return redirect(url_for('quiz'))

@app.route('/quiz', methods=['GET', 'POST'])
def quiz():
    if 'current_quiz_id' not in session:
        return redirect(url_for('index'))
    
    current_quiz_id = session['current_quiz_id']

    if request.method == 'POST':
        user_answer = request.form.get('answer', '')
        correct_answer = request.form.get('correct_answer', '')
        session['question_count'] += 1
        
        if user_answer.lower().strip() == correct_answer.lower().strip():
            session['score'] += 1
            flash(f"Rätt! Svaret var {correct_answer}.", "success")
        else:
            flash(f"Fel! Rätt svar var: {correct_answer}", "error")
        return redirect(url_for('quiz'))

    # Hämta frågor BARA för detta quiz
    questions = Question.query.filter_by(quiz_id=current_quiz_id).all()
    
    if not questions:
        return "Inga frågor i detta quiz!"
    
    question = random.choice(questions)
    return render_template('quiz.html', question=question, quiz_name=session.get('current_quiz_name'))

@app.route('/finish')
def finish():
    if 'username' in session:
        res = Result(
            username=session['username'], 
            score=session.get('score', 0), 
            total_questions=session.get('question_count', 0),
            quiz_name=session.get('current_quiz_name', 'Okänt')
        )
        db.session.add(res)
        db.session.commit()
    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
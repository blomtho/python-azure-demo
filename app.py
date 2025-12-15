import os
import pandas as pd
import random
import urllib.parse  # <--- NY RAD: Vi behöver denna!
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
app.secret_key = "hemlig_nyckel_för_sessioner"

# --- DATABAS KOPPLING ---
# Klistra in din sträng från Azure (med DITT lösenord):
connection_string = "Driver={ODBC Driver 18 for SQL Server};Server=tcp:sql-thomas-quiz.database.windows.net,1433;Database=quizdb;Uid=dbadmin;Pwd=Azure-Quiz-Master-2025!;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

# --- HÄR ÄR FIXEN ---
# Vi använder quote_plus för att göra strängen säker för URL:er
quoted = urllib.parse.quote_plus(connection_string)
app.config['SQLALCHEMY_DATABASE_URI'] = f"mssql+pyodbc:///?odbc_connect={quoted}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- DATABAS MODELLER (Tabeller) ---
class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.String(500), nullable=False)
    answer_text = db.Column(db.String(200), nullable=False)

class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    date_taken = db.Column(db.DateTime, default=datetime.now)

# Skapa tabellerna om de inte finns (körs när appen startar)
with app.app_context():
    db.create_all()

# --- SIDOR (ROUTES) ---

@app.route('/')
def index():
    # Startsidan: Visa topplista och knapp för att starta
    recent_results = Result.query.order_by(Result.date_taken.desc()).limit(5).all()
    return render_template('index.html', results=recent_results)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    # Ladda upp CSV med frågor
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)
        file = request.files['file']
        if file.filename != '':
            # Rensa gamla frågor (valfritt)
            Question.query.delete()
            
            # Läs CSV med Pandas
            df = pd.read_csv(file)
            # Loopa igenom och spara till databasen
            for index, row in df.iterrows():
                # Antar att CSV har kolumnerna "Fråga" och "Svar"
                new_q = Question(question_text=row['Fråga'], answer_text=row['Svar'])
                db.session.add(new_q)
            
            db.session.commit()
            flash("Frågor uppladdade till databasen!")
            return redirect(url_for('index'))
    return render_template('upload.html')

@app.route('/start', methods=['POST'])
def start_quiz():
    session['username'] = request.form['username']
    session['score'] = 0
    session['question_count'] = 0
    return redirect(url_for('quiz'))

@app.route('/quiz', methods=['GET', 'POST'])
def quiz():
    # Hämta en slumpmässig fråga
    if request.method == 'POST':
        # Rätta svaret från föregående fråga
        user_answer = request.form['answer']
        correct_answer = request.form['correct_answer']
        
        session['question_count'] += 1
        
        # Enkel koll (ignorerar stora/små bokstäver)
        if user_answer.lower().strip() == correct_answer.lower().strip():
            session['score'] += 1
            flash(f"Rätt! Svaret var {correct_answer}.", "success")
        else:
            flash(f"Fel! Rätt svar var: {correct_answer}", "error")
            
        return redirect(url_for('quiz'))

    # Hämta slumpmässig fråga från DB
    questions = Question.query.all()
    if not questions:
        return "Inga frågor i databasen! Ladda upp en CSV först."
    
    question = random.choice(questions)
    return render_template('quiz.html', question=question)

@app.route('/finish')
def finish():
    # Spara resultatet till DB
    if 'username' in session:
        res = Result(
            username=session['username'], 
            score=session['score'], 
            total_questions=session['question_count']
        )
        db.session.add(res)
        db.session.commit()
    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
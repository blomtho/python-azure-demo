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

# --- 1. SÄKERHET & DATABAS-KOPPLING ---

# Hämta lösenordet från miljön (Environment Variable)
db_password = os.environ.get("DB_PASSWORD")

# Fallback för lokal testning (OBS: Detta körs om vi inte hittar variabeln)
if not db_password:
    # Om du vill köra lokalt utan att krångla med export, kan du skriva lösenordet här tillfälligt.
    # MEN: Ta bort det innan du pushar till GitHub igen!
    print("VARNING: Använder hårdkodat lösenord (Testläge)")
    db_password = "Nytt-Starkt-Lösenord-2025!" # <--- Ändra till ditt nya lösenord här om du testar lokalt

# Byt ut DITT-SERVERNAMN mot ditt riktiga servernamn (t.ex. sql-thomas-quiz)
server_name = "DITT-SERVERNAMN" # <--- OBS: Skriv in ditt servernamn här!

connection_string = f"Driver={{ODBC Driver 17 for SQL Server}};Server=tcp:sql-thomas-quiz.database.windows.net,1433;Database=quizdb;Uid=dbadmin;Pwd={db_password};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

# URL-enkoda strängen för att hantera specialtecken
quoted = urllib.parse.quote_plus(connection_string)
app.config['SQLALCHEMY_DATABASE_URI'] = f"mssql+pyodbc:///?odbc_connect={quoted}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- 2. SKAPA DB-OBJEKTET (Här var felet sist!) ---
db = SQLAlchemy(app)

# --- 3. DATABAS MODELLER ---
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

# Skapa tabellerna om de inte finns
with app.app_context():
    db.create_all()

# --- 4. SIDOR (ROUTES) ---
@app.route('/')
def index():
    try:
        recent_results = Result.query.order_by(Result.date_taken.desc()).limit(5).all()
        return render_template('index.html', results=recent_results)
    except Exception as e:
        return f"Kunde inte koppla till databasen. Fel: {e}"

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)
        file = request.files['file']
        if file.filename != '':
            try:
                # Rensa gamla frågor först
                Question.query.delete()
                
                df = pd.read_csv(file)
                for index, row in df.iterrows():
                    new_q = Question(question_text=str(row['Fråga']), answer_text=str(row['Svar']))
                    db.session.add(new_q)
                db.session.commit()
                flash("Frågor uppladdade!", "success")
            except Exception as e:
                flash(f"Fel vid uppladdning: {e}", "error")
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

    questions = Question.query.all()
    if not questions:
        return "Inga frågor i databasen! <a href='/upload'>Ladda upp här</a>"
    
    question = random.choice(questions)
    return render_template('quiz.html', question=question)

@app.route('/finish')
def finish():
    if 'username' in session:
        res = Result(
            username=session['username'], 
            score=session.get('score', 0), 
            total_questions=session.get('question_count', 0)
        )
        db.session.add(res)
        db.session.commit()
    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
# Tvingar fram en omstart och rebuild för Python 3.11
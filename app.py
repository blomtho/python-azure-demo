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

# --- 1. DATABAS KOPPLING ---

# Hämta lösenordet från miljön (Environment Variable)
db_password = os.environ.get("DB_PASSWORD")

if not db_password:
    # Fallback om du kör lokalt och inte satt variabeln
    # OBS: Lämna tomt när du pushar till GitHub!
    db_password = "" 

# --- VIKTIGT: ÄNDRA DENNA RAD TILL DITT SERVERNAMN ---
server_name = "sql-thomas-quiz"

# Anslutningssträng (Anpassad för Azure Linux med ODBC Driver 17)
connection_string = f"Driver={{ODBC Driver 17 for SQL Server}};Server=tcp:{server_name}.database.windows.net,1433;Database=quizdb;Uid=dbadmin;Pwd={db_password};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"

# URL-enkoda strängen för att hantera specialtecken säkert
quoted = urllib.parse.quote_plus(connection_string)
app.config['SQLALCHEMY_DATABASE_URI'] = f"mssql+pyodbc:///?odbc_connect={quoted}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- 2. DATABAS MODELLER ---

class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    # Relation: Ett quiz har många frågor
    questions = db.relationship('Question', backref='quiz', lazy=True, cascade="all, delete-orphan")

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.String(500), nullable=False)
    answer_text = db.Column(db.String(200), nullable=False)
    # Koppling: Varje fråga hör till ett Quiz ID
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)

class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    quiz_name = db.Column(db.String(100), nullable=False)
    date_taken = db.Column(db.DateTime, default=datetime.now)

# Skapa tabellerna om de inte finns
with app.app_context():
    db.create_all()

# --- 3. LOGIK & ROUTES ---

@app.route('/')
def index():
    # Startsidan: Visa topplista och tillgängliga quiz
    try:
        quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
        recent_results = Result.query.order_by(Result.date_taken.desc()).limit(5).all()
        return render_template('index.html', quizzes=quizzes, results=recent_results)
    except:
        return render_template('index.html', quizzes=[], results=[])

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    # Ladda upp CSV och skapa nytt Quiz
    if request.method == 'POST':
        quiz_name = request.form.get('quiz_name')
        file = request.files['file']
        
        if file and quiz_name:
            try:
                # A. Skapa Quizet
                new_quiz = Quiz(name=quiz_name)
                db.session.add(new_quiz)
                db.session.flush() # Ger oss ID:t direkt

                # B. Läs CSV och skapa frågor
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
    # Starta spelet: Initiera kö-systemet
    quiz = Quiz.query.get_or_404(quiz_id)
    
    # Hämta ALLA frågors ID för detta quiz
    questions = Question.query.filter_by(quiz_id=quiz.id).all()
    if not questions:
        flash("Detta quiz har inga frågor än.", "error")
        return redirect(url_for('index'))

    question_ids = [q.id for q in questions]
    random.shuffle(question_ids) # Blanda ordningen

    # Spara spel-data i sessionen
    session['username'] = request.form['username']
    session['current_quiz_id'] = quiz.id
    session['current_quiz_name'] = quiz.name
    
    # INITIERA KÖERNA
    session['queue'] = question_ids       # Huvudkön
    session['retry_queue'] = []           # Returkön (felaktiga svar)
    session['phase'] = 'main'             # Vi börjar i huvudfasen
    session['history'] = []               # Facit
    session['score'] = 0
    session['total_questions'] = len(question_ids)
    session.pop('saved', None)            # Rensa eventuell spar-flagga

    return redirect(url_for('quiz'))

@app.route('/quiz', methods=['GET', 'POST'])
def quiz():
    if 'current_quiz_id' not in session:
        return redirect(url_for('index'))

    # --- HANTERA SVAR (POST) ---
    if request.method == 'POST':
        user_answer = request.form.get('answer', '').strip()
        correct_answer = request.form.get('correct_answer', '').strip()
        question_text = request.form.get('question_text', '')
        # Hämta ID säkert (kan vara None om något går fel)
        q_id_str = request.form.get('question_id')
        question_id = int(q_id_str) if q_id_str else None
        
        is_correct = user_answer.lower() == correct_answer.lower()

        # Poängräkning (endast i huvudfasen)
        if session['phase'] == 'main':
            if is_correct:
                session['score'] += 1
            else:
                # Svara man fel i fas 1, lägg till i retry-kön för senare
                retry_list = session.get('retry_queue', [])
                if question_id and question_id not in retry_list:
                    retry_list.append(question_id)
                session['retry_queue'] = retry_list

        # Spara historik
        history = session.get('history', [])
        history.append({
            'question': question_text,
            'user_answer': user_answer,
            'correct_answer': correct_answer,
            'is_correct': is_correct,
            'phase': session['phase']
        })
        session['history'] = history
        
        # Ge feedback
        if is_correct:
            flash("Rätt!", "success")
        else:
            flash(f"Fel. Rätt svar var: {correct_answer}", "error")
            
        return redirect(url_for('quiz'))

    # --- HÄMTA NÄSTA FRÅGA (GET) ---
    queue = session.get('queue', [])
    retry_queue = session.get('retry_queue', [])
    next_q_id = None
    
    # 1. Finns det frågor i huvud-kön?
    if len(queue) > 0:
        next_q_id = queue.pop(0)
        session['queue'] = queue # Uppdatera sessionen
    
    # 2. Om huvud-kön är slut, men vi har retry-frågor (Byte till Fas 2)
    elif len(retry_queue) > 0:
        if session['phase'] == 'main':
            flash("Nu repeterar vi de frågor du missade! 🔄", "info")
            session['phase'] = 'retry'
            # Flytta retry till vanliga kön
            session['queue'] = retry_queue
            session['retry_queue'] = [] # Töm retry
            next_q_id = session['queue'].pop(0)
        else:
            # Vi är redan i retry-fasen och har frågor kvar
            next_q_id = retry_queue.pop(0)
            session['retry_queue'] = retry_queue # (Obs: logiken här flyttades till queue ovan, men safe guard)
            
            # Egentligen hanterar raden ovan (session['queue'] = retry_queue) detta, 
            # men för säkerhets skull om logiken hamnar snett:
            if not next_q_id and len(session['queue']) > 0:
                 next_q_id = session['queue'].pop(0)

    # 3. Allt är slut
    else:
        return redirect(url_for('show_result'))

    # Om vi av någon anledning inte fick ett ID (borde inte hända), gå till resultat
    if next_q_id is None:
         return redirect(url_for('show_result'))

    # Hämta frågan från DB
    current_question = Question.query.get(next_q_id)
    return render_template('quiz.html', question=current_question, quiz_name=session['current_quiz_name'])

@app.route('/result')
def show_result():
    # Visa facit och spara resultat
    if 'history' not in session:
        return redirect(url_for('index'))
    
    save_result_to_db()
    
    return render_template('result.html', 
                           history=session['history'], 
                           score=session['score'], 
                           total=session['total_questions'])

@app.route('/finish')
def finish():
    # Manuell avslutning via länk
    save_result_to_db()
    return redirect(url_for('index'))

def save_result_to_db():
    # Hjälpfunktion för att spara resultat (en gång per spel)
    try:
        if 'saved' not in session and 'username' in session:
            res = Result(
                username=session['username'], 
                score=session.get('score', 0), 
                total_questions=session.get('total_questions', 0),
                quiz_name=session.get('current_quiz_name', 'Okänt')
            )
            db.session.add(res)
            db.session.commit()
            session['saved'] = True
    except Exception as e:
        print(f"Kunde inte spara resultat: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
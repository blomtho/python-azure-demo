import os
import pandas as pd
import random
import urllib.parse
import traceback # För att kunna se felmeddelanden
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = "hemlig_nyckel_för_sessioner"

# --- DB CONFIG ---
db_password = os.environ.get("DB_PASSWORD", "")
server_name = "sql-thomas-quiz" # <--- KONTROLLERA ATT DETTA STÄMMER
connection_string = f"Driver={{ODBC Driver 17 for SQL Server}};Server=tcp:{server_name}.database.windows.net,1433;Database=quizdb;Uid=dbadmin;Pwd={db_password};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
quoted = urllib.parse.quote_plus(connection_string)
app.config['SQLALCHEMY_DATABASE_URI'] = f"mssql+pyodbc:///?odbc_connect={quoted}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- MODELLER ---
class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    questions = db.relationship('Question', backref='quiz', lazy=True, cascade="all, delete-orphan")

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.String(500), nullable=False)
    answer_text = db.Column(db.String(200), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)

class Result(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    quiz_name = db.Column(db.String(100), nullable=False)
    date_taken = db.Column(db.DateTime, default=datetime.now)

with app.app_context():
    db.create_all()

# --- ROUTES ---

@app.route('/')
def index():
    try:
        quizzes = Quiz.query.order_by(Quiz.created_at.desc()).all()
        recent_results = Result.query.order_by(Result.date_taken.desc()).limit(5).all()
        return render_template('index.html', quizzes=quizzes, results=recent_results)
    except Exception as e:
        return f"<h1>Databasfel på startsidan</h1><p>{e}</p>"

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        quiz_name = request.form.get('quiz_name')
        file = request.files['file']
        
        if file and quiz_name:
            try:
                # Läs filen och normalisera
                df = pd.read_csv(file)
                df.columns = [c.lower().strip() for c in df.columns]
                
                # Hitta kolumner
                q_col = next((c for c in df.columns if c in ['fråga', 'question', 'question_text']), None)
                a_col = next((c for c in df.columns if c in ['svar', 'answer', 'answer_text']), None)

                if not q_col or not a_col:
                    flash(f"Fel: Hittade inte kolumner. Filen har: {list(df.columns)}", "error")
                    return redirect(url_for('upload'))

                # Skapa quiz
                new_quiz = Quiz(name=quiz_name)
                db.session.add(new_quiz)
                db.session.flush()

                count = 0
                for _, row in df.iterrows():
                    q_text = str(row[q_col]).strip()
                    a_text = str(row[a_col]).strip()
                    if q_text and a_text and q_text.lower() != 'nan':
                        db.session.add(Question(question_text=q_text, answer_text=a_text, quiz_id=new_quiz.id))
                        count += 1
                
                db.session.commit()
                flash(f"Succé! Quiz '{quiz_name}' med {count} frågor skapat!", "success")

            except Exception as e:
                db.session.rollback()
                flash(f"Fel vid uppladdning: {e}", "error")
            return redirect(url_for('index'))
            
    return render_template('upload.html')

@app.route('/start/<int:quiz_id>', methods=['POST'])
def start_quiz(quiz_id):
    try:
        quiz = db.session.get(Quiz, quiz_id)
        if not quiz:
            return f"<h1>Fel:</h1><p>Hittade inget quiz med ID {quiz_id}</p>"
            
        questions = Question.query.filter_by(quiz_id=quiz.id).all()
        
        if not questions:
            flash(f"Quizet '{quiz.name}' är tomt! Ladda upp igen.", "error")
            return redirect(url_for('index'))

        question_ids = [q.id for q in questions]
        random.shuffle(question_ids)

        session['username'] = request.form['username']
        session['current_quiz_id'] = quiz.id
        session['current_quiz_name'] = quiz.name
        session['queue'] = question_ids
        session['retry_queue'] = []
        session['phase'] = 'main'
        session['history'] = []
        session['score'] = 0
        session['total_questions'] = len(question_ids)

        return redirect(url_for('quiz'))
    except Exception as e:
         return f"<h1>Fel vid start:</h1><p>{e}</p>"

@app.route('/quiz', methods=['GET', 'POST'])
def quiz():
    # 1. Kolla om vi har en session
    if 'current_quiz_id' not in session:
        return "<h1>Status: Ingen session.</h1><p>Du har blivit utloggad. <a href='/'>Gå till start</a></p>"

    # 2. Hämta kö-listan
    queue = session.get('queue', [])
    retry_queue = session.get('retry_queue', [])
    current_quiz_name = session.get('current_quiz_name', 'Okänt namn')
    
    # 3. Debug-utskrift (Detta är vad du kommer se på skärmen)
    info = f"""
    <h1>🔍 Spel-diagnos</h1>
    <p><strong>Quiz:</strong> {current_quiz_name}</p>
    <p><strong>Frågor kvar i kön:</strong> {len(queue)} st</p>
    <p><strong>Frågor i retry-kön:</strong> {len(retry_queue)} st</p>
    <p><strong>Nuvarande fas:</strong> {session.get('phase')}</p>
    <hr>
    """

    if not queue and not retry_queue:
        return info + "<h2>Slutsats: Slut på frågor!</h2> <p>Borde skicka till resultat.</p>"

    # 4. Tjuvkika på nästa fråga
    next_id = queue[0] if queue else retry_queue[0]
    
    try:
        # Försök hämta frågan från DB
        question = db.session.get(Question, next_id)
        
        if question:
            return info + f"""
            <h2>✅ Nästa fråga hittad!</h2>
            <p><strong>ID:</strong> {question.id}</p>
            <p><strong>Fråga:</strong> {question.question_text}</p>
            <p><strong>Svar:</strong> {question.answer_text}</p>
            <hr>
            <p>Om du ser detta fungerar databasen, men 'quiz.html' kanske krånglar.</p>
            """
        else:
            return info + f"""
            <h2 style='color:red'>❌ VARNING: Spök-ID</h2>
            <p>Appen försöker hämta fråga med ID <strong>{next_id}</strong>, men den finns inte i databasen!</p>
            <p>Detta orsakar den blanka sidan.</p>
            """
    except Exception as e:
        return info + f"<h2 style='color:red'>💥 KRASCH: {str(e)}</h2>"

@app.route('/result')
def show_result():
    try:
        if 'history' not in session: return redirect(url_for('index'))
        save_result()
        return render_template('result.html', history=session['history'], score=session['score'], total=session['total_questions'])
    except Exception as e:
        return f"Fel vid resultat: {e}"

@app.route('/finish')
def finish():
    save_result(show_result)
    return redirect(url_for('index'))

def save_result():
    try:
        if 'saved' not in session and 'username' in session:
            db.session.add(Result(
                username=session['username'], score=session.get('score', 0), 
                total_questions=session.get('total_questions', 0),
                quiz_name=session.get('current_quiz_name', '?')
            ))
            db.session.commit()
            session['saved'] = True
    except: pass ChildProcessError

@app.route('/debug')
def debug_page():
    status = "Databas: Okänd"
    q_count = 0
    quiz_count = 0
    try:
        quiz_count = db.session.query(Quiz).count()
        q_count = db.session.query(Question).count()
        status = f"✅ ANSLUTEN!"
    except Exception as e:
        status = f"❌ FEL: {str(e)}"

    return f"""
    <h1>Debug-rapport 🛠️</h1>
    <p><strong>Server:</strong> {server_name}</p>
    <p><strong>Status:</strong> {status}</p>
    <ul>
        <li>Antal Quiz: <strong>{quiz_count}</strong></li>
        <li>Antal Frågor totalt: <strong>{q_count}</strong> (Om detta är 0 funkar inte spelet!)</li>
    </ul>
    <hr>
    <a href="/">Tillbaka till start</a>
    """

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
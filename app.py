from flask import Flask, render_template, jsonify, request, send_from_directory, redirect, url_for, session, flash
from flask_cors import CORS
import os
import sqlite3
from datetime import datetime
from werkzeug.utils import secure_filename
from PIL import Image, ImageStat
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

# App/config
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'results.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            method TEXT NOT NULL,
            score INTEGER,
            total INTEGER,
            level TEXT,
            description TEXT,
            image_filename TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    # Migration: add user_id column to results if missing
    cur = conn.execute("PRAGMA table_info(results)")
    cols = [r[1] for r in cur.fetchall()]
    if 'user_id' not in cols:
        conn.execute("ALTER TABLE results ADD COLUMN user_id INTEGER")
        conn.commit()
    conn.close()

init_db()

# Sample skin sensitivity test questions
SKIN_QUESTIONS = [
    "Does your skin often feel tight or dry after cleansing?",
    "Do you experience redness or irritation with new skincare products?",
    "Does your skin react to weather changes?",
    "Do you have a history of eczema, rosacea, or psoriasis?",
    "Does your skin burn or sting when applying products?",
    "Do you have visible broken capillaries?",
    "Does your skin react to fragranced products?",
    "Do you experience frequent rashes or hives?"
]

@app.route('/')
def home():
    return render_template('index.html', brand="Edwin Kriti Derma Solutions", user=session.get('user'))

@app.route('/api/questions')
def get_questions():
    return jsonify({
        'questions': SKIN_QUESTIONS,
        'total_questions': len(SKIN_QUESTIONS)
    })

@app.route('/api/analyze', methods=['POST'])
def analyze_skin():
    data = request.json
    answers = data.get('answers', [])
    name = data.get('name', 'Anonymous')
    
    # Simple scoring mechanism
    score = sum(1 for ans in answers if ans == 'yes')
    total = len(answers)
    
    # Determine sensitivity level
    if score == 0:
        level = "Low"
        description = "Your skin shows minimal signs of sensitivity. You can tolerate most products well."
    elif score <= 3:
        level = "Mild"
        description = "Your skin shows some signs of sensitivity. Be cautious with new products."
    elif score <= 5:
        level = "Moderate"
        description = "Your skin is moderately sensitive. Look for fragrance-free and hypoallergenic products."
    else:
        level = "High"
        description = "Your skin is highly sensitive. Consult with a dermatologist for personalized care."

    # Persist result
    conn = get_db()
    user_id = session.get('user', {}).get('id') if session.get('user') else None
    conn.execute(
        "INSERT INTO results (name, method, score, total, level, description, image_filename, created_at, user_id) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            name,
            'questionnaire',
            score,
            total,
            level,
            description,
            None,
            datetime.utcnow().isoformat(),
            user_id
        )
    )
    conn.commit()
    conn.close()

    return jsonify({'score': score, 'total': total, 'level': level, 'description': description})

def allowed_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS

def analyze_image_file(path: str):
    with Image.open(path) as img:
        img = img.convert('RGB')
        img_small = img.resize((256, 256))
        stat = ImageStat.Stat(img_small)
        r_mean, g_mean, b_mean = stat.mean
        # Brightness approximation
        brightness = (0.299 * r_mean + 0.587 * g_mean + 0.114 * b_mean)
        # Simple redness proxy
        redness = max(r_mean - (g_mean + b_mean) / 2, 0)
        # Scale to a 0-8 score combining redness and low/high brightness extremes
        score = 0
        if redness > 15:
            score += 3
        elif redness > 8:
            score += 2
        elif redness > 4:
            score += 1
        # Very low or very high brightness can indicate barrier issues/sensitivity in this crude heuristic
        if brightness < 60 or brightness > 200:
            score += 3
        elif brightness < 90 or brightness > 170:
            score += 2
        elif brightness < 110 or brightness > 150:
            score += 1

        total = 8
        if score <= 1:
            level = 'Low'
            description = 'Image suggests minimal visible sensitivity indicators.'
        elif score <= 3:
            level = 'Mild'
            description = 'Image suggests mild sensitivity; consider gentle, fragrance-free products.'
        elif score <= 5:
            level = 'Moderate'
            description = 'Visible indicators suggest moderate sensitivity. Patch test and introduce products slowly.'
        else:
            level = 'High'
            description = 'Indicators suggest high sensitivity. Consider consulting a dermatologist.'
        return score, total, level, description, {
            'brightness': brightness,
            'redness': redness,
        }

@app.route('/api/analyze_image', methods=['POST'])
def analyze_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided under field "image"'}), 400
    file = request.files['image']
    name = request.form.get('name', 'Anonymous')
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Unsupported file type'}), 400
    filename = datetime.utcnow().strftime('%Y%m%d%H%M%S_') + secure_filename(file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)

    try:
        score, total, level, description, metrics = analyze_image_file(save_path)
    except Exception as e:
        return jsonify({'error': 'Failed to analyze image', 'details': str(e)}), 500

    # Persist result
    conn = get_db()
    user_id = session.get('user', {}).get('id') if session.get('user') else None
    conn.execute(
        "INSERT INTO results (name, method, score, total, level, description, image_filename, created_at, user_id) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            name,
            'image',
            score,
            total,
            level,
            description,
            filename,
            datetime.utcnow().isoformat(),
            user_id
        )
    )
    conn.commit()
    conn.close()

    return jsonify({'score': score, 'total': total, 'level': level, 'description': description, 'metrics': metrics, 'image': filename})

@app.route('/api/results')
def list_results():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, method, score, total, level, description, image_filename, created_at FROM results ORDER BY id DESC LIMIT 100"
    ).fetchall()
    conn.close()
    return jsonify({'results': [dict(r) for r in rows]})

@app.route('/api/my_results')
def my_results():
    if not session.get('user'):
        return jsonify({'error': 'Unauthorized'}), 401
    user_id = session['user']['id']
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, method, score, total, level, description, image_filename, created_at FROM results WHERE user_id = ? ORDER BY id DESC LIMIT 100",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify({'results': [dict(r) for r in rows]})

@app.route('/about')
def about():
    return render_template('about.html', brand="Edwin Kriti Derma Solutions", user=session.get('user'))

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/results')
def results_page():
    return render_template('results.html', brand="Edwin Kriti Derma Solutions", user=session.get('user'))

# ---------- Auth Routes ----------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        if not email or not password:
            flash('Email and password are required.', 'error')
            return redirect(url_for('register'))
        conn = get_db()
        try:
            conn.execute(
                'INSERT INTO users (name, email, password_hash, created_at) VALUES (?,?,?,?)',
                (name or email.split('@')[0], email, generate_password_hash(password), datetime.utcnow().isoformat())
            )
            conn.commit()
        except sqlite3.IntegrityError:
            flash('Email already registered.', 'error')
            conn.close()
            return redirect(url_for('register'))
        # Auto-login and redirect to analyzer (home)
        new_user = {'id': conn.execute('SELECT last_insert_rowid()').fetchone()[0], 'name': name or email.split('@')[0], 'email': email}
        conn.close()
        session['user'] = new_user
        flash('Registration successful. Welcome!', 'success')
        return redirect(url_for('home'))
    return render_template('register.html', brand="Edwin Kriti Derma Solutions", user=session.get('user'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        conn = get_db()
        row = conn.execute('SELECT id, name, email, password_hash FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        if not row or not check_password_hash(row['password_hash'], password):
            flash('Invalid email or password.', 'error')
            return redirect(url_for('login'))
        session['user'] = {'id': row['id'], 'name': row['name'], 'email': row['email']}
        flash('Welcome back!', 'success')
        return redirect(url_for('home'))
    return render_template('login.html', brand="Edwin Kriti Derma Solutions", user=session.get('user'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

def login_required(view_func):
    def wrapper(*args, **kwargs):
        if not session.get('user'):
            flash('Please log in to view this page.', 'error')
            return redirect(url_for('login'))
        return view_func(*args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', brand="Edwin Kriti Derma Solutions", user=session.get('user'))

if __name__ == '__main__':
    app.run(debug=True)

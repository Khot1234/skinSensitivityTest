from flask import Flask, render_template, jsonify, request, send_from_directory, redirect, url_for, session, flash
from flask_cors import CORS
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from PIL import Image, ImageStat
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson import ObjectId

app = Flask(__name__)
CORS(app)

# App/config
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Local upload folder (used for local development). In production on Vercel we
# use Blob Storage instead; the code will prefer Vercel blobs when BLOB_STORE_TOKEN
# is set. This keeps Pylance and local runs happy.
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-me')

# Vercel Blob Storage configuration
BLOB_STORE_TOKEN = os.environ.get('BLOB_STORE_TOKEN')
# Public base URL for blobs (you can set BLOB_STORE_BASE_URL in Vercel env vars
# to the store public URL). If not set we fall back to the default Vercel blob API
# host used by the app.
VERCEL_BLOB_API = os.environ.get('BLOB_STORE_BASE_URL', "https://blob.vercel-storage.com")

# MongoDB configuration
MONGO_URI = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/skin_sensitivity')
mongo_client = MongoClient(MONGO_URI)
db = mongo_client.get_default_database() if 'mongodb+srv://' in MONGO_URI else mongo_client.skin_sensitivity

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def init_db():
    # Create indexes
    db.users.create_index('email', unique=True)
    db.results.create_index('user_id')
    db.results.create_index('created_at')

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
    user_id = session.get('user', {}).get('id') if session.get('user') else None
    result = {
        'name': name,
        'method': 'questionnaire',
        'score': score,
        'total': total,
        'level': level,
        'description': description,
        'image_filename': None,
        'created_at': datetime.utcnow(),
        'user_id': ObjectId(user_id) if user_id else None
    }
    db.results.insert_one(result)

    return jsonify({'score': score, 'total': total, 'level': level, 'description': description})

def allowed_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS

def analyze_image_file(file):
    with Image.open(file) as img:
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

    try:
        # First analyze the image from memory
        score, total, level, description, metrics = analyze_image_file(file)

        # Then upload to Vercel Blob Storage if analysis was successful
        if not BLOB_STORE_TOKEN:
            return jsonify({'error': 'Storage configuration missing'}), 500

        import httpx
        filename = datetime.utcnow().strftime('%Y%m%d%H%M%S_') + secure_filename(file.filename)
        
        # Get upload URL from Vercel Blob
        headers = {'Authorization': f'Bearer {BLOB_STORE_TOKEN}'}
        response = httpx.post(
            f"{VERCEL_BLOB_API}/upload",
            headers=headers,
            json={
                'size': len(file.read()),
                'contentType': file.content_type,
                'filename': filename
            }
        )
        file.seek(0)  # Reset file pointer after reading
        
        if response.status_code != 201:
            return jsonify({'error': 'Failed to get upload URL'}), 500
        
        upload_url = response.json().get('uploadUrl')
        blob_url = response.json().get('url')
        
        # Upload the file to Vercel Blob
        upload_response = httpx.put(
            upload_url,
            content=file.read(),
            headers={'Content-Type': file.content_type}
        )
        
        if upload_response.status_code != 200:
            return jsonify({'error': 'Failed to upload image'}), 500
            
    except Exception as e:
        app.logger.error(f'Error in image analysis: {str(e)}')
        return jsonify({'error': 'Failed to analyze image', 'details': str(e)}), 500

    # Persist result
    user_id = session.get('user', {}).get('id') if session.get('user') else None
    result = {
        'name': name,
        'method': 'image',
        'score': score,
        'total': total,
        'level': level,
        'description': description,
        'image_filename': filename,
        'created_at': datetime.utcnow(),
        'user_id': ObjectId(user_id) if user_id else None
    }
    db.results.insert_one(result)

    return jsonify({'score': score, 'total': total, 'level': level, 'description': description, 'metrics': metrics, 'image': filename})


# Debug-only endpoint: analyze image in-memory and return results without
# attempting to upload to Blob Storage or persist to the database. This is
# useful for local testing and diagnosing image-analysis issues independently
# from storage. Keep available in all environments but it intentionally
# skips any external integrations.
@app.route('/api/debug_analyze_image', methods=['POST'])
def debug_analyze_image():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided under field "image"'}), 400
    file = request.files['image']
    name = request.form.get('name', 'Anonymous')
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Unsupported file type'}), 400

    try:
        score, total, level, description, metrics = analyze_image_file(file)
    except Exception as e:
        app.logger.error(f'Debug analysis error: {str(e)}')
        return jsonify({'error': 'Failed to analyze image', 'details': str(e)}), 500

    # Return result (no DB writes, no uploads)
    return jsonify({'score': score, 'total': total, 'level': level, 'description': description, 'metrics': metrics})

@app.route('/api/results')
def list_results():
    results = list(db.results.find({}, {'_id': False}).sort('created_at', -1).limit(100))
    return jsonify({'results': results})

@app.route('/api/my_results')
def my_results():
    if not session.get('user'):
        return jsonify({'error': 'Unauthorized'}), 401
    user_id = session['user']['id']
    results = list(db.results.find(
        {'user_id': ObjectId(user_id)},
        {'_id': False}
    ).sort('created_at', -1).limit(100))
    return jsonify({'results': results})

@app.route('/about')
def about():
    return render_template('about.html', brand="Edwin Kriti Derma Solutions", user=session.get('user'))

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    # Redirect to the Vercel Blob URL
    return redirect(f"{VERCEL_BLOB_API}/{filename}")

@app.route('/results')
def results_page():
    return render_template('results.html', brand="Edwin Kriti Derma Solutions", user=session.get('user'))

# ---------- Auth Routes ----------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            email = request.form.get('email', '').lower().strip()
            password = request.form.get('password', '')
            
            if not email or not password:
                flash('Email and password are required.', 'error')
                return redirect(url_for('register'))
            
            # Ensure indexes exist
            init_db()
            
            # Create user document
            user = {
                'name': name or email.split('@')[0],
                'email': email,
                'password_hash': generate_password_hash(password),
                'created_at': datetime.utcnow()
            }
            
            try:
                result = db.users.insert_one(user)
                # Auto-login and redirect to analyzer (home)
                user['_id'] = result.inserted_id
                session['user'] = {
                    'id': str(result.inserted_id),
                    'name': user['name'],
                    'email': user['email']
                }
                flash('Registration successful. Welcome!', 'success')
                return redirect(url_for('home'))
            except Exception as e:
                if 'duplicate key' in str(e):
                    flash('Email already registered.', 'error')
                else:
                    app.logger.error(f'Database error during registration: {str(e)}')
                    flash('An error occurred during registration. Please try again.', 'error')
                return redirect(url_for('register'))
        except Exception as e:
            app.logger.error(f'Registration error: {str(e)}')
            flash('An error occurred during registration. Please try again.', 'error')
            return redirect(url_for('register'))
    return render_template('register.html', brand="Edwin Kriti Derma Solutions", user=session.get('user'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password', '')
        
        user = db.users.find_one({'email': email})
        
        if not user or not check_password_hash(user['password_hash'], password):
            flash('Invalid email or password.', 'error')
            return redirect(url_for('login'))
            
        session['user'] = {
            'id': str(user['_id']),
            'name': user['name'],
            'email': user['email']
        }
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

# Ensure database is initialized on startup
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True)

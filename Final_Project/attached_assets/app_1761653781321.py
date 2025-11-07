from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import csv, os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secretkey123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///agrobot.db'
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ==============================
# MODELS
# ==============================

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(120))
    role = db.Column(db.String(50), default='user')
    primary_crop = db.Column(db.String(120))
    region = db.Column(db.String(120))
    preferred_language = db.Column(db.String(10), default='en')

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user_message = db.Column(db.String(500))
    bot_response = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==============================
# LOGIN MANAGER
# ==============================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==============================
# HELPER — LOAD KNOWLEDGE BASE
# ==============================

def load_kb():
    kb = []
    if os.path.exists('kb_full_professional.csv'):
        with open('kb_full_professional.csv', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                kb.append(row)
    return kb

# ==============================
# SIMPLE CHATBOT LOGIC
# ==============================

def chatbot_response(message, lang='en'):
    message = message.lower()
    kb = load_kb()
    for row in kb:
        if row['keywords'].lower() in message:
            key = f"answer_{lang}" if f"answer_{lang}" in row and row[f"answer_{lang}"] else "answer_en"
            return row.get(key, "Sorry, I don’t have an answer.")
    return "Sorry, I don’t understand that question."

# ==============================
# ROUTES
# ==============================

@app.route('/')
def index():
    recent_users = User.query.order_by(User.id.desc()).limit(5).all() if current_user.is_authenticated and current_user.role == 'admin' else None
    return render_template('index.html', title="AgroBot Chat", recent_users=recent_users)

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    user_msg = request.form['message']
    lang = current_user.preferred_language or 'en'
    bot_reply = chatbot_response(user_msg, lang)
    chat = Chat(user_id=current_user.id, user_message=user_msg, bot_response=bot_reply)
    db.session.add(chat)
    db.session.commit()
    return jsonify({'reply': bot_reply})

# ==============================
# AUTH ROUTES
# ==============================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        user = User(email=email, password=password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

# ==============================
# PROFILE
# ==============================

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.name = request.form['name']
        current_user.primary_crop = request.form['primary_crop']
        current_user.region = request.form['region']
        current_user.preferred_language = request.form['preferred_language']
        db.session.commit()
        flash('Profile updated!', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html')

# ==============================
# ADMIN DASHBOARD
# ==============================

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    users = User.query.all()
    chats = Chat.query.order_by(Chat.created_at.desc()).limit(50).all()
    kb_content = ""
    if os.path.exists('kb_full_professional.csv'):
        with open('kb_full_professional.csv', encoding='utf-8') as f:
            kb_content = f.read()
    return render_template('admin_dashboard.html', users=users, chats=chats, kb_content=kb_content)

@app.route('/admin/user/<int:user_id>')
@login_required
def admin_view_user(user_id):
    if current_user.role != 'admin':
        return redirect(url_for('index'))
    user = User.query.get_or_404(user_id)
    chats = Chat.query.filter_by(user_id=user_id).order_by(Chat.created_at.desc()).all()
    return render_template('admin_view_user.html', user=user, chats=chats)

@app.route('/admin/upload_kb_csv', methods=['POST'])
@login_required
def admin_upload_kb_csv():
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    file = request.files['csv_file']
    if file and file.filename.endswith('.csv'):
        file.save('kb_full_professional.csv')
        flash('Knowledge base updated!', 'success')
    else:
        flash('Please upload a valid CSV file.', 'danger')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_kb', methods=['POST'])
@login_required
def admin_edit_kb():
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    kb_data = request.form['kb_data']
    with open('kb_full_professional.csv', 'w', encoding='utf-8') as f:
        f.write(kb_data)
    flash('Knowledge base saved!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/clear_chats', methods=['POST'])
@login_required
def admin_clear_chats():
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    Chat.query.delete()
    db.session.commit()
    flash('All chat history cleared.', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if current_user.role != 'admin':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('User deleted.', 'info')
    return redirect(url_for('admin_dashboard'))

# ==============================
# MAIN
# ==============================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

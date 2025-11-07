
import os, json, time
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from database import init_db, db, User, ChatHistory
from chatbot_model import process_message, load_kb, KB_PATH
from utils.safety import contains_blocked, sanitize_output
from PIL import Image
import io

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "super_secret_key")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# init DB & default admin
init_db(app)

# login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/")
def index():
    recent_users = []
    if current_user.is_authenticated and current_user.role == "admin":
        recent_users = User.query.order_by(User.id.desc()).limit(20).all()
    return render_template("index.html", recent_users=recent_users)


# Register / Login / Logout / Profile
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        if User.query.filter_by(email=email).first():
            flash("Email already registered", "warning");
            return redirect(url_for("register"))
        user = User(
            email=email,
            password=generate_password_hash(request.form["password"]),
            name=request.form.get("name", ""),
            primary_crop=request.form.get("primary_crop", ""),
            region=request.form.get("region", ""),
            preferred_language=request.form.get("preferred_language", "en")
        )
        db.session.add(user);
        db.session.commit()
        flash("Registration successful — please log in", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, request.form["password"]):
            login_user(user)
            flash("Welcome back, " + (user.name or "Farmer") + "!", "success")
            return redirect(url_for("index"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for("index"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_user.name = request.form.get("name", "")
        current_user.primary_crop = request.form.get("primary_crop", "")
        current_user.region = request.form.get("region", "")
        current_user.preferred_language = request.form.get("preferred_language", "en")
        db.session.commit()
        flash("Profile updated", "success")
    return render_template("profile.html")


# Chat API
@app.route("/api/chat", methods=["POST"])
def api_chat():
    try:
        data = request.get_json() or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"response": "Please type a question."})
        if contains_blocked(message):
            return jsonify({"response": "Sorry, message contains prohibited content."}), 400
        user_profile = {
            "id": current_user.id if current_user.is_authenticated else None,
            "primary_crop": current_user.primary_crop if current_user.is_authenticated else None,
            "region": current_user.region if current_user.is_authenticated else None,
            "preferred_language": current_user.preferred_language if current_user.is_authenticated else None
        }
        reply = process_message(user_profile, message)
        reply = sanitize_output(reply)
        ch = ChatHistory(user_id=user_profile["id"], user_message=message, bot_response=reply)
        db.session.add(ch);
        db.session.commit()
        return jsonify({"response": reply})
    except Exception as e:
        print("Error /api/chat:", e)
        return jsonify({"response": "Internal server error"}), 500


# Admin routes
@app.route("/admin")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        flash("Access denied", "danger");
        return redirect(url_for("index"))
    users = User.query.order_by(User.id.desc()).all()
    chats = ChatHistory.query.order_by(ChatHistory.created_at.desc()).limit(500).all()
    kb_content = ""
    try:
        with open(KB_PATH, "r", encoding="utf-8") as f:
            kb_content = f.read()
    except Exception:
        kb_content = "[]"
    return render_template("admin_dashboard.html", users=users, chats=chats, kb_content=kb_content)


@app.route("/admin/user/<int:user_id>")
@login_required
def admin_view_user(user_id):
    """View individual user details and chat history"""
    if current_user.role != "admin":
        flash("Access denied", "danger")
        return redirect(url_for("index"))

    user = User.query.get_or_404(user_id)
    chats = ChatHistory.query.filter_by(user_id=user.id).order_by(ChatHistory.created_at.desc()).all()

    return render_template("admin_view_user.html", user=user, chats=chats)


@app.route("/admin/edit_kb", methods=["POST"])
@login_required
def admin_edit_kb():
    if current_user.role != "admin":
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    data = request.form.get("kb_data", "")
    try:
        parsed = json.loads(data)
        with open(KB_PATH, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)
        flash("KB updated", "success")
    except Exception as e:
        flash("Invalid JSON: " + str(e), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/upload_kb_csv", methods=["POST"])
@login_required
def admin_upload_kb_csv():
    if current_user.role != "admin": return jsonify({"ok": False, "error": "unauthorized"}), 403
    f = request.files.get("csv_file")
    if not f: flash("No file uploaded", "warning"); return redirect(url_for("admin_dashboard"))
    filename = secure_filename(f.filename);
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename);
    f.save(path)
    # minimal CSV parse (keywords,answer_en,answer_hi,answer_ta)
    import csv
    rows = []
    try:
        with open(path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for r in reader:
                keys = [k.strip() for k in (r.get('keywords') or "").split(',') if k.strip()]
                rows.append(
                    {"keywords": keys, "answer_en": r.get('answer_en') or "", "answer_hi": r.get('answer_hi') or "",
                     "answer_ta": r.get('answer_ta')  or ""})
        # merge into KB
        try:
            with open(KB_PATH, "r", encoding='utf-8') as f:
                existing = json.load(f)
            if not isinstance(existing, list): existing = []
        except Exception:
            existing = []
        existing.extend(rows)
        with open(KB_PATH, "w", encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        flash(f"Imported {len(rows)} rows", "success")
    except Exception as e:
        flash("CSV parse error: " + str(e), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    if current_user.role != "admin":
        flash("Access denied!", "danger")
        return redirect(url_for("index"))

    user = User.query.get_or_404(user_id)
    if user.role == "admin":
        flash("You cannot delete another admin.", "warning")
        return redirect(url_for("admin_dashboard"))

    db.session.delete(user)
    db.session.commit()
    flash("User deleted successfully!", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/clear_chats", methods=["POST"])
@login_required
def admin_clear_chats():
    if current_user.role != "admin":
        flash("Access denied!", "danger")
        return redirect(url_for("index"))

    ChatHistory.query.delete()
    db.session.commit()
    flash("✅ All chat history cleared successfully!", "success")
    return redirect(url_for("admin_dashboard"))


# Image analysis configuration
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/api/analyze-image", methods=["POST"])
@login_required
def analyze_image():
    """Enhanced image analysis endpoint that integrates with chat history"""
    try:
        if 'image' not in request.files:
            return jsonify({"error": "No image file provided"}), 400

        file = request.files['image']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400

        if not file or not allowed_file(file.filename):
            return jsonify({"error": "Invalid file type. Allowed: PNG, JPG, JPEG, GIF, WebP"}), 400

        # Check file size
        file.seek(0, 2)  # Seek to end to get size
        file_size = file.tell()
        file.seek(0)  # Reset seek position

        if file_size > MAX_FILE_SIZE:
            return jsonify({"error": "File too large. Maximum size is 5MB"}), 400

        # Get text message if provided
        text_message = request.form.get('message', '').strip()

        # Analyze image
        image_data = file.read()
        img = Image.open(io.BytesIO(image_data))

        # Get image information
        image_info = {
            'filename': secure_filename(file.filename),
            'size': file_size,
            'dimensions': img.size,
            'format': img.format,
            'mode': img.mode
        }

        # Enhanced image analysis
        analysis_result = analyze_image_content(img, text_message)

        # Save to chat history
        user_message = f"[Image: {image_info['filename']}] {text_message}" if text_message else f"[Image: {image_info['filename']}]"

        if current_user.is_authenticated:
            ch = ChatHistory(
                user_id=current_user.id,
                user_message=user_message,
                bot_response=analysis_result['response']
            )
            db.session.add(ch)
            db.session.commit()

        return jsonify({
            "success": True,
            "response": analysis_result['response'],
            "analysis": analysis_result['analysis'],
            "image_info": image_info
        })

    except Exception as e:
        print("Image analysis error:", e)
        return jsonify({"error": "Image analysis failed", "message": str(e)}), 500


def analyze_image_content(img, user_question=""):
    """Analyze image content and provide agricultural insights"""
    width, height = img.size

    # Convert to RGB for analysis
    rgb_img = img.convert('RGB')
    pixels = list(rgb_img.getdata())
    total_pixels = len(pixels)

    # Color analysis for agricultural context
    green_pixels = sum(1 for r, g, b in pixels if g > r + 20 and g > b + 20)  # Green dominance
    brown_pixels = sum(1 for r, g, b in pixels if r > 100 and g < 100 and b < 100)  # Brown/dry
    yellow_pixels = sum(1 for r, g, b in pixels if r > 150 and g > 150 and b < 100)  # Yellowing

    green_ratio = green_pixels / total_pixels
    brown_ratio = brown_pixels / total_pixels
    yellow_ratio = yellow_pixels / total_pixels

    # Determine plant health status
    if green_ratio > 0.6:
        health_status = "HEALTHY"
        confidence = "high"
    elif green_ratio > 0.3:
        health_status = "MODERATE"
        confidence = "medium"
    else:
        health_status = "STRESSED"
        confidence = "high"

    # Generate analysis report
    analysis = {
        "dimensions": f"{width}×{height}",
        "health_status": health_status,
        "confidence": confidence,
        "color_analysis": {
            "green_percentage": round(green_ratio * 100, 1),
            "brown_percentage": round(brown_ratio * 100, 1),
            "yellow_percentage": round(yellow_ratio * 100, 1)
        }
    }

    # Generate response based on analysis and user question
    response = generate_image_response(analysis, user_question, img.format)

    return {
        "response": response,
        "analysis": analysis
    }


def generate_image_response(analysis, user_question, image_format):
    """Generate contextual response based on image analysis"""

    response_parts = []

    # Add contextual response to user question
    if user_question:
        response_parts.append(f"Regarding your question '{user_question}':")

    response_parts.append("🌿 **Image Analysis Results:**")
    response_parts.append(f"• **Health Status**: {analysis['health_status']} (confidence: {analysis['confidence']})")
    response_parts.append(f"• **Image Size**: {analysis['dimensions']} pixels")
    response_parts.append(f"• **Color Analysis**:")
    response_parts.append(f"  - Green: {analysis['color_analysis']['green_percentage']}% (healthy vegetation)")
    response_parts.append(f"  - Brown: {analysis['color_analysis']['brown_percentage']}% (dry/soil)")
    response_parts.append(f"  - Yellow: {analysis['color_analysis']['yellow_percentage']}% (potential stress)")

    # Add agricultural advice based on analysis
    response_parts.append("\n**Agricultural Insights:**")

    if analysis['health_status'] == "HEALTHY":
        response_parts.append("✅ Plants appear healthy with good green coverage. Maintain current practices.")
    elif analysis['health_status'] == "MODERATE":
        response_parts.append("⚠️  Plants show some stress. Check water levels and look for pest signs.")
    else:
        response_parts.append("🚨 Plants show significant stress. Consider:")
        response_parts.append("   - Checking soil moisture")
        response_parts.append("   - Inspecting for diseases/pests")
        response_parts.append("   - Reviewing fertilizer application")

    if analysis['color_analysis']['yellow_percentage'] > 20:
        response_parts.append("\n💡 High yellow percentage may indicate:")
        response_parts.append("   - Nutrient deficiency (nitrogen)")
        response_parts.append("   - Water stress")
        response_parts.append("   - Pest damage")

    response_parts.append("\n*Note: This is automated analysis. Consult agricultural expert for precise diagnosis.*")

    return "\n".join(response_parts)


@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")

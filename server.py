import os
import time
import base64
import threading
import json
import io
import secrets
import hashlib
import logging
from functools import wraps
from datetime import datetime, timedelta

import cv2
import numpy as np
import pyotp
import qrcode
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask import (
    Flask,
    render_template,
    render_template_string,
    request,
    jsonify,
    session,
    redirect,
    url_for,
)
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Import AI processor
from ai_processor import AIProcessor


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


# ===== Security / Auth Config =====
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    # Avoid hard-crash if env not set; set ENCRYPTION_KEY to keep users.json decryptable after restart.
    ENCRYPTION_KEY = Fernet.generate_key().decode("utf-8")
    logger.warning("ENCRYPTION_KEY is not set. Generated a temporary key for this run.")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=24)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# CORS (keep compatible with client usage)
CORS(app, supports_credentials=True)

# CSRF protection (JSON endpoints are exempt where needed)
csrf = CSRFProtect(app)

# Rate limiting (in-memory)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["1000 per day", "200 per hour"],
    storage_uri="memory://",
    swallow_errors=True,
    headers_enabled=True,
)
print("TEMPLATE SEARCH PATHS =", app.jinja_loader.searchpath)

@app.after_request
def add_security_headers(resp):
    """Make browser back/forward behavior less likely to expose prior auth pages."""
    try:
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")

        # Do not disable caching for static assets.
        if not request.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp


# ===== User & Client Key Storage =====
USERS_FILE = "users.json"
CLIENT_API_KEYS_FILE = "client_api_keys.json"


def _fernet():
    key = ENCRYPTION_KEY
    if isinstance(key, str):
        key = key.encode("utf-8")
    return Fernet(key)


def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "rb") as f:
            content = f.read()
        if not content:
            return {}

        # Try decrypt first
        try:
            decrypted = _fernet().decrypt(content).decode("utf-8")
            return json.loads(decrypted)
        except Exception:
            # Fallback to plaintext JSON
            return json.loads(content.decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to load users: {e}")
        return {}


def save_users(users: dict) -> None:
    encrypted = _fernet().encrypt(json.dumps(users, ensure_ascii=False).encode("utf-8"))
    with open(USERS_FILE, "wb") as f:
        f.write(encrypted)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def validate_password(password: str):
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        return False, "Password must contain at least one special character"
    return True, "Password is strong"


def load_api_keys():
    if not os.path.exists(CLIENT_API_KEYS_FILE):
        default_keys = {
            "default_client_key_12345": {
                "name": "Default Client",
                "created": datetime.now().isoformat(),
                "active": True,
            }
        }
        save_api_keys(default_keys)
        return default_keys
    try:
        with open(CLIENT_API_KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_api_keys(keys: dict) -> None:
    with open(CLIENT_API_KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(keys, f, ensure_ascii=False, indent=2)


def verify_api_key(api_key: str) -> bool:
    keys = load_api_keys()
    if api_key in keys:
        return bool(keys[api_key].get("active", False))
    return False


def auth_or_api_key_required(f):
    """Allow either logged-in session user OR a valid X-API-Key."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("user"):
            return f(*args, **kwargs)
        api_key = request.headers.get("X-API-Key")
        if api_key and verify_api_key(api_key):
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401

    return decorated


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


# ===== Account lockout  =====
failed_login_attempts = {}  # {username: {'count': int, 'locked_until': datetime}}
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = timedelta(minutes=15)


def is_account_locked(username: str):
    if username in failed_login_attempts:
        attempt = failed_login_attempts[username]
        if attempt["count"] >= LOCKOUT_THRESHOLD:
            if datetime.now() < attempt["locked_until"]:
                return True, attempt["locked_until"]
            del failed_login_attempts[username]
    return False, None


def record_failed_login(username: str) -> None:
    if username not in failed_login_attempts:
        failed_login_attempts[username] = {"count": 0, "locked_until": None}
    failed_login_attempts[username]["count"] += 1
    if failed_login_attempts[username]["count"] >= LOCKOUT_THRESHOLD:
        failed_login_attempts[username]["locked_until"] = datetime.now() + LOCKOUT_DURATION


def reset_failed_login(username: str) -> None:
    if username in failed_login_attempts:
        del failed_login_attempts[username]


# ===== 2FA functions =====
def generate_2fa_secret() -> str:
    return pyotp.random_base32()


def generate_qr_code(username: str, secret: str) -> str:
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=username, issuer_name="Driver State Detection")

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


def verify_2fa_code(secret: str, code: str) -> bool:
    totp = pyotp.TOTP(secret)
    return bool(totp.verify(code, valid_window=1))


# ===== Login/Register UI =====
LOGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset=\"utf-8\"><title>Login</title>
<meta http-equiv=\"Cache-Control\" content=\"no-store\" />
<meta http-equiv=\"Pragma\" content=\"no-cache\" />
<meta http-equiv=\"Expires\" content=\"0\" />
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root {--primary:#5882aa;--primary-dark:#466786;}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background-image:url('/static/images/Background.png');background-size:cover;background-position:center;background-attachment:fixed;min-height:100vh;display:flex;align-items:center;justify-content:center;}
.container{background:rgba(255,255,255,0.35);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);padding:40px;border-radius:20px;box-shadow:0 10px 40px rgba(0,0,0,.25);max-width:450px;width:100%;border:1px solid rgba(255,255,255,0.3);}
h1{text-align:center;color:var(--primary);margin-bottom:30px}
input{width:100%;padding:12px;margin:10px 0;border:2px solid var(--primary);border-radius:10px;background:rgba(255,255,255,0.6);}
input:focus{border-color:var(--primary-dark);box-shadow:0 0 6px rgba(88,130,170,0.6)}
button{width:100%;padding:14px;background:var(--primary);color:#fff;border:none;border-radius:10px;font-size:1.1em;cursor:pointer;margin-top:10px;transition:0.25s;}
button:hover{background:var(--primary-dark)}
.msg{padding:10px;margin:10px 0;border-radius:8px;display:none}
.msg.error{background:rgba(255,80,80,0.2);color:#c0392b}
.msg.info{background:rgba(88,130,170,0.15);color:var(--primary-dark)}
.otp-step{display:none}
a{color:var(--primary);font-weight:600}
a:hover{color:var(--primary-dark)}
</style>
</head>
<body>
<div class=\"container\">
  <h1>Login</h1>
  <div id=\"msg\" class=\"msg\"></div>
  <div id=\"cred-step\">
    <input type=\"text\" id=\"username\" placeholder=\"Username\" autocomplete=\"username\">
    <input type=\"password\" id=\"password\" placeholder=\"Password\" autocomplete=\"current-password\">
    <button onclick=\"step1()\">Continue</button>
  </div>
  <div id=\"otp-step\" class=\"otp-step\">
    <p style=\"text-align:center;margin-bottom:15px\">Enter OTP from Authenticator</p>
    <input type=\"text\" id=\"otp\" maxlength=\"6\" placeholder=\"000000\" inputmode=\"numeric\">
    <button onclick=\"step2()\">Verify</button>
  </div>
  <div style=\"text-align:center;margin-top:20px\"><a href=\"/register\">Register</a></div>
</div>
<script>
async function step1(){
  const u=document.getElementById('username').value,
        p=document.getElementById('password').value,
        m=document.getElementById('msg');
  try{
    const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
    const d=await r.json();
    if(r.ok){
      if(d.status==='otp_required'){
        document.getElementById('cred-step').style.display='none';
        document.getElementById('otp-step').style.display='block';
        m.textContent=d.message; m.className='msg info'; m.style.display='block';
        history.replaceState(null,'',location.href);
      } else if(d.status==='success'){
        window.location.replace(d.redirect);
      }
    } else {
      m.textContent=d.error; m.className='msg error'; m.style.display='block';
    }
  } catch(e){ m.textContent='Error'; m.className='msg error'; m.style.display='block'; }
}
async function step2(){
  const o=document.getElementById('otp').value,
        m=document.getElementById('msg');
  try{
    const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({otp:o})});
    const d=await r.json();
    if(r.ok && d.status==='success'){ window.location.replace(d.redirect); }
    else { m.textContent=d.error; m.className='msg error'; m.style.display='block'; }
  } catch(e){ m.textContent='Error'; m.className='msg error'; m.style.display='block'; }
}
</script>
</body></html>"""


REGISTER_HTML = """<!DOCTYPE html>
<html><head><meta charset=\"utf-8\"><title>Register</title>
<meta http-equiv=\"Cache-Control\" content=\"no-store\" />
<meta http-equiv=\"Pragma\" content=\"no-cache\" />
<meta http-equiv=\"Expires\" content=\"0\" />
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--primary:#5882aa;--primary-dark:#466786;}
body{font-family:'Segoe UI',system-ui,sans-serif;background-image:url('/static/images/Background.png');background-size:cover;background-position:center;background-attachment:fixed;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;}
.container{background:rgba(255,255,255,0.35);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);padding:40px;border-radius:20px;max-width:500px;width:100%;border:1px solid rgba(255,255,255,0.3);box-shadow:0 10px 40px rgba(0,0,0,.25);}
h1{text-align:center;color:var(--primary);margin-bottom:30px;}
input{width:100%;padding:12px;margin:10px 0;border:2px solid var(--primary);border-radius:10px;background:rgba(255,255,255,0.6);font-size:.95em;}
input:focus{outline:none;border-color:var(--primary-dark);box-shadow:0 0 6px rgba(88,130,170,0.5)}
label{display:block;margin:10px 0 5px;color:#333;font-weight:600;font-size:.9em}
button{width:100%;padding:14px;background:var(--primary);color:#fff;border:none;border-radius:10px;font-size:1.1em;cursor:pointer;margin-top:10px;transition:0.25s;}
button:hover{background:var(--primary-dark);transform:translateY(-2px)}
button:active{transform:translateY(0)}
button:disabled{opacity:0.6;cursor:not-allowed}
button.back{background:#6c757d}
button.back:hover{background:#5a6268}
.msg{padding:12px;margin:10px 0;border-radius:8px;display:none;font-size:.9em}
.msg.error{background:rgba(255,80,80,0.2);color:#c0392b;border-left:4px solid #c0392b}
.msg.success{background:rgba(80,255,80,0.2);color:#2e8b57;border-left:4px solid #2e8b57}
.msg.info{background:rgba(88,130,170,0.15);color:var(--primary-dark);border-left:4px solid var(--primary-dark)}
.qr{text-align:center;margin:20px 0;padding:20px;background:rgba(255,255,255,0.4);border-radius:10px}
.qr img{max-width:250px;border-radius:10px;box-shadow:0 4px 12px rgba(0,0,0,.2)}
.password-requirements{background:rgba(255,255,255,0.5);padding:15px;border-radius:8px;margin:10px 0;font-size:.85em;border-left:4px solid var(--primary);}
.password-requirements strong{color:#333}
.form-footer{text-align:center;margin-top:20px;padding-top:20px;border-top:1px solid rgba(255,255,255,0.4)}
.form-footer a{color:var(--primary);font-weight:600;text-decoration:none}
.form-footer a:hover{color:var(--primary-dark)}
.otp-step{display:none}
</style>
</head>
<body>
<div class=\"container\">
  <h1>Register</h1>
  <div id=\"msg\" class=\"msg\"></div>
  <div id=\"cred-step\">
    <label>Username</label>
    <input type=\"text\" id=\"username\" placeholder=\"Enter username (min 3 chars)\" minlength=\"3\" required>
    <label>Password</label>
    <input type=\"password\" id=\"password\" placeholder=\"Enter password (min 8 chars)\" minlength=\"8\" required>
    <div class=\"password-requirements\">
      <strong>Password must contain:</strong>
      <ul>
        <li>At least 8 characters</li>
        <li>One uppercase letter</li>
        <li>One lowercase letter</li>
        <li>One number</li>
        <li>One special character (!@#$%^&*)</li>
      </ul>
    </div>
    <label>Confirm Password</label>
    <input type=\"password\" id=\"confirm\" placeholder=\"Re-enter password\" required>
    <button onclick=\"step1()\">Continue</button>
  </div>
  <div id=\"otp-step\" class=\"otp-step\">
    <div class=\"qr\" id=\"qr\"></div>
    <p style=\"text-align:center;margin-bottom:15px;color:#333\">Scan QR code using Google Authenticator</p>
    <label>Enter OTP</label>
    <input type=\"text\" id=\"otp\" maxlength=\"6\" placeholder=\"000000\" pattern=\"[0-9]{6}\" required>
    <button onclick=\"step2()\">Activate Account</button>
    <button class=\"back\" onclick=\"backToStep1()\">Back</button>
  </div>
  <div class=\"form-footer\">Already have an account? <a href=\"/login\">Login here</a></div>
</div>
<script>
async function step1(){
  const u=document.getElementById('username').value.trim();
  const p=document.getElementById('password').value;
  const c=document.getElementById('confirm').value;
  const m=document.getElementById('msg');
  if(!u||!p||!c){m.textContent='Please fill all fields';m.className='msg error';m.style.display='block';return;}
  if(p!==c){m.textContent='Passwords do not match';m.className='msg error';m.style.display='block';return;}
  try{
    const r=await fetch('/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
    const d=await r.json();
    if(r.ok && d.status==='qr_generated'){
      document.getElementById('cred-step').style.display='none';
      document.getElementById('otp-step').style.display='block';
      document.getElementById('qr').innerHTML='<img src="data:image/png;base64,'+d.qr_code+'" alt="QR Code">';
      m.textContent=d.message; m.className='msg info'; m.style.display='block';
      history.replaceState(null,'',location.href);
    } else {
      m.textContent=d.error||'Registration failed'; m.className='msg error'; m.style.display='block';
    }
  } catch(e){ m.textContent='Network error'; m.className='msg error'; m.style.display='block'; }
}
async function step2(){
  const o=document.getElementById('otp').value.trim();
  const m=document.getElementById('msg');
  if(!o||o.length!==6){m.textContent='Please enter a valid 6-digit OTP';m.className='msg error';m.style.display='block';return;}
  try{
    const r=await fetch('/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({otp:o})});
    const d=await r.json();
    if(r.ok && d.status==='success'){
      m.textContent=d.message; m.className='msg success'; m.style.display='block';
      setTimeout(()=>{window.location.replace('/login');},800);
    } else {
      m.textContent=d.error||'OTP verification failed'; m.className='msg error'; m.style.display='block';
    }
  } catch(e){ m.textContent='Network error'; m.className='msg error'; m.style.display='block'; }
}
function backToStep1(){
  document.getElementById('otp-step').style.display='none';
  document.getElementById('cred-step').style.display='block';
  document.getElementById('msg').style.display='none';
}
</script>
</body></html>"""


# ===== AI Processor / Driver State Detection =====
ai_processor = None
processing_stats = {
    "total_frames": 0,
    "processed_frames": 0,
    "start_time": time.time(),
    "last_update": time.time(),
}

# History
history_file = "history.json"
history_lock = threading.Lock()
MAX_HISTORY_ITEMS = 1000


def init_ai_processor():
    global ai_processor
    camera_params_path = os.path.join("driver_state_detection", "camera_params.json")
    if os.path.exists(camera_params_path):
        ai_processor = AIProcessor(camera_params=camera_params_path)
    else:
        ai_processor = AIProcessor()
    logger.info("AI Processor initialized")


def load_history():
    try:
        if os.path.exists(history_file):
            with open(history_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load history: {e}")
    return []


def save_history(history):
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save history: {e}")


# ===== Auth Routes =====
@app.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
@csrf.exempt
def register():
    if session.get("user"):
        return redirect(url_for("index"))

    if request.method == "POST":
        try:
            if not request.is_json:
                return jsonify({"error": "Content-Type must be application/json"}), 400
            data = request.get_json(silent=True)
            if data is None:
                return jsonify({"error": "Invalid JSON"}), 400

            username = (data.get("username") or "").strip()
            password = data.get("password") or ""
            otp = (data.get("otp") or "").strip()

            users = load_users()

            # Step 1: create QR
            if not otp:
                if not username or not password:
                    return jsonify({"error": "Missing username or password"}), 400
                if len(username) < 3:
                    return jsonify({"error": "Username must be at least 3 characters"}), 400
                if not username.isalnum():
                    return jsonify({"error": "Username must be alphanumeric"}), 400
                if username in users:
                    return jsonify({"error": "Username already exists"}), 400

                ok, msg = validate_password(password)
                if not ok:
                    return jsonify({"error": msg}), 400

                secret_2fa = generate_2fa_secret()
                session["temp_register"] = {
                    "username": username,
                    "password": hash_password(password),
                    "secret_2fa": secret_2fa,
                    "timestamp": datetime.now().isoformat(),
                }

                qr_code = generate_qr_code(username, secret_2fa)
                return (
                    jsonify(
                        {
                            "status": "qr_generated",
                            "message": "Scan QR with Google Authenticator",
                            "qr_code": qr_code,
                        }
                    ),
                    200,
                )

            # Step 2: verify OTP and finalize
            if "temp_register" not in session:
                return jsonify({"error": "Invalid register session"}), 400
            temp = session["temp_register"]
            reg_time = datetime.fromisoformat(temp["timestamp"])
            if datetime.now() - reg_time > timedelta(minutes=10):
                session.pop("temp_register", None)
                return jsonify({"error": "Register session expired"}), 400
            if not verify_2fa_code(temp["secret_2fa"], otp):
                return jsonify({"error": "Invalid OTP"}), 400

            users[temp["username"]] = {
                "password": temp["password"],
                "secret_2fa": temp["secret_2fa"],
                "created_at": datetime.now().isoformat(),
            }
            save_users(users)
            session.pop("temp_register", None)
            return jsonify({"status": "success", "message": "Registered"}), 200

        except Exception as e:
            logger.error(f"Register error: {e}")
            return jsonify({"error": "Server error"}), 500

    return render_template_string(REGISTER_HTML)


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
@csrf.exempt
def login():
    if request.method == "GET" and session.get("user"):
        return redirect(url_for("index"))

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        otp = (data.get("otp") or "").strip()

        users = load_users()

        # Step 1: username/password
        if not otp:
            is_locked, locked_until = is_account_locked(username)
            if is_locked:
                minutes_left = int((locked_until - datetime.now()).total_seconds() / 60)
                return jsonify({"error": f"Account locked. Try again in {minutes_left} minutes"}), 403

            if username not in users:
                record_failed_login(username)
                return jsonify({"error": "Invalid credentials"}), 400

            if hash_password(password) != users[username].get("password"):
                record_failed_login(username)
                return jsonify({"error": "Invalid credentials"}), 400

            session["temp_login"] = {"username": username, "timestamp": datetime.now().isoformat()}
            return jsonify({"status": "otp_required", "message": "Enter OTP from Authenticator"}), 200

        # Step 2: OTP
        if "temp_login" not in session:
            return jsonify({"error": "Invalid login session"}), 400
        temp = session["temp_login"]
        login_time = datetime.fromisoformat(temp["timestamp"])
        if datetime.now() - login_time > timedelta(minutes=5):
            session.pop("temp_login", None)
            return jsonify({"error": "Login session expired"}), 400

        user = users.get(temp["username"]) or {}
        if not verify_2fa_code(user.get("secret_2fa", ""), otp):
            return jsonify({"error": "Invalid OTP"}), 400

        session["user"] = temp["username"]
        session.permanent = True
        session.pop("temp_login", None)
        reset_failed_login(temp["username"])
        return jsonify({"status": "success", "message": "Logged in", "redirect": "/"}), 200

    return render_template_string(LOGIN_HTML)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ===== Web UI =====
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template(
        "index.html",
        username=session.get("user"),
        speech_count=0,
        sign_count=0,
        speech_data=[],
        sign_data=[],
    )


# ===== API =====
@app.route("/api/health", methods=["GET"])
@limiter.limit("100 per minute")
def health():
    return jsonify(
        {
            "status": "healthy",
            "ai_processor_ready": ai_processor is not None,
            "uptime": time.time() - processing_stats["start_time"],
        }
    )


@app.route("/api/process_frame", methods=["POST"])
@auth_or_api_key_required
@csrf.exempt
@limiter.exempt  # high-frequency
def process_frame():
    global processing_stats
    try:
        json_body = request.get_json(silent=True) if request.is_json else None

        if "image" not in request.files and not (json_body and json_body.get("frame")):
            return jsonify({"error": "No frame"}), 400

        if "image" in request.files:
            frame_bytes = request.files["image"].read()
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        else:
            frame_data = (json_body or {}).get("frame", "")
            if frame_data.startswith("data:image"):
                frame_data = frame_data.split(",", 1)[1]
            frame_bytes = base64.b64decode(frame_data)
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if frame is None:
            return jsonify({"error": "Decode failed"}), 400

        processing_stats["total_frames"] += 1

        if ai_processor is None:
            return jsonify({"error": "AI Processor not ready"}), 500

        result = ai_processor.process_frame(frame)
        processing_stats["processed_frames"] += 1
        processing_stats["last_update"] = time.time()

        elapsed = time.time() - processing_stats["start_time"]
        fps = processing_stats["processed_frames"] / elapsed if elapsed > 0 else 0

        if result.get("processed_frame") is not None:
            ok, buffer = cv2.imencode(".jpg", result["processed_frame"], [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                frame_base64 = base64.b64encode(buffer).decode("utf-8")
                result["processed_frame"] = f"data:image/jpeg;base64,{frame_base64}"
            else:
                result["processed_frame"] = None

        result["fps"] = round(fps, 2)
        result["timestamp"] = datetime.now().isoformat()
        return jsonify(result)

    except Exception as e:
        logger.error(f"process_frame error: {e}")
        return jsonify({"error": "Processing error"}), 500


@app.route("/api/stats", methods=["GET"])
@auth_or_api_key_required
@limiter.exempt
def get_stats():
    elapsed = time.time() - processing_stats["start_time"]
    fps = processing_stats["processed_frames"] / elapsed if elapsed > 0 else 0
    return jsonify(
        {
            "total_frames": processing_stats["total_frames"],
            "processed_frames": processing_stats["processed_frames"],
            "fps": round(fps, 2),
            "uptime": round(elapsed, 2),
            "last_update": processing_stats["last_update"],
        }
    )


@app.route("/api/reset", methods=["POST"])
@auth_or_api_key_required
@csrf.exempt
@limiter.limit("30 per hour")
def reset_stats():
    global processing_stats
    processing_stats = {
        "total_frames": 0,
        "processed_frames": 0,
        "start_time": time.time(),
        "last_update": time.time(),
    }
    if ai_processor:
        ai_processor.reset()
    return jsonify({"message": "Reset"})


@app.route("/api/history", methods=["GET"])
@auth_or_api_key_required
@limiter.exempt
def get_history():
    with history_lock:
        history = load_history()
        history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        history = history[:MAX_HISTORY_ITEMS]
    return jsonify({"history": history})


@app.route("/api/history", methods=["POST"])
@auth_or_api_key_required
@csrf.exempt
@limiter.exempt
def add_history():
    try:
        data = request.get_json(silent=True) or {}
        if not data:
            return jsonify({"error": "No data"}), 400

        has_alert = bool(
            data.get("asleep", False)
            or data.get("tired", False)
            or data.get("looking_away", False)
            or data.get("distracted", False)
        )
        if not has_alert:
            return jsonify({"message": "No alert"})

        history_item = {
            "timestamp": data.get("timestamp", datetime.now().isoformat()),
            "asleep": bool(data.get("asleep", False)),
            "tired": bool(data.get("tired", False)),
            "looking_away": bool(data.get("looking_away", False)),
            "distracted": bool(data.get("distracted", False)),
            "ear": data.get("ear"),
            "gaze": data.get("gaze"),
            "perclos": data.get("perclos"),
            "roll": data.get("roll"),
            "pitch": data.get("pitch"),
            "yaw": data.get("yaw"),
        }

        with history_lock:
            history = load_history()
            history.append(history_item)
            if len(history) > MAX_HISTORY_ITEMS:
                history = history[-MAX_HISTORY_ITEMS:]
            save_history(history)

        return jsonify({"message": "Added", "item": history_item})

    except Exception as e:
        logger.error(f"add_history error: {e}")
        return jsonify({"error": "Server error"}), 500


@app.route("/api/history/clear", methods=["POST"])
@auth_or_api_key_required
@csrf.exempt
@limiter.limit("30 per hour")
def clear_history():
    with history_lock:
        save_history([])
    return jsonify({"message": "Cleared"})


if __name__ == "__main__":
    logger.info("Starting server...")
    init_ai_processor()
    logger.info("Server ready: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)

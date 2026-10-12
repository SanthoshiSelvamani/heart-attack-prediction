"""Flask server for the Heart Attack Prediction System (educational project).

Two kinds of accounts:
  * patient - signs up with a phone number; can ONLY run and save an assessment
  * doctor  - created by the administrator (create_doctor.py); can ONLY view saved records
"""
import functools
import hmac
import logging
import math
import os
import secrets
import threading
import time
import uuid
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

import MySQL as db  # noqa: E402  (after load_dotenv so .env is read first)
import backend  # noqa: E402
import input_rules as rules  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("heart-app")

app = Flask(__name__)

_secret = os.getenv("SECRET_KEY")
if not _secret:
    _secret = secrets.token_hex(32)
    logger.warning("SECRET_KEY is not set in .env - using a temporary key (everyone is signed out on restart).")

app.config.update(
    SECRET_KEY=_secret,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set COOKIE_SECURE=1 in .env once the site is served over HTTPS.
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2),   # signed out after 2 idle hours
    MAX_CONTENT_LENGTH=16 * 1024,
)

# ----------------------------------------------------------------- rules
MAX_AGE = 120
PAGE_SIZE = 15
NUMERIC_LIMITS = {  # field: (min, max, label, unit)
    "trestbps": (50, 300, "Resting blood pressure", "mm Hg"),
    "chol": (50, 700, "Cholesterol", "mg/dl"),
    "thalach": (40, 250, "Maximum heart rate", "bpm"),
    "oldpeak": (0, 10, "Oldpeak", ""),
}
FIXED_CATEGORIES = {
    "sex": (0, 1),       # ASSUMPTION: 0 = Female, 1 = Male (usual coding of this dataset)
    "cp": (0, 1, 2, 3),
    "fbs": (0, 1),
    "restecg": (0, 1, 2),
    "exang": (0, 1),
    "slope": (0, 1, 2),
}
CATEGORY_LABELS = {
    "sex": "Sex", "cp": "Chest pain type", "fbs": "Fasting blood sugar",
    "restecg": "Resting ECG", "exang": "Exercise-induced angina", "slope": "Slope",
    "ca": "Major vessels", "thal": "Thal",
}
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

# Login throttling: 5 wrong passwords per account+computer, then a 10 minute pause.
MAX_FAILED_LOGINS = 5
LOCK_SECONDS = 600
_failed = {}
_failed_lock = threading.Lock()
_DUMMY_HASH = generate_password_hash("not-a-real-password-0")  # keeps timing similar for unknown users


# --------------------------------------------------------------- helpers
def json_error(message, status, fields=None):
    body = {"ok": False, "error": message}
    if fields:
        body["fields"] = fields
    return jsonify(body), status


def to_number(value):
    """Return a finite float, or None if the value is not a usable number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            num = float(text)
        except ValueError:
            return None
    else:
        return None
    return num if math.isfinite(num) else None


def to_int_choice(value, allowed):
    num = to_number(value)
    if num is None or not num.is_integer():
        return None
    num = int(num)
    return num if num in allowed else None


def validate_payload(data, state):
    """Validate everything the browser sends. Returns (clean, errors)."""
    import re
    errors, clean = {}, {}
    this_year = date.today().year

    name = rules.clean_name(data.get("patient_name"))
    if name is None:
        errors["patient_name"] = rules.NAME_MESSAGE
    else:
        clean["patient_name"] = name

    phone = rules.clean_phone(data.get("phone"))
    if phone is None:
        errors["phone"] = rules.PHONE_MESSAGE
    else:
        clean["phone"] = phone

    # Birth year (exactly four digits - full dates are rejected)
    raw = data.get("birth_year")
    text = str(raw) if isinstance(raw, int) and not isinstance(raw, bool) else raw
    text = text.strip() if isinstance(text, str) else ""
    if not re.fullmatch(r"[0-9]{4}", text):
        errors["birth_year"] = "Enter the birth year as 4 digits, for example 1975. A full date is not accepted."
    else:
        year = int(text)
        age = this_year - year
        if age < 1 or age > MAX_AGE:
            errors["birth_year"] = f"Birth year must be between {this_year - MAX_AGE} and {this_year - 1}."
        else:
            clean["birth_year"], clean["age"] = year, age

    category_values = state["profile"]["category_values"]
    allowed_sets = dict(FIXED_CATEGORIES)
    allowed_sets["ca"] = tuple(category_values["ca"])
    allowed_sets["thal"] = tuple(category_values["thal"])
    for field, allowed in allowed_sets.items():
        value = to_int_choice(data.get(field), allowed)
        if value is None:
            errors[field] = f"{CATEGORY_LABELS[field]} must be one of: {', '.join(str(a) for a in allowed)}."
        else:
            clean[field] = value

    for field, (low, high, label, unit) in NUMERIC_LIMITS.items():
        num = to_number(data.get(field))
        if num is None or not low <= num <= high:
            errors[field] = f"{label} must be a number between {low} and {high}{(' ' + unit) if unit else ''}."
        else:
            clean[field] = round(num, 2) if field == "oldpeak" else int(round(num))

    # Optional extra information (not used by the model)
    for field in ("smoking", "alcohol"):
        value = data.get(field)
        if value in (None, ""):
            clean[field] = None
        else:
            choice = to_int_choice(value, (0, 1))
            if choice is None:
                errors[field] = f"{field.capitalize()} must be 0 or 1."
            else:
                clean[field] = choice

    return clean, errors


def model_features(clean):
    return {name: clean[name] for name in backend.EXPECTED_FEATURES}


def class_info(prediction):
    if backend.CLASS_MEANING_VERIFIED:
        if prediction == 1:
            return ("Heart disease predicted", "danger",
                    "The model assigned these values to the heart-disease class. "
                    "This is a statistical estimate, not a diagnosis.")
        return ("No heart disease predicted", "success",
                "The model assigned these values to the no-heart-disease class. "
                "This is a statistical estimate, not a diagnosis.")
    return (f"Model Class {prediction}", "neutral",
            f"The model assigned these values to class {prediction}. What each class means medically "
            "has not been verified for this project, so no diagnosis is stated.")


def range_warnings(features, state):
    warnings = []
    labels = {"age": "Age", "trestbps": "Resting blood pressure", "chol": "Cholesterol",
              "thalach": "Maximum heart rate", "oldpeak": "Oldpeak"}
    for key, rng in state["profile"]["numeric_ranges"].items():
        if not rng["min"] <= features[key] <= rng["max"]:
            warnings.append(f"{labels.get(key, key)} ({features[key]}) is outside the range in the training "
                            f"data ({rng['min']} to {rng['max']}), so the prediction may be less reliable.")
    return warnings


def load_model_or_503():
    try:
        return backend.get_state(), None
    except backend.ModelError as exc:
        logger.error("Model unavailable: %s", exc)
        return None, json_error(f"The prediction model is unavailable: {exc}", 503)


def read_json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def serialize_record(row):
    label, tone, _ = class_info(int(row["prediction"]))
    created = row.get("created_at")
    reg_date = row.get("registration_date")
    out = dict(row)
    out["oldpeak"] = float(row["oldpeak"])
    out["registration_date"] = reg_date.isoformat() if hasattr(reg_date, "isoformat") else str(reg_date)
    out["created_at"] = (created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else str(created))
    out["prediction_label"] = label
    out["prediction_tone"] = tone
    return out


# ------------------------------------------------------------ sign-in state
def ensure_csrf():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def login_user(user):
    """Start a fresh session (prevents session fixation) and remember who signed in."""
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["role"] = user["role"]
    session["full_name"] = user["full_name"]
    session["phone"] = user.get("phone") or ""
    session["csrf_token"] = secrets.token_urlsafe(32)


def home_for(role):
    return url_for("doctor_page") if role == "doctor" else url_for("index")


def require_role(role, api=True):
    """Only let a signed-in user with this role through."""
    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            current = session.get("role")
            if not session.get("user_id") or current is None:
                if api:
                    return json_error("Please sign in to continue.", 401)
                return redirect(url_for("doctor_login_page" if role == "doctor" else "login_page"))
            if current != role:
                if api:
                    return json_error("Your account does not have access to this.", 403)
                return redirect(home_for(current))
            return view(*args, **kwargs)
        return wrapper
    return decorator


def _lock_key(role, identifier):
    return f"{role}:{identifier}:{request.remote_addr}"


def _is_locked(key):
    now = time.time()
    with _failed_lock:
        recent = [t for t in _failed.get(key, []) if now - t < LOCK_SECONDS]
        _failed[key] = recent
        return len(recent) >= MAX_FAILED_LOGINS


def _record_failure(key):
    with _failed_lock:
        _failed.setdefault(key, []).append(time.time())


def _clear_failures(key):
    with _failed_lock:
        _failed.pop(key, None)


def attempt_login(role, field, identifier, password, destination, bad_message):
    key = _lock_key(role, identifier)
    if _is_locked(key):
        return json_error("Too many wrong attempts. Please wait 10 minutes and try again.", 429)
    try:
        user = db.get_user(role, field, identifier)
    except db.DatabaseUnavailable as exc:
        return json_error(str(exc), 503)
    except db.DatabaseError as exc:
        return json_error(str(exc), 500)

    stored_hash = user["password_hash"] if user else _DUMMY_HASH
    matches = check_password_hash(stored_hash, password) if len(password) <= 128 else False
    if not (user and matches):
        _record_failure(key)
        return json_error(bad_message, 401)

    _clear_failures(key)
    login_user(user)
    logger.info("%s %s signed in", role, user["id"])
    return jsonify({"ok": True, "redirect": destination})


# ------------------------------------------------------- security layers
@app.before_request
def csrf_protect():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        sent = request.headers.get("X-CSRF-Token", "").encode()
        expected = session.get("csrf_token", "").encode()
        if not expected or not hmac.compare_digest(sent, expected):
            return json_error("Security check failed. Refresh the page and try again.", 403)


@app.after_request
def add_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    if not request.path.startswith("/static/"):
        # Stops the Back button from showing private pages after signing out.
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if request.path.startswith("/api/"):
        return json_error(exc.description or exc.name, exc.code)
    return exc


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    logger.exception("Unhandled error")  # full detail stays in the terminal only
    return json_error("Something went wrong on the server. Please try again.", 500)


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    role = session.get("role")
    if role == "doctor":
        return redirect(url_for("doctor_page"))
    if role != "patient":
        return redirect(url_for("login_page"))
    user = {"full_name": session.get("full_name", ""), "phone": session.get("phone", "")}
    return render_template("index.html", csrf_token=ensure_csrf(), user=user)


def _auth_page(mode):
    role = session.get("role")
    if role:
        return redirect(home_for(role))
    return render_template("auth.html", mode=mode, csrf_token=ensure_csrf())


@app.get("/login")
def login_page():
    return _auth_page("patient-login")


@app.get("/register")
def register_page():
    return _auth_page("register")


@app.get("/doctor/login")
def doctor_login_page():
    return _auth_page("doctor-login")


@app.get("/doctor")
@require_role("doctor", api=False)
def doctor_page():
    return render_template("doctor.html", csrf_token=ensure_csrf(),
                           doctor_name=session.get("full_name", ""))


# -------------------------------------------------------------- auth API
@app.post("/api/auth/register")
def api_register():
    data = read_json_object()
    if data is None:
        return json_error("Send the form data as a JSON object.", 400)

    errors = {}
    name = rules.clean_name(data.get("full_name"))
    if name is None:
        errors["full_name"] = rules.NAME_MESSAGE
    phone = rules.clean_phone(data.get("phone"))
    if phone is None:
        errors["phone"] = rules.PHONE_MESSAGE
    password = data.get("password")
    problem = rules.password_error(password, phone)
    if problem:
        errors["password"] = problem
    elif password != data.get("confirm_password"):
        errors["confirm_password"] = "The two passwords do not match."
    if errors:
        return json_error("Please correct the highlighted fields.", 422, errors)

    try:
        user_id = db.create_user("patient", name, phone, None, generate_password_hash(password))
    except db.DuplicateUser:
        return json_error("An account with this phone number already exists. Please sign in instead.", 409,
                          {"phone": "This phone number is already registered."})
    
    except db.DatabaseUnavailable as exc:
        app.logger.exception("Registration database unavailable")
        return json_error(str(exc), 503)
    except db.DatabaseError as exc:
        app.logger.exception("Registration database error")
        return json_error(str(exc), 500)


    login_user({"id": user_id, "role": "patient", "full_name": name, "phone": phone})
    return jsonify({"ok": True, "redirect": url_for("index")}), 201


@app.post("/api/auth/login")
def api_patient_login():
    data = read_json_object()
    if data is None:
        return json_error("Send the form data as a JSON object.", 400)
    phone = rules.clean_phone(data.get("phone"))
    password = data.get("password")
    if phone is None or not isinstance(password, str) or not password:
        return json_error("Enter your phone number and password.", 422)
    return attempt_login("patient", "phone", phone, password, url_for("index"),
                         "Incorrect phone number or password.")


@app.post("/api/auth/doctor-login")
def api_doctor_login():
    data = read_json_object()
    if data is None:
        return json_error("Send the form data as a JSON object.", 400)
    username = rules.clean_username(data.get("username"))
    password = data.get("password")
    if username is None or not isinstance(password, str) or not password:
        return json_error("Enter your username and password.", 422)
    return attempt_login("doctor", "username", username, password, url_for("doctor_page"),
                         "Incorrect username or password.")


@app.post("/api/logout")
def api_logout():
    role = session.get("role")
    session.clear()
    return jsonify({"ok": True, "redirect": url_for("doctor_login_page" if role == "doctor" else "login_page")})


# ------------------------------------------------------------ public API
@app.get("/api/health")
def api_health():
    import os
    import MySQL

    try:
        database_status = MySQL.ping()
    except Exception as exc:
        app.logger.exception("Health-check database error")
        database_status = f"error: {type(exc).__name__}"

    return jsonify({
        "database": database_status,
        "mysql_module": MySQL.__file__,
        "app_folder": os.getcwd(),
        "diagnostic": True,
    })

# ----------------------------------------------------------- patient API
@app.get("/api/config")
@require_role("patient")
def api_config():
    state, err = load_model_or_503()
    if err:
        return err
    this_year = date.today().year
    info = backend.model_info()
    return jsonify({
        "ok": True,
        "model": {k: info[k] for k in ("algorithm", "rows_in_dataset", "test_accuracy",
                                       "test_accuracy_note", "class_meaning_verified")},
        "limits": {
            "birth_year": {"min": this_year - MAX_AGE, "max": this_year - 1},
            "numeric": {k: {"min": lo, "max": hi, "label": label, "unit": unit}
                        for k, (lo, hi, label, unit) in NUMERIC_LIMITS.items()},
        },
        "numeric_ranges": state["profile"]["numeric_ranges"],
        "category_values": state["profile"]["category_values"],
    })


def _with_account_identity(data):
    """The name and phone always come from the signed-in account, never from the browser."""
    return dict(data, patient_name=session.get("full_name", ""), phone=session.get("phone", ""))


@app.post("/api/predict")
@require_role("patient")
def api_predict():
    data = read_json_object()
    if data is None:
        return json_error("Send the form data as a JSON object.", 400)
    state, err = load_model_or_503()
    if err:
        return err

    clean, errors = validate_payload(_with_account_identity(data), state)
    if errors:
        return json_error("Please correct the highlighted fields.", 422, errors)

    features = model_features(clean)
    try:
        prediction = backend.predict_one(features)
    except backend.ModelError as exc:
        return json_error(str(exc), 500)

    label, tone, explanation = class_info(prediction)
    return jsonify({
        "ok": True,
        "prediction": prediction,
        "label": label,
        "tone": tone,
        "explanation": explanation,
        "patient_name": clean["patient_name"],
        "age": clean["age"],
        "inputs": features,
        "warnings": range_warnings(features, state),
        "assessed_at": datetime.now().isoformat(timespec="seconds"),
    })


@app.post("/api/patients")
@require_role("patient")
def api_save_patient():
    import re
    data = read_json_object()
    if data is None:
        return json_error("Send the record as a JSON object.", 400)
    state, err = load_model_or_503()
    if err:
        return err

    key = data.get("idempotency_key")
    if not isinstance(key, str) or not re.match(UUID_PATTERN, key):
        return json_error("Missing or invalid request ID. Run the prediction again, then save.", 422)

    clean, errors = validate_payload(_with_account_identity(data), state)
    if errors:
        return json_error("Please correct the highlighted fields.", 422, errors)

    # The browser's prediction is never trusted: the server recomputes it from the inputs.
    try:
        prediction = backend.predict_one(model_features(clean))
    except backend.ModelError as exc:
        return json_error(str(exc), 500)

    record = dict(clean, prediction=prediction, registration_date=date.today(),
                  patient_user_id=session["user_id"])
    try:
        record_id, already_saved = db.save_patient_record(record, str(uuid.UUID(key)))
    except db.DatabaseUnavailable as exc:
        return json_error(str(exc), 503)
    except db.DatabaseError as exc:
        return json_error(str(exc), 500)

    message = (f"This record was already saved as #{record_id}." if already_saved
               else f"Record #{record_id} saved.")
    return jsonify({"ok": True, "id": record_id, "already_saved": already_saved,
                    "message": message}), (200 if already_saved else 201)


# ------------------------------------------------------------ doctor API
@app.get("/api/doctor/records")
@require_role("doctor")
def api_doctor_records():
    search = (request.args.get("q") or "").strip()[:60]
    try:
        page = min(max(1, int(request.args.get("page", "1"))), 100000)
    except ValueError:
        page = 1
    try:
        result = db.list_records(search, page, PAGE_SIZE)
    except db.DatabaseUnavailable as exc:
        return json_error(str(exc), 503)
    except db.DatabaseError as exc:
        return json_error(str(exc), 500)

    counts = result["class_counts"]
    logger.info("doctor %s viewed the patient list (page %s)", session["user_id"], page)
    return jsonify({
        "ok": True,
        "records": [serialize_record(r) for r in result["records"]],
        "total": result["total"],
        "page": page,
        "pages": max(1, math.ceil(result["total"] / PAGE_SIZE)),
        "stats": {
            "total": sum(counts.values()),
            "classes": [{"value": c, "label": class_info(c)[0], "count": counts.get(c, 0)} for c in (0, 1)],
        },
    })


# ------------------------------------------------------------------ start
def _startup_checks():
    try:
        backend.get_state()
    except backend.ModelError as exc:
        logger.error("Model not ready: %s", exc)
    try:
        db.init_db()
        logger.info("Database ready.")
    except (db.DatabaseUnavailable, db.DatabaseError) as exc:
        logger.error("Database not ready: %s (the site cannot sign anyone in until this is fixed)", exc)


if __name__ == "__main__":
    _startup_checks()
    app.run(host="127.0.0.1", port=5000, debug=False)

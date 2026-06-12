from flask import Flask, render_template, jsonify, request, session, redirect, Response
from qr_logic import generate_qr, is_qr_valid, get_time_window
from database import get_db
import hashlib
import random
import string
from datetime import datetime
import os
import time
from dotenv import load_dotenv

load_dotenv()

# Prevent TensorFlow logging bloat on the cloud server
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# Import PostgreSQL drivers instead of sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True  # True for production HTTPS

# OVERRIDE: Re-write the database fetch engine to route directly to Neon Cloud
def get_db():
    DATABASE_URL = os.environ.get('DATABASE_URL')
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    # Automatically formats database rows into dictionaries matching SQLite row factory behavior
    conn.cursor_factory = RealDictCursor
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def check_already_scanned(student_email, window_id, session_code):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM scans 
        WHERE student_email = %s 
        AND classroom_id = %s
        AND window_id IN (%s, %s, %s)
    """, (student_email, session_code,
          int(window_id),
          int(window_id) - 1,
          int(window_id) + 1))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def record_scan(student_email, window_id, session_code):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO scans (student_email, window_id, classroom_id)
        VALUES (%s, %s, %s)
    """, (student_email, window_id, session_code))
    cursor.execute("DELETE FROM scans WHERE window_id < %s", (int(time.time() // 10) - 8640,))
    conn.commit()
    conn.close()

def record_attendance(student_email, session_code):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM attendance 
        WHERE student_email = %s 
        AND session_code = %s
        AND DATE(timestamp) = CURRENT_DATE
    """, (student_email, session_code))
    already_exists = cursor.fetchone()
    if not already_exists:
        cursor.execute("""
            INSERT INTO attendance (student_email, session_code, classroom_id, status)
            VALUES (%s, %s, %s, 'present')
        """, (student_email, session_code, session_code))
        conn.commit()
    conn.close()

def generate_session_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# ==========================================
#                 ROUTING & PAGES             
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/teacher")
def teacher():
    return render_template("teacher.html")

@app.route("/emaans-panel", methods=["GET", "POST"])
def secret_admin():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM students")
        students_list = cursor.fetchall()
    except Exception as e:
        print(f"[ERROR] Could not fetch student data: {e}")
        students_list = []
    finally:
        conn.close()

    if request.method == "POST":
        if request.form:
            email = request.form.get("email", "admin@arro.edu.pk").strip().lower()
            password = request.form.get("password", "")
        else:
            data = request.get_json() or {}
            email = data.get("email", "").strip().lower()
            password = data.get("password", "")

        # Safe environment validation with your explicit hash string fallback
        raw_hash = os.getenv("ADMIN_PASSWORD_HASH")
        if not raw_hash:
            expected_hash = "ecc73d49823f8b6f046653f751d2b8b32e93027ed757931ebbe10c36a29980c8"
        else:
            expected_hash = str(raw_hash)

        # Sanitize any quotes or trailing spaces perfectly
        expected_hash = expected_hash.strip().replace('"', '').replace("'", "")

        if email == "admin@arro.edu.pk" and hash_password(password) == expected_hash:
            session["is_admin"] = True
            session["admin_email"] = "admin@arro.edu.pk"
            return redirect("/emaans-panel")
            
        if request.form:
            return "Invalid Credentials. Please head back and re-enter your password.", 401
        return jsonify({"success": False, "message": "Invalid credentials"})

    if session.get("is_admin") and session.get("admin_email") == "admin@arro.edu.pk":
        return render_template("admin.html", students=students_list)

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ARRO Admin Gateway</title>
        <style>
            body { background: #121212; color: #fff; font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
            .box { background: #1e1e1e; padding: 30px; border-radius: 8px; border: 1px solid #333; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.3); }
            input { width: 250px; padding: 10px; margin: 10px 0; border: 1px solid #444; background: #2a2a2a; color: white; border-radius: 4px; display: block; }
            button { width: 272px; padding: 10px; background: #007bff; border: none; color: white; font-weight: bold; border-radius: 4px; cursor: pointer; }
            button:hover { background: #0056b3; }
        </style>
    </head>
    <body>
        <form class="box" method="POST" action="/emaans-panel">
            <h2>ARRO Admin Portal</h2>
            <input type="hidden" name="email" value="admin@arro.edu.pk">
            <input type="password" name="password" placeholder="Enter Secure Admin Password" required>
            <button type="submit">Access Panel</button>
        </form>
    </body>
    </html>
    """

@app.route("/admin")
def admin():
    return redirect("/emaans-panel")

@app.route("/admin/manage-student", methods=["POST"])
def manage_student():
    if not session.get("is_admin") or session.get("admin_email") != "admin@arro.edu.pk":
        return jsonify({"success": False, "message": "Unauthorized access"}), 403

    action = request.form.get("action")
    student_id = request.form.get("student_id")

    if not student_id:
        return jsonify({"success": False, "message": "Missing Student ID"}), 400

    conn = get_db()
    cursor = conn.cursor()

    try:
        if action == "reset_password":
            default_password = "Reset2026"
            hashed_pw = hash_password(default_password)
            cursor.execute("UPDATE students SET password = %s WHERE email = %s", (hashed_pw, student_id))
            conn.commit()
            return jsonify({"success": True, "message": "Password reset to: Reset2026"})
        elif action == "reset_device":
            cursor.execute("UPDATE students SET device_fingerprint = NULL WHERE id = %s", (int(student_id),))
            conn.commit()
            return jsonify({"success": True, "message": "Device binding cleared successfully."})

    except Exception as e:
        print(f"[ADMIN ERROR] Management action failed: {e}")
        return jsonify({"success": False, "message": "Database update failed"}), 500
    finally:
        conn.close()

    return jsonify({"success": False, "message": "Invalid action"}), 400

@app.route("/student")
def student():
    return render_template("student.html")

# ==========================================
#           CORE ENGINE & AUTH API           
# ==========================================

@app.route("/get-qr/<classroom_id>")
def get_qr(classroom_id):
    img_base64, window = generate_qr(classroom_id)
    return jsonify({"qr_image": img_base64, "window": window})

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    face_image = data.get("face_image", None)

    if not email or not email.endswith(".edu.pk"):
        return jsonify({"success": False, "message": "Use your university email (.edu.pk)"})

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE email = %s", (email,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"success": False, "message": "Email already registered"})

    is_niqab_requested = data.get("is_niqab", 0)
    niqab_status = "pending" if is_niqab_requested else "none"
    
    cursor.execute("""
        INSERT INTO students (email, password, face_image, is_niqab, pin, niqab_status)
        VALUES (%s, %s, %s, 0, NULL, %s)
    """, (email, hash_password(password), face_image, niqab_status))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Registered successfully"})

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE email = %s AND password = %s",
                   (email, hash_password(password)))
    student_row = cursor.fetchone()
    conn.close()

    if student_row:
        session["student_email"] = email 
        niqab_status = student_row["niqab_status"] or "none"
        return jsonify({
            "success": True,
            "is_admin": False,
            "is_niqab": student_row["is_niqab"],
            "niqab_status": niqab_status,
            "has_fingerprint": bool(student_row["device_fingerprint"])
        })
        
    return jsonify({"success": False, "message": "Invalid email or password"})

@app.route("/scan", methods=["POST"])
def scan():
    data = request.get_json()
    qr_window = data.get("window")
    classroom_id = data.get("classroom_id")
    student_email = data.get("student_email")
    live_face = data.get("live_face")

    if not student_email:
        return jsonify({"success": False, "message": "Please login first"})

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students WHERE email = %s", (student_email,))
    student_row = cursor.fetchone()
    conn.close()

    if not student_row:
        return jsonify({"success": False, "message": "Student not found"})
        
    try:
        qr_window = int(qr_window)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid QR code"})

    if not is_qr_valid(qr_window):
        return jsonify({"success": False, "message": "QR expired, scan again"})
    
    if check_already_scanned(student_email, qr_window, classroom_id):
        return jsonify({"success": False, "message": "Already marked present"})

    if not live_face:
        return jsonify({"success": False, "message": "Face image required"})
        
    from face_logic import verify_student
    verified, message = verify_student(student_email, live_face)
    if not verified:
        return jsonify({"success": False, "message": f"Face verification failed: {message}"})
    
    record_scan(student_email, qr_window, classroom_id)
    record_attendance(student_email, classroom_id)
    return jsonify({"success": True, "message": "Present! Attendance marked"})

# ==========================================
#           SECURED ADMIN ENDPOINTS          
# ==========================================

@app.route("/admin/data")
def admin_data():
    if not session.get("is_admin"): return jsonify({"error": "Unauthorized"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, is_niqab, pin_approved, device_fingerprint, niqab_status, created_at FROM students")
    students = [dict(row) for row in cursor.fetchall()]
    cursor.execute("""
        SELECT a.id, a.student_email, a.session_code,
               a.timestamp, a.status,
               s.subject, s.section, s.room, s.teacher_email
        FROM attendance a
        LEFT JOIN sessions s ON s.session_code = a.session_code
        ORDER BY a.timestamp DESC
    """)
    attendance = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"students": students, "attendance": attendance})

@app.route("/admin/delete-student/<email>", methods=["DELETE"])
def delete_student(email):
    if not session.get("is_admin"): return jsonify({"error": "Unauthorized"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM students WHERE email = %s", (email,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/admin/approve-pin/<email>", methods=["POST"])
def approve_pin(email):
    if not session.get("is_admin"): return jsonify({"error": "Unauthorized"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE students SET is_niqab = 1, niqab_status = 'approved'
        WHERE email = %s
    """, (email,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/admin/reject-pin/<email>", methods=["POST"])
def reject_pin(email):
    if not session.get("is_admin"): return jsonify({"error": "Unauthorized"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE students SET is_niqab = 0, niqab_status = 'rejected'
        WHERE email = %s
    """, (email,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/admin/teachers")
def admin_teachers():
    if not session.get("is_admin"): return jsonify({"error": "Unauthorized"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, created_at FROM teachers ORDER BY created_at DESC")
    teachers = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"teachers": teachers})

@app.route("/admin/delete-teacher/<email>", methods=["DELETE"])
def delete_teacher(email):
    if not session.get("is_admin"): return jsonify({"error": "Unauthorized"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM teachers WHERE email = %s", (email,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/admin/set-face-mode/<email>", methods=["POST"])
def set_face_mode(email):
    if not session.get("is_admin"): return jsonify({"error": "Unauthorized"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE students SET is_niqab = 0, niqab_status = 'none'
        WHERE email = %s
    """, (email,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/admin/set-niqab", methods=["POST"])
def set_niqab():
    if not session.get("is_admin"): return jsonify({"error": "Unauthorized"}), 403
    data = request.get_json()
    email = data.get("email")
    is_niqab = data.get("is_niqab", 1)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE students SET is_niqab = %s WHERE email = %s", (is_niqab, email))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/admin/niqab-students")
def niqab_students():
    if not session.get("is_admin"): return jsonify({"error": "Unauthorized"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT email, is_niqab, device_fingerprint, created_at 
        FROM students 
        WHERE is_niqab = 1
    """)
    students = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"students": students})

@app.route("/admin/active-sessions")
def active_sessions():
    if not session.get("is_admin"): return jsonify({"error": "Unauthorized"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE is_active = 1")
    sessions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"sessions": sessions})

# ==========================================
#             TEACHER SYSTEM API            
# ==========================================

@app.route("/attendance/<classroom_id>")
def get_attendance(classroom_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT student_email as email, timestamp
        FROM attendance
        WHERE session_code = %s
        ORDER BY timestamp DESC
    """, (classroom_id,))
    records = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT COUNT(*) as count FROM students")
    total = cursor.fetchone()["count"]
    conn.close()
    return jsonify({"records": records, "total_students": total})

@app.route("/start-session", methods=["POST"])
def start_session():
    data = request.get_json()
    session_code = generate_session_code()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sessions 
        (session_code, teacher_email, subject, section, room, date, start_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        session_code,
        data.get("teacher_email"),
        data.get("subject"),
        data.get("section"),
        data.get("room"),
        datetime.now().strftime("%Y-%m-%d"),
        datetime.now().strftime("%H:%M:%S")
    ))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "session_code": session_code})

@app.route("/end-session/<session_code>", methods=["POST"])
def end_session(session_code):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sessions SET is_active = 0, end_time = %s
        WHERE session_code = %s
    """, (datetime.now().strftime("%H:%M:%S"), session_code))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/export/<session_code>")
def export_attendance(session_code):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE session_code = %s", (session_code,))
    sess = dict(cursor.fetchone())
    cursor.execute("""
        SELECT student_email, timestamp FROM attendance
        WHERE session_code = %s
        ORDER BY timestamp
    """, (session_code,))
    records = cursor.fetchall()
    conn.close()
    lines = [
        "ARRO ATTENDANCE REPORT",
        f"Subject: {sess['subject']}",
        f"Section: {sess['section']} | Room: {sess['room']}",
        f"Date: {sess['date']} | Time: {sess['start_time']}",
        "",
        "Student Email,Time,Status"
    ]
    for r in records:
        lines.append(f"{r['student_email']},{r['timestamp']},Present")
    return Response(
        "\n".join(lines),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=arro_{session_code}.csv"}
    )

@app.route("/teacher-register", methods=["POST"])
def teacher_register():
    data = request.get_json()
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    if not email or not email.endswith(".edu.pk"):
        return jsonify({"success": False, "message": "Use your university email"})
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM teachers WHERE email = %s", (email,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"success": False, "message": "Email already registered"})
    cursor.execute("""
        INSERT INTO teachers (name, email, password)
        VALUES (%s, %s, %s)
    """, (name, email, hash_password(password)))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/teacher-login", methods=["POST"])
def teacher_login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM teachers WHERE email = %s AND password = %s",
                   (email, hash_password(password)))
    teacher = cursor.fetchone()
    conn.close()
    if teacher:
        session["teacher_email"] = email
        session["teacher_name"] = teacher["name"]
        return jsonify({"success": True, "name": teacher["name"]})
    return jsonify({"success": False, "message": "Invalid email or password"})

@app.route("/teacher-sessions")
def teacher_sessions():
    teacher_email = request.args.get("email")
    if not teacher_email:
        return jsonify({"sessions": []})
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.session_code, s.subject, s.section, s.room,
               s.date, s.start_time, s.end_time, s.is_active,
               COUNT(a.id) as present_count
        FROM sessions s
        LEFT JOIN attendance a ON a.session_code = s.session_code
        WHERE s.teacher_email = %s
        GROUP BY s.session_code
        ORDER BY s.date DESC, s.start_time DESC
    """, (teacher_email,))
    sessions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"sessions": sessions})

@app.route("/send-pins", methods=["POST"])
def send_pins():
    data = request.get_json()
    session_code = data.get("session_code")
    teacher_email = data.get("teacher_email")

    if not session_code or not teacher_email:
        return jsonify({"success": False, "message": "Missing data"})

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM sessions WHERE session_code = %s AND teacher_email = %s",
                   (session_code, teacher_email))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"success": False, "message": "Session not found"})

    cursor.execute("SELECT email FROM students WHERE is_niqab = 1")
    niqab_students = cursor.fetchall()

    if not niqab_students:
        conn.close()
        return jsonify({"success": False, "message": "No approved niqab students found"})

    count = 0
    for student in niqab_students:
        email = student["email"]
        pin = ''.join(random.choices(string.digits, k=6))

        cursor.execute("""
            DELETE FROM niqab_pins
            WHERE student_email = %s AND session_code = %s AND used = 0
        """, (email, session_code))

        cursor.execute("""
            INSERT INTO niqab_pins (student_email, session_code, pin)
            VALUES (%s, %s, %s)
        """, (email, session_code, pin))
        count += 1

    conn.commit()
    conn.close()
    return jsonify({"success": True, "count": count, "message": f"PINs sent to {count} students"})

# ==========================================
#             STUDENT SYSTEM API            
# ==========================================

@app.route("/student-history")
def student_history():
    student_email = request.args.get("email")
    if not student_email:
        return jsonify({"records": []})
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.timestamp, a.session_code,
               s.subject, s.section, s.room, s.date
        FROM attendance a
        LEFT JOIN sessions s ON s.session_code = a.session_code
        WHERE a.student_email = %s
        ORDER BY a.timestamp DESC
    """, (student_email,))
    records = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"records": records})

@app.route("/register-fingerprint", methods=["POST"])
def register_fingerprint():
    data = request.get_json()
    email = data.get("email")
    fingerprint = data.get("fingerprint")
    
    if not email or not fingerprint:
        return jsonify({"success": False, "message": "Missing data"})
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE students SET device_fingerprint = %s WHERE email = %s", 
                   (fingerprint, email))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/generate-niqab-pin", methods=["POST"])
def generate_niqab_pin():
    data = request.get_json()
    student_email = data.get("student_email")
    session_code = data.get("session_code")
    
    if not student_email or not session_code:
        return jsonify({"success": False, "message": "Missing data"})
    
    pin = ''.join(random.choices(string.digits, k=6))
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM niqab_pins 
        WHERE student_email = %s AND session_code = %s AND used = 0
    """, (student_email, session_code))
    
    cursor.execute("""
        INSERT INTO niqab_pins (student_email, session_code, pin)
        VALUES (%s, %s, %s)
    """, (student_email, session_code, pin))
    
    conn.commit()
    conn.close()
    return jsonify({"success": True, "pin": pin})

@app.route("/scan-niqab", methods=["POST"])
def scan_niqab():
    data = request.get_json()
    qr_window = data.get("window")
    classroom_id = data.get("classroom_id")
    student_email = data.get("student_email")
    pin = data.get("pin")
    fingerprint = data.get("fingerprint")
    selfie = data.get("selfie")

    if not student_email:
        return jsonify({"success": False, "message": "Please login first"})
    try:
        qr_window = int(qr_window)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid QR code"})

    if check_already_scanned(student_email, qr_window, classroom_id):
        return jsonify({"success": False, "message": "Already marked present"})

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM students WHERE email = %s", (student_email,))
    student_row = cursor.fetchone()

    if not student_row:
        conn.close()
        return jsonify({"success": False, "message": "Student not found"})

    registered_fingerprint = student_row["device_fingerprint"]
    if not registered_fingerprint:
        conn.close()
        return jsonify({"success": False, "message": "No device registered. Please re-register."})

    if registered_fingerprint != fingerprint:
        conn.close()
        return jsonify({"success": False, "message": "Wrong device. Use your registered phone."})

    cursor.execute("""
        SELECT * FROM niqab_pins 
        WHERE student_email = %s 
        AND session_code = %s 
        AND pin = %s 
        AND used = 0
    """, (student_email, classroom_id, pin))
    
    pin_row = cursor.fetchone()
    if not pin_row:
        conn.close()
        return jsonify({"success": False, "message": "Invalid or expired PIN"})

    cursor.execute("""
        UPDATE niqab_pins SET used = 1 
        WHERE student_email = %s AND session_code = %s
    """, (student_email, classroom_id))

    if selfie:
        cursor.execute("""
            UPDATE students SET niqab_selfie = %s WHERE email = %s
        """, (selfie, student_email))

    conn.commit()
    conn.close()

    record_scan(student_email, qr_window, classroom_id)
    record_attendance(student_email, classroom_id)
    
    return jsonify({"success": True, "message": "Present! Attendance marked"})

@app.route("/check-niqab")
def check_niqab():
    email = request.args.get("email")
    if not email:
        return jsonify({"is_niqab": 0})
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_niqab, device_fingerprint, niqab_status FROM students WHERE email = %s", (email,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return jsonify({
            "is_niqab": row["is_niqab"],
            "has_fingerprint": bool(row["device_fingerprint"]),
            "niqab_status": row["niqab_status"] or "none"
        })
    return jsonify({"is_niqab": 0, "has_fingerprint": False, "niqab_status": "none"})

@app.route("/get-my-pin", methods=["POST"])
def get_my_pin():
    data = request.get_json()
    student_email = data.get("student_email")
    session_code = data.get("session_code")
    fingerprint = data.get("fingerprint")

    if not student_email or not session_code or not fingerprint:
        return jsonify({"success": False, "message": "Missing data"})

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT device_fingerprint, is_niqab, niqab_status FROM students WHERE email = %s",
                   (student_email,))
    student = cursor.fetchone()

    if not student:
        conn.close()
        return jsonify({"success": False, "message": "Student not found"})

    if student["niqab_status"] != "approved":
        conn.close()
        return jsonify({"success": False, "message": "PIN mode not approved for your account"})

    if student["device_fingerprint"] != fingerprint:
        conn.close()
        return jsonify({"success": False, "message": "Wrong device. Use your registered phone."})

    cursor.execute("""
        SELECT pin FROM niqab_pins
        WHERE student_email = %s AND session_code = %s AND used = 0
        ORDER BY id DESC LIMIT 1
    """)
    pin_row = cursor.fetchone()
    conn.close()

    if not pin_row:
        return jsonify({"success": False, "message": "No PIN available yet. Ask your teacher to send PINs."})

    return jsonify({"success": True, "pin": pin_row["pin"]})

@app.route("/secure-portal")
def secure_portal():
    return render_template("admin_login.html")

@app.route("/logout-admin")
def logout_admin():
    session.clear()
    return redirect("/emaans-panel")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
import sqlite3

def get_db():
    conn = sqlite3.connect("arro.db", timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        face_image TEXT,
        is_niqab INTEGER DEFAULT 0,
        pin TEXT,
        pin_approved INTEGER DEFAULT 0,
        device_fingerprint TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_email TEXT NOT NULL,
        session_code TEXT NOT NULL,
        classroom_id TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'present'
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_email TEXT NOT NULL,
        window_id INTEGER NOT NULL,
        classroom_id TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_code TEXT UNIQUE NOT NULL,
        teacher_email TEXT NOT NULL,
        subject TEXT NOT NULL,
        section TEXT NOT NULL,
        room TEXT NOT NULL,
        date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT,
        is_active INTEGER DEFAULT 1
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS teachers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS niqab_pins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_email TEXT NOT NULL,
        session_code TEXT NOT NULL,
        pin TEXT NOT NULL,
        used INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Safely add new columns to existing tables if they don't exist
    safe_add_column(cursor, "students", "device_fingerprint", "TEXT")
    safe_add_column(cursor, "students", "niqab_selfie", "TEXT")

    # niqab_status tracks admin approval:
    #   'none'     — regular face student (default)
    #   'pending'  — student requested niqab/PIN mode, waiting for admin approval
    #   'approved' — admin approved, student can use PIN attendance
    #   'rejected' — admin rejected the request
    safe_add_column(cursor, "students", "niqab_status", "TEXT DEFAULT 'none'")

    conn.commit()
    conn.close()

def safe_add_column(cursor, table, column, col_type):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except Exception:
        pass  # Column already exists, ignore
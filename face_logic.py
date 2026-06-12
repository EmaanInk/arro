import requests
import os

HF_API_URL = "https://emaanink-arro-face-engine.hf.space/verify"

def find_registered_face(student_email):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(os.environ.get("DATABASE_URL"), sslmode='require')
    conn.cursor_factory = RealDictCursor
    cursor = conn.cursor()
    cursor.execute("SELECT face_image FROM students WHERE email = %s", (student_email,))
    result = cursor.fetchone()
    conn.close()
    if result and result["face_image"]:
        return result["face_image"]
    return None

def verify_student(student_email, live_image_b64):
    registered_face = find_registered_face(student_email)
    if not registered_face:
        return False, "No face registered for this account"
    try:
        response = requests.post(HF_API_URL, json={
            "registered_b64": registered_face,
            "live_b64": live_image_b64
        }, timeout=60)
        if response.status_code == 200:
            result = response.json()
            return (True, "Face verified successfully") if result.get("match") else (False, "Face does not match")
        return False, f"API Error: {response.text}"
    except Exception as e:
        return False, f"Verification timeout. Please scan again."
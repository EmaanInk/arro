import requests
from database import get_db

# PASTE YOUR HUGGING FACE DIRECT URL HERE (Make sure to add /verify at the end!)
HF_API_URL = "https://emaanink-arro-face-engine.hf.space/verify"

def find_registered_face(student_email):
    conn = get_db()
    cursor = conn.cursor()
    # Using standard PostgreSQL %s syntax for your cloud DB
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
        # Packages up the text image strings safely
        payload = {
            "registered_b64": registered_face,
            "live_b64": live_image_b64
        }
        
        # Passes the heavy lifting to your 16GB Hugging Face engine!
        response = requests.post(HF_API_URL, json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("match"):
                return True, "Face verified successfully"
            else:
                return False, "Face does not match"
        else:
            return False, f"API Error: {response.text}"
            
    except Exception as e:
        print(f"Connection error: {str(e)}")
        return False, "Verification system timeout. Please scan once more."
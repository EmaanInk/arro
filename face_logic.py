from database import get_db
from deepface import DeepFace
import base64
import numpy as np
import cv2

def find_registered_face(student_email):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT face_image FROM students WHERE email = ?", (student_email,))
    result = cursor.fetchone()
    conn.close()
    if result and result["face_image"]:
        return result["face_image"]
    return None

def base64_to_image(base64_string):
    try:
        if not base64_string:
            return None
        if isinstance(base64_string, str) and "," in base64_string:
            base64_string = base64_string.split(",")[1]
        img_bytes = base64.b64decode(base64_string)
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        print(f"Image decode error: {str(e)}")
        return None
def match_faces(registered_b64, live_b64):
    registered_img = base64_to_image(registered_b64)
    live_img = base64_to_image(live_b64)
    
    if registered_img is None:
        raise ValueError("Registered image could not be decoded")
    if live_img is None:
        raise ValueError("Live image could not be decoded")
    
    registered_img = cv2.resize(registered_img, (800, 600))
    live_img = cv2.resize(live_img, (800, 600))
    
    result = DeepFace.verify(
        img1_path=registered_img,
        img2_path=live_img,
        model_name="ArcFace",
        detector_backend="mtcnn",
        enforce_detection=False
    )
    
    distance = result.get("distance", 1.0)
    print(f"ArcFace distance: {distance:.6f}, threshold: 0.68, verified: {result.get('verified')}")
    
    # Use stricter threshold of 0.40 instead of default 0.68
    return distance < 0.40


def verify_student(student_email, live_image_b64):
    registered_face = find_registered_face(student_email)
    if not registered_face:
        return False, "No face registered for this account"
    try:
        match = match_faces(registered_face, live_image_b64)
        if match:
            return True, "Face verified successfully"
        else:
            return False, "Face does not match"
    except Exception as e:
        print(f"DeepFace error: {str(e)}")
        return False, f"Verification failed: {str(e)}"
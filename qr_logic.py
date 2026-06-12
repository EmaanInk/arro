import qrcode
import time
import io
import base64

def get_time_window():
    current_time = int(time.time())
    current_window = current_time // 10
    return current_window

def is_qr_valid(qr_window):
    current_window = get_time_window()
    return abs(current_window - qr_window) <= 2

def can_scan(student_id, scanned_this_window):
    if student_id in scanned_this_window:
        return False
    else:
        return True
    
def generate_qr(classroom_id):
    window = get_time_window()
    qr_data = f"{window}:{classroom_id}"
    
    qr = qrcode.make(qr_data)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)  
    
    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return img_base64, window

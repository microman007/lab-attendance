from flask import Flask, request, jsonify
import os
import json
from datetime import datetime
import base64
import gspread

app = Flask(__name__)

# --- GOOGLE SHEETS & SECURE CREDENTIALS SETUP ---
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1ooYMNLndxhy1BWrIC8PfpIUKW_MtVHLVZHlhmoi05zE/edit?usp=sharing"

def get_gspread_client():
    try:
        # Check if environment variable exists (Render deployment)
        if "GOOGLE_CREDENTIALS_JSON" in os.environ:
            creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
            gc = gspread.service_account_from_dict(creds_dict)
        else:
            # Fallback to local file for testing on your PC
            CREDENTIALS_FILE = "lab-attendance-503206-eec19b2056bc.json"
            gc = gspread.service_account(filename=CREDENTIALS_FILE)
        
        sheet_instance = gc.open_by_url(GOOGLE_SHEET_URL).sheet1
        print("Connected to Google Sheets successfully!")
        return sheet_instance
    except Exception as e:
        print(f"Warning: Could not connect to Google Sheets. Error: {e}")
        return None

sheet = get_gspread_client()

@app.route('/')
def index():
    with open('index.html', 'r', encoding='utf-8') as f:
        return f.read()

@app.route('/checkin', methods=['POST'])
def checkin():
    global sheet
    if not sheet:
        sheet = get_gspread_client()
        if not sheet:
            return jsonify({"status": "error", "message": "Google Sheets connection unavailable."}), 500

    data = request.get_json()
    user_lat = data.get('lat')
    user_lon = data.get('lon')
    action = data.get('action', 'IN') # 'IN' or 'OUT'
    face_image_data = data.get('face_image')
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    user_id = "Arvind"
    today_date = datetime.now().strftime('%Y-%m-%d')
    
    filename = "N/A"
    if face_image_data:
        try:
            header, encoded = face_image_data.split(",", 1)
            image_bytes = base64.b64decode(encoded)
            os.makedirs('attendance_captures', exist_ok=True)
            filename = f"attendance_captures/{user_id}_{action}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            with open(filename, "wb") as fh:
                fh.write(image_bytes)
        except Exception as e:
            print(f"Failed to save face image: {e}")
    
    # Updated headers to include Photo column (Column H)
    expected_header = ['User ID', 'Check In', 'Check Out', 'Hours Present', 'Latitude', 'Longitude', 'Status', 'Photo']
    
    try:
        rows = sheet.get_all_values()
    except Exception:
        rows = []

    if not rows:
        sheet.append_row(expected_header)
        rows = [expected_header]
    elif rows[0] != expected_header:
        sheet.update(range_name='A1:H1', values=[expected_header])
        rows[0] = expected_header

    user_row_index = -1
    for i in range(1, len(rows)):
        if rows[i][0] == user_id and rows[i][1].startswith(today_date):
            if rows[i][2] == '': 
                user_row_index = i + 1 
                break

    if action == 'IN':
        if user_row_index != -1:
            return jsonify({"status": "error", "message": "Already checked in today! Please Check Out later."}), 400
        else:
            new_row = [user_id, timestamp, '', '', user_lat, user_lon, 'Checked In', filename]
            sheet.append_row(new_row)
            
    elif action == 'OUT':
        if user_row_index != -1:
            check_in_time_str = rows[user_row_index - 1][1]
            
            hours_str = "Error Calc"
            try:
                fmt = '%Y-%m-%d %H:%M:%S'
                in_time = datetime.strptime(check_in_time_str, fmt)
                out_time = datetime.strptime(timestamp, fmt)
                diff_seconds = (out_time - in_time).total_seconds()
                hours = round(diff_seconds / 3600, 2)
                hours_str = f"{hours} hrs"
            except Exception:
                pass

            sheet.update_cell(user_row_index, 3, timestamp)       # Check Out
            sheet.update_cell(user_row_index, 4, hours_str)       # Hours Present
            sheet.update_cell(user_row_index, 7, 'Completed')     # Status
            sheet.update_cell(user_row_index, 8, filename)        # Photo path
        else:
            new_row = [user_id, '', timestamp, 'N/A', user_lat, user_lon, 'Checked Out Only', filename]
            sheet.append_row(new_row)

    print(f"[{timestamp}] Attendance {action} logged live to Google Sheet for {user_id}")
    return jsonify({"status": "success", "message": f"Successfully Checked {action} with Face & Biometric verified!"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
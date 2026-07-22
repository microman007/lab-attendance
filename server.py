import os
import json
import base64
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template_string
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

app = Flask(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

DRIVE_FOLDER_ID = "1v78xmQXfQ8C-gkljXRHYLvktukjfdMrq"
IMGBB_API_KEY = "ecde3d2fcace699980aac77104e7d6de"

try:
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if credentials_json:
        creds_dict = json.loads(credentials_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    
    client = gspread.authorize(creds)
    sheet = client.open("Lab Attendance").sheet1
    
    # Initialize Google Drive API client (kept for any auxiliary needs)
    drive_service = build('drive', 'v3', credentials=creds)
    print("Connected to Google Sheets & Drive successfully!")
except Exception as e:
    print(f"Google Connection Error: {e}")

def upload_base64_to_drive(base64_data, filename):
    try:
        if "," in base64_data:
            base64_data = base64_data.split(",")[1]
            
        payload = {
            "key": IMGBB_API_KEY,
            "image": base64_data,
            "name": filename
        }
        
        response = requests.post("https://api.imgbb.com/1/upload", data=payload)
        result = response.json()
        
        if result.get("success"):
            # Returns the direct public image URL for the Google Sheet =IMAGE() formula
            return result["data"]["url"]
        else:
            print(f"ImgBB Error: {result}")
            return ""
    except Exception as e:
        print(f"Image Upload Error: {e}")
        return ""

@app.route("/")
def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return render_template_string(f.read())

def process_attendance(action):
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "No JSON payload received."}), 400

        user_id = data.get("user_id", "Arvind")
        lat = data.get("latitude") or data.get("lat")
        lon = data.get("longitude") or data.get("lon")
        image_data = data.get("image") or data.get("face_image")

        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST)
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        
        action_label = "IN" if action == "in" else "OUT"
        file_suffix = now.strftime("%Y%m%d_%H%M%S")
        photo_filename = f"{user_id}_{action_label}_{file_suffix}.jpg"
        
        # Upload image to ImgBB and generate a proper image formula
        img_formula = ""
        if image_data:
            public_url = upload_base64_to_drive(image_data, photo_filename)
            if public_url:
                img_formula = f'=IMAGE("{public_url}")'
            else:
                img_formula = photo_filename

        records = sheet.get_all_records()

        if action == "in":
            active_row = None
            for idx, row in enumerate(records, start=2):
                if str(row.get("User ID")) == str(user_id) and (not row.get("Check Out") or row.get("Check Out") == ""):
                    active_row = idx
                    break
            
            if active_row:
                return jsonify({"status": "error", "message": "Already Checked In! Please Check Out first."}), 400

            # Columns: User ID(A), Check In(B), Check Out(C), Hours(D), Lat(E), Lon(F), Status(G), Check-In Photo(H), Check-Out Photo(I)
            row_data = [user_id, timestamp, "", "", lat, lon, "Checked In", img_formula, ""]
            sheet.append_row(row_data, value_input_option='USER_ENTERED')
            return jsonify({"status": "success", "message": "Successfully Checked IN!"})

        elif action == "out":
            active_row = None
            check_in_time_str = None
            for idx, row in enumerate(records, start=2):
                if str(row.get("User ID")) == str(user_id) and (not row.get("Check Out") or row.get("Check Out") == ""):
                    active_row = idx
                    check_in_time_str = row.get("Check In")
                    break
            
            if not active_row:
                return jsonify({"status": "error", "message": "No active Check-In found. Please Check In first."}), 400

            try:
                check_in_time = datetime.strptime(check_in_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
                hours_present = round((now - check_in_time).total_seconds() / 3600, 2)
                hours_str = f"{hours_present} hrs"
            except Exception:
                hours_str = "0 hrs"

            sheet.update_cell(active_row, 3, timestamp)
            sheet.update_cell(active_row, 4, hours_str)
            sheet.update_cell(active_row, 7, "Completed")
            if image_data:
                sheet.update_cell(active_row, 9, img_formula)

            return jsonify({"status": "success", "message": "Successfully Checked OUT!"})

        return jsonify({"status": "error", "message": "Invalid action."}), 400

    except Exception as e:
        print(f"Error handling attendance: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/attendance", methods=["POST"])
def attendance_route():
    data = request.json or {}
    action = data.get("action", "in").lower()
    return process_attendance(action)

@app.route("/checkin", methods=["POST"])
def checkin_route():
    return process_attendance("in")

@app.route("/checkout", methods=["POST"])
def checkout_route():
    return process_attendance("out")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
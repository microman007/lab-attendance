import os
import json
import base64
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template_string
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
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
        leave_reason = data.get("leave_reason", "")

        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
        file_suffix = now.strftime("%Y%m%d_%H%M%S")
        
        action_label = "IN" if action == "in" else ("OUT" if action == "out" else "LEAVE")
        photo_filename = f"{user_id}_{action_label}_{file_suffix}.jpg"
        
        img_formula = ""
        if image_data:
            public_url = upload_base64_to_drive(image_data, photo_filename)
            if public_url:
                img_formula = f'=HYPERLINK("{public_url}", IMAGE("{public_url}"))'
            else:
                img_formula = photo_filename

        records = sheet.get_all_records()
        
        # Find if a row already exists for this user today
        target_row = None
        for idx, row in enumerate(records, start=2):
            if str(row.get("User ID")) == str(user_id) and str(row.get("Date")) == date_str:
                target_row = idx
                break

        # Handle Leave Option
        if action == "leave":
            status_val = "On Leave"
            if target_row:
                sheet.update_cell(target_row, 3, status_val)
                sheet.update_cell(target_row, 4, leave_reason)
            else:
                # User ID(A), Date(B), Status(C), Leave Reason(D), CI1(E), CO1(F), CI2(G), CO2(H), TotalHours(I), Photo1(J), Photo2(K)
                row_data = [user_id, date_str, status_val, leave_reason, "", "", "", "", "0 hrs", "", ""]
                sheet.append_row(row_data, value_input_option='USER_ENTERED')
            return jsonify({"status": "success", "message": "Leave status recorded successfully!"})

        # Handle Check-In
        if action == "in":
            # Determine OnTime vs Late based on 9:30 AM cutoff
            cutoff_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
            status_val = "OnTime/Present" if now <= cutoff_time else "Late/Present"

            if target_row:
                # Check if currently checked in (Check-In 1 filled but Check-Out 1 empty, or Check-In 2 filled but Check-Out 2 empty)
                row = records[target_row - 2]
                if not row.get("Check Out 1"):
                    return jsonify({"status": "error", "message": "Already Checked In! Please Check Out first."}), 400
                elif row.get("Check Out 1") and not row.get("Check In 2"):
                    sheet.update_cell(target_row, 7, time_str) # Check-In 2 is column G (7)
                    sheet.update_cell(target_row, 11, img_formula) # Photo 2 is column K (11)
                elif row.get("Check Out 2") and not row.get("Check In 3"):
                    sheet.update_cell(target_row, 9, time_str) # Check-In 3 is column I
                    # update photo if needed or handle additional columns
                else:
                    return jsonify({"status": "error", "message": "Maximum check-ins reached for today."}), 400
            else:
                # Create a fresh single-row entry for today
                # Columns: User ID(1), Date(2), Status(3), Leave Reason(4), Check-In 1(5), Check-Out 1(6), Check-In 2(7), Check-Out 2(8), Total Hours(9), Photo 1(10), Photo 2(11)
                row_data = [user_id, date_str, status_val, "", time_str, "", "", "", "0 hrs", img_formula, ""]
                sheet.append_row(row_data, value_input_option='USER_ENTERED')

            return jsonify({"status": "success", "message": f"Successfully Checked IN ({status_val})!"})

        # Handle Check-Out
        elif action == "out":
            if not target_row:
                return jsonify({"status": "error", "message": "No active Check-In found for today."}), 400
            
            row = records[target_row - 2]
            
            # Determine which Check-Out to fill
            if row.get("Check In 1") and not row.get("Check Out 1"):
                check_out_col = 6 # Check-Out 1
                photo_col = 10    # Photo 1 update if needed
                check_in_time_str = row.get("Check In 1")
            elif row.get("Check In 2") and not row.get("Check Out 2"):
                check_out_col = 8 # Check-Out 2
                photo_col = 11    # Photo 2
                check_in_time_str = row.get("Check In 2")
            else:
                return jsonify({"status": "error", "message": "No active session to check out from."}), 400

            sheet.update_cell(target_row, check_out_col, time_str)
            if image_data:
                sheet.update_cell(target_row, photo_col, img_formula)

            # Calculate cumulative hours across sessions if needed or simple delta
            try:
                ci_time = datetime.strptime(f"{date_str} {check_in_time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
                session_hrs = (now - ci_time).total_seconds() / 3600
                
                # Read existing hours or add up
                current_total_str = str(row.get("Total Hours", "0")).replace(" hrs", "")
                existing_hrs = float(current_total_str) if current_total_str else 0.0
                total_hrs = round(existing_hrs + session_hrs, 2)
                
                sheet.update_cell(target_row, 9, f"{total_hrs} hrs")
            except Exception as ex:
                print(f"Hours calc error: {ex}")

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

@app.route("/leave", methods=["POST"])
def leave_route():
    return process_attendance("leave")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
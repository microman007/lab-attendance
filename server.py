import os
import json
import base64
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# Google Sheets Setup (Dual-mode: Local file or Render Environment Variable)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

try:
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if credentials_json:
        creds_dict = json.loads(credentials_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    
    client = gspread.authorize(creds)
    sheet = client.open("Lab Attendance").sheet1
    print("Connected to Google Sheets successfully!")
except Exception as e:
    print(f"Google Sheets Connection Error: {e}")

@app.route("/")
def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return render_template_string(f.read())

@app.route("/attendance", methods=["POST"])
def handle_attendance():
    try:
        data = request.json
        action = data.get("action")  # 'in' or 'out'
        user_id = data.get("user_id", "Arvind")
        lat = data.get("latitude")
        lon = data.get("longitude")
        image_data = data.get("image")  # Base64 string from webcam

        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # Format image for Google Sheets IMAGE() formula if provided
        img_formula = f'=IMAGE("{image_data}")' if image_data else ""

        records = sheet.get_all_records()

        if action == "in":
            # Check if there is an active session (Checked In without Check Out)
            active_row = None
            for idx, row in enumerate(records, start=2): # Row 2 is first data row
                if str(row.get("User ID")) == str(user_id) and not row.get("Check Out"):
                    active_row = idx
                    break
            
            if active_row:
                return jsonify({"status": "error", "message": "Already Checked In! Please Check Out first."}), 400

            # Append new row for Check-In
            # Columns: User ID (A), Check In (B), Check Out (C), Hours (D), Lat (E), Lon (F), Status (G), Check-In Photo (H), Check-Out Photo (I)
            row_data = [user_id, timestamp, "", "", lat, lon, "Checked In", img_formula, ""]
            sheet.append_row(row_data, value_input_option='USER_ENTERED')
            return jsonify({"status": "success", "message": "Successfully Checked IN!"})

        elif action == "out":
            # Find the active check-in row
            active_row = None
            check_in_time_str = None
            for idx, row in enumerate(records, start=2):
                if str(row.get("User ID")) == str(user_id) and not row.get("Check Out"):
                    active_row = idx
                    check_in_time_str = row.get("Check In")
                    break
            
            if not active_row:
                return jsonify({"status": "error", "message": "No active Check-In found. Please Check In first."}), 400

            # Calculate hours present
            try:
                check_in_time = datetime.strptime(check_in_time_str, "%Y-%m-%d %H:%M:%S")
                hours_present = round((now - check_in_time).total_seconds() / 3600, 2)
                hours_str = f"{hours_present} hrs"
            except Exception:
                hours_str = "0 hrs"

            # Update Check Out (Col C), Hours (Col D), Status (Col G), and Check-Out Photo (Col I)
            sheet.update_cell(active_row, 3, timestamp)
            sheet.update_cell(active_row, 4, hours_str)
            sheet.update_cell(active_row, 7, "Completed")
            if img_formula:
                sheet.update_cell(active_row, 9, img_formula)

            return jsonify({"status": "success", "message": "Successfully Checked OUT!"})

        return jsonify({"status": "error", "message": "Invalid action."}), 400

    except Exception as e:
        print(f"Error handling attendance: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
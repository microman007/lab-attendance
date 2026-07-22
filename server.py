import os
import json
import base64
import requests
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify, render_template_string
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

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
    print("Connected to Google Sheets successfully!")
except Exception as e:
    print(f"Google Connection Error: {e}")

def upload_base64_to_imgbb(base64_data, filename):
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
        lat = data.get("latitude") or data.get("lat", "")
        lon = data.get("longitude") or data.get("lon", "")
        image_data = data.get("image") or data.get("face_image", "")
        leave_reason = data.get("leave_reason", "")

        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        file_suffix = now.strftime("%Y%m%d_%H%M%S")
        
        action_label = "IN" if action == "in" else ("OUT" if action == "out" else "LEAVE")
        photo_filename = f"{user_id}_{action_label}_{file_suffix}.jpg"
        
        img_formula = ""
        if image_data:
            public_url = upload_base64_to_imgbb(image_data, photo_filename)
            if public_url:
                img_formula = f'=HYPERLINK("{public_url}", IMAGE("{public_url}"))'
            else:
                img_formula = photo_filename

        records = sheet.get_all_records()

        # Find if a single row already exists for today
        target_row = None
        for idx, row in enumerate(records, start=2):
            if str(row.get("User ID")) == str(user_id) and str(row.get("Date")) == date_str:
                target_row = idx
                break

        # Handle Leave Option
        if action == "leave":
            status_val = "On Leave"
            if target_row:
                sheet.update_cell(target_row, 3, status_val) # Status
                sheet.update_cell(target_row, 4, f"Leave: {leave_reason}") # Total Hours or Notes
            else:
                # User ID(A), Date(B), Status(C), Notes(D), CI1(E), CO1(F), CI2(G), CO2(H), CI3(I), CO3(H->J), CI4(K), CO4(L)...
                row_data = [user_id, date_str, status_val, f"Leave: {leave_reason}", "", "", "", "", "", "", "", "", "0 hrs"]
                sheet.append_row(row_data, value_input_option='USER_ENTERED')
            return jsonify({"status": "success", "message": "Leave status recorded successfully!"})

        # Determine OnTime vs Late based on 9:30 AM cutoff for the first check-in of the day
        cutoff_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        base_status = "OnTime/Present" if now <= cutoff_time else "Late/Present"

        if action == "in":
            if target_row:
                row = records[target_row - 2]
                # Check available slot (up to 4 check-ins)
                # Columns mapping for Check-In / Check-Out pairs:
                # E: Check-In 1, F: Check-Out 1
                # G: Check-In 2, H: Check-Out 2
                # I: Check-In 3, J: Check-Out 3
                # K: Check-In 4, L: Check-Out 4
                if not row.get("Check-Out 1"):
                    return jsonify({"status": "error", "message": "Please Check Out of Session 1 first."}), 400
                elif row.get("Check-Out 1") and not row.get("Check-In 2"):
                    sheet.update_cell(target_row, 7, time_str)   # Check-In 2 (Col G)
                    sheet.update_cell(target_row, 3, "In Lab (Active)") # Live Status update
                elif row.get("Check-Out 2") and not row.get("Check-In 3"):
                    sheet.update_cell(target_row, 9, time_str)   # Check-In 3 (Col I)
                    sheet.update_cell(target_row, 3, "In Lab (Active)")
                elif row.get("Check-Out 3") and not row.get("Check-In 4"):
                    sheet.update_cell(target_row, 11, time_str)  # Check-In 4 (Col K)
                    sheet.update_cell(target_row, 3, "In Lab (Active)")
                else:
                    return jsonify({"status": "error", "message": "Maximum 4 check-ins reached for today."}), 400
            else:
                # Create a fresh single-row entry for today with 4-session capacity
                # Col A: User ID, Col B: Date, Col C: Live Status, Col D: Notes/Extra, 
                # Col E: CI1, Col F: CO1, Col G: CI2, Col H: CO2, Col I: CI3, Col J: CO3, Col K: CI4, Col L: CO4, Col M: Total Hours
                row_data = [user_id, date_str, "In Lab (Active)", "", time_str, "", "", "", "", "", "", "", "0 hrs"]
                sheet.append_row(row_data, value_input_option='USER_ENTERED')

            return jsonify({"status": "success", "message": "Successfully Checked IN! [Live Status: In Lab (Active)]"})

        elif action == "out":
            if not target_row:
                return jsonify({"status": "error", "message": "No active session found for today."}), 400
            
            row = records[target_row - 2]
            
            # Find which active session needs checkout
            ci_col_idx, co_col_idx = None, None
            if row.get("Check-In 1") and not row.get("Check-Out 1"):
                ci_col_idx, co_col_idx = 5, 6
            elif row.get("Check-In 2") and not row.get("Check-Out 2"):
                ci_col_idx, co_col_idx = 7, 8
            elif row.get("Check-In 3") and not row.get("Check-Out 3"):
                ci_col_idx, co_col_idx = 9, 10
            elif row.get("Check-In 4") and not row.get("Check-Out 4"):
                ci_col_idx, co_col_idx = 11, 12
            else:
                return jsonify({"status": "error", "message": "No active check-in session found to check out from."}), 400

            sheet.update_cell(target_row, co_col_idx, time_str)
            sheet.update_cell(target_row, 3, "Checked Out") # Live Status update when leaving lab

            # Recalculate total hours accumulated across sessions
            try:
                # Pull updated row values to calculate total span
                updated_row = sheet.row_values(target_row)
                total_seconds = 0
                
                # Pairs are indices (4,5), (6,7), (8,9), (10,11) in 0-indexed python list
                pairs = [(4, 5), (6, 7), (8, 9), (10, 11)]
                for ci_idx, co_idx in pairs:
                    if len(updated_row) > co_idx and updated_row[ci_idx] and updated_row[co_idx]:
                        t_in = datetime.strptime(updated_row[ci_idx], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
                        t_out = datetime.strptime(updated_row[co_idx], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
                        total_seconds += (t_out - t_in).total_seconds()
                
                total_hrs = round(total_seconds / 3600, 2)
                sheet.update_cell(target_row, 13, f"{total_hrs} hrs") # Column M for total hours
            except Exception as ex:
                print(f"Hours calculation error: {ex}")

            return jsonify({"status": "success", "message": "Successfully Checked OUT! [Live Status: Checked Out]"})

        return jsonify({"status": "error", "message": "Invalid action."}), 400

    except Exception as e:
        print(f"Error handling attendance: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
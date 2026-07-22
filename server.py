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

EXPECTED_HEADERS = [
    "User ID", "Date", "Live Status", "Latitude", "Longitude", "Notes",
    "Check-In 1", "Check-In 1 Photo", "Check-Out 1", "Check-Out 1 Photo",
    "Check-In 2", "Check-In 2 Photo", "Check-Out 2", "Check-Out 2 Photo",
    "Check-In 3", "Check-In 3 Photo", "Check-Out 3", "Check-Out 3 Photo",
    "Check-In 4", "Check-In 4 Photo", "Check-Out 4", "Check-Out 4 Photo",
    "Total Hours"
]

try:
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if credentials_json:
        creds_dict = json.loads(credentials_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    
    client = gspread.authorize(creds)
    sheet = client.open("Lab Attendance").sheet1
    
    # Automatically verify and set sheet headers if missing or empty
    existing_headers = sheet.row_values(1)
    if not existing_headers or len(existing_headers) < len(EXPECTED_HEADERS):
        sheet.insert_row(EXPECTED_HEADERS, 1)
        print("Sheet headers initialized successfully!")
    else:
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
            public_url = result["data"]["url"]
            return f'=HYPERLINK("{public_url}", IMAGE("{public_url}"))'
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
        lat = str(data.get("latitude") or data.get("lat", ""))
        lon = str(data.get("longitude") or data.get("lon", ""))
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
            img_formula = upload_base64_to_imgbb(image_data, photo_filename)

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
                sheet.update_cell(target_row, 3, status_val) # Live Status (Col C)
                sheet.update_cell(target_row, 4, lat)        # Lat (Col D)
                sheet.update_cell(target_row, 5, lon)        # Lon (Col E)
                sheet.update_cell(target_row, 6, f"Leave: {leave_reason}") # Notes (Col F)
            else:
                row_data = [user_id, date_str, status_val, lat, lon, f"Leave: {leave_reason}"] + [""] * 16 + ["0 hrs"]
                sheet.append_row(row_data, value_input_option='USER_ENTERED')
            return jsonify({"status": "success", "message": "Leave status recorded successfully!"})

        if action == "in":
            if target_row:
                row = records[target_row - 2]
                if lat:
                    sheet.update_cell(target_row, 4, lat)
                if lon:
                    sheet.update_cell(target_row, 5, lon)

                if row.get("Check-In 1") and not row.get("Check-Out 1"):
                    return jsonify({"status": "error", "message": "Please Check Out of Session 1 first."}), 400
                elif row.get("Check-Out 1") and not row.get("Check-In 2"):
                    sheet.update_cell(target_row, 11, time_str)  # Check-In 2 (Col K)
                    sheet.update_cell(target_row, 12, img_formula) # Check-In 2 Photo (Col L)
                    sheet.update_cell(target_row, 3, "In Lab")
                elif row.get("Check-Out 2") and not row.get("Check-In 3"):
                    sheet.update_cell(target_row, 15, time_str)  # Check-In 3 (Col O)
                    sheet.update_cell(target_row, 16, img_formula) # Check-In 3 Photo (Col P)
                    sheet.update_cell(target_row, 3, "In Lab")
                elif row.get("Check-Out 3") and not row.get("Check-In 4"):
                    sheet.update_cell(target_row, 19, time_str)  # Check-In 4 (Col S)
                    sheet.update_cell(target_row, 20, img_formula) # Check-In 4 Photo (Col T)
                    sheet.update_cell(target_row, 3, "In Lab")
                else:
                    return jsonify({"status": "error", "message": "Maximum 4 check-ins reached for today."}), 400
            else:
                row_data = [user_id, date_str, "In Lab", lat, lon, "", time_str, img_formula] + [""] * 14 + ["0 hrs"]
                sheet.append_row(row_data, value_input_option='USER_ENTERED')

            return jsonify({"status": "success", "message": "Successfully Checked IN! [Live Status: In Lab]"})

        elif action == "out":
            if not target_row:
                return jsonify({"status": "error", "message": "No active session found for today."}), 400
            
            row = records[target_row - 2]
            
            co_col_idx, photo_col_idx = None, None
            if row.get("Check-In 1") and not row.get("Check-Out 1"):
                co_col_idx, photo_col_idx = 9, 10   # Col I & J
            elif row.get("Check-In 2") and not row.get("Check-Out 2"):
                co_col_idx, photo_col_idx = 13, 14 # Col M & N
            elif row.get("Check-In 3") and not row.get("Check-Out 3"):
                co_col_idx, photo_col_idx = 17, 18 # Col Q & R
            elif row.get("Check-In 4") and not row.get("Check-Out 4"):
                co_col_idx, photo_col_idx = 21, 22 # Col U & V
            else:
                return jsonify({"status": "error", "message": "No active check-in session found to check out from."}), 400

            sheet.update_cell(target_row, co_col_idx, time_str)
            if img_formula:
                sheet.update_cell(target_row, photo_col_idx, img_formula)
            sheet.update_cell(target_row, 3, "Checked Out")

            try:
                updated_row = sheet.row_values(target_row)
                total_seconds = 0
                pairs = [(6, 8), (10, 12), (14, 16), (18, 20)]
                for ci_idx, co_idx in pairs:
                    if len(updated_row) > co_idx and updated_row[ci_idx] and updated_row[co_idx]:
                        t_in = datetime.strptime(updated_row[ci_idx], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
                        t_out = datetime.strptime(updated_row[co_idx], "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
                        total_seconds += (t_out - t_in).total_seconds()
                
                total_hrs = round(total_seconds / 3600, 2)
                sheet.update_cell(target_row, 23, f"{total_hrs} hrs") # Col W for total hours
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
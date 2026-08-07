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
    
    existing_headers = sheet.row_values(1)
    if not existing_headers or len(existing_headers) < len(EXPECTED_HEADERS):
        sheet.insert_row(EXPECTED_HEADERS, 1)
        print("Sheet headers initialized successfully!")
    else:
        print("Connected to Google Sheets successfully!")

except Exception as e:
    print(f"Google Connection Error: {e}")

def upload_to_freeimage(base64_data, filename):
    try:
        if "," in base64_data:
            base64_data = base64_data.split(",")[1]
        
        image_bytes = base64.b64decode(base64_data)
        
        # Using freeimage.host free anonymous upload API
        url = "https://freeimage.host/api/1/upload"
        payload = {
            "key": "6d207e02198a847aa98d0a2a901485a5", # Free public community key
            "action": "upload",
            "format": "json"
        }
        files = {
            "source": (filename, image_bytes, "image/jpeg")
        }
        
        print(f"Uploading image {filename} to FreeImage...")
        response = requests.post(url, data=payload, files=files, timeout=20)
        result = response.json()
        
        if response.status_code == 200 and result.get("status_code") == 200:
            public_url = result["image"]["url"]
            print(f"Image uploaded successfully: {public_url}")
            # Fixed formula: valid Google Sheets HYPERLINK syntax
            return f'=HYPERLINK("{public_url}", "📷 View Photo")'
        else:
            print(f"FreeImage API Error Response: {result}")
            return ""
    except Exception as e:
        print(f"Image Upload Exception Error: {e}")
        return ""

def update_stale_sessions(current_date_str):
    try:
        records = sheet.get_all_records()
        for idx, row in enumerate(records, start=2):
            if row.get("Live Status") == "In Lab":
                row_date = str(row.get("Date"))
                if row_date and row_date != current_date_str:
                    sheet.update_cell(idx, 3, "Checkout Remaining")
    except Exception as e:
        print(f"Stale session update error: {e}")

@app.route("/")
def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return render_template_string(f.read())

def process_attendance(action):
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "No JSON payload received."}), 400

        user_id = data.get("user_name") or data.get("user_id", "Arvind Kayande")
        lat = str(data.get("latitude") or data.get("lat", ""))
        lon = str(data.get("longitude") or data.get("lon", ""))
        image_data = data.get("image") or data.get("face_image", "")
        leave_reason = data.get("leave_reason", "")
        lab_location = data.get("lab_location", "")

        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        file_suffix = now.strftime("%Y%m%d_%H%M%S")
        
        update_stale_sessions(date_str)

        action_label = "IN" if action == "in" else ("OUT" if action == "out" else "LEAVE")
        photo_filename = f"{user_id.replace(' ', '_')}_{action_label}_{file_suffix}.jpg"
        
        img_formula = ""
        if image_data:
            img_formula = upload_to_freeimage(image_data, photo_filename)
        else:
            print("Warning: No image data received from frontend!")

        records = sheet.get_all_records()

        target_row = None
        for idx, row in enumerate(records, start=2):
            if str(row.get("User ID")) == str(user_id) and str(row.get("Date")) == date_str:
                target_row = idx
                break

        if action == "leave":
            status_val = "On Leave"
            notes_val = f"Leave: {leave_reason}" + (f" | Lab: {lab_location}" if lab_location else "")
            if target_row:
                sheet.update_cell(target_row, 3, status_val)
                sheet.update_cell(target_row, 4, lat)
                sheet.update_cell(target_row, 5, lon)
                sheet.update_cell(target_row, 6, notes_val)
            else:
                row_data = [user_id, date_str, status_val, lat, lon, notes_val] + [""] * 16 + ["0 hrs"]
                sheet.append_row(row_data, value_input_option='USER_ENTERED')
            return jsonify({"status": "success", "message": "Leave status recorded successfully!"})

        if action == "in":
            notes_val = f"Lab: {lab_location}" if lab_location else ""
            if target_row:
                row = records[target_row - 2]
                if lat:
                    sheet.update_cell(target_row, 4, lat)
                if lon:
                    sheet.update_cell(target_row, 5, lon)
                if notes_val:
                    sheet.update_cell(target_row, 6, notes_val)

                if row.get("Check-In 1") and not row.get("Check-Out 1"):
                    return jsonify({"status": "error", "message": "Please Check Out of Session 1 first."}), 400
                elif row.get("Check-Out 1") and not row.get("Check-In 2"):
                    sheet.update_cell(target_row, 11, time_str)
                    sheet.update_cell(target_row, 12, img_formula)
                    sheet.update_cell(target_row, 3, "In Lab")
                elif row.get("Check-Out 2") and not row.get("Check-In 3"):
                    sheet.update_cell(target_row, 15, time_str)
                    sheet.update_cell(target_row, 16, img_formula)
                    sheet.update_cell(target_row, 3, "In Lab")
                elif row.get("Check-Out 3") and not row.get("Check-In 4"):
                    sheet.update_cell(target_row, 19, time_str)
                    sheet.update_cell(target_row, 20, img_formula)
                    sheet.update_cell(target_row, 3, "In Lab")
                else:
                    return jsonify({"status": "error", "message": "Maximum 4 check-ins reached for today."}), 400
            else:
                row_data = [user_id, date_str, "In Lab", lat, lon, notes_val, time_str, img_formula] + [""] * 14 + ["0 hrs"]
                sheet.append_row(row_data, value_input_option='USER_ENTERED')

            return jsonify({"status": "success", "message": f"Successfully Checked IN at {lab_location or 'Lab'}! [Live Status: In Lab]"})

        elif action == "out":
            if not target_row:
                return jsonify({"status": "error", "message": "No active session found for today."}), 400
            
            row = records[target_row - 2]
            
            co_col_idx, photo_col_idx = None, None
            if row.get("Check-In 1") and not row.get("Check-Out 1"):
                co_col_idx, photo_col_idx = 9, 10
            elif row.get("Check-In 2") and not row.get("Check-Out 2"):
                co_col_idx, photo_col_idx = 13, 14
            elif row.get("Check-In 3") and not row.get("Check-Out 3"):
                co_col_idx, photo_col_idx = 17, 18
            elif row.get("Check-In 4") and not row.get("Check-Out 4"):
                co_col_idx, photo_col_idx = 21, 22
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
                sheet.update_cell(target_row, 23, f"{total_hrs} hrs")
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

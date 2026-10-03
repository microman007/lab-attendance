import base64
import json
import os
from datetime import datetime, timedelta, timezone

from flask import (
    Flask,
    jsonify,
    render_template_string,
    request,
    send_from_directory,
)
from google.oauth2.service_account import Credentials
import gspread

# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)


# ============================================================
# GOOGLE API SCOPES
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ============================================================
# GOOGLE SHEETS HEADERS
# ============================================================

EXPECTED_HEADERS = [
    "User ID",
    "Date",
    "Day of Week",
    "Live Status",
    "Latitude",
    "Longitude",
    "Notes",
    "Check-In 1",
    "Check-In 1 Photo",
    "Check-Out 1",
    "Check-Out 1 Photo",
    "Check-In 2",
    "Check-In 2 Photo",
    "Check-Out 2",
    "Check-Out 2 Photo",
    "Check-In 3",
    "Check-In 3 Photo",
    "Check-Out 3",
    "Check-Out 3 Photo",
    "Check-In 4",
    "Check-In 4 Photo",
    "Check-Out 4",
    "Check-Out 4 Photo",
    "Break Taken",
    "Total Hours",
]


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

try:
  credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")

  if credentials_json:
    creds_dict = json.loads(credentials_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
  else:
    creds = Credentials.from_service_account_file(
        "credentials.json", scopes=SCOPES
    )

  client = gspread.authorize(creds)
  sheet = client.open("Lab Attendance").sheet1

  # --------------------------------------------------------
  # Automatically verify and set sheet headers
  # --------------------------------------------------------

  existing_headers = sheet.row_values(1)

  if not existing_headers or len(existing_headers) < len(EXPECTED_HEADERS):
    sheet.insert_row(EXPECTED_HEADERS, 1)
    print("Sheet headers initialized successfully!")
  else:
    print("Connected to Google Sheets successfully!")


except Exception as e:
  print("Google Connection Error:", repr(e))


# ============================================================
# LOCAL PHOTO STORAGE FUNCTION
# ============================================================


def save_photo_locally(base64_data, filename):
  try:
    if not base64_data:
      print("No image data received.")
      return ""

    if "," in base64_data:
      base64_data = base64_data.split(",", 1)[1]

    image_bytes = base64.b64decode(base64_data)

    # Ensure local directory exists
    os.makedirs("static/photos", exist_ok=True)
    file_path = os.path.join("static/photos", filename)

    with open(file_path, "wb") as f:
      f.write(image_bytes)

    # Generate public URL using Render host domain dynamically
    base_url = request.host_url.rstrip("/")
    public_url = f"{base_url}/photos/{filename}"

    # Create Google Sheets formula rendering both the image thumbnail and hyperlink
    formula = f'=HYPERLINK("{public_url}", IMAGE("{public_url}"))'
    print(f"Local photo saved successfully: {public_url}")

    return formula

  except Exception as e:
    print("LOCAL IMAGE SAVE ERROR:", repr(e))
    return ""


# ============================================================
# SERVE LOCAL PHOTOS ROUTE
# ============================================================


@app.route("/photos/<filename>")
def serve_photo(filename):
  return send_from_directory("static/photos", filename)


# ============================================================
# HOME PAGE
# ============================================================


@app.route("/")
def index():
  with open("index.html", "r", encoding="utf-8") as f:
    return render_template_string(f.read())


# ============================================================
# ATTENDANCE PROCESSING
# ============================================================


def process_attendance(action):
  try:
    # ----------------------------------------------------
    # Read JSON request
    # ----------------------------------------------------

    data = request.json

    if not data:
      return (
          jsonify(
              {"status": "error", "message": "No JSON payload received."}
          ),
          400,
      )

    # ----------------------------------------------------
    # USER ID
    # ----------------------------------------------------

    user_id = data.get("user_id") or data.get("user_name") or "Arvind"

    # ----------------------------------------------------
    # GPS LATITUDE & LONGITUDE
    # ----------------------------------------------------

    lat = str(data.get("latitude") or data.get("lat") or "")

    lon = str(data.get("longitude") or data.get("lon") or "")

    # ----------------------------------------------------
    # IMAGE DATA
    # ----------------------------------------------------

    image_data = data.get("image") or data.get("face_image") or ""

    # ----------------------------------------------------
    # LEAVE REASON
    # ----------------------------------------------------

    leave_reason = data.get("leave_reason", "")

    # ====================================================
    # INDIA TIMEZONE
    # ====================================================

    IST = timezone(timedelta(hours=5, minutes=30))

    now = datetime.now(IST)

    date_str = now.strftime("%Y-%m-%d")
    day_str = now.strftime("%a")  # e.g., Mon, Tue, Wed, etc.
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    file_suffix = now.strftime("%Y%m%d_%H%M%S")

    # ====================================================
    # PHOTO FILE NAME
    # ====================================================

    action_label = (
        "IN"
        if action == "in"
        else ("OUT" if action == "out" else "LEAVE")
    )

    # Sanitize user_id to remove spaces for a clean URL
    safe_user_id = str(user_id).replace(" ", "_")

    photo_filename = f"{safe_user_id}_{action_label}_{file_suffix}.jpg"

    # ====================================================
    # SAVE PHOTO LOCALLY
    # ====================================================

    img_formula = ""

    if image_data:
      print("Photo received from browser.")
      img_formula = save_photo_locally(image_data, photo_filename)
      if img_formula:
        print("Photo URL/formula generated successfully.")
      else:
        print(
            "WARNING: Photo save failed. Attendance will continue without"
            " photo."
        )
    else:
      print("No photo was included in the request.")

    # ====================================================
    # GET EXISTING RECORDS
    # ====================================================

    records = sheet.get_all_records()

    # ====================================================
    # AUTO-CLOSE OLD OPEN SESSIONS FROM PREVIOUS DAYS
    # ====================================================
    try:
      for idx, row in enumerate(records, start=2):
        row_user = str(row.get("User ID"))
        row_date = str(row.get("Date"))
        live_status = str(row.get("Live Status"))

        if (
            row_date
            and row_date < date_str
            and live_status == "In Lab"
        ):
          sheet.update_cell(idx, 4, "Checked-Out-Remained")
          print(
              f"Auto-updated old session on {row_date} for {user_id} to"
              " Checked-Out-Remained"
          )

      records = sheet.get_all_records()
    except Exception as ex:
      print("Error auto-updating old sessions:", repr(ex))

    # ====================================================
    # FIND TODAY'S ROW FOR THIS USER
    # ====================================================

    target_row = None

    for idx, row in enumerate(records, start=2):
      if str(row.get("User ID")) == str(user_id) and str(row.get("Date")) == str(
          date_str
      ):
        target_row = idx
        break

    # ====================================================
    # LEAVE
    # ====================================================

    if action == "leave":
      status_val = "On Leave"

      if target_row:
        sheet.update_cell(target_row, 4, status_val)
        sheet.update_cell(target_row, 5, lat)
        sheet.update_cell(target_row, 6, lon)
        sheet.update_cell(target_row, 7, f"Leave: {leave_reason}")
      else:
        row_data = (
            [
                user_id,
                date_str,
                day_str,
                status_val,
                lat,
                lon,
                f"Leave: {leave_reason}",
            ]
            + [""] * 17
            + ["0 hrs", "0 hrs"]
        )

        sheet.append_row(row_data, value_input_option="USER_ENTERED")

      return jsonify(
          {"status": "success", "message": "Leave status recorded successfully!"}
      )

    # ====================================================
    # CHECK IN
    # ====================================================

    if action == "in":

      if target_row:
        row = records[target_row - 2]

        if lat:
          sheet.update_cell(target_row, 5, lat)

        if lon:
          sheet.update_cell(target_row, 6, lon)

        # SESSION 1
        if row.get("Check-In 1") and not row.get("Check-Out 1"):
          return (
              jsonify({
                  "status": "error",
                  "message": "Please Check Out of Session 1 first.",
              }),
              400,
          )

        # SESSION 2
        elif row.get("Check-Out 1") and not row.get("Check-In 2"):
          sheet.update_cell(target_row, 12, time_str)
          sheet.update_cell(target_row, 13, img_formula)
          sheet.update_cell(target_row, 4, "In Lab")

        # SESSION 3
        elif row.get("Check-Out 2") and not row.get("Check-In 3"):
          sheet.update_cell(target_row, 16, time_str)
          sheet.update_cell(target_row, 17, img_formula)
          sheet.update_cell(target_row, 4, "In Lab")

        # SESSION 4
        elif row.get("Check-Out 3") and not row.get("Check-In 4"):
          sheet.update_cell(target_row, 20, time_str)
          sheet.update_cell(target_row, 21, img_formula)
          sheet.update_cell(target_row, 4, "In Lab")

        else:
          return (
              jsonify({
                  "status": "error",
                  "message": "Maximum 4 check-ins reached for today.",
              }),
              400,
          )

      else:
        # First Check-In of the day
        row_data = (
            [
                user_id,
                date_str,
                day_str,
                "In Lab",
                lat,
                lon,
                "",
                time_str,
                img_formula,
            ]
            + [""] * 14
            + ["0 hrs", "0 hrs"]
        )

        sheet.append_row(row_data, value_input_option="USER_ENTERED")

      return jsonify({
          "status": "success",
          "message": "Successfully Checked IN! [Live Status: In Lab]",
      })

    # ====================================================
    # CHECK OUT
    # ====================================================

    elif action == "out":

      if not target_row:
        return (
            jsonify({
                "status": "error",
                "message": "No active session found for today.",
            }),
            400,
        )

      row = records[target_row - 2]

      co_col_idx = None
      photo_col_idx = None

      # Session 1
      if row.get("Check-In 1") and not row.get("Check-Out 1"):
        co_col_idx = 10
        photo_col_idx = 11

      # Session 2
      elif row.get("Check-In 2") and not row.get("Check-Out 2"):
        co_col_idx = 14
        photo_col_idx = 15

      # Session 3
      elif row.get("Check-In 3") and not row.get("Check-Out 3"):
        co_col_idx = 18
        photo_col_idx = 19

      # Session 4
      elif row.get("Check-In 4") and not row.get("Check-Out 4"):
        co_col_idx = 22
        photo_col_idx = 23

      else:
        return (
            jsonify({
                "status": "error",
                "message": (
                    "No active check-in session found to check out from."
                ),
            }),
            400,
        )

      # Save check-out info
      sheet.update_cell(target_row, co_col_idx, time_str)

      if img_formula:
        sheet.update_cell(target_row, photo_col_idx, img_formula)

      sheet.update_cell(target_row, 4, "Checked Out")

      # Calculate total hours and breaks taken
      try:
        updated_row = sheet.row_values(target_row)
        work_seconds = 0
        break_seconds = 0

        work_pairs = [(7, 9), (11, 13), (15, 17), (19, 21)]
        session_times = []

        for ci_idx, co_idx in work_pairs:
          if (
              len(updated_row) > co_idx
              and updated_row[ci_idx]
              and updated_row[co_idx]
          ):
            t_in = datetime.strptime(
                updated_row[ci_idx], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=IST)
            t_out = datetime.strptime(
                updated_row[co_idx], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=IST)
            work_seconds += (t_out - t_in).total_seconds()
            session_times.append((t_in, t_out))

        # Calculate breaks between completed sessions
        session_times.sort(key=lambda x: x[0])
        for i in range(len(session_times) - 1):
          t_out_prev = session_times[i][1]
          t_in_next = session_times[i + 1][0]
          if t_in_next > t_out_prev:
            break_seconds += (t_in_next - t_out_prev).total_seconds()

        total_hrs = round(work_seconds / 3600, 2)
        break_hrs = round(break_seconds / 3600, 2)

        sheet.update_cell(target_row, 25, f"{total_hrs} hrs")
        sheet.update_cell(target_row, 24, f"{break_hrs} hrs")

      except Exception as ex:
        print("Hours/Break calculation error:", repr(ex))

      return jsonify({
          "status": "success",
          "message": "Successfully Checked OUT! [Live Status: Checked Out]",
      })

    return jsonify({"status": "error", "message": "Invalid action."}), 400

  except Exception as e:
    print("Error handling attendance:", repr(e))
    return jsonify({"status": "error", "message": str(e)}), 500


# ============================================================
# ROUTES
# ============================================================


@app.route("/checkin", methods=["POST"])
def checkin_route():
  return process_attendance("in")


@app.route("/checkout", methods=["POST"])
def checkout_route():
  return process_attendance("out")


@app.route("/leave", methods=["POST"])
def leave_route():
  return process_attendance("leave")


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":
  app.run(host="0.0.0.0", port=10000)

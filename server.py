import os
import json
import requests
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify, render_template_string
import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# FLASK APPLICATION
# ============================================================

app = Flask(__name__)


# ============================================================
# GOOGLE API SCOPES
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]


# ============================================================
# FREEIMAGE.HOST API KEY
#
# IMPORTANT:
# Store the API key in Render Environment Variables:
#
# FREEIMAGE_API_KEY
#
# Do NOT put the actual API key in GitHub.
# ============================================================

FREEIMAGE_API_KEY = os.environ.get("FREEIMAGE_API_KEY")


# ============================================================
# GOOGLE SHEETS HEADERS
# ============================================================

EXPECTED_HEADERS = [
    "User ID",
    "Date",
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

    "Total Hours"
]


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

try:

    credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")

    if credentials_json:

        creds_dict = json.loads(credentials_json)

        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=SCOPES
        )

    else:

        creds = Credentials.from_service_account_file(
            "credentials.json",
            scopes=SCOPES
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
# FREEIMAGE.HOST IMAGE UPLOAD
# ============================================================

def upload_base64_to_freeimage(base64_data, filename):

    try:

        # ----------------------------------------------------
        # Check image data
        # ----------------------------------------------------

        if not base64_data:

            print("No image data received.")

            return ""


        # ----------------------------------------------------
        # Remove:
        #
        # data:image/jpeg;base64,
        #
        # from Base64 string
        # ----------------------------------------------------

        if "," in base64_data:

            base64_data = base64_data.split(",", 1)[1]


        # ----------------------------------------------------
        # Check Freeimage API key
        # ----------------------------------------------------

        if not FREEIMAGE_API_KEY:

            print("ERROR: FREEIMAGE_API_KEY is not configured.")

            return ""


        # ----------------------------------------------------
        # Freeimage.host API
        #
        # IMPORTANT:
        # We are intentionally using the documented API
        # parameters only.
        #
        # DO NOT add album_id here.
        # ----------------------------------------------------

        payload = {

            "key": FREEIMAGE_API_KEY,

            "action": "upload",

            "source": base64_data,

            "format": "json"

        }


        # ----------------------------------------------------
        # Upload image
        # ----------------------------------------------------

        print("Uploading photo to Freeimage.host...")

        response = requests.post(

            "https://freeimage.host/api/1/upload",

            data=payload,

            timeout=60

        )


        # ----------------------------------------------------
        # Print HTTP response for Render logs
        # ----------------------------------------------------

        print(
            "Freeimage.host HTTP status:",
            response.status_code
        )


        # ----------------------------------------------------
        # Convert response to JSON
        # ----------------------------------------------------

        try:

            result = response.json()

        except ValueError:

            print(
                "Freeimage.host returned invalid JSON."
            )

            print(
                "Raw response:",
                response.text[:2000]
            )

            return ""


        # ----------------------------------------------------
        # Print API response
        #
        # This is very important for debugging.
        # ----------------------------------------------------

        print(
            "Freeimage.host response:",
            result
        )


        # ----------------------------------------------------
        # Check successful upload
        # ----------------------------------------------------

        if (

            response.ok

            and result.get("status_code") == 200

            and result.get("success")

            and result.get("image")

        ):

            image_info = result.get("image", {})


            # ------------------------------------------------
            # Direct image URL
            # ------------------------------------------------

            image_url = image_info.get("url")


            # ------------------------------------------------
            # Freeimage viewer URL
            # ------------------------------------------------

            viewer_url = image_info.get("url_viewer")


            print(
                "Freeimage upload SUCCESS."
            )

            print(
                "Filename:",
                filename
            )

            print(
                "Direct image URL:",
                image_url
            )

            print(
                "Viewer URL:",
                viewer_url
            )


            # ------------------------------------------------
            # Create Google Sheets formula
            #
            # IMAGE() displays the actual image.
            #
            # HYPERLINK() makes the image clickable and opens
            # the Freeimage viewer page.
            # ------------------------------------------------

            if image_url:

                if viewer_url:

                    formula = (
                        f'=HYPERLINK("{viewer_url}",'
                        f'IMAGE("{image_url}"))'
                    )

                else:

                    formula = (
                        f'=IMAGE("{image_url}")'
                    )


                return formula


        # ----------------------------------------------------
        # Upload failed
        # ----------------------------------------------------

        print(
            "Freeimage.host upload FAILED."
        )

        print(
            "API result:",
            result
        )

        return ""


    except requests.exceptions.Timeout:

        print(
            "Freeimage.host upload TIMEOUT."
        )

        return ""


    except requests.exceptions.RequestException as e:

        print(
            "Freeimage.host REQUEST ERROR:",
            repr(e)
        )

        return ""


    except Exception as e:

        print(
            "Freeimage.host IMAGE UPLOAD ERROR:",
            repr(e)
        )

        return ""


# ============================================================
# HOME PAGE
# ============================================================

@app.route("/")
def index():

    with open(
        "index.html",
        "r",
        encoding="utf-8"
    ) as f:

        return render_template_string(
            f.read()
        )


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

            return jsonify({

                "status": "error",

                "message":
                "No JSON payload received."

            }), 400


        # ----------------------------------------------------
        # USER ID
        #
        # Supports:
        #
        # user_id
        # user_name
        # ----------------------------------------------------

        user_id = (

            data.get("user_id")

            or data.get("user_name")

            or "Arvind"

        )


        # ----------------------------------------------------
        # GPS LATITUDE
        # ----------------------------------------------------

        lat = str(

            data.get("latitude")

            or data.get("lat")

            or ""

        )


        # ----------------------------------------------------
        # GPS LONGITUDE
        # ----------------------------------------------------

        lon = str(

            data.get("longitude")

            or data.get("lon")

            or ""

        )


        # ----------------------------------------------------
        # IMAGE
        #
        # Supports:
        #
        # image
        # face_image
        # ----------------------------------------------------

        image_data = (

            data.get("image")

            or data.get("face_image")

            or ""

        )


        # ----------------------------------------------------
        # LEAVE REASON
        # ----------------------------------------------------

        leave_reason = data.get(
            "leave_reason",
            ""
        )


        # ====================================================
        # INDIA TIMEZONE
        # ====================================================

        IST = timezone(
            timedelta(hours=5, minutes=30)
        )


        now = datetime.now(IST)


        date_str = now.strftime(
            "%Y-%m-%d"
        )


        time_str = now.strftime(
            "%Y-%m-%d %H:%M:%S"
        )


        file_suffix = now.strftime(
            "%Y%m%d_%H%M%S"
        )


        # ====================================================
        # PHOTO FILE NAME
        # ====================================================

        action_label = (

            "IN"

            if action == "in"

            else (

                "OUT"

                if action == "out"

                else "LEAVE"

            )

        )


        photo_filename = (

            f"{user_id}_"
            f"{action_label}_"
            f"{file_suffix}.jpg"

        )


        # ====================================================
        # UPLOAD PHOTO
        # ====================================================

        img_formula = ""


        if image_data:

            print(
                "Photo received from browser."
            )

            img_formula = upload_base64_to_freeimage(

                image_data,

                photo_filename

            )

            if img_formula:

                print(
                    "Photo URL/formula generated successfully."
                )

            else:

                print(
                    "WARNING: Photo upload failed. "
                    "Attendance will continue without photo."
                )

        else:

            print(
                "No photo was included in the request."
            )


        # ====================================================
        # GET EXISTING RECORDS
        # ====================================================

        records = sheet.get_all_records()


        # ====================================================
        # FIND TODAY'S ROW FOR THIS USER
        # ====================================================

        target_row = None


        for idx, row in enumerate(
            records,
            start=2
        ):

            if (

                str(row.get("User ID"))

                == str(user_id)

                and

                str(row.get("Date"))

                == date_str

            ):

                target_row = idx

                break


        # ====================================================
        # LEAVE
        # ====================================================

        if action == "leave":

            status_val = "On Leave"


            if target_row:

                sheet.update_cell(
                    target_row,
                    3,
                    status_val
                )


                sheet.update_cell(
                    target_row,
                    4,
                    lat
                )


                sheet.update_cell(
                    target_row,
                    5,
                    lon
                )


                sheet.update_cell(
                    target_row,
                    6,
                    f"Leave: {leave_reason}"
                )


            else:

                row_data = (

                    [

                        user_id,

                        date_str,

                        status_val,

                        lat,

                        lon,

                        f"Leave: {leave_reason}"

                    ]

                    + [""] * 16

                    + ["0 hrs"]

                )


                sheet.append_row(

                    row_data,

                    value_input_option="USER_ENTERED"

                )


            return jsonify({

                "status": "success",

                "message":
                "Leave status recorded successfully!"

            })


        # ====================================================
        # CHECK IN
        # ====================================================

        if action == "in":


            # ------------------------------------------------
            # Existing row for today
            # ------------------------------------------------

            if target_row:

                row = records[
                    target_row - 2
                ]


                # --------------------------------------------
                # Update GPS
                # --------------------------------------------

                if lat:

                    sheet.update_cell(

                        target_row,
                        4,
                        lat

                    )


                if lon:

                    sheet.update_cell(

                        target_row,
                        5,
                        lon

                    )


                # --------------------------------------------
                # SESSION 1
                # --------------------------------------------

                if (

                    row.get("Check-In 1")

                    and

                    not row.get("Check-Out 1")

                ):

                    return jsonify({

                        "status": "error",

                        "message":
                        "Please Check Out of Session 1 first."

                    }), 400


                # --------------------------------------------
                # SESSION 2
                # --------------------------------------------

                elif (

                    row.get("Check-Out 1")

                    and

                    not row.get("Check-In 2")

                ):

                    sheet.update_cell(

                        target_row,
                        11,
                        time_str

                    )


                    sheet.update_cell(

                        target_row,
                        12,
                        img_formula

                    )


                    sheet.update_cell(

                        target_row,
                        3,
                        "In Lab"

                    )


                # --------------------------------------------
                # SESSION 3
                # --------------------------------------------

                elif (

                    row.get("Check-Out 2")

                    and

                    not row.get("Check-In 3")

                ):

                    sheet.update_cell(

                        target_row,
                        15,
                        time_str

                    )


                    sheet.update_cell(

                        target_row,
                        16,
                        img_formula

                    )


                    sheet.update_cell(

                        target_row,
                        3,
                        "In Lab"

                    )


                # --------------------------------------------
                # SESSION 4
                # --------------------------------------------

                elif (

                    row.get("Check-Out 3")

                    and

                    not row.get("Check-In 4")

                ):

                    sheet.update_cell(

                        target_row,
                        19,
                        time_str

                    )


                    sheet.update_cell(

                        target_row,
                        20,
                        img_formula

                    )


                    sheet.update_cell(

                        target_row,
                        3,
                        "In Lab"

                    )


                else:

                    return jsonify({

                        "status": "error",

                        "message":
                        "Maximum 4 check-ins reached for today."

                    }), 400


            # ------------------------------------------------
            # First Check-In of the day
            # ------------------------------------------------

            else:

                row_data = (

                    [

                        user_id,

                        date_str,

                        "In Lab",

                        lat,

                        lon,

                        "",

                        time_str,

                        img_formula

                    ]

                    + [""] * 14

                    + ["0 hrs"]

                )


                sheet.append_row(

                    row_data,

                    value_input_option="USER_ENTERED"

                )


            return jsonify({

                "status": "success",

                "message":
                "Successfully Checked IN! "
                "[Live Status: In Lab]"

            })


        # ====================================================
        # CHECK OUT
        # ====================================================

        elif action == "out":


            # ------------------------------------------------
            # No attendance row
            # ------------------------------------------------

            if not target_row:

                return jsonify({

                    "status": "error",

                    "message":
                    "No active session found for today."

                }), 400


            row = records[
                target_row - 2
            ]


            # ------------------------------------------------
            # Determine active session
            # ------------------------------------------------

            co_col_idx = None

            photo_col_idx = None


            # --------------------------------------------
            # Session 1
            # --------------------------------------------

            if (

                row.get("Check-In 1")

                and

                not row.get("Check-Out 1")

            ):

                co_col_idx = 9

                photo_col_idx = 10


            # --------------------------------------------
            # Session 2
            # --------------------------------------------

            elif (

                row.get("Check-In 2")

                and

                not row.get("Check-Out 2")

            ):

                co_col_idx = 13

                photo_col_idx = 14


            # --------------------------------------------
            # Session 3
            # --------------------------------------------

            elif (

                row.get("Check-In 3")

                and

                not row.get("Check-Out 3")

            ):

                co_col_idx = 17

                photo_col_idx = 18


            # --------------------------------------------
            # Session 4
            # --------------------------------------------

            elif (

                row.get("Check-In 4")

                and

                not row.get("Check-Out 4")

            ):

                co_col_idx = 21

                photo_col_idx = 22


            else:

                return jsonify({

                    "status": "error",

                    "message":
                    "No active check-in session "
                    "found to check out from."

                }), 400


            # =================================================
            # SAVE CHECK-OUT TIME
            # =================================================

            sheet.update_cell(

                target_row,
                co_col_idx,
                time_str

            )


            # =================================================
            # SAVE CHECK-OUT PHOTO
            # =================================================

            if img_formula:

                sheet.update_cell(

                    target_row,
                    photo_col_idx,
                    img_formula

                )


            # =================================================
            # UPDATE LIVE STATUS
            # =================================================

            sheet.update_cell(

                target_row,
                3,
                "Checked Out"

            )


            # =================================================
            # CALCULATE TOTAL HOURS
            # =================================================

            try:

                updated_row = sheet.row_values(
                    target_row
                )


                total_seconds = 0


                # ------------------------------------------------
                # ZERO-BASED INDEXES
                #
                # G/I = Session 1
                # K/M = Session 2
                # O/Q = Session 3
                # S/U = Session 4
                # ------------------------------------------------

                pairs = [

                    (6, 8),

                    (10, 12),

                    (14, 16),

                    (18, 20)

                ]


                for ci_idx, co_idx in pairs:

                    if (

                        len(updated_row) > co_idx

                        and

                        updated_row[ci_idx]

                        and

                        updated_row[co_idx]

                    ):

                        t_in = datetime.strptime(

                            updated_row[ci_idx],

                            "%Y-%m-%d %H:%M:%S"

                        ).replace(
                            tzinfo=IST
                        )


                        t_out = datetime.strptime(

                            updated_row[co_idx],

                            "%Y-%m-%d %H:%M:%S"

                        ).replace(
                            tzinfo=IST
                        )


                        total_seconds += (

                            t_out - t_in

                        ).total_seconds()


                total_hrs = round(

                    total_seconds / 3600,

                    2

                )


                # ------------------------------------------------
                # Column W = Total Hours
                # ------------------------------------------------

                sheet.update_cell(

                    target_row,
                    23,
                    f"{total_hrs} hrs"

                )


            except Exception as ex:

                print(
                    "Hours calculation error:",
                    repr(ex)
                )


            return jsonify({

                "status": "success",

                "message":
                "Successfully Checked OUT! "
                "[Live Status: Checked Out]"

            })


        # ====================================================
        # INVALID ACTION
        # ====================================================

        return jsonify({

            "status": "error",

            "message":
            "Invalid action."

        }), 400


    except Exception as e:

        print(
            "Error handling attendance:",
            repr(e)
        )


        return jsonify({

            "status": "error",

            "message": str(e)

        }), 500


# ============================================================
# CHECK-IN ROUTE
# ============================================================

@app.route(
    "/checkin",
    methods=["POST"]
)
def checkin_route():

    return process_attendance("in")


# ============================================================
# CHECK-OUT ROUTE
# ============================================================

@app.route(
    "/checkout",
    methods=["POST"]
)
def checkout_route():

    return process_attendance("out")


# ============================================================
# LEAVE ROUTE
# ============================================================

@app.route(
    "/leave",
    methods=["POST"]
)
def leave_route():

    return process_attendance("leave")


# ============================================================
# APPLICATION START
# ============================================================

if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=10000

    )

from flask import Flask, render_template, request, jsonify
import pandas as pd
import numpy as np
from datetime import datetime
import traceback
from pathlib import Path

app = Flask(__name__)

# -------- Paths --------
BASE_DIR = Path(__file__).resolve().parent
COURSES_CSV = BASE_DIR / "courses_master.csv"
PROGRAM_REQ_CSV = BASE_DIR / "program_requirements.csv"

# -------- Globals --------
DF_COURSES = pd.DataFrame()
DF_REQ = pd.DataFrame()

def load_data():
    """Load & preprocess data safely."""
    global DF_COURSES, DF_REQ

    print("=== LOADING CSVs ===")
    print("COURSES_CSV:", COURSES_CSV)
    print("PROGRAM_REQ_CSV:", PROGRAM_REQ_CSV)

    # ใช้ utf-8-sig กัน BOM
    DF_COURSES = pd.read_csv(COURSES_CSV, encoding="utf-8-sig")
    DF_REQ = pd.read_csv(PROGRAM_REQ_CSV, encoding="utf-8-sig")

    # กันช่องว่าง/ตัวพิมพ์ในชื่อคอลัมน์
    DF_COURSES.columns = DF_COURSES.columns.str.strip()
    DF_REQ.columns = DF_REQ.columns.str.strip()

    # ตรวจคอลัมน์ที่จำเป็น
    need_courses = {"course_code", "course_name", "day", "start_time", "end_time", "exam_date", "exam_session"}
    miss_courses = need_courses - set(DF_COURSES.columns)
    if miss_courses:
        raise ValueError(f"courses_master.csv missing columns: {sorted(miss_courses)}")

    need_req = {"program_code", "course_code", "type"}
    miss_req = need_req - set(DF_REQ.columns)
    if miss_req:
        raise ValueError(f"program_requirements.csv missing columns: {sorted(miss_req)}")

    # รวม type จาก requirement
    DF_COURSES = pd.merge(DF_COURSES, DF_REQ[["course_code", "type"]], on="course_code", how="left")
    DF_COURSES["type"] = DF_COURSES["type"].fillna("ทั่วไป")

    # แผนที่วัน (M, TU, W, TH, F, S -> ภาษาไทย)
    day_map = {"M": "จันทร์", "TU": "อังคาร", "W": "พุธ", "TH": "พฤหัสบดี", "F": "ศุกร์", "S": "เสาร์"}
    DF_COURSES["day"] = DF_COURSES["day"].astype(str).str.strip()
    DF_COURSES["day_full"] = DF_COURSES["day"].map(day_map)

    # แปลงเวลาแบบยืดหยุ่น (รองรับ 9.15, 09:15, 09:15:00)
    def parse_time_any(x):
        s = str(x).strip()
        if not s:
            return pd.NaT
        s = s.replace(".", ":")
        # พยายาม parse แบบ auto ก่อน
        try:
            return pd.to_datetime(s, errors="raise").time()
        except Exception:
            try:
                return pd.to_datetime(s, format="%H:%M", errors="raise").time()
            except Exception:
                return pd.NaT

    DF_COURSES["start_time_obj"] = DF_COURSES["start_time"].apply(parse_time_any)
    DF_COURSES["end_time_obj"] = DF_COURSES["end_time"].apply(parse_time_any)

    # ทิ้งแถวที่วัน/เวลาแปลงไม่ได้
    DF_COURSES.dropna(subset=["start_time_obj", "end_time_obj", "day_full"], inplace=True)
    DF_COURSES.fillna("", inplace=True)

    # ทำให้ program_code เป็น str และ uppercase
    DF_REQ["program_code"] = DF_REQ["program_code"].astype(str).str.strip().str.upper()

    print("=== DATA READY ===")

@app.route("/")
def index():
    # ถ้ายังไม่โหลด (เช่น import ล่าช้า) ลองโหลดอีกครั้ง
    global DF_REQ
    if DF_REQ.empty:
        try:
            load_data()
        except Exception as e:
            return f"Error loading data: {e}"
    programs = sorted(DF_REQ["program_code"].dropna().unique())
    return render_template("index.html", programs=programs)

@app.route("/get_courses_filtered", methods=["POST"])
def get_courses_filtered():
    """Filter courses based on user criteria and return JSON-safe payload."""
    try:
        global DF_COURSES, DF_REQ
        if DF_COURSES.empty or DF_REQ.empty:
            load_data()

        # รองรับกรณีไม่ได้ตั้ง header เป็น application/json
        filters = request.get_json(silent=True) or {}
        print("Incoming filters:", filters)

        program_code = (filters.get("program_code") or "").strip().upper()
        if not program_code:
            return jsonify([])

        # เฉพาะวิชาของสาขาที่เลือก
        program_courses_list = DF_REQ[DF_REQ["program_code"] == program_code]["course_code"].tolist()
        df = DF_COURSES[DF_COURSES["course_code"].isin(program_courses_list)].copy()

        # กรองวัน (ชื่อวันภาษาไทย)
        selected_days = filters.get("days", [])
        if selected_days:
            df = df[df["day_full"].isin(selected_days)]

        # กรองเวลา
        start_time_filter = datetime.strptime(filters.get("startTime", "00:00"), "%H:%M").time()
        end_time_filter = datetime.strptime(filters.get("endTime", "23:59"), "%H:%M").time()
        mask = (df["start_time_obj"] >= start_time_filter) & (df["end_time_obj"] <= end_time_filter)
        final_df = df[mask].copy()

        if final_df.empty:
            return jsonify([])

        # แทนที่ NaN ด้วย '' และไม่ส่งคอลัมน์ชนิด time ออกไป (กัน JSON serialize error)
        final_df.replace({pd.NA: "", np.nan: ""}, inplace=True)

        courses_output = {}
        for _, row in final_df.iterrows():
            code = row["course_code"]
            if code not in courses_output:
                courses_output[code] = {
                    "course_code": code,
                    "course_name": row["course_name"],
                    "type": row.get("type", ""),
                    "exam_date": row["exam_date"],
                    "exam_session": row["exam_session"],
                    "sections": []
                }
            # ส่งเฉพาะฟิลด์ที่ฝั่งหน้าเว็บใช้
            courses_output[code]["sections"].append({
                "day_full": row["day_full"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "room": row.get("room", ""),
                "lecturer": row.get("lecturer", "")
            })

        return jsonify(list(courses_output.values()))

    except Exception as e:
        print("\n--- SERVER ERROR ---")
        traceback.print_exc()
        print("--- END ERROR ---\n")
        return jsonify({"error": str(e)}), 500

# โหลดข้อมูลตั้งแต่ตอน import เพื่อรองรับ gunicorn/Render
load_data()

if __name__ == "__main__":
    app.run(debug=True)

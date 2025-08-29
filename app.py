from flask import Flask, render_template, request, jsonify
import pandas as pd
from datetime import datetime
import traceback # Import traceback for detailed error logging

app = Flask(__name__)

# --- Global variables for data ---
DF_COURSES = pd.DataFrame()
DF_REQ = pd.DataFrame()

def load_data():
    """Loads and preprocesses data from CSV files."""
    global DF_COURSES, DF_REQ
    try:
        DF_COURSES = pd.read_csv('courses_master.csv', encoding='utf-8')
        DF_REQ = pd.read_csv('program_requirements.csv', encoding='utf-8')
        
        DF_COURSES = pd.merge(DF_COURSES, DF_REQ[['course_code', 'type']], on='course_code', how='left')
        DF_COURSES['type'].fillna('ทั่วไป', inplace=True)
        
        day_map = {'M': 'จันทร์', 'TU': 'อังคาร', 'W': 'พุธ', 'TH': 'พฤหัสบดี', 'F': 'ศุกร์', 'S': 'เสาร์'}
        DF_COURSES['day_full'] = DF_COURSES['day'].map(day_map)

        DF_COURSES['start_time_obj'] = pd.to_datetime(DF_COURSES['start_time'], format='%H:%M', errors='coerce').dt.time
        DF_COURSES['end_time_obj'] = pd.to_datetime(DF_COURSES['end_time'], format='%H:%M', errors='coerce').dt.time
        
        DF_COURSES.dropna(subset=['start_time_obj', 'end_time_obj', 'day_full'], inplace=True)
        
        DF_COURSES.fillna('', inplace=True)
        print("Data loaded and preprocessed successfully.")
        
    except FileNotFoundError as e:
        print(f"CRITICAL ERROR: File not found -> {e.filename}. Please check if the file exists.")
    except Exception as e:
        print(f"An error occurred during data loading: {e}")

@app.route('/')
def index():
    """Renders the main page."""
    if DF_REQ.empty:
        return "Error: Could not load program_requirements.csv"
    programs = sorted(DF_REQ['program_code'].dropna().unique())
    return render_template('index.html', programs=programs)

@app.route('/get_courses_filtered', methods=['POST'])
def get_courses_filtered():
    """API endpoint to filter courses based on user criteria."""
    try:
        if DF_COURSES.empty:
            return jsonify([])

        filters = request.json
        program_code = filters.get('program_code')
        if not program_code:
            return jsonify([])

        program_courses_list = DF_REQ[DF_REQ['program_code'] == program_code]['course_code'].tolist()
        df = DF_COURSES[DF_COURSES['course_code'].isin(program_courses_list)].copy()
        
        selected_days = filters.get('days', [])
        if selected_days:
            df = df[df['day_full'].isin(selected_days)]
        
        start_time_filter = datetime.strptime(filters.get('startTime', '00:00'), '%H:%M').time()
        end_time_filter = datetime.strptime(filters.get('endTime', '23:59'), '%H:%M').time()
        
        mask = (df['start_time_obj'] >= start_time_filter) & (df['end_time_obj'] <= end_time_filter)
        final_df = df[mask]

        if final_df.empty:
            return jsonify([])

        # *** NEW, MORE ROBUST GROUPING LOGIC ***
        courses_output_dict = {}
        for _, section in final_df.iterrows():
            code = section['course_code']
            if code not in courses_output_dict:
                courses_output_dict[code] = {
                    'course_code': code,
                    'course_name': section['course_name'],
                    'type': section['type'],
                    'exam_date': section['exam_date'],
                    'exam_session': section['exam_session'],
                    'sections': []
                }
            courses_output_dict[code]['sections'].append(section.to_dict())
        
        return jsonify(list(courses_output_dict.values()))

    except Exception as e:
        print("\n--- !!! SERVER ERROR !!! ---")
        traceback.print_exc()
        print("--- !!! END ERROR !!! ---\n")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    load_data()
    app.run(debug=True)

from flask import Flask, render_template, request, jsonify
import pandas as pd
import os
import warnings

app = Flask(__name__)

# Paths to the provided data files
LOT_DATA_FILE_PATH = "EPA - CIM Monitoring for lot.csv"
DISPATCH_FILE_PATH = "EPA - CIM Monitoring for Dispatch.xlsx"

def load_dispatch_data(file_path):
    try:
        df = pd.read_excel(file_path, dtype=str)

        print("✅ Dispatch data loaded successfully!")
        print(df.head())  # Debugging: Show the first few rows

        # Rename columns
        df.rename(columns={
            'DISPATCHED DOCUMENTS': 'region_name',
            'Unnamed: 1': 'division_name',
            'Unnamed: 2': 'school_id',
            'Unnamed: 3': 'school_name',
            'Unnamed: 4': 'dispatched_date',
            'Unnamed: 5': 'plan_batch_no'
        }, inplace=True)

        # Convert 'dispatched_date' to datetime
        df['dispatched_date'] = pd.to_datetime(df['dispatched_date'], errors='coerce')

        print("📅 Dispatched Date column after conversion:")
        print(df['dispatched_date'].head())  # Debugging: Check date column

        return df.dropna(subset=['dispatched_date'])
    except Exception as e:
        print(f"❌ Error loading dispatch data: {e}")
        return pd.DataFrame()


# Load and clean the lot data
def load_and_clean_lot_data(file_path):
    try:
        df = pd.read_csv(file_path, on_bad_lines='skip')
        df = df[['region_name', 'division_name', 'school_id', 'school_name', 'allocated_lots_numbers']].dropna()

        def clean_lot_numbers(value):
            if pd.isna(value):
                return ''
            numbers = [num.strip()[-2:] if num.strip().isdigit() and len(num.strip()) >= 4 else num.strip() for num in value.split(',')]
            return ', '.join(filter(str.isdigit, numbers))

        df['allocated_lots_numbers'] = df['allocated_lots_numbers'].apply(clean_lot_numbers)
        return df
    except Exception as e:
        print(f"❌ Error loading and cleaning lot data: {e}")
        return pd.DataFrame()

# Load data at startup
dispatch_df = load_dispatch_data(DISPATCH_FILE_PATH)
df = load_and_clean_lot_data(LOT_DATA_FILE_PATH)

# Global list to store selected school IDs
selected_schools = []

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/input', methods=['GET', 'POST'])
def input_data():
    if request.method == 'POST':
        school_id = request.form['school_id'].strip()
        school_name = request.form['school_name'].strip()

        # Filter based on provided inputs
        if school_id and school_name:
            filtered_df = df[(df['school_id'].astype(str) == school_id) & (df['school_name'].str.lower() == school_name.lower())]
        elif school_id:
            filtered_df = df[df['school_id'].astype(str) == school_id]
        elif school_name:
            filtered_df = df[df['school_name'].str.lower() == school_name.lower()]
        else:
            return render_template('input.html', result="Please enter a School ID or School Name.")

        if not filtered_df.empty:
            row = filtered_df.iloc[0]
            lot_numbers = row['allocated_lots_numbers']
            region_name = row['region_name']
            division_name = row['division_name']
            return render_template('match_result.html', school_id=row['school_id'], school_name=row['school_name'], lots=lot_numbers, region_name=region_name, division_name=division_name)
        else:
            return render_template('input.html', result="No matching data found.")
    return render_template('input.html')

@app.route('/search_dispatch', methods=['GET', 'POST'])
def search_dispatch():
    global dispatch_df  # Ensure we're always using the latest DataFrame

    if request.method == 'POST':
        # Get user-selected filters
        start_date_input = request.form.get('start_date', '')
        end_date_input = request.form.get('end_date', '')
        search_school_id = request.form.get('search_school_id', '').strip()
        search_school_name = request.form.get('search_school_name', '').strip().lower()

        # Validate date inputs
        if not start_date_input:
            return render_template('search_dispatch.html', result="Please select a start date.")
        else:
            start_date = pd.to_datetime(start_date_input).date()

        end_date = pd.to_datetime(end_date_input).date() if end_date_input else start_date

        # Filter data dynamically
        # Ensure dispatched_date is converted to date type before filtering
        dispatch_df['dispatched_date'] = pd.to_datetime(dispatch_df['dispatched_date']).dt.date

        date_filtered = dispatch_df[
        (dispatch_df['dispatched_date'] >= start_date) & 
        (dispatch_df['dispatched_date'] <= end_date)
        ]


        # Apply additional filters
        if search_school_id:
            date_filtered = date_filtered[date_filtered['school_id'].astype(str) == search_school_id]
        if search_school_name:
            date_filtered = date_filtered[
                date_filtered['school_name'].str.lower().str.contains(search_school_name, na=False)
            ]

        # Ensure available filters update dynamically
        available_regions = sorted(date_filtered['region_name'].dropna().unique().tolist())
        available_divisions = sorted(date_filtered['division_name'].dropna().unique().tolist())
        available_batches = sorted(date_filtered['plan_batch_no'].dropna().unique().tolist())

        # Convert final filtered data to a list of records for the table
        dispatch_records = date_filtered[
            ['school_id', 'school_name', 'dispatched_date', 'region_name', 'division_name', 'plan_batch_no']
        ].dropna().to_dict(orient='records')

        return render_template(
            'search_dispatch.html',
            start_date=start_date,
            end_date=end_date,
            dispatch_records=dispatch_records,
            search_school_id=search_school_id,
            search_school_name=search_school_name,
            region_options=available_regions,
            division_options=available_divisions,
            plan_batch_options=available_batches
        )

    return render_template('search_dispatch.html')

@app.route('/check_lot_availability', methods=['GET', 'POST'])
def check_lot_availability():
    global selected_schools

    if not selected_schools:
        return render_template("lot_availability.html", lot_records=[], selected_schools=[], message="No schools selected.")

    # Merge dispatch and lot data on 'school_id'
    dispatch_df['school_id'] = dispatch_df['school_id'].astype(str)
    df['school_id'] = df['school_id'].astype(str)

    merged_df = pd.merge(dispatch_df, df, on="school_id", how="inner")


    # Filter based on selected school IDs
    filtered_df = merged_df[merged_df['school_id'].astype(str).isin(selected_schools)]

    if filtered_df.empty:
        return render_template("lot_availability.html", lot_records=[], selected_schools=selected_schools, message="No matching lot availability found.")

    # Extract relevant columns for display
    lot_records = filtered_df[['region_name_x', 'division_name_x', 'school_id', 'school_name_x', 'allocated_lots_numbers']].rename(
        columns={"region_name_x": "region_name", "division_name_x": "division_name", "school_name_x": "school_name"}
    ).to_dict(orient="records")

    return render_template(
        "lot_availability.html",
        lot_records=lot_records,
        selected_schools=selected_schools,
        message=None
    )

@app.route('/save_selected_schools', methods=['POST'])
def save_selected_schools():
    global selected_schools
    data = request.get_json()
    selected_ids = data.get('selected_schools', [])
    
    # Update the global list with selected schools
    selected_schools = selected_ids
    
    return jsonify({'status': 'success', 'count': len(selected_schools)})

@app.route('/clear_selections', methods=['POST'])
def clear_selections():
    global selected_schools
    selected_schools = []  # Clear the list
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    app.run(debug=True)
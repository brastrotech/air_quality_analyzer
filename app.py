import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from flask import Flask, request, render_template, jsonify, send_from_directory, url_for
from werkzeug.utils import secure_filename
import datetime # Though pandas handles most datetime, good to have if needed
import base64
from io import BytesIO
import shutil
import zipfile
import uuid
import logging # Import logging

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads_temp'
PERMANENT_STORAGE_FOLDER = 'permanent_csv_storage'
GENERATED_FILES_FOLDER = 'generated_files'
ALLOWED_EXTENSIONS = {'csv'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PERMANENT_STORAGE_FOLDER'] = PERMANENT_STORAGE_FOLDER
app.config['GENERATED_FILES_FOLDER'] = GENERATED_FILES_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PERMANENT_STORAGE_FOLDER, exist_ok=True)
os.makedirs(GENERATED_FILES_FOLDER, exist_ok=True)

# Setup logging
logging.basicConfig(level=logging.INFO) # Or logging.DEBUG for more detail
app.logger.setLevel(logging.INFO) # Ensure Flask's logger also respects this level


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_plot_and_get_base64(fig, directory, base_filename_prefix):
    safe_prefix = secure_filename(base_filename_prefix)
    plot_filename = f"{safe_prefix}_{uuid.uuid4().hex[:8]}.png"
    full_plot_path = os.path.join(directory, plot_filename)
    
    fig.savefig(full_plot_path, format="png", bbox_inches='tight')
    
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    plt.close(fig)
    base64_string = base64.b64encode(buf.getvalue()).decode('utf-8')
    
    return base64_string, full_plot_path

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_files():
    if 'files[]' not in request.files:
        return jsonify({"error": "No file part"}), 400

    files = request.files.getlist('files[]')

    if not files or all(f.filename == '' for f in files):
        return jsonify({"error": "No selected files"}), 400

    session_id = uuid.uuid4().hex
    session_permanent_upload_dir = os.path.join(app.config['PERMANENT_STORAGE_FOLDER'], session_id)
    os.makedirs(session_permanent_upload_dir, exist_ok=True)
    session_generated_files_dir = os.path.join(app.config['GENERATED_FILES_FOLDER'], session_id)
    os.makedirs(session_generated_files_dir, exist_ok=True)

    dataframes = []
    processing_errors = []
    saved_original_files = []

    for file in files:
        if file and allowed_file(file.filename):
            original_filename = secure_filename(file.filename)
            temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{session_id}_{original_filename}")
            file.save(temp_filepath)
            
            permanent_filepath = os.path.join(session_permanent_upload_dir, original_filename)
            try:
                shutil.copy(temp_filepath, permanent_filepath)
                saved_original_files.append(permanent_filepath)
            except Exception as e:
                processing_errors.append(f"Could not copy {original_filename} to permanent storage: {str(e)}")

            try:
                df = pd.read_csv(temp_filepath)
                if df.empty:
                    processing_errors.append(f"File {original_filename} is empty.")
                    if os.path.exists(temp_filepath): os.remove(temp_filepath)
                    continue
                dataframes.append(df)
            except Exception as e:
                processing_errors.append(f"Error reading {original_filename}: {str(e)}")
            finally:
                if os.path.exists(temp_filepath):
                    os.remove(temp_filepath)
        else:
            processing_errors.append(f"File type not allowed or no file for: {file.filename or 'unknown file'}")

    if not dataframes:
        # ... (error handling as before)
        error_message = "No valid CSV files were processed."
        if processing_errors:
            error_message += " Details: " + ", ".join(processing_errors)
        return jsonify({"error": error_message}), 400


    try:
        merged_df = pd.concat(dataframes, ignore_index=True)
        if merged_df.empty:
            return jsonify({"error": "Merged data is empty."}), 400
    except Exception as e:
        return jsonify({"error": f"Error merging CSVs: {str(e)}"}), 500

    if merged_df.columns.empty:
        return jsonify({"error": "Merged CSV has no columns."}), 400
    
    timestamp_col_name = merged_df.columns[0]
    app.logger.info(f"Session [{session_id}]: Using column '{timestamp_col_name}' as timestamp.")

    try:
        merged_df[timestamp_col_name] = pd.to_datetime(merged_df[timestamp_col_name], errors='coerce')
        if merged_df[timestamp_col_name].isnull().all():
            processing_errors.append(f"Could not parse any values in column '{timestamp_col_name}' as timestamps.")
        merged_df.dropna(subset=[timestamp_col_name], inplace=True)
        if merged_df.empty:
            return jsonify({"error": f"No valid data rows remain after timestamp parsing in '{timestamp_col_name}'."}), 400
        merged_df = merged_df.set_index(timestamp_col_name).sort_index()
    except Exception as e:
        return jsonify({"error": f"Error processing column '{timestamp_col_name}' as timestamp: {str(e)}"}), 500

    processed_csv_filename = "merged_processed_data.csv"
    processed_csv_filepath = os.path.join(session_generated_files_dir, processed_csv_filename)
    processed_csv_url = None
    try:
        merged_df.to_csv(processed_csv_filepath)
        processed_csv_url = url_for('download_general_file', session_id=session_id, filename=processed_csv_filename, _external=True)
    except Exception as e:
        processing_errors.append(f"Could not save processed CSV: {str(e)}")
        
    numeric_cols = merged_df.select_dtypes(include=np.number).columns.tolist()
    app.logger.info(f"Session [{session_id}]: Numeric columns found: {numeric_cols}")
    if not numeric_cols:
        # ... (error handling as before)
        msg = "No numeric data columns found for analysis after processing timestamps."
        if processing_errors: return jsonify({"error": msg, "details": processing_errors}), 400
        return jsonify({"error": msg}), 400


    plots_data_base64 = {}
    saved_plot_paths = []

    # --- Time Series Plots ---
    app.logger.info(f"Session [{session_id}]: Checking for 'PM2.5' and 'PM10' in {numeric_cols}")
    for param in ['PM2.5', 'PM10']:
        if param in numeric_cols:
            if merged_df[param].isnull().all():
                processing_errors.append(f"Column '{param}' has all missing values, cannot plot time series.")
                app.logger.warning(f"Session [{session_id}]: Column '{param}' has all NaNs. Skipping time series.")
                continue
            try:
                fig, ax = plt.subplots(figsize=(12, 6))
                merged_df[param].plot(ax=ax, legend=True)
                ax.set_title(f'Time Series of {param}')
                ax.set_xlabel(f'Timestamp ({merged_df.index.name})')
                ax.set_ylabel(param + ' (µg/m³)')
                ax.grid(True)
                base64_str, plot_path = save_plot_and_get_base64(fig, session_generated_files_dir, f"{param}_timeseries")
                plots_data_base64[f'{param.lower().replace(".", "")}_timeseries'] = base64_str
                saved_plot_paths.append(plot_path)
            except Exception as e:
                err_msg = f"Error generating time series for {param}: {str(e)}"
                app.logger.error(f"Session [{session_id}]: {err_msg}")
                processing_errors.append(err_msg)
        else:
            app.logger.info(f"Session [{session_id}]: Param {param} not found for time series.")


    # --- Overall Diurnal Variation (Mean with SD/SE) ---
    diurnal_plots_base64 = {}
    for param in numeric_cols:
        try:
            series = pd.to_numeric(merged_df[param], errors='coerce').dropna()
            if series.empty: continue

            hourly_data = series.groupby(series.index.hour)
            hourly_mean = hourly_data.mean()
            hourly_std = hourly_data.std()
            hourly_count = hourly_data.count()
            hourly_sem = hourly_std / np.sqrt(hourly_count.replace(0, np.nan))

            if hourly_mean.empty: continue

            fig, ax = plt.subplots(figsize=(10, 6))
            hourly_mean.plot(ax=ax, label='Mean', color='blue', marker='o')
            ax.fill_between(hourly_mean.index, hourly_mean - hourly_std, hourly_mean + hourly_std,
                            color='lightblue', alpha=0.5, label='Mean ± SD')
            ax.fill_between(hourly_mean.index, hourly_mean - hourly_sem, hourly_mean + hourly_sem,
                            color='lightcoral', alpha=0.7, label='Mean ± SE')
            ax.set_title(f'Average Diurnal Variation of {param}')
            ax.set_xlabel('Hour of Day')
            ax.set_ylabel(f'Average {param}')
            ax.set_xticks(range(24))
            ax.legend()
            ax.grid(True)
            base64_str, plot_path = save_plot_and_get_base64(fig, session_generated_files_dir, f"{param}_diurnal_overall")
            diurnal_plots_base64[secure_filename(param)] = base64_str
            saved_plot_paths.append(plot_path)
        except Exception as e:
            processing_errors.append(f"Error generating overall diurnal plot for {param}: {str(e)}")
    plots_data_base64['diurnal_variations_overall'] = diurnal_plots_base64 # Renamed key


    # --- Diurnal Variation by Day of the Week (Mean lines only) ---
    day_of_week_diurnal_plots_base64 = {}
    # Define the desired order for days of the week for consistent plotting
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    # Add temporary columns for day name and hour if not already present
    # (though DatetimeIndex provides .day_name and .hour directly)
    df_for_dow = merged_df.copy() # Work on a copy if adding columns
    df_for_dow['day_name'] = df_for_dow.index.day_name()
    df_for_dow['hour'] = df_for_dow.index.hour


    for param in numeric_cols:
        try:
            series = pd.to_numeric(df_for_dow[param], errors='coerce').dropna()
            if series.empty:
                app.logger.info(f"Session [{session_id}]: Series for {param} is empty for DoW diurnal. Skipping.")
                continue

            # Group by day_name and hour, then calculate mean
            # Use the series derived from df_for_dow which has 'day_name' and 'hour' columns
            day_hour_means = df_for_dow.groupby(['day_name', 'hour'])[param].mean()
            
            if day_hour_means.empty:
                app.logger.info(f"Session [{session_id}]: No data after grouping for {param} for DoW diurnal. Skipping.")
                continue

            # Unstack to get hours as index and days as columns
            plot_data_dow = day_hour_means.unstack(level='day_name')
            
            # Reorder columns to ensure consistent day plotting order
            # Only include days that are actually present in the data to avoid KeyErrors
            plot_data_dow = plot_data_dow.reindex(columns=[day for day in days_order if day in plot_data_dow.columns])

            if plot_data_dow.empty or plot_data_dow.isnull().all().all():
                app.logger.info(f"Session [{session_id}]: plot_data_dow for {param} is empty or all NaN after reindexing. Skipping.")
                continue

            fig, ax = plt.subplots(figsize=(12, 7))
            plot_data_dow.plot(ax=ax, marker='o', linestyle='-') # Each column (day) becomes a line
            
            ax.set_title(f'Diurnal Variation of {param} by Day of Week (Mean)')
            ax.set_xlabel('Hour of Day')
            ax.set_ylabel(f'Average {param}')
            ax.set_xticks(range(24))
            ax.legend(title='Day of Week')
            ax.grid(True)
            
            base64_str, plot_path = save_plot_and_get_base64(fig, session_generated_files_dir, f"{param}_diurnal_by_dow")
            day_of_week_diurnal_plots_base64[secure_filename(param)] = base64_str
            saved_plot_paths.append(plot_path)
            app.logger.info(f"Session [{session_id}]: Successfully generated DoW diurnal for {param}")

        except Exception as e:
            err_msg = f"Error generating Day-of-Week diurnal plot for {param}: {str(e)}"
            app.logger.error(f"Session [{session_id}]: {err_msg}")
            processing_errors.append(err_msg)
            
    plots_data_base64['diurnal_variations_by_day_of_week'] = day_of_week_diurnal_plots_base64


    # --- Zipping and Response ---
    plots_zip_url = None
    if saved_plot_paths:
        # ... (zipping as before)
        zip_filename = "all_plots.zip"
        zip_filepath = os.path.join(session_generated_files_dir, zip_filename)
        try:
            with zipfile.ZipFile(zip_filepath, 'w') as zipf:
                for plot_file in saved_plot_paths:
                    if os.path.exists(plot_file): # Check if file exists before adding
                         zipf.write(plot_file, os.path.basename(plot_file))
            plots_zip_url = url_for('download_general_file', session_id=session_id, filename=zip_filename, _external=True)
        except Exception as e:
            processing_errors.append(f"Could not create plots ZIP: {str(e)}")


    response_data = {
        "plots": plots_data_base64,
        "processed_csv_url": processed_csv_url,
        "plots_zip_url": plots_zip_url,
        "session_id": session_id
    }
    if processing_errors:
        response_data["warnings"] = processing_errors

    if not any(plots_data_base64.values()): # Simplified check
         if not processing_errors and "diurnal_variations_overall" not in plots_data_base64 and "diurnal_variations_by_day_of_week" not in plots_data_base64:
            response_data["message"] = "Processing complete. No plots could be generated."
    
    return jsonify(response_data)

@app.route('/download/<session_id>/<filename>')
def download_general_file(session_id, filename):
    directory = os.path.join(app.config['GENERATED_FILES_FOLDER'], secure_filename(session_id))
    safe_filename = secure_filename(filename)
    file_path = os.path.join(directory, safe_filename)

    # Basic security: Ensure the path is within the intended directory
    if not os.path.abspath(file_path).startswith(os.path.abspath(directory)):
        app.logger.warning(f"Attempt to access file outside designated directory: {file_path}")
        return "Access denied", 403
        
    if not os.path.exists(file_path):
        app.logger.warning(f"Requested file not found for download: {file_path}")
        return "File not found", 404
        
    return send_from_directory(directory, safe_filename, as_attachment=True)

if __name__ == '__main__':
    app.logger.info("Flask App Starting...")
    app.run(debug=True, use_reloader=True)
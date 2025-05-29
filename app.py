import os
import pandas as pd
import matplotlib
matplotlib.use('Agg') # Non-interactive backend for Matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from flask import Flask, request, render_template, jsonify, send_from_directory, url_for # Added url_for
from werkzeug.utils import secure_filename
import datetime
import base64
from io import BytesIO
import shutil # For copying files
import zipfile # For zipping files
import uuid # For unique IDs

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads_temp' # Temporary storage during request processing
PERMANENT_STORAGE_FOLDER = 'permanent_csv_storage' # For storing original CSVs
GENERATED_FILES_FOLDER = 'generated_files' # For plots and processed CSVs

ALLOWED_EXTENSIONS = {'csv'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PERMANENT_STORAGE_FOLDER'] = PERMANENT_STORAGE_FOLDER
app.config['GENERATED_FILES_FOLDER'] = GENERATED_FILES_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024 * 1024  # 6 GB limit (use with caution!)

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PERMANENT_STORAGE_FOLDER, exist_ok=True)
os.makedirs(GENERATED_FILES_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_plot_and_get_base64(fig, directory, base_filename_prefix):
    """Saves the plot to a file and returns its base64 encoding and filepath."""
    # Sanitize base_filename_prefix for use in filenames
    safe_prefix = secure_filename(base_filename_prefix)
    plot_filename = f"{safe_prefix}_{uuid.uuid4().hex[:8]}.png"
    full_plot_path = os.path.join(directory, plot_filename)
    
    fig.savefig(full_plot_path, format="png", bbox_inches='tight')
    
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    plt.close(fig) # Close the figure to free memory
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

    # Create a unique session ID for this request
    session_id = uuid.uuid4().hex
    
    # Create session-specific directories
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
            
            # Store a copy in the permanent session directory
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
                    continue
                dataframes.append(df)
            except Exception as e:
                processing_errors.append(f"Error reading {original_filename}: {str(e)}")
            finally:
                if os.path.exists(temp_filepath): # Clean up temp file
                    os.remove(temp_filepath)
        else:
            processing_errors.append(f"File type not allowed or no file for: {file.filename or 'unknown file'}")

    if not dataframes:
        error_message = "No valid CSV files were processed."
        if processing_errors:
            error_message += " Details: " + ", ".join(processing_errors)
        return jsonify({"error": error_message}), 400

    try:
        merged_df = pd.concat(dataframes, ignore_index=True)
        if merged_df.empty:
            return jsonify({"error": "Merged data is empty. Please check your CSV files."}), 400
    except Exception as e:
        return jsonify({"error": f"Error merging CSVs: {str(e)}"}), 500

    # --- Data Preprocessing ---
    if merged_df.columns.empty:
        return jsonify({"error": "Merged CSV has no columns."}), 400
    
    timestamp_col_name = merged_df.columns[0]
    app.logger.info(f"Session [{session_id}]: Using column '{timestamp_col_name}' as timestamp.")

    try:
        merged_df[timestamp_col_name] = pd.to_datetime(merged_df[timestamp_col_name], errors='coerce')
        if merged_df[timestamp_col_name].isnull().all():
            processing_errors.append(f"Could not parse any values in the first column ('{timestamp_col_name}') as timestamps.")
        merged_df.dropna(subset=[timestamp_col_name], inplace=True) # Crucial: drop rows where timestamp is NaT
        if merged_df.empty:
            return jsonify({"error": f"After attempting to parse timestamps in column '{timestamp_col_name}', no valid data rows remain."}), 400
        merged_df = merged_df.set_index(timestamp_col_name).sort_index() # Set index and sort
    except Exception as e:
        return jsonify({"error": f"Error processing the first column ('{timestamp_col_name}') as timestamp: {str(e)}"}), 500

    # Save the processed DataFrame
    processed_csv_filename = "merged_processed_data.csv"
    processed_csv_filepath = os.path.join(session_generated_files_dir, processed_csv_filename)
    try:
        merged_df.to_csv(processed_csv_filepath)
        processed_csv_url = url_for('download_general_file', session_id=session_id, filename=processed_csv_filename, _external=True)
    except Exception as e:
        processing_errors.append(f"Could not save processed CSV: {str(e)}")
        processed_csv_url = None
        
    # Identify numeric columns for processing (AFTER setting index)
    numeric_cols = merged_df.select_dtypes(include=np.number).columns.tolist()
    app.logger.info(f"Session [{session_id}]: Numeric columns found: {numeric_cols}")
    if not numeric_cols:
        msg = "No numeric data columns found for analysis after processing timestamps."
        if processing_errors: return jsonify({"error": msg, "details": processing_errors}), 400
        return jsonify({"error": msg}), 400

    plots_data_base64 = {}
    saved_plot_paths = []

    # --- Time Series Plots (PM2.5, PM10 if they exist) ---
    app.logger.info(f"Session [{session_id}]: Checking for 'PM2.5' and 'PM10' in {numeric_cols}")
    for param in ['PM2.5', 'PM10']: # Case-sensitive
        if param in numeric_cols:
            app.logger.info(f"Session [{session_id}]: Processing time series for {param}")
            if merged_df[param].isnull().all():
                app.logger.warning(f"Session [{session_id}]: Column '{param}' exists but contains all NaN values. Skipping time series plot.")
                processing_errors.append(f"Column '{param}' contains all missing values, cannot plot time series.")
                continue
            try:
                fig, ax = plt.subplots(figsize=(12, 6))
                merged_df[param].plot(ax=ax, legend=True) # Plot directly
                ax.set_title(f'Time Series of {param}')
                ax.set_xlabel(f'Timestamp ({merged_df.index.name})') # Use index name
                ax.set_ylabel(param + ' (µg/m³)')
                ax.grid(True)
                
                base64_str, plot_path = save_plot_and_get_base64(fig, session_generated_files_dir, f"{param}_timeseries")
                plots_data_base64[f'{param.lower().replace(".", "")}_timeseries'] = base64_str
                saved_plot_paths.append(plot_path)
                app.logger.info(f"Session [{session_id}]: Successfully generated time series for {param}")
            except Exception as e:
                err_msg = f"Error generating time series for {param}: {str(e)}"
                app.logger.error(f"Session [{session_id}]: {err_msg}")
                processing_errors.append(err_msg)
        else:
            app.logger.info(f"Session [{session_id}]: Parameter {param} not found in numeric columns or not plottable for time series.")


    # --- Diurnal Variation for all numeric parameters ---
    diurnal_plots_base64 = {}
    for param in numeric_cols:
        try:
            series = pd.to_numeric(merged_df[param], errors='coerce').dropna()
            if series.empty:
                continue

            hourly_data = series.groupby(series.index.hour) # Group by hour of the DatetimeIndex
            hourly_mean = hourly_data.mean()
            hourly_std = hourly_data.std()
            hourly_count = hourly_data.count()
            hourly_sem = hourly_std / np.sqrt(hourly_count.replace(0, np.nan))

            if hourly_mean.empty: # Skip if no data after grouping
                continue

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
            
            base64_str, plot_path = save_plot_and_get_base64(fig, session_generated_files_dir, f"{param}_diurnal")
            # Use a sanitized param name for the key if necessary, but original param for display
            diurnal_plots_base64[secure_filename(param)] = base64_str 
            saved_plot_paths.append(plot_path)
        except Exception as e:
            processing_errors.append(f"Error generating diurnal plot for {param}: {str(e)}")

    plots_data_base64['diurnal_variations'] = diurnal_plots_base64
    
    # Zip all generated plot files
    plots_zip_url = None
    if saved_plot_paths:
        zip_filename = "all_plots.zip"
        zip_filepath = os.path.join(session_generated_files_dir, zip_filename)
        try:
            with zipfile.ZipFile(zip_filepath, 'w') as zipf:
                for plot_file in saved_plot_paths:
                    zipf.write(plot_file, os.path.basename(plot_file))
            plots_zip_url = url_for('download_general_file', session_id=session_id, filename=zip_filename, _external=True)
        except Exception as e:
            processing_errors.append(f"Could not create plots ZIP: {str(e)}")
            
    response_data = {
        "plots": plots_data_base64,
        "processed_csv_url": processed_csv_url,
        "plots_zip_url": plots_zip_url,
        "session_id": session_id # For potential future use or debugging
    }
    if processing_errors:
        response_data["warnings"] = processing_errors

    if not any(plots_data_base64.values()) and not diurnal_plots_base64:
         if not processing_errors: # if no errors but also no plots
            response_data["message"] = "Processing complete. No specific plots could be generated based on the data (e.g., missing PM2.5/PM10 or other numeric data)."
    
    return jsonify(response_data)

@app.route('/download/<session_id>/<filename>')
def download_general_file(session_id, filename):
    # This route serves files from the session-specific generated_files directory
    directory = os.path.join(app.config['GENERATED_FILES_FOLDER'], secure_filename(session_id))
    safe_filename = secure_filename(filename)
    
    # Basic security check: ensure file is within the intended directory
    file_path = os.path.join(directory, safe_filename)
    if not os.path.abspath(file_path).startswith(os.path.abspath(directory)):
        return "Access denied", 403 # Or handle error more gracefully
        
    if not os.path.exists(file_path):
        return "File not found", 404
        
    return send_from_directory(directory, safe_filename, as_attachment=True)

if __name__ == '__main__':
    # Setup logging for debugging
    import logging
    logging.basicConfig(level=logging.INFO) # You can set to logging.DEBUG for more verbosity
    app.logger.info("Flask App Starting...")
    app.run(debug=True, use_reloader=True) # use_reloader=True can be helpful for dev
import os
import pandas as pd
import matplotlib
matplotlib.use('Agg') # Non-interactive backend for Matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from flask import Flask, request, render_template, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import datetime
import base64
from io import BytesIO

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
PLOTS_FOLDER = 'generated_plots'
ALLOWED_EXTENSIONS = {'csv'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PLOTS_FOLDER'] = PLOTS_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit

# Ensure upload and plot directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PLOTS_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_plot_as_base64(fig):
    """Converts a Matplotlib figure to a base64 encoded string."""
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    plt.close(fig) # Close the figure to free memory
    return base64.b64encode(buf.getvalue()).decode('utf-8')

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_files():
    if 'files[]' not in request.files:
        return jsonify({"error": "No file part"}), 400

    files = request.files.getlist('files[]')
    timestamp_col_name = request.form.get('timestamp_col', 'Timestamp') # Default to 'Timestamp'

    if not files or all(f.filename == '' for f in files):
        return jsonify({"error": "No selected files"}), 400

    dataframes = []
    processing_errors = []

    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            try:
                df = pd.read_csv(filepath)
                dataframes.append(df)
            except Exception as e:
                processing_errors.append(f"Error reading {filename}: {str(e)}")
                continue # Skip this file
            finally:
                if os.path.exists(filepath): # Clean up uploaded file
                    os.remove(filepath)
        else:
            processing_errors.append(f"File type not allowed for {file.filename or 'unknown file'}")


    if not dataframes and processing_errors:
         return jsonify({"error": "No valid CSV files processed.", "details": processing_errors}), 400
    if not dataframes:
        return jsonify({"error": "No CSV files were successfully processed."}), 400

    try:
        merged_df = pd.concat(dataframes, ignore_index=True)
    except Exception as e:
        return jsonify({"error": f"Error merging CSVs: {str(e)}"}), 500

    # --- Data Preprocessing ---
    if timestamp_col_name not in merged_df.columns:
        return jsonify({"error": f"Timestamp column '{timestamp_col_name}' not found in the merged data."}), 400

    try:
        # Attempt to parse with common formats, make more robust if needed
        merged_df[timestamp_col_name] = pd.to_datetime(merged_df[timestamp_col_name], errors='coerce')
        merged_df.dropna(subset=[timestamp_col_name], inplace=True) # Remove rows where timestamp couldn't be parsed
        merged_df.set_index(timestamp_col_name, inplace=True)
        merged_df.sort_index(inplace=True)
    except Exception as e:
        return jsonify({"error": f"Error processing timestamp column: {str(e)}"}), 500

    # Identify numeric columns for processing (excluding potential non-numeric ones)
    numeric_cols = merged_df.select_dtypes(include=np.number).columns.tolist()
    if not numeric_cols:
        return jsonify({"error": "No numeric data columns found for analysis."}), 400

    plots_data = {}

    # --- Time Series Plots (PM2.5, PM10 if they exist) ---
    for param in ['PM2.5', 'PM10']:
        if param in numeric_cols:
            fig, ax = plt.subplots(figsize=(12, 6))
            merged_df[param].plot(ax=ax, legend=True)
            ax.set_title(f'Time Series of {param}')
            ax.set_xlabel('Timestamp')
            ax.set_ylabel(param + ' (µg/m³)') # Assuming units
            ax.grid(True)
            plots_data[f'{param.lower()}_timeseries'] = generate_plot_as_base64(fig)

    # --- Diurnal Variation for all numeric parameters ---
    diurnal_plots = {}
    for param in numeric_cols:
        try:
            # Ensure column is numeric, coerce errors
            series = pd.to_numeric(merged_df[param], errors='coerce').dropna()
            if series.empty:
                continue

            hourly_data = series.groupby(series.index.hour)
            hourly_mean = hourly_data.mean()
            hourly_std = hourly_data.std()
            hourly_count = hourly_data.count()
            hourly_sem = hourly_std / np.sqrt(hourly_count) # Standard Error of the Mean

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
            diurnal_plots[param] = generate_plot_as_base64(fig)
        except Exception as e:
            processing_errors.append(f"Error generating diurnal plot for {param}: {str(e)}")

    plots_data['diurnal_variations'] = diurnal_plots
    
    response_data = {"plots": plots_data}
    if processing_errors:
        response_data["warnings"] = processing_errors

    return jsonify(response_data)


if __name__ == '__main__':
    app.run(debug=True)
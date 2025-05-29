# Air Quality Analyzer

A Flask web application to upload multiple CSV files containing air quality data, merge them, and display time series analysis for PM2.5 and PM10, along with average diurnal variations (mean ± SD, mean ± SE) for all numeric parameters.

## Features

-   Upload multiple CSV files.
-   Specify the timestamp column name.
-   Merges all uploaded CSVs.
-   Generates and displays:
    -   Time series plots for PM2.5 and PM10.
    -   Diurnal variation plots (hourly average with Standard Deviation and Standard Error bands) for all numeric parameters found in the data.

## Technologies Used

-   Python
-   Flask
-   Pandas
-   NumPy
-   Matplotlib
-   HTML, CSS, JavaScript (jQuery, Bootstrap)

## Setup and Run

1.  **Clone the repository (or download the files):**
    ```bash
    git clone <repository-url>
    cd air_quality_analyzer
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the Flask application:**
    ```bash
    python app.py
    ```

5.  Open your web browser and navigate to `http://127.0.0.1:5000/`.

## CSV File Requirements

-   Files must be in CSV format.
-   Files should contain a timestamp column that can be parsed into datetime objects. The name of this column can be specified in the UI.
-   Parameter columns (like PM2.5, PM10, etc.) should contain numeric data.
# Data Visualization Dashboard

This directory provides a minimal browser/server (B/S) application that connects to a MySQL database and displays data on a web page using Chart.js. It is intended as a starting point for building a large-screen data visualization system.

## Features

- Connects to MySQL using environment variables:
  - `MYSQL_HOST` (default `localhost`)
  - `MYSQL_USER` (default `root`)
  - `MYSQL_PASSWORD` (default empty)
  - `MYSQL_DB` (default `test`)
  - `MYSQL_TABLE` (default `sample_data`)
- Fetches `label` and `value` columns from the configured table and displays them using a selectable chart type (bar, line, or pie).
- Uses Flask for the backend and Chart.js on the frontend.

## Running

Install the requirements and start the server:

```bash
pip install -r requirements.txt
python app.py
```

Ensure the environment variables for your MySQL database are set before running the server. Then open `http://localhost:5000/` in a browser to view the dashboard.

This example is deliberately simple and can be extended for more complex visualization needs.

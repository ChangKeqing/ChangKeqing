from flask import Flask, render_template, jsonify
import pymysql
import os

app = Flask(__name__)

def get_db_connection():
    return pymysql.connect(
        host=os.environ.get('MYSQL_HOST', 'localhost'),
        user=os.environ.get('MYSQL_USER', 'root'),
        password=os.environ.get('MYSQL_PASSWORD', ''),
        db=os.environ.get('MYSQL_DB', 'test'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/data')
def data():
    table = os.environ.get('MYSQL_TABLE', 'sample_data')
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT label, value FROM {table} LIMIT 100")
            rows = cursor.fetchall()
    finally:
        conn.close()
    labels = [row['label'] for row in rows]
    values = [row['value'] for row in rows]
    return jsonify({'labels': labels, 'values': values})

if __name__ == '__main__':
    app.run(debug=True)

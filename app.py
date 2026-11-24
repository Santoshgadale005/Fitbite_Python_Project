import os
import csv
import random
import sqlite3
import io
import base64
import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'fitness.db')

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'fitbite-secret-key')

db = SQLAlchemy(app)


def init_db():
    """Ensure SQLite tables exist automatically on fresh cloud deployments."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS User (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username VARCHAR(100) UNIQUE NOT NULL,
                        password VARCHAR(100) NOT NULL
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS Progress (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        date DATE NOT NULL,
                        weight FLOAT NOT NULL,
                        height FLOAT NOT NULL,
                        bmi FLOAT NOT NULL,
                        calories_consumed INTEGER NOT NULL,
                        calories_burned INTEGER NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES User(id)
                    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS Meal (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        meal_type VARCHAR(50) NOT NULL,
                        meal VARCHAR(100) NOT NULL,
                        calories INTEGER NOT NULL,
                        date DATE NOT NULL,
                        FOREIGN KEY (user_id) REFERENCES User(id)
                    )''')
    conn.commit()
    conn.close()


init_db()


# SQLAlchemy model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)


# Function to calculate BMR
def calculate_bmr(age, height_cm, weight, gender):
    if gender == "Male":
        bmr = (10 * weight) + (6.25 * height_cm) - (5 * age) + 5
    else:  # Female
        bmr = (10 * weight) + (6.25 * height_cm) - (5 * age) - 161
    return bmr


# Function to calculate calorie intake based on BMR and physical activity level
def calculate_calories(bmr, activity_level):
    if activity_level == "Sedentary":
        calorie_intake = bmr * 1.2
    elif activity_level == "Lightly active":
        calorie_intake = bmr * 1.375
    elif activity_level == "Moderately active":
        calorie_intake = bmr * 1.55
    elif activity_level == "Very active":
        calorie_intake = bmr * 1.725
    else:  # Extra active
        calorie_intake = bmr * 1.9
    return calorie_intake


# Function to read meal options from CSV
def read_meal_options(file_path):
    meal_options = []
    full_path = file_path if os.path.isabs(file_path) else os.path.join(BASE_DIR, file_path)
    with open(full_path, mode='r', newline='', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader)  # Skip header row
        for row in reader:
            meal_type, meal, calories = row[0], row[1], float(row[2])
            meal_options.append((meal_type, meal, calories))
    return meal_options


# Function to select one meal randomly from each meal type and find the combination closest to the target calorie count
def select_meals(meal_options, target_calories):
    selected_meals = []

    meal_dict = {meal_type: [] for meal_type in ["Breakfast", "Lunch", "Snacks", "Dinner"]}
    for meal in meal_options:
        meal_type, meal_name, calories = meal
        meal_dict[meal_type].append((meal_name, calories))

    for meal_type, meals in meal_dict.items():
        selected_meal = random.choice(meals)
        selected_meals.append((meal_type, *selected_meal))

    closest_combination = selected_meals
    min_difference = abs(sum(meal[2] for meal in selected_meals) - target_calories)
    for _ in range(1000):
        random_combination = [(meal_type, *random.choice(meals)) for meal_type, meals in meal_dict.items()]
        total_calories = sum(meal[2] for meal in random_combination)
        if abs(total_calories - target_calories) < min_difference:
            closest_combination = random_combination
            min_difference = abs(total_calories - target_calories)

    return closest_combination


# Function to classify BMI
def classify_bmi(bmi):
    if bmi < 18.5:
        return "Underweight"
    elif 18.5 <= bmi < 25:
        return "Healthy Weight"
    elif 25 <= bmi < 30:
        return "Overweight"
    else:
        return "Obese"


# Function to display recommended calorie intake and diet plan
@app.route('/previou_ver', methods=['GET', 'POST'])
def display_result():
    if request.method == 'POST':
        try:
            age = int(request.form['age'])
            height_cm = float(request.form['height'])
            weight = float(request.form['weight'])
            gender = request.form['gender']
            activity_level = request.form['activity']
            diet_type = request.form['diet']

            bmr = calculate_bmr(age, height_cm, weight, gender)
            calorie_intake = calculate_calories(bmr, activity_level)

            if diet_type == "Vegan":
                meal_options = read_meal_options("vegan.csv")
            elif diet_type == "Vegetarian":
                meal_options = read_meal_options("veg.csv")
            else:
                meal_options = read_meal_options("non-veg.csv")

            selected_meals = select_meals(meal_options, calorie_intake)

            bmi = (weight / ((height_cm / 100) ** 2))
            bmi_classification = classify_bmi(bmi)

            result_data = {
                'bmi': f"{bmi:.2f} ({bmi_classification})",
                'calorie_intake': f"{calorie_intake:.2f}",
                'diet_plan': selected_meals
            }

            return render_template('result.html', result=result_data)

        except ValueError:
            error_message = "Please enter valid age, height, and weight."
            return render_template('error.html', error=error_message)

    return render_template('index.html')


def create_connection():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
    except sqlite3.Error as e:
        print(e)
    return conn


def authenticate_user(conn, username, password):
    sql_select_user = """
        SELECT * FROM User WHERE username = ? AND password = ?;
    """
    cursor = conn.cursor()
    cursor.execute(sql_select_user, (username, password))
    row = cursor.fetchone()
    return bool(row)


def create_user(conn, username, password):
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM User WHERE username = ?", (username,))
        if cursor.fetchone():
            return False

        cursor.execute("INSERT INTO User (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        return True
    except Exception as e:
        print("Error creating user:", e)
        return False


@app.route('/', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = create_connection()
        is_valid = authenticate_user(conn, username, password)
        conn.close()
        if is_valid:
            session['username'] = username
            return redirect(url_for('index2'))
        else:
            flash("Invalid username or password. Please try again.", 'error')
            return redirect(url_for('login_page'))
    else:
        return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            flash("Passwords do not match. Please try again.", 'error')
            return redirect(url_for('signup'))

        conn = create_connection()
        created = create_user(conn, username, password)
        conn.close()
        if created:
            flash("User created successfully!", 'success')
            return redirect(url_for('login_page'))
        else:
            flash("Failed to create user. Please try again.", 'error')
            return redirect(url_for('signup'))
    else:
        return render_template('signup.html')


def get_user_id(username):
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM User WHERE username = ?', (username,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


@app.route('/index2', methods=['GET', 'POST'])
def index2():
    if 'username' not in session:
        return redirect(url_for('login_page'))

    username = session['username']
    user_id = get_user_id(username)
    if user_id is None:
        session.pop('username', None)
        return redirect(url_for('login_page'))

    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(calories_consumed), SUM(calories_burned) FROM Progress WHERE user_id = ?', (user_id,))
    totals = cursor.fetchone()
    conn.close()
    total_calories_consumed = (totals[0] or 0) if totals else 0
    total_calories_burned = (totals[1] or 0) if totals else 0

    if request.method == 'POST':
        try:
            age = int(request.form['age'])
            height_cm = float(request.form['height'])
            weight = float(request.form['weight'])
            gender = request.form['gender']
            activity_level = request.form['activity']
            diet_type = request.form['diet']

            bmr = calculate_bmr(age, height_cm, weight, gender)
            calorie_intake = calculate_calories(bmr, activity_level)

            if diet_type == "Vegan":
                meal_options = read_meal_options("vegan.csv")
            elif diet_type == "Vegetarian":
                meal_options = read_meal_options("veg.csv")
            else:
                meal_options = read_meal_options("non-veg.csv")

            selected_meals = select_meals(meal_options, calorie_intake)
            bmi = (weight / ((height_cm / 100) ** 2))
            bmi_classification = classify_bmi(bmi)

            result_data = {
                'bmi': f"{bmi:.2f} ({bmi_classification})",
                'calorie_intake': f"{calorie_intake:.2f}",
                'diet_plan': selected_meals
            }

            return render_template(
                'index2.html',
                username=username,
                result_data=result_data,
                total_calories_burned=total_calories_burned,
                total_calories_consumed=total_calories_consumed,
            )

        except ValueError:
            error_message = "Please enter valid age, height, and weight."
            return render_template('error.html', error=error_message)

    return render_template(
        'index2.html',
        username=username,
        result_data={},
        total_calories_burned=total_calories_burned,
        total_calories_consumed=total_calories_consumed,
    )


@app.route('/track_progress', methods=['GET', 'POST'])
def track_progress():
    if 'username' not in session:
        return redirect(url_for('login_page'))

    username = session['username']
    user_id = get_user_id(username)
    if user_id is None:
        session.pop('username', None)
        return redirect(url_for('login_page'))

    if request.method == 'POST':
        try:
            date = request.form['date']
            weight = float(request.form['weight'])
            height = float(request.form['height'])
            bmi = weight / ((height / 100) ** 2)
            calories_consumed = int(request.form['calories_consumed'])
            calories_burned = int(request.form['calories_burned'])

            conn = create_connection()
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO Progress (user_id, date, weight, height, bmi, calories_consumed, calories_burned)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (user_id, date, weight, height, bmi, calories_consumed, calories_burned),
            )
            conn.commit()
            conn.close()
        except ValueError:
            return render_template('track_progress.html', username=username, error="Please enter valid data.")

    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT date, weight, bmi FROM Progress WHERE user_id = ? ORDER BY date', (user_id,))
    data = cursor.fetchall()
    conn.close()

    dates = [datetime.datetime.strptime(row[0], '%Y-%m-%d').date() for row in data]
    weights = [row[1] for row in data]
    bmis = [row[2] for row in data]

    plt.figure(figsize=(10, 5))
    plt.plot(dates, weights, label='Weight (kg)', marker='o')
    plt.plot(dates, bmis, label='BMI', marker='o')
    plt.xlabel('Date')
    plt.ylabel('Values')
    plt.title('Progress Over Time')
    plt.legend()
    plt.grid(True)

    img = io.BytesIO()
    plt.savefig(img, format='png')
    plt.close()
    img.seek(0)
    plot_url = base64.b64encode(img.getvalue()).decode()

    return render_template('track_progress.html', username=username, plot_url=plot_url)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG') == '1')

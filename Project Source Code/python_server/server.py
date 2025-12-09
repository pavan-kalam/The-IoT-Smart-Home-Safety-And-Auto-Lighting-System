import os
import json
import hashlib
import base64
import time
import requests
import math
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import threading
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import errors as psycopg2_errors
import smtplib
import ssl
from email.mime.text import MIMEText
import sys

# Setting up the Flask application
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-in-production')

# Email notification configuration
EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'false').lower() == 'true'
EMAIL_SMTP_SERVER = os.getenv('EMAIL_SMTP_SERVER', 'smtp.gmail.com')
EMAIL_SMTP_PORT = int(os.getenv('EMAIL_SMTP_PORT', '587'))
EMAIL_SENDER = os.getenv('EMAIL_SENDER', '')
EMAIL_SENDER_PASSWORD = os.getenv('EMAIL_SENDER_PASSWORD', '')
EMAIL_RECIPIENTS = [addr.strip() for addr in os.getenv('EMAIL_RECIPIENTS', '').split(',') if addr.strip()]

# Notification throttling (air quality every 5 minutes)
# Initialize with timezone-aware datetime to avoid timezone errors
last_air_quality_notification = datetime.min.replace(tzinfo=timezone.utc)
AIR_QUALITY_NOTIFICATION_INTERVAL = timedelta(minutes=5)

# PostgreSQL Database configuration (from environment variables)
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'database': os.getenv('POSTGRES_DATABASE', 'smart_home_db'),
    'user': os.getenv('POSTGRES_USER', 'iotuser'),
    'password': os.getenv('POSTGRES_PASSWORD', 'iotpassword'),
    'port': int(os.getenv('POSTGRES_PORT', '5432'))
}

# Function to get PostgreSQL database connection
def get_db_connection():
    """Get PostgreSQL database connection"""
    try:
        conn = psycopg2.connect(**POSTGRES_CONFIG)
        # Set timezone to UTC for consistent timestamp handling
        cur = conn.cursor()
        cur.execute("SET timezone = 'UTC'")
        cur.close()
        return conn
    except psycopg2.OperationalError as e:
        print(f"❌ Database connection error: {e}")
        sys.exit(1)

# AES encryption configuration (must match ESP32)
ENCRYPTION_KEY = b'MySecretKey12345'  # 16 bytes key for AES-128
BLOCK_SIZE = 16

# Initialize database with required tables
def init_database():
    """Initialize PostgreSQL database with required tables"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Create sensor data table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sensor_data (
            id SERIAL PRIMARY KEY,
            pir_motion BOOLEAN NOT NULL,
            flame_detected BOOLEAN NOT NULL,
            door_open BOOLEAN NOT NULL,
            air_quality INTEGER NOT NULL,
            sound_level INTEGER NOT NULL,
            light_level INTEGER NOT NULL,
            temperature DECIMAL(5,2) NOT NULL,
            humidity DECIMAL(5,2) NOT NULL,
            timestamp BIGINT NOT NULL,
            encrypted_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create users table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'user',
            active_sessions INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create system control table (for ESP32 control board commands)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS system_control (
            id SERIAL PRIMARY KEY,
            light_on BOOLEAN DEFAULT FALSE,
            buzzer_on BOOLEAN DEFAULT FALSE,
            buzzer_manual_off BOOLEAN DEFAULT FALSE,
            manual_mode BOOLEAN DEFAULT FALSE,
            brightness_level INTEGER DEFAULT 100,
            home_mode BOOLEAN DEFAULT TRUE,
            control_board_server_url VARCHAR(255),
            buzzer_activated_at TIMESTAMP,
            light_activated_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create sensor board control table (for ESP32 Board 1 commands)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sensor_board_control (
            id SERIAL PRIMARY KEY,
            monitoring BOOLEAN DEFAULT FALSE,
            encryption_enabled BOOLEAN DEFAULT TRUE,
            upload_interval INTEGER DEFAULT 2000,
            wifi_ssid VARCHAR(100),
            wifi_password VARCHAR(100),
            server_url VARCHAR(255),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create event log table
    cur.execute('''
        CREATE TABLE IF NOT EXISTS event_log (
            id SERIAL PRIMARY KEY,
            event_type VARCHAR(50) NOT NULL,
            event_message TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create per-sensor control table (for individual sensor light/buzzer controls)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sensor_controls (
            sensor_name VARCHAR(100) PRIMARY KEY,
            light_enabled BOOLEAN DEFAULT TRUE,
            buzzer_enabled BOOLEAN DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Initialize default sensor controls if table is empty
    cur.execute('SELECT COUNT(*) FROM sensor_controls')
    count = cur.fetchone()[0]
    if count == 0:
        default_sensors = [
            ('PIR Motion Sensor', True, True),
            ('Flame Sensor', True, True),
            ('MQ135 Air Quality Sensor', True, True),
            ('Reed Switch (Door Sensor)', True, True),
            ('Sound Sensor', True, True),
            ('LDR Light Sensor', True, False),  # Light sensor doesn't control buzzer
            ('DHT11 Temperature & Humidity', False, False)  # Monitoring only
        ]
        for sensor_name, light_enabled, buzzer_enabled in default_sensors:
            cur.execute('''
                INSERT INTO sensor_controls (sensor_name, light_enabled, buzzer_enabled)
                VALUES (%s, %s, %s)
                ON CONFLICT (sensor_name) DO NOTHING
            ''', (sensor_name, light_enabled, buzzer_enabled))
    
    # Create per-sensor control table (for individual sensor light/buzzer controls)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sensor_controls (
            sensor_name VARCHAR(100) PRIMARY KEY,
            light_enabled BOOLEAN DEFAULT TRUE,
            buzzer_enabled BOOLEAN DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Initialize default sensor controls if table is empty
    cur.execute('SELECT COUNT(*) FROM sensor_controls')
    count = cur.fetchone()[0]
    if count == 0:
        default_sensors = [
            ('PIR Motion Sensor', True, True),
            ('Flame Sensor', True, True),
            ('MQ135 Air Quality Sensor', True, True),
            ('Reed Switch (Door Sensor)', True, True),
            ('Sound Sensor', True, True),
            ('LDR Light Sensor', True, False),  # Light sensor doesn't control buzzer
            ('DHT11 Temperature & Humidity', False, False)  # Monitoring only
        ]
        for sensor_name, light_enabled, buzzer_enabled in default_sensors:
            cur.execute('''
                INSERT INTO sensor_controls (sensor_name, light_enabled, buzzer_enabled)
                VALUES (%s, %s, %s)
                ON CONFLICT (sensor_name) DO NOTHING
            ''', (sensor_name, light_enabled, buzzer_enabled))
    
    # Create sensor events table (for sensor events with actions)
    # Use TIMESTAMPTZ (timestamp with timezone) to ensure proper timezone handling
    cur.execute('''
        CREATE TABLE IF NOT EXISTS sensor_events (
            id SERIAL PRIMARY KEY,
            sensor_name VARCHAR(100) NOT NULL,
            sensor_information TEXT NOT NULL,
            action_taken TEXT NOT NULL,
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Add buzzer_manual_off column if it doesn't exist (for existing databases)
    try:
        cur.execute('ALTER TABLE system_control ADD COLUMN IF NOT EXISTS buzzer_manual_off BOOLEAN DEFAULT FALSE')
    except Exception:
        pass
    
    # Add columns to sensor_board_control if they don't exist (for existing databases)
    try:
        cur.execute('ALTER TABLE sensor_board_control ADD COLUMN IF NOT EXISTS wifi_ssid VARCHAR(100)')
        cur.execute('ALTER TABLE sensor_board_control ADD COLUMN IF NOT EXISTS wifi_password VARCHAR(100)')
        cur.execute('ALTER TABLE sensor_board_control ADD COLUMN IF NOT EXISTS server_url VARCHAR(255)')
    except Exception:
        pass
    
    # Add control_board_server_url column if it doesn't exist
    try:
        cur.execute('ALTER TABLE system_control ADD COLUMN IF NOT EXISTS control_board_server_url VARCHAR(255)')
    except Exception:
        pass
    
    # Add activation timestamp columns if they don't exist
    try:
        cur.execute('ALTER TABLE system_control ADD COLUMN IF NOT EXISTS buzzer_activated_at TIMESTAMP')
        cur.execute('ALTER TABLE system_control ADD COLUMN IF NOT EXISTS light_activated_at TIMESTAMP')
    except Exception:
        pass
    
    # Create notifications table for dashboard/email alerts
    cur.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            notification_type VARCHAR(50) DEFAULT 'info',
            read BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Add read column if it doesn't exist
    try:
        cur.execute('ALTER TABLE notifications ADD COLUMN IF NOT EXISTS read BOOLEAN DEFAULT FALSE')
    except:
        pass
    
    # Add timing columns for buzzer and light
    try:
        cur.execute('ALTER TABLE system_control ADD COLUMN IF NOT EXISTS buzzer_activated_at TIMESTAMP')
        cur.execute('ALTER TABLE system_control ADD COLUMN IF NOT EXISTS light_activated_at TIMESTAMP')
    except Exception as e:
        # Columns might already exist, ignore error
        pass
    
    # Create sensor_events table if it doesn't exist (for existing databases)
    try:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS sensor_events (
                id SERIAL PRIMARY KEY,
                sensor_name VARCHAR(100) NOT NULL,
                sensor_information TEXT NOT NULL,
                action_taken TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    except Exception as e:
        # Table might already exist, ignore error
        pass
    
    # Create indexes for better performance
    cur.execute('CREATE INDEX IF NOT EXISTS idx_sensor_timestamp ON sensor_data(timestamp)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_event_timestamp ON event_log(timestamp)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
    
    # Insert default admin user if not exists
    admin_password = hash_password('admin123')
    cur.execute('''
        INSERT INTO users (username, password_hash, role) 
        VALUES (%s, %s, %s)
        ON CONFLICT (username) DO NOTHING
    ''', ('admin', admin_password, 'admin'))
    
    # Initialize system control with default values (all OFF initially)
    cur.execute('''
        INSERT INTO system_control (id, light_on, buzzer_on, buzzer_manual_off, manual_mode, brightness_level, home_mode, control_board_server_url)
        VALUES (1, FALSE, FALSE, FALSE, FALSE, 100, TRUE, '')
        ON CONFLICT (id) DO NOTHING
    ''')
    
    # Ensure buzzer and light start OFF (reset on startup)
    cur.execute('''
        UPDATE system_control 
        SET buzzer_on = FALSE, light_on = FALSE, buzzer_manual_off = FALSE
        WHERE id = 1
    ''')
    
    # Initialize sensor board control with default values
    cur.execute('''
        INSERT INTO sensor_board_control (id, monitoring, encryption_enabled, upload_interval)
        VALUES (1, FALSE, TRUE, 2000)
        ON CONFLICT (id) DO NOTHING
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully!")

# Password hashing functions
def hash_password(password):
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, password_hash):
    """Verify password against hash"""
    return hash_password(password) == password_hash

# Decrypt data from ESP32
def decrypt_data(encrypted_data):
    """Decrypt AES-encrypted data from ESP32"""
    try:
        from urllib.parse import unquote
        print(f"🔐 Decrypt: Input length: {len(encrypted_data)}")
        encrypted_data = unquote(encrypted_data)
        print(f"🔐 Decrypt: After unquote length: {len(encrypted_data)}")
        encrypted_data = encrypted_data.strip().replace('\n', '').replace('\r', '').replace(' ', '+')
        
        if len(encrypted_data) % 4 != 0:
            padding_needed = 4 - (len(encrypted_data) % 4)
            print(f"🔐 Decrypt: Adding {padding_needed} padding chars")
            encrypted_data += '=' * padding_needed
        
        print(f"🔐 Decrypt: Base64 string length: {len(encrypted_data)}")
        combined_data = base64.b64decode(encrypted_data)
        print(f"🔐 Decrypt: Decoded binary length: {len(combined_data)}")
        
        if len(combined_data) < 16:
            print("Error: Encrypted data too short")
            return None
        
        iv = combined_data[:16]
        ciphertext = combined_data[16:]
        print(f"🔐 Decrypt: IV length: {len(iv)}, Ciphertext length: {len(ciphertext)}")
        
        if len(ciphertext) % 16 != 0:
            print(f"Warning: Ciphertext length {len(ciphertext)} not multiple of 16")
            return None
        
        cipher = AES.new(ENCRYPTION_KEY, AES.MODE_CBC, iv)
        decrypted_padded = cipher.decrypt(ciphertext)
        
        try:
            decrypted = unpad(decrypted_padded, BLOCK_SIZE)
        except ValueError as e:
            print(f"Padding error: {e}")
            decrypted = decrypted_padded.rstrip(b'\x00')
            if len(decrypted) > 0:
                padding_length = decrypted[-1]
                if padding_length <= 16 and padding_length > 0:
                    decrypted = decrypted[:-padding_length]
        
        try:
            result = decrypted.decode('utf-8')
            return result
        except UnicodeDecodeError:
            result = decrypted.decode('utf-8', errors='replace')
            return result
        
    except Exception as e:
        print(f"Decryption error: {e}")
        return None

# Login required decorator
def login_required(f):
    """Decorator to require login for protected routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    """Redirect to dashboard if logged in, otherwise to login"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT id, password_hash, role, active_sessions FROM users WHERE username = %s', (username,))
        user = cur.fetchone()
        conn.close()
        
        if user and verify_password(password, user['password_hash']):
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('UPDATE users SET active_sessions = active_sessions + 1 WHERE id = %s', (user['id'],))
            conn.commit()
            conn.close()
            
            session['user_id'] = user['id']
            session['username'] = username
            session['role'] = user['role']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password!', 'error')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration page - anyone can create an account"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        # Validation
        if not username or not password:
            flash('Username and password are required!', 'error')
            return render_template('register.html')
        
        if len(username) < 3:
            flash('Username must be at least 3 characters long!', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters long!', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return render_template('register.html')
        
        # Check if username already exists
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT id FROM users WHERE username = %s', (username,))
        if cur.fetchone():
            conn.close()
            flash('Username already exists! Please choose a different username.', 'error')
            return render_template('register.html')
        
        # Create new user
        try:
            password_hash = hash_password(password)
            cur.execute('''
                INSERT INTO users (username, password_hash, role)
                VALUES (%s, %s, 'user')
                RETURNING id
            ''', (username, password_hash))
            user_id = cur.fetchone()[0]
            conn.commit()
            conn.close()
            
            flash('Account created successfully! Please login with your credentials.', 'success')
            log_event('INFO', f'New user registered: {username}')
            return redirect(url_for('login'))
        except Exception as e:
            conn.rollback()
            conn.close()
            print(f"Error creating user: {e}")
            flash('Error creating account. Please try again.', 'error')
            return render_template('register.html')
    
    return render_template('register.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Forgot password page to reset user password"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not username or not new_password or not confirm_password:
            flash('All fields are required!', 'error')
            return render_template('forgot_password.html')
        
        if len(new_password) < 6:
            flash('Password must be at least 6 characters long!', 'error')
            return render_template('forgot_password.html')
        
        if new_password != confirm_password:
            flash('Passwords do not match!', 'error')
            return render_template('forgot_password.html')
        
        # Update password in database
        conn = get_db_connection()
        cur = conn.cursor()
        password_hash = hash_password(new_password)
        cur.execute('UPDATE users SET password_hash = %s WHERE username = %s', (password_hash, username))
        conn.commit()
        affected_rows = cur.rowcount
        conn.close()
        
        if affected_rows > 0:
            flash('Password updated successfully! Please login with your new password.', 'success')
            log_event('INFO', f'Password reset for user: {username}')
            return redirect(url_for('login'))
        else:
            flash('Username not found!', 'error')
            return render_template('forgot_password.html')
    
    return render_template('forgot_password.html')

@app.route('/logout')
def logout():
    """User logout"""
    if 'user_id' in session:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('UPDATE users SET active_sessions = GREATEST(active_sessions - 1, 0) WHERE id = %s', (session['user_id'],))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Error updating active sessions on logout: {e}")
    
    session.clear()
    flash('Logged out successfully!', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    """Main dashboard page"""
    return render_template('dashboard.html', 
                         username=session.get('username'),
                         role=session.get('role', 'user'))

@app.route('/visualization')
@login_required
def visualization():
    """Visualization page with real-time sensor graphs"""
    return render_template('visualization.html', 
                         username=session.get('username'),
                         role=session.get('role', 'user'))

# API Routes for ESP32 Sensor Board
@app.route('/api/sensor-data', methods=['POST'])
def receive_sensor_data():
    """Receive sensor data from ESP32 Board 1"""
    try:
        # Handle both JSON (for encrypted data) and form-urlencoded (for unencrypted data)
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form
        
        # Extract raw values (handle both JSON and form-urlencoded)
        def get_bool_value(key, default=False):
            val = data.get(key, default)
            if isinstance(val, bool):
                return val
            return str(val).lower() == 'true'
        
        def get_int_value(key, default=0):
            val = data.get(key, default)
            if isinstance(val, int):
                return val
            return int(val) if val else default
        
        def get_float_value(key, default=0.0):
            val = data.get(key, default)
            if isinstance(val, (int, float)):
                return float(val)
            return float(val) if val else default
        
        def get_str_value(key, default=''):
            val = data.get(key, default)
            return str(val) if val else default
        
        pir_motion = get_bool_value('pir_motion', False)
        flame_detected_raw = data.get('flame_detected', False)
        # Debug: Print raw flame value
        print(f"🔥 FLAME RAW VALUE: {flame_detected_raw} (type: {type(flame_detected_raw)})")
        if isinstance(flame_detected_raw, bool):
            flame_detected = flame_detected_raw
        else:
            flame_detected = str(flame_detected_raw).lower() == 'true'
        print(f"🔥 FLAME PARSED: {flame_detected}")
        # Reed switch logic: When magnet is close (reed switch active) = door closed
        # When magnet is far (reed switch inactive) = door open
        # So we need to invert the value from the sensor
        door_open_raw = get_bool_value('door_open', False)
        door_open = not door_open_raw  # Invert: active (magnet close) = closed, inactive (magnet far) = open
        air_quality = get_int_value('air_quality', 0)
        sound_level = get_int_value('sound_level', 0)
        light_level = get_int_value('light_level', 0)
        temperature = get_float_value('temperature', 0.0)
        humidity = get_float_value('humidity', 0.0)
        timestamp = get_int_value('timestamp', 0)
        is_encrypted = get_bool_value('is_encrypted', False)
        encrypted_data = get_str_value('encrypted_data', '')
        
        # Validate humidity range
        if humidity < 0.0:
            humidity = 0.0
        if humidity > 100.0:
            humidity = 100.0
        
        # Decrypt if encrypted
        if is_encrypted and encrypted_data:
            print(f"🔐 Received encrypted_data length: {len(encrypted_data)}")
            print(f"🔐 First 50 chars: {encrypted_data[:50]}")
            decrypted_json = decrypt_data(encrypted_data)
            if decrypted_json:
                try:
                    decrypted_data = json.loads(decrypted_json)
                    # Handle boolean or string values from JSON
                    pir_motion_val = decrypted_data.get('pir_motion', pir_motion)
                    if isinstance(pir_motion_val, bool):
                        pir_motion = pir_motion_val
                    else:
                        pir_motion = str(pir_motion_val).lower() == 'true'
                    
                    flame_detected_val = decrypted_data.get('flame_detected', flame_detected)
                    if isinstance(flame_detected_val, bool):
                        flame_detected = flame_detected_val
                    else:
                        flame_detected = str(flame_detected_val).lower() == 'true'
                    # Reed switch logic: When magnet is close (reed switch active) = door closed
                    # When magnet is far (reed switch inactive) = door open
                    # So we need to invert the value from the sensor
                    door_open_raw = decrypted_data.get('door_open', door_open)
                    if isinstance(door_open_raw, bool):
                        door_open = not door_open_raw  # Invert: active (magnet close) = closed, inactive (magnet far) = open
                    else:
                        door_open_raw = str(door_open_raw).lower() == 'true'
                        door_open = not door_open_raw
                    air_quality = int(decrypted_data.get('air_quality', air_quality))
                    sound_level = int(decrypted_data.get('sound_level', sound_level))
                    light_level = int(decrypted_data.get('light_level', light_level))
                    temperature = float(decrypted_data.get('temperature', temperature))
                    humidity = float(decrypted_data.get('humidity', humidity))
                    timestamp = int(decrypted_data.get('timestamp', timestamp))
                    if humidity < 0.0:
                        humidity = 0.0
                    if humidity > 100.0:
                        humidity = 100.0
                    print(f"✅ Successfully decrypted sensor data")
                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {e}")
            else:
                print("⚠️ Failed to decrypt data, using unencrypted values")
        
        # Store sensor data in database
        # Use timezone-aware datetime
        if timestamp > 0:
            created_at_timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone()
        else:
            created_at_timestamp = datetime.now(timezone.utc).astimezone()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO sensor_data (pir_motion, flame_detected, door_open, air_quality, sound_level, 
                                   light_level, temperature, humidity, timestamp, encrypted_data, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (pir_motion, flame_detected, door_open, air_quality, sound_level, light_level, 
              temperature, humidity, timestamp, encrypted_data, created_at_timestamp))
        conn.commit()
        conn.close()
        
        # Process all alerts and auto-controls (buzzer, lights, notifications) FIRST
        # This ensures actions are determined before logging sensor events
        process_alerts_and_controls(pir_motion, flame_detected, door_open, air_quality, sound_level, light_level)
        
        # Log all sensors in real-time (shows all sensors with their current readings)
        # This is called AFTER processing alerts so actions reflect current system state
        log_all_sensors(pir_motion, flame_detected, door_open, air_quality, sound_level, light_level, temperature, humidity)
        
        sensor_payload = {
            "pir_motion": pir_motion,
            "flame_detected": flame_detected,
            "door_open": door_open,
            "air_quality": air_quality,
            "sound_level": sound_level,
            "light_level": light_level,
            "temperature": round(float(temperature), 2),
            "humidity": round(float(humidity), 2),
            "timestamp": timestamp,
            "encrypted": is_encrypted
        }
        
        current_time = datetime.now(timezone.utc)
        print(f"📊 SENSOR DATA RECEIVED (ESP32 Board 1) at {current_time.isoformat()}")
        print(json.dumps(sensor_payload, indent=2))
        # Debug: Print flame sensor value specifically
        print(f"🔥 FLAME SENSOR DEBUG: flame_detected={flame_detected} (type: {type(flame_detected)})")
        
        # Debug: Log that we're about to log sensor events
        print(f"🔄 About to log sensor events for all sensors...")
        
        return jsonify({
            'status': 'success',
            'message': 'Data received and stored',
            'timestamp': timestamp
        })
        
    except Exception as e:
        print(f"❌ Error receiving sensor data: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

# API Routes for ESP32 Sensor Board (Board 1)
@app.route('/api/sensor-board/commands', methods=['GET'])
def get_sensor_board_commands():
    """Get control commands for ESP32 Board 1 (Sensor Board) - Called by ESP32"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM sensor_board_control WHERE id = 1')
        control = cur.fetchone()
        conn.close()
        
        if control:
            encryption_value = control.get('encryption_enabled', True)
            # Ensure it's a boolean value (PostgreSQL might return it as a different type)
            if isinstance(encryption_value, str):
                encryption_value = encryption_value.lower() in ('true', '1', 'yes', 'on', 't')
            else:
                encryption_value = bool(encryption_value)
            print(f"📡 Sensor board polling: returning encryption_enabled={encryption_value}")
            return jsonify({
                'monitoring': control['monitoring'],
                'encryption_enabled': encryption_value,
                'upload_interval': control['upload_interval'],
                'wifi_ssid': control.get('wifi_ssid', ''),
                'wifi_password': control.get('wifi_password', ''),
                'server_url': control.get('server_url', '')
            })
        else:
            return jsonify({
                'monitoring': False,
                'encryption_enabled': True,
                'upload_interval': 2000,
                'wifi_ssid': '',
                'wifi_password': '',
                'server_url': ''
            })
    except Exception as e:
        print(f"❌ Error getting sensor board commands: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sensor-board/status', methods=['POST'])
def update_sensor_board_status():
    """Receive status update from ESP32 Board 1"""
    try:
        data = request.get_json() or request.form
        
        monitoring_state = data.get('monitoring', False)
        encryption_state = data.get('encryption_enabled', True)
        
        conn = get_db_connection()
        cur = conn.cursor()
        # Update status but don't overwrite commands from dashboard
        # Only update if ESP32 reports different state (for sync)
        cur.execute('SELECT monitoring, encryption_enabled FROM sensor_board_control WHERE id = 1')
        current = cur.fetchone()
        if current:
            # Only update if there's a mismatch (ESP32 might be out of sync)
            if current[0] != monitoring_state or current[1] != encryption_state:
                cur.execute('''
                    UPDATE sensor_board_control 
                    SET monitoring = %s, encryption_enabled = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                ''', (monitoring_state, encryption_state))
                conn.commit()
        conn.close()
        
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"❌ Error updating sensor board status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sensor-board/monitoring', methods=['PUT'])
@login_required
def control_sensor_monitoring():
    """Start/Stop monitoring on ESP32 Sensor Board"""
    try:
        data = request.get_json()
        monitoring = data.get('monitoring', data.get('state', False))
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE sensor_board_control 
            SET monitoring = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (monitoring,))
        conn.commit()
        conn.close()
        
        log_event('CONTROL', f'📊 Sensor monitoring {"STARTED" if monitoring else "STOPPED"} (manual)')
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sensor-board/encryption', methods=['PUT'])
@login_required
def control_sensor_encryption():
    """Toggle encryption on ESP32 Sensor Board"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        encryption_enabled = data.get('encryption_enabled')
        if encryption_enabled is None:
            encryption_enabled = data.get('state', True)
        
        # Ensure it's a boolean value
        if isinstance(encryption_enabled, str):
            encryption_enabled = encryption_enabled.lower() in ('true', '1', 'yes', 'on')
        else:
            encryption_enabled = bool(encryption_enabled)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE sensor_board_control 
            SET encryption_enabled = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (encryption_enabled,))
        
        if cur.rowcount == 0:
            # Row doesn't exist, create it
            cur.execute('''
                INSERT INTO sensor_board_control (id, encryption_enabled, updated_at)
                VALUES (1, %s, CURRENT_TIMESTAMP)
            ''', (encryption_enabled,))
        
        conn.commit()
        conn.close()
        
        log_event('CONTROL', f'🔐 Encryption {"ENABLED" if encryption_enabled else "DISABLED"} (manual)')
        print(f"🔐 Encryption setting updated in database: {encryption_enabled}")
        print(f"🔐 Sensor board will pick up this change on next poll (every 3 seconds)")
        
        return jsonify({
            'status': 'ok',
            'encryption_enabled': encryption_enabled,
            'message': f'Encryption {"enabled" if encryption_enabled else "disabled"} successfully'
        })
    except Exception as e:
        print(f"❌ Error toggling encryption: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/sensor-board/wifi', methods=['PUT'])
@login_required
def update_sensor_wifi():
    """Update WiFi settings for ESP32 Sensor Board"""
    try:
        data = request.get_json()
        wifi_ssid = data.get('ssid', '')
        wifi_password = data.get('password', '')
        server_url = data.get('server_url', '')
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE sensor_board_control 
            SET wifi_ssid = %s, wifi_password = %s, server_url = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (wifi_ssid, wifi_password, server_url))
        conn.commit()
        conn.close()
        
        log_event('CONTROL', f'📡 WiFi settings updated for Sensor Board')
        
        return jsonify({'status': 'ok', 'message': 'WiFi settings updated. ESP32 will reconnect on next poll.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sensor-board/info', methods=['GET'])
@login_required
def get_sensor_board_info():
    """Get current Sensor Board status and configuration"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM sensor_board_control WHERE id = 1')
        control = cur.fetchone()
        conn.close()
        
        if control:
            return jsonify({
                'monitoring': control['monitoring'],
                'encryption_enabled': control['encryption_enabled'],
                'upload_interval': control['upload_interval'],
                'wifi_ssid': control.get('wifi_ssid', ''),
                'server_url': control.get('server_url', '')
            })
        else:
            return jsonify({
                'monitoring': False,
                'encryption_enabled': True,
                'upload_interval': 2000,
                'wifi_ssid': '',
                'server_url': ''
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sensor-board/upload-interval', methods=['PUT'])
@login_required
def set_upload_interval():
    """Set upload interval for Sensor Board"""
    try:
        data = request.get_json()
        upload_interval = int(data.get('upload_interval', data.get('interval', 2000)))
        upload_interval = max(1000, min(10000, upload_interval))  # Clamp to 1000-10000ms
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE sensor_board_control 
            SET upload_interval = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (upload_interval,))
        conn.commit()
        conn.close()
        
        log_event('CONTROL', f'📊 Upload interval set to {upload_interval} ms')
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API Routes for ESP32 Control Board (Board 2)
def check_timeouts():
    """Check if buzzer/light timeouts have passed and turn them off if needed.
    This is called on every ESP32 poll to ensure timeouts are checked even when no sensor data is received."""
    try:
        MOTION_BUZZER_TIMEOUT = 10   # seconds
        MOTION_LIGHT_TIMEOUT = 60    # seconds
        OTHER_SENSORS_TIMEOUT = 10   # seconds
        
        # Use UTC for all time comparisons to avoid timezone issues
        now = datetime.now(timezone.utc)
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM system_control WHERE id = 1')
        control = cur.fetchone()
        
        if not control:
            conn.close()
            return
        
        # Check buzzer timeout using PostgreSQL's time functions to avoid timezone issues
        # Both motion and other sensors use 10s timeout for buzzer
        if control.get('buzzer_on', False) and control.get('buzzer_activated_at') and not control.get('manual_mode', False):
            # Use SQL to calculate elapsed time directly (avoids timezone issues)
            cur.execute('''
                SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - buzzer_activated_at)) as elapsed_seconds
                FROM system_control 
                WHERE id = 1 AND buzzer_on = TRUE AND buzzer_activated_at IS NOT NULL
            ''')
            result = cur.fetchone()
            if result and result['elapsed_seconds'] is not None:
                time_elapsed = result['elapsed_seconds']
                
                # Get latest sensor data to determine if this was motion-triggered
                cur.execute('''
                    SELECT pir_motion, door_open FROM sensor_data 
                    ORDER BY created_at DESC 
                    LIMIT 1
                ''')
                sensor_result = cur.fetchone()
                door_closed = True  # Default to closed if no data
                motion_active = False  # Default to no motion
                if sensor_result:
                    # sensor_result is a dict from RealDictCursor, access by column name
                    door_open_value = sensor_result.get('door_open', False)
                    door_closed = not door_open_value  # door_open is inverted, so not door_open = door closed
                    motion_active = sensor_result.get('pir_motion', False)
                
                manual_off = control.get('buzzer_manual_off', False)
                print(f"🔔 Buzzer timeout check: elapsed={time_elapsed:.1f}s, timeout={OTHER_SENSORS_TIMEOUT}s, manual_off={manual_off}, door_closed={door_closed}, motion_active={motion_active}")
                
                # Buzzer timeout is 10s for both motion and other sensors
                if time_elapsed >= OTHER_SENSORS_TIMEOUT:
                    # For motion-triggered buzzer: always turn off after timeout, even if manual_off is True
                    # This ensures motion buzzer respects the 10s timeout regardless of manual_off flag
                    if motion_active and not door_closed:
                        # Motion is active and door is open - this is likely a motion buzzer
                        # Turn off after timeout even if manual_off is True
                        print(f"🏃 Motion buzzer timeout reached - turning OFF (ignoring manual_off for motion timeout)")
                        cur.execute('''
                            UPDATE system_control 
                            SET buzzer_on = FALSE, buzzer_activated_at = NULL, buzzer_manual_off = FALSE, updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                        ''')
                        conn.commit()
                        print(f"✅ Buzzer turned OFF in database - Motion timeout: {OTHER_SENSORS_TIMEOUT}s elapsed")
                        log_event('AUTO', f'🔔 Buzzer turned OFF (auto) - Motion timeout: {OTHER_SENSORS_TIMEOUT}s elapsed')
                    # If door is closed and timeout passed, turn off buzzer even if manual_off is True
                    # This handles case where user manually turned off buzzer but door closed
                    elif manual_off and door_closed:
                        print(f"🚪 Door closed and timeout passed - clearing manual_off and turning OFF buzzer")
                        cur.execute('''
                            UPDATE system_control 
                            SET buzzer_on = FALSE, buzzer_activated_at = NULL, buzzer_manual_off = FALSE, updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                        ''')
                        conn.commit()
                        print(f"✅ Buzzer turned OFF in database - Door closed, timeout: {OTHER_SENSORS_TIMEOUT}s elapsed")
                        log_event('AUTO', f'🔔 Buzzer turned OFF (auto) - Door closed, timeout: {OTHER_SENSORS_TIMEOUT}s elapsed')
                    elif manual_off:
                        print(f"⏳ Buzzer timeout passed ({time_elapsed:.1f}s >= {OTHER_SENSORS_TIMEOUT}s) but manual_off=True and door still open, keeping ON")
                    else:
                        print(f"⏰ Buzzer timeout reached! Turning OFF...")
                        cur.execute('''
                            UPDATE system_control 
                            SET buzzer_on = FALSE, buzzer_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                        ''')
                        conn.commit()
                        print(f"✅ Buzzer turned OFF in database - Timeout: {OTHER_SENSORS_TIMEOUT}s elapsed")
                        log_event('AUTO', f'🔔 Buzzer turned OFF (auto) - Timeout: {OTHER_SENSORS_TIMEOUT}s elapsed')
                else:
                    print(f"⏳ Buzzer still within timeout: {time_elapsed:.1f}s < {OTHER_SENSORS_TIMEOUT}s")
        
        # Check light timeout using PostgreSQL's time functions to avoid timezone issues
        # Motion: 60s, Other sensors: 10s
        # To properly determine if it's motion, check the latest sensor data
        if control.get('light_on', False) and control.get('light_activated_at') and not control.get('manual_mode', False):
            # Use SQL to calculate elapsed time directly (avoids timezone issues)
            cur.execute('''
                SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - light_activated_at)) as elapsed_seconds
                FROM system_control 
                WHERE id = 1 AND light_on = TRUE AND light_activated_at IS NOT NULL
            ''')
            result = cur.fetchone()
            if result and result['elapsed_seconds'] is not None:
                time_elapsed = result['elapsed_seconds']
                
                # Get latest sensor data to determine if motion triggered the light
                cur.execute('''
                    SELECT pir_motion, flame_detected, door_open, air_quality, sound_level
                    FROM sensor_data 
                    ORDER BY created_at DESC 
                    LIMIT 1
                ''')
                latest_sensor = cur.fetchone()
                
                # Determine if it's motion light:
                # IMPORTANT: We need to determine if motion was the original trigger, not just if it's currently active
                # Strategy: If elapsed < 60s AND no other sensor is currently active, assume it's motion (60s timeout)
                # If fire/door/air quality/sound is currently active, it's NOT a motion light (use 10s timeout)
                is_motion_light = False
                if latest_sensor:
                    pir_motion = latest_sensor.get('pir_motion', False) or False
                    flame_detected = latest_sensor.get('flame_detected', False) or False
                    door_open = latest_sensor.get('door_open', False) or False
                    air_quality = int(latest_sensor.get('air_quality', 0) or 0)
                    sound_level = int(latest_sensor.get('sound_level', 0) or 0)
                    
                    AIR_QUALITY_THRESHOLD = 2000
                    SOUND_THRESHOLD = 2000
                    
                    # Check if other sensors are currently active (excluding motion)
                    other_sensor_active = (door_open or flame_detected or 
                                          air_quality > AIR_QUALITY_THRESHOLD or 
                                          sound_level > SOUND_THRESHOLD)
                    
                    # KEY PRINCIPLE: Once motion triggers the light, it gets the FULL 60s timeout
                    # Even if motion stops and other sensors (like door) are active, we maintain the 60s timeout
                    # This prevents premature light shutoff when motion stops but door is still open
                    
                    # Strategy: Check if we're within 60s window first
                    # If we are within 60s AND no CRITICAL sensor (fire/gas/loud noise) is active,
                    # assume it was motion-triggered and use 60s timeout
                    # Only doors don't override motion's 60s timeout
                    
                    if pir_motion:
                        # Motion is currently active → definitely motion light (60s timeout)
                        is_motion_light = True
                    elif time_elapsed < MOTION_LIGHT_TIMEOUT:
                        # We're within the 60s motion window
                        # Only CRITICAL sensors (fire/gas/loud noise) override motion timeout
                        # Door being open doesn't change motion's 60s timeout
                        critical_sensor_active = (flame_detected or 
                                                air_quality > AIR_QUALITY_THRESHOLD or 
                                                sound_level > SOUND_THRESHOLD)
                        
                        if critical_sensor_active:
                            # Critical sensor is currently active → likely the trigger, use 10s timeout
                            is_motion_light = False
                        else:
                            # No critical sensor active, and we're within 60s window
                            # Assume motion triggered it, maintain 60s timeout
                            # Door being open doesn't affect this
                            is_motion_light = True
                    else:
                        # Beyond 60s window → definitely not motion anymore
                        is_motion_light = False
                
                # Determine timeout based on whether it's motion or other sensors
                if is_motion_light:
                    check_timeout = MOTION_LIGHT_TIMEOUT  # 60s for motion
                else:
                    check_timeout = OTHER_SENSORS_TIMEOUT  # 10s for other sensors
                
                print(f"💡 Light timeout check: elapsed={time_elapsed:.1f}s, timeout={check_timeout}s, is_motion={is_motion_light}")
                
                if time_elapsed >= check_timeout:
                    print(f"⏰ Light timeout reached! Turning OFF...")
                    cur.execute('''
                        UPDATE system_control 
                        SET light_on = FALSE, light_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                        WHERE id = 1
                    ''')
                    conn.commit()
                    print(f"✅ Light turned OFF in database - Timeout: {check_timeout}s elapsed")
                    log_event('AUTO', f'💡 Light turned OFF (auto) - Timeout: {check_timeout}s elapsed')
                else:
                    print(f"⏳ Light still within timeout: {time_elapsed:.1f}s < {check_timeout}s")
        
        conn.close()
    except Exception as e:
        print(f"❌ Error checking timeouts: {e}")
        import traceback
        traceback.print_exc()

@app.route('/api/control/commands', methods=['GET'])
def get_control_commands():
    """Get control commands for ESP32 Board 2 - Also returns server URL"""
    try:
        # Check timeouts before returning commands (ensures timeouts are checked on every poll)
        check_timeouts()
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM system_control WHERE id = 1')
        control = cur.fetchone()
        conn.close()
        
        if control:
            response = {
                'light_on': control['light_on'],
                'buzzer_on': control.get('buzzer_on', False),
                'manual_mode': control['manual_mode'],
                'brightness_level': control['brightness_level'],
                'home_mode': control['home_mode']
            }
            # Include server URL if configured
            if control.get('control_board_server_url'):
                response['server_url'] = control['control_board_server_url']
            return jsonify(response)
        else:
            return jsonify({
                'light_on': False,
                'buzzer_on': False,
                'manual_mode': False,
                'brightness_level': 100,
                'home_mode': True
            })
    except Exception as e:
        print(f"❌ Error getting control commands: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/status', methods=['POST'])
def update_control_status():
    """Receive status update from ESP32 Board 2"""
    try:
        data = request.get_json() or request.form
        
        light_on = data.get('light_on', False)
        buzzer_on = data.get('buzzer_on', False)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE system_control 
            SET light_on = %s, buzzer_on = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (light_on, buzzer_on))
        conn.commit()
        conn.close()
        
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"❌ Error updating control status: {e}")
        return jsonify({'error': str(e)}), 500

# API Routes for Dashboard
@app.route('/api/system-state', methods=['GET'])
@login_required
def get_system_state():
    """Get current system state for dashboard"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get latest sensor data
        cur.execute('''
            SELECT * FROM sensor_data
            ORDER BY timestamp DESC
            LIMIT 1
        ''')
        sensor = cur.fetchone()
        
        # Debug: Print air quality value if available
        if sensor and sensor.get('air_quality') is not None:
            print(f"DEBUG: Air quality raw value from DB: {sensor.get('air_quality')}, type: {type(sensor.get('air_quality'))}")
        
        # Get system control
        cur.execute('SELECT * FROM system_control WHERE id = 1')
        control = cur.fetchone()
        conn.close()
        
        if sensor and control:
            # Calculate air quality percentage and status
            # Get air quality value, handle None/NoneType
            air_quality_value = sensor.get('air_quality')
            if air_quality_value is None:
                air_quality_raw = 0
            else:
                try:
                    air_quality_raw = int(float(air_quality_value))
                except (ValueError, TypeError):
                    air_quality_raw = 0
            
            # MQ135 typically reads 0-4095 (12-bit ADC on ESP32)
            # Map to 0-100% where higher values = worse air quality (higher pollution)
            # Simple linear mapping: 0 = 0%, 4095 = 100%
            if air_quality_raw <= 0:
                air_quality_percent = 0
            else:
                # Map 0-4095 to 0-100%
                air_quality_percent = int(round((air_quality_raw / 4095.0) * 100))
                air_quality_percent = min(100, max(0, air_quality_percent))
            
            # Determine air quality status based on raw value
            # Thresholds: Excellent < 1000, Good < 2000, Moderate < 3000, Poor < 4000, Very Poor >= 4000
            if air_quality_raw < 1000:
                air_quality_status = 'Excellent'
            elif air_quality_raw < 2000:
                air_quality_status = 'Good'
            elif air_quality_raw < 3000:
                air_quality_status = 'Moderate'
            elif air_quality_raw < 4000:
                air_quality_status = 'Poor'
            else:
                air_quality_status = 'Very Poor'
            
            return jsonify({
                'sensors': {
                    'pir_motion': sensor['pir_motion'],
                    'flame_detected': sensor['flame_detected'],
                    'door_open': sensor['door_open'],
                    'air_quality': air_quality_raw,
                    'air_quality_raw': air_quality_raw,
                    'air_quality_percent': air_quality_percent,
                    'air_quality_status': air_quality_status,
                    'sound_level': sensor['sound_level'],
                    'light_level': sensor['light_level'],
                    'temperature': float(sensor['temperature']),
                    'humidity': float(sensor['humidity']),
                    'last_update': sensor['timestamp']
                },
                'system': {
                    'light_on': control['light_on'],
                    'buzzer_on': control.get('buzzer_on', False),
                    'manual_mode': control['manual_mode'],
                    'brightness_level': control['brightness_level'],
                    'home_mode': control['home_mode'],
                    'control_board_server_url': control.get('control_board_server_url', '')
                }
            })
        else:
            return jsonify({
                'sensors': {
                    'pir_motion': False,
                    'flame_detected': False,
                    'door_open': False,
                    'air_quality': 0,
                    'air_quality_raw': 0,
                    'air_quality_percent': 0,
                    'air_quality_status': 'Unknown',
                    'sound_level': 0,
                    'light_level': 0,
                    'temperature': 0.0,
                    'humidity': 0.0,
                    'last_update': 0
                },
                'system': {
                    'light_on': False,
                    'buzzer_on': False,
                    'manual_mode': False,
                    'brightness_level': 100,
                    'home_mode': True
                }
            })
    except Exception as e:
        print(f"❌ Error getting system state: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/light', methods=['PUT'])
@login_required
def control_light():
    """Control light on/off"""
    try:
        data = request.get_json()
        light_on = data.get('state', False)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE system_control 
            SET light_on = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (light_on,))
        conn.commit()
        conn.close()
        
        log_event('CONTROL', f'💡 Light turned {"ON" if light_on else "OFF"} (manual)')
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/buzzer', methods=['PUT'])
@login_required
def control_buzzer():
    """Control buzzer on/off (turn off alerts)"""
    try:
        data = request.get_json()
        buzzer_on = data.get('state', False)
        
        conn = get_db_connection()
        cur = conn.cursor()
        # Track if user manually turned off (so we don't auto-activate for non-critical alerts)
        cur.execute('''
            UPDATE system_control 
            SET buzzer_on = %s, buzzer_manual_off = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (buzzer_on, not buzzer_on))
        conn.commit()
        conn.close()
        
        log_event('CONTROL', f'🔔 Buzzer turned {"ON" if buzzer_on else "OFF"} (manual)')
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/mode', methods=['PUT'])
@login_required
def control_mode():
    """Switch between auto and manual mode"""
    try:
        data = request.get_json()
        mode = data.get('mode', 'auto')
        manual_mode = (mode == 'manual')
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE system_control 
            SET manual_mode = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (manual_mode,))
        conn.commit()
        conn.close()
        
        log_event('CONTROL', f'Mode: {"Manual" if manual_mode else "Auto"}')
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/brightness', methods=['PUT'])
@login_required
def control_brightness():
    """Set brightness level"""
    try:
        data = request.get_json()
        brightness = int(data.get('brightness', 100))
        brightness = max(0, min(100, brightness))  # Clamp to 0-100
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE system_control 
            SET brightness_level = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (brightness,))
        conn.commit()
        conn.close()
        
        log_event('CONTROL', f'Brightness set to {brightness}%')
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/control/home-mode', methods=['PUT'])
@login_required
def control_home_mode():
    """Set home/away mode"""
    try:
        data = request.get_json()
        home_mode = data.get('home_mode', True)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE system_control 
            SET home_mode = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (home_mode,))
        conn.commit()
        conn.close()
        
        log_event('CONTROL', f'Home mode: {"Someone home" if home_mode else "Away"}')
        
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/control-board/server-url', methods=['PUT'])
@login_required
def set_control_board_server_url():
    """Set server URL for ESP32 Control Board (configurable via dashboard)"""
    try:
        data = request.get_json()
        server_url = data.get('server_url', '').strip()
        
        if not server_url:
            return jsonify({'error': 'Server URL is required'}), 400
        
        # Validate URL format
        if not (server_url.startswith('http://') or server_url.startswith('https://')):
            return jsonify({'error': 'Server URL must start with http:// or https://'}), 400
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            UPDATE system_control 
            SET control_board_server_url = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (server_url,))
        conn.commit()
        conn.close()
        
        log_event('CONTROL', f'Control Board Server URL updated: {server_url}')
        
        return jsonify({'status': 'ok', 'message': 'Server URL updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/control-board/server-url', methods=['GET'])
@login_required
def get_control_board_server_url():
    """Get current server URL for ESP32 Control Board"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT control_board_server_url FROM system_control WHERE id = 1')
        control = cur.fetchone()
        conn.close()
        
        if control:
            return jsonify({
                'server_url': control.get('control_board_server_url', '')
            })
        else:
            return jsonify({'server_url': ''})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/events', methods=['GET'])
@login_required
def get_events():
    """Get event log with pagination"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        offset = (page - 1) * per_page
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get total count
        cur.execute('SELECT COUNT(*) as total FROM event_log')
        total = cur.fetchone()['total']
        
        # Get events for current page
        cur.execute('''
            SELECT event_type, event_message, timestamp
            FROM event_log
            ORDER BY timestamp DESC
            LIMIT %s OFFSET %s
        ''', (per_page, offset))
        events = cur.fetchall()
        conn.close()
        
        event_list = []
        for event in events:
            timestamp_str = event['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(event['timestamp'], datetime) else str(event['timestamp'])
            event_list.append({
                'type': event['event_type'],
                'message': event['event_message'],
                'timestamp': timestamp_str
            })
        
        total_pages = (total + per_page - 1) // per_page
        
        return jsonify({
            'events': event_list,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages,
                'has_next': page < total_pages,
                'has_prev': page > 1
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sensor-events', methods=['GET'])
@login_required
def get_sensor_events():
    """Get latest sensor readings (one per sensor) for real-time updates - shows current sensor data"""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get the latest sensor data entry (same as what's shown in Sensor Readings)
        cur.execute('''
            SELECT pir_motion, flame_detected, door_open, air_quality, sound_level, 
                   light_level, temperature, humidity, created_at
            FROM sensor_data 
            ORDER BY created_at DESC 
            LIMIT 1
        ''')
        
        latest_data = cur.fetchone()
        
        if not latest_data:
            conn.close()
            return jsonify({'sensor_events': [], 'query_time': time.time(), 'count': 0})
        
        # Get current system control state to determine actions
        cur.execute('SELECT * FROM system_control WHERE id = 1')
        control = cur.fetchone()
        
        # Get per-sensor control states
        cur.execute('SELECT sensor_name, light_enabled, buzzer_enabled FROM sensor_controls')
        sensor_controls = {row['sensor_name']: {'light_enabled': row['light_enabled'], 'buzzer_enabled': row['buzzer_enabled']} 
                          for row in cur.fetchall()}
        
        conn.close()
        
        if not control:
            control = {'buzzer_on': False, 'light_on': False, 'manual_mode': False, 'home_mode': True}
        
        # Extract sensor values
        pir_motion = latest_data['pir_motion']
        flame_detected = latest_data['flame_detected']
        door_open = latest_data['door_open']
        air_quality = int(latest_data['air_quality'])
        sound_level = int(latest_data['sound_level'])
        light_level = int(latest_data['light_level'])
        temperature = float(latest_data['temperature'])
        humidity = float(latest_data['humidity'])
        timestamp = latest_data['created_at']
        
        # Thresholds
        LIGHT_THRESHOLD = 2000  # Higher value = darker (0-4095 range, Dark=4095, Bright=0)
        # If light_level > 2000, it's considered dark
        AIR_QUALITY_THRESHOLD = 2000
        SOUND_THRESHOLD = 200
        
        # Determine actions for each sensor (same logic as log_all_sensors)
        actions = {}
        
        # PIR Motion Sensor
        if pir_motion:
            low_light = light_level > LIGHT_THRESHOLD  # Higher value = darker
            if not control.get('manual_mode', False) and low_light:
                actions['pir'] = 'Light ON (auto - low light)'
            elif not control.get('home_mode', True):
                actions['pir'] = 'Buzzer ON, Light ON (away mode)'
            else:
                actions['pir'] = 'No action (normal conditions)'
        else:
            actions['pir'] = 'No action (no motion)'
        
        # Flame Sensor
        if flame_detected:
            actions['flame'] = 'Buzzer ON, Light ON'
        else:
            actions['flame'] = 'No action (no fire detected)'
        
        # MQ135 Air Quality Sensor
        if air_quality > AIR_QUALITY_THRESHOLD:
            actions['mq135'] = 'Buzzer ON, Light ON'
        else:
            actions['mq135'] = f'No action (normal: {air_quality} < {AIR_QUALITY_THRESHOLD})'
        
        # Reed Switch (Door Sensor)
        if door_open:
            low_light = light_level > LIGHT_THRESHOLD  # Higher value = darker
            if not control.get('manual_mode', False) and low_light:
                actions['door'] = 'Light ON (auto - low light)'
            elif not control.get('home_mode', True):
                actions['door'] = 'Buzzer ON, Light ON (away mode)'
            else:
                actions['door'] = 'No action (normal conditions)'
        else:
            actions['door'] = 'No action (door closed)'
        
        # Sound Sensor
        if sound_level > SOUND_THRESHOLD:
            actions['sound'] = 'Buzzer ON, Light ON'
        else:
            actions['sound'] = f'No action (normal: {sound_level} < {SOUND_THRESHOLD})'
        
        # LDR Light Sensor
        if light_level > LIGHT_THRESHOLD:  # Higher value = darker
            if control.get('light_on', False):
                actions['ldr'] = 'Light ON (low light detected)'
            else:
                actions['ldr'] = f'Light ready (low light: {light_level} < {LIGHT_THRESHOLD})'
        else:
            actions['ldr'] = f'No action (sufficient light: {light_level})'
        
        # DHT11 Temperature & Humidity Sensor
        actions['dht11'] = 'No action (monitoring only)'
        
        # Build event list with current sensor readings
        event_list = []
        
        # Convert timestamp to ISO format
        if timestamp:
            if hasattr(timestamp, 'isoformat'):
                timestamp_str = timestamp.isoformat()
            else:
                timestamp_str = str(timestamp)
        else:
            timestamp_str = None
        
        # Helper function to get sensor control states
        def get_sensor_control(sensor_name):
            return sensor_controls.get(sensor_name, {'light_enabled': True, 'buzzer_enabled': True})
        
        # Add all sensors with their current readings and control states
            event_list.append({
            'sensor_name': 'DHT11 Temperature & Humidity',
            'sensor_information': f'Temp: {temperature}°C, Humidity: {humidity}%',
            'action_taken': actions['dht11'],
            'light_enabled': get_sensor_control('DHT11 Temperature & Humidity')['light_enabled'],
            'buzzer_enabled': get_sensor_control('DHT11 Temperature & Humidity')['buzzer_enabled']
        })
        
        event_list.append({
            'sensor_name': 'LDR Light Sensor',
            'sensor_information': f'Light level: {light_level} (threshold: {LIGHT_THRESHOLD})',
            'action_taken': actions['ldr'],
            'light_enabled': get_sensor_control('LDR Light Sensor')['light_enabled'],
            'buzzer_enabled': get_sensor_control('LDR Light Sensor')['buzzer_enabled']
        })
        
        event_list.append({
            'sensor_name': 'Sound Sensor',
            'sensor_information': f'Level: {sound_level} (threshold: {SOUND_THRESHOLD})',
            'action_taken': actions['sound'],
            'light_enabled': get_sensor_control('Sound Sensor')['light_enabled'],
            'buzzer_enabled': get_sensor_control('Sound Sensor')['buzzer_enabled']
        })
        
        event_list.append({
            'sensor_name': 'Reed Switch (Door Sensor)',
            'sensor_information': f'Door: {"Open" if door_open else "Closed"}',
            'action_taken': actions['door'],
            'light_enabled': get_sensor_control('Reed Switch (Door Sensor)')['light_enabled'],
            'buzzer_enabled': get_sensor_control('Reed Switch (Door Sensor)')['buzzer_enabled']
        })
        
        event_list.append({
            'sensor_name': 'MQ135 Air Quality Sensor',
            'sensor_information': f'Reading: {air_quality} (threshold: {AIR_QUALITY_THRESHOLD})',
            'action_taken': actions['mq135'],
            'light_enabled': get_sensor_control('MQ135 Air Quality Sensor')['light_enabled'],
            'buzzer_enabled': get_sensor_control('MQ135 Air Quality Sensor')['buzzer_enabled']
        })
        
        event_list.append({
            'sensor_name': 'Flame Sensor',
            'sensor_information': f'Fire: {"Detected" if flame_detected else "None"}',
            'action_taken': actions['flame'],
            'light_enabled': get_sensor_control('Flame Sensor')['light_enabled'],
            'buzzer_enabled': get_sensor_control('Flame Sensor')['buzzer_enabled']
        })
        
        event_list.append({
            'sensor_name': 'PIR Motion Sensor',
            'sensor_information': f'Motion: {"Detected" if pir_motion else "None"}',
            'action_taken': actions['pir'],
            'light_enabled': get_sensor_control('PIR Motion Sensor')['light_enabled'],
            'buzzer_enabled': get_sensor_control('PIR Motion Sensor')['buzzer_enabled']
        })
        
        # Add a unique identifier to force frontend refresh
        import time
        response_data = {
            'sensor_events': event_list,
            'query_time': time.time(),
            'count': len(event_list)
        }
        
        # Add cache control headers
        response = jsonify(response_data)
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        print(f"❌ Error getting sensor events: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'sensor_events': []}), 500

@app.route('/api/sensor-control/toggle', methods=['POST'])
@login_required
def toggle_sensor_control():
    """Toggle light or buzzer control for a specific sensor"""
    try:
        data = request.get_json()
        sensor_name = data.get('sensor_name')
        control_type = data.get('control_type')  # 'light' or 'buzzer'
        enabled = data.get('enabled', True)
        
        if not sensor_name or not control_type:
            return jsonify({'error': 'Missing sensor_name or control_type'}), 400
        
        if control_type not in ['light', 'buzzer']:
            return jsonify({'error': 'control_type must be "light" or "buzzer"'}), 400
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Update or insert sensor control
        if control_type == 'light':
            cur.execute('''
                INSERT INTO sensor_controls (sensor_name, light_enabled, buzzer_enabled)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (sensor_name) 
                DO UPDATE SET light_enabled = %s, updated_at = CURRENT_TIMESTAMP
            ''', (sensor_name, enabled, enabled))
        else:  # buzzer
            cur.execute('''
                INSERT INTO sensor_controls (sensor_name, light_enabled, buzzer_enabled)
                VALUES (%s, TRUE, %s)
                ON CONFLICT (sensor_name) 
                DO UPDATE SET buzzer_enabled = %s, updated_at = CURRENT_TIMESTAMP
            ''', (sensor_name, enabled, enabled))
        
        conn.commit()
        conn.close()
        
        # Build response with dynamic key
        response_data = {
            'success': True,
            'sensor_name': sensor_name,
            control_type + '_enabled': enabled
        }
        return jsonify(response_data)
    except Exception as e:
        print(f"❌ Error toggling sensor control: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/history/motion', methods=['GET'])
@login_required
def get_motion_history():
    """Get motion detection history"""
    try:
        limit = request.args.get('limit', 10, type=int)
        if limit is None or limit <= 0:
            limit = 10
        limit = int(limit)  # Ensure it's an integer
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT timestamp, event_message
            FROM event_log
            WHERE event_message LIKE %s OR event_message LIKE %s 
               OR event_message LIKE %s OR event_message LIKE %s
            ORDER BY timestamp DESC
            LIMIT %s
        ''', ('%Motion%', '%motion%', '%👁️%', '%🚨 Motion%', limit))
        events = cur.fetchall()
        conn.close()
        
        history = []
        for event in events:
            if not event:
                continue
            timestamp = event.get('timestamp')
            event_message = event.get('event_message', '')
            
            # Determine if motion was detected based on message
            motion_detected = 'detected' in event_message.lower() or 'Motion' in event_message
            
            if timestamp:
                # Format timestamp - if timezone-aware, convert to ISO format; otherwise format as-is
                if isinstance(timestamp, datetime):
                    # Use ISO format which JavaScript can parse correctly
                    timestamp_str = timestamp.isoformat()
                else:
                    timestamp_str = str(timestamp)
            else:
                timestamp_str = None
            
            history.append({
                'timestamp': timestamp_str,
                'motion_detected': motion_detected,
                'message': event_message
            })
        
        return jsonify({
            'history': history,
            'count': len(history)
        })
    except Exception as e:
        print(f"❌ Error getting motion history: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/history/door', methods=['GET'])
@login_required
def get_door_history():
    """Get door open/close history"""
    try:
        limit = request.args.get('limit', 10, type=int)
        if limit is None or limit <= 0:
            limit = 10
        limit = int(limit)  # Ensure it's an integer
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT timestamp, event_message
            FROM event_log
            WHERE event_message LIKE %s OR event_message LIKE %s 
               OR event_message LIKE %s OR event_message LIKE %s
               OR event_message LIKE %s OR event_message LIKE %s
            ORDER BY timestamp DESC
            LIMIT %s
        ''', ('%Door%', '%door%', '%Window%', '%window%', '%🚪%', '%🚨 Door%', limit))
        events = cur.fetchall()
        conn.close()
        
        history = []
        for event in events:
            if not event:
                continue
            timestamp = event.get('timestamp')
            event_message = event.get('event_message', '')
            
            # Determine if door is open based on message
            door_open = 'open' in event_message.lower() or 'opened' in event_message.lower()
            
            if timestamp:
                # Format timestamp - if timezone-aware, convert to ISO format; otherwise format as-is
                if isinstance(timestamp, datetime):
                    # Use ISO format which JavaScript can parse correctly
                    timestamp_str = timestamp.isoformat()
                else:
                    timestamp_str = str(timestamp)
            else:
                timestamp_str = None
            
            history.append({
                'timestamp': timestamp_str,
                'door_open': door_open,
                'message': event_message
            })
        
        return jsonify({
            'history': history,
            'count': len(history)
        })
    except Exception as e:
        print(f"❌ Error getting door history: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/history/fire', methods=['GET'])
@login_required
def get_fire_history():
    """Get fire detection history"""
    try:
        limit = request.args.get('limit', 10, type=int)
        if limit is None or limit <= 0:
            limit = 10
        limit = int(limit)  # Ensure it's an integer
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT timestamp, event_message
            FROM event_log
            WHERE event_message LIKE %s OR event_message LIKE %s 
               OR event_message LIKE %s OR event_message LIKE %s
               OR event_message LIKE %s
            ORDER BY timestamp DESC
            LIMIT %s
        ''', ('%Fire%', '%fire%', '%Flame%', '%flame%', '%🔥%', limit))
        events = cur.fetchall()
        conn.close()
        
        history = []
        for event in events:
            if not event:
                continue
            timestamp = event.get('timestamp')
            event_message = event.get('event_message', '')
            
            # Determine if fire was detected based on message
            flame_detected = 'fire' in event_message.lower() or 'flame' in event_message.lower() or '🔥' in event_message
            
            if timestamp:
                # Format timestamp - if timezone-aware, convert to ISO format; otherwise format as-is
                if isinstance(timestamp, datetime):
                    # Use ISO format which JavaScript can parse correctly
                    timestamp_str = timestamp.isoformat()
                else:
                    timestamp_str = str(timestamp)
            else:
                timestamp_str = None
            
            history.append({
                'timestamp': timestamp_str,
                'flame_detected': flame_detected,
                'message': event_message
            })
        
        return jsonify({
            'history': history,
            'count': len(history)
        })
    except Exception as e:
        print(f"❌ Error getting fire history: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    """Get recent notifications for dashboard"""
    try:
        limit = request.args.get('limit', 10, type=int)
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT id, title, message, notification_type, created_at, read
            FROM notifications
            ORDER BY created_at DESC
            LIMIT %s
        ''', (limit,))
        notifications = cur.fetchall()
        conn.close()
        
        notif_list = []
        for notif in notifications:
            notif_list.append({
                'id': notif['id'],
                'title': notif['title'],
                'message': notif['message'],
                'type': notif['notification_type'],
                'timestamp': notif['created_at'].isoformat() if notif['created_at'] else None,
                'read': notif['read']
            })
        
        return jsonify({'notifications': notif_list})
    except Exception as e:
        return jsonify({'error': str(e), 'notifications': []}), 500

@app.route('/api/notifications/<int:notif_id>/read', methods=['PUT'])
@login_required
def mark_notification_read(notif_id):
    """Mark notification as read"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('UPDATE notifications SET read = TRUE WHERE id = %s', (notif_id,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/events/clear', methods=['DELETE'])
@login_required
def clear_events():
    """Clear all event logs"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('DELETE FROM event_log')
        conn.commit()
        conn.close()
        log_event('INFO', 'Event log cleared by user')
        return jsonify({'status': 'ok', 'message': 'Event log cleared'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/notifications/clear', methods=['DELETE'])
@login_required
def clear_notifications():
    """Clear all notifications"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('DELETE FROM notifications')
        conn.commit()
        conn.close()
        return jsonify({'status': 'ok', 'message': 'Notifications cleared'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sensor-data/history', methods=['GET'])
@login_required
def get_sensor_data_history():
    """Get sensor data history for visualization (last N records)"""
    try:
        limit = request.args.get('limit', 50, type=int)
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('''
            SELECT temperature, humidity, air_quality, sound_level, light_level, 
                   pir_motion, flame_detected, door_open, created_at
            FROM sensor_data
            ORDER BY created_at DESC
            LIMIT %s
        ''', (limit,))
        data = cur.fetchall()
        conn.close()
        
        # Reverse to get chronological order (oldest first)
        data = list(reversed(data))
        
        history = []
        for row in data:
            timestamp = row['created_at']
            if timestamp:
                if isinstance(timestamp, datetime):
                    timestamp_str = timestamp.isoformat()
                else:
                    timestamp_str = str(timestamp)
            else:
                timestamp_str = None
            
            history.append({
                'timestamp': timestamp_str,
                'temperature': float(row['temperature']),
                'humidity': float(row['humidity']),
                'air_quality': int(row['air_quality']),
                'sound_level': int(row['sound_level']),
                'light_level': int(row['light_level']),
                'pir_motion': bool(row['pir_motion']),
                'flame_detected': bool(row['flame_detected']),
                'door_open': bool(row['door_open'])
            })
        
        return jsonify({'data': history})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def log_event(event_type, message):
    """Log event to database"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO event_log (event_type, event_message)
            VALUES (%s, %s)
        ''', (event_type, message))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging event: {e}")

def log_sensor_event(sensor_name, sensor_information, action_taken):
    """Log a sensor event with action taken"""
    try:
        # Ensure all values are strings and not None
        sensor_name = str(sensor_name) if sensor_name is not None else 'Unknown Sensor'
        sensor_information = str(sensor_information) if sensor_information is not None else 'N/A'
        action_taken = str(action_taken) if action_taken is not None else 'No action'
        
        conn = get_db_connection()
        cur = conn.cursor()
        # Explicitly set timestamp to ensure it's current
        cur.execute('''
            INSERT INTO sensor_events (sensor_name, sensor_information, action_taken, timestamp) 
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
        ''', (sensor_name, sensor_information, action_taken))
        conn.commit()
        conn.close()
        
        # Debug: log successful insert (only occasionally to avoid spam)
        import time
        if not hasattr(log_sensor_event, 'last_log') or (time.time() - log_sensor_event.last_log) > 10:
            print(f"✅ Logged sensor event: {sensor_name}")
            log_sensor_event.last_log = time.time()
    except Exception as e:
        print(f"❌ Error logging sensor event for {sensor_name}: {e}")
        import traceback
        traceback.print_exc()

def log_all_sensors(pir_motion, flame_detected, door_open, air_quality, sound_level, light_level, temperature, humidity):
    """Log all sensors in real-time with their current readings"""
    try:
        # Ensure all values are valid (handle None/empty values)
        sound_level = int(sound_level) if sound_level is not None and str(sound_level).strip() != '' else 0
        air_quality = int(air_quality) if air_quality is not None and str(air_quality).strip() != '' else 0
        light_level = int(light_level) if light_level is not None and str(light_level).strip() != '' else 0
        temperature = float(temperature) if temperature is not None and str(temperature).strip() != '' else 0.0
        humidity = float(humidity) if humidity is not None and str(humidity).strip() != '' else 0.0
        
        # Get current system control state to determine actions
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM system_control WHERE id = 1')
        control = cur.fetchone()
        conn.close()
        
        if not control:
            control = {'buzzer_on': False, 'light_on': False, 'manual_mode': False, 'home_mode': True}
        
        # Thresholds
        LIGHT_THRESHOLD = 2000  # Higher value = darker (0-4095 range, Dark=4095, Bright=0)
        # If light_level > 2000, it's considered dark
        AIR_QUALITY_THRESHOLD = 2000
        SOUND_THRESHOLD = 200  # Sound threshold for loud noise detection
        
        # Determine actions for each sensor
        actions = {}
        
        # PIR Motion Sensor
        if pir_motion:
            low_light = light_level > LIGHT_THRESHOLD  # Higher value = darker
            if not control.get('manual_mode', False) and low_light:
                actions['pir'] = 'Light ON (auto - low light)'
            elif not control.get('home_mode', True):
                actions['pir'] = 'Buzzer ON, Light ON (away mode)'
            else:
                actions['pir'] = 'No action (normal conditions)'
        else:
            actions['pir'] = 'No action (no motion)'
        
        # Flame Sensor
        if flame_detected:
            actions['flame'] = 'Buzzer ON, Light ON'
        else:
            actions['flame'] = 'No action (no fire detected)'
        
        # MQ135 Air Quality Sensor
        if air_quality > AIR_QUALITY_THRESHOLD:
            actions['mq135'] = 'Buzzer ON, Light ON'
        else:
            actions['mq135'] = f'No action (normal: {air_quality} < {AIR_QUALITY_THRESHOLD})'
        
        # Reed Switch (Door Sensor)
        if door_open:
            low_light = light_level > LIGHT_THRESHOLD  # Higher value = darker
            if not control.get('manual_mode', False) and low_light:
                actions['door'] = 'Light ON (auto - low light)'
            elif not control.get('home_mode', True):
                actions['door'] = 'Buzzer ON, Light ON (away mode)'
            else:
                actions['door'] = 'No action (normal conditions)'
        else:
            actions['door'] = 'No action (door closed)'
        
        # Sound Sensor
        if sound_level > SOUND_THRESHOLD:
            actions['sound'] = 'Buzzer ON, Light ON'
        else:
            actions['sound'] = f'No action (normal: {sound_level} < {SOUND_THRESHOLD})'
        
        # LDR Light Sensor
        if light_level > LIGHT_THRESHOLD:  # Higher value = darker
            if control.get('light_on', False):
                actions['ldr'] = 'Light ON (low light detected)'
            else:
                actions['ldr'] = f'Light ready (low light: {light_level} < {LIGHT_THRESHOLD})'
        else:
            actions['ldr'] = f'No action (sufficient light: {light_level})'
        
        # DHT11 Temperature & Humidity Sensor
        actions['dht11'] = 'No action (monitoring only)'
        
        # Log all sensors (with individual error handling)
        # Always log events every time sensor data is received - this ensures real-time updates
        print(f"🔄 Logging sensor events for all sensors...")
        try:
            log_sensor_event('PIR Motion Sensor', f'Motion: {"Detected" if pir_motion else "None"}', actions.get('pir', 'No action'))
        except Exception as e:
            print(f"❌ Error logging PIR sensor: {e}")
        
        try:
            log_sensor_event('Flame Sensor', f'Fire: {"Detected" if flame_detected else "None"}', actions.get('flame', 'No action'))
        except Exception as e:
            print(f"❌ Error logging Flame sensor: {e}")
        
        try:
            log_sensor_event('MQ135 Air Quality Sensor', f'Reading: {air_quality} (threshold: {AIR_QUALITY_THRESHOLD})', actions.get('mq135', 'No action'))
        except Exception as e:
            print(f"❌ Error logging MQ135 sensor: {e}")
        
        try:
            log_sensor_event('Reed Switch (Door Sensor)', f'Door: {"Open" if door_open else "Closed"}', actions.get('door', 'No action'))
        except Exception as e:
            print(f"❌ Error logging Door sensor: {e}")
        
        try:
            log_sensor_event('Sound Sensor', f'Level: {sound_level} (threshold: {SOUND_THRESHOLD})', actions.get('sound', 'No action'))
        except Exception as e:
            print(f"❌ Error logging Sound sensor: {e}")
            import traceback
            traceback.print_exc()
        
        try:
            log_sensor_event('LDR Light Sensor', f'Light level: {light_level} (threshold: {LIGHT_THRESHOLD})', actions.get('ldr', 'No action'))
        except Exception as e:
            print(f"❌ Error logging LDR sensor: {e}")
        
        try:
            log_sensor_event('DHT11 Temperature & Humidity', f'Temp: {temperature}°C, Humidity: {humidity}%', actions.get('dht11', 'No action'))
        except Exception as e:
            print(f"❌ Error logging DHT11 sensor: {e}")
        
        print(f"✅ Finished logging all sensor events")
        
    except Exception as e:
        print(f"Error logging all sensors: {e}")
        import traceback
        traceback.print_exc()

def process_alerts_and_controls(pir_motion, flame_detected, door_open, air_quality, sound_level, light_level):
    """Process all alerts, auto-lighting, and buzzer activation"""
    try:
        global last_air_quality_notification
        # Thresholds
        LIGHT_THRESHOLD = 2000  # LDR threshold for low light (0-4095, higher = darker, lower = brighter)
        # If light_level > 2000, it's considered dark (Dark=4095, Bright=0)
        # Note: LDR sensor behavior - Dark = high value (4095), Bright = low value (0)
        AIR_QUALITY_THRESHOLD = 2000  # MQ135 threshold for gas leak
        SOUND_THRESHOLD = 200  # Sound threshold for loud noise (glass breaking, etc.)
        
        # Use UTC for all time comparisons to avoid timezone issues
        # Database timestamps are stored in UTC (TIMESTAMPTZ), so we use UTC here too
        now = datetime.now(timezone.utc)
        
        # Get current system control state
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM system_control WHERE id = 1')
        control = cur.fetchone()
        
        # Get per-sensor control states
        cur.execute('SELECT sensor_name, light_enabled, buzzer_enabled FROM sensor_controls')
        sensor_controls = {row['sensor_name']: {'light_enabled': row['light_enabled'], 'buzzer_enabled': row['buzzer_enabled']} 
                          for row in cur.fetchall()}
        
        conn.close()
        
        if not control:
            return
        
        # Helper function to check if sensor control is enabled
        def is_sensor_control_enabled(sensor_name, control_type):
            """Check if light or buzzer is enabled for a specific sensor"""
            sensor_control = sensor_controls.get(sensor_name, {'light_enabled': True, 'buzzer_enabled': True})
            if control_type == 'light':
                return sensor_control.get('light_enabled', True)
            elif control_type == 'buzzer':
                return sensor_control.get('buzzer_enabled', True)
            return True  # Default to enabled if not found
        
        # Track alert conditions
        alert_conditions = []
        should_buzzer_on = False
        should_light_on = False
        away_mode_active = not control['home_mode']
        
        # Track alert types for different timeout handling
        # Motion: Buzzer 5s, Light 60s
        # Fire/Door: Both 30s
        motion_alert_active = False
        fire_door_alert_active = False
        
        # Track if motion/door/fire was detected in this cycle (for timeout tracking)
        motion_detected_this_cycle = pir_motion
        door_opened_this_cycle = door_open
        fire_detected_this_cycle = flame_detected
        
        # Check for fire
        if flame_detected:
            alert_conditions.append('FIRE DETECTED')
            # Check per-sensor controls before activating
            # Fire is critical - always activate buzzer/light regardless of mode
            if is_sensor_control_enabled('Flame Sensor', 'buzzer'):
                should_buzzer_on = True
            if is_sensor_control_enabled('Flame Sensor', 'light'):
                should_light_on = True
            fire_door_alert_active = True  # Fire uses 10s timeout
            log_event('ALERT', '🔥 Fire detected!')
            send_notification('Fire Alert', 'Fire detected in your home! Please check immediately.', 'fire')
        
        # Check for gas leak (throttle notifications to every 5 minutes)
        if air_quality > AIR_QUALITY_THRESHOLD:
            alert_conditions.append('GAS LEAK')
            # Check per-sensor controls before activating
            # Gas leak is critical - always activate buzzer/light regardless of mode
            if is_sensor_control_enabled('MQ135 Air Quality Sensor', 'buzzer'):
                should_buzzer_on = True
            if is_sensor_control_enabled('MQ135 Air Quality Sensor', 'light'):
                should_light_on = True
            fire_door_alert_active = True  # Air quality uses 10s timeout
            log_event('ALERT', f'⚠️ Gas leak detected! Air quality: {air_quality}')
            
            # Throttle air quality notifications to every 5 minutes
            global last_air_quality_notification
            if now - last_air_quality_notification >= AIR_QUALITY_NOTIFICATION_INTERVAL:
                send_notification('Gas Leak Alert', f'Gas leak detected! Air quality reading: {air_quality}', 'warning')
                last_air_quality_notification = now
                send_notification('Air Quality Alert', f'Gas leak detected! Air quality reading: {air_quality}', 'air_quality')
                last_air_quality_notification = now
        
        # Check for loud noise (glass breaking, etc.)
        if sound_level > SOUND_THRESHOLD:
            alert_conditions.append('LOUD NOISE')
            # Check per-sensor controls before activating
            # Only activate in AUTO mode (not manual mode)
            if not control['manual_mode']:
                if is_sensor_control_enabled('Sound Sensor', 'buzzer'):
                    should_buzzer_on = True
                if is_sensor_control_enabled('Sound Sensor', 'light'):
                    should_light_on = True
            fire_door_alert_active = True  # Sound uses 10s timeout
            log_event('ALERT', f'🔊 Loud noise detected! Sound level: {sound_level}')
            send_notification('Loud Noise Alert', f'Loud noise detected! Sound level: {sound_level}', 'sound')
        
        # Check for motion
        if pir_motion:
            log_event('INFO', '👁️ Motion detected')
            send_notification('Motion Alert', 'Motion detected in your home', 'motion')
            alert_conditions.append('MOTION DETECTED')
            motion_alert_active = True  # Motion uses motion timeout (buzzer 10s, light 60s)
            
            # Motion while away triggers buzzer and light
            if not control['home_mode']:
                alert_conditions.append('MOTION WHILE AWAY')
                # Check per-sensor controls before activating
                if is_sensor_control_enabled('PIR Motion Sensor', 'buzzer'):
                    should_buzzer_on = True
                if is_sensor_control_enabled('PIR Motion Sensor', 'light'):
                    should_light_on = True
                log_event('ALERT', '🚨 Motion detected while away!')
                send_notification('Security Alert', 'Motion detected while system is in away mode', 'motion')
            else:
                # In HOME mode, motion always triggers light (60s timeout), but not buzzer
                if not control['manual_mode']:
                    # Check per-sensor controls before activating
                    if is_sensor_control_enabled('PIR Motion Sensor', 'light'):
                        should_light_on = True  # Always trigger light for motion in HOME mode (60s timeout)
                # Motion in HOME mode doesn't trigger buzzer (normal activity)
        
        # Check for door/window opening
        if door_open:
            log_event('INFO', '🚪 Door/Window opened')
            send_notification('Door Alert', 'Door or window has been opened', 'door')
            alert_conditions.append('DOOR OPENED')
            fire_door_alert_active = True  # Door uses 10s timeout
            
            # Door opening while away triggers buzzer and light (only in AUTO mode)
            if not control['home_mode']:
                alert_conditions.append('DOOR OPEN WHILE AWAY')
                log_event('ALERT', '🚨 Door opened while away!')
                send_notification('Security Alert', 'Door or window opened while system is in away mode', 'door')
                # Only activate in AUTO mode
                if not control['manual_mode']:
                    if is_sensor_control_enabled('Reed Switch (Door Sensor)', 'buzzer'):
                        should_buzzer_on = True
                    if is_sensor_control_enabled('Reed Switch (Door Sensor)', 'light'):
                        should_light_on = True
            
            # Door opening triggers lights in low light (if not in manual mode)
            low_light = light_level > LIGHT_THRESHOLD  # Higher value = darker
            if not control['manual_mode'] and low_light:
                if is_sensor_control_enabled('Reed Switch (Door Sensor)', 'light'):
                    should_light_on = True
        else:
            # Door is closed - if buzzer was activated by door opening, clear manual_off flag
            # This allows buzzer to turn off after timeout when door closes
            if not control['manual_mode'] and control.get('buzzer_on', False) and control.get('buzzer_manual_off', False):
                # Check if buzzer was activated by door (check if it's been on for less than timeout)
                if control.get('buzzer_activated_at'):
                    buzzer_activated = control['buzzer_activated_at']
                    if isinstance(buzzer_activated, datetime):
                        if buzzer_activated.tzinfo is None:
                            buzzer_activated = buzzer_activated.replace(tzinfo=timezone.utc)
                        else:
                            buzzer_activated = buzzer_activated.astimezone(timezone.utc)
                        time_elapsed = (now - buzzer_activated).total_seconds()
                        # If door was recently opened (within last 15 seconds), likely door-triggered buzzer
                        # Clear manual_off flag to allow timeout to work
                        if time_elapsed < 15:  # Recent activation, likely from door
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute('''
                                UPDATE system_control 
                                SET buzzer_manual_off = FALSE, updated_at = CURRENT_TIMESTAMP
                                WHERE id = 1
                            ''')
                            conn.commit()
                            conn.close()
                            print(f"🚪 Door closed - cleared buzzer_manual_off flag to allow timeout")
                            # Refresh control state
                            control['buzzer_manual_off'] = False
        
        # Define timeouts based on alert type
        # Motion: Buzzer 10s, Light 60s
        # All other sensors (fire, door, air quality, sound): Both buzzer and light 10s
        MOTION_BUZZER_TIMEOUT = 10   # seconds
        MOTION_LIGHT_TIMEOUT = 60    # seconds
        OTHER_SENSORS_TIMEOUT = 10   # seconds (for fire, door, air quality, sound)
        
        motion_door_fire_alert = ('MOTION DETECTED' in alert_conditions) or ('DOOR OPENED' in alert_conditions) or ('FIRE DETECTED' in alert_conditions)
        away_alert_triggered = ('MOTION WHILE AWAY' in alert_conditions) or ('DOOR OPEN WHILE AWAY' in alert_conditions)
        
        # Determine which timeout to use based on current alert type
        # Motion: Buzzer 10s, Light 60s
        # All other sensors: Both 10s
        if motion_alert_active:
            buzzer_timeout = MOTION_BUZZER_TIMEOUT  # 10s
            light_timeout = MOTION_LIGHT_TIMEOUT     # 60s
        else:
            # All other sensors (fire, door, air quality, sound): 10s for both
            buzzer_timeout = OTHER_SENSORS_TIMEOUT
            light_timeout = OTHER_SENSORS_TIMEOUT
        
        # Check timeout for buzzer - keep on if timeout hasn't passed, turn off if it has
        # This ensures buzzer stays on for full timeout period even if motion stops
        if control.get('buzzer_on', False) and control.get('buzzer_activated_at'):
            buzzer_activated = control['buzzer_activated_at']
            if isinstance(buzzer_activated, datetime):
                # Make sure buzzer_activated is timezone-aware and in UTC
                if buzzer_activated.tzinfo is None:
                    buzzer_activated = buzzer_activated.replace(tzinfo=timezone.utc)
                else:
                    # Convert to UTC if it's in a different timezone
                    buzzer_activated = buzzer_activated.astimezone(timezone.utc)
                time_elapsed = (now - buzzer_activated).total_seconds()
                
                # Determine if this was a motion buzzer: if motion is active OR if we're within motion timeout
                # and no other sensor is currently active
                is_motion_buzzer = motion_alert_active or (time_elapsed < MOTION_BUZZER_TIMEOUT and 
                                                          not (door_opened_this_cycle or fire_detected_this_cycle or 
                                                               flame_detected or air_quality > AIR_QUALITY_THRESHOLD or 
                                                               sound_level > SOUND_THRESHOLD))
                
                # Determine timeout based on what type of alert activated it
                if is_motion_buzzer:
                    check_buzzer_timeout = MOTION_BUZZER_TIMEOUT  # 10s for motion
                else:
                    check_buzzer_timeout = OTHER_SENSORS_TIMEOUT  # 10s for all other sensors
                
                # Keep on if timeout hasn't passed (even if motion stopped), turn off if it has
                if time_elapsed < check_buzzer_timeout:
                    should_buzzer_on = True  # Keep on if timeout hasn't passed
                else:
                    should_buzzer_on = False  # Turn off after timeout
        
        
        # Update buzzer state (only in AUTO mode - manual mode user has full control)
        if not control['manual_mode']:
            # Motion/door/fire alerts should always activate buzzer
            critical_alert = flame_detected or air_quality > AIR_QUALITY_THRESHOLD
            if should_buzzer_on and (critical_alert or motion_door_fire_alert or not control.get('buzzer_manual_off', False)):
                # Only activate if currently off (avoid unnecessary updates)
                if not control.get('buzzer_on', False):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    # Clear buzzer_manual_off when activating buzzer due to motion/door/fire
                    # This ensures timeout works properly after motion detection
                    cur.execute('''
                        UPDATE system_control 
                        SET buzzer_on = TRUE, buzzer_activated_at = CURRENT_TIMESTAMP, 
                            buzzer_manual_off = FALSE, updated_at = CURRENT_TIMESTAMP
                        WHERE id = 1
                    ''')
                    conn.commit()
                    conn.close()
                    log_event('ALERT', f'🔔 Buzzer activated - {", ".join(alert_conditions) if alert_conditions else "Alert condition"}')
                elif control.get('buzzer_on', False) and not control.get('buzzer_activated_at'):
                    # Update activation time if buzzer is on but time not set
                    # Also clear manual_off flag to ensure timeout works
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute('''
                        UPDATE system_control 
                        SET buzzer_activated_at = CURRENT_TIMESTAMP, buzzer_manual_off = FALSE, updated_at = CURRENT_TIMESTAMP
                        WHERE id = 1 AND buzzer_activated_at IS NULL
                    ''')
                    conn.commit()
                    conn.close()
            # Always check timeout for buzzer - turn off if timeout has passed (even if sensor is still active)
            # This check runs after sensor checks, so it can override sensor-based settings
            if control.get('buzzer_on', False) and control.get('buzzer_activated_at'):
                buzzer_activated = control['buzzer_activated_at']
                if isinstance(buzzer_activated, datetime):
                    # Make sure buzzer_activated is timezone-aware and in UTC
                    if buzzer_activated.tzinfo is None:
                        buzzer_activated = buzzer_activated.replace(tzinfo=timezone.utc)
                    else:
                        # Convert to UTC if it's in a different timezone
                        buzzer_activated = buzzer_activated.astimezone(timezone.utc)
                    
                    time_elapsed = (now - buzzer_activated).total_seconds()
                
                    # Determine if this was a motion buzzer: if motion is active OR if we're within motion timeout
                    # and no other sensor is currently active
                    is_motion_buzzer = motion_alert_active or (time_elapsed < MOTION_BUZZER_TIMEOUT and 
                                                              not (door_opened_this_cycle or fire_detected_this_cycle or 
                                                                   flame_detected or air_quality > AIR_QUALITY_THRESHOLD or 
                                                                   sound_level > SOUND_THRESHOLD))
                    
                    # Determine which timeout to check based on what triggered the buzzer
                    if is_motion_buzzer:
                        check_timeout = MOTION_BUZZER_TIMEOUT  # 10s for motion
                    else:
                        check_timeout = OTHER_SENSORS_TIMEOUT  # 10s for all other sensors
                    
                    # Turn off if timeout has passed - this overrides sensor-based settings
                    if time_elapsed >= check_timeout:
                        should_buzzer_on = False  # Override sensor-based setting
                        # Turn off buzzer
                        if not control.get('buzzer_manual_off', False):
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute('''
                                UPDATE system_control 
                                SET buzzer_on = FALSE, buzzer_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                                WHERE id = 1
                            ''')
                            conn.commit()
                            conn.close()
                            timeout_used = MOTION_BUZZER_TIMEOUT if is_motion_buzzer else OTHER_SENSORS_TIMEOUT
                            log_event('AUTO', f'🔔 Buzzer turned OFF (auto) - Timeout: {timeout_used}s elapsed')
                    else:
                        # Keep on if timeout hasn't passed (even if motion stopped)
                        should_buzzer_on = True
            
            # Also handle case where should_buzzer_on is False and buzzer is on (for other conditions)
            if not should_buzzer_on and control.get('buzzer_on', False):
                # Turn off buzzer if conditions no longer met
                if not control.get('buzzer_manual_off', False):
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute('''
                        UPDATE system_control 
                        SET buzzer_on = FALSE, buzzer_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                        WHERE id = 1
                    ''')
                    conn.commit()
                    conn.close()
                    log_event('AUTO', '🔔 Buzzer turned OFF (auto) - Conditions no longer met')
        
        # Keep light on for minimum timeout if motion/door/fire was detected
        # Check if light was activated by motion/door/fire and is still within timeout
        # IMPORTANT: Only check timeouts in AUTO mode - in MANUAL mode, user has full control
        if not control['manual_mode'] and control.get('light_on', False) and control.get('light_activated_at'):
            light_activated = control['light_activated_at']
            if isinstance(light_activated, datetime):
                # Make sure light_activated is timezone-aware and in UTC
                if light_activated.tzinfo is None:
                    light_activated = light_activated.replace(tzinfo=timezone.utc)
                else:
                    # Convert to UTC if it's in a different timezone
                    light_activated = light_activated.astimezone(timezone.utc)
                
                time_elapsed = (now - light_activated).total_seconds()
                
                # Check if this light was activated by motion (keep on for 60s regardless of current motion state)
                # IMPORTANT: Only motion should use 60s timeout. All other sensors (fire, door, air quality, sound) use 10s.
                # IMPORTANT: If motion is currently active, it's ALWAYS a motion light (60s timeout)
                # This ensures motion-triggered lights get the full 60s timeout even if other sensors are also active
                # Priority: Motion > Other sensors for light timeout
                if motion_alert_active:
                    # Motion is active, so it's definitely a motion light (60s timeout)
                    is_motion_light = True
                else:
                    # Motion is not active - check if we're within 60s and no other sensor is active
                    other_sensor_active = (door_opened_this_cycle or fire_detected_this_cycle or 
                                          flame_detected or air_quality > AIR_QUALITY_THRESHOLD or 
                                          sound_level > SOUND_THRESHOLD)
                    
                    if not other_sensor_active and time_elapsed < MOTION_LIGHT_TIMEOUT:
                        # No other sensor active and within 60s, likely motion (use 60s timeout)
                        is_motion_light = True
                    else:
                        # Other sensor is active or timeout passed, so it's NOT motion (use 10s timeout)
                        is_motion_light = False
                
                # Override should_light_on based on timeout - keep on if timeout hasn't passed, turn off if it has
                # BUT: Only keep on if the sensor's light control is enabled
                if is_motion_light:
                    # Motion: keep on for 60 seconds, turn off after 60 seconds
                    if time_elapsed >= MOTION_LIGHT_TIMEOUT:
                        should_light_on = False  # Turn off after 60 seconds
                        # Immediately update database to turn off light
                        conn_timeout = get_db_connection()
                        cur_timeout = conn_timeout.cursor()
                        cur_timeout.execute('''
                            UPDATE system_control 
                            SET light_on = FALSE, light_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                        ''')
                        conn_timeout.commit()
                        conn_timeout.close()
                        log_event('AUTO', f'💡 Light turned OFF (auto) - Motion timeout: {MOTION_LIGHT_TIMEOUT}s elapsed')
                    else:
                        # Check if motion sensor's light control is enabled
                        if is_sensor_control_enabled('PIR Motion Sensor', 'light'):
                            should_light_on = True  # Keep on if timeout hasn't passed (even if motion stopped)
                        else:
                            should_light_on = False  # Turn off if sensor control is disabled
                else:
                    # Other sensors: keep on for 10 seconds, turn off after 10 seconds
                    # Don't check current sensor readings - just check timeout and sensor control enabled
                    if time_elapsed >= OTHER_SENSORS_TIMEOUT:
                        should_light_on = False  # Turn off after 10 seconds
                        # Immediately update database to turn off light
                        conn_timeout = get_db_connection()
                        cur_timeout = conn_timeout.cursor()
                        cur_timeout.execute('''
                            UPDATE system_control 
                            SET light_on = FALSE, light_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                        ''')
                        conn_timeout.commit()
                        conn_timeout.close()
                        log_event('AUTO', f'💡 Light turned OFF (auto) - Timeout: {OTHER_SENSORS_TIMEOUT}s elapsed')
                    else:
                        # Check if any sensor that could have triggered the light has light enabled
                        # This ensures light stays on for full timeout even if sensor reading becomes normal
                        # We check all sensors with OR (not elif) because any of them could have triggered it
                        sensor_light_enabled = (is_sensor_control_enabled('Flame Sensor', 'light') or
                                               is_sensor_control_enabled('MQ135 Air Quality Sensor', 'light') or
                                               is_sensor_control_enabled('Sound Sensor', 'light') or
                                               is_sensor_control_enabled('Reed Switch (Door Sensor)', 'light'))
                        
                        if sensor_light_enabled:
                            should_light_on = True  # Keep on if timeout hasn't passed (even if sensor reading is now normal)
                        else:
                            should_light_on = False  # Turn off if all sensor controls are disabled
        
        # Process auto-lighting (only if not in manual mode)
        # NOTE: This section should NOT re-activate light if timeout has passed
        # The timeout check above already handles turning off the light
        if not control['manual_mode']:
            low_light = light_level > LIGHT_THRESHOLD  # Higher value = darker
            
            # Lights should be on if:
            # 1. Any alert condition (fire, gas, noise, motion/door while away) - already set above
            # 2. Motion detected in low light (but only if timeout hasn't passed AND light is currently off)
            # 3. Door opened in low light (but only if timeout hasn't passed AND light is currently off)
            # IMPORTANT: Only activate if light is currently OFF (not already on from previous activation)
            if not should_light_on and not control.get('light_on', False):
                # Check if timeout has passed before allowing sensor to turn on light
                timeout_passed = False
                if control.get('light_activated_at') and isinstance(control.get('light_activated_at'), datetime):
                    light_activated = control['light_activated_at']
                    if light_activated.tzinfo is None:
                        light_activated = light_activated.replace(tzinfo=timezone.utc)
                    else:
                        # Convert to UTC if it's in a different timezone
                        light_activated = light_activated.astimezone(timezone.utc)
                    time_elapsed = (now - light_activated).total_seconds()
                    # Check if this was a motion light
                    # IMPORTANT: Only motion should use 60s timeout. All other sensors use 10s.
                    # Motion must be active AND no other sensor was detected this cycle
                    is_motion_light = motion_alert_active and not (door_opened_this_cycle or fire_detected_this_cycle or 
                                                                   flame_detected or air_quality > AIR_QUALITY_THRESHOLD or 
                                                                   sound_level > SOUND_THRESHOLD)
                    if is_motion_light:
                        timeout_passed = time_elapsed >= MOTION_LIGHT_TIMEOUT
                    else:
                        timeout_passed = time_elapsed >= OTHER_SENSORS_TIMEOUT
                else:
                    # No activation time means light was never on, so timeout has "passed" (can activate)
                    timeout_passed = True  # Allow activation if light was never on
                
                # Only allow sensor to turn on light if timeout has passed (light was off) AND sensor control is enabled
                # This prevents re-activation immediately after timeout
                if timeout_passed and (pir_motion or door_open) and low_light:
                    if pir_motion and is_sensor_control_enabled('PIR Motion Sensor', 'light'):
                        should_light_on = True
                    elif door_open and is_sensor_control_enabled('Reed Switch (Door Sensor)', 'light'):
                        should_light_on = True
            
            # Adjust brightness based on ambient light
            target_brightness = control['brightness_level']
            if should_light_on:
                # Map light_level (0-4095) to brightness (20-100%)
                # Higher light_level (darker) = higher brightness needed
                # Invert the mapping: 4095 (dark) -> 100%, 0 (bright) -> 20%
                target_brightness = int(map_value(light_level, LIGHT_THRESHOLD, 4095, 20, 100))
                target_brightness = max(20, min(100, target_brightness))  # Clamp to 20-100
            else:
                # If light should be off, keep current brightness for when it turns on again
                target_brightness = control['brightness_level']
            
            # Update light state if needed
            # IMPORTANT: Only update light state in AUTO mode - in MANUAL mode, user has full control
            # IMPORTANT: If should_light_on is False, check timeout before turning off
            # The light should stay on until its timeout expires, even if the triggering condition is gone
            if not control['manual_mode'] and not should_light_on and control.get('light_on', False):
                # Before turning off, check if light is still within its timeout period
                can_turn_off = True
                if control.get('light_activated_at'):
                    light_activated = control['light_activated_at']
                    if isinstance(light_activated, datetime):
                        if light_activated.tzinfo is None:
                            light_activated = light_activated.replace(tzinfo=timezone.utc)
                        else:
                            light_activated = light_activated.astimezone(timezone.utc)
                        
                        time_elapsed = (now - light_activated).total_seconds()
                        
                        # Check if we're still within timeout period
                        # If motion light (within 60s), don't turn off
                        # If other sensor light (within 10s), don't turn off
                        if time_elapsed < MOTION_LIGHT_TIMEOUT:
                            # Still within possible timeout, don't turn off
                            can_turn_off = False
                
                # Only turn off if timeout has passed
                if can_turn_off:
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute('''
                        UPDATE system_control 
                        SET light_on = FALSE, brightness_level = %s, light_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                        WHERE id = 1
                    ''', (target_brightness,))
                    conn.commit()
                    conn.close()
                    log_event('AUTO', '💡 Light turned OFF (auto) - Conditions/timeout')
            elif not control['manual_mode'] and (should_light_on != control['light_on'] or (should_light_on and target_brightness != control['brightness_level'])):
                # Only update light state in AUTO mode - in MANUAL mode, user has full control
                conn = get_db_connection()
                cur = conn.cursor()
                if should_light_on:
                    # Light turning ON - set activation time
                    cur.execute('''
                        UPDATE system_control 
                        SET light_on = %s, brightness_level = %s, light_activated_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                        WHERE id = 1
                    ''', (should_light_on, target_brightness))
                    conn.commit()
                    conn.close()
                    log_event('AUTO', f'💡 Light turned ON (auto) - Brightness: {target_brightness}%')
                else:
                    # Light turning OFF - clear activation time
                    cur.execute('''
                        UPDATE system_control 
                        SET light_on = %s, brightness_level = %s, light_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                        WHERE id = 1
                    ''', (should_light_on, target_brightness))
                    conn.commit()
                    conn.close()
                    log_event('AUTO', '💡 Light turned OFF (auto) - Conditions no longer met')
            # Always check timeout for light - turn off if timeout has passed
            # This ensures light turns off after timeout even if sensor is still active
            # IMPORTANT: Only check timeouts in AUTO mode - in MANUAL mode, user has full control
            if not control['manual_mode'] and control.get('light_on', False) and control.get('light_activated_at'):
                light_activated = control['light_activated_at']
                if isinstance(light_activated, datetime):
                    # Make sure light_activated is timezone-aware and in UTC
                    if light_activated.tzinfo is None:
                        light_activated = light_activated.replace(tzinfo=timezone.utc)
                    else:
                        # Convert to UTC if it's in a different timezone
                        light_activated = light_activated.astimezone(timezone.utc)
                
                time_elapsed = (now - light_activated).total_seconds()
                
                # Determine if this light was activated by motion
                # IMPORTANT: Only motion should use 60s timeout. All other sensors use 10s.
                # Strategy: If no other sensor is active AND (motion is currently active OR we're within 60s), assume it's motion
                # This handles the case where motion has stopped but we're still within the 60s timeout
                other_sensor_active = (door_opened_this_cycle or fire_detected_this_cycle or 
                                      flame_detected or air_quality > AIR_QUALITY_THRESHOLD or 
                                      sound_level > SOUND_THRESHOLD)
                
                if not other_sensor_active:
                    # If motion is currently active, definitely motion
                    # OR if we're within 60s and no other sensor is active, likely motion (use 60s timeout)
                    is_motion_light = motion_alert_active or time_elapsed < MOTION_LIGHT_TIMEOUT
                else:
                    # Other sensor is active, so it's NOT motion (use 10s timeout)
                    is_motion_light = False
                
                # Turn off if timeout has passed, otherwise keep on
                if is_motion_light:
                    if time_elapsed >= MOTION_LIGHT_TIMEOUT:
                        should_light_on = False  # Override sensor-based setting
                        # Turn off light
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute('''
                            UPDATE system_control 
                            SET light_on = FALSE, light_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                        ''')
                        conn.commit()
                        conn.close()
                        log_event('AUTO', f'💡 Light turned OFF (auto) - Motion timeout: {MOTION_LIGHT_TIMEOUT}s elapsed')
                    else:
                        # Keep on if timeout hasn't passed AND motion sensor's light control is enabled
                        if is_sensor_control_enabled('PIR Motion Sensor', 'light'):
                            should_light_on = True  # Keep on if timeout hasn't passed (even if motion stopped)
                        else:
                            should_light_on = False  # Turn off if sensor control is disabled
                else:
                    if time_elapsed >= OTHER_SENSORS_TIMEOUT:
                        should_light_on = False  # Override sensor-based setting
                        # Turn off light
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute('''
                            UPDATE system_control 
                            SET light_on = FALSE, light_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                        ''')
                        conn.commit()
                        conn.close()
                        log_event('AUTO', f'💡 Light turned OFF (auto) - Timeout: {OTHER_SENSORS_TIMEOUT}s elapsed')
                    else:
                        # Keep on if timeout hasn't passed AND the triggering sensor's light control is enabled
                        # Don't check current sensor readings - just check if timeout passed and sensor control enabled
                        # This ensures light stays on for full 10 seconds even if sensor reading becomes normal
                        # Check if any sensor that could have triggered the light has light enabled (use OR, not elif)
                        sensor_light_enabled = (is_sensor_control_enabled('Flame Sensor', 'light') or
                                               is_sensor_control_enabled('MQ135 Air Quality Sensor', 'light') or
                                               is_sensor_control_enabled('Sound Sensor', 'light') or
                                               is_sensor_control_enabled('Reed Switch (Door Sensor)', 'light'))
                        
                        if sensor_light_enabled:
                            should_light_on = True  # Keep on if timeout hasn't passed (even if sensor reading is now normal)
                        else:
                            should_light_on = False  # Turn off if all sensor controls are disabled
            
            # Also handle case where should_light_on is False and light is on (for other conditions)
            if not should_light_on and control.get('light_on', False):
                # Turn off light if conditions no longer met
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute('''
                    UPDATE system_control 
                    SET light_on = FALSE, light_activated_at = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                ''')
                conn.commit()
                conn.close()
                log_event('AUTO', '💡 Light turned OFF (auto) - Conditions no longer met')
            if should_light_on and control.get('light_on', False) and not control.get('light_activated_at'):
                # Update activation time if light is on but time not set
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute('''
                    UPDATE system_control 
                    SET light_activated_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1 AND light_activated_at IS NULL
                ''')
                conn.commit()
                conn.close()
        
        # Also handle manual mode - if user manually controls light, respect that
        # But still activate for critical alerts (fire, gas) - these override manual mode
        if control['manual_mode']:
            # Critical alerts (fire, gas) override manual mode for lights and buzzer
            if flame_detected or air_quality > AIR_QUALITY_THRESHOLD:
                if flame_detected and is_sensor_control_enabled('Flame Sensor', 'light'):
                    if not control.get('light_on', False):
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute('''
                            UPDATE system_control 
                            SET light_on = TRUE, light_activated_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                        ''')
                        conn.commit()
                        conn.close()
                        log_event('ALERT', '💡 Light turned ON (critical alert override - fire)')
                if air_quality > AIR_QUALITY_THRESHOLD and is_sensor_control_enabled('MQ135 Air Quality Sensor', 'light'):
                    if not control.get('light_on', False):
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute('''
                            UPDATE system_control 
                            SET light_on = TRUE, light_activated_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                            WHERE id = 1
                        ''')
                        conn.commit()
                        conn.close()
                        log_event('ALERT', '💡 Light turned ON (critical alert override - gas)')
        
        # Note: Auto-turn OFF logic is handled above in the main buzzer control section
        # This ensures buzzer stays on for minimum duration and respects all conditions
        
    except Exception as e:
        print(f"Error processing alerts and controls: {e}")

def send_email_notification(title, message):
    """Send email notification via SMTP if enabled."""
    if not EMAIL_ENABLED:
        return
    if not (EMAIL_SENDER and EMAIL_SENDER_PASSWORD and EMAIL_RECIPIENTS):
        print("⚠️ Email notification skipped: missing configuration.")
        return
    
    try:
        mime = MIMEText(message)
        mime['Subject'] = title
        mime['From'] = EMAIL_SENDER
        mime['To'] = ', '.join(EMAIL_RECIPIENTS)
        
        context = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(EMAIL_SENDER, EMAIL_SENDER_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENTS, mime.as_string())
    except Exception as e:
        print(f"Error sending email notification: {e}")


def send_notification(title, message, notification_type='info'):
    """Send notification (dashboard + optional email)."""
    try:
        print(f"📧 NOTIFICATION: {title} - {message}")
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO notifications (title, message, notification_type)
            VALUES (%s, %s, %s)
            RETURNING id
        ''', (title, message, notification_type))
        notification_id = cur.fetchone()[0]
        conn.commit()
        conn.close()
        
        send_email_notification(title, message)
        return notification_id
    except Exception as e:
        print(f"Error sending notification: {e}")
        return None

def map_value(value, from_min, from_max, to_min, to_max):
    """Map a value from one range to another"""
    if from_max == from_min:
        return to_min
    return to_min + (value - from_min) * (to_max - to_min) / (from_max - from_min)

if __name__ == '__main__':
    # Initialize database
    init_database()
    
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    print("🚀 Starting Smart Home Monitoring Server...")
    print("📊 Dashboard will be available at: http://localhost:8888")
    print("🔐 Default login: admin / admin123")
    print("⚠️  Change default credentials in production!")
    
    app.run(host='0.0.0.0', port=8888, debug=False)


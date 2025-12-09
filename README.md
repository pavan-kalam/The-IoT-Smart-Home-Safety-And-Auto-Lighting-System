# Smart Home Safety & Auto-Lighting System - Setup Guide

This IoT project consists of two ESP32 boards (Sensor Board and Control Board) communicating via ESP-NOW, with a Python Flask server managing the system and storing data in PostgreSQL.

## Table of Contents

1. [Hardware Setup](#hardware-setup)
2. [MAC Address Configuration](#mac-address-configuration)
3. [WiFi Configuration](#wifi-configuration)
4. [PostgreSQL Database Setup](#postgresql-database-setup)
5. [Python Server Setup](#python-server-setup)
6. [Dashboard Configuration](#dashboard-configuration)
7. [Troubleshooting](#troubleshooting)

---

## Hardware Setup

### Required Components

**ESP32 Sensor Board (Board 1):**
- PIR Motion Sensor
- Flame Sensor
- MQ135 Air Quality Sensor
- Reed Switch (Door Sensor)
- Analog Sound Sensor
- LDR Light Sensor
- DHT11 (Temperature & Humidity)

**ESP32 Control Board (Board 2):**
- 5V 1-Channel Relay Module (for lights)
- Active Buzzer (for alerts)

### Pin Connections

**Sensor Board:**
- PIR Motion Sensor: GPIO 12
- Reed Switch: GPIO 13
- Flame Sensor: GPIO 14
- Sound Sensor: GPIO 33 (Analog)
- MQ135 Air Quality: GPIO 34 (Analog)
- LDR Light Sensor: GPIO 32 (Analog)
- DHT11: GPIO 27

**Control Board:**
- Relay Module: GPIO 25
- Active Buzzer: GPIO 26

---

## MAC Address Configuration

### Step 1: Get MAC Addresses

#### Sensor Board MAC Address

1. Upload `esp32_sensor_board.ino` to the Sensor Board (ESP32 Board 1)
2. Open Serial Monitor (115200 baud)
3. Look for the MAC address printed at startup:
   ```
   ========================================
      MAC ADDRESS - COPY THIS!
   ========================================
   📡 SENSOR BOARD MAC: XX:XX:XX:XX:XX:XX
   ⚠️ COPY THIS MAC to Control Board code (line 54)!
   ========================================
   ```
4. **Copy this MAC address** - you'll need it for the Control Board

#### Control Board MAC Address

1. Upload `esp32_control_board.ino` to the Control Board (ESP32 Board 2)
2. Open Serial Monitor (115200 baud)
3. Look for the MAC address printed at startup:
   ```
   ========================================
      MAC ADDRESS - COPY THIS!
   ========================================
   📡 CONTROL BOARD MAC: XX:XX:XX:XX:XX:XX
   ⚠️ COPY THIS MAC to Sensor Board code (line 54)!
   ========================================
   ```
4. **Copy this MAC address** - you'll need it for the Sensor Board

### Step 2: Configure MAC Addresses in Code

#### Update Sensor Board Code

1. Open `Project Source Code/esp32_sensor_board/esp32_sensor_board.ino`
2. Find line 54 (around the ESP-NOW Configuration section):
   ```cpp
   uint8_t controlBoardMAC[] = {0x1C, 0x69, 0x20, 0x30, 0x7C, 0xD4};
   ```
3. Replace with the **Control Board MAC address** you copied:
   ```cpp
   uint8_t controlBoardMAC[] = {0xXX, 0xXX, 0xXX, 0xXX, 0xXX, 0xXX};
   ```
   - Convert MAC format `XX:XX:XX:XX:XX:XX` to hex array `{0xXX, 0xXX, 0xXX, 0xXX, 0xXX, 0xXX}`
   - Example: `1C:69:20:30:7C:D4` becomes `{0x1C, 0x69, 0x20, 0x30, 0x7C, 0xD4}`
4. Save and re-upload the code to Sensor Board

#### Update Control Board Code

1. Open `Project Source Code/esp32_control_board/esp32_control_board.ino`
2. Find line 54 (around the ESP-NOW Configuration section):
   ```cpp
   uint8_t sensorBoardMAC[] = {0xF4, 0x65, 0x0B, 0xC2, 0x55, 0x98};
   ```
3. Replace with the **Sensor Board MAC address** you copied:
   ```cpp
   uint8_t sensorBoardMAC[] = {0xXX, 0xXX, 0xXX, 0xXX, 0xXX, 0xXX};
   ```
   - Convert MAC format `XX:XX:XX:XX:XX:XX` to hex array `{0xXX, 0xXX, 0xXX, 0xXX, 0xXX, 0xXX}`
   - Example: `F4:65:0B:C2:55:98` becomes `{0xF4, 0x65, 0x0B, 0xC2, 0x55, 0x98}`
4. Save and re-upload the code to Control Board

### Step 3: Verify MAC Address Configuration

After uploading both boards:

1. **Sensor Board Serial Monitor** should show:
   ```
   🔧 Configured Control Board MAC: XX:XX:XX:XX:XX:XX
   ✅ Control Board added as ESP-NOW peer successfully
   ```

2. **Control Board Serial Monitor** should show:
   ```
   🔧 Configured Sensor Board MAC: XX:XX:XX:XX:XX:XX
   ✅ Sensor Board added as ESP-NOW peer
   ```

3. **Test ESP-NOW Communication:**
   - Sensor Board should show: `✅ Sensor data sent successfully to: XX:XX:XX:XX:XX:XX`
   - Control Board should show: `✅ Sensor data received and processed via ESP-NOW`

---

## WiFi Configuration

### Control Board WiFi Setup (Hardcoded in Code)

The Control Board uses **hardcoded WiFi credentials** that must be updated in the code:

1. Open `Project Source Code/esp32_control_board/esp32_control_board.ino`
2. Update with your WiFi credentials:
   ```cpp
   const char* WIFI_SSID = "YourWiFiNetwork";
   const char* WIFI_PASSWORD = "YourWiFiPassword";
   ```
3. Save and re-upload the code to Control Board

**Note:** The Control Board requires WiFi to communicate with the Python server. ESP-NOW communication with Sensor Board works independently of WiFi.

### Sensor Board WiFi Setup (Interactive via Serial Monitor)

The Sensor Board uses an **interactive WiFi setup** via Serial Monitor:

1. Upload `esp32_sensor_board.ino` to Sensor Board
2. Open Serial Monitor (115200 baud)
3. The board will scan for available WiFi networks and display them:
   ```
   Scanning for available networks...
   Found X networks:
   1: NetworkName1 (RSSI: -45)
   2: NetworkName2 (RSSI: -67)
   ...
   ```
4. **Select WiFi network:**
   - Option 1: Enter network number (1-X)
   - Option 2: Enter full SSID manually
5. **Enter WiFi Password** when prompted
6. **Enter Server URL** when prompted (e.g., `http://192.168.1.222:8888/api/sensor-data`)

**Note:** WiFi is optional for Sensor Board - ESP-NOW communication works without WiFi. WiFi is only needed for server commands (monitoring, encryption settings).

### Changing WiFi Settings via Dashboard

#### Sensor Board WiFi Settings

1. Login to the dashboard at `http://your-server-ip:8888`
2. Scroll down to **"📡 Sensor Board Controls (ESP32 Board 1)"** section
3. Click **"Change WiFi Settings"** button
4. Enter:
   - **WiFi SSID:** Your WiFi network name
   - **WiFi Password:** Your WiFi password
   - **Server URL:** `http://your-server-ip:8888/api/sensor-data`
5. Click **"Save WiFi Settings"**
6. The Sensor Board will automatically reconnect to the new WiFi network

#### Control Board Server URL Configuration

1. Login to the dashboard at `http://your-server-ip:8888`
2. Scroll down to **"🔧 Control Board Configuration (ESP32 Board 2)"** section
3. Enter the **Server URL** (e.g., `http://192.168.1.222:8888`)
4. Click **"Save URL"**
5. The Control Board will automatically retrieve this URL from the server

**Note:** Control Board WiFi credentials must be changed in code (see above). Only the Server URL can be configured via dashboard.

---

## PostgreSQL Database Setup

### Step 1: Install PostgreSQL

#### macOS
```bash
brew install postgresql@14
brew services start postgresql@14
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

#### Windows
Download and install from: https://www.postgresql.org/download/windows/

### Step 2: Create Database and User

1. **Access PostgreSQL:**
   ```bash
   # macOS/Linux
   sudo -u postgres psql
   
   # Or if using default user
   psql postgres
   ```

2. **Create Database:**
   ```sql
   CREATE DATABASE smart_home_db;
   ```

3. **Create User:**
   ```sql
   CREATE USER iotuser WITH PASSWORD 'iotpassword';
   ```

4. **Grant Privileges:**
   ```sql
   GRANT ALL PRIVILEGES ON DATABASE smart_home_db TO iotuser;
   \c smart_home_db
   GRANT ALL ON SCHEMA public TO iotuser;
   ```

5. **Exit PostgreSQL:**
   ```sql
   \q
   ```

### Step 3: Configure Environment Variables

The Python server uses environment variables for database configuration. You can set them in several ways:

#### Option 1: Environment Variables (Recommended)

Create a `.env` file in the `python_server` directory (or set system environment variables):

```bash
export POSTGRES_HOST=localhost
export POSTGRES_DATABASE=smart_home_db
export POSTGRES_USER=iotuser
export POSTGRES_PASSWORD=iotpassword
export POSTGRES_PORT=5432
```

#### Option 2: Modify server.py (Not Recommended)

Default values in `server.py` (lines 40-46):
```python
POSTGRES_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'database': os.getenv('POSTGRES_DATABASE', 'smart_home_db'),
    'user': os.getenv('POSTGRES_USER', 'iotuser'),
    'password': os.getenv('POSTGRES_PASSWORD', 'iotpassword'),
    'port': int(os.getenv('POSTGRES_PORT', '5432'))
}
```

### Step 4: Verify Database Connection

The database tables will be automatically created when you start the Python server. The `init_database()` function creates the following tables:

- `sensor_data` - Stores sensor readings
- `users` - User accounts for dashboard login
- `system_control` - Control Board commands and settings
- `sensor_board_control` - Sensor Board commands and settings
- `event_log` - System events and logs
- `sensor_controls` - Individual sensor control settings
- `sensor_events` - Sensor event history

---

## Python Server Setup

### Step 1: Install Python Dependencies

1. **Navigate to the server directory:**
   ```bash
   cd "Project Source Code/python_server"
   ```

2. **Create virtual environment (recommended):**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install required packages:**
   ```bash
   pip install -r requirements.txt
   ```

   Required packages:
   - Flask==2.3.3
   - pycryptodome==3.19.0
   - requests==2.31.0
   - Werkzeug==2.3.7
   - psycopg2-binary==2.9.9

### Step 2: Configure Server Settings

#### Database Configuration
Set PostgreSQL environment variables (see [PostgreSQL Database Setup](#postgresql-database-setup))

#### Email Notifications (Optional)
Set environment variables for email notifications:
```bash
export EMAIL_ENABLED=true
export EMAIL_SMTP_SERVER=smtp.gmail.com
export EMAIL_SMTP_PORT=587
export EMAIL_SENDER=your-email@gmail.com
export EMAIL_SENDER_PASSWORD=your-app-password
export EMAIL_RECIPIENTS=recipient1@example.com,recipient2@example.com
```

#### Flask Secret Key
Set a secure secret key for Flask sessions:
```bash
export FLASK_SECRET_KEY=your-secret-key-change-in-production
```

### Step 3: Start the Server

1. **Make sure PostgreSQL is running:**
   ```bash
   # Check PostgreSQL status
   brew services list  # macOS
   sudo systemctl status postgresql  # Linux
   ```

2. **Start the Python server:**
   ```bash
   python server.py
   ```

   Or with environment variables:
   ```bash
   POSTGRES_HOST=localhost POSTGRES_DATABASE=smart_home_db POSTGRES_USER=iotuser POSTGRES_PASSWORD=iotpassword python server.py
   ```

3. **Server will start and display:**
   ```
   🚀 Starting Smart Home Monitoring Server...
   📊 Dashboard will be available at: http://localhost:8888
   🔐 Default login: admin / admin123
   ⚠️  Change default credentials in production!
   ✅ Database initialized successfully!
   ```

4. **Access the dashboard:**
   - Local: `http://localhost:8888`
   - Network: `http://your-server-ip:8888`

### Step 4: Default Login Credentials

- **Username:** `admin`
- **Password:** `admin123`

**⚠️ IMPORTANT:** Change these credentials in production! You can register a new user or change password via the dashboard.

---

## Dashboard Configuration

### Accessing the Dashboard

1. Open a web browser
2. Navigate to: `http://your-server-ip:8888`
3. Login with credentials (default: `admin` / `admin123`)

### Sensor Board Configuration via Dashboard

1. **Scroll to "📡 Sensor Board Controls (ESP32 Board 1)"** section
2. **Available controls:**
   - **Monitoring:** Start/Stop sensor data collection
   - **Encryption:** Enable/Disable AES-128-CBC encryption
   - **Upload Interval:** Adjust data upload frequency (1000-10000 ms)
   - **Show Sensor Board Info:** Display current Sensor Board status
   - **Change WiFi Settings:** Update WiFi SSID, password, and server URL

3. **WiFi Settings Modal:**
   - Click **"Change WiFi Settings"** button
   - Enter:
     - WiFi SSID
     - WiFi Password
     - Server URL (e.g., `http://192.168.1.222:8888/api/sensor-data`)
   - Click **"Save WiFi Settings"**
   - Sensor Board will automatically reconnect to new WiFi

### Control Board Configuration via Dashboard

1. **Scroll to "🔧 Control Board Configuration (ESP32 Board 2)"** section
2. **Server URL Configuration:**
   - Enter Server URL (e.g., `http://192.168.1.222:8888`)
   - Click **"Save URL"**
   - Control Board will automatically retrieve this URL

**Note:** Control Board WiFi credentials must be changed in code (see [Control Board WiFi Setup](#control-board-wifi-setup-hardcoded-in-code)). Only the Server URL can be configured via dashboard.

### Viewing Board Information

#### Sensor Board Info
- Click **"Show Sensor Board Info"** in Sensor Board Controls section
- Displays:
  - Current monitoring status
  - Encryption status
  - Upload interval
  - WiFi connection status

#### Control Board Status
- Control Board status is displayed in the main dashboard
- Shows:
  - Light status (ON/OFF)
  - Buzzer status (ON/OFF)
  - Connection status

---

## Troubleshooting

### ESP-NOW Communication Issues

**Problem:** Sensor Board not sending data to Control Board

**Solutions:**
1. Verify MAC addresses are correctly configured in both boards
2. Check Serial Monitor for ESP-NOW errors
3. Ensure both boards are powered on
4. Check that boards are within range (ESP-NOW range: ~200m line-of-sight)
5. Verify peer registration messages in Serial Monitor:
   - Sensor Board: `✅ Control Board added as ESP-NOW peer successfully`
   - Control Board: `✅ Sensor Board added as ESP-NOW peer`

### WiFi Connection Issues

**Problem:** Control Board not connecting to WiFi

**Solutions:**
1. Verify WiFi SSID and password in code (lines 57-58)
2. Check WiFi network is available and password is correct
3. Check Serial Monitor for WiFi connection errors
4. Ensure WiFi signal strength is adequate (RSSI > -75 dBm)
5. Try restarting the board

**Problem:** Sensor Board not connecting to WiFi

**Solutions:**
1. Check Serial Monitor for WiFi setup prompts
2. Verify WiFi credentials entered correctly
3. Ensure server URL format is correct: `http://ip-address:port/api/sensor-data`
4. Use dashboard to update WiFi settings if needed

### Database Connection Issues

**Problem:** Server fails to connect to PostgreSQL

**Solutions:**
1. Verify PostgreSQL is running:
   ```bash
   brew services list  # macOS
   sudo systemctl status postgresql  # Linux
   ```
2. Check database credentials in environment variables
3. Verify database and user exist:
   ```bash
   psql -U iotuser -d smart_home_db
   ```
4. Check PostgreSQL logs for errors
5. Verify firewall allows connections on port 5432

### Server Not Starting

**Problem:** Python server fails to start

**Solutions:**
1. Check all dependencies are installed: `pip install -r requirements.txt`
2. Verify PostgreSQL is running
3. Check port 8888 is not already in use:
   ```bash
   lsof -i :8888  # macOS/Linux
   netstat -ano | findstr :8888  # Windows
   ```
4. Check server logs for error messages
5. Verify environment variables are set correctly

### Dashboard Not Accessible

**Problem:** Cannot access dashboard in browser

**Solutions:**
1. Verify server is running (check terminal output)
2. Check server IP address is correct
3. Ensure firewall allows connections on port 8888
4. Try accessing `http://localhost:8888` first
5. Check browser console for errors (F12)

### Sensor Data Not Appearing in Dashboard

**Problem:** Dashboard shows no sensor data

**Solutions:**
1. Verify ESP-NOW communication is working (check Serial Monitors)
2. Check Control Board is connected to WiFi
3. Verify Server URL is configured correctly in Control Board
4. Check server logs for incoming data
5. Verify database connection is working
6. Check browser console for JavaScript errors (F12)

---

## Additional Notes

### ESP-NOW vs WiFi

- **ESP-NOW:** Used for Sensor Board → Control Board communication (no WiFi needed)
- **WiFi:** Used for Control Board → Server communication and Sensor Board → Server commands

### Encryption

- Sensor data can be encrypted using AES-128-CBC with Base64 encoding
- Encryption can be enabled/disabled via dashboard
- Encryption key must match between Sensor Board, Control Board, and Server

### Power Requirements

- Both ESP32 boards can run on USB power (5V)
- Control Board can use power-only USB port after initial setup
- Sensor Board requires data USB port for Serial Monitor (optional after setup)

### Network Requirements

- All devices (ESP32 boards and server) must be on the same network for WiFi communication
- ESP-NOW works independently of WiFi network
- Server IP address must be accessible from ESP32 boards

---

## Support

For issues or questions:
1. Check Serial Monitor output from both ESP32 boards
2. Check server logs in terminal
3. Review database logs
4. Verify all configurations match this guide

---



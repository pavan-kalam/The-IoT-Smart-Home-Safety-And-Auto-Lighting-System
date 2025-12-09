/*
 * ESP32 Sensor Board (Board 1)
 * Collects data from all sensors and sends to Control Board via ESP-NOW
 * 
 * Features:
 * - ESP-NOW communication to Control Board (no WiFi needed for sensor data)
 * - WiFi for server commands (monitoring, encryption settings)
 * - AES-128-CBC encryption with PKCS7 padding (optional)
 * - Base64 encoding for secure transmission
 * - All sensors integrated
 * 
 * Sensors:
 * - PIR Motion Sensor
 * - Flame Sensor
 * - MQ135 Air Quality Sensor
 * - Reed Switch (Door Sensor)
 * - Analog Sound Sensor
 * - LDR Light Sensor
 * - DHT11 (Temperature & Humidity)
 * 
 * SETUP:
 * 1. Upload this code to ESP32 Board 1 (Sensor Board)
 * 2. Check Serial Monitor for this board's MAC address
 * 3. Update CONTROL_BOARD_MAC in control board code with this MAC address
 * 4. Update SENSOR_BOARD_MAC in this code with control board's MAC address
 */

#include <WiFi.h>
#include <esp_now.h>
#include <HTTPClient.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <time.h>
#include <mbedtls/aes.h>
#include <mbedtls/base64.h>

// Sensor Pins - Using Available Pins: D13, D12, D14, D27, D26, D25, D33, D32, D35, D34
// All analog sensors use ADC1 pins (D32, D33, D34, D35) - SAFE with WiFi
// All digital sensors use available GPIO pins
#define PIR_PIN 12        // Digital pin - PIR Motion Sensor OUT (GPIO 12)
#define REED_PIN 13       // Digital pin - Reed Switch (GPIO 13 with internal pull-up)
#define FLAME_PIN 14      // Digital pin - Flame Sensor DO (GPIO 14)
#define SOUND_PIN 33      // Analog pin - Sound Sensor A0 (GPIO 33 - ADC1_CH5 - SAFE with WiFi)
#define MQ135_PIN 34      // Analog pin - MQ135 Air Quality A0 (GPIO 34 - ADC1_CH6 - SAFE with WiFi)
#define LDR_PIN 32        // Analog pin - LDR Light Sensor A0 (GPIO 32 - ADC1_CH4 - SAFE with WiFi)
#define DHT_PIN 27        // Digital pin - DHT11 DATA (GPIO 27)
#define DHT_TYPE DHT11

// Initialize DHT sensor
DHT dht(DHT_PIN, DHT_TYPE);

// ESP-NOW Configuration
// REPLACE WITH YOUR CONTROL BOARD MAC ADDRESS (get from Serial Monitor)
uint8_t controlBoardMAC[] = {0x1C, 0x69, 0x20, 0x30, 0x7C, 0xD4};  // Control Board MAC: 1C:69:20:30:7C:D4

// Variables for WiFi and server configuration (for commands only)
String ssid;
String wifiPassword;
String serverUrl;  // e.g., "http://192.168.1.100:8888/api/sensor-data"

// Configurable settings
bool encryptEnabled = true;  // Encryption flag
long uploadInterval = 2000;  // Upload every 2 seconds
bool monitoring = true;  // Monitoring state (set to true to enable without WiFi, or false to enable via server)

// Timing
unsigned long lastReadTime = 0;
unsigned long lastSendTime = 0;
unsigned long lastPollTime = 0;
unsigned long lastDHTReadTime = 0;
const unsigned long readInterval = 1000;  // Read sensors every 1 second
const unsigned long dhtReadInterval = 2000;  // Read DHT11 every 2 seconds (minimum required)
const unsigned long pollInterval = 3000;  // Poll server for commands every 3 seconds

// Sensor States
bool pirState = false;
bool flameDetected = false;
bool doorOpen = false;
int airQuality = 0;
int soundLevel = 0;
int lightLevel = 0;
float temperature = 0;
float humidity = 0;

// Latest sensor readings
float lastTemperature = 0.0;
float lastHumidity = 0.0;
String lastTimestamp = "";

// NTP settings for Unix timestamp
const char* ntpServer = "pool.ntp.org";
long gmtOffset_sec = 0;   // UTC for Unix time
int daylightOffset_sec = 0;

// 16-byte encryption key for AES-128-CBC (must match server.py exactly)
const unsigned char encryptionKey[16] = {
    'M', 'y', 'S', 'e', 'c', 'r', 'e', 't', 'K', 'e', 'y', '1', '2', '3', '4', '5'
};

// Debouncing
unsigned long lastPIRChange = 0;
unsigned long lastReedChange = 0;
const unsigned long debounceDelay = 50;

// ESP-NOW callback
void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
    char macStr[18];
    snprintf(macStr, sizeof(macStr), "%02x:%02x:%02x:%02x:%02x:%02x",
             mac_addr[0], mac_addr[1], mac_addr[2],
             mac_addr[3], mac_addr[4], mac_addr[5]);
    
    if (status == ESP_NOW_SEND_SUCCESS) {
        Serial.print("✅ Sensor data sent successfully to: ");
        Serial.println(macStr);
    } else {
        Serial.print("❌ ESP-NOW send failed to: ");
        Serial.println(macStr);
        Serial.print("   Status code: ");
        Serial.println(status);
        Serial.println("   Possible causes:");
        Serial.println("   - Control board not in range");
        Serial.println("   - Control board not powered on");
        Serial.println("   - Control board ESP-NOW not initialized");
        Serial.println("   - MAC address mismatch");
    }
}

// Function to wait for user input from serial monitor with timeout
void waitForSerialInput(String &input, String fieldName) {
    unsigned long timeout = millis() + 30000; // 30 second timeout
    input = "";
    
    while (millis() < timeout) {
        if (Serial.available() > 0) {
            input = Serial.readStringUntil('\n');
            input.trim();
            if (input.length() > 0) {
                Serial.println("Received: " + input);
                return;
            }
        }
        delay(100);
        if ((millis() % 5000) < 100) {
            Serial.print(".");
        }
    }
    
    Serial.println("\nTimeout! No input received for " + fieldName + ".");
    Serial.println("Restarting setup process...");
    ESP.restart();
}

void setup() {
    Serial.begin(115200);
    delay(2000); // Wait for serial to initialize
    
    Serial.println("ESP32 Sensor Board Starting...");
    Serial.println("=================================");
    
    // Initialize ESP-NOW FIRST (before WiFi connection)
    // ESP-NOW requires WiFi in STA mode but doesn't need connection
    Serial.println("\n=== Initializing ESP-NOW ===");
    WiFi.mode(WIFI_STA);
    delay(500); // Give WiFi time to initialize
    
    // NOW print MAC address (after WiFi.mode is set)
    Serial.println("\n\n");
    Serial.println("========================================");
    Serial.println("   MAC ADDRESS - COPY THIS!");
    Serial.println("========================================");
    Serial.print("📡 SENSOR BOARD MAC: ");
    Serial.println(WiFi.macAddress());
    Serial.println("⚠️ COPY THIS MAC to Control Board code (line 54)!");
    Serial.println("========================================");
    Serial.println("\n");
    
    // Print MAC address again for reference
    Serial.print("📡 Sensor Board MAC Address: ");
    Serial.println(WiFi.macAddress());
    Serial.println("⚠️ IMPORTANT: Copy this MAC address to Control Board code!");
    
    if (esp_now_init() != ESP_OK) {
        Serial.println("❌ Error initializing ESP-NOW");
        ESP.restart();
    }
    
    // Register send callback
    esp_now_register_send_cb((esp_now_send_cb_t)OnDataSent);
    
    // Debug: Print configured control board MAC
    char macStr[18];
    snprintf(macStr, sizeof(macStr), "%02x:%02x:%02x:%02x:%02x:%02x",
             controlBoardMAC[0], controlBoardMAC[1], controlBoardMAC[2],
             controlBoardMAC[3], controlBoardMAC[4], controlBoardMAC[5]);
    Serial.print("🔧 Configured Control Board MAC: ");
    Serial.println(macStr);
    
    // Remove peer if it already exists (to avoid conflicts)
    esp_now_del_peer(controlBoardMAC);
    
    // Add peer (Control Board)
    esp_now_peer_info_t peerInfo = {};
    memcpy(peerInfo.peer_addr, controlBoardMAC, 6);
    peerInfo.encrypt = false;
    
    // CRITICAL: Use channel 0 for auto-select (works with any WiFi channel)
    // Setting a specific channel causes "Peer channel is not equal to the home channel" error
    peerInfo.channel = 0;
    Serial.println("🔧 Using channel 0 (auto-select) for ESP-NOW");
    Serial.print("🔧 Adding peer with MAC: ");
    Serial.println(macStr);
    
    esp_err_t addPeerResult = esp_now_add_peer(&peerInfo);
    if (addPeerResult != ESP_OK) {
        Serial.println("❌ Failed to add Control Board as peer!");
        Serial.print("   Error code: ");
        Serial.println(addPeerResult);
        Serial.print("   Error: ");
        Serial.println(esp_err_to_name(addPeerResult));
        Serial.println("⚠️ ESP-NOW send may still work, but may fail if MAC is wrong");
    } else {
        Serial.println("✅ Control Board added as ESP-NOW peer successfully");
        // Verify the peer was added correctly
        esp_now_peer_info_t verifyPeer;
        if (esp_now_get_peer(controlBoardMAC, &verifyPeer) == ESP_OK) {
            Serial.println("✅ Peer verified - ready to send data");
            Serial.print("   Verified peer MAC: ");
            char verifyMacStr[18];
            snprintf(verifyMacStr, sizeof(verifyMacStr), "%02x:%02x:%02x:%02x:%02x:%02x",
                     verifyPeer.peer_addr[0], verifyPeer.peer_addr[1], verifyPeer.peer_addr[2],
                     verifyPeer.peer_addr[3], verifyPeer.peer_addr[4], verifyPeer.peer_addr[5]);
            Serial.println(verifyMacStr);
        } else {
            Serial.println("⚠️ Warning: Peer added but verification failed");
        }
    }
    
    Serial.println("=== ESP-NOW Ready ===\n");
    
    // Now setup WiFi for server commands (optional - ESP-NOW works without WiFi)
    Serial.println("=== WiFi Setup (for server commands) ===");
    Serial.println("Note: Sensor data is sent via ESP-NOW.");
    Serial.println("WiFi is only needed for server commands (monitoring, encryption settings).\n");
    
    // Scan for available WiFi networks
    Serial.println("Scanning for available networks...");
    int n = WiFi.scanNetworks();
    Serial.println("Found " + String(n) + " networks:");
    for (int i = 0; i < n; i++) {
        Serial.println(String(i+1) + ": " + WiFi.SSID(i) + " (RSSI: " + WiFi.RSSI(i) + ")");
    }
    
    // Input by user to select the network
    Serial.println("\nSelect WiFi network:");
    Serial.println("Option 1: Enter network number (1-" + String(n) + ")");
    Serial.println("Option 2: Enter full SSID manually");
    Serial.print("Your choice: ");
    
    String choice = "";
    unsigned long timeout = millis() + 30000;
    
    while (millis() < timeout) {
        if (Serial.available() > 0) {
            choice = Serial.readStringUntil('\n');
            choice.trim();
            if (choice.length() > 0) {
                Serial.println("Received: " + choice);
                break;
            }
        }
        delay(100);
    }
    
    // Identify if user entered number or SSID manually
    bool isNumber = true;
    for (int i = 0; i < choice.length(); i++) {
        if (!isDigit(choice.charAt(i))) {
            isNumber = false;
            break;
        }
    }
    
    if (isNumber && choice.toInt() >= 1 && choice.toInt() <= n) {
        int networkIndex = choice.toInt() - 1;
        ssid = WiFi.SSID(networkIndex);
        Serial.println("Selected network: " + ssid);
    } else {
        ssid = choice;
        Serial.println("Using SSID: " + ssid);
    }
    
    // Get WiFi password and server URL
    Serial.print("Enter WiFi Password: ");
    waitForSerialInput(wifiPassword, "WiFi Password");
    
    Serial.print("Enter Server URL (e.g., http://192.168.1.100:8888/api/sensor-data): ");
    waitForSerialInput(serverUrl, "Server URL");
    
    // Connect to WiFi
    WiFi.begin(ssid.c_str(), wifiPassword.c_str());
    Serial.print("Connecting to WiFi...");
    
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(1000);
        Serial.print(".");
        attempts++;
    }
    
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\n✅ Connected to WiFi");
        Serial.print("IP Address: ");
        Serial.println(WiFi.localIP());
        
        // Initialize NTP for timestamp
        configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);
        Serial.println("NTP time synchronized");
    } else {
        Serial.println("\n⚠️ WiFi connection failed!");
        Serial.println("ESP-NOW will still work for sensor data transmission.");
        Serial.println("WiFi is only needed for server commands.");
    }
    
    // Initialize pins - Using Available Pins: D12, D13, D14, D27, D32, D33, D34
    pinMode(PIR_PIN, INPUT);           // D12 - PIR Motion Sensor (Digital)
    pinMode(REED_PIN, INPUT_PULLUP);   // D13 - Reed Switch (Digital with internal pull-up)
    pinMode(FLAME_PIN, INPUT);         // D14 - Flame Sensor DO (Digital)
    pinMode(MQ135_PIN, INPUT);         // D34 - MQ135 Air Quality (Analog - ADC1_CH6 - SAFE with WiFi)
    pinMode(SOUND_PIN, INPUT);         // D33 - Sound Sensor (Analog - ADC1_CH5 - SAFE with WiFi)
    pinMode(LDR_PIN, INPUT);          // D32 - LDR Light Sensor (Analog - ADC1_CH4 - SAFE with WiFi)
    
    // Initialize DHT
    dht.begin();
    delay(2000);  // Give DHT11 time to stabilize after initialization
    
    // Try to read DHT11 once to verify it's working
    float testTemp = dht.readTemperature();
    float testHum = dht.readHumidity();
    if (!isnan(testTemp) && !isnan(testHum)) {
        Serial.println("✅ DHT11 sensor initialized successfully");
        lastTemperature = testTemp;
        lastHumidity = testHum;
    } else {
        Serial.println("⚠️ DHT11 sensor initialization - will retry on first read");
    }
    
    Serial.println("=================================");
    Serial.println("Sensor Board initialized");
    Serial.println("Monitoring: " + String(monitoring ? "Enabled" : "Disabled"));
    Serial.println("Upload Interval: " + String(uploadInterval) + " ms");
    Serial.println("Encryption: " + String(encryptEnabled ? "Enabled" : "Disabled"));
    Serial.println("=================================");
    Serial.println("✅ Sensor data will be sent via ESP-NOW");
    Serial.println("✅ WiFi is optional (only for server commands)");
    Serial.println("=================================");
}

void loop() {
    unsigned long currentTime = millis();
    
    // Print Sensor Board MAC every 30 seconds (first 3 times) for easy reference
    static int macPrintCount = 0;
    static unsigned long lastMacPrint = 0;
    if (macPrintCount < 3 && (currentTime - lastMacPrint > 30000)) {
        Serial.println("");
        Serial.println("========================================");
        Serial.print("📡 SENSOR BOARD MAC: ");
        Serial.println(WiFi.macAddress());
        Serial.println("⚠️ COPY THIS to Control Board code (line 54)!");
        Serial.println("========================================");
        Serial.println("");
        lastMacPrint = currentTime;
        macPrintCount++;
    }
    
    // Poll server for commands (monitoring, encryption, WiFi settings)
    if (currentTime - lastPollTime >= pollInterval) {
        if (WiFi.status() == WL_CONNECTED) {
            pollServerCommands();
        }
        lastPollTime = currentTime;
    }
    
    // Read sensors periodically (only if monitoring is enabled)
    if (monitoring && (currentTime - lastReadTime >= readInterval)) {
        readSensors();
        lastReadTime = currentTime;
    }
    
    // Send data to Control Board via ESP-NOW periodically (only if monitoring is enabled)
    if (monitoring && (currentTime - lastSendTime >= uploadInterval)) {
        sendDataViaESPNOW();
        lastSendTime = currentTime;
    }
    
    delay(10);
}

void readSensors() {
    // Read PIR Motion Sensor (with debouncing)
    bool currentPIR = digitalRead(PIR_PIN);
    if (currentPIR != pirState && (millis() - lastPIRChange > debounceDelay)) {
        pirState = currentPIR;
        lastPIRChange = millis();
        Serial.println(pirState ? "Motion detected!" : "Motion cleared");
    }
    
    // Read Flame Sensor (LOW when flame detected)
    flameDetected = !digitalRead(FLAME_PIN);
    
    // Read Reed Switch (LOW when door is open, HIGH when closed)
    bool currentReed = !digitalRead(REED_PIN);
    if (currentReed != doorOpen && (millis() - lastReedChange > debounceDelay)) {
        doorOpen = currentReed;
        lastReedChange = millis();
        Serial.println(doorOpen ? "Door opened!" : "Door closed");
    }
    
    // Read MQ135 Air Quality (0-4095, higher = more gas detected)
    airQuality = analogRead(MQ135_PIN);
    
    // Read Sound Sensor (0-4095, higher = louder)
    // Take multiple readings and average for better accuracy and stability
    int soundReadings = 0;
    for (int i = 0; i < 5; i++) {
        soundReadings += analogRead(SOUND_PIN);
        delay(2);
    }
    soundLevel = soundReadings / 5;  // Average of 5 readings
    
    // Read LDR Light Sensor (0-4095, higher = brighter)
    lightLevel = analogRead(LDR_PIN);
    
    // Read DHT11 (only every 2 seconds - minimum required delay)
    unsigned long currentTime = millis();
    if (currentTime - lastDHTReadTime >= dhtReadInterval) {
        // DHT11 needs a small delay before reading
        delay(50);  // Small delay to ensure sensor is ready
        
        // Try reading with retry logic
        float temp = dht.readTemperature();
        float hum = dht.readHumidity();
        
        // Retry once if reading failed
        if (isnan(temp) || isnan(hum)) {
            delay(100);  // Wait a bit longer
            temp = dht.readTemperature();
            hum = dht.readHumidity();
        }
        
        // Check if reading succeeded
        if (!isnan(temp) && !isnan(hum)) {
            temperature = temp;
            humidity = hum;
            lastTemperature = temperature;
            lastHumidity = humidity;
            lastDHTReadTime = currentTime;
        } else {
            // Use last known good values if reading failed
            Serial.println("⚠️ Failed to read from DHT sensor! Using last known values.");
            temperature = lastTemperature;
            humidity = lastHumidity;
            lastDHTReadTime = currentTime;  // Still update time to avoid spamming
        }
    } else {
        // Use last known values if not time to read yet
        temperature = lastTemperature;
        humidity = lastHumidity;
    }
}

// Structure to match data sent via ESP-NOW (max 250 bytes)
typedef struct struct_message {
    bool pir_motion;
    bool flame_detected;
    bool door_open;
    int air_quality;
    int sound_level;
    int light_level;
    float temperature;
    float humidity;
    unsigned long timestamp;
    bool is_encrypted;
} struct_message;

void sendDataViaESPNOW() {
    // Get Unix timestamp
    time_t now;
    time(&now);
    lastTimestamp = String(now);
    
    // Create data structure
    struct_message sensorData;
    sensorData.pir_motion = pirState;
    sensorData.flame_detected = flameDetected;
    sensorData.door_open = doorOpen;
    sensorData.air_quality = airQuality;
    sensorData.sound_level = soundLevel;
    sensorData.light_level = lightLevel;
    sensorData.temperature = temperature;
    sensorData.humidity = humidity;
    sensorData.timestamp = now;
    sensorData.is_encrypted = encryptEnabled;
    
    // Debug: Print destination MAC before sending
    char macStr[18];
    snprintf(macStr, sizeof(macStr), "%02x:%02x:%02x:%02x:%02x:%02x",
             controlBoardMAC[0], controlBoardMAC[1], controlBoardMAC[2],
             controlBoardMAC[3], controlBoardMAC[4], controlBoardMAC[5]);
    Serial.print("📤 Sending sensor data via ESP-NOW to: ");
    Serial.println(macStr);
    
    // Send via ESP-NOW
    esp_err_t result = esp_now_send(controlBoardMAC, (uint8_t *) &sensorData, sizeof(sensorData));
    
    if (result == ESP_OK) {
        Serial.println("   ✅ Send command successful (waiting for callback...)");
    } else {
        Serial.println("   ❌ ESP-NOW send error: " + String(esp_err_to_name(result)));
    }
}

void pollServerCommands() {
    HTTPClient http;
    String url = serverUrl;
    // Extract base URL (remove /api/sensor-data if present)
    int apiIndex = url.indexOf("/api/sensor-data");
    if (apiIndex > 0) {
        url = url.substring(0, apiIndex);
    }
    url += "/api/sensor-board/commands";
    
    http.begin(url);
    int httpCode = http.GET();
    
    if (httpCode > 0) {
        if (httpCode == HTTP_CODE_OK) {
            String payload = http.getString();
            
            StaticJsonDocument<512> doc;
            DeserializationError error = deserializeJson(doc, payload);
            
            if (!error) {
                // Update monitoring state
                bool newMonitoring = doc["monitoring"] | false;
                if (newMonitoring != monitoring) {
                    monitoring = newMonitoring;
                    Serial.println("📊 Monitoring: " + String(monitoring ? "STARTED" : "STOPPED"));
                }
                
                // Update encryption setting
                bool newEncryption = doc["encryption_enabled"] | true;
                if (newEncryption != encryptEnabled) {
                    encryptEnabled = newEncryption;
                    Serial.println("🔐 Encryption: " + String(encryptEnabled ? "ENABLED" : "DISABLED"));
                }
                
                // Update upload interval
                long newInterval = doc["upload_interval"] | 2000;
                if (newInterval != uploadInterval && newInterval >= 1000) {
                    uploadInterval = newInterval;
                    Serial.println("⏱️ Upload interval: " + String(uploadInterval) + " ms");
                }
                
                // Check for WiFi settings update
                String newSSID = doc["wifi_ssid"] | "";
                String newPassword = doc["wifi_password"] | "";
                String newServerUrl = doc["server_url"] | "";
                
                if (newSSID.length() > 0 && newSSID != ssid) {
                    Serial.println("📡 WiFi settings updated from server");
                    ssid = newSSID;
                    wifiPassword = newPassword;
                    serverUrl = newServerUrl;
                    
                    // Reconnect to new WiFi
                    Serial.println("Reconnecting to new WiFi network...");
                    WiFi.disconnect();
                    delay(1000);
                    WiFi.begin(ssid.c_str(), wifiPassword.c_str());
                    
                    int attempts = 0;
                    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
                        delay(1000);
                        Serial.print(".");
                        attempts++;
                    }
                    
                    if (WiFi.status() == WL_CONNECTED) {
                        Serial.println("\n✅ Connected to new WiFi: " + ssid);
                        Serial.println("IP Address: " + WiFi.localIP().toString());
                    } else {
                        Serial.println("\n❌ Failed to connect to new WiFi");
                    }
                }
            }
        }
    }
    
    http.end();
    
    // Send status update back to server
    sendStatusUpdate();
}

void sendStatusUpdate() {
    HTTPClient http;
    String url = serverUrl;
    int apiIndex = url.indexOf("/api/sensor-data");
    if (apiIndex > 0) {
        url = url.substring(0, apiIndex);
    }
    url += "/api/sensor-board/status";
    
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    
    StaticJsonDocument<128> doc;
    doc["monitoring"] = monitoring;
    doc["encryption_enabled"] = encryptEnabled;
    
    String payload;
    serializeJson(doc, payload);
    
    int httpCode = http.POST(payload);
    http.end();
}

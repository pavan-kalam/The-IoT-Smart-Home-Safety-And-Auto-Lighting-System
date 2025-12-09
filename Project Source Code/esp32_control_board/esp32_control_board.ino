/*
 * ESP32 Control Board (Board 2)
 * Receives sensor data from Sensor Board via ESP-NOW
 * Forwards sensor data to Python web server via WiFi/HTTP
 * Receives control commands from Python server
 * Controls relay (lights) and buzzer (alerts)
 * 
 * Features:
 * - ESP-NOW communication with Sensor Board (no WiFi needed for sensor data)
 * - WiFi for server communication (sensor data upload and command polling)
 * - WiFi credentials hardcoded in code (update WIFI_SSID and WIFI_PASSWORD)
 * - Server URL configurable via dashboard
 * - Works standalone (power-only USB) - Serial is optional for debugging
 * 
 * Controls:
 * - 5V 1-Channel Relay (for lights) - GPIO 25
 * - Active Buzzer (for alerts) - GPIO 26
 * 
 * SETUP INSTRUCTIONS:
 * 1. Upload this code to ESP32 Board 2 (Control Board) - use data port for first upload
 * 2. Check Serial Monitor for this board's MAC address (first time only)
 * 3. Update SENSOR_BOARD_MAC in sensor board code with this MAC address
 * 4. Update CONTROL_BOARD_MAC in this code with sensor board's MAC address
 * 5. Update WIFI_SSID and WIFI_PASSWORD below
 * 6. Configure Server URL in web dashboard
 * 7. After setup, can use power-only USB port - board works standalone
 */

 #include <WiFi.h>
 #include <esp_now.h>
 #include <HTTPClient.h>
 #include <ArduinoJson.h>
 #include <time.h>
 #include <mbedtls/aes.h>
 #include <mbedtls/base64.h>
 
 // Serial output helper - only prints if Serial is available (optional debugging)
 #define SERIAL_DEBUG true  // Set to false to disable all Serial output
 
 #if SERIAL_DEBUG
     #define DEBUG_PRINT(x) Serial.print(x)
     #define DEBUG_PRINTLN(x) Serial.println(x)
 #else
     #define DEBUG_PRINT(x)
     #define DEBUG_PRINTLN(x)
 #endif
 
 // Control Pins - Using Available Pins: D25, D26
 #define RELAY_PIN 25     // Relay Module IN (GPIO 25 - Digital Output)
 #define BUZZER_PIN 26    // Active Buzzer S (GPIO 26 - Digital Output)
 
 // ESP-NOW Configuration
 // REPLACE WITH YOUR SENSOR BOARD MAC ADDRESS (get from Serial Monitor)
 uint8_t sensorBoardMAC[] = {0xF4, 0x65, 0x0B, 0xC2, 0x55, 0x98};  // Sensor Board MAC: 1C:69:20:EA:DA:10
 
 // WiFi Configuration - UPDATE THESE VALUES IN CODE
 const char* WIFI_SSID = "Avengers";        // Change this to your WiFi network name
 const char* WIFI_PASSWORD = "Google@12345";  // Change this to your WiFi password
 
 // Server URL - Will be retrieved from server (configurable via dashboard)
 String serverUrl;  // e.g., "http://192.168.1.222:8888"

 // 16-byte encryption key for AES-128-CBC (must match server.py exactly)
 const unsigned char encryptionKey[16] = {
     'M', 'y', 'S', 'e', 'c', 'r', 'e', 't', 'K', 'e', 'y', '1', '2', '3', '4', '5'
 };
 
 // ESP-NOW data structure (must match sensor board)
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
 
 // Latest received sensor data
 struct_message latestSensorData;
 bool newSensorData = false;
 
 // System States
 bool lightOn = false;
 bool buzzerOn = false;
 bool manualMode = false;
 int brightnessLevel = 100;
 bool homeMode = true;
 
 // Timing
 unsigned long lastPollTime = 0;
 unsigned long lastStatusUpdate = 0;
 unsigned long lastSensorUpload = 0;
 unsigned long lastServerUrlRefresh = 0;
 unsigned long lastFailedPollTime = 0;
 int consecutiveFailures = 0;
 const unsigned long pollInterval = 1000;  // Poll server every 1 second
 const unsigned long statusUpdateInterval = 5000;  // Update status every 5 seconds
 const unsigned long sensorUploadInterval = 2000;  // Upload sensor data every 2 seconds
 const unsigned long serverUrlRefreshInterval = 30000;  // Refresh server URL every 30 seconds
 const int maxConsecutiveFailures = 3;  // Reset URL after 3 consecutive failures
 
 // ESP-NOW callback function
void OnDataRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
    // Debug: Print sender MAC address
    char macStr[18];
    snprintf(macStr, sizeof(macStr), "%02x:%02x:%02x:%02x:%02x:%02x",
             info->src_addr[0], info->src_addr[1], info->src_addr[2],
             info->src_addr[3], info->src_addr[4], info->src_addr[5]);
    DEBUG_PRINTLN("========================================");
    DEBUG_PRINT("📥 ESP-NOW data received from: ");
    DEBUG_PRINTLN(macStr);
    DEBUG_PRINT("   Data length: ");
    DEBUG_PRINT(len);
    DEBUG_PRINT(" bytes, Expected: ");
    DEBUG_PRINT(sizeof(struct_message));
    DEBUG_PRINTLN(" bytes");
    
    if (len == sizeof(struct_message)) {
        memcpy(&latestSensorData, data, sizeof(latestSensorData));
        newSensorData = true;
        DEBUG_PRINTLN("✅ Sensor data received and processed via ESP-NOW");
        DEBUG_PRINT("   Motion: ");
        DEBUG_PRINTLN(latestSensorData.pir_motion ? "YES" : "NO");
        DEBUG_PRINT("   Temperature: ");
        DEBUG_PRINT(latestSensorData.temperature);
        DEBUG_PRINTLN("°C");
    } else {
        DEBUG_PRINT("⚠️ Data length mismatch! Expected ");
        DEBUG_PRINT(sizeof(struct_message));
        DEBUG_PRINT(" bytes, got ");
        DEBUG_PRINTLN(len);
        DEBUG_PRINTLN("   Data will be ignored");
    }
    DEBUG_PRINTLN("========================================");
}
 
 void setup() {
     // Initialize Serial only if debugging is enabled
     #if SERIAL_DEBUG
         Serial.begin(115200);
         delay(2000); // Longer delay for Serial to initialize
     #endif
     
     DEBUG_PRINTLN("ESP32 Control Board Starting...");
     DEBUG_PRINTLN("=================================");
     
     // Initialize ESP-NOW first (before WiFi)
     DEBUG_PRINTLN("\n=== Initializing ESP-NOW ===");
     WiFi.mode(WIFI_STA);
     delay(500); // Give WiFi time to initialize
     
     // NOW print MAC address (after WiFi.mode is set)
     DEBUG_PRINTLN("\n\n");
     DEBUG_PRINTLN("========================================");
     DEBUG_PRINTLN("   MAC ADDRESS - COPY THIS!");
     DEBUG_PRINTLN("========================================");
     DEBUG_PRINT("📡 CONTROL BOARD MAC: ");
     DEBUG_PRINTLN(WiFi.macAddress());
     DEBUG_PRINTLN("⚠️ COPY THIS MAC to Sensor Board code (line 54)!");
     DEBUG_PRINTLN("========================================");
     DEBUG_PRINTLN("\n");
     
     // Print MAC address again for reference
     DEBUG_PRINT("📡 Control Board MAC Address: ");
     DEBUG_PRINTLN(WiFi.macAddress());
     DEBUG_PRINTLN("⚠️ IMPORTANT: Copy this MAC address to Sensor Board code!");
     
     if (esp_now_init() != ESP_OK) {
         DEBUG_PRINTLN("❌ Error initializing ESP-NOW");
         ESP.restart();
     }
     
    // Register receive callback
    esp_err_t recv_cb_result = esp_now_register_recv_cb(OnDataRecv);
    if (recv_cb_result == ESP_OK) {
        DEBUG_PRINTLN("✅ ESP-NOW receive callback registered successfully");
    } else {
        DEBUG_PRINTLN("❌ Failed to register ESP-NOW receive callback!");
        DEBUG_PRINTLN("   Error: " + String(esp_err_to_name(recv_cb_result)));
    }
    
    // Debug: Print configured sensor board MAC
    char macStr[18];
    snprintf(macStr, sizeof(macStr), "%02x:%02x:%02x:%02x:%02x:%02x",
             sensorBoardMAC[0], sensorBoardMAC[1], sensorBoardMAC[2],
             sensorBoardMAC[3], sensorBoardMAC[4], sensorBoardMAC[5]);
    DEBUG_PRINT("🔧 Configured Sensor Board MAC: ");
    DEBUG_PRINTLN(macStr);
    
    // Check if MAC is still default (broadcast address)
    bool isDefaultMAC = true;
    for (int i = 0; i < 6; i++) {
        if (sensorBoardMAC[i] != 0xFF) {
            isDefaultMAC = false;
            break;
        }
    }
    
    if (isDefaultMAC) {
        DEBUG_PRINTLN("⚠️ WARNING: Sensor Board MAC is still default (broadcast)!");
        DEBUG_PRINTLN("⚠️ ESP-NOW will receive from ANY sender (not secure, but will work)");
        DEBUG_PRINTLN("⚠️ To configure specific MAC, update sensorBoardMAC[] in code");
    } else {
        // Add peer (Sensor Board) - only if MAC is configured
        esp_now_peer_info_t peerInfo = {};
        memcpy(peerInfo.peer_addr, sensorBoardMAC, 6);
        peerInfo.encrypt = false;
        
        // CRITICAL: Use channel 0 for auto-select (works with any WiFi channel)
        // Setting a specific channel causes "Peer channel is not equal to the home channel" error
        peerInfo.channel = 0;
        DEBUG_PRINTLN("🔧 Using channel 0 (auto-select) for ESP-NOW");
        
        if (esp_now_add_peer(&peerInfo) != ESP_OK) {
            DEBUG_PRINTLN("❌ Failed to add Sensor Board as peer");
            DEBUG_PRINTLN("⚠️ ESP-NOW will still receive from any sender");
        } else {
            DEBUG_PRINTLN("✅ Sensor Board added as ESP-NOW peer");
        }
    }
    
    DEBUG_PRINTLN("📡 ESP-NOW is ready to receive data from any sender");
    DEBUG_PRINT("📏 Expected sensor data size: ");
    DEBUG_PRINT(sizeof(struct_message));
    DEBUG_PRINTLN(" bytes");
    DEBUG_PRINTLN("=== ESP-NOW Ready ===");
    DEBUG_PRINTLN("");
    DEBUG_PRINTLN("🔍 ESP-NOW DEBUGGING INFO:");
    DEBUG_PRINT("   📡 Control Board MAC: ");
    DEBUG_PRINTLN(WiFi.macAddress());
    DEBUG_PRINT("   🔧 Configured Sensor Board MAC: ");
    DEBUG_PRINTLN(macStr);
    if (isDefaultMAC) {
        DEBUG_PRINTLN("   ⚠️ WARNING: Using broadcast MAC - configure actual MAC for reliable communication!");
    }
    DEBUG_PRINTLN("   📥 Waiting for ESP-NOW data...");
    DEBUG_PRINTLN("   (If no data received, check MAC addresses are configured correctly)");
    DEBUG_PRINTLN("");
     
     // Configure WiFi for stable connection
     // CRITICAL: Disable WiFi power save mode to prevent disconnections
     WiFi.setSleep(false);  // Disable WiFi sleep mode (prevents random disconnections)
     WiFi.setAutoReconnect(true);  // Enable automatic reconnection
     WiFi.persistent(true);  // Save WiFi credentials to flash (persistent across reboots)
     
     // Connect to WiFi using hardcoded credentials
     DEBUG_PRINT("Connecting to WiFi: ");
     DEBUG_PRINTLN(WIFI_SSID);
     WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
     
     int attempts = 0;
     while (WiFi.status() != WL_CONNECTED && attempts < 30) {
         delay(1000);
         #if SERIAL_DEBUG
             if (attempts % 5 == 0) Serial.print(".");
         #endif
         attempts++;
     }
     
     if (WiFi.status() == WL_CONNECTED) {
         DEBUG_PRINTLN("\n✅ Connected to WiFi!");
         DEBUG_PRINT("IP Address: ");
         DEBUG_PRINTLN(WiFi.localIP());
         DEBUG_PRINT("Signal Strength (RSSI): ");
         DEBUG_PRINT(WiFi.RSSI());
         DEBUG_PRINTLN(" dBm");
         if (WiFi.RSSI() < -75) {
             DEBUG_PRINTLN("⚠️ WARNING: Weak WiFi signal! May cause disconnections.");
             DEBUG_PRINTLN("   Move closer to router or check signal strength.");
         }
     } else {
         DEBUG_PRINTLN("\n❌ WiFi connection failed!");
         DEBUG_PRINTLN("Please check:");
         DEBUG_PRINTLN("1. WIFI_SSID and WIFI_PASSWORD in code");
         DEBUG_PRINTLN("2. WiFi network is available");
         DEBUG_PRINTLN("3. WiFi password is correct");
         DEBUG_PRINTLN("Retrying in 10 seconds...");
         delay(10000);
         // Don't restart immediately - try to continue, WiFi might recover
     }
     
     // Get server URL from server (will be set via dashboard)
     // Try to get from server, if not available use default
     serverUrl = "";  // Will be retrieved from server
     DEBUG_PRINTLN("Server URL will be retrieved from server configuration");
     
     // Initialize pins
     pinMode(RELAY_PIN, OUTPUT);
     pinMode(BUZZER_PIN, OUTPUT);
     digitalWrite(RELAY_PIN, LOW);
     digitalWrite(BUZZER_PIN, LOW);  // Start with buzzer OFF
     
     DEBUG_PRINTLN("=================================");
     DEBUG_PRINTLN("Control Board initialized");
     DEBUG_PRINTLN("Relay: OFF");
     DEBUG_PRINTLN("Buzzer: OFF");
     DEBUG_PRINTLN("=================================");
     DEBUG_PRINTLN("⚠️ IMPORTANT: Configure Server URL in Dashboard!");
     DEBUG_PRINTLN("   Go to Dashboard → Control Board Configuration");
     DEBUG_PRINTLN("   Enter: http://192.168.1.222:8888");
     DEBUG_PRINTLN("=================================");
     
     // Visual feedback: Blink buzzer briefly to indicate board is ready
     // (only if buzzer is available - gives visual confirmation)
     digitalWrite(BUZZER_PIN, HIGH);
     delay(100);
     digitalWrite(BUZZER_PIN, LOW);
 }
 
 void loop() {
     unsigned long currentTime = millis();
     
     // Get server URL from server if not set (first time or after update)
     if (serverUrl.length() == 0 && WiFi.status() == WL_CONNECTED) {
         getServerUrlFromServer();
     }
     
     // Periodically refresh server URL (to pick up changes from dashboard)
     if (WiFi.status() == WL_CONNECTED && (currentTime - lastServerUrlRefresh >= serverUrlRefreshInterval)) {
         refreshServerUrl();
         lastServerUrlRefresh = currentTime;
     }
     
     // Upload sensor data to server if new data received via ESP-NOW
     if (newSensorData && WiFi.status() == WL_CONNECTED && serverUrl.length() > 0) {
         if (currentTime - lastSensorUpload >= sensorUploadInterval) {
             uploadSensorDataToServer();
             newSensorData = false;
             lastSensorUpload = currentTime;
         }
     }
     
     // Poll server for commands
     if (currentTime - lastPollTime >= pollInterval) {
         if (WiFi.status() == WL_CONNECTED && serverUrl.length() > 0) {
             bool success = pollServerCommands();
             if (success) {
                 consecutiveFailures = 0;  // Reset failure counter on success
             } else {
                 consecutiveFailures++;
                 lastFailedPollTime = currentTime;
                 
                 // If multiple consecutive failures, try to refresh server URL
                 if (consecutiveFailures >= maxConsecutiveFailures) {
                     DEBUG_PRINTLN("⚠️ Multiple poll failures detected. Refreshing server URL...");
                     refreshServerUrl();
                     consecutiveFailures = 0;  // Reset counter after refresh attempt
                 }
             }
         } else if (WiFi.status() != WL_CONNECTED) {
             DEBUG_PRINTLN("⚠️ WiFi disconnected, attempting reconnect...");
             WiFi.disconnect();
             delay(100);
             WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
             
             // Wait up to 10 seconds for reconnection
             int reconnectAttempts = 0;
             while (WiFi.status() != WL_CONNECTED && reconnectAttempts < 10) {
                 delay(1000);
                 reconnectAttempts++;
                 if (reconnectAttempts % 2 == 0) {
                     DEBUG_PRINT(".");
                 }
             }
             
             if (WiFi.status() == WL_CONNECTED) {
                 DEBUG_PRINTLN("\n✅ WiFi reconnected!");
                 DEBUG_PRINT("IP Address: ");
                 DEBUG_PRINTLN(WiFi.localIP());
             } else {
                 DEBUG_PRINTLN("\n❌ WiFi reconnection failed. Will retry on next poll.");
             }
         }
         lastPollTime = currentTime;
     }
     
     // Send status update to server
     if (currentTime - lastStatusUpdate >= statusUpdateInterval) {
         if (WiFi.status() == WL_CONNECTED && serverUrl.length() > 0) {
             sendStatusUpdate();
         }
         lastStatusUpdate = currentTime;
     }
     
     delay(10);
 }
 
 void refreshServerUrl() {
     // Try to get updated server URL from server
     // This allows picking up URL changes from dashboard
     
     // Try common server URLs first
     String possibleUrls[] = {
         "http://192.168.1.222:8888",
         "http://127.0.0.1:8888",
         "http://192.168.1.100:8888",
         "http://192.168.0.222:8888",
         "http://172.18.251.238:8888"
     };
     
     // Also try current URL if set
     if (serverUrl.length() > 0) {
         // Try current URL first
         HTTPClient http;
         String testUrl = serverUrl + "/api/control/commands";
         http.begin(testUrl);
         http.setTimeout(2000);
         
         int httpCode = http.GET();
         if (httpCode == HTTP_CODE_OK) {
             String payload = http.getString();
             StaticJsonDocument<256> doc;
             DeserializationError error = deserializeJson(doc, payload);
             
             if (!error && doc.containsKey("server_url")) {
                 String newUrl = doc["server_url"].as<String>();
                 if (newUrl != serverUrl && newUrl.length() > 0) {
                     serverUrl = newUrl;
                     DEBUG_PRINTLN("✅ Server URL refreshed: " + serverUrl);
                     http.end();
                     return;
                 }
             }
         }
         http.end();
     }
     
     // Try other common URLs
     for (int i = 0; i < 3; i++) {
         HTTPClient http;
         String testUrl = possibleUrls[i] + "/api/control/commands";
         http.begin(testUrl);
         http.setTimeout(2000);
         
         int httpCode = http.GET();
         if (httpCode == HTTP_CODE_OK) {
             String payload = http.getString();
             StaticJsonDocument<256> doc;
             DeserializationError error = deserializeJson(doc, payload);
             
             if (!error && doc.containsKey("server_url")) {
                 String newUrl = doc["server_url"].as<String>();
                 if (newUrl.length() > 0) {
                     serverUrl = newUrl;
                     DEBUG_PRINTLN("✅ Server URL retrieved: " + serverUrl);
                     http.end();
                     return;
                 }
             }
         }
         http.end();
     }
 }
 
 void getServerUrlFromServer() {
     // Initial server URL discovery
     refreshServerUrl();
     
    // If still not found, use default
    if (serverUrl.length() == 0) {
        DEBUG_PRINTLN("⚠️ Server URL not configured in dashboard!");
        DEBUG_PRINTLN("Please set Server URL in dashboard: Control Board Configuration");
        DEBUG_PRINTLN("Using default: http://192.168.1.222:8888");
        serverUrl = "http://192.168.1.222:8888";  // Default fallback
        DEBUG_PRINTLN("🔧 To change server URL, update line 348 in control board code");
        DEBUG_PRINTLN("   Or configure it in the web dashboard");
    }
 }
 
 bool pollServerCommands() {
     // First, try to get server URL from server if not set
     if (serverUrl.length() == 0) {
         getServerUrlFromServer();
         return false;
     }
     
     HTTPClient http;
     String url = serverUrl + "/api/control/commands";
     
     http.begin(url);
     http.setTimeout(3000);  // 3 second timeout
     int httpCode = http.GET();
     
     if (httpCode > 0) {
         if (httpCode == HTTP_CODE_OK) {
             String payload = http.getString();
             
             StaticJsonDocument<256> doc;
             DeserializationError error = deserializeJson(doc, payload);
             
             if (!error) {
                 // Update server URL if provided (from dashboard configuration)
                 if (doc.containsKey("server_url") && doc["server_url"].as<String>().length() > 0) {
                     String newServerUrl = doc["server_url"].as<String>();
                     if (newServerUrl != serverUrl && newServerUrl.length() > 0) {
                         serverUrl = newServerUrl;
                         DEBUG_PRINTLN("✅ Server URL updated from poll: " + serverUrl);
                     }
                 }
                 
                 // Update light control
                 bool newLightState = doc["light_on"] | false;
                 if (newLightState != lightOn) {
                     lightOn = newLightState;
                     digitalWrite(RELAY_PIN, lightOn ? HIGH : LOW);
                     DEBUG_PRINTLN("💡 Light: " + String(lightOn ? "ON" : "OFF"));
                 }
                 
                 // Update buzzer control
                 bool newBuzzerState = doc["buzzer_on"] | false;
                 if (newBuzzerState != buzzerOn) {
                     buzzerOn = newBuzzerState;
                     digitalWrite(BUZZER_PIN, buzzerOn ? HIGH : LOW);
                     DEBUG_PRINTLN("🔔 Buzzer: " + String(buzzerOn ? "ON" : "OFF"));
                 }
                 
                 // Update other settings (for future use)
                 manualMode = doc["manual_mode"] | false;
                 brightnessLevel = doc["brightness_level"] | 100;
                 homeMode = doc["home_mode"] | true;
                 
                 http.end();
                 return true;  // Success
             } else {
                 DEBUG_PRINTLN("⚠️ JSON parse error in poll response");
                 http.end();
                 return false;
             }
         } else {
             DEBUG_PRINTLN("⚠️ Server returned HTTP code: " + String(httpCode));
             http.end();
             return false;
         }
     } else {
         DEBUG_PRINTLN("❌ Error polling server: " + String(http.errorToString(httpCode).c_str()));
         http.end();
         return false;  // Failure
     }
 }
 
 // Encrypt sensor data using AES-128-CBC with Base64 encoding
 String encryptSensorData() {
     // Create JSON payload from sensor data
     StaticJsonDocument<512> doc;
     doc["pir_motion"] = latestSensorData.pir_motion;
     doc["flame_detected"] = latestSensorData.flame_detected;
     doc["door_open"] = latestSensorData.door_open;
     doc["air_quality"] = latestSensorData.air_quality;
     doc["sound_level"] = latestSensorData.sound_level;
     doc["light_level"] = latestSensorData.light_level;
     doc["temperature"] = latestSensorData.temperature;
     doc["humidity"] = latestSensorData.humidity;
     doc["timestamp"] = latestSensorData.timestamp;
     
     String jsonPayload;
     serializeJson(doc, jsonPayload);
     
     // Generate random IV (16 bytes)
     uint8_t iv[16];
     uint8_t ivCopy[16];  // Save original IV (mbedtls modifies IV in place)
     esp_fill_random(iv, 16);
     memcpy(ivCopy, iv, 16);  // Save original IV
     
     // Prepare plaintext (JSON string)
     const char* plaintext = jsonPayload.c_str();
     size_t plaintextLen = strlen(plaintext);
     size_t jsonPayloadLen = jsonPayload.length();
     
     // Verify lengths match
     if (plaintextLen != jsonPayloadLen) {
         DEBUG_PRINTLN("⚠️ WARNING: strlen()=" + String(plaintextLen) + " != jsonPayload.length()=" + String(jsonPayloadLen));
         plaintextLen = jsonPayloadLen;  // Use String length instead
     }
     
     DEBUG_PRINTLN("🔐 Plaintext length: " + String(plaintextLen) + " bytes");
     int previewLen = (plaintextLen > 50) ? 50 : plaintextLen;
     DEBUG_PRINTLN("🔐 JSON preview: " + jsonPayload.substring(0, previewLen));
     
     // Calculate padding (PKCS7)
     size_t paddingLen = 16 - (plaintextLen % 16);
     if (paddingLen == 0) paddingLen = 16;  // If already multiple of 16, add full block
     size_t paddedLen = plaintextLen + paddingLen;
     
     DEBUG_PRINTLN("🔐 Padding: " + String(paddingLen) + ", Padded length: " + String(paddedLen));
     
     // Verify paddedLen is multiple of 16
     if (paddedLen % 16 != 0) {
         DEBUG_PRINTLN("❌ ERROR: Padded length not multiple of 16!");
         return "";
     }
     
     // Allocate buffer for padded plaintext
     uint8_t* paddedPlaintext = (uint8_t*)malloc(paddedLen);
     if (!paddedPlaintext) {
         DEBUG_PRINTLN("❌ Memory allocation failed for encryption");
         return "";
     }
     
     // Copy plaintext and add padding
     memcpy(paddedPlaintext, plaintext, plaintextLen);
     for (size_t i = plaintextLen; i < paddedLen; i++) {
         paddedPlaintext[i] = (uint8_t)paddingLen;
     }
     
     // Initialize AES context
     mbedtls_aes_context aes;
     mbedtls_aes_init(&aes);
     mbedtls_aes_setkey_enc(&aes, encryptionKey, 128);
     
     // Encrypt (IV is used, ciphertext will be same size as padded plaintext)
     // Note: mbedtls_aes_crypt_cbc modifies the IV parameter, so we use ivCopy
     uint8_t* ciphertext = (uint8_t*)malloc(paddedLen);
     if (!ciphertext) {
         free(paddedPlaintext);
         mbedtls_aes_free(&aes);
         DEBUG_PRINTLN("❌ Memory allocation failed for ciphertext");
         return "";
     }
     
     // Use ivCopy since mbedtls modifies IV in place
     memcpy(iv, ivCopy, 16);  // Restore original IV
     
     // Verify paddedLen is multiple of 16 before encryption
     if (paddedLen % 16 != 0) {
         DEBUG_PRINTLN("❌ FATAL: paddedLen " + String(paddedLen) + " is NOT multiple of 16 before encryption!");
         free(paddedPlaintext);
         free(ciphertext);
         mbedtls_aes_free(&aes);
         return "";
     }
     
     int encrypt_ret = mbedtls_aes_crypt_cbc(&aes, MBEDTLS_AES_ENCRYPT, paddedLen, iv, paddedPlaintext, ciphertext);
     if (encrypt_ret != 0) {
         DEBUG_PRINTLN("❌ AES encryption failed: " + String(encrypt_ret));
         free(paddedPlaintext);
         free(ciphertext);
         mbedtls_aes_free(&aes);
         return "";
     }
     
     DEBUG_PRINTLN("🔐 Encryption successful, ciphertext length: " + String(paddedLen));
     
     // Combine IV (16 bytes) + ciphertext
     size_t combinedLen = 16 + paddedLen;
     uint8_t* combined = (uint8_t*)malloc(combinedLen);
     if (!combined) {
         free(paddedPlaintext);
         free(ciphertext);
         mbedtls_aes_free(&aes);
         DEBUG_PRINTLN("❌ Memory allocation failed for combined data");
         return "";
     }
     
     // Verify ciphertext is actually a multiple of 16 bytes
     if (paddedLen % 16 != 0) {
         DEBUG_PRINTLN("❌ FATAL ERROR: Ciphertext length " + String(paddedLen) + " is NOT multiple of 16 after encryption!");
         free(paddedPlaintext);
         free(ciphertext);
         free(combined);
         mbedtls_aes_free(&aes);
         return "";
     }
     
     // Use original IV (ivCopy), not the modified one
     memcpy(combined, ivCopy, 16);
     memcpy(combined + 16, ciphertext, paddedLen);
     
     // Verify combined length
     if (combinedLen != (16 + paddedLen)) {
         DEBUG_PRINTLN("❌ FATAL ERROR: Combined length mismatch! Expected " + String(16 + paddedLen) + ", calculated " + String(combinedLen));
         free(paddedPlaintext);
         free(ciphertext);
         free(combined);
         mbedtls_aes_free(&aes);
         return "";
     }
     
     DEBUG_PRINTLN("🔐 Combined length: " + String(combinedLen) + " (IV: 16 + Ciphertext: " + String(paddedLen) + ")");
     
     // Base64 encode
     // Calculate required buffer size: Base64 encoding increases size by ~33%
     // Formula: ((input_len + 2) / 3) * 4, plus 1 for null terminator
     size_t base64Len = ((combinedLen + 2) / 3) * 4 + 1;
     
     // Allocate buffer with some extra space for safety
     unsigned char* base64Output = (unsigned char*)malloc(base64Len + 16);  // Extra padding
     if (!base64Output) {
         free(paddedPlaintext);
         free(ciphertext);
         free(combined);
         mbedtls_aes_free(&aes);
         DEBUG_PRINTLN("❌ Memory allocation failed for base64");
         return "";
     }
     
     size_t outputLen = 0;
     // Use base64Len (without the +16 extra) as the buffer size
     int ret = mbedtls_base64_encode(base64Output, base64Len, &outputLen, combined, combinedLen);
     
     String encryptedData = "";
     if (ret == 0 && outputLen > 0) {
         // Ensure null termination
         base64Output[outputLen] = '\0';
         encryptedData = String((char*)base64Output);
         // Remove any newlines or whitespace that might have been added
         encryptedData.trim();
         
         // Verify: Base64 length should be multiple of 4 (after padding)
         size_t expectedBase64Len = ((combinedLen + 2) / 3) * 4;
         
         // Critical verification
         DEBUG_PRINTLN("🔐 Encryption complete:");
         DEBUG_PRINTLN("   Plaintext: " + String(plaintextLen) + " bytes");
         DEBUG_PRINTLN("   Padded: " + String(paddedLen) + " bytes (must be multiple of 16)");
         DEBUG_PRINTLN("   Combined: " + String(combinedLen) + " bytes (16 IV + " + String(paddedLen) + " ciphertext)");
         DEBUG_PRINTLN("   Base64: " + String(outputLen) + " chars (expected ~" + String(expectedBase64Len) + ")");
         DEBUG_PRINTLN("   Final string: " + String(encryptedData.length()) + " chars");
         
         // Verify all lengths
         if (paddedLen % 16 != 0) {
             DEBUG_PRINTLN("❌ CRITICAL: Ciphertext length " + String(paddedLen) + " is NOT multiple of 16!");
         }
         if (combinedLen != (16 + paddedLen)) {
             DEBUG_PRINTLN("❌ CRITICAL: Combined length mismatch! Expected " + String(16 + paddedLen) + ", got " + String(combinedLen));
         }
         if (encryptedData.length() != outputLen) {
             DEBUG_PRINTLN("⚠️ WARNING: Base64 string length mismatch after trim!");
         }
     } else {
         DEBUG_PRINTLN("❌ Base64 encoding failed: ret=" + String(ret) + ", outputLen=" + String(outputLen) + ", base64Len=" + String(base64Len));
     }
     
     // Cleanup
     free(paddedPlaintext);
     free(ciphertext);
     free(combined);
     free(base64Output);
     mbedtls_aes_free(&aes);
     
     return encryptedData;
 }

 // URL encode a string (for Base64 strings - handles +, /, = correctly)
 String urlEncode(String str) {
     String encoded = "";
     char c;
     for (int i = 0; i < str.length(); i++) {
         c = str.charAt(i);
         if (isalnum(c) || c == '-' || c == '_' || c == '.') {
             encoded += c;
         } else {
             // URL encode special characters (including +, /, = from Base64)
             encoded += '%';
             byte b = (byte)c;
             char hex1 = (b >> 4) & 0x0F;
             char hex2 = b & 0x0F;
             encoded += (hex1 < 10) ? ('0' + hex1) : ('A' + hex1 - 10);
             encoded += (hex2 < 10) ? ('0' + hex2) : ('A' + hex2 - 10);
         }
     }
     return encoded;
 }

 void uploadSensorDataToServer() {
     // Forward sensor data received via ESP-NOW to Python server
     HTTPClient http;
     String url = serverUrl + "/api/sensor-data";
     
     http.begin(url);
     // Content-Type will be set based on whether we're sending encrypted (JSON) or unencrypted (form-urlencoded)
     
     String postData;
     
     // If encryption is enabled, encrypt the data
     if (latestSensorData.is_encrypted) {
         String encryptedData = encryptSensorData();
         if (encryptedData.length() > 0) {
             // Send as JSON to avoid URL encoding issues with long Base64 strings
             http.addHeader("Content-Type", "application/json");
             StaticJsonDocument<1024> doc;
             doc["encrypted_data"] = encryptedData;  // Base64 string, no URL encoding needed in JSON
             doc["is_encrypted"] = true;
             serializeJson(doc, postData);
             DEBUG_PRINTLN("🔐 Sending encrypted sensor data as JSON (Base64 len: " + String(encryptedData.length()) + ")");
         } else {
             // Encryption failed, fall back to unencrypted
             DEBUG_PRINTLN("⚠️ Encryption failed, sending unencrypted data");
             http.addHeader("Content-Type", "application/x-www-form-urlencoded");
             postData = "pir_motion=" + String(latestSensorData.pir_motion ? "true" : "false") +
                       "&flame_detected=" + String(latestSensorData.flame_detected ? "true" : "false") +
                       "&door_open=" + String(latestSensorData.door_open ? "true" : "false") +
                       "&air_quality=" + String(latestSensorData.air_quality) +
                       "&sound_level=" + String(latestSensorData.sound_level) +
                       "&light_level=" + String(latestSensorData.light_level) +
                       "&temperature=" + String(latestSensorData.temperature, 1) +
                       "&humidity=" + String(latestSensorData.humidity, 1) +
                       "&timestamp=" + String(latestSensorData.timestamp) +
                       "&is_encrypted=false";
         }
     } else {
         // Send unencrypted data (original behavior)
         http.addHeader("Content-Type", "application/x-www-form-urlencoded");
         postData = "pir_motion=" + String(latestSensorData.pir_motion ? "true" : "false") +
                   "&flame_detected=" + String(latestSensorData.flame_detected ? "true" : "false") +
                   "&door_open=" + String(latestSensorData.door_open ? "true" : "false") +
                   "&air_quality=" + String(latestSensorData.air_quality) +
                   "&sound_level=" + String(latestSensorData.sound_level) +
                   "&light_level=" + String(latestSensorData.light_level) +
                   "&temperature=" + String(latestSensorData.temperature, 1) +
                   "&humidity=" + String(latestSensorData.humidity, 1) +
                   "&timestamp=" + String(latestSensorData.timestamp) +
                   "&is_encrypted=false";
     }
     
     // Send POST request
     int httpCode = http.POST(postData);
     if (httpCode > 0) {
         if (httpCode == HTTP_CODE_OK) {
             DEBUG_PRINTLN("✅ Sensor data uploaded to server");
         } else {
             DEBUG_PRINTLN("⚠️ Server response: " + String(httpCode));
         }
     } else {
         DEBUG_PRINTLN("❌ HTTP POST failed: " + String(http.errorToString(httpCode).c_str()));
     }
     http.end();
 }
 
 void sendStatusUpdate() {
     HTTPClient http;
     String url = serverUrl + "/api/control/status";
     
     http.begin(url);
     http.addHeader("Content-Type", "application/json");
     
     StaticJsonDocument<128> doc;
     doc["light_on"] = lightOn;
     doc["buzzer_on"] = buzzerOn;
     
     String payload;
     serializeJson(doc, payload);
     
     int httpCode = http.POST(payload);
     if (httpCode > 0) {
         // Status updated successfully
     } else {
         DEBUG_PRINTLN("Error updating status: " + String(http.errorToString(httpCode).c_str()));
     }
     
     http.end();
 }
 
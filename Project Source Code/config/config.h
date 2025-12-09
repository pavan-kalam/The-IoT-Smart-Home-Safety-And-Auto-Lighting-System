/*
 * Configuration File
 * Update these values before uploading to ESP32 boards
 */

#ifndef CONFIG_H
#define CONFIG_H

// WiFi Configuration
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

// ESP32 Board 2 (Control Board) IP Address
// Update this after Board 2 connects to WiFi
#define CONTROL_BOARD_IP "192.168.1.100"

// Authentication (Change these!)
#define DEFAULT_USERNAME "admin"
#define DEFAULT_PASSWORD "admin123"

// Email Configuration (for notifications)
#define SMTP_SERVER "smtp.gmail.com"
#define SMTP_PORT 587
#define EMAIL_USER "your-email@gmail.com"
#define EMAIL_PASSWORD "your-app-password"
#define NOTIFICATION_EMAIL "recipient@example.com"

// Sensor Thresholds
#define LIGHT_THRESHOLD 1000        // LDR threshold for low light
#define AIR_QUALITY_THRESHOLD 2000  // MQ135 threshold for gas leak
#define SOUND_THRESHOLD 2000        // Sound threshold for unusual activity

// Timing Intervals (milliseconds)
#define SENSOR_READ_INTERVAL 1000   // Read sensors every 1 second
#define DATA_SEND_INTERVAL 2000     // Send data every 2 seconds
#define DASHBOARD_UPDATE_INTERVAL 2000  // Update dashboard every 2 seconds

#endif


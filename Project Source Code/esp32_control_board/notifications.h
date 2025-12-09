/*
 * Notification System
 * Handles email and push notifications for alerts
 */

#ifndef NOTIFICATIONS_H
#define NOTIFICATIONS_H

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// Email notification via SMTP (using external service or ESP32 Mail Client library)
class NotificationSystem {
private:
  String smtpServer;
  int smtpPort;
  String emailUser;
  String emailPassword;
  String recipientEmail;
  
public:
  NotificationSystem() {
    // Initialize with default values
    smtpServer = "smtp.gmail.com";
    smtpPort = 587;
    emailUser = "";
    emailPassword = "";
    recipientEmail = "";
  }
  
  void configure(String server, int port, String user, String pass, String recipient) {
    smtpServer = server;
    smtpPort = port;
    emailUser = user;
    emailPassword = pass;
    recipientEmail = recipient;
  }
  
  // Send email notification
  bool sendEmail(String subject, String message) {
    // Option 1: Use ESP32 Mail Client library
    // Option 2: Use external webhook service (IFTTT, Zapier, etc.)
    // Option 3: Use HTTP POST to email service API
    
    // For now, using a webhook approach (you can use IFTTT, Zapier, or custom server)
    HTTPClient http;
    String webhookURL = "https://maker.ifttt.com/trigger/smart_home_alert/with/key/YOUR_IFTTT_KEY";
    
    http.begin(webhookURL);
    http.addHeader("Content-Type", "application/json");
    
    StaticJsonDocument<256> doc;
    doc["value1"] = subject;
    doc["value2"] = message;
    doc["value3"] = "Smart Home System";
    
    String payload;
    serializeJson(doc, payload);
    
    int httpResponseCode = http.POST(payload);
    http.end();
    
    return httpResponseCode > 0;
  }
  
  // Send push notification (using Pushover, Pushbullet, or similar)
  bool sendPushNotification(String title, String message) {
    // Using Pushover as example
    HTTPClient http;
    String pushoverURL = "https://api.pushover.net/1/messages.json";
    
    http.begin(pushoverURL);
    http.addHeader("Content-Type", "application/x-www-form-urlencoded");
    
    String postData = "token=YOUR_PUSHOVER_TOKEN&user=YOUR_PUSHOVER_USER&title=" + 
                      title + "&message=" + message;
    
    int httpResponseCode = http.POST(postData);
    http.end();
    
    return httpResponseCode > 0;
  }
  
  // Send notification for fire alert
  void notifyFire() {
    sendEmail("🔥 FIRE ALERT - Smart Home", "Fire detected in your home! Please check immediately.");
    sendPushNotification("🔥 Fire Alert", "Fire detected in your home!");
  }
  
  // Send notification for gas leak
  void notifyGasLeak(int airQuality) {
    String message = "Gas leak detected! Air quality reading: " + String(airQuality);
    sendEmail("⚠️ Gas Leak Alert - Smart Home", message);
    sendPushNotification("⚠️ Gas Leak", message);
  }
  
  // Send notification for unauthorized access
  void notifyUnauthorizedAccess() {
    sendEmail("🚨 Security Alert - Smart Home", "Unauthorized access detected! Door opened while system is in away mode.");
    sendPushNotification("🚨 Security Alert", "Unauthorized access detected!");
  }
  
  // Send notification for motion while away
  void notifyMotionWhileAway() {
    sendEmail("👁️ Motion Alert - Smart Home", "Motion detected while system is in away mode.");
    sendPushNotification("👁️ Motion Alert", "Motion detected while away");
  }
};

#endif


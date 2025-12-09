// API Base URL
const API_BASE = '/api';

// Format timestamp to local time
function formatTimestamp(timestamp) {
    if (!timestamp) return 'N/A';
    try {
        // Debug: log the timestamp being parsed
        console.log('Parsing timestamp:', timestamp);
        const date = new Date(timestamp);
        if (isNaN(date.getTime())) {
            console.error('Invalid date:', timestamp);
            return timestamp; // Return as-is if not a valid date
        }
        // Debug: log the parsed date
        console.log('Parsed date UTC:', date.toISOString(), 'Local:', date.toLocaleString());
        // Format to local time with timezone
        const formatted = date.toLocaleString('en-US', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true,
            timeZoneName: 'short'
        });
        console.log('Formatted result:', formatted);
        return formatted;
    } catch (e) {
        console.error('Error formatting timestamp:', e, timestamp);
        return timestamp;
    }
}

// Global state
let currentEventPage = 1;
let eventPagination = null;

// Initialize dashboard
document.addEventListener('DOMContentLoaded', function() {
    updateDashboard();
    updateSensorBoardStatus();
    loadSensorEvents();
    loadEvents();
    loadNotifications();
    loadControlBoardUrl();
    
    // Update every 2 seconds
    setInterval(() => {
        updateDashboard();
        loadSensorEvents();
        loadNotifications();
    }, 2000);
    
    // Update events every 5 seconds
    setInterval(() => {
        loadEvents();
    }, 5000);
});

// Update Dashboard
async function updateDashboard() {
    try {
        const response = await fetch(`${API_BASE}/system-state`);
        if (!response.ok) {
            if (response.status === 401) {
                window.location.href = '/login';
                return;
            }
            throw new Error('Failed to fetch system state');
        }
        const data = await response.json();
        
        // Update sensor values
        document.getElementById('temperature').textContent = data.sensors.temperature.toFixed(1) + '°C';
        document.getElementById('humidity').textContent = data.sensors.humidity.toFixed(1) + '%';
        
        // Motion
        document.getElementById('motion-status').textContent = data.sensors.pir_motion ? 'Motion Detected' : 'No Motion';
        let motionBadge = document.getElementById('motion-badge');
        motionBadge.textContent = data.sensors.pir_motion ? 'Active' : 'Inactive';
        motionBadge.className = 'status-badge ' + (data.sensors.pir_motion ? 'active' : 'inactive');
        
        // Door
        document.getElementById('door-status').textContent = data.sensors.door_open ? 'Open' : 'Closed';
        let doorBadge = document.getElementById('door-badge');
        doorBadge.textContent = data.sensors.door_open ? 'Open' : 'Closed';
        doorBadge.className = 'status-badge ' + (data.sensors.door_open ? 'warning' : 'active');
        
        // Flame
        document.getElementById('flame-status').textContent = data.sensors.flame_detected ? 'FIRE!' : 'Safe';
        let flameBadge = document.getElementById('flame-badge');
        flameBadge.textContent = data.sensors.flame_detected ? 'FIRE!' : 'Safe';
        flameBadge.className = 'status-badge ' + (data.sensors.flame_detected ? 'danger' : 'active');
        
        // Air Quality - Enhanced display
        const airQualityRaw = data.sensors.air_quality_raw !== undefined ? data.sensors.air_quality_raw : (data.sensors.air_quality || 0);
        const airQualityPercent = data.sensors.air_quality_percent !== undefined ? data.sensors.air_quality_percent : 0;
        const airQualityStatus = data.sensors.air_quality_status || 'Unknown';
        
        // Display format: Raw Value (Percentage% - Status)
        document.getElementById('air-quality').textContent = `${airQualityRaw} (${airQualityPercent}% - ${airQualityStatus})`;
        let airBadge = document.getElementById('air-badge');
        airBadge.textContent = airQualityStatus;
        
        // Set badge color based on status
        let badgeClass = 'sensor-badge ';
        if (airQualityStatus === 'Excellent' || airQualityStatus === 'Good') {
            badgeClass += 'active';
        } else if (airQualityStatus === 'Moderate') {
            badgeClass += 'warning';
        } else {
            badgeClass += 'danger';
        }
        airBadge.className = badgeClass;
        
        // Light Level
        // Note: LDR sensor - Higher value (4095) = Dark, Lower value (0) = Bright
        document.getElementById('light-level').textContent = data.sensors.light_level;
        let lightBadge = document.getElementById('light-badge');
        lightBadge.textContent = data.sensors.light_level > 2000 ? 'Dark' : 'Bright';
        lightBadge.className = 'sensor-badge ' + (data.sensors.light_level > 2000 ? 'inactive' : 'active');
        
        // System state
        document.getElementById('light-status').textContent = 'Light: ' + (data.system.light_on ? 'ON' : 'OFF');
        document.getElementById('light-btn').textContent = data.system.light_on ? 'Turn Off' : 'Turn On';
        document.getElementById('light-btn').className = 'btn-control ' + (data.system.light_on ? 'active' : '');
        
        document.getElementById('buzzer-status').textContent = 'Buzzer: ' + (data.system.buzzer_on ? 'ON' : 'OFF');
        document.getElementById('buzzer-btn').textContent = data.system.buzzer_on ? 'Turn Off Alerts' : 'Turn On Alerts';
        document.getElementById('buzzer-btn').className = 'btn-control btn-danger ' + (data.system.buzzer_on ? 'active' : '');
        
        document.getElementById('mode-status').textContent = data.system.manual_mode ? 'Manual Mode Active' : 'Auto Mode Active';
        document.getElementById('mode-btn').textContent = data.system.manual_mode ? 'Manual' : 'Auto';
        document.getElementById('mode-btn').className = 'btn-control ' + (data.system.manual_mode ? '' : 'active');
        
        document.getElementById('brightness-value').textContent = data.system.brightness_level + '%';
        document.getElementById('brightness-slider').value = data.system.brightness_level;
        
        document.getElementById('home-mode-status').textContent = data.system.home_mode ? 'Someone Home' : 'Away';
        document.getElementById('home-mode-btn').textContent = data.system.home_mode ? 'Home' : 'Away';
        document.getElementById('home-mode-btn').className = 'btn-control ' + (data.system.home_mode ? 'active' : '');
    } catch (err) {
        console.error('Error updating dashboard:', err);
    }
}

// Update Sensor Board Status
async function updateSensorBoardStatus() {
    try {
        const response = await fetch(`${API_BASE}/sensor-board/info`);
        if (!response.ok) return;
        const data = await response.json();
        
        document.getElementById('monitoring-status').textContent = 'Monitoring: ' + (data.monitoring ? 'Active' : 'Stopped');
        document.getElementById('monitoring-btn').textContent = data.monitoring ? 'Stop' : 'Start';
        document.getElementById('monitoring-btn').className = 'btn-control ' + (data.monitoring ? 'active' : '');
        
        document.getElementById('encryption-status').textContent = 'Encryption: ' + (data.encryption_enabled ? 'Enabled' : 'Disabled');
        document.getElementById('encryption-btn').textContent = data.encryption_enabled ? 'Disable' : 'Enable';
        
        document.getElementById('upload-interval-slider').value = data.upload_interval;
        document.getElementById('upload-interval-value').textContent = data.upload_interval + ' ms';
    } catch (err) {
        console.error('Error updating sensor board status:', err);
    }
}

// Load Events with Pagination
async function loadEvents(page = currentEventPage) {
    try {
        const response = await fetch(`${API_BASE}/events?page=${page}&per_page=10`);
        if (!response.ok) return;
        const data = await response.json();
        
        eventPagination = data.pagination;
        currentEventPage = page;
        
        let eventList = document.getElementById('event-list');
        eventList.innerHTML = '';
        
        if (data.events.length === 0) {
            eventList.innerHTML = '<div class="loading">No events found</div>';
            return;
        }
        
        data.events.forEach(event => {
            let div = document.createElement('div');
            div.className = 'event-item' + (event.type === 'ALERT' ? ' event-alert' : '');
            
            let timeSpan = document.createElement('span');
            timeSpan.className = 'event-time';
            timeSpan.textContent = event.timestamp;
            
            let typeSpan = document.createElement('span');
            typeSpan.className = 'event-type';
            typeSpan.textContent = '[' + event.type + ']';
            
            let messageSpan = document.createElement('span');
            messageSpan.textContent = event.message;
            
            div.appendChild(timeSpan);
            div.appendChild(typeSpan);
            div.appendChild(messageSpan);
            eventList.appendChild(div);
        });
        
        // Update pagination controls
        document.getElementById('page-info').textContent = `Page ${eventPagination.page} of ${eventPagination.total_pages}`;
        document.getElementById('prev-btn').disabled = !eventPagination.has_prev;
        document.getElementById('next-btn').disabled = !eventPagination.has_next;
    } catch (err) {
        console.error('Error loading events:', err);
    }
}

function loadPreviousEvents() {
    if (eventPagination && eventPagination.has_prev) {
        loadEvents(currentEventPage - 1);
    }
}

function loadNextEvents() {
    if (eventPagination && eventPagination.has_next) {
        loadEvents(currentEventPage + 1);
    }
}

// Load Sensor Events
let lastSensorEventsHash = '';
async function loadSensorEvents() {
    try {
        // Add cache-busting parameter to ensure fresh data - use current time
        const cacheBuster = Date.now();
        const response = await fetch(`${API_BASE}/sensor-events?t=${cacheBuster}&_=${Math.random()}`, {
            method: 'GET',
            cache: 'no-store',
            credentials: 'include', // Include session cookies
            headers: {
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
                'X-Requested-With': 'XMLHttpRequest' // Prevent caching
            }
        });
        
        if (!response.ok) {
            console.error('Failed to load sensor events:', response.status, response.statusText);
            let tbody = document.getElementById('sensor-events-body');
            if (tbody) {
                tbody.innerHTML = `<tr><td colspan="4" class="loading" style="color: red;">Error: ${response.status} ${response.statusText}</td></tr>`;
            }
            return;
        }
        
        const data = await response.json();
        
        let tbody = document.getElementById('sensor-events-body');
        if (!tbody) {
            console.error('sensor-events-body element not found');
            return;
        }
        
        if (!data.sensor_events || data.sensor_events.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="loading">No sensor events yet</td></tr>';
            return;
        }
        
        // Sort by sensor name for consistent display
        const sortedEvents = data.sensor_events.sort((a, b) => {
            return a.sensor_name.localeCompare(b.sensor_name);
        });
        
        // Always rebuild the table completely to force visual update
        // Clear existing content
        tbody.innerHTML = '';
        
        // Create new rows with toggle switches
        sortedEvents.forEach(event => {
            let tr = document.createElement('tr');
            const sensorId = event.sensor_name.replace(/[^a-zA-Z0-9]/g, '_').toLowerCase();
            const lightEnabled = event.light_enabled !== undefined ? event.light_enabled : true;
            const buzzerEnabled = event.buzzer_enabled !== undefined ? event.buzzer_enabled : true;
            
            tr.innerHTML = `
                <td>${escapeHtml(event.sensor_name)}</td>
                <td>${escapeHtml(event.sensor_information)}</td>
                <td>${escapeHtml(event.action_taken)}</td>
                <td>
                    <label class="toggle-switch">
                        <input type="checkbox" 
                               class="light-toggle" 
                               data-sensor="${escapeHtml(event.sensor_name)}"
                               ${lightEnabled ? 'checked' : ''}
                               onchange="toggleSensorControl('${escapeHtml(event.sensor_name)}', 'light', this.checked, this)">
                        <span class="toggle-slider"></span>
                        <span class="toggle-label">${lightEnabled ? 'ON' : 'OFF'}</span>
                    </label>
                </td>
                <td>
                    <label class="toggle-switch">
                        <input type="checkbox" 
                               class="buzzer-toggle" 
                               data-sensor="${escapeHtml(event.sensor_name)}"
                               ${buzzerEnabled ? 'checked' : ''}
                               onchange="toggleSensorControl('${escapeHtml(event.sensor_name)}', 'buzzer', this.checked, this)">
                        <span class="toggle-slider"></span>
                        <span class="toggle-label">${buzzerEnabled ? 'ON' : 'OFF'}</span>
                    </label>
                </td>
            `;
            tbody.appendChild(tr);
        });
        
        // Update status indicator with visual feedback
        const statusEl = document.getElementById('sensor-events-status');
        if (statusEl) {
            const updateTime = new Date().toLocaleTimeString();
            statusEl.textContent = `(Last updated: ${updateTime})`;
            statusEl.style.color = '#4CAF50';
            statusEl.style.fontWeight = 'bold';
            // Reset color after 1 second
            setTimeout(() => {
                if (statusEl) {
                    statusEl.style.color = '#666';
                    statusEl.style.fontWeight = 'normal';
                }
            }, 1000);
        }
        
        // Debug: log when sensor events are updated (only log every 5 seconds to avoid spam)
        const now = Date.now();
        if (!window.lastSensorEventLog || (now - window.lastSensorEventLog) > 5000) {
            console.log(`✅ Sensor events refreshed: ${sortedEvents.length} events at ${new Date().toLocaleTimeString()}`);
            if (sortedEvents.length > 0) {
                const latestEvent = sortedEvents[0]; // Already sorted by newest first
                console.log(`   Latest: ${latestEvent.sensor_name} at ${formatTimestamp(latestEvent.timestamp)}`);
            }
            window.lastSensorEventLog = now;
        }
    } catch (err) {
        console.error('❌ Error loading sensor events:', err);
        // Show error in table if element exists
        let tbody = document.getElementById('sensor-events-body');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="4" class="loading" style="color: red;">Error loading sensor events. Check console.</td></tr>';
        }
    }
}

// Helper function to escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Load Notifications
async function loadNotifications() {
    try {
        const response = await fetch(`${API_BASE}/notifications?limit=10`);
        if (!response.ok) return;
        const data = await response.json();
        
        let notificationList = document.getElementById('notification-list');
        let badge = document.getElementById('notification-badge');
        
        if (!data.notifications || data.notifications.length === 0) {
            notificationList.innerHTML = '<div class="notification-item">No notifications</div>';
            badge.textContent = '0';
            badge.style.display = 'none';
            return;
        }
        
        let unreadCount = data.notifications.filter(n => !n.read).length;
        badge.textContent = unreadCount;
        badge.style.display = unreadCount > 0 ? 'flex' : 'none';
        
        notificationList.innerHTML = '';
        data.notifications.forEach(notif => {
            let div = document.createElement('div');
            div.className = 'notification-item' + (notif.read ? '' : ' unread');
            div.onclick = () => markNotificationRead(notif.id);
            
            div.innerHTML = `
                <div class="notif-title">${notif.title}</div>
                <div class="notif-message">${notif.message}</div>
                <div class="notif-time">${formatTimestamp(notif.timestamp)}</div>
            `;
            notificationList.appendChild(div);
        });
    } catch (err) {
        console.error('Error loading notifications:', err);
    }
}

function toggleNotifications() {
    let dropdown = document.getElementById('notification-dropdown');
    dropdown.classList.toggle('show');
}

function markNotificationRead(notifId) {
    fetch(`${API_BASE}/notifications/${notifId}/read`, {
        method: 'PUT'
    }).then(() => {
        loadNotifications();
    });
}

async function clearNotifications() {
    if (!confirm('Are you sure you want to clear all notifications?')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/notifications/clear`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadNotifications();
            alert('All notifications cleared');
        } else {
            const error = await response.json();
            alert('Failed to clear notifications: ' + (error.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('Error clearing notifications:', err);
        alert('Error clearing notifications. Check console for details.');
    }
}

async function clearEvents() {
    if (!confirm('Are you sure you want to clear all event logs?')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/events/clear`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadEvents(1); // Reload first page
            alert('All events cleared');
        } else {
            const error = await response.json();
            alert('Failed to clear events: ' + (error.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('Error clearing events:', err);
        alert('Error clearing events. Check console for details.');
    }
}

// Show History Modals
async function showMotionHistory() {
    try {
        const response = await fetch(`${API_BASE}/history/motion?limit=10`);
        const data = await response.json();
        
        let content = document.getElementById('motion-history-content');
        if (!data.history || data.history.length === 0) {
            content.innerHTML = '<div class="loading">No motion events found</div>';
        } else {
            content.innerHTML = '';
            data.history.forEach(item => {
                let div = document.createElement('div');
                div.className = 'history-item';
                div.innerHTML = `
                    <div class="history-time">${formatTimestamp(item.timestamp)}</div>
                    <div class="history-message">${item.message}</div>
                `;
                content.appendChild(div);
            });
        }
        document.getElementById('motion-modal').classList.add('show');
    } catch (err) {
        console.error('Error loading motion history:', err);
    }
}

async function showDoorHistory() {
    try {
        const response = await fetch(`${API_BASE}/history/door?limit=10`);
        const data = await response.json();
        
        let content = document.getElementById('door-history-content');
        if (!data.history || data.history.length === 0) {
            content.innerHTML = '<div class="loading">No door events found</div>';
        } else {
            content.innerHTML = '';
            data.history.forEach(item => {
                let div = document.createElement('div');
                div.className = 'history-item';
                div.innerHTML = `
                    <div class="history-time">${formatTimestamp(item.timestamp)}</div>
                    <div class="history-message">${item.message}</div>
                `;
                content.appendChild(div);
            });
        }
        document.getElementById('door-modal').classList.add('show');
    } catch (err) {
        console.error('Error loading door history:', err);
    }
}

async function showFireHistory() {
    try {
        const response = await fetch(`${API_BASE}/history/fire?limit=10`);
        const data = await response.json();
        
        let content = document.getElementById('fire-history-content');
        if (!data.history || data.history.length === 0) {
            content.innerHTML = '<div class="loading">No fire events found</div>';
        } else {
            content.innerHTML = '';
            data.history.forEach(item => {
                let div = document.createElement('div');
                div.className = 'history-item';
                div.innerHTML = `
                    <div class="history-time">${formatTimestamp(item.timestamp)}</div>
                    <div class="history-message">${item.message}</div>
                `;
                content.appendChild(div);
            });
        }
        document.getElementById('fire-modal').classList.add('show');
    } catch (err) {
        console.error('Error loading fire history:', err);
    }
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('show');
}

// Close modal when clicking outside
window.onclick = function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.classList.remove('show');
    }
}

// Toggle Collapsible Sections
function toggleSection(element) {
    let content = element.nextElementSibling;
    content.classList.toggle('hidden');
    element.textContent = element.textContent.replace('▼', '').replace('▲', '');
    element.textContent += content.classList.contains('hidden') ? ' ▼' : ' ▲';
}

// Control Functions
async function toggleLight() {
    try {
        const statusText = document.getElementById('light-status').textContent;
        const currentState = statusText.includes('ON');
        const newState = !currentState;
        
        const response = await fetch(`${API_BASE}/control/light`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ state: newState })
        });
        
        if (response.ok) {
            updateDashboard();
        } else {
            const error = await response.json();
            alert('Failed to toggle light: ' + (error.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('Error toggling light:', err);
        alert('Error toggling light. Check console for details.');
    }
}

async function toggleBuzzer() {
    try {
        const statusText = document.getElementById('buzzer-status').textContent;
        const currentState = statusText.includes('ON');
        const newState = !currentState;
        
        const response = await fetch(`${API_BASE}/control/buzzer`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ state: newState })
        });
        
        if (response.ok) {
            updateDashboard();
        } else {
            const error = await response.json();
            alert('Failed to toggle buzzer: ' + (error.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('Error toggling buzzer:', err);
        alert('Error toggling buzzer. Check console for details.');
    }
}

async function toggleMode() {
    const currentMode = document.getElementById('mode-btn').textContent === 'Auto';
    try {
        const response = await fetch(`${API_BASE}/control/mode`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ mode: currentMode ? 'manual' : 'auto' })
        });
        if (response.ok) {
            updateDashboard();
        }
    } catch (err) {
        console.error('Error toggling mode:', err);
    }
}

async function setBrightness(value) {
    document.getElementById('brightness-value').textContent = value + '%';
    try {
        await fetch(`${API_BASE}/control/brightness`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ brightness: parseInt(value) })
        });
    } catch (err) {
        console.error('Error setting brightness:', err);
    }
}

async function toggleHomeMode() {
    const currentMode = document.getElementById('home-mode-btn').textContent === 'Home';
    try {
        const response = await fetch(`${API_BASE}/control/home-mode`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ home_mode: !currentMode })
        });
        if (response.ok) {
            updateDashboard();
        }
    } catch (err) {
        console.error('Error toggling home mode:', err);
    }
}

// Sensor Board Controls
async function toggleMonitoring() {
    try {
        const response = await fetch(`${API_BASE}/sensor-board/info`);
        if (!response.ok) {
            alert('Failed to get sensor board info');
            return;
        }
        const data = await response.json();
        const newState = !data.monitoring;
        
        const updateResponse = await fetch(`${API_BASE}/sensor-board/monitoring`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ monitoring: newState })
        });
        
        if (updateResponse.ok) {
            updateSensorBoardStatus();
        } else {
            const error = await updateResponse.json();
            alert('Failed to toggle monitoring: ' + (error.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('Error toggling monitoring:', err);
        alert('Error toggling monitoring. Check console for details.');
    }
}

async function toggleEncryption() {
    try {
        const response = await fetch(`${API_BASE}/sensor-board/info`);
        if (!response.ok) {
            alert('Failed to get sensor board info');
            return;
        }
        const data = await response.json();
        const newState = !data.encryption_enabled;
        
        console.log(`🔄 Toggling encryption to: ${newState}`);
        
        const updateResponse = await fetch(`${API_BASE}/sensor-board/encryption`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include', // Include cookies for session
            body: JSON.stringify({ encryption_enabled: newState })
        });
        
        if (updateResponse.ok) {
            const result = await updateResponse.json();
            console.log('✅ Encryption toggled:', result);
            // Update UI immediately
            updateSensorBoardStatus();
        } else {
            const error = await updateResponse.json();
            console.error('❌ Failed to toggle encryption:', error);
            alert('Failed to toggle encryption: ' + (error.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('❌ Error toggling encryption:', err);
        alert('Error toggling encryption. Check console for details.');
    }
}

async function setUploadInterval(value) {
    document.getElementById('upload-interval-value').textContent = value + ' ms';
    try {
        await fetch(`${API_BASE}/sensor-board/upload-interval`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ upload_interval: parseInt(value) })
        });
    } catch (err) {
        console.error('Error setting upload interval:', err);
    }
}

async function showSensorBoardInfo() {
    try {
        const response = await fetch(`${API_BASE}/sensor-board/info`);
        const data = await response.json();
        alert(`Sensor Board Info:\nMonitoring: ${data.monitoring ? 'Active' : 'Stopped'}\nEncryption: ${data.encryption_enabled ? 'Enabled' : 'Disabled'}\nUpload Interval: ${data.upload_interval}ms`);
    } catch (err) {
        console.error('Error getting sensor board info:', err);
    }
}

async function showWiFiSettings() {
    try {
        // Load current WiFi settings
        const response = await fetch(`${API_BASE}/sensor-board/info`);
        if (response.ok) {
            const data = await response.json();
            document.getElementById('wifi-ssid-input').value = data.wifi_ssid || '';
            document.getElementById('wifi-password-input').value = '';
            document.getElementById('server-url-input').value = data.server_url || '';
        }
        document.getElementById('wifi-modal').classList.add('show');
    } catch (err) {
        console.error('Error loading WiFi settings:', err);
        document.getElementById('wifi-modal').classList.add('show');
    }
}

async function saveWiFiSettings() {
    const ssid = document.getElementById('wifi-ssid-input').value.trim();
    const password = document.getElementById('wifi-password-input').value;
    const serverUrl = document.getElementById('server-url-input').value.trim();
    
    if (!ssid) {
        alert('Please enter WiFi SSID');
        return;
    }
    
    if (!serverUrl) {
        alert('Please enter Server URL');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/sensor-board/wifi`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                ssid: ssid,
                password: password,
                server_url: serverUrl
            })
        });
        
        const statusDiv = document.getElementById('wifi-settings-status');
        if (response.ok) {
            const data = await response.json();
            statusDiv.textContent = data.message || 'WiFi settings saved successfully!';
            statusDiv.style.color = '#4CAF50';
            setTimeout(() => {
                closeModal('wifi-modal');
                statusDiv.textContent = '';
            }, 2000);
        } else {
            const error = await response.json();
            statusDiv.textContent = 'Error: ' + (error.error || 'Unknown error');
            statusDiv.style.color = '#f44336';
        }
    } catch (err) {
        console.error('Error saving WiFi settings:', err);
        document.getElementById('wifi-settings-status').textContent = 'Error saving settings. Check console for details.';
        document.getElementById('wifi-settings-status').style.color = '#f44336';
    }
}

async function saveControlBoardUrl() {
    const url = document.getElementById('control-board-url-input').value;
    if (!url) {
        alert('Please enter a server URL');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/control-board/server-url`, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ server_url: url })
        });
        
        if (response.ok) {
            const result = await response.json();
            document.getElementById('control-board-url-status').textContent = 'URL saved successfully: ' + url;
            document.getElementById('control-board-url-status').style.color = '#4CAF50';
            setTimeout(() => {
                loadControlBoardUrl(); // Reload to show current status
            }, 1000);
        } else {
            const error = await response.json();
            alert('Failed to save URL: ' + (error.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('Error saving control board URL:', err);
        alert('Error saving URL. Check console for details.');
    }
}

// Load control board URL on page load
async function loadControlBoardUrl() {
    try {
        const response = await fetch(`${API_BASE}/control-board/server-url`);
        if (response.ok) {
            const data = await response.json();
            if (data.server_url) {
                document.getElementById('control-board-url-input').value = data.server_url;
                document.getElementById('control-board-url-status').textContent = 'Currently configured: ' + data.server_url;
                document.getElementById('control-board-url-status').style.color = '#4CAF50';
            } else {
                document.getElementById('control-board-url-status').textContent = 'Not configured';
                document.getElementById('control-board-url-status').style.color = '#999';
            }
        }
    } catch (err) {
        console.error('Error loading control board URL:', err);
    }
}

// Toggle sensor control (light or buzzer)
async function toggleSensorControl(sensorName, controlType, enabled, toggleElement) {
    try {
        const response = await fetch(`${API_BASE}/sensor-control/toggle`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'include',
            body: JSON.stringify({
                sensor_name: sensorName,
                control_type: controlType,
                enabled: enabled
            })
        });
        
        if (response.ok) {
            const result = await response.json();
            console.log(`✅ ${controlType} ${enabled ? 'enabled' : 'disabled'} for ${sensorName}`, result);
            
            // Update the label text
            const label = toggleElement.parentElement.querySelector('.toggle-label');
            if (label) {
                label.textContent = enabled ? 'ON' : 'OFF';
            }
        } else {
            const error = await response.json().catch(() => ({ error: 'Unknown error' }));
            console.error(`❌ Failed to toggle ${controlType} for ${sensorName}:`, error);
            alert(`Failed to update ${controlType} control: ${error.error || 'Unknown error'}`);
            
            // Revert the toggle
            toggleElement.checked = !enabled;
            const label = toggleElement.parentElement.querySelector('.toggle-label');
            if (label) {
                label.textContent = !enabled ? 'ON' : 'OFF';
            }
        }
    } catch (err) {
        console.error('Error toggling sensor control:', err);
        alert('Error updating control. Check console for details.');
        
        // Revert the toggle
        if (toggleElement) {
            toggleElement.checked = !enabled;
            const label = toggleElement.parentElement.querySelector('.toggle-label');
            if (label) {
                label.textContent = !enabled ? 'ON' : 'OFF';
            }
        }
    }
}

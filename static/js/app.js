// Global variables
let videoStream = null;
let isProcessing = false;
let processingInterval = null;
let statsInterval = null;
const API_BASE = '';

// DOM Elements
const videoInput = document.getElementById('videoInput');
const canvasOutput = document.getElementById('canvasOutput');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const resetBtn = document.getElementById('resetBtn');
const statusIndicator = document.getElementById('statusIndicator');
const statusText = document.getElementById('statusText');
const connectionStatus = document.getElementById('connectionStatus');
const connectionText = document.getElementById('connectionText');
const connectionDot = connectionStatus.querySelector('.connection-dot');

// Stats elements
const fpsValue = document.getElementById('fpsValue');
const processedFrames = document.getElementById('processedFrames');
const uptime = document.getElementById('uptime');

// Metric elements
const earValue = document.getElementById('earValue');
const gazeValue = document.getElementById('gazeValue');
const perclosValue = document.getElementById('perclosValue');
const rollValue = document.getElementById('rollValue');
const pitchValue = document.getElementById('pitchValue');
const yawValue = document.getElementById('yawValue');

// Alert elements
const asleepAlert = document.getElementById('asleepAlert');
const tiredAlert = document.getElementById('tiredAlert');
const lookingAwayAlert = document.getElementById('lookingAwayAlert');
const distractedAlert = document.getElementById('distractedAlert');

// History elements
const historyList = document.getElementById('historyList');
const refreshHistoryBtn = document.getElementById('refreshHistoryBtn');
const clearHistoryBtn = document.getElementById('clearHistoryBtn');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    checkServerHealth();
    setupEventListeners();
});

// Check server health
async function checkServerHealth() {
    try {
        const response = await fetch(`${API_BASE}/api/health`);
        const data = await response.json();
        
        if (data.status === 'healthy') {
            updateConnectionStatus(true);
        } else {
            updateConnectionStatus(false);
        }
    } catch (error) {
        console.error('Server health check failed:', error);
        updateConnectionStatus(false);
    }
}

// Update connection status
function updateConnectionStatus(connected) {
    if (connected) {
        connectionDot.classList.add('connected');
        connectionText.textContent = 'Đã kết nối';
    } else {
        connectionDot.classList.remove('connected');
        connectionText.textContent = 'Mất kết nối';
    }
}

// Setup event listeners
function setupEventListeners() {
    startBtn.addEventListener('click', startProcessing);
    stopBtn.addEventListener('click', stopProcessing);
    resetBtn.addEventListener('click', resetStats);
    refreshHistoryBtn.addEventListener('click', loadHistory);
    clearHistoryBtn.addEventListener('click', clearHistory);
    
    // Load history on page load
    loadHistory();
}

// Start video processing
async function startProcessing() {
    try {
        // Request camera access
        videoStream = await navigator.mediaDevices.getUserMedia({
            video: { 
                width: { ideal: 1280 },
                height: { ideal: 720 },
                facingMode: 'user'
            }
        });
        
        videoInput.srcObject = videoStream;
        videoInput.play();
        
        isProcessing = true;
        startBtn.disabled = true;
        stopBtn.disabled = false;
        
        statusIndicator.querySelector('.status-dot').classList.add('active');
        statusText.textContent = 'Đang xử lý...';
        
        // Start processing frames
        processingInterval = setInterval(processFrame, 100); // ~10 FPS
        
        // Start stats update
        statsInterval = setInterval(updateStats, 1000);
        
    } catch (error) {
        console.error('Error accessing camera:', error);
        alert('Không thể truy cập camera. Vui lòng kiểm tra quyền truy cập.');
    }
}

// Stop video processing
function stopProcessing() {
    if (videoStream) {
        videoStream.getTracks().forEach(track => track.stop());
        videoStream = null;
    }
    
    videoInput.srcObject = null;
    isProcessing = false;
    startBtn.disabled = false;
    stopBtn.disabled = true;
    
    statusIndicator.querySelector('.status-dot').classList.remove('active');
    statusText.textContent = 'Đã dừng';
    
    if (processingInterval) {
        clearInterval(processingInterval);
        processingInterval = null;
    }
    
    if (statsInterval) {
        clearInterval(statsInterval);
        statsInterval = null;
    }
}

// Process frame
async function processFrame() {
    if (!isProcessing || !videoInput.videoWidth) return;
    
    try {
        // Capture frame from video
        const canvas = document.createElement('canvas');
        canvas.width = videoInput.videoWidth;
        canvas.height = videoInput.videoHeight;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(videoInput, 0, 0);
        
        // Convert to base64
        const frameData = canvas.toDataURL('image/jpeg', 0.8);
        
        // Send to server
        const response = await fetch(`${API_BASE}/api/process_frame`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ frame: frameData })
        });
        
        if (!response.ok) {
            throw new Error('Server error');
        }
        
        const result = await response.json();
        
        // Display processed frame
        if (result.processed_frame) {
            displayProcessedFrame(result.processed_frame);
        }
        
        // Update metrics
        updateMetrics(result);
        
        // Update alerts
        updateAlerts(result);
        
        // Check and save to history if alert detected
        checkAndSaveHistory(result);
        
        // Update connection status
        updateConnectionStatus(true);
        
    } catch (error) {
        console.error('Error processing frame:', error);
        updateConnectionStatus(false);
    }
}

// Display processed frame
function displayProcessedFrame(frameData) {
    const img = new Image();
    img.onload = () => {
        canvasOutput.width = img.width;
        canvasOutput.height = img.height;
        const ctx = canvasOutput.getContext('2d');
        ctx.save();
        ctx.scale(-1, 1);
        ctx.drawImage(img, -img.width, 0);
        ctx.restore();
        canvasOutput.style.display = 'block';
    };
    img.src = frameData;
}

// Update metrics
function updateMetrics(result) {
    if (result.ear !== null && result.ear !== undefined) {
        earValue.textContent = result.ear;
    }
    if (result.gaze !== null && result.gaze !== undefined) {
        gazeValue.textContent = result.gaze;
    }
    if (result.perclos !== null && result.perclos !== undefined) {
        perclosValue.textContent = result.perclos;
    }
    if (result.roll !== null && result.roll !== undefined) {
        rollValue.textContent = result.roll + '°';
    }
    if (result.pitch !== null && result.pitch !== undefined) {
        pitchValue.textContent = result.pitch + '°';
    }
    if (result.yaw !== null && result.yaw !== undefined) {
        yawValue.textContent = result.yaw + '°';
    }
    
    if (result.fps) {
        fpsValue.textContent = result.fps;
    }
}

// Update alerts
function updateAlerts(result) {
    // Asleep
    if (result.asleep) {
        asleepAlert.classList.add('active');
        asleepAlert.querySelector('.alert-badge').textContent = 'CÓ';
        asleepAlert.querySelector('.alert-badge').classList.remove('inactive');
    } else {
        asleepAlert.classList.remove('active');
        asleepAlert.querySelector('.alert-badge').textContent = 'KHÔNG';
        asleepAlert.querySelector('.alert-badge').classList.add('inactive');
    }
    
    // Tired
    if (result.tired) {
        tiredAlert.classList.add('active');
        tiredAlert.querySelector('.alert-badge').textContent = 'CÓ';
        tiredAlert.querySelector('.alert-badge').classList.remove('inactive');
    } else {
        tiredAlert.classList.remove('active');
        tiredAlert.querySelector('.alert-badge').textContent = 'KHÔNG';
        tiredAlert.querySelector('.alert-badge').classList.add('inactive');
    }
    
    // Looking away
    if (result.looking_away) {
        lookingAwayAlert.classList.add('active');
        lookingAwayAlert.querySelector('.alert-badge').textContent = 'CÓ';
        lookingAwayAlert.querySelector('.alert-badge').classList.remove('inactive');
    } else {
        lookingAwayAlert.classList.remove('active');
        lookingAwayAlert.querySelector('.alert-badge').textContent = 'KHÔNG';
        lookingAwayAlert.querySelector('.alert-badge').classList.add('inactive');
    }
    
    // Distracted
    if (result.distracted) {
        distractedAlert.classList.add('active');
        distractedAlert.querySelector('.alert-badge').textContent = 'CÓ';
        distractedAlert.querySelector('.alert-badge').classList.remove('inactive');
    } else {
        distractedAlert.classList.remove('active');
        distractedAlert.querySelector('.alert-badge').textContent = 'KHÔNG';
        distractedAlert.querySelector('.alert-badge').classList.add('inactive');
    }
}

// Update stats
async function updateStats() {
    try {
        const response = await fetch(`${API_BASE}/api/stats`);
        const data = await response.json();
        
        processedFrames.textContent = data.processed_frames || 0;
        
        const uptimeSeconds = Math.floor(data.uptime || 0);
        const minutes = Math.floor(uptimeSeconds / 60);
        const seconds = uptimeSeconds % 60;
        uptime.textContent = `${minutes}m ${seconds}s`;
        
    } catch (error) {
        console.error('Error updating stats:', error);
    }
}

// Reset stats
async function resetStats() {
    try {
        const response = await fetch(`${API_BASE}/api/reset`, {
            method: 'POST'
        });
        
        if (response.ok) {
            // Reset UI
            processedFrames.textContent = '0';
            uptime.textContent = '0s';
            fpsValue.textContent = '0';
            
            // Reset metrics
            earValue.textContent = '-';
            gazeValue.textContent = '-';
            perclosValue.textContent = '-';
            rollValue.textContent = '-';
            pitchValue.textContent = '-';
            yawValue.textContent = '-';
            
            // Reset alerts
            [asleepAlert, tiredAlert, lookingAwayAlert, distractedAlert].forEach(alert => {
                alert.classList.remove('active');
                alert.querySelector('.alert-badge').textContent = 'KHÔNG';
                alert.querySelector('.alert-badge').classList.add('inactive');
            });
            
            alert('Đã reset thống kê!');
        }
    } catch (error) {
        console.error('Error resetting stats:', error);
    }
}

// Load history
async function loadHistory() {
    try {
        const response = await fetch(`${API_BASE}/api/history`);
        const data = await response.json();
        
        if (data.history && data.history.length > 0) {
            historyList.innerHTML = '';
            data.history.forEach(item => {
                const historyItem = createHistoryItem(item);
                historyList.appendChild(historyItem);
            });
        } else {
            historyList.innerHTML = '<div class="history-empty">Chưa có dữ liệu lịch sử</div>';
        }
    } catch (error) {
        console.error('Error loading history:', error);
        historyList.innerHTML = '<div class="history-empty">Lỗi khi tải lịch sử</div>';
    }
}

// Create history item element
function createHistoryItem(item) {
    const div = document.createElement('div');
    div.className = 'history-item';
    
    const alerts = [];
    if (item.asleep) alerts.push('Ngủ gật');
    if (item.tired) alerts.push('Mệt mỏi');
    if (item.looking_away) alerts.push('Nhìn đi chỗ khác');
    if (item.distracted) alerts.push('Mất tập trung');
    
    const time = new Date(item.timestamp).toLocaleString('vi-VN');
    
    let metricsHTML = '';
    if (item.ear !== null && item.ear !== undefined) {
        metricsHTML += `<div class="history-metric"><span class="history-metric-label">EAR:</span><span class="history-metric-value">${item.ear}</span></div>`;
    }
    if (item.gaze !== null && item.gaze !== undefined) {
        metricsHTML += `<div class="history-metric"><span class="history-metric-label">Gaze:</span><span class="history-metric-value">${item.gaze}</span></div>`;
    }
    if (item.perclos !== null && item.perclos !== undefined) {
        metricsHTML += `<div class="history-metric"><span class="history-metric-label">PERCLOS:</span><span class="history-metric-value">${item.perclos}</span></div>`;
    }
    
    div.innerHTML = `
        <div class="history-item-header">
            <span class="history-item-time">${time}</span>
            ${alerts.length > 0 ? `<div class="history-item-alerts">${alerts.map(a => `<span class="history-alert-badge">${a}</span>`).join('')}</div>` : ''}
        </div>
        ${metricsHTML ? `<div class="history-item-metrics">${metricsHTML}</div>` : ''}
    `;
    
    return div;
}

// Clear history
async function clearHistory() {
    if (!confirm('Bạn có chắc muốn xóa toàn bộ lịch sử?')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/history/clear`, {
            method: 'POST'
        });
        
        if (response.ok) {
            loadHistory();
            alert('Đã xóa lịch sử!');
        }
    } catch (error) {
        console.error('Error clearing history:', error);
        alert('Lỗi khi xóa lịch sử!');
    }
}

// Save to history when alert is detected
let lastAlertState = {
    asleep: false,
    tired: false,
    looking_away: false,
    distracted: false
};

function checkAndSaveHistory(result) {
    const currentState = {
        asleep: result.asleep || false,
        tired: result.tired || false,
        looking_away: result.looking_away || false,
        distracted: result.distracted || false
    };
    
    // Check if any alert state changed from false to true
    const alertDetected = (
        (!lastAlertState.asleep && currentState.asleep) ||
        (!lastAlertState.tired && currentState.tired) ||
        (!lastAlertState.looking_away && currentState.looking_away) ||
        (!lastAlertState.distracted && currentState.distracted)
    );
    
    if (alertDetected) {
        // Save to history
        saveToHistory(result);
    }
    
    lastAlertState = currentState;
}

// Save to history
async function saveToHistory(result) {
    try {
        await fetch(`${API_BASE}/api/history`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                timestamp: result.timestamp || new Date().toISOString(),
                asleep: result.asleep || false,
                tired: result.tired || false,
                looking_away: result.looking_away || false,
                distracted: result.distracted || false,
                ear: result.ear,
                gaze: result.gaze,
                perclos: result.perclos,
                roll: result.roll,
                pitch: result.pitch,
                yaw: result.yaw
            })
        });
    } catch (error) {
        console.error('Error saving to history:', error);
    }
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    stopProcessing();
});


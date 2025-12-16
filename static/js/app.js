// Global variables
let pollingInterval = null;
const API_BASE = '';

// DOM Elements
const videoStreamImg = document.getElementById('videoStream');
const statusText = document.getElementById('statusText');
const connectionStatus = document.getElementById('connectionStatus');
const connectionText = document.getElementById('connectionText');
const connectionDot = connectionStatus ? connectionStatus.querySelector('.connection-dot') : null;
const statusDot = document.getElementById('statusDot');
const loadingOverlay = document.getElementById('loadingOverlay');

// Check video stream status
if (videoStreamImg) {
    // Thêm event listener để check khi video load
    videoStreamImg.addEventListener('load', () => {
        console.log('Video stream image loaded successfully');
        hideLoadingOverlay();
    });

    videoStreamImg.addEventListener('error', () => {
        console.log('Video stream image error');
        showStreamError();
    });
}

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

    // Bắt đầu polling kết quả từ server
    startPolling();

    // Load history
    loadHistory();

    // Auto hide loading overlay sau 3 giây (fallback)
    setTimeout(() => {
        if (loadingOverlay && loadingOverlay.style.display !== 'none') {
            console.log('Auto-hiding loading overlay (timeout)');
            hideLoadingOverlay();
        }
    }, 3000);
});

// Hide loading overlay khi video stream sẵn sàng
function hideLoadingOverlay() {
    console.log('Video stream đã load, đang ẩn overlay...');

    if (loadingOverlay && loadingOverlay.style.display !== 'none') {
        loadingOverlay.style.opacity = '0';
        loadingOverlay.style.transition = 'opacity 0.5s';
        setTimeout(() => {
            loadingOverlay.style.display = 'none';
        }, 500);

        if (statusText) {
            statusText.textContent = 'Đang phân tích...';
        }
        if (statusDot) {
            statusDot.classList.add('status-active');
        }

        console.log('Video stream đã sẵn sàng');
    }
}

// Export để có thể gọi từ HTML
window.hideLoadingOverlay = hideLoadingOverlay;

// Show error khi stream gặp lỗi
function showStreamError() {
    console.error('Lỗi khi load video stream');

    if (loadingOverlay) {
        loadingOverlay.style.display = 'flex';
        loadingOverlay.style.opacity = '1';
        loadingOverlay.innerHTML = `
            <div class="text-center">
                <svg class="w-16 h-16 mx-auto mb-4 text-[#f582ae]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
                </svg>
                <p class="text-white font-bold text-lg mb-2">Không thể tải video stream</p>
                <p class="text-[#8bd3dd] text-sm">Vui lòng khởi động Raspberry Pi client</p>
                <button onclick="location.reload()" class="mt-4 bg-[#8bd3dd] text-[#001858] px-6 py-2 rounded-[6px] font-bold hover:shadow-xl transition-all">
                    Thử lại
                </button>
            </div>
        `;
    }
}

// Export để có thể gọi từ HTML
window.showStreamError = showStreamError;

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
    if (refreshHistoryBtn) {
        refreshHistoryBtn.addEventListener('click', loadHistory);
    }
    if (clearHistoryBtn) {
        clearHistoryBtn.addEventListener('click', clearHistory);
    }
}

// Start polling latest result từ server
function startPolling() {
    // Poll metrics mỗi 500ms
    pollingInterval = setInterval(pollLatestResult, 500);

    console.log('Đã bắt đầu polling kết quả từ server');

    // Check video stream status sau 2 giây
    setTimeout(() => {
        if (videoStreamImg && videoStreamImg.complete && videoStreamImg.naturalHeight !== 0) {
            console.log('Video stream đã sẵn sàng (complete check)');
            hideLoadingOverlay();
        }
    }, 2000);
}

// Poll latest result từ server
async function pollLatestResult() {
    try {
        const response = await fetch(`${API_BASE}/api/latest_result`);
        if (!response.ok) {
            throw new Error('Server error');
        }

        const result = await response.json();

        // Update metrics
        updateMetrics(result);

        // Update alerts
        updateAlerts(result);

        // Check and save to history if alert detected
        checkAndSaveHistory(result);

        // Update connection status
        updateConnectionStatus(true);

    } catch (error) {
        console.error('Error polling result:', error);
        updateConnectionStatus(false);
    }
}

// Không cần các function xử lý camera local nữa
// Video stream đến từ Raspberry Pi qua /video_feed endpoint

// Update metrics
function updateMetrics(result) {
    if (result.ear !== null && result.ear !== undefined) {
        earValue.textContent = Number(result.ear).toFixed(4);
    } else {
        earValue.textContent = '-';
    }

    if (result.gaze !== null && result.gaze !== undefined) {
        gazeValue.textContent = Number(result.gaze).toFixed(4);
    } else {
        gazeValue.textContent = '-';
    }

    if (result.perclos !== null && result.perclos !== undefined) {
        perclosValue.textContent = Number(result.perclos).toFixed(4);
    } else {
        perclosValue.textContent = '-';
    }

    if (result.roll !== null && result.roll !== undefined) {
        rollValue.textContent = Number(result.roll).toFixed(1) + '°';
    } else {
        rollValue.textContent = '-';
    }

    if (result.pitch !== null && result.pitch !== undefined) {
        pitchValue.textContent = Number(result.pitch).toFixed(1) + '°';
    } else {
        pitchValue.textContent = '-';
    }

    if (result.yaw !== null && result.yaw !== undefined) {
        yawValue.textContent = Number(result.yaw).toFixed(1) + '°';
    } else {
        yawValue.textContent = '-';
    }

}

// Update alerts
function updateAlerts(result) {
    // Asleep
    if (result.asleep) {
        asleepAlert.classList.add('alert-active');
        asleepAlert.querySelector('.alert-badge').textContent = 'CÓ';
    } else {
        asleepAlert.classList.remove('alert-active');
        asleepAlert.querySelector('.alert-badge').textContent = 'KHÔNG';
    }

    // Tired
    if (result.tired) {
        tiredAlert.classList.add('alert-active');
        tiredAlert.querySelector('.alert-badge').textContent = 'CÓ';
    } else {
        tiredAlert.classList.remove('alert-active');
        tiredAlert.querySelector('.alert-badge').textContent = 'KHÔNG';
    }

    // Looking away
    if (result.looking_away) {
        lookingAwayAlert.classList.add('alert-active');
        lookingAwayAlert.querySelector('.alert-badge').textContent = 'CÓ';
    } else {
        lookingAwayAlert.classList.remove('alert-active');
        lookingAwayAlert.querySelector('.alert-badge').textContent = 'KHÔNG';
    }

    // Distracted
    if (result.distracted) {
        distractedAlert.classList.add('alert-active');
        distractedAlert.querySelector('.alert-badge').textContent = 'CÓ';
    } else {
        distractedAlert.classList.remove('alert-active');
        distractedAlert.querySelector('.alert-badge').textContent = 'KHÔNG';
    }
}

// Load history
async function loadHistory() {
    try {
        const response = await fetch(`${API_BASE}/api/history`);
        const data = await response.json();

        if (data.history && data.history.length > 0) {
            historyList.innerHTML = '<div class="space-y-3"></div>';
            const container = historyList.querySelector('.space-y-3');

            data.history.forEach(item => {
                const historyItem = createHistoryItem(item);
                container.appendChild(historyItem);
            });
        } else {
            historyList.innerHTML = `
                <div class="text-center text-body py-12">
                    <svg class="w-16 h-16 mx-auto mb-4 text-[rgba(0,24,88,0.3)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path>
                    </svg>
                    <p class="text-xl font-bold text-headline mb-2">Chưa có dữ liệu lịch sử</p>
                    <p class="text-sm text-muted">Hệ thống sẽ tự động lưu khi phát hiện cảnh báo</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('Error loading history:', error);
        historyList.innerHTML = `
            <div class="text-center text-body py-8">
                <p class="text-lg font-bold text-headline mb-2">Lỗi khi tải lịch sử</p>
                <p class="text-sm text-muted">Vui lòng thử lại sau</p>
            </div>
        `;
    }
}

// Create history item element
function createHistoryItem(item) {
    const div = document.createElement('div');
    div.className = 'p-6 rounded-[6px] bg-white/80 backdrop-blur-sm border-2 border-[rgba(0,24,88,0.1)] hover:shadow-xl transition-all duration-300';

    const alerts = [];
    if (item.asleep) alerts.push({ text: '😴 Ngủ gật', color: 'bg-[#f582ae] text-[#001858]' });
    if (item.tired) alerts.push({ text: '😪 Mệt mỏi', color: 'bg-[#8bd3dd] text-[#001858]' });
    if (item.looking_away) alerts.push({ text: '👀 Nhìn xa', color: 'bg-[#f3d2c1] text-[#001858]' });
    if (item.distracted) alerts.push({ text: '💭 Mất tập trung', color: 'bg-[rgba(0,24,88,0.2)] text-[#001858]' });

    const time = new Date(item.timestamp).toLocaleString('vi-VN');

    let metricsHTML = '';
    if (item.ear !== null && item.ear !== undefined) {
        metricsHTML += `
            <div class="flex justify-between items-center p-3 bg-[rgba(245,130,174,0.1)] rounded-[6px]">
                <span class="text-sm font-semibold text-[#001858]">EAR:</span>
                <span class="text-lg font-bold text-[#001858]">${Number(item.ear).toFixed(4)}</span>
            </div>`;
    }
    if (item.gaze !== null && item.gaze !== undefined) {
        metricsHTML += `
            <div class="flex justify-between items-center p-3 bg-[rgba(139,211,221,0.1)] rounded-[6px]">
                <span class="text-sm font-semibold text-[#001858]">Gaze:</span>
                <span class="text-lg font-bold text-[#001858]">${Number(item.gaze).toFixed(4)}</span>
            </div>`;
    }
    if (item.perclos !== null && item.perclos !== undefined) {
        metricsHTML += `
            <div class="flex justify-between items-center p-3 bg-[rgba(0,24,88,0.08)] rounded-[6px]">
                <span class="text-sm font-semibold text-[#001858]">PERCLOS:</span>
                <span class="text-lg font-bold text-[#001858]">${Number(item.perclos).toFixed(4)}</span>
            </div>`;
    }

    div.innerHTML = `
        <div class="flex justify-between items-start mb-4">
            <span class="text-sm font-bold text-[#001858] bg-[rgba(139,211,221,0.2)] px-4 py-2 rounded-[6px]">${time}</span>
            ${alerts.length > 0 ? `
                <div class="flex flex-wrap gap-2">
                    ${alerts.map(a => `<span class="inline-flex items-center px-4 py-2 rounded-[6px] text-sm font-bold ${a.color}">${a.text}</span>`).join('')}
                </div>
            ` : ''}
        </div>
        ${metricsHTML ? `<div class="grid grid-cols-3 gap-3 mt-4">${metricsHTML}</div>` : ''}
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
                timestamp: new Date().toISOString(),
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

        // Reload history sau khi save
        loadHistory();
    } catch (error) {
        console.error('Error saving to history:', error);
    }
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (pollingInterval) {
        clearInterval(pollingInterval);
    }
});


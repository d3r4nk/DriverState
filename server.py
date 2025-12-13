import os
import time
import base64
import threading
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import cv2
import numpy as np

# Import AI processor
from ai_processor import AIProcessor

app = Flask(__name__)
CORS(app)

# Khởi tạo AI processor
ai_processor = None
processing_stats = {
    'total_frames': 0,
    'processed_frames': 0,
    'start_time': time.time(),
    'last_update': time.time()
}

# Lịch sử biểu hiện
history_file = 'history.json'
history_lock = threading.Lock()
MAX_HISTORY_ITEMS = 1000  # Giới hạn số lượng lịch sử

def init_ai_processor():
    """Khởi tạo AI processor với các tham số mặc định"""
    global ai_processor
    camera_params_path = os.path.join('driver_state_detection', 'camera_params.json')
    if os.path.exists(camera_params_path):
        ai_processor = AIProcessor(camera_params=camera_params_path)
    else:
        ai_processor = AIProcessor()
    print("AI Processor đã được khởi tạo thành công!")

@app.route('/')
def index():
    """Trang chủ với giao diện web"""
    return render_template('index.html')

@app.route('/api/health', methods=['GET'])
def health():
    """Kiểm tra trạng thái server"""
    return jsonify({
        'status': 'healthy',
        'ai_processor_ready': ai_processor is not None,
        'uptime': time.time() - processing_stats['start_time']
    })

@app.route('/api/process_frame', methods=['POST'])
def process_frame():
    """API endpoint để nhận frame từ client và xử lý AI"""
    global processing_stats
    
    try:
        # Kiểm tra nếu có file ảnh trong request
        if 'image' not in request.files and 'frame' not in request.json:
            return jsonify({'error': 'Không tìm thấy frame trong request'}), 400
        
        # Lấy frame từ request
        if 'image' in request.files:
            # Nhận file ảnh
            file = request.files['image']
            frame_bytes = file.read()
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        else:
            # Nhận base64 encoded frame
            frame_data = request.json.get('frame', '')
            if frame_data.startswith('data:image'):
                frame_data = frame_data.split(',')[1]
            frame_bytes = base64.b64decode(frame_data)
            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if frame is None:
            return jsonify({'error': 'Không thể decode frame'}), 400
        
        processing_stats['total_frames'] += 1
        
        # Xử lý frame với AI
        if ai_processor is None:
            return jsonify({'error': 'AI Processor chưa được khởi tạo'}), 500
        
        result = ai_processor.process_frame(frame)
        processing_stats['processed_frames'] += 1
        processing_stats['last_update'] = time.time()
        
        # Tính FPS
        elapsed = time.time() - processing_stats['start_time']
        fps = processing_stats['processed_frames'] / elapsed if elapsed > 0 else 0
        
        # Encode frame đã xử lý thành base64 để gửi lại client
        if result.get('processed_frame') is not None:
            _, buffer = cv2.imencode('.jpg', result['processed_frame'], [cv2.IMWRITE_JPEG_QUALITY, 85])
            frame_base64 = base64.b64encode(buffer).decode('utf-8')
            result['processed_frame'] = f'data:image/jpeg;base64,{frame_base64}'
        
        result['fps'] = round(fps, 2)
        result['timestamp'] = datetime.now().isoformat()
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Lỗi khi xử lý frame: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Lỗi xử lý: {str(e)}'}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Lấy thống kê xử lý"""
    elapsed = time.time() - processing_stats['start_time']
    fps = processing_stats['processed_frames'] / elapsed if elapsed > 0 else 0
    
    return jsonify({
        'total_frames': processing_stats['total_frames'],
        'processed_frames': processing_stats['processed_frames'],
        'fps': round(fps, 2),
        'uptime': round(elapsed, 2),
        'last_update': processing_stats['last_update']
    })

@app.route('/api/reset', methods=['POST'])
def reset_stats():
    """Reset thống kê"""
    global processing_stats
    processing_stats = {
        'total_frames': 0,
        'processed_frames': 0,
        'start_time': time.time(),
        'last_update': time.time()
    }
    if ai_processor:
        ai_processor.reset()
    return jsonify({'message': 'Đã reset thống kê'})

def load_history():
    """Load lịch sử từ file"""
    try:
        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Lỗi khi load lịch sử: {e}")
    return []

def save_history(history):
    """Lưu lịch sử vào file"""
    try:
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Lỗi khi lưu lịch sử: {e}")

@app.route('/api/history', methods=['GET'])
def get_history():
    """Lấy lịch sử biểu hiện"""
    with history_lock:
        history = load_history()
        # Sắp xếp theo thời gian mới nhất
        history.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        # Giới hạn số lượng
        history = history[:MAX_HISTORY_ITEMS]
    return jsonify({'history': history})

@app.route('/api/history', methods=['POST'])
def add_history():
    """Thêm một mục vào lịch sử"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Không có dữ liệu'}), 400
        
        # Chỉ lưu khi có cảnh báo
        has_alert = (
            data.get('asleep', False) or
            data.get('tired', False) or
            data.get('looking_away', False) or
            data.get('distracted', False)
        )
        
        if not has_alert:
            return jsonify({'message': 'Không có cảnh báo, không lưu lịch sử'})
        
        history_item = {
            'timestamp': data.get('timestamp', datetime.now().isoformat()),
            'asleep': data.get('asleep', False),
            'tired': data.get('tired', False),
            'looking_away': data.get('looking_away', False),
            'distracted': data.get('distracted', False),
            'ear': data.get('ear'),
            'gaze': data.get('gaze'),
            'perclos': data.get('perclos'),
            'roll': data.get('roll'),
            'pitch': data.get('pitch'),
            'yaw': data.get('yaw')
        }
        
        with history_lock:
            history = load_history()
            history.append(history_item)
            # Giới hạn số lượng
            if len(history) > MAX_HISTORY_ITEMS:
                history = history[-MAX_HISTORY_ITEMS:]
            save_history(history)
        
        return jsonify({'message': 'Đã thêm vào lịch sử', 'item': history_item})
        
    except Exception as e:
        print(f"Lỗi khi thêm lịch sử: {e}")
        return jsonify({'error': f'Lỗi: {str(e)}'}), 500

@app.route('/api/history/clear', methods=['POST'])
def clear_history():
    """Xóa toàn bộ lịch sử"""
    with history_lock:
        save_history([])
    return jsonify({'message': 'Đã xóa toàn bộ lịch sử'})

if __name__ == '__main__':
    print("Đang khởi động server...")
    init_ai_processor()
    print("Server đã sẵn sàng!")
    print("Truy cập http://localhost:5000 để xem giao diện")
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)


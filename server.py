"""
Server Flask để nhận frame từ Raspberry Pi client và xử lý phát hiện trạng thái người lái xe.

Author: Driver State Detection Server
Date: 2025
"""

import base64
import io
import time
from datetime import datetime
from threading import Lock

import cv2
import mediapipe as mp
import numpy as np
from flask import Flask, jsonify, request, render_template, Response

# Import các module xử lý từ driver_state_detection
import sys
sys.path.append('driver_state_detection')

from driver_state_detection.attention_scorer import AttentionScorer
from driver_state_detection.eye_detector import EyeDetector
from driver_state_detection.pose_estimation import HeadPoseEstimator
from driver_state_detection.utils import get_landmarks, load_camera_parameters

# ============================================================================
# Khởi tạo Flask App
# ============================================================================
app = Flask(__name__)

# ============================================================================
# Cấu hình và khởi tạo các detector
# ============================================================================

# Thông số mặc định (có thể điều chỉnh)
EAR_THRESH = 0.15           # Ngưỡng EAR để phát hiện mắt nhắm
GAZE_THRESH = 0.2           # Ngưỡng Gaze Score
EAR_TIME_THRESH = 2.0       # Thời gian nhắm mắt liên tục (giây)
GAZE_TIME_THRESH = 2.0      # Thời gian nhìn không tập trung (giây)
ROLL_THRESH = 20            # Ngưỡng góc roll (độ)
PITCH_THRESH = 20           # Ngưỡng góc pitch (độ)
YAW_THRESH = 28             # Ngưỡng góc yaw (độ)
POSE_TIME_THRESH = 2.5      # Thời gian tư thế đầu sai (giây)
PERCLOS_THRESH = 0.2        # Ngưỡng PERCLOS (20%)

print("🚀 Đang khởi tạo MediaPipe FaceMesh...")
# Khởi tạo MediaPipe Face Mesh
face_mesh_detector = mp.solutions.face_mesh.FaceMesh(
    static_image_mode=False,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
    refine_landmarks=True,
)

# Khởi tạo Eye Detector
eye_detector = EyeDetector(show_processing=False)

# Khởi tạo Head Pose Estimator (không cần camera parameters cho demo)
head_pose_estimator = HeadPoseEstimator(
    show_axis=False, 
    camera_matrix=None, 
    dist_coeffs=None
)

# Khởi tạo Attention Scorer
attention_scorer = AttentionScorer(
    t_now=time.perf_counter(),
    ear_thresh=EAR_THRESH,
    gaze_thresh=GAZE_THRESH,
    perclos_thresh=PERCLOS_THRESH,
    roll_thresh=ROLL_THRESH,
    pitch_thresh=PITCH_THRESH,
    yaw_thresh=YAW_THRESH,
    ear_time_thresh=EAR_TIME_THRESH,
    gaze_time_thresh=GAZE_TIME_THRESH,
    pose_time_thresh=POSE_TIME_THRESH,
    verbose=False,
)

# Biến toàn cục để theo dõi FPS
prev_time = time.perf_counter()
fps_value = 0.0

# Biến toàn cục để throttle (giới hạn tần suất) cảnh báo
last_alert_times = {
    'tired': 0.0,
    'looking_away': 0.0,
    'distracted': 0.0
}
ALERT_THROTTLE_SECONDS = 3.0  # Gửi cảnh báo không nghiêm trọng mỗi 3 giây

# Biến toàn cục để theo dõi thống kê
start_time = time.perf_counter()
processed_frames_count = 0
history_data = []  # Lưu lịch sử cảnh báo
MAX_HISTORY_SIZE = 100  # Giới hạn số lượng lịch sử

# Biến toàn cục để lưu frame stream từ Raspberry Pi
latest_frame = None  # Frame mới nhất từ client
latest_processed_frame = None  # Frame đã xử lý (có vẽ landmarks, metrics)
frame_lock = Lock()  # Lock để đồng bộ truy cập frame
last_result = None  # Kết quả xử lý mới nhất

print("✅ Server đã sẵn sàng!")

# ============================================================================
# Helper Functions
# ============================================================================

def decode_frame_from_base64(base64_string):
    """
    Decode frame từ chuỗi base64.
    
    Args:
        base64_string: Chuỗi base64 (có thể có prefix 'data:image/jpeg;base64,')
    
    Returns:
        numpy.ndarray: Frame ở định dạng BGR (OpenCV)
    """
    # Loại bỏ prefix nếu có
    if ',' in base64_string:
        base64_string = base64_string.split(',')[1]
    
    # Decode base64
    img_bytes = base64.b64decode(base64_string)
    
    # Chuyển bytes thành numpy array
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    
    # Decode JPEG thành OpenCV image
    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    
    return frame


def decode_frame_from_bytes(raw_bytes):
    """
    Decode frame từ raw bytes.
    
    Args:
        raw_bytes: Raw bytes của ảnh JPEG
    
    Returns:
        numpy.ndarray: Frame ở định dạng BGR (OpenCV)
    """
    img_array = np.frombuffer(raw_bytes, dtype=np.uint8)
    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    return frame


def draw_annotations_on_frame(frame, result):
    """
    Vẽ annotations (metrics, alerts) lên frame
    
    Args:
        frame: numpy array (BGR format)
        result: dict kết quả xử lý
    
    Returns:
        numpy.ndarray: Frame đã vẽ annotations
    """
    annotated_frame = frame.copy()
    
    # Vẽ metrics
    y_pos = 30
    if result.get('ear') is not None:
        cv2.putText(annotated_frame, f"EAR: {result['ear']:.4f}", 
                   (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        y_pos += 25
    
    if result.get('gaze') is not None:
        cv2.putText(annotated_frame, f"Gaze: {result['gaze']:.4f}", 
                   (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        y_pos += 25
    
    cv2.putText(annotated_frame, f"PERCLOS: {result['perclos']:.4f}", 
               (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    y_pos += 25
    
    if result.get('roll') is not None:
        cv2.putText(annotated_frame, f"Roll: {result['roll']:.1f}", 
                   (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        y_pos += 25
    
    # Vẽ alerts
    alert_y = 30
    if result.get('asleep'):
        cv2.putText(annotated_frame, "ASLEEP!", 
                   (annotated_frame.shape[1] - 150, alert_y), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        alert_y += 30
    
    if result.get('tired'):
        cv2.putText(annotated_frame, "TIRED!", 
                   (annotated_frame.shape[1] - 150, alert_y), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
        alert_y += 30
    
    if result.get('looking_away'):
        cv2.putText(annotated_frame, "LOOKING AWAY!", 
                   (annotated_frame.shape[1] - 150, alert_y), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        alert_y += 30
    
    if result.get('distracted'):
        cv2.putText(annotated_frame, "DISTRACTED!", 
                   (annotated_frame.shape[1] - 150, alert_y), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    
    # Vẽ FPS
    cv2.putText(annotated_frame, f"FPS: {result.get('fps', 0):.1f}", 
               (10, annotated_frame.shape[0] - 10), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
    
    return annotated_frame


def generate_mjpeg_stream():
    """
    Generator để tạo MJPEG stream từ latest_processed_frame
    """
    global latest_processed_frame
    
    while True:
        with frame_lock:
            if latest_processed_frame is not None:
                frame = latest_processed_frame.copy()
            else:
                # Tạo frame placeholder nếu chưa có frame
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(frame, "Waiting for stream...", 
                           (180, 240), cv2.FONT_HERSHEY_SIMPLEX, 
                           1, (255, 255, 255), 2)
        
        # Encode frame thành JPEG
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        frame_bytes = buffer.tobytes()
        
        # Tạo multipart response cho MJPEG stream
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        # Giảm CPU usage
        time.sleep(0.033)  # ~30 FPS


def process_frame(frame):
    """
    Xử lý frame và trả về các chỉ số.
    
    Args:
        frame: numpy array (BGR format)
    
    Returns:
        dict: Dictionary chứa các chỉ số
    """
    global prev_time, fps_value, attention_scorer, processed_frames_count
    
    # Tăng số frame đã xử lý
    processed_frames_count += 1
    
    # Tính FPS
    t_now = time.perf_counter()
    elapsed_time = t_now - prev_time
    prev_time = t_now
    
    if elapsed_time > 0:
        fps_value = round(1 / elapsed_time, 2)
    
    # Chuyển đổi frame sang grayscale
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    frame_size = (frame.shape[1], frame.shape[0])
    
    # Tạo 3-channel grayscale image cho MediaPipe
    gray_3ch = np.stack([gray, gray, gray], axis=2)
    
    # Detect face landmarks
    results = face_mesh_detector.process(gray_3ch)
    
    # Khởi tạo giá trị mặc định
    ear = None
    gaze = None
    roll = None
    pitch = None
    yaw = None
    asleep = False
    tired = False
    looking_away = False
    distracted = False
    perclos = 0.0
    
    # Nếu phát hiện được khuôn mặt
    if results.multi_face_landmarks:
        # Lấy landmarks của khuôn mặt đầu tiên
        landmarks = get_landmarks(results.multi_face_landmarks)
        
        # Tính EAR (Eye Aspect Ratio)
        ear = eye_detector.get_EAR(landmarks=landmarks)
        
        # Tính PERCLOS (rolling window)
        tired, perclos = attention_scorer.get_rolling_PERCLOS(t_now, ear)
        
        # Tính Gaze Score
        gaze = eye_detector.get_Gaze_Score(
            frame=gray_3ch, landmarks=landmarks, frame_size=frame_size
        )
        
        # Tính Head Pose
        _, roll, pitch, yaw = head_pose_estimator.get_pose(
            frame=frame, landmarks=landmarks, frame_size=frame_size
        )
        
        # Chuyển đổi roll, pitch, yaw từ numpy array sang float
        if roll is not None:
            roll = float(roll[0])
        if pitch is not None:
            pitch = float(pitch[0])
        if yaw is not None:
            yaw = float(yaw[0])
        
        # Đánh giá trạng thái
        asleep, looking_away, distracted = attention_scorer.eval_scores(
            t_now=t_now,
            ear_score=ear,
            gaze_score=gaze,
            head_roll=roll,
            head_pitch=pitch,
            head_yaw=yaw,
        )
    
    # Throttle (giới hạn tần suất) cho các cảnh báo không nghiêm trọng
    global last_alert_times
    current_time = time.perf_counter()
    
    # ASLEEP luôn gửi ngay lập tức (nguy hiểm nhất)
    send_asleep = bool(asleep)
    
    # TIRED: chỉ gửi nếu đã qua 6 giây hoặc trạng thái thay đổi
    if tired and (current_time - last_alert_times['tired'] >= ALERT_THROTTLE_SECONDS):
        send_tired = True
        last_alert_times['tired'] = current_time
    else:
        send_tired = False
    
    # LOOKING_AWAY: chỉ gửi nếu đã qua 6 giây
    if looking_away and (current_time - last_alert_times['looking_away'] >= ALERT_THROTTLE_SECONDS):
        send_looking_away = True
        last_alert_times['looking_away'] = current_time
    else:
        send_looking_away = False
    
    # DISTRACTED: chỉ gửi nếu đã qua 6 giây
    if distracted and (current_time - last_alert_times['distracted'] >= ALERT_THROTTLE_SECONDS):
        send_distracted = True
        last_alert_times['distracted'] = current_time
    else:
        send_distracted = False
    
    # Chuẩn bị response
    response = {
        "ear": round(ear, 4) if ear is not None else None,
        "gaze": round(gaze, 4) if gaze is not None else None,
        "perclos": round(perclos, 4),
        "roll": round(roll, 2) if roll is not None else None,
        "pitch": round(pitch, 2) if pitch is not None else None,
        "yaw": round(yaw, 2) if yaw is not None else None,
        "asleep": send_asleep,           # Luôn gửi ngay
        "tired": send_tired,             # Throttled 6s
        "looking_away": send_looking_away,  # Throttled 6s
        "distracted": send_distracted,   # Throttled 6s
        "fps": fps_value,
    }
    
    return response


# ============================================================================
# API Endpoints
# ============================================================================

@app.route('/')
def index():
    """
    Trang chủ - Dashboard giao diện web
    """
    return render_template('index.html')


@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Endpoint để kiểm tra server có sẵn sàng không.
    """
    return jsonify({
        "status": "healthy",
        "message": "Server đang hoạt động",
        "timestamp": datetime.now().isoformat()
    }), 200


@app.route('/api/process_frame', methods=['POST'])
def process_frame_endpoint():
    """
    Endpoint chính để nhận và xử lý frame từ Raspberry Pi client.
    
    Hỗ trợ 2 định dạng:
    1. JSON với base64: {"frame": "data:image/jpeg;base64,..."}
    2. Raw bytes: Content-Type: application/octet-stream
    """
    global latest_frame, latest_processed_frame, last_result
    
    try:
        start_time_processing = time.perf_counter()
        
        # Kiểm tra Content-Type
        content_type = request.content_type
        
        if 'application/json' in content_type:
            # Nhận frame dưới dạng JSON base64
            data = request.get_json()
            
            if not data or 'frame' not in data:
                return jsonify({
                    "error": "Missing 'frame' field in JSON"
                }), 400
            
            base64_string = data['frame']
            frame = decode_frame_from_base64(base64_string)
            
        elif 'application/octet-stream' in content_type or 'image/' in content_type:
            # Nhận frame dưới dạng raw bytes
            raw_bytes = request.get_data()
            
            if not raw_bytes:
                return jsonify({
                    "error": "Empty request body"
                }), 400
            
            frame = decode_frame_from_bytes(raw_bytes)
            
        else:
            return jsonify({
                "error": f"Unsupported Content-Type: {content_type}"
            }), 400
        
        # Kiểm tra frame có hợp lệ không
        if frame is None or frame.size == 0:
            return jsonify({
                "error": "Failed to decode frame"
            }), 400
        
        # Lưu frame gốc vào biến global để stream
        with frame_lock:
            latest_frame = frame.copy()
        
        # Xử lý frame và vẽ annotations
        result = process_frame(frame)
        
        # Lưu kết quả xử lý mới nhất
        with frame_lock:
            last_result = result
            # Tạo frame đã xử lý với annotations nếu cần
            latest_processed_frame = draw_annotations_on_frame(frame, result)
        
        # Tính thời gian xử lý
        processing_time = time.perf_counter() - start_time_processing
        
        # Log ngắn gọn
        face_detected = result['ear'] is not None
        status_flags = []
        if result['asleep']:
            status_flags.append('🚨 ASLEEP')
        if result['tired']:
            status_flags.append('⚠️ TIRED')
        if result['looking_away']:
            status_flags.append('👀 LOOKING_AWAY')
        if result['distracted']:
            status_flags.append('💭 DISTRACTED')
        
        status_str = ', '.join(status_flags) if status_flags else '✅ NORMAL'
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] "
              f"Face: {'✓' if face_detected else '✗'} | "
              f"EAR: {result['ear'] if result['ear'] else 'N/A'} | "
              f"Status: {status_str} | "
              f"Process: {processing_time*1000:.1f}ms")
        
        return jsonify(result), 200
        
    except Exception as e:
        print(f"❌ Error processing frame: {e}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            "error": str(e),
            "ear": None,
            "gaze": None,
            "perclos": 0.0,
            "roll": None,
            "pitch": None,
            "yaw": None,
            "asleep": False,
            "tired": False,
            "looking_away": False,
            "distracted": False,
            "fps": 0.0
        }), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """
    Endpoint để lấy thống kê server
    """
    global processed_frames_count, start_time
    
    uptime = time.perf_counter() - start_time
    
    return jsonify({
        "processed_frames": processed_frames_count,
        "uptime": int(uptime),
        "fps": fps_value
    }), 200


@app.route('/api/reset', methods=['POST'])
def reset_stats():
    """
    Endpoint để reset thống kê
    """
    global processed_frames_count, start_time, attention_scorer
    
    processed_frames_count = 0
    start_time = time.perf_counter()
    
    # Reset attention scorer
    t_now = time.perf_counter()
    attention_scorer = AttentionScorer(
        t_now=t_now,
        ear_thresh=EAR_THRESH,
        gaze_thresh=GAZE_THRESH,
        perclos_thresh=PERCLOS_THRESH,
        roll_thresh=ROLL_THRESH,
        pitch_thresh=PITCH_THRESH,
        yaw_thresh=YAW_THRESH,
        ear_time_thresh=EAR_TIME_THRESH,
        gaze_time_thresh=GAZE_TIME_THRESH,
        pose_time_thresh=POSE_TIME_THRESH,
        verbose=False,
    )
    
    print("🔄 Đã reset thống kê")
    
    return jsonify({
        "status": "ok",
        "message": "Đã reset thống kê"
    }), 200


@app.route('/api/history', methods=['GET', 'POST'])
def manage_history():
    """
    Endpoint để quản lý lịch sử
    - GET: Lấy danh sách lịch sử
    - POST: Thêm mục mới vào lịch sử
    """
    global history_data
    
    if request.method == 'GET':
        # Trả về lịch sử (mới nhất ở đầu)
        return jsonify({
            "history": list(reversed(history_data))
        }), 200
    
    elif request.method == 'POST':
        try:
            data = request.get_json()
            
            # Thêm timestamp nếu chưa có
            if 'timestamp' not in data:
                data['timestamp'] = datetime.now().isoformat()
            
            # Thêm vào lịch sử
            history_data.append(data)
            
            # Giới hạn kích thước lịch sử
            if len(history_data) > MAX_HISTORY_SIZE:
                history_data.pop(0)
            
            return jsonify({
                "status": "ok",
                "message": "Đã thêm vào lịch sử"
            }), 200
            
        except Exception as e:
            return jsonify({
                "error": str(e)
            }), 500


@app.route('/api/history/clear', methods=['POST'])
def clear_history():
    """
    Endpoint để xóa toàn bộ lịch sử
    """
    global history_data
    
    history_data = []
    
    print("🗑️  Đã xóa lịch sử")
    
    return jsonify({
        "status": "ok",
        "message": "Đã xóa lịch sử"
    }), 200


@app.route('/video_feed')
def video_feed():
    """
    Endpoint để stream video MJPEG từ Raspberry Pi
    """
    return Response(generate_mjpeg_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/latest_result', methods=['GET'])
def get_latest_result():
    """
    Endpoint để lấy kết quả xử lý mới nhất (cho frontend polling)
    """
    global last_result
    
    if last_result is None:
        return jsonify({
            "ear": None,
            "gaze": None,
            "perclos": 0.0,
            "roll": None,
            "pitch": None,
            "yaw": None,
            "asleep": False,
            "tired": False,
            "looking_away": False,
            "distracted": False,
            "fps": 0.0
        }), 200
    
    return jsonify(last_result), 200


@app.route('/logout')
def logout():
    """
    Endpoint logout (placeholder - chưa có authentication)
    """
    return render_template('index.html')


# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚗 DRIVER STATE DETECTION SERVER")
    print("="*60)
    print(f"📍 Endpoints:")
    print(f"   GET  /api/health        - Health check")
    print(f"   POST /api/process_frame - Xử lý frame")
    print(f"\n⚙️  Thông số:")
    print(f"   EAR Threshold:      {EAR_THRESH}")
    print(f"   Gaze Threshold:     {GAZE_THRESH}")
    print(f"   PERCLOS Threshold:  {PERCLOS_THRESH}")
    print(f"   Roll/Pitch/Yaw:     {ROLL_THRESH}°/{PITCH_THRESH}°/{YAW_THRESH}°")
    print(f"\n🔔 Alert Throttling:")
    print(f"   ASLEEP:             Gửi ngay lập tức (nguy hiểm)")
    print(f"   TIRED:              {ALERT_THROTTLE_SECONDS}s mỗi lần")
    print(f"   LOOKING_AWAY:       {ALERT_THROTTLE_SECONDS}s mỗi lần")
    print(f"   DISTRACTED:         {ALERT_THROTTLE_SECONDS}s mỗi lần")
    print("="*60 + "\n")
    
    # Chạy Flask server
    # host='0.0.0.0' để cho phép kết nối từ các máy khác trong mạng
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)


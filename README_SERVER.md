# Driver State Detection Server

Server với giao diện web hiện đại để nhận dữ liệu từ client và xử lý AI phát hiện trạng thái tài xế.

## Tính năng

- ✅ Giao diện web hiện đại, responsive
- ✅ Nhận video stream từ webcam client
- ✅ Xử lý AI real-time với MediaPipe
- ✅ Hiển thị các metrics: EAR, Gaze, PERCLOS, Head Pose
- ✅ Cảnh báo trạng thái: Ngủ gật, Mệt mỏi, Nhìn đi chỗ khác, Mất tập trung
- ✅ Thống kê FPS và số frames đã xử lý
- ✅ API RESTful để tích hợp với các ứng dụng khác

## Cài đặt

### 1. Cài đặt dependencies

```bash
# Sử dụng Python 3.11 (khuyến nghị)
py -3.11 -m pip install -r requirements.txt
```

### 2. Chạy server

```bash
# Sử dụng Python 3.11
py -3.11 server.py
```

Server sẽ chạy tại: `http://localhost:5000`

## Sử dụng

1. Mở trình duyệt và truy cập `http://localhost:5000`
2. Click nút "Bắt đầu" để bắt đầu stream từ webcam
3. Hệ thống sẽ tự động xử lý và hiển thị kết quả real-time

## API Endpoints

### `GET /api/health`
Kiểm tra trạng thái server

**Response:**
```json
{
  "status": "healthy",
  "ai_processor_ready": true,
  "uptime": 123.45
}
```

### `POST /api/process_frame`
Xử lý một frame từ client

**Request Body:**
```json
{
  "frame": "data:image/jpeg;base64,..."
}
```

**Response:**
```json
{
  "ear": 0.25,
  "gaze": 0.012,
  "roll": 5.2,
  "pitch": -3.1,
  "yaw": 2.5,
  "asleep": false,
  "looking_away": false,
  "distracted": false,
  "tired": false,
  "perclos": 0.15,
  "face_detected": true,
  "fps": 10.5,
  "processed_frame": "data:image/jpeg;base64,...",
  "timestamp": "2025-12-13T21:15:30.123456"
}
```

### `GET /api/stats`
Lấy thống kê xử lý

**Response:**
```json
{
  "total_frames": 1000,
  "processed_frames": 950,
  "fps": 9.5,
  "uptime": 100.0,
  "last_update": 1702482930.123
}
```

### `POST /api/reset`
Reset thống kê và AI processor

## Cấu trúc thư mục

```
.
├── server.py                 # Flask server chính
├── ai_processor.py           # Module xử lý AI
├── templates/
│   └── index.html            # Giao diện web
├── static/
│   ├── css/
│   │   └── style.css         # CSS styling
│   └── js/
│       └── app.js            # JavaScript frontend
└── driver_state_detection/   # Module phát hiện trạng thái tài xế
```

## Lưu ý

- Server yêu cầu Python 3.11 hoặc 3.12 (không hỗ trợ Python 3.14)
- Cần có webcam để test
- MediaPipe yêu cầu camera access permission từ browser

## Troubleshooting

### Lỗi "AI Processor chưa được khởi tạo"
- Kiểm tra xem các file trong `driver_state_detection/` có đầy đủ không
- Kiểm tra đường dẫn `camera_params.json` nếu có

### Lỗi import module
- Đảm bảo đang chạy từ thư mục root của project
- Kiểm tra Python version: `py -3.11 --version`

### Camera không hoạt động
- Kiểm tra quyền truy cập camera trong browser
- Thử refresh trang và cho phép camera access


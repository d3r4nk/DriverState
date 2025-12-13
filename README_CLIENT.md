# Client cho Raspberry Pi

Client để gửi video stream từ webcam Raspberry Pi đến server xử lý AI.

## Cài đặt trên Raspberry Pi

### 1. Cài đặt dependencies

```bash
pip3 install opencv-python numpy requests
```

Hoặc nếu dùng requirements.txt:

```bash
pip3 install -r requirements.txt
```

### 2. Chạy client

```bash
# Kết nối đến server mặc định (localhost:5000)
python3 client.py

# Kết nối đến server khác
python3 client.py --server http://192.168.1.100:5000

# Chỉ định camera và FPS
python3 client.py --server http://192.168.1.100:5000 --camera 0 --fps 10
```

## Tham số

- `--server`: URL của server (mặc định: http://localhost:5000)
- `--camera`: Index của camera (mặc định: 0)
- `--fps`: Số frames gửi mỗi giây (mặc định: 10)

## Ví dụ sử dụng

### Kết nối đến server trên mạng LAN

```bash
python3 client.py --server http://192.168.1.100:5000
```

### Sử dụng camera USB thứ 2

```bash
python3 client.py --camera 1
```

### Gửi với tốc độ 5 FPS (tiết kiệm băng thông)

```bash
python3 client.py --fps 5
```

## Lưu ý

- Đảm bảo server đã chạy trước khi khởi động client
- Kiểm tra kết nối mạng giữa Raspberry Pi và server
- FPS cao hơn sẽ tốn nhiều băng thông hơn
- Client sẽ tự động resize frame nếu quá lớn để tối ưu băng thông

## Sử dụng Camera USB

Client đã được tối ưu cho camera USB trên Raspberry Pi:

```bash
# Sử dụng camera USB mặc định (thường là /dev/video0)
python3 client.py --server http://192.168.1.100:5000 --camera 0

# Nếu có nhiều camera USB, thử các index khác
python3 client.py --server http://192.168.1.100:5000 --camera 1
python3 client.py --server http://192.168.1.100:5000 --camera 2
```

### Kiểm tra camera USB

Trước khi chạy, kiểm tra camera USB đã được nhận diện:

```bash
# Liệt kê các camera USB
ls -l /dev/video*

# Kiểm tra thông tin camera
v4l2-ctl --list-devices
```

Nếu thấy `/dev/video0`, `/dev/video1`, v.v. nghĩa là camera đã được nhận diện.

## Troubleshooting

### Lỗi "Không thể mở camera"
- Kiểm tra camera đã được kết nối chưa
- Thử đổi `--camera` sang index khác (0, 1, 2...)
- Kiểm tra quyền truy cập camera: `ls -l /dev/video*`

### Lỗi "Không thể kết nối đến server"
- Kiểm tra server đã chạy chưa
- Kiểm tra địa chỉ IP và port của server
- Kiểm tra firewall có chặn kết nối không
- Thử ping server từ Raspberry Pi

### FPS thấp
- Giảm FPS bằng tham số `--fps`
- Kiểm tra băng thông mạng
- Kiểm tra hiệu năng server


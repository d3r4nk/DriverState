"""
Client đơn giản cho Raspberry Pi để gửi frame đến server

Tính năng:
- Capture frame từ USB webcam
- Resize về 640x480
- Encode thành JPEG
- Gửi đến server qua HTTP POST
- Xử lý kết quả và hiển thị (optional)

Author: Driver State Detection
Date: 2025
"""

import argparse
import time
from datetime import datetime
from threading import Thread

import cv2
import requests

# GPIO cho Raspberry Pi (optional - sẽ check nếu có)
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    print("⚠️  RPi.GPIO không có - Chạy ở chế độ không có buzzer")
    GPIO_AVAILABLE = False

# ============================================================================
# Configuration
# ============================================================================

DEFAULT_SERVER_URL = 'http://192.168.1.96:5000'  # Thay đổi IP này
DEFAULT_FPS = 10  # FPS mục tiêu
DEFAULT_QUALITY = 85  # JPEG quality (0-100)

# GPIO Configuration
BUZZER_PIN = 17  # GPIO 17 cho buzzer
BUZZER_DURATION = 5  # Buzzer kêu 5 giây khi có cảnh báo

# ============================================================================
# Main Client Class
# ============================================================================

class DriverStateClient:
    """Client để gửi frame đến Driver State Detection Server"""
    
    def __init__(self, server_url, target_fps=10, jpeg_quality=85, show_video=False, enable_buzzer=True):
        """
        Khởi tạo client
        
        Args:
            server_url: URL của server (ví dụ: http://192.168.1.100:5000)
            target_fps: FPS mục tiêu để gửi frame
            jpeg_quality: Chất lượng JPEG (0-100)
            show_video: Có hiển thị video không (False cho Raspberry Pi headless)
            enable_buzzer: Có bật buzzer cảnh báo không (True)
        """
        self.server_url = server_url.rstrip('/')
        self.process_url = f'{self.server_url}/api/process_frame'
        self.health_url = f'{self.server_url}/api/health'
        
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self.jpeg_quality = jpeg_quality
        self.show_video = show_video
        self.enable_buzzer = enable_buzzer and GPIO_AVAILABLE
        
        self.cap = None
        self.running = False
        
        # Statistics
        self.frame_count = 0
        self.error_count = 0
        self.total_latency = 0
        
        # GPIO/Buzzer
        self.buzzer_active = False
        self.buzzer_thread = None
        
        # Setup GPIO nếu có
        if self.enable_buzzer:
            self.setup_gpio()
        
    def setup_gpio(self):
        """Setup GPIO cho buzzer"""
        try:
            GPIO.setmode(GPIO.BCM)  # Sử dụng BCM numbering
            GPIO.setwarnings(False)
            GPIO.setup(BUZZER_PIN, GPIO.OUT)
            GPIO.output(BUZZER_PIN, GPIO.LOW)  # Tắt buzzer ban đầu
            print(f"✅ Đã setup GPIO {BUZZER_PIN} cho buzzer")
        except Exception as e:
            print(f"⚠️  Không thể setup GPIO: {e}")
            self.enable_buzzer = False
    
    def activate_buzzer(self, duration=BUZZER_DURATION):
        """
        Kích hoạt buzzer trong thời gian nhất định
        
        Args:
            duration: Thời gian kêu (giây)
        """
        if not self.enable_buzzer or self.buzzer_active:
            return
        
        def buzzer_thread_func():
            try:
                self.buzzer_active = True
                print(f"🔊 BUZZER ON ({duration}s)")
                
                GPIO.output(BUZZER_PIN, GPIO.HIGH)
                time.sleep(duration)
                GPIO.output(BUZZER_PIN, GPIO.LOW)
                
                print(f"🔇 BUZZER OFF")
                self.buzzer_active = False
                
            except Exception as e:
                print(f"⚠️  Lỗi buzzer: {e}")
                self.buzzer_active = False
        
        # Chạy buzzer trong thread riêng để không block
        self.buzzer_thread = Thread(target=buzzer_thread_func, daemon=True)
        self.buzzer_thread.start()
    
    def check_server(self):
        """Kiểm tra server có sẵn sàng không"""
        print(f"🔍 Checking server: {self.server_url}")
        
        try:
            response = requests.get(self.health_url, timeout=3)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Server sẵn sàng: {data.get('message')}")
                return True
            else:
                print(f"❌ Server trả về status code: {response.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            print(f"❌ Không thể kết nối đến server")
            return False
        except Exception as e:
            print(f"❌ Lỗi: {e}")
            return False
    
    def init_camera(self, camera_id=0, width=640, height=480):
        """
        Khởi tạo camera
        
        Args:
            camera_id: ID của camera (0 cho camera mặc định)
            width: Chiều rộng frame
            height: Chiều cao frame
        """
        print(f"📷 Đang khởi tạo camera {camera_id}...")
        
        self.cap = cv2.VideoCapture(camera_id)
        
        if not self.cap.isOpened():
            print(f"❌ Không thể mở camera {camera_id}")
            return False
        
        # Set resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        
        # Đọc thử một frame
        ret, frame = self.cap.read()
        if not ret:
            print(f"❌ Không thể đọc frame từ camera")
            return False
        
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        print(f"✅ Camera đã sẵn sàng: {actual_width}x{actual_height}")
        
        return True
    
    def send_frame(self, frame):
        """
        Gửi frame đến server
        
        Args:
            frame: numpy array (BGR format)
            
        Returns:
            dict hoặc None: Kết quả từ server
        """
        # Encode frame thành JPEG
        _, buffer = cv2.imencode('.jpg', frame, 
                                 [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        
        try:
            # Gửi request
            start_time = time.time()
            response = requests.post(
                self.process_url,
                data=buffer.tobytes(),
                headers={'Content-Type': 'application/octet-stream'},
                timeout=5
            )
            latency = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                result = response.json()
                self.total_latency += latency
                return result, latency
            else:
                print(f"⚠️  Server error: {response.status_code}")
                self.error_count += 1
                return None, latency
                
        except requests.exceptions.Timeout:
            print(f"⚠️  Request timeout")
            self.error_count += 1
            return None, 0
        except requests.exceptions.ConnectionError:
            print(f"⚠️  Connection error")
            self.error_count += 1
            return None, 0
        except Exception as e:
            print(f"⚠️  Error: {e}")
            self.error_count += 1
            return None, 0
    
    def process_result(self, result):
        """
        Xử lý kết quả từ server
        
        Args:
            result: dict kết quả từ server
        """
        # Log các trạng thái quan trọng
        alerts = []
        has_critical_alert = False
        
        if result.get('asleep'):
            alerts.append('😴 ASLEEP')
            has_critical_alert = True
        if result.get('tired'):
            alerts.append('😪 TIRED')
            has_critical_alert = True
        if result.get('looking_away'):
            alerts.append('👀 LOOKING_AWAY')
            has_critical_alert = True
        if result.get('distracted'):
            alerts.append('💭 DISTRACTED')
            has_critical_alert = True
        
        if alerts:
            alert_str = ' | '.join(alerts)
            print(f"🚨 ALERT: {alert_str}")
            
            # Kích hoạt buzzer nếu có cảnh báo (bất kỳ loại nào)
            if has_critical_alert and self.enable_buzzer:
                self.activate_buzzer(duration=BUZZER_DURATION)
    
    def run(self):
        """Chạy client chính"""
        print("\n" + "="*60)
        print("🚗 DRIVER STATE DETECTION CLIENT")
        print("="*60)
        print(f"🎯 Server: {self.server_url}")
        print(f"📊 Target FPS: {self.target_fps}")
        print(f"🎨 JPEG Quality: {self.jpeg_quality}")
        print(f"📺 Show Video: {self.show_video}")
        print(f"🔊 Buzzer: {'Enabled (GPIO {})'.format(BUZZER_PIN) if self.enable_buzzer else 'Disabled'}")
        if self.enable_buzzer:
            print(f"   Duration: {BUZZER_DURATION}s khi có cảnh báo")
        print("="*60)
        
        # Check server
        if not self.check_server():
            print("\n❌ Server không sẵn sàng. Thoát.")
            return False
        
        # Init camera
        if not self.init_camera():
            print("\n❌ Camera không sẵn sàng. Thoát.")
            return False
        
        print(f"\n✅ Bắt đầu gửi frames...")
        print(f"💡 Nhấn Ctrl+C để dừng\n")
        
        self.running = True
        last_frame_time = 0
        
        try:
            while self.running:
                # Kiểm tra thời gian để giữ FPS mục tiêu
                current_time = time.time()
                if current_time - last_frame_time < self.frame_interval:
                    time.sleep(0.01)  # Sleep ngắn để không waste CPU
                    continue
                
                last_frame_time = current_time
                
                # Capture frame
                ret, frame = self.cap.read()
                if not ret:
                    print("⚠️  Không đọc được frame")
                    continue
                
                # Resize về 640x480 nếu cần
                if frame.shape[1] != 640 or frame.shape[0] != 480:
                    frame = cv2.resize(frame, (640, 480))
                
                # Gửi frame đến server
                result, latency = self.send_frame(frame)
                
                if result:
                    self.frame_count += 1
                    
                    # Xử lý kết quả
                    self.process_result(result)
                    
                    # In thông tin (mỗi 30 frames)
                    if self.frame_count % 30 == 0:
                        avg_latency = self.total_latency / self.frame_count
                        error_rate = (self.error_count / (self.frame_count + self.error_count)) * 100
                        
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                              f"Frames: {self.frame_count} | "
                              f"Avg Latency: {avg_latency:.1f}ms | "
                              f"Error Rate: {error_rate:.1f}%")
                    
                    # Hiển thị video nếu được bật
                    if self.show_video:
                        # Vẽ thông tin lên frame
                        ear = result.get('ear')
                        if ear:
                            cv2.putText(frame, f"EAR: {ear:.3f}", 
                                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 
                                       0.7, (255, 255, 255), 2)
                        
                        cv2.putText(frame, f"Latency: {latency:.0f}ms", 
                                   (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 
                                   0.7, (255, 255, 255), 2)
                        
                        # Vẽ cảnh báo
                        if result.get('asleep'):
                            cv2.putText(frame, "ASLEEP!", (10, 100), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 
                                       1, (0, 0, 255), 2)
                        
                        cv2.imshow('Driver State Detection', frame)
                        
                        # Nhấn 'q' để thoát
                        if cv2.waitKey(1) & 0xFF == ord('q'):
                            break
        
        except KeyboardInterrupt:
            print("\n\n⏸️  Dừng bởi người dùng (Ctrl+C)")
        
        finally:
            self.cleanup()
        
        return True
    
    def cleanup(self):
        """Dọn dẹp tài nguyên"""
        print("\n🧹 Đang dọn dẹp...")
        
        self.running = False
        
        # Tắt buzzer nếu đang kêu
        if self.enable_buzzer:
            try:
                GPIO.output(BUZZER_PIN, GPIO.LOW)
                GPIO.cleanup()
                print("🔇 Đã tắt buzzer và cleanup GPIO")
            except Exception as e:
                print(f"⚠️  Lỗi cleanup GPIO: {e}")
        
        if self.cap:
            self.cap.release()
        
        if self.show_video:
            cv2.destroyAllWindows()
        
        # In thống kê cuối
        print("\n" + "="*60)
        print("📊 THỐNG KÊ")
        print("="*60)
        print(f"Frames processed:  {self.frame_count}")
        print(f"Errors:            {self.error_count}")
        
        if self.frame_count > 0:
            avg_latency = self.total_latency / self.frame_count
            success_rate = (self.frame_count / (self.frame_count + self.error_count)) * 100
            
            print(f"Average latency:   {avg_latency:.1f}ms")
            print(f"Success rate:      {success_rate:.1f}%")
        
        print("="*60)
        print("👋 Tạm biệt!\n")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Client cho Driver State Detection Server (Raspberry Pi)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python raspberry_pi_client.py
  python raspberry_pi_client.py --server http://192.168.1.100:5000
  python raspberry_pi_client.py --fps 15 --quality 90
  python raspberry_pi_client.py --show-video
  python raspberry_pi_client.py --camera 1
        """
    )
    
    parser.add_argument('--server', type=str, default=DEFAULT_SERVER_URL,
                        help=f'URL của server (mặc định: {DEFAULT_SERVER_URL})')
    parser.add_argument('--fps', type=int, default=DEFAULT_FPS,
                        help=f'FPS mục tiêu (mặc định: {DEFAULT_FPS})')
    parser.add_argument('--quality', type=int, default=DEFAULT_QUALITY,
                        help=f'JPEG quality 0-100 (mặc định: {DEFAULT_QUALITY})')
    parser.add_argument('--camera', type=int, default=0,
                        help='Camera ID (mặc định: 0)')
    parser.add_argument('--show-video', action='store_true',
                        help='Hiển thị video (mặc định: không)')
    parser.add_argument('--width', type=int, default=640,
                        help='Frame width (mặc định: 640)')
    parser.add_argument('--height', type=int, default=480,
                        help='Frame height (mặc định: 480)')
    parser.add_argument('--no-buzzer', action='store_true',
                        help='Tắt buzzer cảnh báo (mặc định: bật)')
    
    args = parser.parse_args()
    
    # Tạo client
    client = DriverStateClient(
        server_url=args.server,
        target_fps=args.fps,
        jpeg_quality=args.quality,
        show_video=args.show_video,
        enable_buzzer=not args.no_buzzer
    )
    
    # Chạy
    success = client.run()
    
    return 0 if success else 1


if __name__ == '__main__':
    import sys
    sys.exit(main())


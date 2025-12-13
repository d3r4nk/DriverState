#!/usr/bin/env python3
"""
Client cho Raspberry Pi để gửi video stream từ webcam đến server
Sử dụng: python3 client.py --server http://localhost:5000
"""

import argparse
import time
import base64
import cv2
import requests
import numpy as np
from datetime import datetime

class DriverStateClient:
    def __init__(self, server_url, camera_index=0, fps=10):
        """
        Khởi tạo client
        
        Parameters:
        -----------
        server_url: str
            URL của server (ví dụ: http://192.168.1.100:5000)
        camera_index: int
            Index của camera (mặc định: 0)
        fps: int
            Số frames gửi mỗi giây (mặc định: 10)
        """
        self.server_url = server_url.rstrip('/')
        self.camera_index = camera_index
        self.fps = fps
        self.frame_interval = 1.0 / fps
        self.cap = None
        self.running = False
        
    def connect(self):
        """Kết nối đến camera USB"""
        print(f"Đang kết nối đến camera USB (index {self.camera_index})...")
        
        # Thử sử dụng V4L2 backend cho camera USB trên Linux/Raspberry Pi
        try:
            # Trên Raspberry Pi/Linux, thử dùng V4L2 backend
            self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
        except:
            # Nếu không được, dùng backend mặc định
            self.cap = cv2.VideoCapture(self.camera_index)
        
        if not self.cap.isOpened():
            raise Exception(f"Không thể mở camera USB {self.camera_index}. "
                          f"Hãy kiểm tra:\n"
                          f"  - Camera đã được kết nối chưa\n"
                          f"  - Thử đổi index: --camera 0, 1, 2...\n"
                          f"  - Kiểm tra: ls -l /dev/video*")
        
        # Thiết lập độ phân giải cho camera USB
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # Đợi camera khởi động (quan trọng với camera USB)
        time.sleep(0.5)
        
        # Kiểm tra lại sau khi thiết lập
        actual_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        print(f"Đã kết nối camera USB thành công!")
        print(f"  - Độ phân giải: {actual_width}x{actual_height}")
        print(f"  - FPS: {self.fps} frames/giây")
        
    def check_server(self):
        """Kiểm tra server có sẵn sàng không"""
        try:
            response = requests.get(f"{self.server_url}/api/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                print(f"Server đã sẵn sàng: {data}")
                return True
        except Exception as e:
            print(f"Không thể kết nối đến server: {e}")
        return False
    
    def encode_frame(self, frame):
        """Encode frame thành base64"""
        # Resize frame nếu quá lớn để giảm băng thông
        height, width = frame.shape[:2]
        if width > 640:
            scale = 640 / width
            new_width = int(width * scale)
            new_height = int(height * scale)
            frame = cv2.resize(frame, (new_width, new_height))
        
        # Encode thành JPEG
        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        frame_bytes = buffer.tobytes()
        frame_base64 = base64.b64encode(frame_bytes).decode('utf-8')
        return frame_base64
    
    def send_frame(self, frame):
        """Gửi frame đến server"""
        try:
            frame_base64 = self.encode_frame(frame)
            
            payload = {
                'frame': f'data:image/jpeg;base64,{frame_base64}'
            }
            
            response = requests.post(
                f"{self.server_url}/api/process_frame",
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                return result
            else:
                print(f"Lỗi từ server: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            print("Timeout khi gửi frame")
            return None
        except Exception as e:
            print(f"Lỗi khi gửi frame: {e}")
            return None
    
    def process_result(self, result):
        """Xử lý và hiển thị kết quả từ server"""
        if result is None:
            return
        
        # In thông tin cơ bản
        status = []
        if result.get('asleep'):
            status.append('NGỦ GẬT')
        if result.get('tired'):
            status.append('MỆT MỎI')
        if result.get('looking_away'):
            status.append('NHÌN ĐI CHỖ KHÁC')
        if result.get('distracted'):
            status.append('MẤT TẬP TRUNG')
        
        if status:
            print(f"[CẢNH BÁO] {', '.join(status)}")
        
        # In metrics nếu có
        if result.get('ear') is not None:
            print(f"EAR: {result['ear']:.3f}", end=' | ')
        if result.get('gaze') is not None:
            print(f"Gaze: {result['gaze']:.3f}", end=' | ')
        if result.get('perclos') is not None:
            print(f"PERCLOS: {result['perclos']:.3f}", end=' | ')
        if result.get('fps'):
            print(f"FPS: {result['fps']}")
    
    def run(self):
        """Chạy client và gửi frames"""
        if not self.check_server():
            print("Server không sẵn sàng. Thoát.")
            return
        
        self.connect()
        self.running = True
        
        print(f"Bắt đầu gửi frames đến {self.server_url}")
        print(f"FPS: {self.fps} frames/giây")
        print("Nhấn Ctrl+C để dừng")
        print("-" * 50)
        
        frame_count = 0
        start_time = time.time()
        last_frame_time = time.time()
        
        try:
            while self.running:
                ret, frame = self.cap.read()
                
                if not ret:
                    print("Không thể đọc frame từ camera")
                    break
                
                # Kiểm tra thời gian để đảm bảo FPS
                current_time = time.time()
                elapsed = current_time - last_frame_time
                
                if elapsed >= self.frame_interval:
                    # Gửi frame đến server
                    result = self.send_frame(frame)
                    
                    if result:
                        frame_count += 1
                        self.process_result(result)
                    
                    last_frame_time = current_time
                
                # Hiển thị frame local (tùy chọn)
                # cv2.imshow('Raspberry Pi Camera', frame)
                # if cv2.waitKey(1) & 0xFF == ord('q'):
                #     break
                
                # Sleep một chút để không chiếm quá nhiều CPU
                time.sleep(0.01)
                
        except KeyboardInterrupt:
            print("\nĐang dừng client...")
        finally:
            self.stop()
    
    def stop(self):
        """Dừng client"""
        self.running = False
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()
        print("Client đã dừng")

def main():
    parser = argparse.ArgumentParser(description='Client gửi video stream từ Raspberry Pi đến server')
    parser.add_argument(
        '--server',
        type=str,
        default='http://localhost:5000',
        help='URL của server (mặc định: http://localhost:5000)'
    )
    parser.add_argument(
        '--camera',
        type=int,
        default=0,
        help='Index của camera (mặc định: 0)'
    )
    parser.add_argument(
        '--fps',
        type=int,
        default=10,
        help='Số frames gửi mỗi giây (mặc định: 10)'
    )
    
    args = parser.parse_args()
    
    client = DriverStateClient(
        server_url=args.server,
        camera_index=args.camera,
        fps=args.fps
    )
    
    try:
        client.run()
    except Exception as e:
        print(f"Lỗi: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()


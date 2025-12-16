"""
Script test buzzer trên Raspberry Pi
Dùng để kiểm tra buzzer có hoạt động không

Kết nối:
- Buzzer (+) → GPIO 17 (Pin 11)
- Buzzer (-) → GND (Pin 6, 9, 14, 20, 25, 30, 34, 39)

Chạy: python buzzer_setup.py
"""

import time

try:
    import RPi.GPIO as GPIO
    
    BUZZER_PIN = 17
    
    print("="*60)
    print("🔊 BUZZER TEST - RASPBERRY PI")
    print("="*60)
    print(f"GPIO Pin: {BUZZER_PIN}")
    print(f"Kết nối:")
    print(f"  Buzzer (+) → GPIO 17 (Physical Pin 11)")
    print(f"  Buzzer (-) → GND (Physical Pin 6, 9, 14, etc.)")
    print("="*60)
    
    # Setup GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(BUZZER_PIN, GPIO.OUT)
    
    print("\n✅ GPIO đã setup thành công")
    print("\n🔊 Test 1: Kêu 1 giây...")
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    time.sleep(1)
    GPIO.output(BUZZER_PIN, GPIO.LOW)
    print("✅ Test 1 hoàn thành")
    
    time.sleep(1)
    
    print("\n🔊 Test 2: Kêu 5 giây (như cảnh báo thật)...")
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    for i in range(5, 0, -1):
        print(f"   {i}s...", end='\r')
        time.sleep(1)
    GPIO.output(BUZZER_PIN, GPIO.LOW)
    print("✅ Test 2 hoàn thành      ")
    
    time.sleep(1)
    
    print("\n🔊 Test 3: Kêu 3 lần (mỗi lần 0.5s)...")
    for i in range(3):
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(0.5)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        time.sleep(0.5)
        print(f"   Lần {i+1}/3 hoàn thành")
    print("✅ Test 3 hoàn thành")
    
    # Cleanup
    GPIO.cleanup()
    
    print("\n" + "="*60)
    print("✅ TẤT CẢ TESTS THÀNH CÔNG!")
    print("="*60)
    print("\nBuzzer hoạt động tốt!")
    print("Bạn có thể chạy client với buzzer: python raspberry_pi_client.py --server http://SERVER_IP:5000")
    print("\n")

except ImportError:
    print("❌ Lỗi: RPi.GPIO không có")
    print("Cài đặt: sudo apt-get install python3-rpi.gpio")
    print("Hoặc: pip install RPi.GPIO")

except Exception as e:
    print(f"\n❌ Lỗi: {e}")
    print("\nKiểm tra:")
    print("  1. Kết nối phần cứng đúng chưa?")
    print("  2. Có chạy với quyền sudo không? (sudo python buzzer_setup.py)")
    print("  3. GPIO có bị sử dụng bởi process khác không?")
    
    try:
        GPIO.cleanup()
    except:
        pass


#!/usr/bin/env python3
import os
import sys

# Force RPi.GPIO to use BCM mode before import
os.environ['GPIOZERO_PIN_FACTORY'] = 'rpigpio'

import warnings
warnings.filterwarnings("ignore")

try:
    import RPi.GPIO as GPIO
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.cleanup()
    except:
        pass
except ImportError:
    print("Installing RPi.GPIO...")
    os.system("pip3 install RPi.GPIO")
    import RPi.GPIO as GPIO

import time
import subprocess
import cv2
import numpy as np
from datetime import datetime
import threading

# GPIO Configuration
SERVO_PIN = 4
TRIGGER_PIN = 17
ECHO_PIN = 27

# Detection parameters
ANIMAL_DETECTION_DISTANCE = 50  # cm - distance to trigger detection
COLOR_THRESHOLD = 10  # Minimum percentage of color pixels to trigger servo

class AnimalColorDetector:
    def __init__(self, target_color, cycle_time):
        # Initialize GPIO
        self.setup_gpio()
        
        # Store settings
        self.target_color = target_color.lower()
        self.cycle_time = cycle_time
        
        # SERVO SETTINGS - Using 7% and 8% for slower, symmetrical rotation
        self.servo_stop = 7.5      # Stop position
        self.servo_open = 7.0      # Open speed (one direction, 0.5% below stop)
        self.servo_close = 8.0     # Close speed (opposite direction, 0.5% above stop)
        self.rotation_time = 1.0   # 2 seconds each way (you may need to increase this for slower speed)
        
        # Live view flag
        self.live_view_active = False
        
        # Initialize servo
        self.servo_pwm = None
        try:
            self.servo_pwm = GPIO.PWM(SERVO_PIN, 50)
            self.servo_pwm.start(0)
            
            # Make sure servo is stopped initially
            self.stop_servo()
            print(f"📐 Servo initialized with slower symmetrical speeds:")
            print(f"   Open (Duty Cycle):  {self.servo_open}%")
            print(f"   Close (Duty Cycle): {self.servo_close}%")
            print(f"   Rotation time each way: {self.rotation_time} seconds (may need calibration)")
        except Exception as e:
            print(f"⚠️ Servo initialization warning: {e}")
        
        # Define color ranges
        self.setup_color_ranges()
        
        # Create directory for images
        self.image_dir = "captured_images"
        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir)
        
        print(f"✅ System ready for {self.target_color.upper()} detection!")
    
    def setup_gpio(self):
        """Setup GPIO pins"""
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        
        # Force cleanup first
        for pin in [SERVO_PIN, TRIGGER_PIN, ECHO_PIN]:
            try:
                GPIO.cleanup(pin)
            except:
                pass
        
        time.sleep(0.5)
        
        # Setup pins
        GPIO.setup(TRIGGER_PIN, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(ECHO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(SERVO_PIN, GPIO.OUT)
    
    def setup_color_ranges(self):
        """Setup color detection ranges"""
        self.all_color_ranges = {
            'brown': [
                [(10, 50, 50), (20, 255, 200)],
                [(5, 40, 40), (15, 200, 150)],
                [(8, 60, 30), (22, 255, 180)],
                [(15, 30, 30), (25, 200, 200)]
            ],
            'black': [
                [(0, 0, 0), (180, 255, 30)],
                [(0, 0, 0), (180, 30, 50)]
            ],
            'white': [
                [(0, 0, 200), (180, 30, 255)],
                [(0, 0, 150), (180, 20, 255)]
            ],
            'gray': [
                [(0, 0, 50), (180, 30, 150)]
            ],
            'orange': [
                [(5, 100, 100), (15, 255, 255)],
                [(10, 100, 100), (20, 255, 255)]
            ],
            'yellow': [
                [(20, 100, 100), (30, 255, 255)],
                [(25, 50, 50), (35, 255, 255)]
            ],
            'red': [
                [(0, 100, 100), (10, 255, 255)],
                [(170, 100, 100), (180, 255, 255)]
            ],
            'green': [
                [(40, 50, 50), (80, 255, 255)],
                [(35, 40, 40), (85, 255, 200)]
            ],
            'blue': [
                [(100, 50, 50), (130, 255, 255)],
                [(90, 50, 50), (140, 255, 255)]
            ],
            'tan': [
                [(15, 20, 50), (25, 100, 200)],
                [(10, 15, 60), (20, 60, 180)]
            ]
        }
        
        if self.target_color in self.all_color_ranges:
            self.color_ranges = self.all_color_ranges[self.target_color]
        else:
            self.target_color = 'brown'
            self.color_ranges = self.all_color_ranges['brown']
    
    def stop_servo(self):
        """Stop the continuous rotation servo"""
        if self.servo_pwm:
            self.servo_pwm.ChangeDutyCycle(self.servo_stop)
            time.sleep(0.1)
            self.servo_pwm.ChangeDutyCycle(0)
    
    def dispense_food(self):
        """Dispense food - rotate forward 2s, then reverse 2s"""
        print(f"🍽️ Dispensing food...")
        
        if self.servo_pwm:
            # OPEN with duty cycle 7.0
            print(f"   📂 Opening (duty: {self.servo_open}%)...")
            self.servo_pwm.ChangeDutyCycle(self.servo_open)
            time.sleep(self.rotation_time)
            self.stop_servo()
            
            time.sleep(0.2)
            
            # CLOSE with duty cycle 8.0
            print(f"   📁 Closing (duty: {self.servo_close}%)...")
            self.servo_pwm.ChangeDutyCycle(self.servo_close)
            time.sleep(self.rotation_time)
            self.stop_servo()
            
        print("✅ Dispensing complete. Feeder returned to start.")
        
    def live_camera_view(self):
        """Show live camera feed in a preview window"""
        print("\n📹 LIVE CAMERA VIEW")
        print("="*50)
        
        try:
            print("Starting camera preview...")
            print("Close the preview window (e.g., press 'X') to return.")
            
            subprocess.run([
                'rpicam-hello',
                '-t', '0',
                '--width', '800',
                '--height', '600'
            ])
            print("\nPreview window closed.")
            
        except FileNotFoundError:
            print("❌ 'rpicam-hello' not found. Cannot open live view.")
        except Exception as e:
            print(f"❌ Error starting live view: {e}")
            
    def manual_control_menu(self):
        """Interactive manual control menu"""
        while True:
            print("\n" + "="*50)
            print("🎮 MANUAL CONTROL MENU")
            print("="*50)
            print("  1. Dispense Food Now")
            print("  2. Live Camera View")
            print("  3. Test Servo (Open/Close)")
            print("  4. Check Distance Sensor")
            print("  5. Take Photo")
            print("  6. Back to Main Menu")
            print("="*50)
            
            choice = input("\nSelect option (1-6): ").strip()
            
            if choice == '1':
                self.dispense_food()
                input("\nPress ENTER to continue...")
            elif choice == '2':
                self.live_camera_view()
            elif choice == '3':
                self.test_servo_movement()
            elif choice == '4':
                self.test_distance_sensor()
            elif choice == '5':
                self.take_snapshot()
            elif choice == '6':
                break
            else:
                print("❌ Invalid choice")
                
    def test_servo_movement(self):
        print("\n🔧 Testing servo movement...")
        print(f"   Open duty: {self.servo_open}%")
        print(f"   Close duty: {self.servo_close}%")
        self.dispense_food()
        
    def test_distance_sensor(self):
        print("\n📏 Testing distance sensor...")
        print("   Press Ctrl+C to stop\n")
        try:
            while True:
                distance = self.get_distance()
                if distance:
                    bar = "█" * int(distance / 5) if distance < 100 else "█" * 20
                    print(f"   Distance: {distance:6.2f} cm [{bar}]", end='\r')
                else:
                    print(f"   Distance: No reading                    ", end='\r')
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\n   Test ended")
            
    def take_snapshot(self):
        print("\n📸 Taking snapshot...")
        image, filename = self.capture_image_rpicam()
        if image is not None:
            print(f"   ✅ Photo saved: {filename}")
            color_percentage = self.detect_target_color(image)
            print(f"   📊 {self.target_color.capitalize()} detected: {color_percentage:.2f}%")
        else:
            print("   ❌ Failed to capture image")
            
    def calibrate_servo(self):
        """Calibrate the open/close duty cycles and timing"""
        print("\n🔧 SERVO CALIBRATION")
        print("="*50)
        print("Calibrate the speed and time to return to exact position")
        print(f"\nCurrent settings:")
        print(f"  Open speed (duty): {self.servo_open}%")
        print(f"  Close speed (duty): {self.servo_close}%")
        print(f"  Time each way: {self.rotation_time}s")
        print("\n📋 Commands:")
        print("  'test' - Test full open/close cycle")
        print("  'open' - Test only opening")
        print("  'close' - Test only closing")
        print("  'stop' - Emergency stop")
        print("  'time X' - Set rotation time (e.g., 'time 2.5')")
        print("  'open speed X' - Set open speed (e.g., 'open speed 7.0')")
        print("  'close speed X' - Set close speed (e.g., 'close speed 8.0')")
        print("  'q' - Quit calibration")
        print("\n⚠️ Mark the starting position to verify it returns exactly!")
        
        while True:
            cmd = input("\nCommand: ").lower().strip()
            
            if cmd == 'q':
                self.stop_servo()
                break
            elif cmd == 'stop':
                self.stop_servo()
            elif cmd == 'test':
                print(f"Testing full cycle: {self.servo_open}% for {self.rotation_time}s, then {self.servo_close}% for {self.rotation_time}s")
                self.dispense_food()
                print("Did it return exactly?")
            elif cmd == 'open':
                self.servo_pwm.ChangeDutyCycle(self.servo_open)
                time.sleep(self.rotation_time)
                self.stop_servo()
            elif cmd == 'close':
                self.servo_pwm.ChangeDutyCycle(self.servo_close)
                time.sleep(self.rotation_time)
                self.stop_servo()
            elif cmd.startswith('time '):
                try:
                    self.rotation_time = float(cmd.split()[1])
                    print(f"✅ Time set to {self.rotation_time}s")
                except:
                    print("Invalid format. Use: time 2.0")
            elif cmd.startswith('open speed '):
                try:
                    speed = float(cmd.split()[2])
                    self.servo_open = speed
                    print(f"✅ Open speed set to {speed}%")
                except:
                    print("Invalid format. Use: open speed 7.0")
            elif cmd.startswith('close speed '):
                try:
                    speed = float(cmd.split()[2])
                    self.servo_close = speed
                    print(f"✅ Close speed set to {speed}%")
                except:
                    print("Invalid format. Use: close speed 8.0")
            else:
                print("❌ Invalid command")
                
    def get_distance(self):
        try:
            GPIO.output(TRIGGER_PIN, False)
            time.sleep(0.1)
            GPIO.output(TRIGGER_PIN, True)
            time.sleep(0.00001)
            GPIO.output(TRIGGER_PIN, False)
            
            pulse_start = time.time()
            timeout = time.time() + 0.5
            while GPIO.input(ECHO_PIN) == 0 and time.time() < timeout:
                pulse_start = time.time()
            
            pulse_end = time.time()
            timeout = time.time() + 0.5
            while GPIO.input(ECHO_PIN) == 1 and time.time() < timeout:
                pulse_end = time.time()
            
            duration = pulse_end - pulse_start
            distance = duration * 17150
            return round(distance, 2) if 2 < distance < 400 else None
        except:
            return None
            
    def capture_image_rpicam(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.image_dir, f"detection_{self.target_color}_{timestamp}.jpg")
        cmd = ['rpicam-still', '-o', filename, '-t', '1', '--width', '640', '--height', '480', '--immediate', '-n']
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            if result.returncode == 0:
                image = cv2.imread(filename)
                if image is not None:
                    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB), filename
        except:
            pass
        return None, None
        
    def detect_target_color(self, image):
        hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
        combined_mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        
        for lower, upper in self.color_ranges:
            mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
            combined_mask = cv2.bitwise_or(combined_mask, mask)
        
        kernel = np.ones((5, 5), np.uint8)
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)
        
        color_pixels = cv2.countNonZero(combined_mask)
        total_pixels = image.shape[0] * image.shape[1]
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mask_filename = os.path.join(self.image_dir, f"{self.target_color}_mask_{timestamp}.jpg")
        cv2.imwrite(mask_filename, combined_mask)
        
        return (color_pixels / total_pixels) * 100
        
    def process_detection(self):
        print("\n📸 Capturing image...")
        image, filename = self.capture_image_rpicam()
        if image is None:
            print("❌ Failed to capture image")
            return False
        print(f"   Image saved: {filename}")
        
        print(f"🔍 Analyzing for {self.target_color} color...")
        color_percentage = self.detect_target_color(image)
        print(f"📊 {self.target_color.capitalize()} pixels: {color_percentage:.2f}%")
        
        if color_percentage >= COLOR_THRESHOLD:
            print(f"✅ {self.target_color.upper()} ANIMAL DETECTED!")
            print("🚨 ACTIVATING FEEDER!")
            self.dispense_food()
            return True
        else:
            print(f"❌ Not a {self.target_color} animal")
            return False
            
    def monitor(self):
        print("\n" + "="*50)
        print(f"🦊 AUTOMATIC MONITORING ACTIVE")
        print("="*50)
        print(f"🔄 Servo: Open (duty {self.servo_open}%) for {self.rotation_time}s, Close (duty {self.servo_close}%) for {self.rotation_time}s")
        print(f"⏰ Cycle time: {self.cycle_time} seconds")
        print("\nPress Ctrl+C to return to menu\n")
        
        last_detection_time = 0
        
        while True:
            try:
                distance = self.get_distance()
                if distance and distance < ANIMAL_DETECTION_DISTANCE:
                    current_time = time.time()
                    if current_time - last_detection_time > self.cycle_time:
                        print(f"\n🚨 ANIMAL DETECTED at {distance:.2f} cm!")
                        if self.process_detection():
                            last_detection_time = current_time
                            print(f"\n⏳ Next detection in {self.cycle_time} seconds...")
                    else:
                        remaining = int(self.cycle_time - (current_time - last_detection_time))
                        print(f"📏 Distance: {distance:.2f} cm - Cooldown: {remaining}s    ", end='\r')
                else:
                    if distance:
                        print(f"📏 Distance: {distance:.2f} cm - Clear         ", end='\r')
                    else:
                        print("📏 Distance: No reading         ", end='\r')
                time.sleep(0.5)
            except KeyboardInterrupt:
                print("\n\nReturning to menu...")
                break
            except Exception as e:
                print(f"\n⚠️ Error: {e}")
                time.sleep(1)
                
    def cleanup(self):
        print("\n🧹 Cleaning up...")
        try:
            if self.servo_pwm:
                self.stop_servo()
                time.sleep(0.5)
                self.servo_pwm.stop()
                self.servo_pwm = None
            time.sleep(0.1)
            GPIO.cleanup()
        except:
            pass
        print("✅ Cleanup complete")
        
def get_color_choice():
    available_colors = ['brown', 'black', 'white', 'gray', 'orange', 'yellow', 'red', 'green', 'blue', 'tan']
    print("\n🎨 SELECT TARGET COLOR")
    for i, color in enumerate(available_colors, 1):
        print(f"  {i}. {color.capitalize()}")
    while True:
        choice = input("\nEnter color or number: ").lower().strip()
        if choice in available_colors: return choice
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(available_colors): return available_colors[idx]
        except: pass
        print("❌ Invalid choice")
        
def get_cycle_time():
    print("\n⏰ SET DETECTION CYCLE TIME (seconds)")
    while True:
        try:
            time_input = input("Enter cycle time (10-3600): ").strip()
            cycle_time = int(time_input)
            if 10 <= cycle_time <= 3600: return cycle_time
            print("❌ Enter value between 10 and 3600")
        except:
            print("❌ Enter a valid number")
            
def main():
    print("\n" + "🐾"*20)
    print(" SMART PET FEEDER")
    print("🐾"*20)
    
    target_color = get_color_choice()
    cycle_time = get_cycle_time()
    
    detector = None
    try:
        detector = AnimalColorDetector(target_color, cycle_time)
        
        while True:
            # Main menu
            print("\n" + "="*50)
            print("📋 MAIN MENU")
            print("="*50)
            print("  1. Start Automatic Monitoring")
            print("  2. Manual Control Menu")
            print("  3. Exit")
            print("="*50)
            
            choice = input("\nSelect option (1-3): ").strip()
            
            if choice == '1':
                detector.monitor()
            elif choice == '2':
                detector.manual_control_menu()
            elif choice == '3':
                print("\n👋 Goodbye!")
                break
            else:
                print("❌ Invalid choice")
                
    except KeyboardInterrupt:
        print("\n⛔ Interrupted")
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        if detector:
            detector.cleanup()
            
if __name__ == "__main__":
    if os.geteuid() != 0:
        print("⚠️ If you get GPIO errors, try: sudo python3 " + sys.argv[0])
    main()

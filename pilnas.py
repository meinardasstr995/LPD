#!/usr/bin/env python3
import os
import sys
 
# Force RPi.GPIO to use BCM mode before import
os.environ["GPIOZERO_PIN_FACTORY"] = "rpigpio"
 
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
import requests   # HTTP client to send data
 
# -----------------------------------------------------------------------------
# NETWORK CONFIGURATION  (update host if needed)
# -----------------------------------------------------------------------------
HOST = "<IP_ADDRESS>"                  # address of computer running Node‑RED
URL  = f"http://{HOST}:1880/feeder"
 
# GPIO Configuration
SERVO_PIN = 4
TRIGGER_PIN = 17
ECHO_PIN = 27
 
# Detection parameters
ANIMAL_DETECTION_DISTANCE = 50  # cm - distance to trigger detection
COLOR_THRESHOLD = 10            # percent of colour pixels to trigger servo
 
 
def send_feeder_data(remaining_food, fed, time_until_next_feed):
    """Send feeder data to the Node‑RED endpoint."""
    payload = {
        "remaining_food": remaining_food,
        "fed": fed,
        "time_until_next_feed": time_until_next_feed
    }
    try:
        r = requests.post(URL, json=payload, timeout=5)
        print(f"📡 Data sent to Node‑RED ({r.status_code}): {r.text.strip()}")
    except Exception as e:
        print(f"⚠️  Could not send data: {e}")
 
 
# =============================================================================
#  MAIN DETECTOR CLASS
# =============================================================================
class AnimalColorDetector:
    def __init__(self, target_color, cycle_time):
        if not target_color:
            target_color = "brown"
        self.target_color = target_color.lower()
        self.cycle_time = cycle_time
        self.remaining_food = 100.0            # start full container
        self.setup_gpio()
 
        self.servo_stop = 7.5
        self.servo_open = 7.0
        self.servo_close = 8.0
        self.rotation_time = 1.0
        self.live_view_active = False
        self.servo_pwm = None
        try:
            self.servo_pwm = GPIO.PWM(SERVO_PIN, 50)
            self.servo_pwm.start(0)
            self.stop_servo()
            print("📐 Servo initialized.")
        except Exception as e:
            print(f"⚠️ Servo initialization warning: {e}")
 
        self.setup_color_ranges()
        self.image_dir = "captured_images"
        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir)
        print(f"✅ System ready for {self.target_color.upper()} detection!")
 
    # -------------------------------------------------------------------------
    def setup_gpio(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin in [SERVO_PIN, TRIGGER_PIN, ECHO_PIN]:
            try:
                GPIO.cleanup(pin)
            except:
                pass
        time.sleep(0.5)
        GPIO.setup(TRIGGER_PIN, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(ECHO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(SERVO_PIN, GPIO.OUT)
 
    # -------------------------------------------------------------------------
    def setup_color_ranges(self):
        self.all_color_ranges = {
            'brown': [[(10, 50, 50), (20, 255, 200)]],
            'black': [[(0, 0, 0), (180, 255, 30)]],
            'white': [[(0, 0, 200), (180, 30, 255)]],
            'gray':  [[(0, 0, 50), (180, 30, 150)]],
            'orange': [[(10, 100, 100), (20, 255, 255)]],
            'yellow': [[(25, 50, 50), (35, 255, 255)]],
            'red':    [[(0, 100, 100), (10, 255, 255)],
                       [(170, 100, 100), (180, 255, 255)]],
            'green':  [[(40, 50, 50), (80, 255, 255)]],
            'blue':   [[(100, 50, 50), (130, 255, 255)]],
            'tan':    [[(15, 20, 50), (25, 100, 200)]]
        }
        self.color_ranges = self.all_color_ranges.get(self.target_color,
                                                      self.all_color_ranges['brown'])
 
    # -------------------------------------------------------------------------
    def stop_servo(self):
        if self.servo_pwm:
            self.servo_pwm.ChangeDutyCycle(self.servo_stop)
            time.sleep(0.1)
            self.servo_pwm.ChangeDutyCycle(0)
 
    # -------------------------------------------------------------------------
    def dispense_food(self):
        print("🍽️ Dispensing food...")
        if self.servo_pwm:
            self.servo_pwm.ChangeDutyCycle(self.servo_open)
            time.sleep(self.rotation_time)
            self.stop_servo()
            time.sleep(0.2)
            self.servo_pwm.ChangeDutyCycle(self.servo_close)
            time.sleep(self.rotation_time)
            self.stop_servo()
        print("✅ Dispensing complete. Feeder returned to start.")
 
        # --- simulate decrease of food and send to Node‑RED ---
        try:
            self.remaining_food = max(0.0, self.remaining_food - 5.0)
            fed = True
            time_until_next_feed = self.cycle_time
            send_feeder_data(self.remaining_food, fed, time_until_next_feed)
            print(f"💾 Remaining food now {self.remaining_food:.1f}%")
        except Exception as e:
            print(f"⚠️ Failed to send feeder data: {e}")
 
    # -------------------------------------------------------------------------
    def capture_image_rpicam(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.image_dir,
                                f"detection_{self.target_color}_{timestamp}.jpg")
        cmd = ['rpicam-still', '-o', filename, '-t', '1',
               '--width', '640', '--height', '480', '--immediate', '-n']
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            if result.returncode == 0:
                image = cv2.imread(filename)
                if image is not None:
                    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB), filename
        except Exception:
            pass
        return None, None
 
    # -------------------------------------------------------------------------
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
        return (color_pixels / total_pixels) * 100
 
    # -------------------------------------------------------------------------
    def process_detection(self):
        print("\n📸 Capturing image...")
        image, filename = self.capture_image_rpicam()
        if image is None:
            print("❌ Failed to capture image")
            return False
        print(f"   Image saved: {filename}")
        color_percentage = self.detect_target_color(image)
        print(f"📊 {self.target_color.capitalize()} pixels: {color_percentage:.2f}%")
        if color_percentage >= COLOR_THRESHOLD:
            print(f"✅ {self.target_color.upper()} ANIMAL DETECTED! 🚨")
            self.dispense_food()
            return True
        else:
            print(f"❌ Not a {self.target_color} animal")
            return False
 
    # -------------------------------------------------------------------------
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
        except Exception:
            return None
 
    # -------------------------------------------------------------------------
    def monitor(self):
        print("\n" + "=" * 50)
        print("🦊 AUTOMATIC MONITORING ACTIVE")
        print("=" * 50)
        print(f"⏰ Cycle time: {self.cycle_time}s\nPress Ctrl+C to stop\n")
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
                            print(f"\n⏳ Next detection in {self.cycle_time}s...")
                    else:
                        remaining = int(self.cycle_time - (current_time - last_detection_time))
                        print(f"📏 Distance: {distance:.2f}cm – Cooldown: {remaining}s", end="\r")
                else:
                    if distance:
                        print(f"📏 Distance: {distance:.2f}cm – Clear        ", end="\r")
                    else:
                        print("📏 Distance: No reading        ", end="\r")
                time.sleep(0.5)
            except KeyboardInterrupt:
                print("\nReturning to menu...")
                break
            except Exception as e:
                print(f"\n⚠️ Error: {e}")
                time.sleep(1)
 
    # -------------------------------------------------------------------------
    def cleanup(self):
        print("\n🧹 Cleaning up...")
        try:
            if self.servo_pwm:
                self.stop_servo()
                time.sleep(0.5)
                self.servo_pwm.stop()
                self.servo_pwm = None
            GPIO.cleanup()
        except Exception:
            pass
        print("✅ Cleanup complete")
 
 
# =============================================================================
#  COLOR & CYCLE PROMPTS WITH MEMORY
# =============================================================================
def get_color_choice():
    """Ask for a target color and remember last choice."""
    filename = "last_color.txt"
    colors = ['brown', 'black', 'white', 'gray', 'orange',
              'yellow', 'red', 'green', 'blue', 'tan']
    remembered = None
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                remembered = f.read().strip().lower()
        except Exception:
            pass
 
    print("\n🎨 SELECT TARGET COLOR")
    if remembered:
        print(f"(Press ENTER to reuse: {remembered.capitalize()})")
    for i, c in enumerate(colors, 1):
        print(f"  {i}. {c.capitalize()}")
 
    while True:
        ans = input("\nEnter color or number: ").lower().strip()
        if ans == "" and remembered:
            selected = remembered
            break
        if ans in colors:
            selected = ans
            break
        try:
            idx = int(ans) - 1
            if 0 <= idx < len(colors):
                selected = colors[idx]
                break
        except ValueError:
            pass
        print("❌ Invalid choice, try again.")
 
    try:
        with open(filename, "w") as f:
            f.write(selected)
    except Exception as e:
        print(f"⚠️ Could not save color preference: {e}")
 
    print(f"✅ Using color: {selected.capitalize()}")
    return selected
 
 
def get_cycle_time():
    print("\n⏰ SET DETECTION CYCLE TIME (seconds)")
    while True:
        try:
            val = input("Enter cycle time (10‑3600, ENTER=60): ").strip()
            if not val:
                return 60
            num = int(val)
            if 10 <= num <= 3600:
                return num
            print("❌ Value must be between 10 and 3600")
        except ValueError:
            print("❌ Enter a number")
 
 
# =============================================================================
#  PROGRAM ENTRY POINT
# =============================================================================
def main():
    print("\n" + "🐾" * 20)
    print(" SMART PET FEEDER ")
    print("🐾" * 20)
    t_color = get_color_choice()
    cycle_time = get_cycle_time()
    detector = None
    try:
        detector = AnimalColorDetector(t_color, cycle_time)
        while True:
            print("\n" + "=" * 50)
            print("📋 MAIN MENU")
            print("=" * 50)
            print(" 1. Start Automatic Monitoring")
            print(" 2. Manual Control Menu")
            print(" 3. Exit")
            print("=" * 50)
            choice = input("\nSelect option (1‑3): ").strip()
            if choice == "1":
                detector.monitor()
            elif choice == "2":
                detector.manual_control_menu()
            elif choice == "3":
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
        print("⚠️ For GPIO access run with sudo: sudo python3 " + sys.argv[0])
    main()
 

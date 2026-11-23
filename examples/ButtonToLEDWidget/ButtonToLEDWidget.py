"""
SME AIoT - Button To LED Widget        (Raspberry Pi, Jetson, Coral, Orange Pi, Banana Pi and other Linux boards)

Press a button: the LED widget in the app turns on, press again: off. The board's LED shows the same state.
Button: between GPIO 17 (BCM numbering, header pin 11) and GND. Raspberry Pi uses gpiozero; on boards without
gpiozero, or with no button wired, press Enter in the terminal instead.

App widget: LED on TP4 (0 = off, 1 = on).

Run:  python3 ButtonToLEDWidget.py
Install once:  pip install sme-aiot gpiozero

Fill in the values below from your device in the SME AIoT app.
"""
import select
import sys

from smeaiot import SME, TP4

SME_PRINT = True                     # shows the SME AIoT logo and status lines (like #define SME_PRINT Serial)
DASHBOARD_ID = "PROJ-XXXXXXXX"
DEVICE_TOKEN = "SME-XXXX-XXXX-XXXX"
FIRMWARE_VERSION = "0.0.1"           # your program's version, sent to the app
# The board's own network is used (Wi-Fi or Ethernet), so no Wi-Fi name or password here.

BUTTON_GPIO = 17
led_state = False

try:
    from gpiozero import Button      # Raspberry Pi (pip install gpiozero)
    button = Button(BUTTON_GPIO, pull_up=True, bounce_time=0.05)   # pressed = connected to GND
except Exception:
    button = None
    print("No GPIO button here: press Enter in this terminal to press the button.")


def pressed():
    global led_state
    led_state = not led_state
    SME.publish(TP4, 1 if led_state else 0)   # LED widget in the app
    SME.led(led_state)                         # and the board's LED (needs sudo)
    print("Button: LED widget", "ON" if led_state else "OFF")


if button:
    button.when_pressed = lambda: SME.clock.after(1, pressed)   # run it in SME.run(), on this thread

SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)
SME.publish(TP4, 0)                  # the LED widget starts off

while True:
    SME.run()
    if not button and select.select([sys.stdin], [], [], 0)[0]:
        sys.stdin.readline()
        pressed()

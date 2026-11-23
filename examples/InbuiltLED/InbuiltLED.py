"""
SME AIoT - Inbuilt LED        (Raspberry Pi, Jetson, Coral, Orange Pi, Banana Pi and other Linux boards)

Switch the board's LED on and off from the app (Raspberry Pi: the green ACT LED; other
boards: their status LED). SME.led() picks the right one. Writing the board LED needs sudo:
    sudo python3 InbuiltLED.py
After a power cut the LED follows the app: when the board comes online the cloud sends the Switch's last value.

App widget: Switch on TP0 (OFF = 0, ON = 1).

Run:  python3 InbuiltLED.py
Install once:  pip install sme-aiot

Fill in the values below from your device in the SME AIoT app.
"""
from smeaiot import SME, SME_LISTEN, TP0

SME_PRINT = True                     # shows the SME AIoT logo and status lines (like #define SME_PRINT Serial)
DASHBOARD_ID = "PROJ-XXXXXXXX"
DEVICE_TOKEN = "SME-XXXX-XXXX-XXXX"
FIRMWARE_VERSION = "0.0.1"           # your program's version, sent to the app
# The board's own network is used (Wi-Fi or Ethernet), so no Wi-Fi name or password here.


@SME_LISTEN(TP0)                     # the Switch on TP0 changed
def on_switch(payload):
    on = payload.toBool()            # "1" = ON, "0" = OFF
    if not SME.led(on):
        print("(no writable board LED: run with sudo)")
    print("LED:", "ON" if on else "OFF")


SME.led(False)                       # start OFF until the app says otherwise
SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)

while True:
    SME.run()                        # keep it running, never use time.sleep() for long

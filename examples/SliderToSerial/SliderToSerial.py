"""
SME AIoT - Slider To Serial        (Raspberry Pi, Jetson, Coral, Orange Pi, Banana Pi and other Linux boards)

Move a Slider in the app and see its value in the terminal.

App widget: Slider on TP3 (for example 0 to 100).

Run:  python3 SliderToSerial.py
Install once:  pip install sme-aiot

Fill in the values below from your device in the SME AIoT app.
"""
from smeaiot import SME, SME_LISTEN, TP3

SME_PRINT = True                     # shows the SME AIoT logo and status lines (like #define SME_PRINT Serial)
DASHBOARD_ID = "PROJ-XXXXXXXX"
DEVICE_TOKEN = "SME-XXXX-XXXX-XXXX"
FIRMWARE_VERSION = "0.0.1"           # your program's version, sent to the app
# The board's own network is used (Wi-Fi or Ethernet), so no Wi-Fi name or password here.


@SME_LISTEN(TP3)
def on_slider(data):
    print("Slider TP3 =", data.toInt())


SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)

while True:
    SME.run()

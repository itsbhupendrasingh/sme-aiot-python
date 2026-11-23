"""
SME AIoT - Messenger        (Raspberry Pi, Jetson, Coral, Orange Pi, Banana Pi and other Linux boards)

Chat between the terminal and the Messenger widget in the app:
  - type a line here and press Enter: it appears in the app (shown here as [DEVICE -> APP])
  - send a message from the app: it is printed here as [APP -> DEVICE]

App widget: Messenger on TP15.
Note: a message that is only a number ("42") is shown as a value, not chat.

Run:  python3 Messenger.py
Install once:  pip install sme-aiot

Fill in the values below from your device in the SME AIoT app.
"""
from smeaiot import SME, TP15

SME_PRINT = True                     # shows the SME AIoT logo and status lines (like #define SME_PRINT Serial)
DASHBOARD_ID = "PROJ-XXXXXXXX"
DEVICE_TOKEN = "SME-XXXX-XXXX-XXXX"
FIRMWARE_VERSION = "0.0.1"           # your program's version, sent to the app
# The board's own network is used (Wi-Fi or Ethernet), so no Wi-Fi name or password here.

SME.messenger(TP15)                  # terminal <-> Messenger widget on TP15
SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)
SME.sendMessage(TP15, "Hello from the board")   # sent once it is online

while True:
    SME.run()                        # also reads what you type

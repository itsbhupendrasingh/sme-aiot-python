"""
SME AIoT - Send Policy        (Raspberry Pi, Jetson, Coral, Orange Pi, Banana Pi and other Linux boards)

Send less without losing what matters: a deadband skips small changes, a minimum interval caps how often a pin
is sent (the latest value still goes).

App widgets: Value Display on TP1 (CPU load x 100), Value Display on TP2 (a counter).

Run:  python3 SendPolicy.py
Install once:  pip install sme-aiot

Fill in the values below from your device in the SME AIoT app.
"""
import os
import time

from smeaiot import SME, TP1, TP2

SME_PRINT = True                     # shows the SME AIoT logo and status lines (like #define SME_PRINT Serial)
DASHBOARD_ID = "PROJ-XXXXXXXX"
DEVICE_TOKEN = "SME-XXXX-XXXX-XXXX"
FIRMWARE_VERSION = "0.0.1"           # your program's version, sent to the app
# The board's own network is used (Wi-Fi or Ethernet), so no Wi-Fi name or password here.

start = time.monotonic()


def read_values():
    load = os.getloadavg()[0] * 100                   # jitters a little
    counter = int((time.monotonic() - start) * 10)    # changes all the time
    SME.publish(TP1, load)
    SME.publish(TP2, counter)


SME.setDeadband(TP1, 5)              # send TP1 only when it moved 5 or more
SME.setMinInterval(TP2, 5000)        # send TP2 at most every 5 s (the latest value)
SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)
SME.clock.every(200, read_values)

while True:
    SME.run()

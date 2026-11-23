"""
SME AIoT - Send Values        (Raspberry Pi, Jetson, Coral, Orange Pi, Banana Pi and other Linux boards)

Send values from the board to the app every second.

App widgets:
  TP1 : Value Display or Graph (seconds since start)
  TP2 : Gauge or Graph (0 to 100, a smooth wave so the graph moves)

Run:  python3 SendValues.py
Install once:  pip install sme-aiot

Fill in the values below from your device in the SME AIoT app.
"""
import math
import time

from smeaiot import SME, TP1, TP2

SME_PRINT = True                     # shows the SME AIoT logo and status lines (like #define SME_PRINT Serial)
DASHBOARD_ID = "PROJ-XXXXXXXX"
DEVICE_TOKEN = "SME-XXXX-XXXX-XXXX"
FIRMWARE_VERSION = "0.0.1"           # your program's version, sent to the app
# The board's own network is used (Wi-Fi or Ethernet), so no Wi-Fi name or password here.

start = time.monotonic()


def send_values():
    seconds = int(time.monotonic() - start)
    wave = 50.0 + 50.0 * math.sin(seconds / 10.0)   # 0..100, one cycle a minute
    SME.publish(TP1, seconds)        # values published together
    SME.publish(TP2, wave)           # leave together in one send
    print("TP1 = %d   TP2 = %.2f" % (seconds, wave))


SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)
SME.clock.every(1000, send_values)   # every second, no time.sleep() needed

while True:
    SME.run()                        # also runs SME.clock

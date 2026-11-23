"""
SME AIoT - Graph Simulated        (Raspberry Pi, Jetson, Coral, Orange Pi, Banana Pi and other Linux boards)

Live graphs without any sensor: the board makes four moving values (a smooth wave plus a little noise)
and sends them once a second. The connection is real; only the values are made up.

App widgets: Graph (or Gauge) on
  TP0 : temperature-like, about 24..32
  TP1 : humidity-like, about 50..70
  TP2 : slow sine, 0..100
  TP3 : random walk, 0..100

Run:  python3 GraphSimulated.py
Install once:  pip install sme-aiot

Fill in the values below from your device in the SME AIoT app.
"""
import math
import random
import time

from smeaiot import SME, TP0, TP1, TP2, TP3

SME_PRINT = True                     # shows the SME AIoT logo and status lines (like #define SME_PRINT Serial)
DASHBOARD_ID = "PROJ-XXXXXXXX"
DEVICE_TOKEN = "SME-XXXX-XXXX-XXXX"
FIRMWARE_VERSION = "0.0.1"           # your program's version, sent to the app
# The board's own network is used (Wi-Fi or Ethernet), so no Wi-Fi name or password here.

walk = 50.0                          # TP3 state, drifts slowly
waiting_said = False


def send_simulated():
    global walk, waiting_said
    if not SME.connected():          # no made-up data until the device is online
        if not waiting_said:
            print("[sim] not connected yet - no data until online")
            waiting_said = True
        return
    t = time.monotonic()
    temperature = 28.0 + 4.0 * math.sin(t / 30.0) + random.uniform(-0.3, 0.3)
    humidity = 60.0 - 10.0 * math.sin(t / 30.0) + random.uniform(-0.5, 0.5)
    sine = 50.0 + 50.0 * math.sin(t / 10.0)
    walk = min(100.0, max(0.0, walk + random.uniform(-2, 2)))
    SME.publish(TP0, round(temperature, 2))   # the four go together (one message, one graph timestamp)
    SME.publish(TP1, round(humidity, 2))
    SME.publish(TP2, round(sine, 2))
    SME.publish(TP3, round(walk, 2))
    print("TP0=%.2f  TP1=%.2f  TP2=%.2f  TP3=%.2f" % (temperature, humidity, sine, walk))


SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)
SME.clock.every(1000, send_simulated)   # every second

while True:
    SME.run()

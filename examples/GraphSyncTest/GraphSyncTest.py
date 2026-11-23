"""
SME AIoT - Graph Sync Test        (Raspberry Pi, Jetson, Coral, Orange Pi, Banana Pi and other Linux boards)

Proves on one graph that pins published together arrive together. Four values are published in the same
function once a second, so they leave in ONE message and share ONE timestamp: no line is blank at another's time.

App widget: one Graph with four lines
  TP0 : counter, 0..100 then repeats      TP1 : sine, -50..+50
  TP2 : cosine, -50..+50                  TP3 : random walk around 50
What a pass looks like: all four lines have a point at every second; stop the program (Ctrl+C): the app shows
it offline at once; pull the network cable: offline in about 15 s.

Run:  python3 GraphSyncTest.py
Install once:  pip install sme-aiot

Fill in the values below from your device in the SME AIoT app.
"""
import math
import random

from smeaiot import SME, TP0, TP1, TP2, TP3

SME_PRINT = True                     # shows the SME AIoT logo and status lines (like #define SME_PRINT Serial)
DASHBOARD_ID = "PROJ-XXXXXXXX"
DEVICE_TOKEN = "SME-XXXX-XXXX-XXXX"
FIRMWARE_VERSION = "0.0.1"           # your program's version, sent to the app
# The board's own network is used (Wi-Fi or Ethernet), so no Wi-Fi name or password here.

tick = 0                             # seconds counter for the waves
walk = 50                            # TP3 state


def send_test_values():
    global tick, walk
    counter = tick % 101
    sine = 50.0 * math.sin(tick * 0.2)
    cosine = 50.0 * math.cos(tick * 0.2)
    walk = min(100, max(0, walk + random.randint(-3, 3)))
    SME.publish(TP0, counter)        # all four in one go = one message
    SME.publish(TP1, round(sine, 1))
    SME.publish(TP2, round(cosine, 1))
    SME.publish(TP3, walk)
    print("TP0=%d  TP1=%.1f  TP2=%.1f  TP3=%d" % (counter, sine, cosine, walk))
    tick += 1


SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)
SME.clock.every(1000, send_test_values)   # once a second

while True:
    SME.run()

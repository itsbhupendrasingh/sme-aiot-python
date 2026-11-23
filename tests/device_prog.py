# A device program written like the examples (tests only): sends readings, follows a switch, chats on TP15.
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from smeaiot import SME, SME_LISTEN, TP0, TP1, TP2, TP3, TP15   # noqa: E402

SME_PRINT = True
DASHBOARD_ID = os.environ.get('DASH', 'PROJ-TEST0001')
DEVICE_TOKEN = os.environ.get('TOKEN', 'SME-TEST-TOKEN-0001')
FIRMWARE_VERSION = "1.2.3"

count = 0


@SME_LISTEN(TP3)
def on_tp3(data):
    print("HANDLER TP3", data.toInt(), flush=True)
    SME.publish(TP1, data.toInt() * 10)


def send_data():
    global count
    count += 1
    SME.publish(TP0, 20.5 + count)
    SME.publish(TP2, "hello")


SME.setServerUrl(os.environ['SME_URL'])
SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)
SME.clock.every(500, send_data)
SME.messenger(TP15)

t0, said = time.monotonic(), False
end = float(os.environ.get('RUN_SECS', '0') or 0)
while True:
    SME.run()
    if not said and SME.connected() and time.monotonic() - t0 > 2.5:
        SME.sendMessage(TP15, "hi app")
        said = True
    if end and time.monotonic() - t0 > end:
        break
print("PROGRAM END", flush=True)

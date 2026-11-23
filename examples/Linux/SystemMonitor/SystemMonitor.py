"""
SME AIoT - System Monitor        (Raspberry Pi, Jetson, Coral, Orange Pi, Banana Pi and other Linux boards)

The board watches itself: CPU temperature, CPU load, memory and disk use, sent every 2 seconds.
Works on every Linux board with no wiring. 

App widgets: Gauge or Graph on
  TP0 : CPU temperature (°C)     TP1 : CPU load (%)
  TP2 : memory used (%)          TP3 : disk used (%)
  TP4 : Value Display, uptime (hours)

Run:  python3 SystemMonitor.py
Install once:  pip install sme-aiot

Fill in the values below from your device in the SME AIoT app.
"""
import os
import shutil

from smeaiot import SME, TP0, TP1, TP2, TP3, TP4

SME_PRINT = True                     # shows the SME AIoT logo and status lines (like #define SME_PRINT Serial)
DASHBOARD_ID = "PROJ-XXXXXXXX"
DEVICE_TOKEN = "SME-XXXX-XXXX-XXXX"
FIRMWARE_VERSION = "0.0.1"           # your program's version, sent to the app
# The board's own network is used (Wi-Fi or Ethernet), so no Wi-Fi name or password here.


def cpu_temperature():
    for zone in sorted(os.listdir('/sys/class/thermal')) if os.path.isdir('/sys/class/thermal') else []:
        try:
            with open('/sys/class/thermal/%s/temp' % zone) as f:
                return round(int(f.read()) / 1000.0, 1)
        except (OSError, ValueError):
            pass
    return None


def memory_used():
    info = {}
    with open('/proc/meminfo') as f:
        for line in f:
            k, v = line.split(':', 1)
            info[k] = int(v.split()[0])
    return round(100.0 * (1 - info.get('MemAvailable', info['MemFree']) / info['MemTotal']), 1)


def send_status():
    temp = cpu_temperature()
    load = round(100.0 * os.getloadavg()[0] / (os.cpu_count() or 1), 1)
    disk = shutil.disk_usage('/')
    with open('/proc/uptime') as f:
        hours = round(float(f.read().split()[0]) / 3600, 2)
    if temp is not None:
        SME.publish(TP0, temp)
    SME.publish(TP1, load)
    SME.publish(TP2, memory_used())
    SME.publish(TP3, round(100.0 * disk.used / disk.total, 1))
    SME.publish(TP4, hours)
    print("CPU %s °C  load %s %%  up %s h" % (temp, load, hours))


SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)
SME.clock.every(2000, send_status)

while True:
    SME.run()

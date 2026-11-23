# SME AIoT SDK for Python (Linux)

The SME AIoT SDK for Linux: the Arduino **SME AIoT SDK v1.0.0** ported to Python, for
Raspberry Pi, NVIDIA Jetson, Google Coral, Orange Pi, Banana Pi, Radxa ROCK, ODROID,
gateways, servers or any Linux machine that should appear in SME AIoT as a device.

It talks to the cloud **exactly** like a NuttyFi board: the same HTTPS registration,
endpoints, headers and JSON bodies, the same MQTT topics, client id, QoS, retained
"online" message and Last Will, the same batching, rate limit, deadband, retries and
fallback to HTTPS. Numbers are even written the way the board writes them (a
published `23.456789` goes out as `23.45679`, like a 32-bit float on the board).
This is checked automatically: the test suite runs the C++ SDK and this one through
thousands of random scenarios and requires identical traffic (see *Tests*).

## Install

```bash
pip install ./sme-aiot-python        # needs Python 3.6+, installs paho-mqtt
```

Old code with `import smeiot` / `from smeiot import ...` keeps working; new code
uses `smeaiot`.

## Quick start

```python
from smeaiot import SME, SME_LISTEN, TP0, TP1, TP15

SME_PRINT = True                    # like  #define SME_PRINT Serial : logo + status lines
DASHBOARD_ID = "PROJ-XXXXXXXX"      # like  #define DASHBOARD_ID "PROJ-XXXXXXXX"
DEVICE_TOKEN = "SME-XXXX-XXXX-XXXX"
FIRMWARE_VERSION = "0.0.1"

@SME_LISTEN(TP0)                    # the dashboard writes TP0
def on_switch(data):
    print("Switch:", data.toInt())

def my_data():
    SME.publish(TP1, 23.5)

SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)
SME.clock.every(1000, my_data)
SME.messenger(TP15)                 # the terminal <-> the Messenger widget

while True:
    SME.run()                       # = loop() { SME.run(); }  (rests 2 ms: ~2 % of one core)
```

```
  _____ __  __ ______            _____   _______
 / ____|  \/  |  ____|     /\   |_   _| |__   __|
| (___ | \  / | |__       /  \    | |  ___ | |
 \___ \| |\/| |  __|     / /\ \   | | / _ \| |
 ____) | |  | | |____   / ____ \ _| || (_) | |
|_____/|_|  |_|______| /_/    \_\_____\___/|_|

v1.0.0 on Raspberry Pi 5 Model B Rev 1.0
Firmware: 0.0.1

[SME] Network connected, IP 192.168.1.50
[SME] Connecting to SME AIoT cloud...
[SME] Verifying device with the cloud...
[SME] Device verified & registered with the cloud
[SME] Device ID: 3f2c...
[SME] Server offered a real-time channel (MQTT) - connecting...
[SME] MQTT connected - live updates on; unplugged board shows offline in ~15s
[SME] Getting the latest values from the cloud...
[SME] First data sent - check the app graph
```

## From an Arduino sketch to Python

| Arduino sketch | Python |
|---|---|
| `#include <SMEAIoT.h>` | `from smeaiot import SME, SME_LISTEN, TP0, TP1` |
| `#define SME_PRINT Serial` | `SME_PRINT = True` (or `SME.setPrint(sys.stdout)`) |
| `#define DASHBOARD_ID "..."` (and the other values) | `DASHBOARD_ID = "..."` |
| `SME_LISTEN(TP0) { int v = payload.toInt(); }` | `@SME_LISTEN(TP0)`<br>`def on_tp0(payload): v = payload.toInt()` |
| `SME.begin(ID, TOKEN, FW, ssid, pass);` | `SME.begin(ID, TOKEN, FW)` (WiFi arguments are accepted and ignored) |
| `void loop() { SME.run(); }` | `while True: SME.run()` (or `SME.run_forever()`) |
| `SME.publish(TP1, value);` | `SME.publish(TP1, value)` (bool, int, float, str, or dict/list as JSON text) |
| `SME.clock.every(1000, fn);` | `SME.clock.every(1000, fn)`; also `after`, `pause`, `resume`, `stop` |
| `SME.setDeadband(TP1, 0.5);` `SME.setMinInterval(TP2, 5000);` | the same |
| `SME.messenger(TP15);` `SME.sendMessage(TP15, "hi");` | the same; the terminal plays the Serial Monitor |
| `SME.connected()`, `SME.mqttConnected()`, `SME.banner(false)` | the same (`False`) |
| `SME.led(true)` | `SME.led(True)`: the board's status LED (Raspberry Pi ACT ...), needs sudo |
| `payload.toInt() toFloat() toBool() toString() isInt() isFloat() isBool() toJSON()` | the same names, plus `int(payload)`, `float(payload)`, `str(payload)` |

## Server

The SME AIoT cloud (`https://apps.nuttyengineer.cloud/api`). `SME.setServerUrl(url)`
before `SME.begin()` points a program at another server.

The MQTT broker, port and login come from the registration reply, as on the board.
The server certificate is checked against the same pinned root as the board
(ISRG Root X1, Let's Encrypt), not the computer's certificate store.

## Settings

Same names and defaults as `SMEConfig.h`, in `smeaiot.config`. Change them before
`SME.begin()` (unlike on the board, this really reaches the whole SDK):

```python
import smeaiot.config as config
config.SME_FLUSH_INTERVAL = 100
config.SME_DEVICE_TYPE = "SME-Device"   # sent at registration
```

## Run it as a service

`/etc/systemd/system/sme-device.service`:

```ini
[Unit]
Description=SME AIoT device
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/my_device.py
Restart=always
RestartSec=5
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now sme-device
journalctl -u sme-device -f        # the [SME] status lines
```

## Examples

`examples/`: the same seven as the Arduino SDK, with the same names, pins and widgets:
InbuiltLED (Switch TP0), SendValues (TP1, TP2), SliderToSerial (Slider TP3),
ButtonToLEDWidget (a button on GPIO 17, or Enter, to the LED widget TP4), Messenger (TP15),
GraphSimulated (TP0-TP3) and GraphSyncTest (TP0-TP3). `examples/Linux/`: SystemMonitor
(CPU temperature, load, memory, disk, uptime) and SendPolicy (deadband, minimum interval).
Fill in the three values at the top and run `python3 examples/SendValues/SendValues.py`.

GPIO: on a Raspberry Pi use `gpiozero`; on Jetson, Coral, Orange Pi and others their GPIO
library or Adafruit Blinka (`board`, `digitalio`). The Project Builder writes a complete
program, with the parts and pins, for each of these boards.

## What is different from the board, and why

| | Board | Python on Linux |
|---|---|---|
| Network | the SDK joins WiFi | the operating system keeps the network up; the status line says "Network connected" instead of "WiFi connected", and there is no "Connecting to WiFi" line |
| Time | the SDK starts NTP | the system clock is used; "Waiting for time..." still appears if it is not set |
| `device_type` at registration | "NuttyFi2.0 (ESP8266)" / "NuttyFi32 (ESP32)" | the board's own name + " (Linux)", e.g. "Raspberry Pi 5 Model B Rev 1.0 (Linux)", "NVIDIA Jetson Nano Developer Kit (Linux)"; set `config.SME_DEVICE_TYPE` to send something else |
| Board helpers | `SME.led()`, `SME.analogRead...()` | `SME.led()` drives the board's status LED (needs sudo); no analog pins on Linux boards (use an ADC chip) |
| Saving values to flash (`SME_STATE_PERSIST`) | off by default | not included (it is off by default on the board too) |
| A text value over 63 bytes | cut at byte 63, even inside a character like "é" | cut before that character, so the text stays valid UTF-8 |
| Whole numbers beyond ±2,147,483,647 | wrap around (32-bit `long`) | sent exactly |

## Tests

```bash
pip install pytest
python3 -m pytest tests
```

| File | What it checks |
|---|---|
| `test_units.py` | SMEData, timers, rate limiter, sync engine, JSON in ArduinoJson's format |
| `test_examples_broker.py` | every example, run as a user would, against a stand-in cloud (`fakecloud.py`) and a real MQTT broker (`pip install amqtt`) |
| `test_e2e_broker.py` | the SDK end to end on real sockets: register, MQTT data and commands, Messenger both ways, batching, presence beacon, Last-Will on a kill, "offline" on a clean exit, HTTPS fallback (data, polling, acks, heartbeat), wrong token, no server |
| `test_parity.py` | the C++ SDK and this one through the same random scenarios; every HTTP request, MQTT connect/publish/subscribe, handler call and status line must match in the same millisecond. Needs g++ and `SME_ARDUINO_SDK=/path/to/SMEAIoT` (run its `test/run_tests.sh` once) |
| `test_live_mosquitto.py` | real sockets: a real Mosquitto (TLS) and a local HTTPS backend: register, stored values on "online" (also when the backend answers instantly), live commands, data, broker down → HTTPS fallback (data, polling, acks, heartbeat), broker back → MQTT, Last Will, pinned certificate. Needs `mosquitto` (or `SME_MOSQUITTO=/path`) and openssl |

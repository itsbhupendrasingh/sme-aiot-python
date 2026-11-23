# Changelog

## 1.0.0 (2026-11-23): first public release

- Matches the Arduino SME AIoT SDK 1.0.0: the same calls, the same cloud protocol.
- Connects to the SME AIoT cloud (production); the server certificate is checked against the pinned root.
- `pip install sme-aiot`; Python 3.6 or newer, paho-mqtt 1.6 or 2.x.

## Development builds before 1.0.0 (versioned 0.0.1)

First version: the Arduino SME AIoT SDK for Linux, in Python.

- Follows the final Arduino SDK (November 2026): MQTT client id smeiot-<MAC> (the broker resumes the
  session), keepalive 60 s, a retained "online" beacon every 7 s, the cloud's stored values applied first
  (300 ms hold), the first snapshot sent at once, an immediate heartbeat when MQTT falls back to HTTPS,
  200 ms batching, 48-pin snapshots, and the same status lines ("Verifying device with the cloud...",
  "MQTT connected - live updates on ...", "First data sent - check the app graph").
- `SME_PRINT = True` in the program works like `#define SME_PRINT Serial`; `while True: SME.run()` rests
  2 ms per pass (about 2 % of one core instead of 100 %).
- Says which board it runs on (Raspberry Pi, Jetson, Coral, Orange Pi, Banana Pi ...) in the logo and at
  registration. `SME.led()` (board status LED), `SME.mqttConnected()`.
- Examples: the Arduino SDK's seven (InbuiltLED, SendValues, SliderToSerial, ButtonToLEDWidget, Messenger,
  GraphSimulated, GraphSyncTest), plus Linux/SystemMonitor and Linux/SendPolicy.

- Same cloud protocol as the board: HTTPS registration, data, heartbeat, commands
  and executed-acks; MQTT data / commands / status topics, client id, QoS, retained
  "online" and Last Will; the same batching, rate limit, deadband, min-interval,
  resync, retry and backoff; production server by default, pinned ISRG Root X1.
- Same API names: SME.begin / run / publish / clock / setDeadband / setMinInterval /
  messenger / sendMessage / connected / banner / setServerUrl, SME_LISTEN, TP0..TP127,
  SMEData (toInt, toFloat, isInt, toJSON, ...).
- Named SME AIoT: `pip install sme-aiot`, `import smeaiot`; status lines say
  "SME AIoT cloud". `import smeiot` still works as an alias.
- Subscribes to the commands topic before saying "online", like the Arduino SDK, so
  the stored values the backend sends on "online" are never dropped.
- Linux: the OS keeps the network up, the system clock is used, SME.run_forever().
  A lost MQTT connection is noticed with paho-mqtt 1.6 and 2.x.
- Tests: unit tests, examples, parity with the C++ SDK (random scenarios, identical
  traffic), and an end-to-end test with a real Mosquitto and an HTTPS backend.

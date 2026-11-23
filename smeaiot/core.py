"""The SDK core: a line-for-line port of src/SMEAIoT.cpp, src/net/SMEHttp.cpp and
src/net/SMEMqtt.cpp.

Same endpoints, headers, JSON bodies, MQTT topics, QoS, retain flags, Last Will,
client id, timings, retry/backoff, rate limit and order of work inside run(). The
only differences come from Linux not being a board: the operating system keeps
the network up (there is no WiFi to join), the system clock is already set (no
NTP to start), and there is no RAM limit on secure connections.
"""

import logging

from . import _json
from . import config
from . import platform as _p
from .clock import SMEClock
from .data import SMEData
from .sync import RateLimiter, SyncEngine, clip_utf8

log = logging.getLogger("smeaiot")


def _debug(msg, *args):
    if config.SME_DEBUG:
        log.debug("[SME] " + msg, *args)


def _atoi_u8(s):
    """(uint8_t)atoi(s), as the board turns "tp12" into pin 12."""
    i, n = 0, len(s)
    while i < n and s[i] in " \t\n\v\f\r":
        i += 1
    neg = False
    if i < n and s[i] in "+-":
        neg = s[i] == "-"
        i += 1
    v = 0
    while i < n and "0" <= s[i] <= "9":
        v = v * 10 + (ord(s[i]) - 48)
        i += 1
    v = -v if neg else v
    return v & 0xFF


def _pin_of(command):
    """Pin for a command name, or None for a non-pin command (e.g. config_refresh)."""
    if command.startswith("tp"):
        return _atoi_u8(command[2:])
    if command[:1] == "v" and len(command.encode("utf-8")) <= 4:
        return _atoi_u8(command[1:])
    return None


def _value_text(obj):
    """A command's value as text: a string as it is, anything else as JSON."""
    if "value" in obj and isinstance(obj["value"], str):
        return obj["value"]
    return _json.dumps(obj.get("value"))


def _str_field(d, key, default=""):
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, str) else default


def _int_field(d, key, default):
    v = d.get(key) if isinstance(d, dict) else None
    if isinstance(v, bool) or not isinstance(v, int):
        return default
    if not (-(1 << 31) <= v < (1 << 31)):
        return default
    return v


def _bool_field(d, key, default):
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, bool) else default


# ---- HTTPS (src/net/SMEHttp.cpp) ------------------------------------------------

class SMEHttp(object):
    def __init__(self):
        self._conn = None
        self._keep_alive = True
        self._base = config.SME_BASE_URL
        self._token = ""
        self._dash = ""
        self._fw = ""
        self._device_id = ""
        self._cmds = []
        self._cmd_index = 0

    def begin(self, base_url, token, dash_id, fw):
        self._base, self._token, self._dash, self._fw = base_url, token, dash_id, fw
        self._conn = _p.Http()

    def setKeepAlive(self, keep):
        self._keep_alive = keep

    def closeTls(self):
        if self._conn is not None:
            self._conn.close()

    def _call(self, method, path, body, timeout_ms, auth=True, content_type=True):
        headers = {}
        if content_type:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = "Device " + self._token
        code, data = self._conn.request(method, self._base + path, headers,
                                        body.encode("utf-8") if body is not None else None,
                                        timeout_ms, self._keep_alive)
        if code > 0 and not self._keep_alive:
            self._conn.close()
        return code, data

    def registerDevice(self):
        """Returns None on failure, else (device_id, host, port, tls, user, pass)."""
        body = ("{" + '"dashboard_id":' + _json.dumps(self._dash) +
                ',"token":' + _json.dumps(self._token) +
                ',"device_type":' + _json.dumps(_p.device_type()) +
                ',"firmware_version":' + _json.dumps(self._fw) +
                ',"mac_address":' + _json.dumps(_p.mac_address()) +
                ',"ip_address":' + _json.dumps(_p.local_ip() or "0.0.0.0") + "}")
        code, data = self._call("POST", "/devices/register", body, 15000, auth=False)
        _debug("register -> %d", code)
        if code not in (200, 201):
            return None
        try:
            res = _json.loads(data)
        except _json.ParseError:
            return None
        d = res.get("data") if isinstance(res, dict) else None
        if d is None:
            return None
        dev = _str_field(d, "device_id", None)
        if dev is None:
            return None
        self._device_id = dev
        return (dev, _str_field(d, "mqtt_broker"), _int_field(d, "mqtt_port", 1883),
                _bool_field(d, "mqtt_tls", False), _str_field(d, "mqtt_username"),
                _str_field(d, "mqtt_password"))

    def sendData(self, payload):
        if not self._device_id or payload is None:
            return False
        code, _ = self._call("POST", "/devices/%s/data" % self._device_id, payload, 8000)
        return code in (200, 201)

    def sendHeartbeat(self, ip):
        if not self._device_id:
            return
        body = '{"status":"online","ip_address":' + _json.dumps(ip) + "}"
        self._call("POST", "/devices/%s/heartbeat" % self._device_id, body, 6000)

    def fetchCommands(self):
        self._cmds, self._cmd_index = [], 0
        if not self._device_id:
            return False
        code, data = self._call("GET", "/devices/%s/commands" % self._device_id, None, 6000,
                                content_type=False)
        if code == 200:
            try:
                doc = _json.loads(data)
                arr = doc.get("data") if isinstance(doc, dict) else None
                if isinstance(arr, list):
                    self._cmds = arr
            except _json.ParseError:
                pass
        return len(self._cmds) > 0

    def nextCommand(self):
        """(pin, value, cmd_id) for the next command, or None. Non-pin commands
        come back with pin 255 so they still get acked and cleared."""
        while self._cmd_index < len(self._cmds):
            cmd = self._cmds[self._cmd_index]
            self._cmd_index += 1
            if not isinstance(cmd, dict):
                continue
            command = cmd.get("command")
            if not isinstance(command, str):
                continue
            cmd_id = cmd.get("id") if isinstance(cmd.get("id"), str) else ""
            pin = _pin_of(command)
            return (255 if pin is None else pin), _value_text(cmd), cmd_id
        return None

    def markExecuted(self, cmd_id):
        if not self._device_id or not cmd_id:
            return
        self._call("POST", "/devices/%s/commands/%s/executed" % (self._device_id, cmd_id),
                   "{}", 5000)


# ---- MQTT (src/net/SMEMqtt.cpp) ------------------------------------------------

def _default_mqtt_factory():
    from .mqtt import MqttClient
    return MqttClient()


mqtt_factory = _default_mqtt_factory


class SMEMqtt(object):
    def __init__(self):
        self._core = None
        self._mqtt = None

    def setCore(self, core):
        self._core = core

    def configure(self, host, port, device_id, token, use_tls, user, password):
        self._user = user if user else token
        self._pass = password if password else ""
        self._topic_data = "smeiot/devices/%s/data" % device_id
        self._topic_cmd = "smeiot/devices/%s/commands" % device_id
        self._topic_status = "smeiot/devices/%s/status" % device_id
        # smeiot-<MAC>: the same id on every reconnect, so the broker resumes the session (as the board does)
        self._client_id = "smeiot-" + _p.mac_address().replace(":", "").upper()

        verify = config.SME_MQTT_TLS_VERIFY
        if verify is None:
            verify = config.SME_TLS_VERIFY
        m = mqtt_factory()
        m.setTls(use_tls, bool(verify))
        m.setServer(host, port)
        m.setCallback(self._on_message)
        m.setKeepAlive(config.SME_MQTT_KEEPALIVE)
        m.setSocketTimeout(15)
        self._mqtt = m

    def connect(self):
        if self._mqtt.connected():
            return True
        ok = self._mqtt.connect(self._client_id, self._user, self._pass,
                                self._topic_status, 1, True, '{"status":"offline"}', False)
        if not ok:
            _debug("mqtt connect failed, state %d", self._mqtt.state())
            return False
        # Subscribe FIRST, then say "online" (as in the Arduino SDK): the backend
        # answers "online" with the stored pin values at once, and the broker handles
        # this client's packets in order, so the subscription always exists by then.
        self._mqtt.subscribe(self._topic_cmd, 1)                              # commands at QoS 1
        self._mqtt.publish(self._topic_status, '{"status":"online"}', True)   # birth, retained
        _debug("mqtt connected")
        return True

    def isConnected(self):
        return self._mqtt is not None and self._mqtt.connected()

    def state(self):
        return self._mqtt.state() if self._mqtt is not None else -1

    def publishPresence(self):
        """Retained "online" again, so the broker's status stays online while the device is live."""
        if not self.isConnected():
            return False
        return self._mqtt.publish(self._topic_status, '{"status":"online"}', True)

    def loop(self):
        self._mqtt.loop()

    def publishData(self, payload):
        if not self.isConnected() or payload is None:
            return False
        return self._mqtt.publish(self._topic_data, payload)

    def _on_message(self, topic, payload):
        if len(payload) == 0 or len(payload) > config.SME_JSON_CAPACITY:
            return
        try:
            doc = _json.loads(payload)
        except _json.ParseError:
            return
        if not isinstance(doc, dict):
            return
        command = doc.get("command")
        if not isinstance(command, str) or self._core is None:
            return
        pin = _pin_of(command)
        if pin is None:
            return        # non-pin command: nothing to do, nothing to ack
        self._core._handleIncoming(pin, _value_text(doc))


# ---- the SDK (src/SMEAIoT.cpp) ------------------------------------------------------

_LOGO = [
    "  _____ __  __ ______            _____   _______",
    " / ____|  \\/  |  ____|     /\\   |_   _| |__   __|",
    "| (___ | \\  / | |__       /  \\    | |  ___ | |",
    " \\___ \\| |\\/| |  __|     / /\\ \\   | | / _ \\| |",
    " ____) | |  | | |____   / ____ \\ _| || (_) | |",
    "|_____/|_|  |_|______| /_/    \\_\\_____\\___/|_|",
]


class SMEClass(object):
    def __init__(self):
        self.clock = SMEClock()
        self._callbacks = {}
        self._banner = None
        self._base_url = None
        self._out = None
        self._reset()

    def _reset(self):
        self._http = SMEHttp()
        self._mqtt = SMEMqtt()
        self._engine = SyncEngine()
        self._rate = RateLimiter()
        self._dash = self._token = self._fw = None
        self._device_id = ""
        self._mqtt_host = ""
        self._mqtt_port = 1883
        self._mqtt_tls = False
        self._mqtt_user = ""
        self._mqtt_pass = ""
        self._started = False
        self._clock_valid = False
        self._ntp_started = False
        self._ntp_wait_said = False
        self._ntp_slow_said = False
        self._registered = False
        self._mqtt_configured = False
        self._last_mqtt_active = False
        self._last_register = 0
        self._last_time_kick = 0
        self._ntp_since = 0
        self._last_flush = 0
        self._last_resync = 0
        self._last_cmd_poll = 0
        self._last_heartbeat = 0
        self._last_mqtt_try = 0
        self._mqtt_backoff = config.SME_MQTT_BACKOFF_MIN
        self._need_resync = False
        self._resync_active = False
        self._resync_cursor = 0
        self._ackq = []
        self._msgq = []
        self._last_msg_try = 0
        self._wifi_was_up = False
        self._cloud_fail_said = False
        self._last_beacon = 0
        self._flush_asap = False
        self._holding = False
        self._online_at = 0
        self._mqtt_up_said = False
        self._mqtt_down_said = False
        self._first_data_said = False
        self._messenger_pin = -1
        self._line = ""

    # ---- setup -------------------------------------------------------------------

    def setServerUrl(self, url):
        """Point at another server before begin(). Default: the SME AIoT cloud."""
        if url:
            self._base_url = url

    def banner(self, on):
        """False: no SME AIoT logo at start-up. Call before begin()."""
        self._banner = bool(on)

    def setPrint(self, stream):
        """Like #define SME_PRINT Serial: SME.setPrint(sys.stdout) shows the logo and
        plain status lines. None: silent (the default)."""
        config.SME_PRINT = stream

    def begin(self, dashboard_id, token, *rest):
        """Start the SDK. The same forms as on the board:

            SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)
            SME.begin(DASHBOARD_ID, DEVICE_TOKEN)                  # sends SME_FIRMWARE_VERSION
            SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION, ssid, password)
            SME.begin(DASHBOARD_ID, DEVICE_TOKEN, ssid, password)

        WiFi name/password are accepted so board sketches port 1:1, and ignored:
        on Linux the operating system keeps the network up."""
        if len(rest) in (1, 3):
            firmware_version = rest[0]
        elif len(rest) in (0, 2):
            firmware_version = None
        else:
            raise TypeError("begin(dashboard_id, token[, firmware_version][, ssid, password])")
        fw = firmware_version if firmware_version is not None else config.SME_FIRMWARE_VERSION
        # Like SMEClass::_start(): nothing else is reset, so settings made before
        # begin() (global deadband, messenger, queued messages, ...) stay.
        self._dash, self._token, self._fw = dashboard_id, token, fw
        self._out = config.SME_PRINT
        if self._out is None:   # SME_PRINT = True in the program: like  #define SME_PRINT Serial
            import sys
            m = sys.modules.get("__main__")
            p = getattr(m, "SME_PRINT", None) if m is not None else None
            self._out = sys.stdout if p is True else (p if callable(getattr(p, "write", None)) else None)
        base = self._base_url or config.SME_BASE_URL

        banner = config.SME_BANNER if self._banner is None else self._banner
        if self._out is not None and banner:
            w = self._out.write
            w("\n")
            for line in _LOGO:
                w(line + "\n")
            w("\n")
            w("v%s on %s\n" % (config.SME_SDK_VERSION, _p.board_name()))
            w("Firmware: %s\n" % (fw if fw else ""))
            w("\n")
            self._flush_out()

        _debug("starting")
        _debug("server: %s", base)
        self._engine.begin()
        self._rate.begin()
        self._http.begin(base, token, dashboard_id, fw)
        self._started = True

    # ---- the loop ----------------------------------------------------------------

    def run(self):
        """Keep it first in your loop: the timers, the app's commands (SME_LISTEN), the Messenger and the
        cloud link. It rests a moment (SME_RUN_IDLE_MS) so `while True: SME.run()` keeps a core free."""
        self._run_once()
        _p.idle(config.SME_RUN_IDLE_MS)

    def _run_once(self):
        self.clock.run()
        if self._messenger_pin >= 0:
            self._read_messenger_console()
        if not self._started:
            return

        wifi_up = _p.network_up()
        if wifi_up != self._wifi_was_up:
            if wifi_up:
                self._say("Network connected, IP ", _p.local_ip() or "")
                if not self._registered:
                    self._say("Connecting to SME AIoT cloud...")
            else:
                self._say("Network lost, reconnecting...")
            self._wifi_was_up = wifi_up
        if not wifi_up:
            return

        if not self._time_ready():
            return

        if not self._registered:
            self._handle_registration()
            if not self._registered:
                return

        mqtt_active = False
        if self._mqtt_configured:
            if self._mqtt.isConnected():
                self._mqtt.loop()             # commands arrive on the callback; keepalive pings ride here
                mqtt_active = True
                self._mqtt_backoff = config.SME_MQTT_BACKOFF_MIN
                # presence beacon: a retained "online" again, so an idle device stays online in the app
                if _p.millis() - self._last_beacon >= config.SME_PRESENCE_BEACON_INTERVAL:
                    self._last_beacon = _p.millis()
                    self._mqtt.publishPresence()
            else:
                if self._mqtt_up_said:
                    self._say("MQTT link lost - reconnecting...")
                    self._mqtt_up_said = False
                now = _p.millis()
                if now - self._last_mqtt_try >= self._mqtt_backoff:
                    self._last_mqtt_try = now
                    self._http.closeTls()
                    if self._mqtt.connect():
                        mqtt_active = True
                        self._mqtt_backoff = config.SME_MQTT_BACKOFF_MIN
                        self._need_resync = True   # fresh link: push the full state once
                        self._flush_asap = True    # and at once
                        # the cloud answers "online" with the stored pin values: apply them first
                        self._holding = True
                        self._online_at = _p.millis()
                        if not self._mqtt_up_said:
                            self._say("MQTT connected - live updates on; unplugged board shows offline in ~15s")
                            self._say("Getting the latest values from the cloud...")
                            self._mqtt_up_said = True
                            self._mqtt_down_said = False
                    else:
                        if not self._mqtt_down_said:
                            self._say("MQTT connect FAILED (state %d) - staying on HTTP, will retry" % self._mqtt.state())
                            self._mqtt_down_said = True
                        self._mqtt_backoff = min(self._mqtt_backoff << 1,
                                                 config.SME_MQTT_BACKOFF_MAX)

        # fell back from MQTT to HTTPS: push the state again and say "alive" at once
        if not mqtt_active and self._last_mqtt_active:
            self._need_resync = True
            self._flush_asap = True
            self._last_heartbeat = None
        self._last_mqtt_active = mqtt_active

        self._http.setKeepAlive(not mqtt_active)

        if self._holding and (not mqtt_active or _p.millis() - self._online_at >= config.SME_ONLINE_HOLD):
            self._holding = False

        if not self._holding:
            self._flush_message(mqtt_active)
            self._flush_telemetry(mqtt_active)

        if not mqtt_active:
            self._poll_commands_http()
            if config.SME_HTTP_HEARTBEAT:
                now = _p.millis()
                if self._last_heartbeat is None or now - self._last_heartbeat >= config.SME_HEARTBEAT_INTERVAL:
                    self._last_heartbeat = now
                    self._http.sendHeartbeat(_p.local_ip() or "0.0.0.0")

        self._drain_acks()

    def run_forever(self, interval=0.005):
        """The same as `while True: SME.run()`. Stop with Ctrl+C."""
        while True:
            self.run()

    def _time_ready(self):
        if self._clock_valid:
            return True
        now = _p.millis()
        if not self._ntp_started or now - self._last_time_kick >= config.SME_TIME_RETRY_INTERVAL:
            if not self._ntp_started:
                self._ntp_since = now
            self._ntp_started = True
            self._last_time_kick = now
            _debug("time: waiting for the system clock")
        if _p.wall_time() >= config.SME_TIME_VALID_EPOCH:
            self._clock_valid = True
            _debug("time synced")
            if self._ntp_wait_said:
                self._say("Time synced")
            return True
        if not self._ntp_wait_said:
            self._say("Waiting for time...")
            self._ntp_wait_said = True
        elif not self._ntp_slow_said and now - self._ntp_since >= config.SME_TIME_SLOW_WARN:
            self._say("Still no time. Is NTP (UDP 123) blocked? Falling back to server time over HTTP.")
            self._ntp_slow_said = True
        return False

    def _handle_registration(self):
        now = _p.millis()
        if now - self._last_register < config.SME_REGISTER_INTERVAL:
            return
        self._last_register = now
        _debug("registering device")
        self._say("Verifying device with the cloud...")
        r = self._http.registerDevice()
        if r is None:
            if not self._cloud_fail_said:
                self._say("Could not connect to SME AIoT cloud, retrying...")
            self._cloud_fail_said = True
            return
        self._cloud_fail_said = False
        (self._device_id, self._mqtt_host, self._mqtt_port, self._mqtt_tls,
         self._mqtt_user, self._mqtt_pass) = r
        self._say("Device verified & registered with the cloud")
        self._say("Device ID: ", self._device_id)
        _debug("registered: %s", self._device_id)
        if self._mqtt_host:
            self._mqtt.setCore(self)
            self._mqtt.configure(self._mqtt_host, self._mqtt_port, self._device_id, self._token,
                                 self._mqtt_tls, self._mqtt_user, self._mqtt_pass)
            self._mqtt_configured = True
            self._say("Server offered a real-time channel (MQTT) - connecting...")
            _debug("mqtt available, using it")
        else:
            self._say("Server offered NO MQTT - using HTTP (offline shows after ~40s)")
            _debug("no mqtt, using http")
        self._registered = True
        self._need_resync = True
        self._flush_asap = True
        self._last_resync = now
        self._last_heartbeat = None

    def _flush_telemetry(self, mqtt_active):
        now = _p.millis()
        # the very first snapshot after going online skips the 200 ms window
        if not self._flush_asap and now - self._last_flush < config.SME_FLUSH_INTERVAL:
            return
        if not self._resync_active:
            due = self._need_resync
            if (not due and config.SME_FULL_RESYNC_INTERVAL > 0 and
                    now - self._last_resync >= config.SME_FULL_RESYNC_INTERVAL):
                due = True
            if due:
                self._resync_active = True
                self._resync_cursor = 0
                self._need_resync = False
        if not self._engine.has_dirty() and not self._resync_active:
            return
        if not self._rate.take():
            return
        self._last_flush = now

        tp = {}
        if self._resync_active:
            written, self._resync_cursor = self._engine.flush_slice(
                tp, self._resync_cursor, config.SME_RESYNC_BATCH, now & 0xFFFFFFFF)
            if self._resync_cursor >= self._engine.slot_capacity:
                self._resync_active = False
                self._last_resync = now
        else:
            written = self._engine.flush_dirty(tp, now & 0xFFFFFFFF)
        if written == 0:
            return
        payload = _json.dumps({"tpPins": tp})
        sent = self._mqtt.publishData(payload) if mqtt_active else self._http.sendData(payload)
        if sent:
            self._flush_asap = False
            if not self._first_data_said:
                self._say("First data sent - check the app graph")
                self._first_data_said = True

    def _poll_commands_http(self):
        now = _p.millis()
        if now - self._last_cmd_poll < config.SME_COMMAND_POLL_INTERVAL:
            return
        self._last_cmd_poll = now
        if not self._http.fetchCommands():
            return
        handled = 0
        while handled < config.SME_MAX_CMDS_PER_TICK:
            c = self._http.nextCommand()
            if c is None:
                break
            pin, value, cmd_id = c
            self._handleIncoming(pin, value)
            if cmd_id:
                self._ack_command(cmd_id)
            handled += 1

    def _ack_command(self, cmd_id):
        if not cmd_id or len(self._ackq) >= config.SME_ACK_QUEUE:
            return
        self._ackq.append(cmd_id)

    def _drain_acks(self):
        done = 0
        while self._ackq and done < config.SME_MAX_CMDS_PER_TICK:
            self._http.markExecuted(self._ackq.pop(0))
            done += 1

    # ---- values ------------------------------------------------------------------

    def publish(self, pin, value):
        """Queue a value for the next batched sync. Call it as often as you like;
        only the latest value per pin goes out. bool -> 1/0, int -> whole number,
        float -> 32-bit float (as on the board), dict/list -> JSON text, anything
        else -> text."""
        if not isinstance(pin, int) or pin < 0 or pin > 255:
            return
        if isinstance(value, bool):
            self._engine.set_int(pin, 1 if value else 0)
        elif isinstance(value, int):
            self._engine.set_int(pin, value)
        elif isinstance(value, float):
            self._engine.set_float(pin, value)
        elif isinstance(value, (dict, list, tuple)):
            self._engine.set_string(pin, _json.dumps(value))    # JSON text
        else:
            self._engine.set_string(pin, "" if value is None else str(value))

    def attach(self, pin, callback):
        if isinstance(pin, int) and 0 <= pin < config.SME_MAX_PINS:
            self._callbacks[pin] = callback

    def listen(self, pin):
        """Decorator, like SME_LISTEN(TP0): the function runs with the value
        (an SMEData) each time the dashboard writes that pin."""
        def deco(fn):
            self.attach(pin, fn)
            return fn
        return deco

    def setDeadband(self, a, b=None):
        if b is None:
            self._engine.set_deadband_all(a)
        else:
            self._engine.set_deadband(a, b)

    def setMinInterval(self, a, b=None):
        if b is None:
            self._engine.set_min_interval_all(a)
        else:
            self._engine.set_min_interval(a, b)

    def connected(self):
        """True once the device is registered with the cloud."""
        return self._registered

    def mqttConnected(self):
        """True while the real-time MQTT link is up (False on the HTTPS fallback)."""
        return self._mqtt_configured and self._mqtt.isConnected()

    # ---- board helpers, the same names as on NuttyFi --------------------------------

    def led(self, on):
        """The board's status LED (Raspberry Pi: the green ACT LED). Needs sudo to write it.
        Returns False when this board has no LED it may switch."""
        return _p.led(on)

    def ledState(self):
        return _p.led_state()

    def _handleIncoming(self, pin, value):
        if pin >= config.SME_MAX_PINS:
            return
        if pin == self._messenger_pin:
            _p.console_write("[APP -> DEVICE] %s\n" % value)
        cb = self._callbacks.get(pin)
        if cb:
            cb(SMEData(value))

    # ---- messenger -----------------------------------------------------------------

    def messenger(self, pin):
        """Join the console and the Messenger widget on pin: a line typed + Enter
        goes to the app, messages from the app are printed as [APP -> DEVICE]."""
        if isinstance(pin, int) and 0 <= pin < config.SME_MAX_PINS:
            self._messenger_pin = pin

    def sendMessage(self, pin, text):
        """Send one message to the Messenger widget on pin. Sent once (never resent
        after a reconnect), up to SME_MSG_MAX bytes. False for empty text, a bad pin
        or a full queue."""
        if not isinstance(pin, int) or pin < 0 or pin >= config.SME_MAX_PINS or not text:
            return False
        text = str(text).split("\x00", 1)[0]
        if not text:
            return False
        if len(self._msgq) >= config.SME_MSG_QUEUE:
            self._say("Message queue full, message dropped")
            return False
        text = clip_utf8(text, config.SME_MSG_MAX)
        self._msgq.append([pin, 0, text])
        if SMEData(text).isFloat():
            self._say('Message "', text, '" is a plain number: the app shows it as a value, not chat')
        return True

    def _read_messenger_console(self):
        for c in _p.console_read():
            if c in "\n\r":
                s = self._line.strip(" \t")
                if s:
                    self.sendMessage(self._messenger_pin, s)
                self._line = ""
            elif len(self._line.encode("utf-8")) < config.SME_MSG_MAX:
                self._line += c

    def _flush_message(self, mqtt_active):
        if not self._msgq:
            return
        now = _p.millis()
        head = self._msgq[0]
        if head[1] > 0 and now - self._last_msg_try < config.SME_MSG_RETRY_GAP:
            return
        if not self._rate.take():
            return
        self._last_msg_try = now
        pin, _, text = head
        payload = _json.dumps({"tpPins": {str(pin): text}})
        ok = self._mqtt.publishData(payload) if mqtt_active else self._http.sendData(payload)
        if ok:
            if pin == self._messenger_pin:
                _p.console_write("[DEVICE -> APP] %s\n" % text)
        else:
            head[1] += 1
            if head[1] < config.SME_MSG_TRIES:
                return
            self._say("Message not sent: ", text)
        self._msgq.pop(0)

    # ---- output --------------------------------------------------------------------

    def _say(self, a, b=None, c=None):
        if self._out is None:
            return
        self._out.write("[SME] " + a + (b or "") + (c or "") + "\n")
        self._flush_out()

    def _flush_out(self):
        try:
            self._out.flush()
        except Exception:
            pass


SME = SMEClass()

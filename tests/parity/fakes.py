"""Fakes for the Python SDK, mirroring the Arduino SDK's test/fakes: a pretend
clock, network, console, HTTPS backend and MQTT client that record everything."""

import smeaiot
from smeaiot import config, core
from smeaiot import platform as P


class World(object):
    def __init__(self):
        self.now = 100000
        self.epoch = 1800000000
        self.wifi = True
        self.events = []                 # (kind, text)
        self.codes = {}
        self.cmds = []
        self.mqtt_host = ""
        self.console_in = ""
        self.mqtt = None                 # the client the SDK made
        self.mq = None                   # its state (MqttState), from start-up

    def ev(self, kind, text):
        self.events.append((kind, text))


W = World()

K_HTTP, K_CONNECT, K_SUB, K_PUB, K_CB, K_OUT = range(6)


class FakeHttp(object):
    def __init__(self):
        self.open = False

    def connected(self):
        return self.open

    def close(self):
        self.open = False

    def request(self, method, url, headers, body, timeout_ms, keep_alive):
        self.open = True
        h = "".join("%s=%s;" % (k, headers[k]) for k in sorted(headers))
        b = body.decode("utf-8") if body is not None else ""
        W.ev(K_HTTP, "HTTP %s %s %s %s" % (method, url, h, b))
        for suffix, code in sorted(W.codes.items()):
            if url.endswith(suffix) and code != 200:
                return code, b'{"message":"no"}'
        if url.endswith("/devices/register"):
            d = '{"data":{"device_id":"dev-123"'
            if W.mqtt_host:
                d += (',"mqtt_broker":"%s","mqtt_port":8883,"mqtt_tls":true,'
                      '"mqtt_username":"mq-user","mqtt_password":"mq-pass"' % W.mqtt_host)
            return 200, (d + "}}").encode()
        if url.endswith("/commands") and method == "GET":
            if not W.cmds:
                return 200, b'{"data":[]}'
            return 200, ('{"data":' + W.cmds.pop(0) + "}").encode()
        return 200, b"{}"


class MqttState(object):
    """Like the C++ SDK's PubSubClient member: exists from start-up, so a test can
    set it up before the SDK registers."""
    def __init__(self):
        self.accept_connect = True
        self.is_connected = False
        self.publish_ok = True


class FakeMqtt(object):
    def __init__(self):
        self.st = W.mq
        self.callback = None
        self.host, self.port, self.tls, self.keepalive = None, 0, False, 0
        W.mqtt = self

    def setServer(self, h, p):
        self.host, self.port = h, p

    def setTls(self, use_tls, verify):
        self.tls = use_tls

    def setCallback(self, cb):
        self.callback = cb

    def setKeepAlive(self, s):
        self.keepalive = s

    def setSocketTimeout(self, s):
        pass

    def connect(self, cid, user, pw, wt, wq, wr, wm, clean):
        self.st.is_connected = self.st.accept_connect
        W.ev(K_CONNECT, "CONNECT %s:%d tls=%d id=%s user=%s pass=%s will=%s|%d|%d|%s clean=%d keepalive=%d ok=%d"
             % (self.host, self.port, 1 if self.tls else 0, cid, user, pw, wt, wq, 1 if wr else 0, wm,
                1 if clean else 0, self.keepalive, 1 if self.st.is_connected else 0))
        return self.st.is_connected

    def connected(self):
        return self.st.is_connected

    def state(self):
        return 0 if self.st.is_connected else -2

    def publish(self, topic, payload, retained=False):
        if not self.st.is_connected:
            return False
        W.ev(K_PUB, "PUB %s %d %s" % (topic, 1 if retained else 0, payload))
        return self.st.publish_ok

    def subscribe(self, topic, qos):
        W.ev(K_SUB, "SUB %s %d" % (topic, qos))
        return True

    def loop(self):
        return self.st.is_connected

    def deliver(self, payload):
        if self.callback:
            self.callback("smeiot/devices/dev-123/commands", payload.encode("utf-8"))


class FakeOut(object):
    def __init__(self):
        self.buf = ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            W.ev(K_OUT, "OUT " + line)

    def flush(self):
        pass


OUT = FakeOut()


def install():
    P.millis = lambda: W.now
    P.wall_time = lambda: W.epoch
    P.network_up = lambda: W.wifi
    P.local_ip = lambda: "192.168.1.50"
    P.mac_address = lambda: "AA:BB:CC:DD:EE:FF"

    def read():
        s, W.console_in = W.console_in, ""
        return s
    P.console_read = read
    P.console_write = OUT.write
    P.Http = FakeHttp
    core.mqtt_factory = FakeMqtt
    config.SME_PRINT = OUT
    P.idle = lambda ms: None          # no real rests in the simulated time
    config.SME_DEVICE_TYPE = "NuttyFi32 (ESP32)"     # the C++ driver is built as ESP32
    config.SME_BOARD_NAME = "NuttyFi32"


def reboot():
    """A fresh SME, as after a reboot; handlers stay (as on a board)."""
    callbacks = smeaiot.SME._callbacks
    smeaiot.SME.__init__()
    smeaiot.SME._callbacks = callbacks
    W.mqtt = None
    W.mq = MqttState()
    # as fresh_sme() in the C++ tests: WiFi back up, console input cleared
    W.wifi = True
    W.console_in = ""
    OUT.buf = ""

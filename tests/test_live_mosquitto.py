"""End-to-end test over real sockets: a real Mosquitto broker (TLS) and a local
HTTPS backend that behaves like SME AIoT (register, data, commands, executed,
heartbeat; on "online" it sends the stored pin values).

Needs a mosquitto binary (PATH, or SME_MOSQUITTO=/path/to/mosquitto) and openssl.
Skipped otherwise.
"""

import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import paho.mqtt.client as paho   # noqa: E402

MOSQ = os.environ.get("SME_MOSQUITTO") or shutil.which("mosquitto")
pytestmark = pytest.mark.skipif(not MOSQ or not shutil.which("openssl"),
                                reason="needs mosquitto and openssl")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    d = tmp_path_factory.mktemp("certs")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                    "-keyout", str(d / "key.pem"), "-out", str(d / "cert.pem"),
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"],
                   check=True, capture_output=True)
    return d


class Broker(object):
    def __init__(self, certs, tmp):
        self.tls_port, self.plain_port = free_port(), free_port()
        self.conf = tmp / "mosquitto.conf"
        root = "user root\n" if hasattr(os, "geteuid") and os.geteuid() == 0 else ""
        self.conf.write_text(
            root + "per_listener_settings false\nallow_anonymous true\npersistence false\n"
            "listener %d 127.0.0.1\n"
            "listener %d 127.0.0.1\ncertfile %s\nkeyfile %s\n"
            % (self.plain_port, self.tls_port, certs / "cert.pem", certs / "key.pem"))
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen([MOSQ, "-c", str(self.conf)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.plain_port), 0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("mosquitto did not start")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(5)
            self.proc = None


class Backend(object):
    """The SME AIoT backend, as far as a device can see it."""

    def __init__(self, certs, broker):
        self.requests = []              # (method, path, headers, body)
        self.pending = []               # commands for GET /commands
        self.stored = {"tp0": "0"}      # latest dashboard values
        self.mqtt_seen = []             # (topic, payload, retained)
        self.reply_delay = 0.3          # how long the backend takes to answer "online"
        self.broker = broker
        be = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _reply(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n).decode() if n else ""

            def do_POST(self):
                body = self._body()
                be.requests.append(("POST", self.path, dict(self.headers), body))
                if self.path == "/api/devices/register":
                    return self._reply(200, {"data": {
                        "device_id": "dev-1", "mqtt_broker": "localhost",
                        "mqtt_port": be.broker.tls_port, "mqtt_tls": True,
                        "mqtt_username": "dev-user", "mqtt_password": "dev-pass"}})
                return self._reply(200, {"success": True})

            def do_GET(self):
                be.requests.append(("GET", self.path, dict(self.headers), ""))
                if self.path.endswith("/commands"):
                    cmds, be.pending = be.pending, []
                    return self._reply(200, {"data": cmds})
                return self._reply(404, {})

        class S(ThreadingMixIn, HTTPServer):
            daemon_threads = True

        self.port = free_port()
        self.httpd = S(("127.0.0.1", self.port), H)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(certs / "cert.pem"), str(certs / "key.pem"))
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.mq = None

    def mqtt_start(self):
        if hasattr(paho, "CallbackAPIVersion"):
            c = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id="backend")
        else:
            c = paho.Client(client_id="backend")

        def on_message(cl, ud, msg):
            payload = msg.payload.decode()
            self.mqtt_seen.append((msg.topic, payload, bool(msg.retain)))
            if msg.topic.endswith("/status") and json.loads(payload).get("status") == "online":
                def send_stored():                    # Option A: send the stored values
                    for k, v in self.stored.items():
                        cl.publish("smeiot/devices/dev-1/commands",
                                   json.dumps({"id": "s-" + k, "command": k, "value": v}), qos=1)
                if self.reply_delay:
                    threading.Timer(self.reply_delay, send_stored).start()
                else:
                    send_stored()

        c.on_message = on_message
        c.on_connect = lambda cl, ud, f, rc, *a: cl.subscribe("smeiot/devices/dev-1/#", 1)
        c.connect("127.0.0.1", self.broker.plain_port)
        c.loop_start()
        self.mq = c

    def mqtt_stop(self):
        if self.mq:
            self.mq.loop_stop()
            self.mq.disconnect()
            self.mq = None

    def paths(self, method=None):
        return [r[1] for r in self.requests if method is None or r[0] == method]


def run_until(sme, cond, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        sme.run()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def world(certs, tmp_path):
    import smeaiot
    from smeaiot import config
    saved = {k: getattr(config, k) for k in dir(config) if k.startswith("SME_")}
    config.SME_TLS_VERIFY = 0          # self-signed test certificates
    config.SME_MQTT_BACKOFF_MAX = 2000
    config.SME_DEVICE_TYPE = "SME-Device"
    broker = Broker(certs, tmp_path)
    broker.start()
    backend = Backend(certs, broker)
    backend.mqtt_start()
    time.sleep(0.2)
    smeaiot.SME.__init__()
    yield smeaiot, backend, broker
    try:
        if smeaiot.SME._mqtt._mqtt:
            smeaiot.SME._mqtt._mqtt.disconnect()
    except Exception:
        pass
    backend.mqtt_stop()
    backend.httpd.shutdown()
    broker.stop()
    for k, v in saved.items():
        setattr(config, k, v)


def test_full_cycle_over_real_sockets(world):
    smeaiot, be, broker = world
    SME = smeaiot.SME
    got = []
    SME.attach(0, lambda d: got.append(("tp0", d.toString())))
    SME.attach(2, lambda d: got.append(("tp2", d.toString())))

    SME.setServerUrl("https://localhost:%d/api" % be.port)
    SME.begin("PROJ-LIVE0001", "SME-LIVE-TOKEN", "1.2.3")

    # 1. registration over HTTPS, the same JSON body as a board
    assert run_until(SME, lambda: SME.connected(), 10)
    method, path, headers, body = be.requests[0]
    assert (method, path) == ("POST", "/api/devices/register")
    reg = json.loads(body)
    assert list(reg) == ["dashboard_id", "token", "device_type", "firmware_version",
                         "mac_address", "ip_address"]
    assert reg["dashboard_id"] == "PROJ-LIVE0001" and reg["token"] == "SME-LIVE-TOKEN"
    assert reg["firmware_version"] == "1.2.3" and reg["device_type"] == "SME-Device"
    assert len(reg["mac_address"]) == 17 and reg["mac_address"].upper() == reg["mac_address"]
    assert "Authorization" not in headers

    # 2. MQTT over TLS: retained "online", then the backend sends the stored value
    assert run_until(SME, lambda: ("tp0", "0") in got, 10), got
    online = [m for m in be.mqtt_seen if m[0] == "smeiot/devices/dev-1/status"]
    assert online[0][1] == '{"status":"online"}'

    # 3. a live dashboard command arrives over MQTT straight away
    be.mq.publish("smeiot/devices/dev-1/commands", '{"id":"c1","command":"tp2","value":"on"}', qos=1)
    assert run_until(SME, lambda: ("tp2", "on") in got, 5)

    # 4. values go up on the data topic, batched, ArduinoJson number format
    SME.publish(1, 23.5)
    SME.publish(3, 23.456789)
    SME.publish(4, "hello")
    assert run_until(SME, lambda: any(m[0].endswith("/data") for m in be.mqtt_seen), 5)
    data = [m for m in be.mqtt_seen if m[0].endswith("/data")]
    assert data[-1][1] == '{"tpPins":{"1":23.5,"3":23.45679,"4":"hello"}}'
    assert data[-1][2] is False
    assert not [p for p in be.paths() if p.endswith("/data")]   # nothing over HTTPS

    # 5. broker down -> HTTPS fallback: data POSTed, commands polled and acked
    broker.stop()
    be.mqtt_stop()
    be.pending.append({"id": "h1", "command": "tp2", "value": "fallback"})
    SME.publish(1, 99)
    assert run_until(SME, lambda: ("tp2", "fallback") in got, 10), got
    assert run_until(SME, lambda: "/api/devices/dev-1/commands/h1/executed" in be.paths("POST"), 5)
    posted = [r for r in be.requests if r[1] == "/api/devices/dev-1/data"]
    assert posted and json.loads(posted[0][3])["tpPins"]["1"] == 99
    assert posted[0][2]["Authorization"] == "Device SME-LIVE-TOKEN"
    assert "/api/devices/dev-1/heartbeat" in be.paths("POST")

    # 6. broker back -> MQTT again, the stored values arrive again
    be.stored = {"tp0": "1"}
    broker.start()
    be.mqtt_start()
    time.sleep(0.2)
    assert run_until(SME, lambda: ("tp0", "1") in got, 15), got

    # 7. the Last Will: the link dies without a goodbye -> broker says offline
    be.mqtt_seen.clear()
    SME._mqtt._mqtt._c.socket().close()
    deadline = time.time() + 5
    while time.time() < deadline and not any(
            m[0].endswith("/status") and "offline" in m[1] for m in be.mqtt_seen):
        time.sleep(0.05)
    assert any(m[0].endswith("/status") and m[1] == '{"status":"offline"}' for m in be.mqtt_seen)


def test_pinned_root_refuses_an_unknown_certificate(world, capsys):
    smeaiot, be, broker = world
    from smeaiot import config
    config.SME_TLS_VERIFY = 1                     # the default: only ISRG Root X1
    config.SME_PRINT = sys.stdout
    SME = smeaiot.SME
    SME.banner(False)
    SME.setServerUrl("https://localhost:%d/api" % be.port)
    SME.begin("PROJ-LIVE0001", "SME-LIVE-TOKEN", "1.2.3")
    run_until(SME, lambda: False, 1.5)
    assert not SME.connected()
    assert not be.requests                         # the handshake never got to HTTP
    out = capsys.readouterr().out
    assert "[SME] Could not connect to SME AIoT cloud, retrying..." in out


# A backend that answers "online" instantly, with no saved broker session (a first
# connection): the stored value must still arrive. Failed before the fix, when the
# device said "online" before subscribing.
def test_stored_values_arrive_even_when_backend_answers_online_instantly(world):
    smeaiot, be, broker = world
    be.reply_delay = 0                            # answer "online" instantly
    SME = smeaiot.SME
    got = []
    SME.attach(0, lambda d: got.append(d.toString()))
    SME.setServerUrl("https://localhost:%d/api" % be.port)
    SME.begin("PROJ-LIVE0001", "SME-LIVE-TOKEN", "1.2.3")
    assert run_until(SME, lambda: got == ["0"], 5), got
    # the broker saw the subscription before "online"
    assert [m for m in be.mqtt_seen if m[0].endswith("/status")][0][1] == '{"status":"online"}'

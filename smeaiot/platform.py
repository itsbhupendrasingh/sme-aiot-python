"""What the board gets from its hardware, for Linux: millis(), the wall clock,
"is the network up", the IP and MAC address, the console (the board's Serial),
and the HTTPS socket. Tests replace these functions with fakes."""

import os
import select
import socket
import ssl
import sys
import time

try:                                   # Python 3
    import http.client as _httplib
    from urllib.parse import urlsplit
except ImportError:                    # pragma: no cover
    import httplib as _httplib         # type: ignore
    from urlparse import urlsplit      # type: ignore

from . import config
from .certs import SME_ROOT_CA_PEM

_T0 = time.monotonic()


def millis():
    """Milliseconds since the SDK was loaded (the board's millis())."""
    return int((time.monotonic() - _T0) * 1000) + 1000000


def wall_time():
    """The real date, seconds since 1970 (the board's time() after NTP)."""
    return time.time()


# ---- network ----------------------------------------------------------------

_net_cache = {"at": -10000, "ip": None}


def _probe_ip():
    # A UDP "connect" picks the outgoing interface without sending anything.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        return None if ip.startswith("0.") else ip
    except OSError:
        return None
    finally:
        s.close()


def local_ip():
    now = millis()
    if now - _net_cache["at"] >= 1000:      # at most once a second
        _net_cache["ip"] = _probe_ip()
        _net_cache["at"] = now
    return _net_cache["ip"]


def network_up():
    """Like WiFi.status() == WL_CONNECTED: there is a route to the internet."""
    return local_ip() is not None


def _default_iface():
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) > 2 and parts[1] == "00000000":
                    return parts[0]
    except OSError:
        pass
    return None


def mac_address():
    """The MAC of the interface that carries the default route, as
    "AA:BB:CC:DD:EE:FF" (WiFi.macAddress() format)."""
    iface = _default_iface()
    if iface:
        try:
            with open("/sys/class/net/%s/address" % iface) as f:
                mac = f.read().strip().upper()
                if mac and mac != "00:00:00:00:00:00":
                    return mac
        except OSError:
            pass
    import uuid
    n = uuid.getnode()
    return ":".join("%02X" % ((n >> s) & 0xFF) for s in range(40, -1, -8))


# ---- which board this is --------------------------------------------------------

_MODEL_FILES = ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model",
                "/sys/devices/virtual/dmi/id/product_name")


def board_model():
    """The board's own name, e.g. "Raspberry Pi 5 Model B Rev 1.0", "NVIDIA Jetson Nano Developer Kit",
    "Orange Pi 5", "Freescale i.MX8MQ Phanbell" (Google Coral). "" when unknown."""
    for f in _MODEL_FILES:
        try:
            with open(f, "rb") as h:
                m = h.read().replace(b"\x00", b"").decode("utf-8", "replace").strip()
        except OSError:
            continue
        if m and m.lower() not in ("to be filled by o.e.m.", "default string", "system product name"):
            return m
    return ""


def board_name():
    """For the logo (SME_BOARD_NAME, or the board's own name)."""
    from . import config
    if config.SME_BOARD_NAME:
        return config.SME_BOARD_NAME
    m = board_model()
    if "phanbell" in m.lower():
        m = "Google Coral Dev Board"
    return m or "Linux"


def device_type():
    """What the cloud is told (SME_DEVICE_TYPE, or "<board> (Linux)"), like "NuttyFi32 (ESP32)" on the board."""
    from . import config
    if config.SME_DEVICE_TYPE:
        return config.SME_DEVICE_TYPE
    n = board_name()
    return (n[:48] + " (Linux)") if n != "Linux" else "SME-Device (Linux)"


# ---- the board's status LED (Raspberry Pi ACT and other boards' status LEDs) ---------

_LEDS = ("/sys/class/leds/ACT", "/sys/class/leds/led0", "/sys/class/leds/user-led",
         "/sys/class/leds/status", "/sys/class/leds/pwr")
_led_on = [False]


def led(on):
    """True if the LED was set; False when the board has none or this needs sudo."""
    _led_on[0] = bool(on)
    for d in _LEDS:
        if not os.path.isdir(d):
            continue
        try:
            try:
                with open(d + "/trigger", "w") as f:
                    f.write("none")
            except OSError:
                pass
            with open(d + "/brightness", "w") as f:
                f.write("1" if on else "0")
            return True
        except OSError:
            return False
    return False


def led_state():
    return _led_on[0]


def idle(ms):
    """A short rest inside SME.run(), so a bare `while True: SME.run()` does not keep a CPU core busy."""
    if ms > 0:
        time.sleep(ms / 1000.0)


# ---- console (the board's Serial) ---------------------------------------------

def console_write(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def console_read():
    """Characters typed so far (non-blocking). "" when nothing is waiting."""
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, ValueError, OSError):
        return ""
    try:
        r, _, _ = select.select([fd], [], [], 0)
        if not r:
            return ""
        data = os.read(fd, 4096)
    except (OSError, ValueError):
        return ""
    return data.decode("utf-8", "replace")


# ---- TLS --------------------------------------------------------------------

def tls_context(verify):
    """verify=True: trust only the pinned root (as the board does), check the
    host name. verify=False: no checks (local testing only)."""
    if verify:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cadata=SME_ROOT_CA_PEM)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ---- HTTP -------------------------------------------------------------------

class Http(object):
    """One kept-alive HTTP(S) connection, like the board's WiFiClientSecure +
    HTTPClient with setReuse(true). request() returns (code, body): code > 0 is
    the HTTP status, code < 0 a connection error (as HTTPClient does)."""

    def __init__(self):
        self._conn = None
        self._key = None

    def connected(self):
        return self._conn is not None

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = None
        self._key = None

    def request(self, method, url, headers, body, timeout_ms, keep_alive):
        u = urlsplit(url)
        secure = u.scheme == "https"
        port = u.port or (443 if secure else 80)
        key = (u.scheme, u.hostname, port)
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        if self._conn is None or self._key != key:
            self.close()
            if secure:
                self._conn = _httplib.HTTPSConnection(
                    u.hostname, port, timeout=timeout_ms / 1000.0,
                    context=tls_context(bool(config.SME_TLS_VERIFY)))
            else:
                self._conn = _httplib.HTTPConnection(u.hostname, port, timeout=timeout_ms / 1000.0)
            self._key = key
        conn = self._conn
        conn.timeout = timeout_ms / 1000.0
        if conn.sock is not None:
            conn.sock.settimeout(conn.timeout)
        h = {"User-Agent": "SME-AIoT-Python/" + config.SME_SDK_VERSION,
             "Connection": "keep-alive" if keep_alive else "close"}
        h.update(headers)
        try:
            conn.request(method, path, body=body, headers=h)
            resp = conn.getresponse()
            data = resp.read()
            code = resp.status
            if resp.will_close or not keep_alive:
                self.close()
            return code, data
        except (OSError, _httplib.HTTPException, ssl.SSLError):
            self.close()
            return -1, b""

"""A PubSubClient-shaped wrapper around paho-mqtt.

The SDK core talks to this exactly as the board talks to PubSubClient: connect()
blocks until the broker answers (up to the 15 s socket timeout), loop() is called
from SME.run() and delivers incoming messages to the callback there, publish() is
QoS 0. MQTT 3.1.1, like PubSubClient.
"""

import time

import paho.mqtt.client as _paho

from .platform import tls_context

_PAHO2 = hasattr(_paho, "CallbackAPIVersion")


class MqttClient(object):
    def __init__(self):
        self._c = None
        self._host = None
        self._port = 1883
        self._tls = False
        self._verify = True
        self._keepalive = 15
        self._socket_timeout = 15
        self._callback = None
        self._connack = None
        self._lost = False
        self._state = -1           # PubSubClient: MQTT_DISCONNECTED

    # ---- PubSubClient setters ----
    def setServer(self, host, port):
        self._host, self._port = host, int(port)

    def setTls(self, use_tls, verify):
        self._tls, self._verify = bool(use_tls), bool(verify)

    def setCallback(self, cb):
        self._callback = cb

    def setKeepAlive(self, s):
        self._keepalive = int(s)

    def setSocketTimeout(self, s):
        self._socket_timeout = int(s)

    # ---- connection ----
    def _new(self, client_id, clean):
        if _PAHO2:
            c = _paho.Client(_paho.CallbackAPIVersion.VERSION2, client_id=client_id,
                             clean_session=clean, protocol=_paho.MQTTv311)
        else:                                   # paho-mqtt 1.x
            c = _paho.Client(client_id=client_id, clean_session=clean, protocol=_paho.MQTTv311)
        c.on_connect = self._on_connect
        c.on_message = self._on_message
        c.on_disconnect = self._on_disconnect
        try:
            c.connect_timeout = float(self._socket_timeout)
        except AttributeError:
            pass
        if self._tls:
            c.tls_set_context(tls_context(self._verify))
        return c

    def _on_connect(self, client, userdata, flags, rc, *args):
        code = getattr(rc, "value", rc)
        self._connack = int(code)

    def _on_disconnect(self, client, userdata, *args):
        self._state = -3           # MQTT_CONNECTION_LOST
        self._lost = True

    def _on_message(self, client, userdata, msg):
        if self._callback:
            self._callback(msg.topic, bytes(msg.payload))

    def connect(self, client_id, user, password, will_topic, will_qos, will_retain,
                will_msg, clean_session):
        self.disconnect()
        c = self._new(client_id, clean_session)
        c.username_pw_set(user, password)
        c.will_set(will_topic, will_msg, qos=will_qos, retain=will_retain)
        self._connack = None
        self._lost = False
        try:
            c.connect(self._host, self._port, keepalive=self._keepalive)
        except Exception:
            self._state = -2       # MQTT_CONNECT_FAILED
            return False
        deadline = time.monotonic() + self._socket_timeout
        while self._connack is None and time.monotonic() < deadline:
            if c.loop(timeout=0.05) != _paho.MQTT_ERR_SUCCESS and self._connack is None:
                break
        if self._connack != 0:
            self._state = -4 if self._connack is None else self._connack
            try:
                c.disconnect()
            except Exception:
                pass
            return False
        self._c = c
        self._state = 0
        return True

    def disconnect(self):
        if self._c is not None:
            try:
                self._c.disconnect()
            except Exception:
                pass
        self._c = None

    def connected(self):
        # paho 1.x can report connected after the link died, so also trust our
        # own disconnect flag.
        return self._c is not None and not self._lost and self._c.is_connected()

    def state(self):
        return 0 if self.connected() else self._state

    def publish(self, topic, payload, retained=False):
        if not self.connected():
            return False
        info = self._c.publish(topic, payload, qos=0, retain=retained)
        return info.rc == _paho.MQTT_ERR_SUCCESS

    def subscribe(self, topic, qos):
        if not self.connected():
            return False
        rc, _ = self._c.subscribe(topic, qos)
        return rc == _paho.MQTT_ERR_SUCCESS

    def loop(self):
        if self._c is None:
            return False
        rc = self._c.loop(timeout=0)
        if rc != _paho.MQTT_ERR_SUCCESS or self._lost or not self._c.is_connected():
            self._lost = True
            self._state = -3       # MQTT_CONNECTION_LOST
            try:
                self._c.disconnect()
            except Exception:
                pass
            self._c = None
            return False
        return True

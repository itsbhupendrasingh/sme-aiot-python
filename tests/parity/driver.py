"""Parity driver for the Python SDK: the same script language and the same
trace format as driver.cpp (see there)."""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smeaiot import SME             # noqa: E402
import fakes                       # noqa: E402
from fakes import W, K_CB          # noqa: E402


def f32bits(h):
    return struct.unpack("<f", struct.pack("<I", int(h, 16)))[0]


def f64bits(h):
    return struct.unpack("<d", struct.pack("<Q", int(h, 16)))[0]


def make_listener(n):
    def cb(data):
        W.ev(K_CB, "CB %d %s" % (n, data.toString()))
    return cb


def main(stream, out):
    fakes.install()
    for n in list(range(21)) + [127]:
        SME.attach(n, make_listener(n))
    fakes.reboot()

    def flush(tick):
        evs = sorted(enumerate(W.events), key=lambda e: (e[1][0], e[0]))
        for _, (_, text) in evs:
            out.write("%d %s\n" % (tick, text))
        W.events = []

    for raw in stream:
        line = raw.rstrip("\n")
        cmd, _, rest = line.partition(" ")
        tick = W.now
        if cmd == "offer_mqtt":
            W.mqtt_host = "" if rest == "-" else rest
        elif cmd == "wifi":
            W.wifi = rest == "1"
        elif cmd == "epoch":
            W.epoch = int(rest)
        elif cmd == "code":
            s, c = rest.split()
            W.codes[s] = int(c)
        elif cmd == "cmds":
            W.cmds.append(rest)
        elif cmd == "begin":
            SME.begin("PROJ-TEST0001", "SME-TEST-TOKEN-0001", rest or "0.0.1", "my-wifi", "wifi-pass")
        elif cmd == "begin_nofw":
            SME.begin("PROJ-TEST0001", "SME-TEST-TOKEN-0001", "my-wifi", "wifi-pass")
        elif cmd == "reboot":
            fakes.reboot()
        elif cmd == "run":
            for _ in range(0, int(rest), 10):
                tick = W.now
                SME.run()
                flush(tick)
                W.now += 10
            continue
        elif cmd == "pub_i":
            p, v = rest.split()
            SME.publish(int(p), int(v))
        elif cmd == "pub_f":
            p, h = rest.split()
            SME.publish(int(p), f32bits(h))
        elif cmd == "pub_d":
            p, h = rest.split()
            SME.publish(int(p), f64bits(h))
        elif cmd == "pub_b":
            p, v = rest.split()
            SME.publish(int(p), v != "0")
        elif cmd == "pub_s":
            p, _, t = rest.partition(" ")
            SME.publish(int(p), t)
        elif cmd == "deadband":
            p, h = rest.split()
            if int(p) < 0:
                SME.setDeadband(f32bits(h))
            else:
                SME.setDeadband(int(p), f32bits(h))
        elif cmd == "minint":
            p, ms = rest.split()
            if int(p) < 0:
                SME.setMinInterval(int(ms))
            else:
                SME.setMinInterval(int(p), int(ms))
        elif cmd == "msg":
            p, _, t = rest.partition(" ")
            ok = SME.sendMessage(int(p), t)
            W.ev(K_CB, "MSGQ %d" % (1 if ok else 0))
        elif cmd == "messenger":
            SME.messenger(int(rest))
        elif cmd == "type":
            W.console_in += rest + "\n"
        elif cmd == "mqtt_drop":
            W.mq.is_connected = False
        elif cmd == "mqtt_accept":
            W.mq.accept_connect = rest == "1"
        elif cmd == "mqtt_pubok":
            W.mq.publish_ok = rest == "1"
        elif cmd == "deliver":
            if W.mqtt:
                W.mqtt.deliver(rest)
        flush(tick)


if __name__ == "__main__":
    main(sys.stdin, sys.stdout)

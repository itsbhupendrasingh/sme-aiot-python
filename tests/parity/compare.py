"""Random-scenario parity check: the same scripts through the Arduino SDK (C++,
driver_cpp) and the Python SDK (driver.py); every HTTP request, MQTT connect /
publish / subscribe, handler call and status line must match, in the same tick.

    python3 tests/parity/compare.py tests/parity/driver_cpp [count] [seed]

The only accepted differences are the two deliberate wording changes for Linux
(no WiFi to join): "Connecting to WiFi ..." is not printed, and "WiFi connected"/
"WiFi lost" read "Network connected"/"Network lost".
"""

import os
import random
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def norm_cpp(lines):
    out = []
    for l in lines:
        if ' OUT [SME] Connecting to WiFi "' in l:
            continue
        l = l.replace(" OUT [SME] WiFi connected, IP ", " OUT [SME] Network connected, IP ")
        l = l.replace(" OUT [SME] WiFi lost, reconnecting...", " OUT [SME] Network lost, reconnecting...")
        out.append(l)
    return out


WORDS = ["hello", "Hi there", "42", "3.5", "-7", "1e3", "on", "OFF", "true", "false", "",
         "née", "温度 25°C", "tab\there", 'q"uote', "back\\slash", "x" * 70, "é" * 40,
         "emoji 🌡️ ok", "{\"a\":1}", " padded "]

VALUES = ['"1"', '"0"', "1", "0", "true", "false", "null", "2.5", "0.1", "-3", "1e5",
          '"hello"', '{"temp":27.5,"hum":60}', "[1,2,3]", '"温度"', "123456789", "3.14159265358979"]

COMMANDS = ["tp0", "tp1", "tp5", "tp15", "tp20", "tp127", "tp128", "tp300", "tp", "tpx", "v1",
            "v12", "v127", "v1234", "config_refresh", "TP1", "tp 3", "tp-1"]


def rnd_f32(r):
    k = r.random()
    if k < 0.4:
        x = round(r.uniform(-500, 500), r.randint(0, 3))
    elif k < 0.7:
        x = r.uniform(-1, 1) * 10 ** r.randint(-8, 9)
    elif k < 0.8:
        x = r.choice([0.0, -0.0, 0.1, 23.5, 99.99, 1e7, 1e-5, float("nan"), float("inf")])
    else:
        return "%08x" % r.getrandbits(32)
    try:
        return "%08x" % struct.unpack("<I", struct.pack("<f", x))[0]
    except OverflowError:
        return "7f800000"


def command_json(r):
    c = r.choice(COMMANDS)
    obj = '{"command":"%s","value":%s' % (c, r.choice(VALUES))
    if r.random() < 0.7:
        obj += ',"id":"c%d"' % r.randint(1, 999)
    elif r.random() < 0.3:
        obj += ',"id":%d' % r.randint(1, 9)
    return obj + "}"


def scenario(r):
    s = []
    if r.random() < 0.6:
        s.append("offer_mqtt mqtt.example.test")
    if r.random() < 0.15:
        s.append("epoch 1600000000")
    if r.random() < 0.1:
        s.append("code /devices/register %d" % r.choice([401, 500, -1]))
    if r.random() < 0.3:
        s.append("messenger %d" % r.choice([15, 3]))
    if r.random() < 0.3:
        s.append("deadband %d %s" % (r.choice([-1, 1, 2]), rnd_f32(r)))
    if r.random() < 0.3:
        s.append("minint %d %d" % (r.choice([-1, 1, 3]), r.choice([50, 300, 1000])))
    s.append("begin_nofw" if r.random() < 0.1 else "begin %s" % r.choice(["0.0.1", "1.2.3", "fw-9"]))
    s.append("run %d" % r.choice([10, 50, 200]))
    for _ in range(r.randint(5, 40)):
        k = r.random()
        pin = r.choice([0, 1, 2, 3, 4, 5, 9, 15, 20, 47, 100, 127, 128, 200])
        if k < 0.2:
            s.append("pub_i %d %d" % (pin, r.choice([0, 1, -1, 42, 1000, -123456, 2147483647, r.randint(-99999, 99999)])))
        elif k < 0.35:
            s.append("pub_f %d %s" % (pin, rnd_f32(r)))
        elif k < 0.4:
            s.append("pub_d %d %016x" % (pin, struct.unpack("<Q", struct.pack("<d", r.uniform(-1e4, 1e4)))[0]))
        elif k < 0.45:
            s.append("pub_b %d %d" % (pin, r.randint(0, 1)))
        elif k < 0.55:
            s.append("pub_s %d %s" % (pin, r.choice(WORDS)))
        elif k < 0.6:
            for p in r.sample(range(0, 128), r.randint(10, 60)):        # many pins at once
                s.append("pub_i %d %d" % (p, r.randint(0, 9)))
        elif k < 0.67:
            s.append("deliver " + (command_json(r) if r.random() < 0.85 else r.choice(['{bad', '[]', '"x"', '{"value":1}', ''])))
        elif k < 0.72:
            s.append("cmds [" + ",".join(command_json(r) for _ in range(r.randint(0, 11))) + "]")
        elif k < 0.76:
            s.append("msg %d %s" % (r.choice([15, 3, 128]), r.choice(WORDS + ["m" * 300])))
        elif k < 0.79:
            s.append("type %s" % r.choice(WORDS))
        elif k < 0.82:
            s.append(r.choice(["mqtt_drop", "mqtt_accept 0", "mqtt_accept 1", "mqtt_pubok 0", "mqtt_pubok 1"]))
        elif k < 0.85:
            s.append("code %s %d" % (r.choice(["/data", "/heartbeat", "/commands", "/executed"]), r.choice([200, 500, -1, 201])))
        elif k < 0.87:
            s.append("wifi %d" % r.randint(0, 1))
        elif k < 0.88:
            s.append("epoch 1800000000")
        elif k < 0.89:
            s.append("reboot")
            s.append("begin 0.0.1")
        s.append("run %d" % r.choice([0, 10, 20, 100, 250, 400, 1000, 3000, 31000]))
    s.append("wifi 1")
    s.append("mqtt_accept 1")
    s.append("run 5000")
    return s


def _lines(raw):
    # The board cuts a long text at 63 bytes even inside a character (broken
    # UTF-8 on the wire); Python cuts before that character. Dropping the broken
    # bytes makes the two the same; everything else must match exactly.
    return raw.decode("utf-8", "ignore").splitlines()


def run_cpp(binary, script):
    return _lines(subprocess.run([binary], input=("\n".join(script) + "\n").encode(),
                                 capture_output=True, check=True).stdout)


def run_py(script):
    # A fresh interpreter per scenario, exactly like a fresh C++ process.
    return _lines(subprocess.run([sys.executable, os.path.join(HERE, "driver.py")],
                                 input=("\n".join(script) + "\n").encode(),
                                 capture_output=True, check=True).stdout)


def main():
    binary = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    total_lines = 0
    for i in range(count):
        r = random.Random(seed * 100000 + i)
        script = scenario(r)
        a = norm_cpp(run_cpp(binary, script))
        b = run_py(script)
        total_lines += len(a)
        if a != b:
            print("MISMATCH in scenario %d (seed %d)" % (i, seed))
            for j, (x, y) in enumerate(zip(a + [""] * len(b), b + [""] * len(a))):
                if x != y:
                    print("  first difference at trace line %d:" % j)
                    print("  C++   :", x)
                    print("  Python:", y)
                    break
            name = "mismatch_seed%d_%d.txt" % (seed, i)
            with open(os.path.join(HERE, name), "w") as f:
                f.write("\n".join(script) + "\n")
            print("  script saved to tests/parity/" + name)
            return 1
    print("parity OK: %d scenarios, %d identical trace lines" % (count, total_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Every example, run as a user would (only the three values filled in), against fakecloud.py + an MQTT broker.
python tests/test_examples.py   (a Python with amqtt + paho-mqtt)"""
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))
SDK_VERSION = {}
exec(open(os.path.join(HERE, '..', 'smeaiot', 'config.py')).read(), SDK_VERSION)
SDK_VERSION = SDK_VERSION['SME_SDK_VERSION']   # the version the logo shows
ROOT = os.path.dirname(HERE)
DEV_PY = os.environ.get('DEVICE_PYTHON', 'python3')
R = []
ok = lambda n, c, i='': R.append((n, bool(c), str(i)[:200]))


def wait(cond, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        if cond():
            return True
        time.sleep(0.1)
    return False


def collect(p):
    fd = p.stdout.fileno()
    fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
    try:
        p._buf = getattr(p, '_buf', '') + (p.stdout.read() or '')
    except (TypeError, OSError):
        p._buf = getattr(p, '_buf', '')
    return p._buf


tmp = tempfile.mkdtemp()
HTTP, BROKER = 18990, 18831
cfgf = os.path.join(tmp, 'b.yaml')
open(cfgf, 'w').write('listeners:\n  default:\n    type: tcp\n    bind: 127.0.0.1:%d\nauth:\n  allow-anonymous: true\n  plugins: [auth_anonymous]\ntopic-check:\n  enabled: false\n' % BROKER)
procs = []
try:
    procs.append(subprocess.Popen([os.path.join(os.path.dirname(sys.executable), 'amqtt'), '-c', cfgf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(2.5)
    stf = os.path.join(tmp, 's.json')
    cloud = subprocess.Popen([sys.executable, os.path.join(HERE, 'fakecloud.py'), str(HTTP), str(BROKER), stf], stdout=subprocess.PIPE, text=True)
    procs.append(cloud)
    time.sleep(0.8)
    dev = cloud.stdout.readline().split()[-1]
    got = []
    app = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='ex-app')
    app.on_message = lambda c, u, m: got.append(json.loads(m.payload.decode()))
    app.connect('127.0.0.1', BROKER)
    app.subscribe('smeiot/devices/%s/data' % dev, 1)
    app.loop_start()
    cmd = lambda pin, v: app.publish('smeiot/devices/%s/commands' % dev, json.dumps({'command': 'tp%d' % pin, 'value': v}), qos=1)
    pins = lambda: {k for g in got for k in g.get('tpPins', {})}

    import glob
    for f in sorted(glob.glob(os.path.join(ROOT, 'examples', '*', '*.py')) + glob.glob(os.path.join(ROOT, 'examples', 'Linux', '*', '*.py'))):
        name = os.path.basename(f)[:-3]
        src = open(f).read()
        ok(name + ': has the standard lines', all(s in src for s in ('SME_PRINT = True', 'DASHBOARD_ID = "PROJ-XXXXXXXX"', 'DEVICE_TOKEN = ', 'FIRMWARE_VERSION = ', 'SME.begin(DASHBOARD_ID, DEVICE_TOKEN, FIRMWARE_VERSION)', 'SME.run()')))
        prog = src.replace('"PROJ-XXXXXXXX"', '"PROJ-TEST0001"').replace('"SME-XXXX-XXXX-XXXX"', '"SME-TEST-TOKEN-0001"')
        prog = prog.replace('SME.begin(DASHBOARD_ID', 'SME.setServerUrl("http://127.0.0.1:%d/api")\nSME.begin(DASHBOARD_ID' % HTTP, 1)
        path = os.path.join(tmp, name + '.py')
        open(path, 'w').write(prog)
        got.clear()
        p = subprocess.Popen([DEV_PY, path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE, text=True,
                             env=dict(os.environ, PYTHONPATH=ROOT, PYTHONUNBUFFERED='1'))
        procs.append(p)
        up = wait(lambda: '[SME] MQTT connected' in collect(p), 12)
        ok(name + ': connects (logo, registered, MQTT)', up and ('v%s on' % SDK_VERSION) in collect(p) and 'Device verified' in collect(p), collect(p)[-300:])
        if name == 'SendValues':
            ok(name + ': TP1 and TP2 arrive together', wait(lambda: any({'1', '2'} <= set(g['tpPins']) for g in got), 6), got[:2])
        if name in ('GraphSimulated', 'GraphSyncTest'):
            ok(name + ': TP0..TP3 in one message', wait(lambda: any({'0', '1', '2', '3'} <= set(g['tpPins']) for g in got), 6), got[:2])
        if name == 'SendPolicy':
            ok(name + ': TP1 and TP2 arrive', wait(lambda: {'1', '2'} <= pins(), 8), pins())
        if name == 'SystemMonitor':
            ok(name + ': load, memory, disk, uptime arrive', wait(lambda: {'1', '2', '3', '4'} <= pins(), 8), pins())
        if name == 'SliderToSerial':
            cmd(3, '42')
            ok(name + ': slider value printed', wait(lambda: 'Slider TP3 = 42' in collect(p), 6), collect(p)[-200:])
        if name == 'InbuiltLED':
            cmd(0, '1')
            ok(name + ': switch handled', wait(lambda: 'LED: ON' in collect(p), 6), collect(p)[-200:])
        if name == 'Messenger':
            ok(name + ': hello sent once online', wait(lambda: any(g['tpPins'].get('15') == 'Hello from the board' for g in got), 6), got[:3])
            cmd(15, 'hi board')
            ok(name + ': app message printed', wait(lambda: '[APP -> DEVICE] hi board' in collect(p), 6))
        if name == 'ButtonToLEDWidget':
            ok(name + ': LED widget starts off', wait(lambda: any(g['tpPins'].get('4') == 0 for g in got), 6), got[:2])
            p.stdin.write('\n')
            p.stdin.flush()
            ok(name + ': a press (Enter) turns the widget on', wait(lambda: any(g['tpPins'].get('4') == 1 for g in got), 6) and 'LED widget ON' in collect(p), collect(p)[-200:])
        ok(name + ': no errors', 'Traceback' not in collect(p) and 'Network error' not in collect(p), collect(p)[-300:])
        p.kill()
        time.sleep(0.3)
finally:
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass

bad = [x for x in R if not x[1]]
for n, p, i in R:
    print(('PASS ' if p else 'FAIL ') + n + ('' if p else '  -> ' + i))
print('examples: %d passed, %d failed' % (len(R) - len(bad), len(bad)))
sys.exit(1 if bad else 0)

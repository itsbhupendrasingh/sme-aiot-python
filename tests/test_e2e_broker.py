"""End to end: the SDK against a stand-in cloud (fakecloud.py) and a real MQTT broker (amqtt).
Run with a Python that has amqtt + paho-mqtt:  python tests/test_e2e.py"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))
SDK_VERSION = {}
exec(open(os.path.join(HERE, '..', 'smeaiot', 'config.py')).read(), SDK_VERSION)
SDK_VERSION = SDK_VERSION['SME_SDK_VERSION']   # the version the logo shows
DEV_PY = os.environ.get('DEVICE_PYTHON', 'python3')   # the Python a user would run the program with
R = []


def ok(name, cond, info=''):
    R.append((name, bool(cond), str(info)[:160]))


def wait(cond, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        if cond():
            return True
        time.sleep(0.1)
    return False


def state(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


tmp = tempfile.mkdtemp()
HTTP, BROKER = 18980, 18830
cfg_file = os.path.join(tmp, 'broker.yaml')
open(cfg_file, 'w').write('listeners:\n  default:\n    type: tcp\n    bind: 127.0.0.1:%d\nauth:\n  allow-anonymous: true\n  plugins: [auth_anonymous]\ntopic-check:\n  enabled: false\n' % BROKER)
procs = []


def start(args, **kw):
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)
    procs.append(p)
    return p


def device(url, extra=None, run_secs=0):
    env = dict(os.environ, SME_URL=url, RUN_SECS=str(run_secs), PYTHONUNBUFFERED='1')
    env.update(extra or {})
    return start([DEV_PY, os.path.join(HERE, 'device_prog.py')], env=env, stdin=subprocess.PIPE)


def out_of(p, secs=0.0):
    time.sleep(secs)
    return p


def collect(p):
    """non-blocking read of what the program printed so far"""
    import fcntl
    fd = p.stdout.fileno()
    fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
    try:
        p._buf = getattr(p, '_buf', '') + (p.stdout.read() or '')
    except (TypeError, OSError):
        p._buf = getattr(p, '_buf', '')
    return p._buf


try:
    broker = start([os.path.join(os.path.dirname(sys.executable), 'amqtt'), '-c', cfg_file])
    time.sleep(2.5)
    st1 = os.path.join(tmp, 'mqtt.json')
    cloud = start([sys.executable, os.path.join(HERE, 'fakecloud.py'), str(HTTP), str(BROKER), st1])
    time.sleep(0.8)
    dev_id = cloud.stdout.readline().split()[-1]

    # an "app" on the broker: watches data + status, sends commands
    got = {'data': [], 'status': []}
    app = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='test-app')
    app.on_message = lambda c, u, m: got['data' if m.topic.endswith('/data') else 'status'].append((json.loads(m.payload.decode()), m.retain, time.time()))
    app.connect('127.0.0.1', BROKER)
    app.subscribe('smeiot/devices/%s/data' % dev_id, 1)
    app.subscribe('smeiot/devices/%s/status' % dev_id, 1)
    app.loop_start()

    # ---------------- A: MQTT
    d = device('http://127.0.0.1:%d/api' % HTTP)
    ok('A registers once with the right fields', wait(lambda: state(st1).get('register'), 10), state(st1).get('register'))
    reg = (state(st1).get('register') or [{}])[0]
    ok('A register body', reg.get('dashboard_id') == 'PROJ-TEST0001' and reg.get('token') == 'SME-TEST-TOKEN-0001' and reg.get('firmware_version') == '1.2.3'
       and ':' in (reg.get('mac_address') or '') and reg.get('ip_address') and reg.get('device_type'), reg)
    ok('A says online (retained) on MQTT', wait(lambda: any(s[0] == {'status': 'online'} for s in got['status']), 10), got['status'][:2])
    ok('A readings arrive over MQTT', wait(lambda: len(got['data']) >= 3, 10), len(got['data']))
    first = got['data'][0][0] if got['data'] else {}
    ok('A tpPins JSON: number and text in one message', isinstance(first.get('tpPins'), dict) and '0' in first['tpPins'] and first['tpPins'].get('2') == 'hello', first)
    ok('A nothing over HTTP while MQTT is up', not state(st1).get('data') and state(st1).get('commands_get', 0) == 0, state(st1).get('data'))
    app.publish('smeiot/devices/%s/commands' % dev_id, json.dumps({'command': 'tp3', 'value': '1'}), qos=1)
    ok('A app command runs the SME_LISTEN handler', wait(lambda: 'HANDLER TP3 1' in collect(d), 6), collect(d)[-300:])
    ok('A the handler\'s publish reaches the app', wait(lambda: any(x[0]['tpPins'].get('1') == 10 for x in got['data']), 6))
    app.publish('smeiot/devices/%s/commands' % dev_id, json.dumps({'command': 'tp3', 'value': 7}), qos=1)
    ok('A a number value arrives as text the handler reads', wait(lambda: 'HANDLER TP3 7' in collect(d), 6))
    ok('A Messenger: sendMessage reaches the app as text', wait(lambda: any(x[0]['tpPins'].get('15') == 'hi app' for x in got['data']), 8))
    ok('A Messenger prints [DEVICE -> APP]', wait(lambda: '[DEVICE -> APP] hi app' in collect(d), 4))
    app.publish('smeiot/devices/%s/commands' % dev_id, json.dumps({'command': 'tp15', 'value': 'hello device'}), qos=1)
    ok('A Messenger prints [APP -> DEVICE]', wait(lambda: '[APP -> DEVICE] hello device' in collect(d), 6))
    d.stdin.write('typed line\n')
    d.stdin.flush()
    ok('A Messenger: a line typed in the terminal goes to the app', wait(lambda: any(x[0]['tpPins'].get('15') == 'typed line' for x in got['data']), 6))
    n0 = len(got['data'])
    time.sleep(2.2)
    rate = (len(got['data']) - n0) / 2.2
    ok('A batching: 2 pins every 0.5 s = about 2 messages a second', 1.2 <= rate <= 3.2, rate)
    out = collect(d)
    ok('A logo and status lines (SME_PRINT = True)', ('v%s on' % SDK_VERSION) in out and '[SME] Device verified & registered with the cloud' in out and '[SME] MQTT connected - live updates on' in out and 'First data sent' in out, out[:600])
    ok('A the token is never printed', 'SME-TEST-TOKEN-0001' not in out)
    # presence beacon: retained online repeats while idle
    s0 = sum(1 for s in got['status'] if s[0] == {'status': 'online'})
    time.sleep(7.8)
    ok('A presence beacon every 7 s', sum(1 for s in got['status'] if s[0] == {'status': 'online'}) > s0)
    # kill -9: the broker's Last-Will says offline
    d.send_signal(signal.SIGKILL)
    ok('A unplugged (killed): Last-Will says offline', wait(lambda: any(s[0] == {'status': 'offline'} for s in got['status']), 100), got['status'][-2:])

    # ---------------- B: a clean exit says offline itself
    got['status'].clear()
    d2 = device('http://127.0.0.1:%d/api' % HTTP, run_secs=4)
    ok('B clean exit: "offline" from the program', wait(lambda: d2.poll() is not None, 15) and wait(lambda: any(s[0] == {'status': 'offline'} for s in got['status']), 5), got['status'][-2:])
    ok('B program ends normally', 'PROGRAM END' in collect(d2))

    # ---------------- C: HTTPS only (no MQTT offered)
    st2 = os.path.join(tmp, 'http.json')
    cloud2 = start([sys.executable, os.path.join(HERE, 'fakecloud.py'), str(HTTP + 1), '0', st2])
    time.sleep(0.8)
    cloud2.stdout.readline()
    json.dump([{'id': 'c1', 'command': 'tp3', 'value': '1'}, {'id': 'c2', 'command': 'config_refresh', 'value': ''}], open(st2 + '.cmds', 'w'))
    d3 = device('http://127.0.0.1:%d/api' % (HTTP + 1))
    ok('C readings over HTTPS POST /data', wait(lambda: len(state(st2).get('data', [])) >= 3, 12), len(state(st2).get('data', [])))
    ok('C command from GET /commands runs the handler', wait(lambda: 'HANDLER TP3 1' in collect(d3), 8), collect(d3)[-200:])
    ok('C commands are acked (pin and non-pin)', wait(lambda: set(state(st2).get('executed', [])) >= {'c1', 'c2'}, 8), state(st2).get('executed'))
    ok('C heartbeat says online', wait(lambda: state(st2).get('heartbeat'), 5) and state(st2)['heartbeat'][0].get('status') == 'online')
    ok('C every call carries the device token', state(st2).get('bad_auth', 0) == 0)
    ok('C says why HTTPS', 'Server offered NO MQTT' in collect(d3))
    d3.kill()

    # ---------------- D: wrong token
    d4 = device('http://127.0.0.1:%d/api' % (HTTP + 1), extra={'TOKEN': 'SME-WRONG'})
    ok('D wrong token: refused, says it is retrying', wait(lambda: 'Could not connect to SME AIoT cloud, retrying' in collect(d4), 10), collect(d4)[-300:])
    ok('D keeps retrying every 5 s', wait(lambda: sum(1 for r in state(st2)['register'] if r.get('token') == 'SME-WRONG') >= 2, 12))
    d4.kill()

    # ---------------- E: no server at all
    d5 = device('http://127.0.0.1:9/api')
    ok('E no server: timers still run, says it is retrying', wait(lambda: 'retrying' in collect(d5), 10), collect(d5)[-200:])
    d5.kill()
finally:
    for p in procs:
        try:
            p.kill()
        except Exception:
            pass

bad = [x for x in R if not x[1]]
for name, p, info in R:
    print(('PASS ' if p else 'FAIL ') + name + ('' if p else '  -> ' + info))
print('e2e: %d passed, %d failed' % (len(R) - len(bad), len(bad)))
sys.exit(1 if bad else 0)

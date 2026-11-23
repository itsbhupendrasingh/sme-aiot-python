"""A stand-in for the SME AIoT cloud API (tests only): the endpoints the SDKs use, recording what they get.

python3 fakecloud.py <http port> <mqtt port or 0> <state file>
State file (JSON, rewritten on every request): registrations, data posts, heartbeats, acks. Commands to hand out over
HTTP are read from <state file>.cmds (a JSON list) on every GET /commands.
"""
import json
import os
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, MQTT_PORT, STATE = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
TOKEN, DASH = 'SME-TEST-TOKEN-0001', 'PROJ-TEST0001'
S = {'register': [], 'data': [], 'heartbeat': [], 'executed': [], 'commands_get': 0, 'bad_auth': 0}
LOCK = threading.Lock()
DEVICE = 'dev-' + uuid.uuid4().hex[:8]


def save():
    with open(STATE + '.tmp', 'w') as f:
        json.dump(S, f)
    os.replace(STATE + '.tmp', STATE)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        try:
            return json.loads(self.rfile.read(n).decode() or 'null')
        except ValueError:
            return None

    def _auth(self):
        ok = self.headers.get('Authorization') == 'Device ' + TOKEN
        if not ok:
            S['bad_auth'] += 1
        return ok

    def do_POST(self):
        b = self._body()
        with LOCK:
            p = self.path
            if p == '/api/devices/register':
                S['register'].append(b)
                if not isinstance(b, dict) or b.get('token') != TOKEN or b.get('dashboard_id') != DASH:
                    save()
                    return self._json(401, {'message': 'invalid token'})
                d = {'device_id': DEVICE}
                if MQTT_PORT:
                    d.update(mqtt_broker='127.0.0.1', mqtt_port=MQTT_PORT, mqtt_tls=False, mqtt_username='', mqtt_password='')
                save()
                return self._json(201, {'data': d})
            if not self._auth():
                save()
                return self._json(401, {'message': 'bad token'})
            if p == '/api/devices/%s/data' % DEVICE:
                S['data'].append(b)
            elif p == '/api/devices/%s/heartbeat' % DEVICE:
                S['heartbeat'].append(b)
            elif p.startswith('/api/devices/%s/commands/' % DEVICE) and p.endswith('/executed'):
                cid = p.split('/')[-2]
                S['executed'].append(cid)
                try:   # an acked command is not handed out again
                    cmds = [c for c in json.load(open(STATE + '.cmds')) if c.get('id') != cid]
                    json.dump(cmds, open(STATE + '.cmds', 'w'))
                except (OSError, ValueError):
                    pass
            else:
                save()
                return self._json(404, {'message': 'not found'})
            save()
            return self._json(200, {'ok': True})

    def do_GET(self):
        with LOCK:
            if not self._auth():
                save()
                return self._json(401, {'message': 'bad token'})
            if self.path == '/api/devices/%s/commands' % DEVICE:
                S['commands_get'] += 1
                try:
                    cmds = json.load(open(STATE + '.cmds'))
                except (OSError, ValueError):
                    cmds = []
                save()
                return self._json(200, {'data': cmds})
            return self._json(404, {})


save()
print('device', DEVICE, flush=True)
ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()

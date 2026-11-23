"""SMEClock: run your own functions on a timer (port of SMEClock.h).

    SME.clock.every(1000, send_data)   # send_data() every second
    SME.clock.after(5000, hello)       # hello() once, 5 s from now
    SME.clock.pause(id); SME.clock.resume(id); SME.clock.stop(id)

Timers keep their pace (no drift when run() is a little late). After a long block
a timer runs once and goes on from there, never a burst to catch up.
"""

from . import config
from . import platform as _p


class _Timer(object):
    __slots__ = ("fn", "period", "last", "left", "serial", "once", "paused")

    def __init__(self):
        self.fn = None
        self.period = 0
        self.last = 0
        self.left = 0
        self.serial = 0
        self.once = False
        self.paused = False


class SMEClock(object):
    def __init__(self, size=None):
        self._t = [_Timer() for _ in range(size or config.SME_CLOCK_MAX)]
        self._serial = 0

    def every(self, ms, fn):
        """Run fn every ms milliseconds. Returns the timer id, or -1."""
        return self._add(ms, fn, False)

    def after(self, ms, fn):
        """Run fn once, ms milliseconds from now. Returns the id, or -1."""
        return self._add(ms, fn, True)

    once = after

    def stop(self, id):
        if id < 0 or id >= len(self._t):
            return
        self._t[id].fn = None
        self._t[id].paused = False

    def pause(self, id):
        if id < 0 or id >= len(self._t):
            return
        t = self._t[id]
        if not t.fn or t.paused:
            return
        gone = _p.millis() - t.last
        t.left = 0 if gone >= t.period else t.period - gone
        t.paused = True

    def resume(self, id):
        if id < 0 or id >= len(self._t):
            return
        t = self._t[id]
        if not t.fn or not t.paused:
            return
        t.last = _p.millis() - (t.period - t.left)
        t.paused = False

    def run(self):
        for i, t in enumerate(self._t):
            if not t.fn or t.paused:
                continue
            now = _p.millis()
            late = now - t.last
            if late < t.period:
                continue
            t.last = now if late >= 2 * t.period else t.last + t.period
            fn, serial, once = t.fn, t.serial, t.once
            fn()   # may stop this timer or start others
            if once and self._t[i].fn and self._t[i].serial == serial:
                self._t[i].fn = None

    def _add(self, ms, fn, once):
        if not fn or not ms or ms <= 0:
            return -1
        for i, t in enumerate(self._t):
            if t.fn:
                continue
            t.period = int(ms)
            t.last = _p.millis()
            t.once = once
            t.paused = False
            self._serial = (self._serial + 1) & 0xFFFF
            t.serial = self._serial
            t.fn = fn
            return i
        return -1

"""The sync engine and rate limiter, ported line for line from
src/sync/SMESyncEngine.cpp and src/sync/SMERateLimiter.h.

Same slots, same order of pins in a batch, same deadband / min-interval rules,
same payload budget, same token bucket. Numbers are held the way the board holds
them: whole numbers as integers, fractions as 32-bit floats.
"""

import math

from . import config
from . import platform as _p
from ._json import Float32, f32

VAL_NONE, VAL_INT, VAL_FLOAT, VAL_STRING = 0, 1, 2, 3


def clip_utf8(s, max_bytes):
    """At most max_bytes of UTF-8, never cutting a character in half."""
    b = s.encode("utf-8")
    if len(b) <= max_bytes:
        return s
    b = b[:max_bytes]
    return b.decode("utf-8", "ignore")


class _Slot(object):
    __slots__ = ("pin", "type", "used", "dirty", "i", "f", "s", "s_bytes",
                 "has_deadband", "deadband", "min_interval",
                 "has_last_sent", "last_sent_num", "last_sent_at")

    def __init__(self):
        self.reset()
        self.used = False

    def reset(self, pin=0):
        self.pin = pin
        self.type = VAL_NONE
        self.dirty = False
        self.i = 0
        self.f = 0.0
        self.s = ""
        self.s_bytes = 0          # length the board's C string would have
        self.has_deadband = False
        self.deadband = 0.0
        self.min_interval = 0
        self.has_last_sent = False
        self.last_sent_num = 0.0
        self.last_sent_at = 0


class SyncEngine(object):
    def __init__(self):
        self._g_has_deadband = False
        self._g_deadband = 0.0
        self._g_min_interval = 0
        self.begin()

    def begin(self):
        # Like SMESyncEngine::begin(): clears the slots (and per-pin settings);
        # the global deadband / min-interval stay.
        self._slots = [_Slot() for _ in range(config.SME_SYNC_SLOTS)]
        self._dirty_count = 0

    @property
    def slot_capacity(self):
        return len(self._slots)

    def has_dirty(self):
        return self._dirty_count > 0

    # ---- policy ----
    def set_deadband_all(self, delta):
        self._g_has_deadband = True
        self._g_deadband = f32(delta)

    def set_deadband(self, pin, delta):
        at = self._find_or_alloc(pin)
        if at < 0:
            return
        self._slots[at].has_deadband = True
        self._slots[at].deadband = f32(delta)

    def set_min_interval_all(self, ms):
        self._g_min_interval = int(ms) & 0xFFFFFFFF

    def set_min_interval(self, pin, ms):
        at = self._find_or_alloc(pin)
        if at < 0:
            return
        self._slots[at].min_interval = int(ms) & 0xFFFFFFFF

    # ---- slots ----
    def _find(self, pin):
        for i, s in enumerate(self._slots):
            if s.used and s.pin == pin:
                return i
        return -1

    def _find_or_alloc(self, pin):
        at = self._find(pin)
        if at >= 0:
            return at
        for i, s in enumerate(self._slots):
            if not s.used:
                s.reset(pin)
                s.used = True
                return i
        return -1

    def _eff_deadband(self, s):
        if s.has_deadband:
            return s.deadband
        if self._g_has_deadband:
            return self._g_deadband
        return -1.0

    def _eff_min_interval(self, s):
        return s.min_interval if s.min_interval > 0 else self._g_min_interval

    def _mark_dirty(self, s):
        if not s.dirty:
            s.dirty = True
            self._dirty_count += 1

    # ---- set ----
    def set_int(self, pin, value):
        if pin >= config.SME_MAX_PINS:
            return False
        at = self._find_or_alloc(pin)
        if at < 0:
            return False
        s = self._slots[at]
        s.type = VAL_INT
        s.i = value
        d = self._eff_deadband(s)
        dirty = d < 0 or not s.has_last_sent or abs(f32(f32(value) - s.last_sent_num)) >= d
        if dirty:
            self._mark_dirty(s)
        return True

    def set_float(self, pin, value):
        if pin >= config.SME_MAX_PINS:
            return False
        at = self._find_or_alloc(pin)
        if at < 0:
            return False
        s = self._slots[at]
        value = f32(value)
        s.type = VAL_FLOAT
        s.f = value
        d = self._eff_deadband(s)
        diff = f32(value - s.last_sent_num)
        dirty = d < 0 or not s.has_last_sent or (not math.isnan(diff) and abs(diff) >= d)
        if dirty:
            self._mark_dirty(s)
        return True

    def set_string(self, pin, value):
        if pin >= config.SME_MAX_PINS:
            return False
        at = self._find_or_alloc(pin)
        if at < 0:
            return False
        s = self._slots[at]
        value = value.split("\x00", 1)[0]              # a C string ends at NUL
        limit = config.SME_STR_MAX
        changed = ((not s.has_last_sent) or s.type != VAL_STRING or
                   s.s.encode("utf-8")[:limit] != value.encode("utf-8")[:limit])
        s.type = VAL_STRING
        s.s = clip_utf8(value, limit - 1)
        s.s_bytes = min(len(value.encode("utf-8")), limit - 1)
        change_only = s.has_deadband or self._g_has_deadband
        if not change_only or changed:
            self._mark_dirty(s)
        return True

    # ---- flush ----
    def _mark_sent(self, s, now):
        s.has_last_sent = True
        s.last_sent_at = now
        if s.type == VAL_INT:
            s.last_sent_num = f32(s.i)
        elif s.type == VAL_FLOAT:
            s.last_sent_num = s.f

    @staticmethod
    def _entry_cost(s):
        key = 6
        if s.type == VAL_STRING:
            return key + s.s_bytes * 2 + 2
        if s.type == VAL_FLOAT:
            return key + 16
        return key + 12

    def _emit(self, tp, s, used):
        cost = self._entry_cost(s)
        if used[0] + cost > config.SME_JSON_CAPACITY - 16:
            return False
        key = str(s.pin)
        if s.type == VAL_INT:
            tp[key] = s.i
        elif s.type == VAL_FLOAT:
            tp[key] = Float32(s.f)
        elif s.type == VAL_STRING:
            tp[key] = s.s
        else:
            return True
        used[0] += cost
        return True

    def flush_dirty(self, tp, now):
        used, written = [14], 0
        for s in self._slots:
            if not s.used or not s.dirty:
                continue
            mi = self._eff_min_interval(s)
            if mi > 0 and s.has_last_sent and ((now - s.last_sent_at) & 0xFFFFFFFF) < mi:
                continue
            if not self._emit(tp, s, used):
                break
            s.dirty = False
            if self._dirty_count > 0:
                self._dirty_count -= 1
            self._mark_sent(s, now)
            written += 1
        return written

    def flush_slice(self, tp, idx, max_emit, now):
        """Returns (emitted, new_idx)."""
        used, emitted = [14], 0
        n = len(self._slots)
        while idx < n and emitted < max_emit:
            s = self._slots[idx]
            if s.used and s.type != VAL_NONE:
                if not self._emit(tp, s, used):
                    break
                if s.dirty:
                    s.dirty = False
                    if self._dirty_count > 0:
                        self._dirty_count -= 1
                self._mark_sent(s, now)
                emitted += 1
            idx += 1
        return emitted, idx


class RateLimiter(object):
    def begin(self, burst=None, per_sec=None):
        burst = config.SME_RATE_BURST if burst is None else burst
        per_sec = config.SME_RATE_PER_SEC if per_sec is None else per_sec
        self._burst = burst or 1
        self._per_sec = per_sec or 1
        self._tokens = self._burst
        self._last = _p.millis()

    def __init__(self):
        self.begin()

    def take(self):
        self._refill()
        if self._tokens == 0:
            return False
        self._tokens -= 1
        return True

    def _refill(self):
        now = _p.millis()
        elapsed = (now - self._last) & 0xFFFFFFFF
        if elapsed < 1000 // self._per_sec:
            return
        gained = (elapsed * self._per_sec) // 1000
        if gained == 0:
            return
        t = self._tokens + gained
        self._tokens = self._burst if t > self._burst else t
        self._last = now

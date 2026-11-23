"""Unit tests: SMEData, SMEClock, the rate limiter, the sync engine and the JSON
writer. The behaviour comes from the Arduino SDK's test/test_units.cpp and
test/test_clock.cpp; tests/test_parity.py checks the whole SDK against the C++
code itself."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest  # noqa: E402

from smeaiot import SMEClock, SMEData, _json, config  # noqa: E402
from smeaiot import platform as P  # noqa: E402
from smeaiot.sync import RateLimiter, SyncEngine  # noqa: E402


@pytest.fixture
def clock(monkeypatch):
    t = {"now": 100000}
    monkeypatch.setattr(P, "millis", lambda: t["now"])
    return t


# ---- SMEData -------------------------------------------------------------------

@pytest.mark.parametrize("text,i,f,b", [
    ("42", 42, 42.0, True), ("-7", -7, -7.0, True), ("3.9", 3, 3.9, True),
    ("0", 0, 0.0, False), ("true", 0, 0.0, True), ("false", 0, 0.0, False),
    ("12abc", 12, 12.0, True), ("abc", 0, 0.0, False), ("", 0, 0.0, False),
    ("  5", 5, 5.0, True), ("1e3", 1, 1000.0, True), ("99999999999", 2147483647, 1e11, True),
])
def test_data_conversions(text, i, f, b):
    d = SMEData(text)
    assert d.toInt() == i and d.asInt() == i
    assert d.toFloat() == pytest.approx(f, rel=1e-6)
    assert d.toBool() is b


def test_data_checks():
    assert SMEData("+3").isInt() and not SMEData("3.0").isInt() and not SMEData("").isInt()
    for ok in ("42", "23.75", "-0.5", ".5", "1e3", "1E-2"):
        assert SMEData(ok).isFloat(), ok
    for bad in ("inf", "nan", "0x10", "1e", "abc", "", "."):
        assert not SMEData(bad).isFloat(), bad
    assert SMEData("TRUE").isBool() and SMEData("0").isBool() and not SMEData("yes").isBool()
    assert SMEData("300").toByte() == 255 and SMEData("-1").toByte() == 0
    assert SMEData("-5").toUInt() == 0 and SMEData("hi").toChar() == "h"


def test_data_json():
    assert SMEData('{"temp":27,"hum":60}').toJSON() == {"temp": 27, "hum": 60}
    assert SMEData("not json").toJSON() == {}
    assert str(SMEData("x")) == "x" and int(SMEData("8")) == 8 and SMEData("a") == "a"


# ---- SMEClock ------------------------------------------------------------------

def test_clock_every_keeps_pace_and_never_bursts(clock):
    c, hits = SMEClock(), []
    c.every(100, lambda: hits.append(clock["now"]))
    for _ in range(35):
        clock["now"] += 10
        c.run()
    assert hits == [100100, 100200, 100300]
    clock["now"] += 1000            # a long block: one run, then on from there
    c.run()
    c.run()
    assert hits[-1] == clock["now"] and len(hits) == 4


def test_clock_after_pause_resume_stop(clock):
    c, hits = SMEClock(), []
    i = c.after(100, lambda: hits.append("once"))
    clock["now"] += 50
    c.pause(i)
    clock["now"] += 500
    c.run()
    assert hits == []
    c.resume(i)
    clock["now"] += 49
    c.run()
    assert hits == []
    clock["now"] += 1
    c.run()
    c.run()
    assert hits == ["once"]
    j = c.every(10, lambda: hits.append("x"))
    c.stop(j)
    clock["now"] += 100
    c.run()
    assert hits == ["once"]
    assert c.every(0, lambda: None) == -1 and c.every(10, None) == -1


def test_clock_full():
    c = SMEClock()
    ids = [c.every(10, lambda: None) for _ in range(config.SME_CLOCK_MAX)]
    assert -1 not in ids and c.every(10, lambda: None) == -1


# ---- rate limiter --------------------------------------------------------------

def test_rate_limiter_burst_then_refill(clock):
    r = RateLimiter()
    assert [r.take() for _ in range(9)] == [True] * 8 + [False]
    clock["now"] += 199
    assert not r.take()
    clock["now"] += 1               # 200 ms at 5/s = one token
    assert r.take() and not r.take()
    clock["now"] += 10000
    assert sum(r.take() for _ in range(20)) == 8


# ---- sync engine ---------------------------------------------------------------

def test_engine_latest_value_per_pin_in_first_publish_order(clock):
    e, tp = SyncEngine(), {}
    e.set_int(5, 1)
    e.set_int(2, 1)
    e.set_int(5, 9)
    assert e.flush_dirty(tp, 0) == 2 and list(tp.items()) == [("5", 9), ("2", 1)]
    assert not e.has_dirty()


def test_engine_deadband_and_min_interval():
    e = SyncEngine()
    e.set_deadband(1, 0.5)
    e.set_float(1, 10.0)
    e.flush_dirty({}, 0)
    e.set_float(1, 10.4)
    assert not e.has_dirty()
    e.set_float(1, 10.5)
    assert e.has_dirty()
    e.set_min_interval(2, 1000)
    e.set_int(2, 1)
    e.flush_dirty({}, 0)
    e.set_int(2, 2)
    tp = {}
    assert e.flush_dirty(tp, 999) == 0 and e.has_dirty()     # pin 2 waits its 1000 ms
    assert e.flush_dirty(tp, 1000) == 1 and tp["2"] == 2


def test_engine_slots_pins_and_strings():
    e = SyncEngine()
    for p in range(config.SME_SYNC_SLOTS):
        assert e.set_int(p, p)
    assert not e.set_int(100, 1)                 # all slots taken
    assert not SyncEngine().set_int(config.SME_MAX_PINS, 1)
    e2 = SyncEngine()
    e2.set_string(1, "x" * 100)
    tp = {}
    e2.flush_dirty(tp, 0)
    assert tp["1"] == "x" * (config.SME_STR_MAX - 1)
    e2.set_string(2, "é" * 40)                   # never cut a character in half
    e2.flush_dirty(tp, 0)
    assert tp["2"] == "é" * 31


def test_engine_budget_splits_big_batches():
    e = SyncEngine()
    for p in range(40):
        e.set_string(p, "y" * 60)
    tp = {}
    n = e.flush_dirty(tp, 0)
    assert 0 < n < 40 and e.has_dirty()
    assert len(_json.dumps({"tpPins": tp})) <= config.SME_JSON_CAPACITY


# ---- JSON as ArduinoJson writes it ---------------------------------------------

@pytest.mark.parametrize("value,text", [
    (_json.Float32(_json.f32(23.5)), "23.5"), (_json.Float32(_json.f32(0.1)), "0.1"),
    (_json.Float32(_json.f32(23.456789)), "23.45679"), (_json.Float32(_json.f32(1e7)), "1e7"),
    (_json.Float32(_json.f32(1.5e-5)), "0.000015"), (_json.Float32(_json.f32(1e-6)), "1e-6"), (float("nan"), "null"), (float("inf"), "null"),
    (0.1, "0.1"), (3.14159265358979, "3.141592654"), (-0.0, "0"), (42, "42"), (True, "true"),
    ("tab\there", '"tab\\there"'), ('q"\\', '"q\\"\\\\"'), ("温度", '"温度"'), ("\x01", '"\x01"'),
    ({"a": [1, None]}, '{"a":[1,null]}'),
])
def test_json_matches_arduinojson(value, text):
    assert _json.dumps(value) == text


def test_json_parse_like_deserializejson():
    assert _json.loads('{"a":1} trailing') == {"a": 1}
    for bad in ("", "{bad", "NaN", "[" * 11 + "]" * 11):
        with pytest.raises(_json.ParseError):
            _json.loads(bad)
    assert _json.loads("[" * 10 + "]" * 10)


# ---- the old package name still works ------------------------------------------

def test_old_name_smeiot_is_an_alias():
    import smeaiot
    import smeiot
    import smeiot.config as old_config
    from smeiot import SME, SME_LISTEN, TP5  # noqa: F401
    assert SME is smeaiot.SME and TP5 == 5
    assert old_config is smeaiot.config and smeiot.__version__ == smeaiot.__version__ == config.SME_SDK_VERSION == "1.0.0"

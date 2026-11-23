"""SMEData: the value an SME_LISTEN handler receives, with the same methods as
the Arduino SDK's SMEData (toInt, toFloat, toBool, isInt, toJSON, ...)."""

import re

from . import _json
from ._json import f32

_INT32_MIN, _INT32_MAX = -(1 << 31), (1 << 31) - 1

_ATOL = re.compile(r"[ \t\n\v\f\r]*([+-]?[0-9]+)")
_STRTOD = re.compile(
    r"[ \t\n\v\f\r]*([+-]?(?:(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|inf(?:inity)?|nan))",
    re.IGNORECASE)


def _atol(s):
    """C atol() on a 32-bit board: leading number, 0 if none, saturated."""
    m = _ATOL.match(s)
    if not m:
        return 0
    n = int(m.group(1))
    return max(_INT32_MIN, min(_INT32_MAX, n))


def _strtod(s):
    m = _STRTOD.match(s)
    if not m:
        return 0.0
    t = m.group(1)
    try:
        return float(t)
    except ValueError:            # e.g. "1e" is matched as "1" by the regex anyway
        return 0.0


class SMEData(object):
    __slots__ = ("_v",)

    def __init__(self, value=""):
        self._v = "" if value is None else str(value)

    # ---- the Arduino names ----
    def toInt(self):
        return _atol(self._v)

    def toLong(self):
        return _atol(self._v)

    def toUInt(self):
        n = _atol(self._v)
        return 0 if n < 0 else n

    def toByte(self):
        n = _atol(self._v)
        return 0 if n < 0 else (255 if n > 255 else n)

    def toChar(self):
        return self._v[0] if self._v else ""

    def toFloat(self):
        return f32(_strtod(self._v))

    def toDouble(self):
        return _strtod(self._v)

    def toBool(self):
        return self._v == "1" or self._v == "true" or self.toFloat() != 0.0

    def toString(self):
        return self._v

    def c_str(self):
        return self._v

    def isEmpty(self):
        return len(self._v) == 0

    asInt = toInt
    asLong = toLong
    asFloat = toFloat
    asDouble = toDouble
    asString = toString

    def isInt(self):
        s = self._v
        if s[:1] in ("+", "-"):
            s = s[1:]
        return len(s) > 0 and all("0" <= c <= "9" for c in s)

    def isFloat(self):
        s, i, n = self._v, 0, len(self._v)
        if i < n and s[i] in "+-":
            i += 1
        digits = 0
        while i < n and "0" <= s[i] <= "9":
            i += 1
            digits += 1
        if i < n and s[i] == ".":
            i += 1
            while i < n and "0" <= s[i] <= "9":
                i += 1
                digits += 1
        if digits == 0:
            return False
        if i < n and s[i] in "eE":
            i += 1
            if i < n and s[i] in "+-":
                i += 1
            if not (i < n and "0" <= s[i] <= "9"):
                return False
            while i < n and "0" <= s[i] <= "9":
                i += 1
        return i == n

    def isBool(self):
        return self._v in ("0", "1") or self._v.lower() in ("true", "false")

    def toJSON(self):
        """The value read as JSON, e.g. {"temp": 27, "hum": 60}. Not JSON: {}."""
        try:
            return _json.loads(self._v)
        except _json.ParseError:
            return {}

    # ---- Python conveniences ----
    def __str__(self):
        return self._v

    def __repr__(self):
        return "SMEData(%r)" % self._v

    def __int__(self):
        return self.toInt()

    def __float__(self):
        return self.toDouble()

    def __eq__(self, other):
        if isinstance(other, SMEData):
            return self._v == other._v
        return self._v == other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self._v)

    def __len__(self):
        return len(self._v)


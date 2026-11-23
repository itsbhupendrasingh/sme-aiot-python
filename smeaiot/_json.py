"""JSON exactly as the Arduino SDK writes it (ArduinoJson 7.4).

The backend sees byte-for-byte the same payloads from a Python device as from a
NuttyFi board, so numbers and strings are written the way ArduinoJson writes them,
not the way Python's json module does:

* a value published as a number with a fraction is a 32-bit float on the board,
  written with up to 6 decimal places: 23.5 -> "23.5", 0.1 -> "0.1",
  23.456789 -> "23.45679";
* a number parsed from JSON (a command value) keeps up to 9 decimal places,
  unless it is exactly a 32-bit float (then 6);
* very large / small numbers use "1.5e7" / "1e-5" style exponents;
* NaN and infinity are written as null;
* in strings only  "  \\  and \\b \\f \\n \\r \\t are escaped, non-ASCII stays as
  UTF-8.

Ported from ArduinoJson/Numbers/FloatParts.hpp and Json/TextFormatter.hpp.
"""

import json
import math
import struct

# ---- 32-bit float (C `float`) ---------------------------------------------------

_F32_MAX = 3.4028234663852886e38


def f32(x):
    """Round a Python float to the nearest C float, as `(float)x` does."""
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return x
    try:
        return struct.unpack("<f", struct.pack("<f", x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def fits_f32(x):
    """True if the double x is exactly a 32-bit float (ArduinoJson then stores it as one)."""
    y = f32(x)
    return y == x


# ---- ArduinoJson float formatting ------------------------------------------------


def _d(bits):
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


_POS = [_d(b) for b in (
    0x4024000000000000, 0x4059000000000000, 0x40C3880000000000,
    0x4197D78400000000, 0x4341C37937E08000, 0x4693B8B5B5056E17,
    0x4D384F03E93FF9F5, 0x5A827748F9301D32, 0x75154FDD7F73BF3C)]
_NEG = [_d(b) for b in (
    0x3FB999999999999A, 0x3F847AE147AE147B, 0x3F1A36E2EB1C432D,
    0x3E45798EE2308C3A, 0x3C9CD2B297D889BC, 0x3949F623D5A8A733,
    0x32A50FFD44F4A73D, 0x255BBA08CF8C979D, 0x0AC8062864AC6F43)]

_POS_THRESHOLD = 1e7
_NEG_THRESHOLD = 1e-5


def _normalize(value):
    powers = 0
    index = 8
    bit = 1 << index
    if value >= _POS_THRESHOLD:
        while index >= 0:
            if value >= _POS[index]:
                value *= _NEG[index]
                powers += bit
            bit >>= 1
            index -= 1
    if value > 0 and value <= _NEG_THRESHOLD:
        while index >= 0:
            if value < _NEG[index] * 10:
                value *= _POS[index]
                powers -= bit
            bit >>= 1
            index -= 1
    return powers, value


def _u32(x):
    # C conversion double -> uint32_t (values here are always in range)
    return int(x) & 0xFFFFFFFF


def format_float(value, decimal_places):
    """ArduinoJson's TextFormatter::writeFloat."""
    value = float(value)
    if math.isnan(value) or math.isinf(value):
        return "null"
    out = ""
    if value < 0.0:
        out = "-"
        value = -value

    max_decimal = 10 ** decimal_places
    exponent, value = _normalize(value)
    integral = _u32(value)
    tmp = integral
    while tmp >= 10:
        max_decimal //= 10
        decimal_places -= 1
        tmp //= 10

    remainder = (value - float(integral)) * float(max_decimal)
    decimal = _u32(remainder)
    remainder = remainder - float(decimal)
    decimal += _u32(remainder * 2)
    if decimal >= max_decimal:
        decimal = 0
        integral += 1
        if exponent and integral >= 10:
            exponent += 1
            integral = 1

    while decimal % 10 == 0 and decimal_places > 0:
        decimal //= 10
        decimal_places -= 1

    out += str(integral)
    if decimal_places:
        out += "." + str(decimal).rjust(decimal_places, "0")[-decimal_places:]
    if exponent:
        out += "e" + str(exponent)
    return out


# ---- values ----------------------------------------------------------------------


class Float32(float):
    """A number the board holds as a C float (published floats)."""


_ESC = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f",
        "\n": "\\n", "\r": "\\r", "\t": "\\t", "\x00": "\\u0000"}


def format_string(s):
    return '"' + "".join(_ESC.get(c, c) for c in s) + '"'


_INT64_MIN = -(1 << 63)
_UINT64_MAX = (1 << 64) - 1


def dumps(v):
    """Serialise like ArduinoJson's serializeJson (compact)."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, Float32):
        return format_float(v, 6)
    if isinstance(v, int):
        if _INT64_MIN <= v <= _UINT64_MAX:
            return str(v)
        return dumps(float(v))          # ArduinoJson parses such numbers as double
    if isinstance(v, float):
        return format_float(v, 6 if fits_f32(v) else 9)
    if isinstance(v, str):
        return format_string(v)
    if isinstance(v, dict):
        return "{" + ",".join(format_string(str(k)) + ":" + dumps(x) for k, x in v.items()) + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(dumps(x) for x in v) + "]"
    raise TypeError("cannot serialise %r" % (type(v),))


# ---- parsing (tolerant like deserializeJson) --------------------------------------

_NESTING_LIMIT = 10
def _no_constants(name):
    raise ValueError("%s is not JSON" % name)   # ArduinoJson: NaN/Infinity disabled


_decoder = json.JSONDecoder(parse_constant=_no_constants)


def _depth(v, d=0):
    if isinstance(v, dict):
        return max([_depth(x, d + 1) for x in v.values()] or [d + 1])
    if isinstance(v, list):
        return max([_depth(x, d + 1) for x in v] or [d + 1])
    return d


class ParseError(ValueError):
    pass


def loads(text):
    """Parse the first JSON value in text (trailing bytes ignored, as ArduinoJson
    does). Raises ParseError on invalid input or nesting deeper than 10."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    s = text.lstrip(" \t\r\n")
    if not s:
        raise ParseError("empty")
    try:
        v, _ = _decoder.raw_decode(s)
    except ValueError as e:
        raise ParseError(str(e))
    if _depth(v) > _NESTING_LIMIT:
        raise ParseError("too deep")
    return v

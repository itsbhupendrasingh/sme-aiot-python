"""Old name of the SME AIoT SDK package, kept so `import smeiot` and
`import smeiot.config` keep working. New code: `import smeaiot`."""

import importlib as _importlib
import sys as _sys

import smeaiot as _new
from smeaiot import *  # noqa: F401,F403
from smeaiot import __all__, __version__  # noqa: F401

for _name in ("config", "core", "clock", "data", "sync", "platform", "mqtt", "certs", "_json"):
    _mod = _importlib.import_module("smeaiot." + _name)
    _sys.modules[__name__ + "." + _name] = _mod
    globals()[_name] = _mod
del _name, _mod

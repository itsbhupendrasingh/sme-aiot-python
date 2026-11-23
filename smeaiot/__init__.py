"""SME AIoT SDK for Linux: the Arduino SME AIoT SDK in Python.

    from smeaiot import SME, SME_LISTEN, TP0, TP1

    @SME_LISTEN(TP0)
    def on_switch(data):
        print("switch:", data.toInt())

    def send_data():
        SME.publish(TP1, 23.5)

    SME.begin("PROJ-XXXXXXXX", "SME-XXXX-XXXX-XXXX", "1.0.0")
    SME.clock.every(1000, send_data)
    SME.run_forever()
"""

from . import config
from .clock import SMEClock
from .core import SME, SMEClass
from .data import SMEData

__version__ = config.SME_SDK_VERSION

# Telemetry Points: TP5 is just 5, as on the board.
for _i in range(128):
    globals()["TP%d" % _i] = _i
del _i


def SME_LISTEN(pin):
    """@SME_LISTEN(TP0) above a function: it runs with the value (an SMEData)
    each time the dashboard writes that pin."""
    return SME.listen(pin)


SME_URL_PRODUCTION = config.SME_URL_PRODUCTION

__all__ = ["SME", "SME_LISTEN", "SMEClass", "SMEClock", "SMEData", "config",
           "SME_URL_PRODUCTION"] + ["TP%d" % i for i in range(128)]

"""Runs the C++ Arduino SDK and the Python SDK through the same random scenarios
and requires identical traces (every HTTP request, MQTT connect / publish /
subscribe, handler call and status line, in the same millisecond).

Needs g++ and the Arduino SDK folder (its test/.deps/ArduinoJson is fetched by
its test/run_tests.sh):

    SME_ARDUINO_SDK=/path/to/SMEAIoT python3 -m pytest tests/test_parity.py

Skipped without SME_ARDUINO_SDK. SME_PARITY_COUNT sets the number of scenarios.
"""

import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.environ.get("SME_ARDUINO_SDK")

pytestmark = pytest.mark.skipif(
    not SDK or not shutil.which("g++") or
    not os.path.isdir(os.path.join(SDK or "", "test", ".deps", "ArduinoJson")),
    reason="set SME_ARDUINO_SDK to the Arduino SDK folder (with test/.deps) and install g++")


def test_python_and_arduino_sdk_behave_identically(tmp_path):
    binary = str(tmp_path / "driver_cpp")
    subprocess.run([os.path.join(HERE, "parity", "build_driver.sh"), SDK, binary],
                   check=True, capture_output=True)
    count = os.environ.get("SME_PARITY_COUNT", "150")
    r = subprocess.run([sys.executable, os.path.join(HERE, "parity", "compare.py"), binary, count, "1"],
                       capture_output=True, text=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    print(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr

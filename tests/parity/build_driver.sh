#!/usr/bin/env bash
# Builds the C++ parity driver against an Arduino SME AIoT SDK folder.
#   tests/parity/build_driver.sh /path/to/SMEAIoT [out-binary]
# Needs g++ and the SDK's test/.deps/ArduinoJson (run its test/run_tests.sh once).
set -euo pipefail
SDK="$(cd "$1" && pwd)"
OUT="${2:-$(dirname "$0")/driver_cpp}"
T="$SDK/test"
g++ -std=c++17 -O1 -w -DESP32 \
  -I "$T" -I "$T/fakes" -I "$SDK/src" -I "$T/.deps/ArduinoJson/src" \
  -DARDUINOJSON_ENABLE_ARDUINO_STRING=1 -DARDUINOJSON_ENABLE_ARDUINO_STREAM=0 -DARDUINOJSON_ENABLE_PROGMEM=0 \
  "$SDK/src/SMEAIoT.cpp" "$SDK/src/net/SMEHttp.cpp" "$SDK/src/net/SMEMqtt.cpp" "$SDK/src/net/SMECerts.cpp" \
  "$SDK/src/sync/SMESyncEngine.cpp" "$SDK/src/storage/SMEStore.cpp" "$SDK/src/SMEBoard.cpp" "$T/fakes/fakes.cpp" \
  "$(dirname "$0")/driver.cpp" -o "$OUT"
echo "built $OUT"

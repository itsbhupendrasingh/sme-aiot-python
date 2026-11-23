"""Settings, with the same names and defaults as the Arduino SDK's SMEConfig.h.

Change one before SME.begin(), for example::

    import smeaiot.config as config
    config.SME_FLUSH_INTERVAL = 100

(Unlike on the board, this really does reach the whole SDK.)
"""

# ---- Backend ----------------------------------------------------------------
SME_URL_PRODUCTION = "https://apps.nuttyengineer.cloud/api"
SME_BASE_URL = SME_URL_PRODUCTION

# ---- Device identity defaults ----------------------------------------------
SME_SDK_VERSION = "1.0.0"
SME_FIRMWARE_VERSION = "0.0.1"   # sent when begin() is given no version
SME_BANNER = 1

# Sent to the backend at registration. "SME-Device" is what the Arduino SDK sends
# on any board that is not a NuttyFi 2.0 or NuttyFi32.
SME_DEVICE_TYPE = None   # None: the board says what it is, e.g. "Raspberry Pi 5 Model B Rev 1.0 (Linux)"
# Shown in the start-up logo only.
SME_BOARD_NAME = None    # None: the board's own name in the logo (Raspberry Pi, Jetson, Coral ...)

# ---- Pins -------------------------------------------------------------------
SME_MAX_PINS = 128
SME_SYNC_SLOTS = 48
SME_STR_MAX = 64          # a string pin value keeps at most SME_STR_MAX - 1 bytes

# ---- Timing (milliseconds) --------------------------------------------------
SME_FLUSH_INTERVAL = 200   # ms: everything published inside this window leaves in one message
SME_MSG_RETRY_GAP = 250
SME_FULL_RESYNC_INTERVAL = 0
SME_RESYNC_BATCH = 48   # pins in one full snapshot message
SME_HEARTBEAT_INTERVAL = 30000
SME_REGISTER_INTERVAL = 5000
SME_COMMAND_POLL_INTERVAL = 400
SME_MQTT_BACKOFF_MIN = 2000
SME_MQTT_BACKOFF_MAX = 30000

# ---- Time -------------------------------------------------------------------
# No secure connection is attempted until the system clock is past this epoch.
SME_TIME_VALID_EPOCH = 1700000000
SME_TIME_RETRY_INTERVAL = 3000
SME_TIME_SLOW_WARN = 30000

# ---- Rate limiting ----------------------------------------------------------
SME_RATE_BURST = 8
SME_RATE_PER_SEC = 5
SME_MAX_CMDS_PER_TICK = 8
SME_ACK_QUEUE = 8

# ---- JSON buffers -----------------------------------------------------------
SME_JSON_CAPACITY = 2048

# ---- Messenger --------------------------------------------------------------
SME_MSG_MAX = 256
SME_MSG_QUEUE = 4
SME_MSG_TRIES = 3

# ---- Timers -----------------------------------------------------------------
SME_CLOCK_MAX = 16

# ---- Security ---------------------------------------------------------------
# 1 = verify the server certificate against the pinned root (ISRG Root X1).
SME_TLS_VERIFY = 1
SME_MQTT_TLS_VERIFY = None   # None = follow SME_TLS_VERIFY

# ---- Output -----------------------------------------------------------------
# Like "#define SME_PRINT Serial": set to sys.stdout (or any file) to show the
# SME AIoT logo and plain status lines. None = silent.
SME_PRINT = None

# Internal details for SDK development (Python logging, logger "smeaiot").
SME_DEBUG = 0
SME_PRESENCE_BEACON_INTERVAL = 7000   # ms: retained "online" again while MQTT is up (the cloud marks a silent device offline)
SME_ONLINE_HOLD = 300   # ms after MQTT comes up: the cloud's stored values are applied before the device sends
SME_MQTT_KEEPALIVE = 60   # s
SME_HTTP_HEARTBEAT = 1   # HTTPS fallback only: an "I'm alive" call every SME_HEARTBEAT_INTERVAL
SME_RUN_IDLE_MS = 2   # SME.run() rests this long when it has nothing to do: `while True: SME.run()` uses ~2 % of a core

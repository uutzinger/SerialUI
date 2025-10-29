################################################################################################################################
# Constants for Serial UI Application
################################################################################################################################
import logging
import re
from colors import color_names_sweet16 as COLORS
################################################################################################################################
# Constants General
VERSION                 = "0.4.0"                # this version
AUTHOR                  = "Urs Utzinger"         # me
DATE                    = "2025"                 # year of last update
################################################################################################################################
# Enable Features
USE_FASTPLOTLIB         = False                  # use fastplotlib instead of pyqtgraph
USE_BLE                 = True                   # enable bleak for BLE communication
USE_BLUETOOTHCTL        = True                   # enable bluetoothctl for bluetoothctl functions on Linux
USE_3DPLOT              = False                  # use the 3D vector display in indicator, not implemented yet
################################################################################################################################
# Debug and Profiling
PROFILEME               = False                  # enable/disable profiling (measure execution time of functions)
DEBUGKEYINPUT           = False                  # enable/disable key input debugging
DEBUGSERIAL             = False                  # enable/disable low level serial debugging
DEBUGCHART              = False                  # enable/disable chart debugging
DEBUGFASTPLOTLIB        = False                  # enable/disable fastplotlib debugging
DEBUGRECEIVER           = False                  # enable/disable receiver debugging in main program (switching receiver on/off)
################################################################################################################################
# Constants Chart
MAX_ROWS                = 131072                # data history length
MAX_COLS                = len(COLORS)           # maximum number of data traces [available colors]
DEF_COLS                = 2                     # default number of data traces at startup
UPDATE_INTERVAL         = 40                    # [ms] 25 Hz plot update, visualization does not improve with higher rate
MAX_ROWS_LINEDATA       = 512                   # maximum number of rows for temporary array when parsing line data
MAJOR_TICKS             = 5                     # major ticks on the y-axis
MINOR_TICKS             = 4                     # minor ticks on the y-axis
WHITE                   = (1.0, 1.0, 1.0, 1.0)  # RR GG BB AA
BLACK                   = (0.0, 0.0, 0.0, 1.0)  #
RED                     = (1.0, 0.0, 0.0, 1.0)  #
GREEN                   = (0.0, 1.0, 0.0, 1.0)  #
BLUE                    = (0.0, 0.0, 1.0, 1.0)  #
DARK_GRAY               = (0.2, 0.2, 0.2, 1.0)  #
LIGHT_GRAY              = (0.9, 0.9, 0.9, 1.0)  #
TRANSPARENT_LIGHT_GRAY  = (0.9, 0.9, 0.9, 0.8)  #
YELLOW                  = (1.0, 1.0, 0.0, 1.0)  #
ORANGE                  = (1.0, 0.5, 0.0, 1.0)  #
MAGENTA                 = (1.0, 0.0, 1.0, 1.0)  #
CYAN                    = (0.0, 1.0, 1.0, 1.0)  #
# Fastplotlib
DISCRETE_GPU            = True                   # prefer discrete GPU if available (e.g. NVIDIA, Radeon on Vulkan backend)
CACHE_FILE              = "wgpu_pipeline.cache"  # once GPU cache read and write would be exposed in the wgpu library we can
#                                               #   pre-load from file which would speed up initialization
################################################################################################################################
# Constants BLE
# Medibrick
DEFAULT_TARGET_DEVICE_NAME = "MediBrick"        # The name of the BLE device to search for,  
                                                # Program searches for all Nordic Serial UART service by default
BLEPIN                  = "123456"              # Known pairing pin for Medibrick_BLE
# UUIDs for the Nordic Serial UART service and characteristics
SERVICE_UUID            = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
RX_CHARACTERISTIC_UUID  = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TX_CHARACTERISTIC_UUID  = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"
# BLE Constants
BLETIMEOUT              =  30                   # Timeout for BLE operations
ATT_HDR                 =   3                   # Attribute header length
BLEMTUMAX               = 517                   # Maximum MTU size
BLEMTUNORMAL            = 247                   # Normal MTU size
BLEMTUDEFAULT           =  23                   # Default MTU size
# Ideally devices send data so that LL fragmentation is avoided
# BLE LL octet size can be set to 27 .. 251 bytes (with 4 bytes header) which results in ideal MTU of 247
# Increasing MTU results in higher throughput, however max settings are set by the peripheral and might 
# be lower than what we request.
################################################################################################################################
# Constants Text Display
BACKGROUNDCOLOR         = "#ffffff"
BACKGROUNDCOLOR_LOG     = "#f0f0f0"
BACKGROUNDCOLOR_TABS    = "#f0f0ff"
# Remove ANSI escape sequences
ANSI_ESCAPE             = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
ENCODING                = "utf-8"               # default encoding for text display
FLUSH_INTERVAL_MS       = 100                   # [ms] 10 Hz update of the text display (received data is buffered)
DEFAULT_TEXT_LINES      = 500                   # number of lines in display window (less is faster,
                                                # but with fast transfer rates, some data might be skipped 
                                                # when data is streamed to file, no data is skipped
MAX_TEXT_LINES          = 5_000                 # max number of lines in display window (max value of user adjustable slider)
MAX_BACKLOG_BYTES       = 1_000_000             # ~1 MB maximum backlog. when viewer scrolls up the text display,
                                                #   update is paused up and incoming data is backlogged up to this limit
################################################################################################################################
# Constants Serial
DEFAULT_BAUDRATE        = 2_000_000             # default baud rate for serial port
SERIAL_BUFFER_SIZE      = 4_096                 # [bytes] size of the serial device buffer, has no effect on Linux and Darwin
################################################################################################################################
# Constants USB Port Monitor
USB_POLLING_INTERVAL    = 300                   # [ms] interval to check for USB device insertion/removal
################################################################################################################################
# Constants for End of Line (EOL) Options
# Human-readable → bytes
# Please do not change the bytes (second column), you can add and change the labels
EOL_DICT = {
    "none"                    : b"",
    "return newline (\\r\\n)" : b"\r\n",
    "newline (\\n)"           : b"\n",
    "return (\\r)"            : b"\r",
    "newline return (\\n\\r)" : b"\n\r",
}
# Defaults
EOL_DEFAULT_LABEL       = "none"
EOL_DEFAULT_BYTES       = EOL_DICT[EOL_DEFAULT_LABEL]
# Bytes → human-readable (for reverse lookup)
EOL_DICT_INV            = {v: k for k, v in EOL_DICT.items()}
DEFAULT_LINETERMINATOR  = EOL_DEFAULT_BYTES      # default line termination
################################################################################################################################
# Constants Data Parsing Options
# Please do not change "simple", "header", "binary", you can add or change the labels
# currently binary data parsing is not implemented but framework is there
PARSE_OPTIONS = {
    "No Labels (simple)" : "simple",
    "With [Label:]"      : "header",
    "Binary"             : "binary",
}
# Defaults
PARSE_DEFAULT_LABEL     = "No Labels (simple)"
PARSE_DEFAULT_NAME      = PARSE_OPTIONS[PARSE_DEFAULT_LABEL]
PARSE_OPTIONS_INV       = {v: k for k, v in PARSE_OPTIONS.items()}
###############################################################################################################################
# Constants for EOL Autodetection for USB and BLE data receiving
MAX_DATAREADYCALLS      = 10                    # if 10 data ready calls occur within MAX_EOL_DETECTION_TIME we autodetect EOL
MAX_EOL_DETECTION_TIME  = 1.0                   # if data is arriving for 1 second and no EOL found, we autodetect EOL
MAX_EOL_FALLBACK_TIMEOUT= 5.0                   # if not EOL is found for 5 seconds we switch to raw (no EOL)
###############################################################################################################################
# Constants LOGLEVEL Options
LOG_OPTIONS = {
    "NONE"     : logging.NOTSET,
    "DEBUG"    : logging.DEBUG,
    "INFO"     : logging.INFO,
    "WARNING"  : logging.WARNING,
    "ERROR"    : logging.ERROR,
    "CRITICAL" : logging.CRITICAL
}
LOG_DEFAULT_LABEL = "INFO"
LOG_DEFAULT_NAME = LOG_OPTIONS[LOG_DEFAULT_LABEL]
LOG_OPTIONS_INV = {v: k for k, v in LOG_OPTIONS.items()}
# logging level and priority
# CRITICAL  50
# ERROR     40
# WARNING   30
# INFO      20
# DEBUG     10
# NOTSET     0
# PROFILE   -1                                  # custom level for profiling log messages
# FORCED    -2                                  # custom level for forced log messages
DEBUG_LEVEL = LOG_DEFAULT_NAME
###############################################################################################################################
# Constants for CHART Options
LINEWIDTH               = 2
AXIS_LINEWIDTH          = 2
CHART_BACKGROUND_COLOR  = WHITE
AXIS_COLOR              = BLACK
POINT_COLOR             = BLACK
GRID_COLOR              = DARK_GRAY
GRID_MINOR_COLOR        = LIGHT_GRAY
GRID_ALPHA              = 0.3
TICK_COLOR              = BLACK
FRAME_TITLE_COLOR       = BLACK
FRAME_PLANE_COLOR       = LIGHT_GRAY
LEGEND_BACKGROUND_COLOR = TRANSPARENT_LIGHT_GRAY
AXIS_FONT_COLOR         = BLACK
TITLE_FONT_COLOR        = BLACK
LEGEND_FONT_COLOR       = BLACK
CAMERA_PAD              = 1.05                  #  5% padding for camera view
SMALLEST                = 1e-18
REL_TOL                 = 0.03
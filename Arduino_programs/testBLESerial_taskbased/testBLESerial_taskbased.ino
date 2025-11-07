// ********************************************************************************************************************
//  Main File: testBLESerial_taskbased.ino
//
//  This program handles data generation and BLE serial communication.
//
//  Commands:
//
//    interval <value>: Sets the data generation interval to the specified value in micro seconds.
//    frequency <value> sets the frequency of the sine, saw tooth or squarewave in Hz
//    scenario <value>: Changes the scenario to the specified value (1 to 5).
//
//    pause:            Pauses the data generation.
//    resume:           Resumes the data generation if it was paused.
//
// ********************************************************************************************************************

#define VERSION_STRING "NUS Tester 1.1.1"

#include <inttypes.h>  // for PRIu32 in printf
#include <cmath>
#include "RingBuffer.h"

// *****************************************************************************************************************
// ESP32 and NimBLE includes
// *****************************************************************************************************************
#include <NimBLEDevice.h>
// for ble_gap_set_prefered_le_phy
extern "C" {
  #include "host/ble_gap.h"      // ble_gap_* (conn params, PHY, DLE)
  #include "host/ble_hs_adv.h"   // BLE_HS_ADV_F_* flags for adv data
  #include "host/ble_hs.h"       // BLE_HS_EDONE for notivy backoff
}
// for mac address
#if __has_include(<esp_mac.h>)
  #include <esp_mac.h>      // IDF 5.x / Arduino core 3.x
#else
  #include <esp_system.h>   // IDF 4.x / Arduino core 2.x
#endif
#if defined(ARDUINO_ARCH_ESP32)
  #include "esp_rom_sys.h"
#endif
// for txTask and RSSI task
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#if defined(ARDUINO_ARCH_ESP32)
  #include <esp_timer.h>   // microsecond one-shot timer for TX pacing
  #define HAS_ESP_TIMER 1
#else
  #define HAS_ESP_TIMER 0
#endif

// *****************************************************************************************************************
// Optimizations: SPEED - RANGE - LOWPOWER
//
// DEBUG ON/OFF
// Secure connections ON/OFF
//
#define SPEED                         
//#undef SPEED                     
//
// min throughput, min power
//
//#define LOWPOWER
#undef LOWPOWER
//
// if not SPEED and if not LOWPOWER
//   results in LONGRANGE
//
// DEBUG verbose output on serial and BLE port for debugging
// INFO output on Serial about system changes
// WARNING output on Serial about issues
// ERROR output on Serial about errors
// For any issues select DEBUG
#define NONE    0
#define WANTED  1
#define ERROR   1 
#define WARNING 2
#define INFO    3
#define DEBUG   4
//
// Avoid DEBUG for SPEED
#define DEBUG_LEVEL INFO
// require pairing and encryption
//
// #define BLE_SECURE
#undef BLE_SECURE
// *****************************************************************************************************************

// ===== SERIAL ======
inline constexpr unsigned long BAUDRATE              = 2'000'000UL;

// ===== Buffer =====
#if defined(SPEED)
  inline constexpr size_t      TX_BUFFERSIZE         = 4096;
#elif defined(LOWPOWER)
  inline constexpr size_t      TX_BUFFERSIZE         = 1024;
#else
  inline constexpr size_t      TX_BUFFERSIZE         = 2048;
#endif
inline constexpr size_t        highWaterMark         = TX_BUFFERSIZE*3/4; // When to throttle data generation
uint16_t                       lowWaterMark          = TX_BUFFERSIZE/4;   // When to resume data generation

// RX buffer for BLE writes (commands)
#if defined(SPEED)
  inline constexpr size_t      RX_BUFFERSIZE         = 1024;
#elif defined(LOWPOWER)
  inline constexpr size_t      RX_BUFFERSIZE         = 512;
#else
  inline constexpr size_t      RX_BUFFERSIZE         = 1024;
#endif

RingBuffer<char, TX_BUFFERSIZE> txBuffer; // Should be a few times larger than the BLE payload size
RingBuffer<char, RX_BUFFERSIZE> rxBuffer; // Buffer for incoming BLE commands, should be large enough to hold on BLE package

// *****************************************************************************************************************
// BLE
// *****************************************************************************************************************

// ===== GAP / Connection preferences =====
#define DEVICE_NAME           "MediBrick"// Name shown when BLE scans for devices
#define BLE_APPEARANCE         0x0540 // Generic Sensor, https://www.bluetooth.com/specifications/assigned-numbers/generic-access-profile/

// ===== GATT / ATT payload sizing =====
inline constexpr uint16_t      BLE_MTU               =  517;    // Max size in bytes to send at once. MAX ESP 517, Android 512, Nordic 247, Regular size is 23
inline constexpr uint16_t      ATT_HDR_BYTES         =    3;
inline constexpr uint16_t      FRAME_SIZE            = BLE_MTU-ATT_HDR_BYTES; // Payload is MTU minus ATT header size

inline constexpr int8_t        RSSI_LOW_THRESHOLD    =  -80;   // low power threshold (increase power if in LOWPOWER mode)
inline constexpr int8_t        RSSI_FAST_THRESHOLD   =  -65;   // Switch back to 2M/1M
inline constexpr int8_t        RSSI_HYSTERESIS       =    4;   // Prevent oscillation
inline constexpr int8_t        RSSI_S8_THRESHOLD     =  -82;   // go S=8 below this
inline constexpr int8_t        RSSI_S2_THRESHOLD     =  -75;   // go S=2 below this
inline constexpr uint32_t      RSSI_INTERVAL         =  500;   // 0.5s

// ===== LL (Link-Layer) performance knobs =====
// If MTU is larger than LL size the GATT packets need to be fragmented on the link layer
// default LL size is 27
// maximum is 251
// Common BLE 4.2/5.0 DLE targets is 244
inline constexpr uint16_t      LL_DEF_TX_OCTETS     =    27;    // 27..251
inline constexpr uint16_t      LL_CONS_TX_OCTETS    =   244;    // 27..251
inline constexpr uint16_t      LL_MAX_TX_OCTETS     =   251;    // 27..251

#if defined(SPEED)
  // max speed
  inline constexpr uint16_t    LL_TX_OCTETS         = LL_MAX_TX_OCTETS;
#elif defined(LOWPOWER)
  // low power
  inline constexpr uint16_t    LL_TX_OCTETS         = LL_DEF_TX_OCTETS;
#else
  // long range
  inline constexpr uint16_t    LL_TX_OCTETS         = LL_CONS_TX_OCTETS;
#endif

inline constexpr uint16_t      LL_TIME_1M_US        =  2120;    // for 1M PHY
inline constexpr uint16_t      LL_TIME_2M_US        =  1060;    // for 2M PHY
inline constexpr uint16_t      LL_TIME_CODED_S2_US  =  4240;    // for Coded PHY (S2)
inline constexpr uint16_t      LL_TIME_CODED_S8_US  = 16960;    // for Coded PHY (S8)

// ===== Security / Pairing =====
inline constexpr uint32_t BLE_PASSKEY_VALUE         =123456;    // Generic static Passkey

// ===== UUIDs =====
// Nordic UART Serial (NUS)
inline constexpr const char SERVICE_UUID[]          = {"6E400001-B5A3-F393-E0A9-E50E24DCCA9E"};
inline constexpr const char CHARACTERISTIC_UUID_RX[]= {"6E400002-B5A3-F393-E0A9-E50E24DCCA9E"};
inline constexpr const char CHARACTERISTIC_UUID_TX[]= {"6E400003-B5A3-F393-E0A9-E50E24DCCA9E"};

// ===== BLE Optimizations =====
// helpers to convert from human units to BLE units
static constexpr uint16_t itvl_us(uint32_t us)    { return (uint16_t)((us * 4) / 5000); } // is in units of 1.25ms
static constexpr uint16_t tout_ms(uint32_t ms)    { return (uint16_t)(ms / 10); }         // is in units of 10ms

// connection interval, latency and supervision timeout
#if defined(SPEED)
  // aggressive speed
  #define MIN_BLE_INTERVAL         itvl_us( 7500)  // Minimum connection interval in microseconds 7.5ms to 4s
  #define MAX_BLE_INTERVAL         itvl_us(10000)  // Maximum connection interval in µs 7.5ms to 4s
  #define BLE_SLAVE_LATENCY                    0   // Slave latency: number of connection events that can be skipped
  #define BLE_SUPERVISION_TIMEOUT   tout_ms(4000)  // Supervision timeout in milli seconds 100ms to 32s, needs to be larger than 2 * (latency + 1) * (max_interval_ms)
#elif defined(LOWPOWER)
  // low power
  #define MIN_BLE_INTERVAL         itvl_us(60000) // 60ms
  #define MAX_BLE_INTERVAL        itvl_us(120000) // 120ms
  #define BLE_SLAVE_LATENCY                    8   // can raise
  #define BLE_SUPERVISION_TIMEOUT  tout_ms( 6000)  // 6s
#else
  // long range
  #define MIN_BLE_INTERVAL         itvl_us(30000)  // 30ms
  #define MAX_BLE_INTERVAL         itvl_us(60000)  // 60ms
  #define BLE_SLAVE_LATENCY                    2   // some dozing
  #define BLE_SUPERVISION_TIMEOUT   tout_ms(6000)  // 6s
#endif

// dBm levels similar to Bluedroid's ESP_PWR_LVL_* names:
#define BLE_TX_DBM_N12                    ( -12)
#define BLE_TX_DBM_N9                       (-9)
#define BLE_TX_DBM_N6                       (-6)
#define BLE_TX_DBM_N3                       (-3)
#define BLE_TX_DBM_0                         (0)
#define BLE_TX_DBM_P3                        (3)
#define BLE_TX_DBM_P6                        (6)
#define BLE_TX_DBM_P9                        (9)   // ~max on many ESP32s

// Scopes roughly matching ESP_BLE_PWR_TYPE_*
#define PWR_ALL  NimBLETxPowerType::All
#define PWR_ADV  NimBLETxPowerType::Advertising
#define PWR_SCAN NimBLETxPowerType::Scan
#define PWR_CONN NimBLETxPowerType::Connections

// Optional: make the key distribution explicit (same idea as init_key/rsp_key in Bluedroid)
inline constexpr uint8_t       KEYDIST_ENC          = 0x01;  // BLE_SM_PAIR_KEY_DIST_ENC
inline constexpr uint8_t       KEYDIST_ID           = 0x02;  // BLE_SM_PAIR_KEY_DIST_ID
inline constexpr uint8_t       KEYDIST_SIGN         = 0x04;  // BLE_SM_PAIR_KEY_DIST_SIGN
inline constexpr uint8_t       KEYDIST_LINK         = 0x08;  // BLE_SM_PAIR_KEY_DIST_LINK

// ===== BLE globals =====
static NimBLEServer          *pServer               = nullptr;           // BLE Server
static NimBLECharacteristic  *pTxCharacteristic     = nullptr;           // Transmission BLE Characteristic
static NimBLECharacteristic  *pRxCharacteristic     = nullptr;           // Reception BLE Characteristic
static NimBLEAdvertising     *pAdvertising          = nullptr;           // Advertising 
volatile bool                 deviceConnected       = false;             // Status
volatile bool                 clientSubscribed      = false;             // GATT client enabled notifications
const uint32_t                passkey               = BLE_PASSKEY_VALUE; // Define your passkey here
volatile uint16_t             txChunkSize           = FRAME_SIZE;
volatile uint16_t             mtu                   = txChunkSize+3; 
int8_t                        rssi                  = 0;                 // BLE signal strength
int8_t                        f_rssi                = -50;               // Filtered BLE signal strength

volatile bool                 phyIs2M               = false;
volatile bool                 phyIsCODED            = false;

static std::string            deviceMac;
/*
 NOTE: NimBLE-Arduino does not expose an API to read back whether CODED PHY
 negotiated S=2 vs S=8 after a generic coded request. We track 'desiredCodedScheme'
 (what we asked for) and assume the controller honored it. If the controller
 silently falls back (e.g. to S=8), timing estimates may be optimistic.
*/
volatile uint8_t              desiredCodedScheme    = 8; // what we asked for: 0=none, 2 (S=2), 8 (S=8)
volatile uint8_t              codedScheme           = 8; // what we got, currently wee can not read it back, so we assume what we asked for
volatile uint16_t             llTimeUS              = LL_TIME_1M_US;

volatile uint16_t             g_connectHandle       = BLE_HS_CONN_HANDLE_NONE; // connection handle
volatile uint16_t             g_ll_tx_octets        = LL_TX_OCTETS;
volatile uint16_t             g_ll_rx_octets        = LL_TX_OCTETS;
volatile uint16_t             g_ll_tx_time_us       = LL_TIME_1M_US;
volatile uint16_t             g_ll_rx_time_us       = LL_TIME_1M_US;

static char                   pending[FRAME_SIZE];                  // temp keep for sent frame
volatile bool                 generationAllowed     = true;         // producer gate based on buffer watermarks
volatile uint32_t             sendInterval          = 200;          // start fast

volatile int                  mtuRetryCount         = 0;            // number of times we retried to obtain MTU
const int                     mtuRetryMax           = 3;            // max number of times we retry to obtain MTU

// ===== Tx backoff/throttle =====
inline constexpr uint16_t     PROBE_AFTER_SUCCESSES = 64;           // wait this many clean sends before probing faster
inline constexpr uint16_t     PROBE_CONFIRM_SUCCESSES = 48;         // accept probe only after this many clean sends
inline constexpr uint32_t     PROBE_STEP_US         = 10;           // absolute probe step
inline constexpr uint32_t     PROBE_STEP_PCT        = 2;            // or % of current interval (use the larger of the two)

inline constexpr uint8_t      LKG_ESCALATE_AFTER_FAILS = 3;         // if LKG last known good fails this many times in a row, relax it
inline constexpr uint32_t     LKG_ESCALATE_NUM      = 103;          // ×1.03
inline constexpr uint32_t     LKG_ESCALATE_DEN      = 100;

inline constexpr int          COOL_SUCCESS_REQUIRED = 64;           // successes before probing resumes after a backoff
inline constexpr uint32_t     ESCALATE_COOLDOWN_US  = 1000000;      // 1 s
inline constexpr uint32_t     TIMEOUT_BACKOFF_NUM   = 6;            // ×1.20 on timeout
inline constexpr uint32_t     TIMEOUT_BACKOFF_DEN   = 5;

volatile uint32_t             lkgInterval           = 0;            // last-known-good interval
volatile bool                 probing               = false;        // currently probing lkg
volatile uint16_t             probeSuccesses        = 0;
volatile uint8_t              probeFailures         = 0;
volatile uint8_t              lkgFailStreak         = 0;
volatile unsigned long        lastEscalateAt        = 0; 

volatile uint32_t             minSendIntervalUs     =  200;         // floor in µs
const uint32_t                maxSendIntervalUs     =
#if defined(LOWPOWER)
// low power:
                                                    100000;         // 100 ms – 500 ms typical for low power
#elif defined(SPEED)
// max speed
                                                      5000;         // 5 ms cap for aggressive streams
#else
// long range
                                                     30000;         // 30 ms balanced
#endif

volatile uint64_t             lastSend              = 0;            // last time data was sent/notify (µs, 64-bit to avoid wrap)
volatile size_t               pendingLen            = 0;            // length data that we attempted to send
volatile bool                 txOkFlag              = false;        // no issues last data was sent
volatile int                  successStreak         = 0;            // number of consecutive successful sends
volatile int                  cooldownSuccess       = 0;            // successes since last backoff
volatile bool                 recentlyBackedOff     = false;        // gate decreases after congestion
volatile uint8_t              badDataRetries        = 0;            // EBADDATA soft fallback attempts
inline constexpr uint8_t      badDataMaxRetries     = 3;            // limit EBADDATA chunk shrink attempts

// ===== Tasks =====
static TaskHandle_t           txTaskHandle          = nullptr;
volatile bool                 txDropPending         = false;
static TaskHandle_t           rssiTaskHandle        = nullptr;

// *****************************************************************************************************************

// ===== General Globals =====
unsigned long                 currentTime;
unsigned long                 interval              = 10000;        // Default interval at which to generate data
unsigned long                 blinkInterval         =  1000;
unsigned long                 lastBlink;
static bool                   userSetInterval       = false;
static bool                   fastMode              = false;        // true if scenario 11 or 20 (run as fast as possible)

const int                     ledPin                = LED_BUILTIN; 
int                           ledState              = LOW; 
int                           samplerate            =  1000;
bool                          paused                = true;         // Flag to pause the data generation
String                        receivedCommand       = "";
volatile bool                 commandPending        = false;        // Flag to indicate if a command is waiting to be processed
char                          data[1024];
unsigned long                 lastDataGenerationTime= 0;            // Last time data was produced

// ===== Data generation globals =====
int                           scenario              =    6;        // stereo sine wave
float                         frequency             =  100.0;      // frequency (Hz)
float                         amplitude             = 1024;        // amplitude
static float                  loc                   =    0;
inline constexpr size_t       TABLESIZE             =  512;        // Number of samples in one full cycle for sine, sawtooth etc
inline constexpr unsigned long SPEEDTEST_DEFAULT_INTERVAL_US = 20;  // e.g. for ESP32

int16_t                       signalTable[TABLESIZE];

// ===== Add timing constraints and helpers (place near other globals) =====
inline constexpr int          MIN_SAMPLERATE_HZ     =      1;
inline constexpr int          MAX_SAMPLERATE_HZ     = 200000;       // 200kHz, limit for Stereo on Teensy is like 80ksps
inline constexpr unsigned long MIN_INTERVAL_US      =    100;       // 0.1 ms minimum frame period
inline constexpr unsigned long MAX_INTERVAL_US      = 500000;       // 500 ms maximum frame period

// ===== BLE Speedtester Globals =====
unsigned long                 lastBLETime           =        0;     // Last time data was produced
unsigned long                 lastCounts            = 10000000; 
unsigned long                 currentCounts         = 10000000;     // Number of lines sent
unsigned long                 countsPerSecond       =        0;

// ===== BLE Mono/Stereo Globals =====

// Fixed-point phase config
constexpr uint32_t ilog2_u32(uint32_t v) {
  uint32_t n = 0;
  while (v > 1) { v >>= 1; ++n; }
  return n;
}
constexpr uint32_t            INT_BITS              = ilog2_u32((uint32_t)TABLESIZE);      // e.g. 9 for 512
constexpr uint32_t            FRAC                  = 32u - INT_BITS;                      // e.g. 23 for 512
constexpr uint64_t            PHASE_MOD             = (uint64_t)TABLESIZE << FRAC;
constexpr uint64_t            PHASE_MASK            = PHASE_MOD - 1ull;
static uint32_t               phase                 = 0;
float                         stereo_drift_hz       = 0.2f;         // adjust for faster/slower relative phase sweep
static uint32_t               stereo_offset_fp      = 0;            // fixed‑point phase offset accumulator (8.24)

static inline uint32_t phase_inc_from_hz(float hz, int sr) {
  if (hz <= 0.0f || sr <= 0) return 0u;
  return (uint32_t)((((uint64_t)TABLESIZE << FRAC) * (double)hz) / (double)sr);
}
static inline uint32_t advance_phase(uint32_t p, uint32_t inc) {
  return (p + inc) & (uint32_t)PHASE_MASK;
}
static inline int table_index(uint32_t p) {
  return (int)((p >> FRAC) & (TABLESIZE - 1));
}

// ===============================================================================================================================================================
// TX task 
// ===============================================================================================================================================================

#if HAS_ESP_TIMER
static inline uint64_t nowMicros() { return esp_timer_get_time(); }
#else
static inline uint64_t nowMicros() { return (uint64_t)micros(); }
#endif

static inline void relax_delay_us(uint32_t us) {
  if (us == 0) return;
  #if defined(ARDUINO_ARCH_ESP32)
    esp_rom_delay_us(us);
  #else
    delayMicroseconds(us);
  #endif
}

// Only the TX task touches pendingLen/txBuffer; callbacks set flags.
static void TxTask(void* /*arg*/) {
  uint64_t nextDue = nowMicros();
  for (;;) {

    // Wait until subscribed and connected
    if (!deviceConnected || !clientSubscribed) {
      vTaskSuspend(nullptr); // resumed by onSubscribe
      // After resume, fall through and process immediately
      nextDue = nowMicros();
    }

    if (!deviceConnected || !clientSubscribed) continue;

    // honor drop request posted by callbacks (e.g., MTU/EMSGSIZE)
    if (txDropPending) {
      pendingLen    = 0;
      txDropPending = false;
      if (txBuffer.available() <= lowWaterMark) generationAllowed = true;
    }

    // consume after a successful notify (signaled by onStatus)
    if (txOkFlag && pendingLen > 0) {
      txBuffer.consume(pendingLen);
      txOkFlag   = false;
      pendingLen = 0;
      if (txBuffer.available() <= lowWaterMark) generationAllowed = true;
    }

    // stage a frame if none is pending
    if (pendingLen == 0) {
      size_t avail = txBuffer.available();
      if (avail > 0) {
        pendingLen = txBuffer.peek(pending, txChunkSize);
        if (pendingLen > 0) generationAllowed = false;
      }
    }

    // If nothing staged, arm a short poll and wait to avoid busy-spin
    if (pendingLen == 0) {
      vTaskDelay(pdMS_TO_TICKS(1));
      nextDue = nowMicros();
      continue;
    }

    // Wait until the next send slot. Favor coarse sleeps when far ahead, fine waits when close.
    uint64_t now = nowMicros();
    int64_t  delta = (int64_t)(nextDue - now);
    if (delta > 1500) {
      // Convert to ms, keep at least 1 tick margin; clamp to avoid zero
      TickType_t waitTicks = pdMS_TO_TICKS((uint32_t)((delta - 1000) / 1000));
      if (waitTicks < 1) waitTicks = 1;
      vTaskDelay(waitTicks);
      continue;
    }
    if (delta > 50) {
      relax_delay_us((uint32_t)(delta - 25));
      continue;
    }
    if (delta > 0) {
      // Barely early; yield once to let NimBLE host run before retrying
      taskYIELD();
      continue;
    }

    // queue one notification; onStatus will signal outcome
    pTxCharacteristic->setValue(reinterpret_cast<uint8_t*>(pending), pendingLen);
    pTxCharacteristic->notify();
    lastSend = nowMicros();

    // Schedule the next slot relative to the current send time (avoid drift on long stalls)
    nextDue = lastSend + (uint64_t)sendInterval;

    // Yield so NimBLE host/stack can advance between notifications
    taskYIELD();
  }
}

// ===============================================================================================================================================================
// RSSI monitor task: polls RSSI and adjusts PHY with hysteresis
// ===============================================================================================================================================================

static void RssiTask(void* arg) {
  const TickType_t pollPeriod = pdMS_TO_TICKS(RSSI_INTERVAL); 
  int8_t tmp_rssi = 0;
  for (;;) {
    if (!deviceConnected || g_connectHandle == BLE_HS_CONN_HANDLE_NONE) {
      vTaskDelay(pdMS_TO_TICKS(200));
      continue;
    }

    if (ble_gap_conn_rssi(g_connectHandle, &tmp_rssi) == 0) {
      rssi = tmp_rssi;
      f_rssi = (int8_t)((4 * (int)f_rssi + (int)rssi) / 5); // low pass filter (approx 4.5s)

      // If RSSI is low and we are on 2M or 1M switch to CODED

      if (f_rssi < (RSSI_S8_THRESHOLD - RSSI_HYSTERESIS)) {
        if (!phyIsCODED || codedScheme != 8) {
          #if DEBUG_LEVEL >= INFO
            Serial.printf("Switching to CODED 8 (RSSI: %d)\r\n", f_rssi);
          #endif
          desiredCodedScheme = 8; // prefer S=8 for range
          if (0 != ble_gap_set_prefered_le_phy(
              g_connectHandle,
              BLE_GAP_LE_PHY_CODED_MASK,
              BLE_GAP_LE_PHY_CODED_MASK,
              BLE_GAP_LE_PHY_CODED_S8)) {
            #if DEBUG_LEVEL >= WARNING
              Serial.println("Failed to set preferred PHY");
            #endif
          }
        }
      } else if (f_rssi < (RSSI_S2_THRESHOLD - RSSI_HYSTERESIS)) {
        if (!phyIsCODED || codedScheme != 2) {
          #if DEBUG_LEVEL >= INFO
            Serial.printf("Switching to CODED 2 (RSSI: %d)\r\n", f_rssi);
          #endif
          desiredCodedScheme = 2;
          if (0 != ble_gap_set_prefered_le_phy(
              g_connectHandle,
              BLE_GAP_LE_PHY_CODED_MASK,
              BLE_GAP_LE_PHY_CODED_MASK,
              BLE_GAP_LE_PHY_CODED_S2)) {
            #if DEBUG_LEVEL >= WARNING
              Serial.println("Failed to set preferred PHY");
            #endif
          }
        }

      // If RSSI is good and we are on CODED switch to 2M/1M

      } else if (f_rssi > (RSSI_FAST_THRESHOLD + RSSI_HYSTERESIS)) {
        // High RSSI: allow 2M/1M
        if (phyIsCODED || codedScheme != 0) {
          #if DEBUG_LEVEL >= INFO
            Serial.printf("Switching to 2M/1M (RSSI: %d)\r\n", f_rssi);
          #endif
          desiredCodedScheme = 0;
          if (0 != ble_gap_set_prefered_le_phy(
              g_connectHandle,
              BLE_GAP_LE_PHY_2M_MASK | BLE_GAP_LE_PHY_1M_MASK,
              BLE_GAP_LE_PHY_2M_MASK | BLE_GAP_LE_PHY_1M_MASK,
              0)) {
            #if DEBUG_LEVEL >= ERROR
              Serial.println("Failed to set preferred PHY");
            #endif
          }
        }
      }
    } else {
      // error reading RSSI
      #if DEBUG_LEVEL >= WARNING
        Serial.println("Error reading RSSI");
      #endif
    }

    vTaskDelay(pollPeriod);
  }
}

// ===============================================================================================================================================================
// Helpers for TX sizing & pacing
// ===============================================================================================================================================================

static inline uint16_t compute_txChunkSize(uint16_t mtu_val, uint16_t ll_octets) {
    // Base payload is MTU-3 (ATT header excluded). For SPEED profile, allow up to
    // 2 LL PDUs to reduce per-notify overhead; otherwise keep within a single LL PDU.
    if (mtu_val <= 3) return 20;
    const uint16_t att_payload = (uint16_t)(mtu_val - 3);

    // Max payload fitting N LL PDUs: N*ll_octets - (L2CAP 4 + ATT 3)
    const uint16_t one_pdu_max = (ll_octets > 7) ? (uint16_t)(ll_octets - 7) : 20;
    #if defined(SPEED)
      // const uint32_t two_pdu_calc = (uint32_t)ll_octets * 2u;
      // const uint16_t two_pdu_max  = (two_pdu_calc > 7u) ? (uint16_t)(two_pdu_calc - 7u) : one_pdu_max;
      // uint16_t llLimit = (two_pdu_max > one_pdu_max) ? two_pdu_max : one_pdu_max;
      uint16_t llLimit = one_pdu_max;
    #else
      uint16_t llLimit = one_pdu_max;
    #endif

    // Final chunk is limited by both ATT MTU and chosen LL limit
    return (att_payload < llLimit) ? att_payload : llLimit;
}

static inline uint32_t compute_minSendIntervalUs(uint16_t chunkSize, uint16_t ll_octets, uint16_t ll_time_us) {
    // Estimate number of link-layer PDUs (ceil divide), then multiply by per-PDU time (+10% guard)
    uint16_t l2cap_plus_att = (uint16_t)(chunkSize + 4 /*L2CAP hdr*/ + 3 /*ATT hdr*/);
    uint16_t num_ll_pd   = (uint16_t)((l2cap_plus_att + ll_octets - 1) / ll_octets);
    // mode-specific guard
    #if defined(SPEED)
      const uint32_t guard_num = 103, guard_den = 100;  // +3%
    #elif defined(LOWPOWER)
      const uint32_t guard_num = 110, guard_den = 100;  // +10%
    #else // LONGRANGE
      const uint32_t guard_num = 115, guard_den = 100;  // +15%
    #endif    
    return (uint32_t)num_ll_pd * (uint32_t)ll_time_us * guard_num / guard_den;
}

static inline size_t update_lowWaterMark(size_t chunkSize) {
    size_t lw = 2 * (size_t)chunkSize;              // up to two outbound packets buffered
    size_t cap = TX_BUFFERSIZE / 4;                    // don't let low water exceed 25% of buffer
    if (lw > cap) lw = cap;
    if (lw < chunkSize) lw = chunkSize;             // never below one chunk
    return lw;
}

static inline void reset_tx_ramp(bool forceToMin) {
  probing            = false;
  probeSuccesses     = 0;
  probeFailures      = 0;
  lkgFailStreak      = 0;
  recentlyBackedOff  = false;
  cooldownSuccess    = 0;
  successStreak      = 0;
  if (forceToMin || sendInterval == 0 || sendInterval > minSendIntervalUs) {
    sendInterval = minSendIntervalUs;
  } else if (sendInterval < minSendIntervalUs) {
    sendInterval = minSendIntervalUs;
  }
  lkgInterval = sendInterval;
}

static inline void recompute_tx_timing() {
  // update chunk size and send interval floor
  txChunkSize  = compute_txChunkSize(mtu, g_ll_tx_octets);
  minSendIntervalUs = compute_minSendIntervalUs(txChunkSize, g_ll_tx_octets, llTimeUS);
  if (sendInterval < minSendIntervalUs) sendInterval = minSendIntervalUs;
  lowWaterMark = update_lowWaterMark(txChunkSize);
  // Seed/repair last-known-good after timing changes
  if (lkgInterval == 0 || lkgInterval < minSendIntervalUs) lkgInterval = sendInterval;
  if (!probing && lkgInterval > sendInterval) lkgInterval = sendInterval;
  size_t used = txBuffer.available();
  if (pendingLen == 0 && used <= lowWaterMark) {
      generationAllowed = true;
  }
  reset_tx_ramp(true);
}

static inline void update_ll_time() {
  // update llTimeUS based on current PHY,
  //   consider 1M, 2M and CODED
  //   then recompute tx timing
  if (phyIsCODED) {
      llTimeUS = (codedScheme == 2) ? LL_TIME_CODED_S2_US : LL_TIME_CODED_S8_US;
  } else if (phyIs2M) {
      llTimeUS = LL_TIME_2M_US;
  } else {
      llTimeUS = LL_TIME_1M_US;
  }
  recompute_tx_timing();
}

// ===============================================================================================================================================================
// BLE Service and Characteristic Callbacks
// ===============================================================================================================================================================

// ----------------
// Server Callbacks 
// ----------------
class ServerCallbacks : public NimBLEServerCallbacks {

private:
  static const char* hciDisconnectReasonStr(uint8_t r) {
  switch (r) {
    case 0x08: return "Connection Timeout";
    case 0x10: return "Remote User Terminated";
    case 0x13: return "Remote User Terminated";          // 0x13 (same meaning)
    case 0x16: return "Connection Terminated by Local Host";
    case 0x3B: return "Unacceptable Connection Parameters";
    case 0x3D: return "MIC Failure";
    case 0x3E: return "Connection Failed to be Established";
    default:   return "Unknown";
  }
}

public:
  void onConnect(NimBLEServer* pServer, NimBLEConnInfo &connInfo) override {
    deviceConnected = true;
    g_connectHandle = connInfo.getConnHandle();

    // We can use the connection handle here to ask for different connection parameters.
    pServer->updateConnParams(
      g_connectHandle, 
      MIN_BLE_INTERVAL,
      MAX_BLE_INTERVAL,
      BLE_SLAVE_LATENCY,
      BLE_SUPERVISION_TIMEOUT
    );

    //PHY and DLE tuning
    #if defined(SPEED)
      // Max speed
      // Ask for 2M (if not supported, rc will be non-zero; that's OK)
      (void)ble_gap_set_prefered_le_phy(g_connectHandle, BLE_GAP_LE_PHY_2M_MASK, BLE_GAP_LE_PHY_2M_MASK, 0);
    #elif defined (LOWPOWER)
      // Low Power
      (void)ble_gap_set_prefered_le_phy(g_connectHandle, BLE_GAP_LE_PHY_1M_MASK, BLE_GAP_LE_PHY_1M_MASK, 0);
    #else
      // Long Range
      (void)ble_gap_set_prefered_le_phy(
        g_connectHandle, 
        BLE_GAP_LE_PHY_CODED_MASK, 
        BLE_GAP_LE_PHY_CODED_MASK, 
        (desiredCodedScheme == 8) ? BLE_GAP_LE_PHY_CODED_S8 : BLE_GAP_LE_PHY_CODED_S2);
    #endif

    // Read the PHY actually in use
    uint8_t txPhy = 0, rxPhy = 0;
    if (ble_gap_read_le_phy(g_connectHandle, &txPhy, &rxPhy) == 0) {
      // Pick the correct LL time based on the negotiated PHY
      phyIs2M    = (txPhy == BLE_HCI_LE_PHY_2M) && (rxPhy == BLE_HCI_LE_PHY_2M);
      phyIsCODED = (txPhy == BLE_HCI_LE_PHY_CODED) && (rxPhy == BLE_HCI_LE_PHY_CODED);
      if (phyIsCODED) { 
        // Reading coding scheme is not supported
         //
        // Coded PHY: check if S=8 or S=2 (default to S=8 if we can't read)
        // uint8_t codedPhyOptions = 0;
        // if (ble_gap_read_phy_options(g_connectHandle, &codedPhyOptions) == 0) {
        //   // S=8 is more robust but slower than S=2
        //   codedScheme = (codedPhyOptions & BLE_GAP_LE_PHY_CODED_S2) ? 2 : 8;
        // } else {
        //   codedScheme = 8; // assume S=8 if we can't read
        // }
        codedScheme = desiredCodedScheme;
      } else {
        codedScheme = 0;
      }
      update_ll_time(); // ll time depends  on 1M, 2M and coded

      // Apply DLE for this link
      (void)ble_gap_set_data_len(g_connectHandle, LL_TX_OCTETS, llTimeUS);
      // reset controller
      probing = false; probeSuccesses = 0; probeFailures = 0; lkgFailStreak = 0;
      recentlyBackedOff = false; cooldownSuccess = 0; successStreak = 0;
      lkgInterval = sendInterval;
  badDataRetries = 0;

    } else {
      // Fallback: assume 1M timings if we couldn't read
      (void)ble_gap_set_data_len(g_connectHandle, LL_TX_OCTETS, LL_TIME_1M_US);
    }

    #if defined(LOWPOWER)
      // Adjust power if too low
      // If available in your build: IDF/NimBLE has ble_gap_conn_rssi()
      int8_t tmp_rssi = 0;
      if (ble_gap_conn_rssi(g_connectHandle, &tmp_rssi) == 0) {
        rssi = tmp_rssi;
        f_rssi = rssi;
        if (rssi < RSSI_LOW_THRESHOLD) {
          NimBLEDevice::setPower(BLE_TX_DBM_0,  PWR_CONN); // boost
        } else if (rssi > RSSI_FAST_THRESHOLD) {
          NimBLEDevice::setPower(BLE_TX_DBM_N6, PWR_CONN); // trim
        }
      }
    #endif    
 
    // Start Pairing

    #if defined(BLE_SECURE)
      NimBLEDevice::startSecurity(g_connectHandle);
    #endif

  // resume background RSSI task; keep TX task suspended until subscribed
  if (rssiTaskHandle) vTaskResume(rssiTaskHandle);
  if (txTaskHandle)   vTaskSuspend(txTaskHandle);

    #if DEBUG_LEVEL >= INFO
      Serial.printf("Client [%s] is connected.\r\n", connInfo.getAddress().toString().c_str());
    #endif

  }

  // When a client disconnects
  void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo &connInfo, int reason) override {
    g_connectHandle = BLE_HS_CONN_HANDLE_NONE;
    phyIs2M         = false;
    phyIsCODED      = false;
    codedScheme     = 0;
    update_ll_time();                    // back to 1M defaults
    deviceConnected = false;
    clientSubscribed = false;
    generationAllowed = false;
    pendingLen      = 0;                 // drop in-flight frame (or keep if you want to resend on next conn)
    successStreak   = 0;
    sendInterval    = maxSendIntervalUs; // restart conservatively
    NimBLEDevice::startAdvertising();    // Restart advertising immediately

  // suspend tasks on disconnect
  if (txTaskHandle)   vTaskSuspend(txTaskHandle);
  if (rssiTaskHandle) vTaskSuspend(rssiTaskHandle);
  txDropPending = false;
  badDataRetries = 0;

        #if DEBUG_LEVEL >= INFO
      uint8_t hci =  (uint8_t)(reason & 0xFF);
      Serial.printf("Client [%s] is disconnected (raw=%d, %s). Advertising restarted.\r\n",
                    connInfo.getAddress().toString().c_str(), reason, hciDisconnectReasonStr(hci));
    #endif
  }

  // MTU updated
  void onMTUChange(uint16_t m, NimBLEConnInfo& connInfo) override {
    mtu = m;
    recompute_tx_timing();
    probing = false; probeSuccesses = 0; probeFailures = 0; lkgFailStreak = 0;
    recentlyBackedOff = false; cooldownSuccess = 0; successStreak = 0;
    lkgInterval = sendInterval;   
    badDataRetries = 0; 
    #if DEBUG_LEVEL >= INFO
      Serial.printf("MTU updated: %u (conn=%u), tx chunk size=%u, min send interval=%u\r\n", 
        m, connInfo.getConnHandle(), txChunkSize, minSendIntervalUs);
    #endif
  }

  // Security callbacks 

  // Passkey display
  uint32_t onPassKeyDisplay() override {
    #if DEBUG_LEVEL >= WANTED
      Serial.printf("Server Passkey Display: %u\r\n", BLE_PASSKEY_VALUE);
    #endif
    // This should return a random 6 digit number for security
    //   or make your own static passkey as done here.
    return BLE_PASSKEY_VALUE;
 }

  // Request to confirm a passkey value match
  void onConfirmPassKey(NimBLEConnInfo& connInfo, uint32_t pass_key) override {
    /** Inject false if passkeys don't match. */
    if (pass_key == BLE_PASSKEY_VALUE) {
      NimBLEDevice::injectConfirmPasskey(connInfo, true);
      #if DEBUG_LEVEL >= INFO
        Serial.printf("The passkey: %" PRIu32 " matches\r\n", pass_key);
      #endif
    } else {
      NimBLEDevice::injectConfirmPasskey(connInfo, false);
      #if DEBUG_LEVEL >= INFO
        Serial.printf("The passkey: %" PRIu32 "does not match\r\n", pass_key);
      #endif
    }
  }

  // Authentication complete
  void onAuthenticationComplete(NimBLEConnInfo& connInfo) override {
    // Check that encryption was successful, if not we disconnect the client
    //   When security is turned off this will not be called
    if (!connInfo.isEncrypted()) {
      NimBLEDevice::getServer()->disconnect(connInfo.getConnHandle());
      #if DEBUG_LEVEL >= WARNING
        Serial.printf("Encrypt connection failed - disconnecting client\r\n");
      #endif
      return;
    }
    #if DEBUG_LEVEL >= INFO
      Serial.printf("Secured connection to: %s\r\n", connInfo.getAddress().toString().c_str());
    #endif
  }

} serverCallBacks;

// ----------------
// RX Callbacks
// ----------------
class RxCallback : public NimBLECharacteristicCallbacks {
public:

  // A client wrote new data to the RX characteristic
  void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
    const std::string &v = pCharacteristic->getValue();
    if (!v.empty()) {
      // Push received data into rxBuffer; allow overwrite to avoid stalling on bursts
      rxBuffer.push(v.data(), v.size(), true);
    }
    #if DEBUG_LEVEL >= DEBUG
      Serial.printf("%s : onWrite(), value: %s\r\n",
                    pCharacteristic->getUUID().toString().c_str(),
                    v.c_str());
    #endif
  }


} receiverCallBacks;

// ----------------
// TX Callbacks
// ----------------
class TxCallback : public NimBLECharacteristicCallbacks {
public:

  // ---- Status code normalization helpers ----
  static inline bool isOkOrDone(int code) {
    return (code == 0 || code == BLE_HS_EDONE || code == 14);
  }
  static inline bool isMsgSize(int code) {
    return (code == BLE_HS_EMSGSIZE || code == 4);
  }
  static inline bool isBadData(int code) {
    // EBADDATA observed as 9 and 10 across builds; include both
    return (code == BLE_HS_EBADDATA || code == 9 || code == 10);
  }
  static inline bool isCongestion(int code) {
    // Treat ENOMEM/ENOMEM_EVT/EBUSY/TIMEOUT as congestion. Accept observed integers too.
    return (code == BLE_HS_ENOMEM       || code == 6  ||
            code == BLE_HS_ENOMEM_EVT   || code == 12 || code == 20 ||
            code == BLE_HS_EBUSY        || code == 15 ||
            code == BLE_HS_ETIMEOUT     || code == 13);
  }
  static inline bool isDisconnectedOrEOS(int code) {
    // ENOTCONN and EOS; observed EOS sometimes 10/11 in logs
    return (code == BLE_HS_ENOTCONN || code == 7 || code == BLE_HS_EOS || code == 10 || code == 11);
  }
  static const char* codeName(int code) {
    switch (code) {
      case 0:  return "OK(0)";
      case 2:  return "EINVAL(2)";
      case 3:  return "EADVSTATE(3)"; // placeholder
      case 4:  return "EMSGSIZE(4)";
      case 5:  return "EALREADY(5)";
      case 6:  return "ENOMEM(6)";
      case 7:  return "ENOTCONN(7)";
      case 8:  return "EAPP(8)";
      case 9:  return "EBADDATA(9)";
      case 10: return "EBADDATA/EOS(10)";
      case 11: return "EOS(11)";
      case 12: return "ENOMEM_EVT(12)";
      case 13: return "ETIMEOUT(13)";
      case 14: return "EDONE(14)";
      case 15: return "EBUSY(15)";
      case 16: return "EDISABLED(16)";
      case 18: return "ENOTSYNCED(18)";
      case 19: return "EAUTHEN(19)";
      case 20: return "EAUTHOR/ENOMEM_EVT?(20)";
      default: return "UNKNOWN";
    }
  }

  // A notification was sent to the client.
  void onStatus(NimBLECharacteristic* pCharacteristic, int code) override {
  /* 
    0 → Success (notification queued/sent). 
    1 (BLE_HS_EUNKNOWN) → Unknown error.
   14 (BLE_HS_EDONE)    → Success for indication (confirmation received). 
    6 (BLE_HS_ENOMEM)   → Out of buffers / resource exhaustion. You’re sending faster than the stack can drain, or mbufs are tight. Back off or throttle. 
   15 (BLE_HS_EBUSY)    → Another LL/GATT procedure is in progress; try again later. 
   13 (BLE_HS_ETIMEOUT) → Timed out (e.g., indication not confirmed). 
    7 (BLE_HS_ENOTCONN) → Connection went away / bad handle. 
  3/2 (BLE_HS_EINVAL)   → Bad arg / state. 
    4 (BLE_HS_EMSGSIZE) → Payload too big for context. (For notifies you should already be ≤ MTU−3.)
    5 (BLE_HS_EALREADY) → Operation already in progress.
    8 (BLE_HS_EAPP)     → Application error.
    9 (BLE_HS_EBADDATA) → Malformed data.
   10 (BLE_HS_EOS)      → Connection closed, end of stream.
   12 (BLE_HS_ENOMEM_EVT) → Out of memory for event allocation.
   16 (BLE_HS_EDISABLED) → BLE stack not enabled.
   18 (BLE_HS_ENOTSYNCED)→ Host not synced with controller yet.
   19 (BLE_HS_EAUTHEN)   → Authentication failed.
   20 (BLE_HS_EAUTHOR)   → Authorization failed.
   21 (BLE_HS_EENCRYPT)  → Encryption failed.
   22 (BLE_HS_EENCRYPT_KEY_SZ) → Insufficient key size.
   23 (BLE_HS_ESTORE_CAP) → Storage capacity reached (bonding).
   24 (BLE_HS_ESTORE_FAIL) → Persistent storage write failed.
   25 (BLE_HS_EHCI)      → Low-level HCI failure.
  */

    if (isOkOrDone(code)) 
    {
      // Success ---------------------------------------------------
      txOkFlag = true;
      mtuRetryCount = 0;

      // cooldown after any backoff/error before allowing new probes for faster rates
      if (recentlyBackedOff) {
        if (++cooldownSuccess >= COOL_SUCCESS_REQUIRED) {
          recentlyBackedOff = false;
          cooldownSuccess   = 0;
          successStreak     = 0;
          lkgFailStreak     = 0; // reset fail streak when we calm down
        }
        return; // do not probe during cooldown
      }

      // If we are probing for faster rates, count successes; accept probe once stable
      if (probing) {
        if (++probeSuccesses >= PROBE_CONFIRM_SUCCESSES) {
          lkgInterval   = sendInterval;   // new stable floor
          probing       = false;
          probeSuccesses= 0;
          probeFailures = 0;
          lkgFailStreak = 0;
          successStreak = 0;
          #if DEBUG_LEVEL >= INFO
            Serial.printf("Probe accepted. LKG=%u\r\n", lkgInterval);
          #endif
        }
        return;
      }

      // Not probing: a success at LKG clears fail streak
      lkgFailStreak = 0;
 
      // After enough successes, try a small faster probe
      if (++successStreak >= PROBE_AFTER_SUCCESSES) {
        successStreak    = 0;
        lkgInterval      = sendInterval;
        uint32_t stepAbs = PROBE_STEP_US;
        uint32_t stepPct = (sendInterval * PROBE_STEP_PCT) / 100;
        uint32_t step    = (stepPct > stepAbs) ? stepPct : stepAbs;
        uint32_t cand    = (sendInterval > step) ? (sendInterval - step) : minSendIntervalUs;
        if (cand < minSendIntervalUs) cand = (uint32_t)minSendIntervalUs;
        if (cand < sendInterval) {
          sendInterval   = cand;
          probing        = true;
          probeSuccesses = 0;
          probeFailures  = 0;
          #if DEBUG_LEVEL >= INFO
            Serial.printf("Probe start: %u -> %u\r\n", lkgInterval, sendInterval);
          #endif
        }
      }
    }
    
    else if (isMsgSize(code)) 
    {
      // Payload too big for context -----------------------------------
      // Recompute chunk size and timing to the current negotiated MTU and restage
      if (++mtuRetryCount <= mtuRetryMax) 
      {
        // Try to get the current MTU from the controller
        uint16_t currentMtu = NimBLEDevice::getMTU();
        if (currentMtu != mtu) {
          mtu = currentMtu;
          recompute_tx_timing();
          #if DEBUG_LEVEL >= INFO
            Serial.printf("MTU adjusted, send interval: %u\r\n", sendInterval);
          #endif
        } else {
          uint16_t oldChunk = txChunkSize;
          txChunkSize = (uint16_t)max(20, (int)txChunkSize / 2);
          lowWaterMark = update_lowWaterMark(txChunkSize);
          minSendIntervalUs = compute_minSendIntervalUs(txChunkSize, g_ll_tx_octets, llTimeUS);
          if (sendInterval < minSendIntervalUs) sendInterval = minSendIntervalUs;
          #if DEBUG_LEVEL >= INFO
            Serial.printf("Chunk reduced old=%u new=%u minSendIntervalUs=%u\r\n",
                          oldChunk, txChunkSize, minSendIntervalUs);
          #endif
        }
        pendingLen  = 0; // drop staged copy (ring still has it)
        // Keep generationAllowed = false so next loop re-peeks the same data with the new size
      } 
      else 
      {
        // We have issues adjusting chunk size, last try effort before disconnect
        #if DEBUG_LEVEL >= WARNING
          Serial.println("EMSGSIZE retries exceeded");
        #endif
        if (txChunkSize > 20) {
          // One last fallback before disconnect: force minimum chunk and retry once
          txChunkSize = 20;
          lowWaterMark = update_lowWaterMark(txChunkSize);
          minSendIntervalUs = compute_minSendIntervalUs(txChunkSize, g_ll_tx_octets, llTimeUS);
          if (sendInterval < minSendIntervalUs) sendInterval = minSendIntervalUs;
          mtuRetryCount = 0; // give it another chance
        } else {
          #if DEBUG_LEVEL >= WARNING
            Serial.println("EMSGSIZE retries exceeded, disconnecting");
          #endif
          pServer->disconnect(g_connectHandle);
          mtuRetryCount = 0;
        }
        pendingLen = 0;
      }
    } 

    else if (isBadData(code))
    {
      // Malformed data (stack-side). Do NOT treat as congestion; try smaller chunks a few times.
      static uint32_t lastPrint9Us = 0;
      static uint16_t suppressed9  = 0;

      const uint64_t now = nowMicros();
      if ((now - lastPrint9Us) > 500000ULL) { // rate-limit: print at most ~2 Hz
        #if DEBUG_LEVEL >= WARNING
          if (suppressed9 > 0) {
            Serial.printf("EBADDATA: +%u suppressed\r\n", suppressed9);
          }
          Serial.printf("EBADDATA: code=%d (%s)\r\n", code, codeName(code));
        #endif
        lastPrint9Us = (uint32_t)now;
        suppressed9  = 0;
      } else {
        ++suppressed9; // quiet path
      }

      if (badDataRetries < badDataMaxRetries) {
        uint16_t oldChunk = txChunkSize;
        // shrink ~25% per attempt; floor at 20 bytes
        uint16_t newChunk = (uint16_t)max(20, (int)((oldChunk * 3) / 4));
        if (newChunk < oldChunk) {
          txChunkSize = newChunk;
          lowWaterMark = update_lowWaterMark(txChunkSize);
          minSendIntervalUs = compute_minSendIntervalUs(txChunkSize, g_ll_tx_octets, llTimeUS);
          if (sendInterval < minSendIntervalUs) sendInterval = minSendIntervalUs; // keep floor only
          ++badDataRetries;
          #if DEBUG_LEVEL >= INFO
            Serial.printf("EBADDATA: reduced chunk old=%u new=%u minSendIntervalUs=%u (retry %u/%u)\r\n",
                          oldChunk, txChunkSize, minSendIntervalUs, badDataRetries, badDataMaxRetries);
          #endif
        }
      }
      // Restage the same data at the new size; do not change pacing/probe state
      pendingLen    = 0;
      txDropPending = true;
    }

    else if (isCongestion(code)) 
    {
      // Congestion ------------------------------------------------
      successStreak = 0;
      recentlyBackedOff = true;
      cooldownSuccess = 0;

      if (probing) {
        probing = false;
        probeFailures++;
        sendInterval = lkgInterval;
        lkgFailStreak = 0;
        #if DEBUG_LEVEL >= INFO
          Serial.printf("Probe failed, revert to LKG=%u\r\n", sendInterval);
        #endif
      } else {
        // failure at LKG; if repeated, relax LKG slightly
        if (++lkgFailStreak >= LKG_ESCALATE_AFTER_FAILS) {
          unsigned long now = micros();
          // only escalate if cooldown passed AND buffer shows pressure
          size_t used = txBuffer.available();
          if ((now - lastEscalateAt) >= ESCALATE_COOLDOWN_US && used >= lowWaterMark) {
            lastEscalateAt = now;
            lkgFailStreak  = 0;
            uint32_t next  = (lkgInterval * LKG_ESCALATE_NUM) / LKG_ESCALATE_DEN;
            if (next < minSendIntervalUs) next = (uint32_t)minSendIntervalUs;
            if (next > maxSendIntervalUs) next = maxSendIntervalUs;
            lkgInterval  = next;
            sendInterval = next;
            #if DEBUG_LEVEL >= INFO
              Serial.printf("Escalate LKG to %u\r\n", lkgInterval);
            #endif
          }
        }
      }
    }
    
    else if (isDisconnectedOrEOS(code)) 
    {
      // Connection dropped
      successStreak = 0;
      recentlyBackedOff = false;
      cooldownSuccess = 0;
      probing = false;
      probeSuccesses = probeFailures = lkgFailStreak = 0;
      sendInterval = maxSendIntervalUs;
      lkgInterval  = sendInterval;
      #if DEBUG_LEVEL >= WARNING
        Serial.println("Connection dropped or EOS");
      #endif      
    } 

    else
    {
      // Unknown/unclassified error: log only; do not change pacing.
      if (probing) {
        probing       = false;
        sendInterval  = lkgInterval; // drop probe only
        lkgFailStreak = 0;
        #if DEBUG_LEVEL >= INFO
          Serial.printf("Unclassified issue %u (%s) while probing: revert to LKG=%u\r\n", code, codeName(code), sendInterval);
        #endif
      } else {
        #if DEBUG_LEVEL >= WARNING
          Serial.printf("Unclassified issue %u (%s) (no interval change)\r\n", code, codeName(code));
        #endif
      }
    }
  }
  // Peer subscribed to notifications/indications
  void onSubscribe(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo, uint16_t subValue) override {
  clientSubscribed = (bool)(subValue & 0x0001); // client subscribed to notifications

    // Start the tranmission task
  if (clientSubscribed) {
        if (txTaskHandle) vTaskResume(txTaskHandle);
    } else {
        if (txTaskHandle) vTaskSuspend(txTaskHandle);
    }

    #if DEBUG_LEVEL >= INFO
      std::string addr = connInfo.getAddress().toString();
      std::string uuid = pCharacteristic->getUUID().toString();
      if (subValue & 0x0001) {
        // Notifications
        Serial.printf("BLE GATT client %s subscribed to notifications: %s\r\n", addr.c_str(), uuid.c_str());
      }
      if (subValue & 0x0002) {
        // Indications
        Serial.printf("BLE GATT client %s subscribed to indications: %s\r\n", addr.c_str(), uuid.c_str());
      }
      if (subValue == 0)
        // Unsubscribed
        Serial.printf("BLE GATT client %s unsubscribed from: %s\r\n", addr.c_str(), uuid.c_str());
    #endif

  }

} transmitterCallBacks;

// ----------------
// GAP Callbacks
// ----------------
static int myGapHandler(struct ble_gap_event* ev, void* /*arg*/) {
  switch (ev->type) {
    // Fires whenever the controller updates data length for this link
    case BLE_GAP_EVENT_DATA_LEN_CHG: {

      // The event is not exposed in current version of Arduino NimBLE, so we use fixed values here
      //   and in future enable the commented code

      // const auto& p = ev->data_len_changed;        // negotiated, per-link
      // g_ll_tx_octets  = p.tx_octets;               // “connMaxTxOctets”
      // g_ll_tx_time_us = p.tx_time;                 // “connMaxTxTime” (µs)
      // g_ll_rx_octets  = p.rx_octets;               // “connMaxRxOctets”
      // g_ll_rx_time_us = p.rx_time;                 // “connMaxRxTime” (µs)
      // llTimeUS = g_ll_tx_time_us;
      g_ll_tx_octets  = LL_TX_OCTETS;
      g_ll_rx_octets  = LL_TX_OCTETS;
      g_ll_tx_time_us = llTimeUS;
      g_ll_rx_time_us = llTimeUS;
      recompute_tx_timing();
      probing = false; probeSuccesses = 0; probeFailures = 0; lkgFailStreak = 0;
      recentlyBackedOff = false; cooldownSuccess = 0; successStreak = 0;
      lkgInterval = sendInterval;     
      badDataRetries = 0; 
      #if DEBUG_LEVEL >= INFO
        Serial.printf("DLE updated: tx=%u octets / %u ll time µs, rx =%u octets / ll time %u µs, tx chunk size=%u, min send interval=%u\r\n",
                      g_ll_tx_octets, g_ll_tx_time_us, g_ll_rx_octets, g_ll_rx_time_us, 
                      txChunkSize, minSendIntervalUs);
      #endif
      break;
    }

    case BLE_GAP_EVENT_PHY_UPDATE_COMPLETE: {
      const auto& p = ev->phy_updated;
      phyIs2M    = (p.tx_phy == BLE_HCI_LE_PHY_2M)    && (p.rx_phy == BLE_HCI_LE_PHY_2M);
      phyIsCODED = (p.tx_phy == BLE_HCI_LE_PHY_CODED) && (p.rx_phy == BLE_HCI_LE_PHY_CODED);
      if (phyIsCODED) { 
        // Coded scheme is not accessible currently

        // Coded PHY: check if S=8 or S=2 (default to S=8 if we can't read)
        // uint8_t codedPhyOptions = 0;
        // if (ble_gap_read_phy_options(g_connectHandle, &codedPhyOptions) == 0) {
        //   // S=8 is more robust but slower than S=2
        //   codedScheme = (codedPhyOptions & BLE_GAP_LE_PHY_CODED_S2) ? 2 : 8;
        // } else {
        //   codedScheme = 8; // assume S=8 if we can't read
        // }
        codedScheme = (desiredCodedScheme == 2 ? 2 : 8);
      } else {
        codedScheme = 0;
      }
      update_ll_time(); // also recomputes tx timing
      probing = false; probeSuccesses = 0; probeFailures = 0; lkgFailStreak = 0;
      recentlyBackedOff = false; cooldownSuccess = 0; successStreak = 0;
      lkgInterval = sendInterval;     
      badDataRetries = 0; 
      #if DEBUG_LEVEL >= INFO
        Serial.printf("PHY updated: tx=%u rx=%u %s ll time=%u, tx chunk size=%u, min send interval=%u\r\n",
                      p.tx_phy, p.rx_phy,
                      phyIsCODED ? (codedScheme==2 ? "CODED(S2)" : "CODED(S8)") :
                                   (phyIs2M ? "2M" : "1M"),
                      llTimeUS, txChunkSize, minSendIntervalUs);
      #endif
      break;
    }    

    default:
      break;
  }
  return 0;
}

// ===============================================================================================================================================================
// Setup
// ===============================================================================================================================================================

void setup()
{
  pinMode(ledPin, OUTPUT);

  Serial.begin(BAUDRATE);

  currentTime = millis();
  while (!Serial && ( (millis() - currentTime) < 10000 )) { delay(5); }
  Serial.println("==================================================================");
  Serial.println(VERSION_STRING);
  Serial.println("==================================================================");

  // Initialize PSRAM (optional check)
  if (psramInit()) {
    Serial.println("PSRAM initialized successfully.");
    Serial.printf("Total PSRAM: %d bytes\r\n", ESP.getPsramSize());
    Serial.printf("Free PSRAM: %d bytes\r\n", ESP.getFreePsram());
  } else {
    Serial.println("PSRAM initialization failed. Continuing without PSRAM.");
  }

  if ((TABLESIZE & (TABLESIZE - 1)) != 0) {
    Serial.println("TABLESIZE must be a power of 2");
    while (true) delay(1000);
  }
  if (TABLESIZE < 8 || TABLESIZE > 16384) {
    Serial.println("TABLESIZE out of expected range");
    while (true) delay(1000);
  }

  // ==================================================================
  // Prepare the BLE Device

  // Core BLE init and MTU (GATT layer)
  NimBLEDevice::init(DEVICE_NAME);
  // Register the GAP hook before you connect
  NimBLEDevice::setCustomGapHandler(myGapHandler);
  // MTU
  NimBLEDevice::setMTU(BLE_MTU);

  // TX power
  #if defined(SPEED)
    // Max power for best range and speed;
    NimBLEDevice::setPower(BLE_TX_DBM_P9, PWR_ALL);   // max TX power everywhere
  #elif defined(LOWPOWER)
    // Min power for best battery life; adjust as needed for your environment
    NimBLEDevice::setPower(BLE_TX_DBM_N9, PWR_ADV);   // small ADV range to save power
    NimBLEDevice::setPower(BLE_TX_DBM_N9, PWR_SCAN);  // scanning (if you do it)
    NimBLEDevice::setPower(BLE_TX_DBM_N6, PWR_CONN);  // enough for typical indoor links
  #else
    // balanced, visible enough, not wasteful
    // NimBLEDevice::setPower(BLE_TX_DBM_N3, PWR_ADV);
    // NimBLEDevice::setPower(BLE_TX_DBM_N6, PWR_SCAN);
    // NimBLEDevice::setPower(BLE_TX_DBM_0,  PWR_CONN);
    // long range
    NimBLEDevice::setPower(BLE_TX_DBM_P9, PWR_ALL);
  #endif

  // Optional: fix address type (disable RPA) if you want a stable MAC:
  // BLE_OWN_ADDR_PUBLIC Use the chip’s factory-burned IEEE MAC (the “public” address). Stable, globally unique.
  // BLE_OWN_ADDR_RANDOM Use the static random address you’ve set with ble_hs_id_set_rnd(). Stable across reboots only if you persist it yourself.
  // BLE_OWN_ADDR_RPA_PUBLIC_DEFAULT Use a Resolvable Private Address (RPA) derived from your public identity. This gives privacy (rotating address) but still resolvable if the peer has your IRK (bonded).
  // BLE_OWN_ADDR_RPA_RANDOM_DEFAULT Use an RPA derived from your random static identity.
  #if defined(BLE_SECURE)
    NimBLEDevice::setOwnAddrType(BLE_OWN_ADDR_RPA_PUBLIC_DEFAULT);
    // your client will need to reacquire the address each time you want to connect
  #else
    NimBLEDevice::setOwnAddrType(BLE_OWN_ADDR_PUBLIC);
    // address remains static and can be reused by the client
  #endif

  // Link preferences
  #if defined(SPEED)
    NimBLEDevice::setDefaultPhy(BLE_GAP_LE_PHY_2M_MASK, BLE_GAP_LE_PHY_2M_MASK);
  #else
    NimBLEDevice::setDefaultPhy(BLE_GAP_LE_PHY_ANY_MASK, BLE_GAP_LE_PHY_ANY_MASK);
  #endif
  // Suggest max data length for future connections; use conservative 1M time
  // (we'll retune per-connection once we know the actual PHY)
  ble_gap_write_sugg_def_data_len(LL_MAX_TX_OCTETS, LL_TIME_1M_US);

  // Security posture
  #if defined(BLE_SECURE)
      NimBLEDevice::setSecurityAuth(/*bonding*/true, /*mitm*/true, /*sc*/true);
      NimBLEDevice::setSecurityPasskey(BLE_PASSKEY_VALUE);                              
      // IO capability: display only (ESP_IO_CAP_OUT)
      NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);  /** Display only passkey */
      // Key distribution (init/rsp) ~ ESP_BLE_SM_SET_INIT_KEY / SET_RSP_KEY
      NimBLEDevice::setSecurityInitKey(KEYDIST_ENC | KEYDIST_ID);
      NimBLEDevice::setSecurityRespKey(KEYDIST_ENC | KEYDIST_ID); 
  #else
      NimBLEDevice::setSecurityAuth(/*bonding*/false, /*mitm*/false, /*sc*/false); // no pairing needed
  #endif
  // ==================================================================

  // ==================================================================
  // Create BLE Server
  pServer = NimBLEDevice::createServer();
  pServer->setCallbacks(&serverCallBacks);
  // ==================================================================

  // ==================================================================
  // Create the BLE Service
  NimBLEService *pService = pServer->createService(SERVICE_UUID);
  // ==================================================================

  // ==================================================================
  // TX: create Service Characteristics
  // Sends Notifications (our generated data) to Client
  // adding READ allows client to read last value (e.g open connection), 
  //   although data is provided throug notifications
  pTxCharacteristic = pService->createCharacteristic(
      CHARACTERISTIC_UUID_TX,
      NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::READ // let clients read last value …
      #if defined(BLE_SECURE)
        | NIMBLE_PROPERTY::READ_ENC   // … add this if you want read to require encryption
      #endif
  );
  pTxCharacteristic->setCallbacks(&transmitterCallBacks);
  // ==================================================================

  // ==================================================================
  // RX: create Service Characteristics
  // Receives data from Client
  pRxCharacteristic = pService->createCharacteristic(
      CHARACTERISTIC_UUID_RX,
      NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR        // write without response (faster)
      #if defined(BLE_SECURE)
        | NIMBLE_PROPERTY::WRITE_ENC       // require encryption for writes (triggers pairing)
      #endif
  );
  pRxCharacteristic->setCallbacks(&receiverCallBacks);
  // ==================================================================

  // ==================================================================
  // Start the service
  pService->start();
  // ==================================================================

  // ==================================================================
  // Primary Advertising: Flags and Service UUID
  pAdvertising = NimBLEDevice::getAdvertising();

  #if defined(SPEED)
    pAdvertising->setMinInterval(0x00A0); // 100 ms
    pAdvertising->setMaxInterval(0x00F0); // 150 ms
  #elif defined(LOWPOWER)
    pAdvertising->setMinInterval(0x0640); // 1.0 s
    pAdvertising->setMaxInterval(0x0C80); // 2.0 s
  #else // LONGRANGE
    pAdvertising->setMinInterval(0x0320); // 0.5 s
    pAdvertising->setMaxInterval(0x0640); // 1.0 s
  #endif

  NimBLEAdvertisementData advData;
  // Flags are recommended in primary ADV (general discoverable, no BR/EDR)
  advData.setFlags(BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP);
  // Put service UUID in the primary ADV
  advData.addServiceUUID(SERVICE_UUID);   
  // If you have multiple services, call addServiceUUID(...) for each:
  // advData.addServiceUUID(NimBLEUUID(SERVICE_UUID_2));
  // Apply primary ADV payload (replaces any previous content)
  advData.addTxPower();

 // Scan Response: put the full name here (saves ADV space)
  NimBLEAdvertisementData scanData;
  scanData.setName(DEVICE_NAME);
  scanData.setAppearance(BLE_APPEARANCE);
  const uint8_t mfg[] = { 0xFF, 0xFF, 'S','i','m',':','1','.','0' }; // 0xFFFF + 27 bytes max
  scanData.setManufacturerData(std::string((const char*)mfg, sizeof(mfg)));  

  pAdvertising->setAdvertisementData(advData);
  pAdvertising->setScanResponseData(scanData);
  
  // Start advertising
  NimBLEDevice::startAdvertising();
  // ==================================================================

  // Print MAC last (purely informational)
  deviceMac = NimBLEDevice::getAddress().toString();
  for (char &c : deviceMac) c = (char)toupper((unsigned char)c);
  Serial.printf("MAC: %s\r\n", deviceMac.c_str());

  // Report pacing backend for clarity during perf testing
  Serial.println("TX pacing: TxTask timed loop (µs scheduler)");

  // ==================================================================
  // Create background tasks once; keep them suspended until needed
  // Create background tasks once; keep them suspended until needed
  if (!txTaskHandle) {
    // Move TX to core 0; higher prio than RSSI, but not too high to starve NimBLE
    xTaskCreatePinnedToCore(TxTask,   "TxTask",   4096, nullptr, 4, &txTaskHandle,   1);
    vTaskSuspend(txTaskHandle);
  }
  if (!rssiTaskHandle) {
    // Keep RSSI on core 1 to reduce interference with NimBLE host
    xTaskCreatePinnedToCore(RssiTask, "RssiTask", 3072, nullptr, 2, &rssiTaskHandle, 1);
    vTaskSuspend(rssiTaskHandle);
  }
  
  // ==================================================================
  // Prints current data generation settings
  Serial.println("==================================================================");
  Serial.println("Current Settings:");
  Serial.printf("Interval:   %d µs\r\n", interval);
  Serial.printf("Samplerate: %d Hz\r\n", samplerate);
  Serial.printf("Scenario:   %d\r\n", scenario);
  Serial.printf("Frequency:  %f\r\n", frequency);
  Serial.printf("Paused:     %s\r\n", paused ? "Yes" : "No");

  randomSeed(analogRead(0));
  updateSignalTable(scenario);

  lastDataGenerationTime  = micros();
  lastBLETime = micros();
  lastBlink = micros();
  lastSend = nowMicros();

}

// ===============================================================================================================================================================
// Loop
// ===============================================================================================================================================================

void loop()
{
  currentTime = micros();

  // Handle Commands (BLE RX via rxBuffer)
  // -----------------------------------------------------------------------
  static String rxLine;
  // Drain available bytes and assemble lines separated by \n or \r
  // Guard against pathological long lines by capping at 512 chars
  while (rxBuffer.available() > 0) {
    char c;
    if (rxBuffer.pop(c) == 0) break;
    if (c == '\n' || c == '\r') {
      if (rxLine.length() > 0) {
        rxLine.trim(); // strip leading/trailing spaces, CR, LF, tabs
        if (rxLine.length() > 0) {
          handleBLECommands(rxLine);
        }
        rxLine = "";
      }
    } else {
      if (rxLine.length() < 512) {
        rxLine += c;
      } else {
        // Line too long; reset to avoid unbounded growth
        rxLine = "";
      }
    }
  }

  // Simulate Data
  // -----------------------------------------------------------------------
  if (!paused && clientSubscribed && generationAllowed)
  {
    if (currentTime - lastDataGenerationTime >= interval)
    {
      lastDataGenerationTime = currentTime;
      size_t ret = generateData();
      size_t used = txBuffer.available();
      if (used >= highWaterMark) {
          generationAllowed = false;
      }
      // Was there issue generating data?
      if (ret == 0) {
        int n = snprintf(data, sizeof(data), "Error generating data\r\n");
        #if DEBUG_LEVEL >= ERROR
          Serial.print(data);
        #endif
      }
    }
  }

  // Blink LED
  // -----------------------------------------------------------------------
  if ((currentTime - lastBlink) >= blinkInterval) {
    lastBlink = currentTime;
    if (ledState == LOW) {
      ledState = HIGH;
      blinkInterval = 200000; 
    } else {
      ledState = LOW;
      blinkInterval = 800000;
    }

    // set the LED with the ledState of the variable:
    digitalWrite(ledPin, ledState);
  } // end blink

} // end main

// ===============================================================================================================================================================
// Support Functions
// ===============================================================================================================================================================

// ----------------------------------------------------------
//  User Input
// ----------------------------------------------------------

String toAsciiDecimal(const String& s) {
  String out;
  out.reserve(s.length() * 4); // rough
  for (size_t i = 0; i < s.length(); ++i) {
    if (i) out += ' ';
    out += String((uint8_t)s[i]);  // decimal
  }
  return out;
}

void handleBLECommands(const String& cmd)
{

  int n;
  #if DEBUG_LEVEL >= DEBUG
    Serial.printf("Command: %s, [%s]\r\n", cmd.c_str(), toAsciiDecimal(cmd).c_str());
  #endif

  if (cmd.startsWith("interval "))
  {
    int newInterval = cmd.substring(9).toInt();
    if (newInterval > 0)
    {
      interval = newInterval;
      userSetInterval = true;
      sanitizeTiming();
      updateSignalTable(scenario);
      txBuffer.clear();
      n = snprintf(data, sizeof(data), "Interval set to %d micro seconds\r\n", interval);
    }
    else
    {
      n = snprintf(data, sizeof(data), "Invalid interval value. Needs to be >0\r\n");
    }
    size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
    txBuffer.push(data, len, false);
    #if DEBUG_LEVEL >= DEBUG
      Serial.print(data);
    #endif
  }

  else if (cmd.startsWith("samplerate "))
  {
    int newSamplerate = cmd.substring(11).toInt();
    if (newSamplerate > 0)
    {
      samplerate = newSamplerate;
      sanitizeTiming();
      n = snprintf(data, sizeof(data), "Samplerate set to %d Hz\r\n", samplerate);
    }
    else
    {
      n = snprintf(data, sizeof(data), "Invalid samplerate value\r\n");
    }
    size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
    txBuffer.push(data, len, false);
    #if DEBUG_LEVEL >= DEBUG
      Serial.print(data);
    #endif
  }

  else if (cmd.startsWith("scenario "))
  {
    int newScenario = cmd.substring(9).toInt();
    if (newScenario >= 1 && newScenario <= 100)
    {
      scenario = newScenario;
      fastMode = (scenario == 11 || scenario == 20);
      if (fastMode && !userSetInterval) {
        interval = SPEEDTEST_DEFAULT_INTERVAL_US;
        n = snprintf(data, sizeof(data), "Interval auto-set for fast mode: %d µs\r\n", interval);
        size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
        txBuffer.push(data, len, false);
        #if DEBUG_LEVEL >= DEBUG
          Serial.print(data);
        #endif
      }
      // If we leave fast mode and interval was 0, give it a sane default before sanitize
      if (!fastMode && interval == 0 && !userSetInterval) {
        interval = 10000UL; // 10 ms default
      }      
      sanitizeTiming();
      updateSignalTable(scenario);
      // Start fresh after scenario switch so we don’t trip “buffer full” or stale frames
      txBuffer.clear();
      generationAllowed   = true;
      pendingLen  = 0;
      successStreak = 0;      
      n = snprintf(data, sizeof(data), "Scenario set to %d\r\n", scenario);
    }
    else
    {
      n = snprintf(data, sizeof(data), "Invalid scenario value\r\n");
    }
    if (n > 0) {
      size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
      txBuffer.push(data, len, false);
      #if DEBUG_LEVEL >= DEBUG
        Serial.print(data);
      #endif
    }
  }

  else if (cmd.startsWith("frequency "))
  {
    float newFreq = cmd.substring(10).toFloat();
    if (newFreq >= 0 && newFreq <= 10000)
    {
      frequency = newFreq;
      sanitizeTiming();
      updateSignalTable(scenario);
      txBuffer.clear();
      n = snprintf(data, sizeof(data), "Frequency set to %.2f Hz\r\n", frequency);
    }
    else
    {
      n = snprintf(data, sizeof(data), "Invalid frequency value\r\n");
    }
    if (n > 0) {
      size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
      txBuffer.push(data, len, false);
      #if DEBUG_LEVEL >= DEBUG
        Serial.print(data);
      #endif
    }
  }

  else if (cmd.startsWith("pause"))
  {
    paused = true;
    n = snprintf(data, sizeof(data), "Data generation paused\r\n");
    if (n > 0) {
        size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
        txBuffer.push(data, len, false);
    }
    #if DEBUG_LEVEL >= DEBUG
      Serial.print(data);
    #endif
  }

  else if (cmd.startsWith("resume"))
  {
    paused = false;
    txBuffer.clear();
    generationAllowed = true;
    n = snprintf(data, sizeof(data), "Data generation resumed\r\n");
    if (n > 0) {
        size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
        txBuffer.push(data, len, false);
    }
    #if DEBUG_LEVEL >= DEBUG
      Serial.print(data);
    #endif
  }

  else if (cmd.startsWith("?"))
  {
      // Prints current settings
    n = snprintf(data, sizeof(data),
        "==================================================================\r\n"
        "Current Settings:\r\n"
        "Paused:     %s\r\n"
        "Scenario:   %d\r\n"
        "Interval:   %lu µs\r\n"
        "Samplerate: %d Hz\r\n"
        "Frequency:  %.2f Hz\r\n",
        paused ? "Yes" : "No",
        scenario,
        (unsigned long)interval,
        samplerate,
        (double)frequency
    );
    size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
    txBuffer.push(data, len, false);
    #if DEBUG_LEVEL >= DEBUG
      Serial.print(data);
    #endif
  }

  else if (cmd.startsWith("."))
  {
    // Prints current ble status
    n = snprintf(data, sizeof(data),
        "==================================================================\r\n"
        "BLE Settings for %s (%s):\r\n"
        "Device is: %s\r\n"
        "RSSI: %d (filtered: %d)\r\n"
        "RSSI thresholds: PHY is coded below %d, fast above %d\r\n"
        "MTU: %d (max is 517)\r\n"
        "Chunk Size: %d (max is 2 * LL tx octets)\r\n"
        "PHY is: %s (2M is fastest)\r\n"
        "LL tx octets: %d (27..251)\r\n"
        "LL tx time:  %d µs (min is 1060)\r\n"
        "LL rx octets: %d\r\n"
        "LL rx time:  %d\r\n"
        "LL time used for tx: %d µs\r\n"
        "Data TX Interval: %lu µs\r\n"
        "Data TX Interval MIN: %lu\r\n"
        "Data TX Interval MAX: %lu\r\n"
        "Pending bytes: %d (attempted to send)\r\n"
        "Tx was %s\r\n"
        "Success streak for %d transmissions\r\n"
        "MTU read retry count: %d\r\n"
        "Permission to generate data is %s\r\n"
        "Buffered used: %d bytes\r\n"
        "Buffer low watermark: %d - high watermark: %d size: %d bytes\r\n"
        "==================================================================\r\n",
        DEVICE_NAME, deviceMac.c_str(),
        deviceConnected ? "connected" : "not connected",
        rssi, f_rssi,
        RSSI_S2_THRESHOLD, RSSI_FAST_THRESHOLD,
        mtu,
        txChunkSize,
        phyIsCODED ? ((codedScheme == 8) ? "Coded S8" : "Coded S2") : (phyIs2M ? "2M" : "1M"),
        g_ll_tx_octets,
        g_ll_tx_time_us,
        g_ll_rx_octets,
        g_ll_rx_time_us,
        llTimeUS,
        sendInterval,
        minSendIntervalUs,
        maxSendIntervalUs,
        pendingLen,
        txOkFlag ? "ok" : "not yet successful",
        successStreak,
        mtuRetryCount,
        generationAllowed ? "on" : "off",
        txBuffer.available(), 
        lowWaterMark,
        highWaterMark,
        txBuffer.capacity()
    );
    size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
    txBuffer.push(data, len, false);
    #if DEBUG_LEVEL >= DEBUG
      Serial.print(data);
    #endif
  }

  else
  {
    static const char HELP_TEXT[] =
    "==================================================================\r\n"
    "Commands are:\r\n"
    "? - this help\r\n"
    ". - current status\r\n"
    "pause\r\n"
    "resume\r\n"
    "interval <micro seconds> > 0\r\n"
    "samplerate <Hz>\r\n"
    "frequency <Hz>\r\n"
    "scenario <number>:\r\n"
    "   1 Agriculture,    2 CanSat (Satellite),   3 Environmental,\r\n"
    "   4 Medical,        5 Power,                6 Stereo Sinewave,\r\n"
    "   7 Mono Sinewave,  8 Mono Sinewave Header, 9 Mono Sawtooth,\r\n"
    "  10 Squarewave,    11 64 Chars,            20 BLE Speed Tester (34)\r\n";
    txBuffer.push(HELP_TEXT, strlen(HELP_TEXT), false);
    #if DEBUG_LEVEL >= DEBUG
      Serial.print(HELP_TEXT);
    #endif
  }
}

//----------------------------------------------------------
// Data Generation Selector
// ----------------------------------------------------------

size_t generateData()
{
  switch (scenario)
  {
    case 1:
      return(generateAgriculturalMonitoringData());
      break;
    case 2:
      return(generateCanSatData());
      break;
    case 3:
      return(generateEnvironmentalData());
      break;
    case 4:
      return(generateMedicalMonitoringData());
      break;
    case 5:
      return(generatePowerSystemData());
      break;
    case 6:
      return(generateStereo(samplerate, interval));
      break;
    case 7:
      return(generateMono(samplerate, interval));
      break;
    case 8:
      return(generateMonoHeader(samplerate, interval, String("Sine")));
      break;
    case 9:
      return(generateMono(samplerate, interval));
      break;
    case 10:
      return(generateMono(samplerate, interval));
      break;
    case 11:
      return(generate64Chars());
      break;
    case 20:
      return(generateStoffregen());
      break;
    default:
    {
      int n = snprintf(data, sizeof(data), "Error: Invalid scenario %d\r\n", scenario);
      size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
      txBuffer.push(data, len, false);
      #if DEBUG_LEVEL >= DEBUG
        Serial.print(data);
      #endif
      return 0;
    }
  }
}

void updateSignalTable(int scenario){
  switch (scenario)
  {
    case 6:
      updateSineWaveTable();
      break;
    case 7:
      updateSineWaveTable();
      break;
    case 8:
      updateSineWaveTable();
      break;
    case 9:
      updateSawToothTable();
      break;
    case 10:
      updateSquareWaveTable();
      break;
    default:
      break;
  }
}

void updateSineWaveTable() {
  int n = snprintf(data, sizeof(data), "Updating sine table...\r\n");
  size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
  txBuffer.push(data, len, false);

  for (int i = 0; i < TABLESIZE; i++) {
    int16_t value1 = int16_t(amplitude * sin(( 2.0 * M_PI * float(i)) / float(TABLESIZE))); 
    // int16_t value2 = int16_t((amplitude / 4) * sin((10.0 * M_PI * i) / float(TABLESIZE))); // Adjusted frequency
    // signalTable[i] = value1 + value2;
    signalTable[i] = value1;
  }
  int16_t mn = INT16_MAX, mx = INT16_MIN;
  for (size_t i = 0; i < TABLESIZE; ++i) { 
    mn = min(mn, signalTable[i]); 
    mx = max(mx, signalTable[i]);
  }
  n = snprintf(data, sizeof(data), "Sine table min: %d, max: %d\r\n", mn, mx);
  len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
  txBuffer.push(data, len, false);
}

void updateSawToothTable() {
  int n = snprintf(data, sizeof(data), "Updating sawtooth table...\r\n");
  size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
  txBuffer.push(data, len, false);

  for (int i = 0; i < TABLESIZE; i++) {
    int16_t value = int16_t(-amplitude + 2.* amplitude * (float(i) / float(TABLESIZE)));
    signalTable[i] = value;
  }
}

void updateSquareWaveTable() {
  int n = snprintf(data, sizeof(data), "Updating square table...\r\n");
  size_t len = (n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
  txBuffer.push(data, len, false);

  for (int i = 0; i < TABLESIZE; i++) {
    int16_t value;
    if (i < TABLESIZE / 2) {  // Corrected missing parentheses
      value = int16_t(amplitude);
    } else {
      value = int16_t(-amplitude);
    }
    signalTable[i] = value;
  }
}

// ===============================================================================================================================================================
// Data Generators
// ===============================================================================================================================================================

// ----------------------------------------------------------
//  Data Generation from Table with Header
// ----------------------------------------------------------
// Estimate avg characters per sample for buffer sizing
static int avgCharsPerSample(int s) {
  switch (s) {
    case 1:  return 184; // Agriculture: "Temp: 23.45 C, Hum: 56.78 %, Soil: 12.34 %\r\n"
    case 2:  return 718; // CanSat: "T:23.45C,P:1013.25hPa,H:56.78%,A:123.
    case 3:  return 159; // Environmental: "Temp: 23.45 C, Hum: 56.78 %, CO2: 400 ppm\r\n"
    case 4:  return 138; // Medical: "HR: 72 bpm, SpO2: 98 %, BP: 120/80 mmHg, Temp: 36.5 C\r\n"
    case 5:  return 129; // Power: "Volt: 12.34 V, Curr: 1.23 A, Power: 15.00 W\r\n"
    case 6:  return  16; // Stereo: "-1024, -1024\r\n" ~ 14 → use 16
    case 7:  return   8; // Mono: "-1024\r\n" ~ 6–7 → use 16
    case 8:  return  14; // Header + value: "Sine: -1024\r\n" ~ 12–14 → use 14
    case 9:  return   8; // Mono: "-1024\r\n" ~ 6–7 → use 8
    case 10: return   8; // Mono: "-1024\r\n" ~ 6–7 → use 8
    case 11: return  64; // 64 chars + newline
    case 20: return  36; // Speed test: count=%9lu, lines/sec=%6lu\r\n
    default: return  64; // Other CSV scenarios build one line per call; keep generous
  }
}

// Compute max samples per frame that fit the per-call text buffer
static int maxSamplesForBuffer(int scen) {
  const int overhead = 32; // guard for final null and minor variation
  int avg = avgCharsPerSample(scen);
  if (avg < 1) avg = 8;
  return max(1, (int)((sizeof(data) - overhead) / avg));
}

// Clamp samplerate/interval and, if needed, shrink interval to keep samples per frame in bounds
// Clamp samplerate/interval and, if needed, shrink interval to keep samples per frame in bounds
static void sanitizeTiming() {

  // Clamp samplerate and interval
  samplerate = constrain(samplerate, MIN_SAMPLERATE_HZ, MAX_SAMPLERATE_HZ);
  
  // Fast modes (11, 20): do NOT clamp interval; allow 0
  if (scenario == 11 || scenario == 20) {
    return;
  }
  // Other scenarios: clamp interval into sane bounds
  interval   = constrain(interval, MIN_INTERVAL_US, MAX_INTERVAL_US);

  // Waveform scenarios (6..10) use samplerate and interval
  if (scenario >= 6 && scenario <= 10) {
    // Ensure we have at least 1 sample per frame
    const unsigned long minIntervalForOneSample =
      (unsigned long)((1000000ULL + (uint64_t)samplerate - 1ULL) / (uint64_t)samplerate); // ceil(1e6/samplerate)
    if (interval < minIntervalForOneSample) {
    interval = minIntervalForOneSample;
    }

    const uint64_t ticks   = (uint64_t)samplerate * (uint64_t)interval;
    int requestedSamples   = (int)(ticks / 1000000ULL);
    int maxSamplesAllowed  = maxSamplesForBuffer(scenario);

    if (requestedSamples > maxSamplesAllowed) {
      // Reduce interval to fit in buffer while keeping samplerate
      // interval_us = samples * 1e6 / samplerate
      unsigned long newInterval = (unsigned long)((uint64_t)maxSamplesAllowed * 1000000ULL / (uint64_t)samplerate);
      newInterval = constrain(newInterval, MIN_INTERVAL_US, MAX_INTERVAL_US);
      if (newInterval != interval) {
        interval = newInterval;
        #if DEBUG_LEVEL >= INFO
          Serial.printf("Note: interval reduced to fit buffer: %lu µs\r\n", interval);
        #endif
      }
    }
  } 

    // Other scenarios (1..5, 11, 20) generate one line per call; no need to adjust interval

}

// ----------------------------------------------------------
//  Data Generation from Table with Header
// ----------------------------------------------------------

size_t generateMonoHeader(int samplerate, unsigned long interval, String header) {
    char* ptr = data;

    const uint64_t ticks = (uint64_t)samplerate * (uint64_t)interval; // microsecond ticks
    int samples = (int)(ticks / 1000000ULL);
    if (samples <= 0) samples =1;

    // Fixed‑point phase increment (TABLESIZE << FRAC scaled by freq / samplerate)
   const uint32_t inc = phase_inc_from_hz(frequency, samplerate);

    const char* h = header.c_str();
    uint32_t p = phase;

    for (int i = 0; i < samples; ++i) {
        size_t rem = sizeof(data) - (size_t)(ptr - data);
        if (rem <= 1) break;
        
        int idx = table_index(p);
        int wrote = snprintf(ptr, rem, "%s: %d\r\n", h, (int)signalTable[idx]);
        if (wrote <= 0 || wrote >= (int)rem) break;
        ptr += wrote;

        p = advance_phase(p, inc);
    }

    phase = p;

    const size_t len = (size_t)(ptr - data);
    return txBuffer.push(data, len, false);
}

// ----------------------------------------------------------
// Data Generator from Table
// ----------------------------------------------------------

size_t generateMono(int samplerate, unsigned long interval) {
    char* ptr = data;
    const uint64_t ticks = (uint64_t)samplerate * (uint64_t)interval;
    int samples = (int)(ticks / 1000000ULL);
    if (samples <= 0) samples = 1;

    // phase increment: TABLESIZE steps per cycle
    const uint32_t inc = phase_inc_from_hz(frequency, samplerate);


    uint32_t p = phase;
    
    for (int i = 0; i < samples; ++i) {
        size_t rem = sizeof(data) - (size_t)(ptr - data);
        if (rem <= 1) break;

        int idx = table_index(p);
        int wrote = snprintf(ptr, rem, "%d\r\n", signalTable[idx]);
        if (wrote <= 0 || wrote >= (int)rem) break;
        ptr += wrote;

        p = advance_phase(p, inc);
    }

    phase = p;

    const size_t len = (size_t)(ptr - data);
    return txBuffer.push(data, len, false);
}

//----------------------------------------------------------
// Data Generation from Table: Stereo
//----------------------------------------------------------

size_t generateStereo(int samplerate, unsigned long interval) {
    char* ptr = data;
    const uint64_t ticks = (uint64_t)samplerate * (uint64_t)interval;
    int samples = (int)(ticks / 1000000ULL);
    if (samples <= 0) samples = 1;

    const uint32_t inc = phase_inc_from_hz(frequency, samplerate);
    const uint32_t inc_offset = phase_inc_from_hz(stereo_drift_hz,  samplerate);
    
    // Local working copies keep constant relative offset
    uint32_t p = phase;
    uint32_t off = stereo_offset_fp;

    for (int i = 0; i < samples; ++i) {
        size_t rem = sizeof(data) - (size_t)(ptr - data);
        if (rem <= 1) break;

        int idx1 = table_index(p);
        int idx2 = table_index(p + off);
        
        int wrote = snprintf(ptr, rem, "%d, %d\r\n", signalTable[idx1], signalTable[idx2]);
        if (wrote <= 0 || wrote >= (int)rem) break;
        ptr += wrote;

        p = advance_phase(p, inc);
        off = advance_phase(off, inc_offset);
    }

    phase = p;
    stereo_offset_fp = off;

    const size_t len = (size_t)(ptr - data);
    return txBuffer.push(data, len, false);
}

// ----------------------------------------------------------
// Data Generator: 64 Characters
// ----------------------------------------------------------

inline constexpr char FIXED_64_CHAR[65] =  "ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZ.012345678\r\n"; 

size_t generate64Chars() {
    return txBuffer.push(FIXED_64_CHAR, 64, false);  // Push 64 bytes to ring buffer
}

// ----------------------------------------------------------
//  Data Generator for BLE test, includes line counter and lines per second
// ----------------------------------------------------------

size_t generateStoffregen() {

  // 34 characters
  size_t n = snprintf(data, sizeof(data), "count=%9lu, lines/sec=%6lu\r\n", currentCounts, countsPerSecond);

  currentCounts++;

  // update every second
  if (currentTime - lastBLETime > 1000000) {
    countsPerSecond = currentCounts - lastCounts;
    lastCounts = currentCounts;
    lastBLETime = currentTime;
  }

  return txBuffer.push(data, n, false);
}

// ----------------------------------------------------------
// Data Generator for Agriculture Data
// ----------------------------------------------------------

size_t  generateAgriculturalMonitoringData()
{

  float soilMoisture    = random(200, 800) / 10.0;       // Soil moisture in percentage
  float soilTemperature = random(100, 350) / 10.0;       // Soil temperature in Celsius
  float airTemperature  = random(150, 350) / 10.0;       // Air temperature in Celsius
  float airHumidity     = random(300, 900) / 10.0;       // Air humidity in percentage
  float lightIntensity  = random(2000,10000) / 100.0;    // Light intensity in lux/100 (overcast)
  float pHLevel         = random(50, 80) / 10.0;         // Soil pH level
  int leafWetness       = random(0, 15);                 // Leaf wetness
  float co2Level        = random(300, 800) / 10.0;       // CO2 level in ppm/10
  float windSpeed       = random(0, 200) / 10.0;         // Wind speed in m/s
  float arssi           = random(-90, -30);              // RSSI value

  int n = snprintf(data, sizeof(data), 
         "SoilMoisture: %.1f, SoilTemperature: %.1f, AirTemperature: %.1f, AirHumidity: %.1f, LightIntensity: %.1f, PHLevel: %.2f, LeafWetness: %d, CO2Level: %.1f, WindSpeed: %.1f, RSSI: %.1f\r\n",
          soilMoisture, soilTemperature, airTemperature,
          airHumidity, lightIntensity, pHLevel, leafWetness,
          co2Level, windSpeed, arssi);

  size_t len = (n > 0 && n < (int)sizeof(data)) ? (size_t)n : (sizeof(data) - 1);
  return(txBuffer.push(data, len, false));

}

// ----------------------------------------------------------
//  Data Generator for Power Monitoring System
// ----------------------------------------------------------

size_t generatePowerSystemData()
{
  float voltageSensor = random(300, 500) / 10.0;                // Voltage sensor
  float currentSensor = random(100, 200) / 10.0;                // Current sensor
  float powerSensor = voltageSensor * currentSensor;            // Power sensor
  float energySensor = powerSensor * random(10, 1000) / 1000.0; // Energy sensor
  float batteryLevel = random(0, 100);                          // Battery level percentage
  float temperatureBattery = random(200, 450) / 10.0;           // Battery temperature
  float prssi = random(-90, -30);                               // RSSI value

  int n = snprintf(data, sizeof(data),
    "VoltageSensor:%.1f,CurrentSensor:%.1f,"
    "PowerSensor:%.1f,EnergySensor:%.1f,BatteryLevel:%.1f,"
    "TemperatureBattery:%.1f,RSSI:%.1f\r\n",
    voltageSensor, currentSensor,
    powerSensor, energySensor, batteryLevel,
    temperatureBattery, prssi);


  size_t length = (n > 0 && n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
  return txBuffer.push(data, length, false);
}

// ----------------------------------------------------------
// Data Generator for Medical Monitoring System
// ----------------------------------------------------------

size_t generateMedicalMonitoringData()
{
  float bodyTemp = random(360, 380) / 10.0;          // Body temperature in Celsius
  int heartRate = random(60, 100);                   // Heart rate in BPM
  int bloodPressureSystolic = random(90, 140);       // Systolic blood pressure
  int bloodPressureDiastolic = random(60, 90);       // Diastolic blood pressure
  float bloodOxygenLevel = random(950, 1000) / 10.0; // Blood oxygen level in percentage
  float respirationRate = random(12, 20);            // Respiration rate in breaths per minute
  float glucoseLevel = random(70, 140);              // Glucose level in mg/dL
  int stepCount = random(0, 10000);                  // Step count
  float mrssi = random(-90, -30);                    // RSSI value

  int n = snprintf(data, sizeof(data),
    "BodyTemp:%.1f,HeartRate:%d,"
    "BloodPressure:%d/%d,BloodOxygenLevel:%.1f,"
    "RespirationRate:%.1f,GlucoseLevel:%.1f,StepCount:%d,"
    "RSSI:%.1f\r\n",
    bodyTemp, heartRate,
    bloodPressureSystolic, bloodPressureDiastolic, bloodOxygenLevel,
    respirationRate, glucoseLevel, stepCount,
    mrssi);

  size_t length = min(strlen(data), sizeof(data));
  return(txBuffer.push(data, length, false));
}

// ----------------------------------------------------------
//  Data Generator for Environmental Monitoring System
// ----------------------------------------------------------

size_t generateEnvironmentalData()
{
  float tempSensor1 = random(200, 300) / 10.0;       // Temperature sensor 1
  float tempSensor2 = random(150, 250) / 10.0;       // Temperature sensor 2
  float humiditySensor = random(300, 800) / 10.0;    // Humidity sensor
  float pressureSensor = random(9000, 10500) / 10.0; // Pressure sensor
  float lightSensor = random(200, 1000);             // Light intensity sensor
  int co2Sensor = random(300, 600);                  // CO2 sensor
  float airQualityIndex = random(50, 150);           // Air quality index
  float noiseLevel = random(30, 100);                // Noise level in dB
  float erssi = random(-90, -30);                    // RSSI value

  int n = snprintf(data, sizeof(data),
    "TempSensor1:%.1f,TempSensor2:%.1f,"
    "HumiditySensor:%.1f,PressureSensor:%.1f,LightSensor:%.1f,"
    "CO2Sensor:%d,AirQualityIndex:%.1f,NoiseLevel:%.1f,"
    "RSSI:%.1f\r\n",
    tempSensor1, tempSensor2,
    humiditySensor, pressureSensor, lightSensor,
    co2Sensor, airQualityIndex, noiseLevel,
    erssi);

  size_t length = min(strlen(data), sizeof(data));
  return(txBuffer.push(data, length, false));
}

// ----------------------------------------------------------
//  Data Generator for CanSat
// ----------------------------------------------------------

size_t generateCanSatData()
{
  uint32_t lightIntensity = random(1000, 5000);
  float uvIndex = random(10, 25) / 10.0;
  float temperatureCanSat = random(239, 256) / 10.0;
  float temperatureExternal = random(239, 256) / 10.0;
  float temperatureMPU = random(239, 256) / 10.0;
  float ambientTemp = random(239, 256) / 10.0;
  float objectTemp = random(239, 256) / 10.0;
  float temperatureSCD30 = random(239, 256) / 10.0;
  float humidityCanSat = random(1, 1000) / 10.0;
  float humidityExternal = random(1, 1000) / 10.0;
  float humiditySCD30 = random(1, 1000) / 10.0;
  float pressureCanSat = random(9959, 10105) / 10.0;
  float pressureExternal = random(9959, 10105) / 10.0;
  float altitudeCanSat = random(2390, 10000) / 10.0;
  float altitudeExternal = random(2390, 10000) / 10.0;
  uint8_t numberOfSatellites = random(0, 6);
  uint16_t latInt = 5002;
  uint16_t lonInt = 1546;
  uint32_t latAfterDot = 2308;
  uint32_t lonAfterDot = 79412;
  int co2SCD30 = 100;
  int co2CCS811 = 200;
  int tvoc = 20;
  float o2Concentration = random(100, 1000) / 10.0;
  int crssi = random(0, 60) - 90;
  float accelerationX = random(10, 150) / 10.0;
  float accelerationY = random(10, 150) / 10.0;
  float accelerationZ = random(10, 150) / 10.0;
  float rotationX = random(10, 150) / 10.0;
  float rotationY = random(10, 150) / 10.0;
  float rotationZ = random(10, 150) / 10.0;
  float magnetometerX = random(10, 150) / 10.0;
  float magnetometerY = random(10, 150) / 10.0;
  float magnetometerZ = random(10, 150) / 10.0;
  float a = random(10, 500) / 10.0;
  float b = random(10, 500) / 10.0;
  float c = random(10, 500) / 10.0;
  float d = random(10, 500) / 10.0;
  float e = random(10, 500) / 10.0;
  float f = random(10, 500) / 10.0;
  float g = random(10, 500) / 10.0;
  float h = random(10, 500) / 10.0;
  float i = random(10, 500) / 10.0;
  float j = random(10, 500) / 10.0;
  float k = random(10, 500) / 10.0;
  float l = random(10, 500) / 10.0;
  float r = random(10, 500) / 10.0;
  float s = random(10, 500) / 10.0;
  float t = random(10, 500) / 10.0;
  float u = random(10, 500) / 10.0;
  float v = random(10, 500) / 10.0;
  float w = random(10, 500) / 10.0;

  int n = snprintf(data, sizeof(data),
    "LightIntensity:%lu,UVIndex:%.1f,"
    "TemperatureCanSat:%.1f,TemperatureMPU:%.1f,TemperatureExternal:%.1f,TemperatureSCD30:%.1f,AmbientTemp:%.1f,ObjectTemp:%.1f,"
    "HumidityCanSat:%.1f,HumidityExternal:%.1f,HumiditySCD30:%.1f,PressureCanSat:%.1f,"
    "PressureExternal:%.1f,AltitudeCanSat:%.1f,AltitudeExternal:%.1f,"
    "AccelerationX:%.1f,AccelerationY:%.1f,AccelerationZ:%.1f,"
    "RotationX:%.1f,RotationY:%.1f,RotationZ:%.1f,MagnetometerX:%.1f,"
    "MagnetometerY:%.1f,MagnetometerZ:%.1f,LatInt:%u,LonInt:%u,"
    "LatAfterDot:%lu,LonAfterDot:%lu,CO2SCD30:%d,CO2CCS811:%d,"
    "TVOC:%d,O2Concentration:%.1f,A:%.1f,B:%.1f,C:%.1f,D:%.1f,"
    "E:%.1f,F:%.1f,G:%.1f,H:%.1f,I:%.1f,J:%.1f,K:%.1f,L:%.1f,"
    "R:%.1f,S:%.1f,T:%.1f,U:%.1f,V:%.1f,W:%.1f,"
    "NumberOfSatellites:%u,RSSI:%d\r\n",
    lightIntensity, uvIndex,
    temperatureCanSat, temperatureMPU, temperatureExternal, temperatureSCD30, ambientTemp, objectTemp,
    humidityCanSat, humidityExternal, humiditySCD30, pressureCanSat,
    pressureExternal, altitudeCanSat, altitudeExternal,
    accelerationX, accelerationY, accelerationZ,
    rotationX, rotationY, rotationZ, magnetometerX,
    magnetometerY, magnetometerZ, latInt, lonInt,
    latAfterDot, lonAfterDot, co2SCD30, co2CCS811,
    tvoc, o2Concentration, a, b, c, d,
    e, f, g, h, i, j, k, l,
    r, s, t, u, v, w,
    numberOfSatellites, crssi);

  size_t length = min(strlen(data), sizeof(data));
  return(txBuffer.push(data, length, false));

}


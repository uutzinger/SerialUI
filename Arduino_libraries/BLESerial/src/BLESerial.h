/******************************************************************************************************/
// Include file for BLESerial library
//
// Urs Utzinger, November 2025
/******************************************************************************************************/

#ifndef BLE_SERIAL_H
#define BLE_SERIAL_H

// Standard Libraries
#include <stdint.h>
#include <inttypes.h>  // for PRIu32 in printf
#include <cmath>

#include <Arduino.h>
#include "RingBuffer.h"

// for ble_gap_set_prefered_le_phy
#include <NimBLEDevice.h>
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

/******************************************************************************************************/
/* Definitions */
/******************************************************************************************************/
#define BLE_SERIAL_VERSION_STRING "BLE Serial Library v1.0.0"
#define BLE_SERIAL_APPEARANCE 0x0540 // Generic Sensor

// DEBUG verbose output on serial port for debugging
// INFO output on Serial about system changes
// WARNING output on Serial about issues
// ERROR output on Serial about errors
// For any issues select DEBUG
// In the code we compare logLevel against these:

#define NONE    0
#define WANTED  1
#define ERROR   1 
#define WARNING 2
#define INFO    3
#define DEBUG   4

// Max GATT MTU supported (ESP32 max 517); ATT payload per notify is MTU-3
#define BLE_SERIAL_MAX_MTU        517
#define BLE_SERIAL_DEFAULT_MTU    247
#define BLE_SERIAL_MIN_MTU         23
#define BLE_SERIAL_ATT_HDR_BYTES    3
#define BLE_SERIAL_L2CAP_HDR_BYTES  4
#define BLE_SERIAL_MAX_FRAME_SIZE (BLE_SERIAL_MAX_MTU - BLE_SERIAL_ATT_HDR_BYTES)

// dBm levels similar to Bluedroid's ESP_PWR_LVL_* names:
#define BLE_TX_DBN12  ( -12)
#define BLE_TX_DBN9     (-9)
#define BLE_TX_DBN6     (-6)
#define BLE_TX_DBN3     (-3)
#define BLE_TX_DB0       (0)
#define BLE_TX_DBP3      (3)
#define BLE_TX_DBP6      (6)
#define BLE_TX_DBP9      (9)   // ~max on many ESP32s

// Scopes roughly matching ESP_BLE_PWR_TYPE_*
#define PWR_ALL  NimBLETxPowerType::All
#define PWR_ADV  NimBLETxPowerType::Advertising
#define PWR_SCAN NimBLETxPowerType::Scan
#define PWR_CONN NimBLETxPowerType::Connections

// Nordic UART (NUS) UUIDs
static constexpr const char     BLE_SERIAL_SERVICE_UUID[]           = {"6E400001-B5A3-F393-E0A9-E50E24DCCA9E"};
static constexpr const char     BLE_SERIAL_CHARACTERISTIC_UUID_RX[] = {"6E400002-B5A3-F393-E0A9-E50E24DCCA9E"};
static constexpr const char     BLE_SERIAL_CHARACTERISTIC_UUID_TX[] = {"6E400003-B5A3-F393-E0A9-E50E24DCCA9E"};

// ===== GATT / ATT payload sizing =====
inline constexpr int8_t         RSSI_LOW_THRESHOLD              =  -80;   // low power threshold (increase power if in LOWPOWER mode)
inline constexpr int8_t         RSSI_FAST_THRESHOLD             =  -65;   // Switch back to 2M/1M
inline constexpr int8_t         RSSI_HYSTERESIS                 =    4;   // Prevent oscillation
inline constexpr int8_t         RSSI_S8_THRESHOLD               =  -82;   // go S=8 below this
inline constexpr int8_t         RSSI_S2_THRESHOLD               =  -75;   // go S=2 below this
inline constexpr uint32_t       RSSI_INTERVAL_MS                = 500UL; // 0.5s
inline constexpr uint32_t       RSSI_ACTION_COOLDOWN_MS         = 4000UL;   // 4s

// ===== LL (Link-Layer) performance knobs =====
// If MTU is larger than LL size the GATT packets need to be fragmented on the link layer
// default LL size is 27
// maximum is 251
// Common BLE 4.2/5.0 DLE targets is 244
inline constexpr uint16_t       LL_MIN_OCTETS                   =    27;    // 27..251
inline constexpr uint16_t       LL_CONS_OCTETS                  =   244;    // 27..251
inline constexpr uint16_t       LL_MAX_OCTETS                   =   251;    // 27..251
inline constexpr uint16_t       LL_TIME_LOW_POWER               =   328;    // for low power
inline constexpr uint16_t       LL_TIME_1US                     =  2120;    // for 1M PHY
inline constexpr uint16_t       LL_TIME_2US                     =  1060;    // for 2M PHY
inline constexpr uint16_t       LL_TIME_CODED_S2_US             =  4240;    // for Coded PHY (S2)
inline constexpr uint16_t       LL_TIME_CODED_S8_US             = 16960;    // for Coded PHY (S8)

// (UUIDs defined above as BLE_SERIAL_* constants)

// BLE optimizations
static constexpr uint16_t itvl_us(uint32_t us)    
    { return (uint16_t)((us * 4) / 5000); } // is in units of 1.25ms
static constexpr uint16_t tout_ms(uint32_t ms)
    { return (uint16_t)(ms / 10); }         // is in units of 10ms

// aggressive speed
inline constexpr const uint16_t MIN_BLE_INTERVAL_SPEED          = itvl_us( 7500);  // Minimum connection interval in microseconds 7.5ms to 4s
inline constexpr const uint16_t MAX_BLE_INTERVAL_SPEED          = itvl_us(10000);  // Maximum connection interval in µs 7.5ms to 4s
inline constexpr const uint16_t BLE_SLAVE_LATENCY_SPEED         = 0;               // Slave latency: number of connection events that can be skipped
inline constexpr const uint16_t BLE_SUPERVISION_TIMEOUT_SPEED   = tout_ms(4000);   // Supervision timeout in milli seconds 100ms to 32s, needs to be larger than 2 * (latency + 1) * (max_interval_ms)
// low power
inline constexpr const uint16_t MIN_BLE_INTERVAL_LOWPWR         = itvl_us(60000);  // 60ms
inline constexpr const uint16_t MAX_BLE_INTERVAL_LOWPWR         = itvl_us(120000); // 120ms
inline constexpr const uint16_t BLE_SLAVE_LATENCY_LOWPWR        = 8;               // can raise
inline constexpr const uint16_t BLE_SUPERVISION_TIMEOUT_LOWPWR  = tout_ms( 6000);  // 6s
// long range
inline constexpr const uint16_t MIN_BLE_INTERVAL_LONG_RANGE     = itvl_us(30000);  // 30ms
inline constexpr const uint16_t MAX_BLE_INTERVAL_LONG_RANGE     = itvl_us(60000);  // 60ms
inline constexpr const uint16_t BLE_SLAVE_LATENCY_LONG_RANGE    = 2;               // some dozing
inline constexpr const uint16_t BLE_SUPERVISION_TIMEOUT_LONG_RANGE = tout_ms(6000);// 6s
// balanced
inline constexpr const uint16_t MIN_BLE_INTERVAL_BALANCED       = itvl_us(15000);  // 15ms
inline constexpr const uint16_t MAX_BLE_INTERVAL_BALANCED       = itvl_us(30000);  // 30ms
inline constexpr const uint16_t BLE_SLAVE_LATENCY_BALANCED      = 2;               // light dozing
inline constexpr const uint16_t BLE_SUPERVISION_TIMEOUT_BALANCED = tout_ms(5000);  // 5s

// Optional: make the key distribution explicit (same idea as init_key/rsp_key in Bluedroid)
inline constexpr uint8_t        KEYDIST_ENC                     = 0x01;  // BLE_SPAIR_KEY_DIST_ENC
inline constexpr uint8_t        KEYDIST_ID                      = 0x02;  // BLE_SPAIR_KEY_DIST_ID
inline constexpr uint8_t        KEYDIST_SIGN                    = 0x04;  // BLE_SPAIR_KEY_DIST_SIGN
inline constexpr uint8_t        KEYDIST_LINK                    = 0x08;  // BLE_SPAIR_KEY_DIST_LINK

// ===== Tx backoff/throttle =====
inline constexpr uint16_t       PROBE_AFTER_SUCCESSES           = 64;           // wait this many clean sends before probing faster
inline constexpr uint16_t       PROBE_CONFIRM_SUCCESSES         = 48;           // accept probe only after this many clean sends
inline constexpr uint32_t       PROBE_STEP_US                   = 10;           // absolute probe step
inline constexpr uint32_t       PROBE_STEP_PCT                  = 2;            // or % of current interval (use the larger of the two)

inline constexpr uint8_t        LKG_ESCALATE_AFTER_FAILS        = 3;         // if LKG last known good fails this many times in a row, relax it
inline constexpr uint32_t       LKG_ESCALATE_NUM                = 103;          // ×1.03
inline constexpr uint32_t       LKG_ESCALATE_DEN                = 100;

inline constexpr int            COOL_SUCCESS_REQUIRED           = 64;           // successes before probing resumes after a backoff
inline constexpr uint32_t       ESCALATE_COOLDOWN_US            = 1000000;      // 1 s
inline constexpr uint32_t       TIMEOUT_BACKOFF_NUM             = 6;            // ×1.20 on timeout
inline constexpr uint32_t       TIMEOUT_BACKOFF_DEN    = 5;

/******************************************************************************************************/
/* Structures */
/******************************************************************************************************/

enum class Mode {
  Fast,
  LowPower,
  LongRange,
  Balanced
};

/******************************************************************************************************/
/* Device Driver */
/***************************************************************************************************/

class BLESerial : public Stream {
public:
  // Construction / configuration
  BLESerial() = default;
  bool begin(Mode mode = Mode::Fast,
             const char* deviceName = "BLESerialDevice",
             uint16_t mtu = BLE_SERIAL_MAX_MTU,
             bool secure = false);  // init stack, create service, start advertising
  void end();                       // stop advertising, dispose service/server

  // Stream API
  int available() override;               // RX bytes ready
  int read() override;                    // 1 byte from RX
  int peek() override;                    // next byte without consuming
  void flush() override;                  // drain TX ring to link
  size_t write(uint8_t b) override;       // enqueue single byte to TX
  size_t write(const uint8_t* b, size_t n) override;

  // Optional: convenience
  int readBytes(uint8_t* dst, size_t n);
  bool readLine(char* dst, size_t maxLen, uint32_t timeoutMs = 0);

  // Pump in polling model
  void update();

  // Transport status helpers
  bool connected() const { return deviceConnected && clientSubscribed; }
  uint16_t mtu() const { return mtu; }
  Mode mode() const { return mode; }

  // Logging / security knobs
  void setLogLevel(uint8_t lvl) { logLevel = lvl; }
  void setSecure(bool en) { secure = en; }

  // Static GAP handler
  static int gapEventHandler(struct ble_gap_event* ev, void* arg);
  // Active instance used by the static GAP handler
  static BLESerial* active;

  // Link adaptation (RSSI/PHY)
  void adjustLink();

private:
  // ===== BLE primitives =====
  NimBLEServer*           server      = nullptr;
  NimBLEService*          service     = nullptr;
  NimBLECharacteristic*   txChar      = nullptr;
  NimBLECharacteristic*   rxChar      = nullptr;
  NimBLEAdvertising*      advertising = nullptr;
  NimBLEAdvertisementData advData;
  NimBLEAdvertisementData scanData;

  // GAP/GATT state
  volatile bool     deviceConnected   = false;
  volatile bool     clientSubscribed  = false;
  volatile uint16_t connHandle        = BLE_HS_CONN_HANDLE_NONE;
  std::string       deviceMac;

  // PHY/DLE
  volatile bool     phyIs2M           = false;
  volatile bool     phyIsCoded        = false;
  volatile uint8_t  desiredCodedScheme= 8;   // 2 or 8 when coded
  volatile uint8_t  codedScheme       = 8;   // best-effort assumption
  volatile uint16_t llTimeUs          = 2120; // 1M default
  volatile uint16_t llOctets          = 251;  // target octets

  // MTU / chunking
  volatile uint16_t mtu               = 23;
  volatile uint16_t txChunkSize       = 20;
  volatile int      mtuRetryCount     = 0;
  static constexpr int kMtuRetryMax   = 3;

  // TX pacing/backoff
  volatile uint32_t sendIntervalUs    = 200;
  volatile uint32_t minSendIntervalUs = 200;
  static constexpr uint32_t kMaxSendIntervalUs = 1000000; // 1s ceiling
  volatile uint32_t lkgIntervalUs     = 0;
  volatile bool     probing           = false;
  volatile uint16_t probeSuccesses    = 0;
  volatile uint8_t  probeFailures     = 0;
  volatile uint8_t  lkgFailStreak     = 0;
  volatile uint32_t lastEscalateAtUs  = 0;
  volatile bool     recentlyBackedOff = false;
  volatile int      cooldownSuccess   = 0;
  volatile int      successStreak     = 0;

  // EBADDATA fallback
  volatile uint8_t  badDataRetries    = 0;
  static constexpr uint8_t kBadDataMaxRetries = 8;

  // TX book-keeping
  volatile uint64_t lastTxUs          = 0;
  volatile size_t   pendingLen        = 0;
  volatile bool     txOk              = false;
  volatile size_t   bytesTx           = 0;
  volatile size_t   txDrops           = 0;
  volatile bool     txAvailable       = true;
  char              pending[BLE_SERIAL_MAX_FRAME_SIZE]{};

  // RX book-keeping
  volatile size_t   bytesRx           = 0;
  volatile size_t   rxDrops           = 0;
  volatile uint64_t lastRxUs          = 0;

  // Buffers and flow control
  RingBuffer<uint8_t, 4096> rxBuf;
  RingBuffer<uint8_t, 4096> txBuf;
  size_t           highWater          = (txBuf.capacity() * 3) / 4;
  size_t           lowWater           = (txBuf.capacity()) / 4;
  volatile bool    txLocked           = false; // prevent producers when high water reached

  // Configuration
  Mode             mode               = Mode::Fast;
  bool             secure             = false;
  uint8_t          logLevel           = INFO;

  // Security
  uint32_t          passkey = 0; // stores the currently displayed/generated 6-digit passkey

  // RSSI polling
  int8_t           rssiRaw            = 0;
  int8_t           rssiAvg            = 0;
  uint32_t         lastRssiMs         = 0;
  uint32_t         lastRssiActionMs   = 0;

  #ifdef ARDUINO_ARCH_ESP32
    // Create RSSI task if not already
    static TaskHandle_t rssiTaskHandle;
  #endif

  // ===== Functions (declarations only; implementations in .cpp) =====

  // TX pump and helpers
  void            pumpTx();
  size_t          frameSize() const { return (mtu > BLE_SERIAL_ATT_HDR_BYTES) ? (mtu - BLE_SERIAL_ATT_HDR_BYTES) : 20; }

  static uint16_t computeTxChunkSize(uint16_t mtu, uint16_t llOctets, Mode mode);
  static uint32_t computeMinSendIntervalUs(uint16_t chunkSize, uint16_t llOctets, uint16_t llTimeUs, Mode mode);
  size_t          updateLowWaterMark(size_t chunkSize);
  void            resetTxRamp(bool forceToMin);
  void            recomputeTxTiming();
  void            updateLlTime();

  // Callbacks
  class ServerCallbacks;
  class RxCallbacks;
  class TxCallbacks;
  friend class ServerCallbacks;
  friend class RxCallbacks;
  friend class TxCallbacks;
};

#endif // BLE_SERIAL_H
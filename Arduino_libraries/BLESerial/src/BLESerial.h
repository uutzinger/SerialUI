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
#include <functional>

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

#if defined(ESP32)
    # include "freertos/FreeRTOS.h"
    # include "freertos/portmacro.h"
    # include "freertos/task.h"
#endif

// Define critical section helpers BEFORE class so they are visible where used.
// They reference 'this->mux_' which is a per-instance spinlock.
#ifdef ARDUINO_ARCH_ESP32
  # define TX_CRITICAL_ENTER() portENTER_CRITICAL(&this->txMux)
  # define TX_CRITICAL_EXIT()  portEXIT_CRITICAL(&this->txMux)
#else
  # define TX_CRITICAL_ENTER()
  # define TX_CRITICAL_EXIT()
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
#define ERROR   2 
#define WARNING 3
#define INFO    4
#define DEBUG   5

// Max GATT MTU supported (ESP32 max 517); ATT payload per notify is MTU-3
#define BLE_SERIAL_MAX_MTU        517u
#define BLE_SERIAL_MAX_GATT       512u
#define BLE_SERIAL_DEFAULT_MTU    247u
#define BLE_SERIAL_MIN_MTU         23u
#define BLE_SERIAL_ATT_HDR_BYTES    3u
#define BLE_SERIAL_L2CAP_HDR_BYTES  4u
#define BLE_SERIAL_ENCRYPT_BYTES    4u

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

inline constexpr uint32_t       LL_DEFAULT_TIME_US              =   2120;

// BLE optimizations
static constexpr uint16_t itvl_us(uint32_t us)    
    { return (uint16_t)((us * 4) / 5000); } // is in units of 1.25ms
static constexpr uint16_t tout_ms(uint32_t ms)
    { return (uint16_t)(ms / 10); }         // is in units of 10ms

inline constexpr const uint32_t MAX_SEND_INTERVAL_US            = 1000000u;

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

inline constexpr uint8_t        LKG_ESCALATE_AFTER_FAILS        = 3;            // if LKG last known good fails this many times in a row, relax it
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
  bool     begin(Mode mode = Mode::Fast,
              const char* deviceName = "BLESerialDevice",
              bool secure = false);                     // init stack, create service, start advertising
  void     end();                                       // stop advertising, dispose service/server

  // Stream API
  int      available() override;                        // RX bytes ready
  int      read() override;                             // 1 byte from RX
  int      read(uint8_t* dst, size_t n);                // helper: read up to n bytes
  int      peek() override;                             // next byte without consuming
  int      peek(uint8_t* dst, size_t n);                // helper: preview up to n bytes
  size_t   write(uint8_t b) override;                   // enqueue single byte to TX
  size_t   write(const uint8_t* b, size_t n) override;
  bool     writeReady() const { return txAvailable; }   // If false you should not write
  bool     writeAvailable(size_t n = 1) const { return txBuf.capacity() - txBuf.available() >= n; }
  size_t   writeTimeout(const uint8_t* p, size_t n, uint32_t timeoutMs = 50);
  void     flush() override;                            // drain TX ring to link

  // Pump in polling model
  void     update();

  #ifdef ARDUINO_ARCH_ESP32
    // TX pump strategy (ESP32 only): Polling (use update()) or Task (background FreeRTOS task)
    enum class PumpMode { Polling, Task };
    void     setPumpMode(PumpMode m);
    PumpMode getPumpMode() const { return pumpMode; }
  #endif

  // Event hooks (no subclassing required)
  // These run in NimBLE callback context; keep handlers fast or defer heavy work to your loop/task.
  void     setOnClientConnect(std::function<void(const std::string& addr)> cb) { onClientConnect = std::move(cb); }
  void     setOnClientDisconnect(std::function<void(const std::string& addr, uint16_t reason)> cb) { onClientDisconnect = std::move(cb); }
  void     setOnMtuChanged(std::function<void(uint16_t mtu)> cb) { onMtuChanged = std::move(cb); }
  void     setOnSubscribeChanged(std::function<void(bool subscribed)> cb) { onSubscribeChanged = std::move(cb); }
  void     setOnDataReceived(std::function<void(const uint8_t* data, size_t len)> cb) { onDataReceived = std::move(cb); }
  void     setOnPacingChanged(std::function<void(const struct PacingInfo& info, enum class PacingReason reason)> cb) { onPacingChanged = std::move(cb); }

  // Logging / security knobs
  void     setLogLevel(uint8_t lvl) { logLevel = lvl; }
  bool     requestMTU(uint16_t newMtu);

  // Stats
  bool     connected()  const { return deviceConnected && clientSubscribed; }
  uint16_t mtu()        const { return mtu; }
  Mode     mode()       const { return mode; }
  uint32_t bytesRx()    const { return bytesRx; }
  uint32_t bytesTx()    const { return bytesTx; }
  uint32_t rxDrops()    const { return rxDrops; }
  uint32_t txDrops()    const { return txDrops; }
  uint32_t interval()   const { return sendIntervalUs; }
  int16_t  rssi()       const { return rssiAvg; }
  const std::string& mac() const { return deviceMac; }
  size_t   txBuffered() const { return txBuf.available(); }
  size_t   rxBuffered() const { return rxBuf.available(); }


private:
  // ===== BLE primitives =====
  NimBLEServer*           server      = nullptr;
  NimBLEService*          service     = nullptr;
  NimBLECharacteristic*   txChar      = nullptr;
  NimBLECharacteristic*   rxChar      = nullptr;
  NimBLEAdvertising*      advertising = nullptr;
  NimBLEAdvertisementData advData;
  NimBLEAdvertisementData scanData;

  // Static GAP handler
  static int gapEventHandler(struct ble_gap_event* ev, void* arg);
  // Active instance used by the static GAP handler
  static BLESerial* active;

  // GAP/GATT state
  volatile bool     deviceConnected   = false;
  volatile bool     clientSubscribed  = false;
  volatile uint16_t connHandle        = BLE_HS_CONN_HANDLE_NONE;
  std::string       deviceMac;

  // PHY/DLE
  volatile uint8_t  phyMask           = BLE_GAP_LE_PHY_1MASK;
  volatile uint8_t  codedScheme       = 2;   // 2 or 8
  volatile uint16_t llOctets          = LL_MAX_OCTETS;  // target octets
  volatile uint16_t llTimeUs          = 2120; // 1M default
  volatile bool     phyIs2M           = false;
  volatile bool     phyIsCoded        = false;

  // Desired link settings that we request from controller/peer
  uint8_t           desiredPhyMask    = BLE_GAP_LE_PHY_1MASK;
  uint8_t           desiredCodedScheme= 0;        // 0, 2, or 8 (desired)
  uint16_t          desiredLlOctets   = LL_MAX_OCTETS;
  uint16_t          desiredLlTimeUs   = LL_DEFAULT_TIME_US;     // conservative time cap

  // MTU / chunking
  volatile uint16_t mtu               = 23;
  volatile uint16_t txChunkSize       = 20;
  volatile int      mtuRetryCount     = 0;
  static constexpr int kMtuRetryMax   = 3;

  // TX pacing/backoff
  volatile uint32_t sendIntervalUs    = 200;
  volatile uint32_t minSendIntervalUs = 200;
  volatile uint32_t lkgIntervalUs     = 0;
  volatile bool     probing           = false;
  volatile uint16_t probeSuccesses    = 0;
  volatile uint8_t  probeFailures     = 0;
  volatile uint8_t  lkgFailStreak     = 0;
  volatile uint32_t lastEscalateAtUs  = 0;
  volatile bool     recentlyBackedOff = false;
  volatile int      cooldownSuccess   = 0;
  volatile int      successStreak     = 0;

  // TX book-keeping
  volatile uint32_t lastTxUs          = 0;
  volatile size_t   pendingLen        = 0;
  volatile bool     txOk              = false;
  volatile size_t   bytesTx           = 0;
  volatile size_t   txDrops           = 0;
  volatile bool     txAvailable       = true;
  char              pending[BLE_SERIAL_MAX_GATT]{};
  volatile uint8_t  badDataRetries    = 0;   // diagnostic counter for malformed payload incidents

  // RX book-keeping
  volatile size_t   bytesRx           = 0;
  volatile size_t   rxDrops           = 0;
  volatile uint32_t lastRxUs          = 0;

  // Buffers and flow control
  RingBuffer<uint8_t, 4096> rxBuf;
  RingBuffer<uint8_t, 4096> txBuf;
  size_t           highWater          = 0;
  size_t           lowWater           = 0;
  volatile bool    txLocked           = false; // prevent producers when high water reached

  int8             powerAdv           = BLE_TX_DB0;
  int8             powerScan          = BLE_TX_DB0;
  int8             powerConn          = BLE_TX_DB0;

  // Configuration
  Mode             mode               = Mode::Fast;
  bool             secure             = false;
  uint8_t          logLevel           = INFO;

  // Security
  uint32_t          passkey = 0;      // stores the currently displayed/generated 6-digit passkey

  // RSSI polling
  int8_t           rssiRaw            = 0;
  int8_t           rssiAvg            = 0;
  uint32_t         lastRssiMs         = 0;
  uint32_t         lastRssiActionMs   = 0;

  // TX pump and helpers
  void            pumpTx();
  void            checkTxSuccess();
  bool            stageTx();  
  size_t          frameSize() const { return (mtu > BLE_SERIAL_ATT_HDR_BYTES) ? (mtu - BLE_SERIAL_ATT_HDR_BYTES) : 20; }

  static uint16_t computeTxChunkSize(uint16_t mtu, uint16_t llOctets, Mode mode, bool encrypted);
  static uint32_t computeMinSendIntervalUs(uint16_t chunkSize, uint16_t llOctets, uint16_t llTimeUs, Mode mode, bool encrypted);
  size_t          updateLowWaterMark(size_t chunkSize);
  void            resetTxRamp(bool forceToMin);
  void            recomputeTxTiming();
  uint32_t        computeLlPduTimeUs(uint16_t llOctets, bool phy2M, bool phyCoded, uint8_t codedScheme);
  void            adjustLink();   // Link adaptation (RSSI/PHY)
  void            firePacingChanged(enum class PacingReason r); // internal helper to emit pacing/backoff changes

  // Background TX task helpers (ESP32)
  #ifdef ARDUINO_ARCH_ESP32
    // Instance spinlock for TX state
    portMUX_TYPE    txMux = portMUX_INITIALIZER_UNLOCKED;
    // Create RSSI task if not already
    static TaskHandle_t rssiTaskHandle;
    static TaskHandle_t txTaskHandle;

    // Current TX pump mode (ESP32 only, default: Polling)
    volatile        PumpMode pumpMode = PumpMode::Polling;

    void            startTxTask();
    void            stopTxTask();
    void            wakeTxTask();
    // Sub-ms remainder threshold: below this use microsecond delay and not vTaskDelay
    static constexpr uint32_t TASK_DELAY_THRESHOLD_US = 800;   // tune (500–1500)

  #endif

  // Callbacks
  class ServerCallbacks;
  class RxCallbacks;
  class TxCallbacks;
  friend class ServerCallbacks;
  friend class RxCallbacks;
  friend class TxCallbacks;

  std::function<void(const std::string& addr)> onClientConnect;
  std::function<void(const std::string& addr, uint16_t reason)> onClientDisconnect;
  std::function<void(uint16_t mtu)> onMtuChanged;
  std::function<void(bool subscribed)> onSubscribeChanged;
  std::function<void(const uint8_t* data, size_t len)> onDataReceived; // raw RX callback

  // Pacing/backoff notification
  struct PacingInfo {
    uint32_t sendIntervalUs;
    uint32_t minSendIntervalUs;
    uint32_t lkgIntervalUs;
    uint16_t txChunkSize;
    uint16_t mtu;
    uint16_t llOctets;
    uint16_t llTimeUs;
    bool     probing;
  };

  enum class PacingReason {
    Recompute,
    ProbeStart,
    ProbeAccepted,
    ChunkShrink,
    MsgSizeFallback,
    Escalate,
    Backoff,
    DisconnectReset
  };
  std::function<void(const PacingInfo&, PacingReason)> onPacingChanged;

};

#endif // BLE_SERIAL_H
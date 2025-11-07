/******************************************************************************************************/
// BLE Serial Library
/******************************************************************************************************/
// Driver for the BLE Serial Library
//
// This driver attempts to implement Nordic UART Service with NimBLE stack
// Urs Utzinger, Fall 2025
/******************************************************************************************************/

#include "logger.h"
#include "BLESerial.h"

class BLESerial : public Stream {

public:
  bool begin(Mode currentMode = Mode::FAST, const char* DEVICE_NAME = "BLESerialDevice", uint16_t BLE_MTU = 517); {
    // BLE: init stack, create service, start adv; UART: config UART
  
    NimBLEDevice::init(DEVICE_NAME);
    NimBLEDevice::setCustomGapHandler(myGapHandler);
    NimBLEDevice::setMTU(BLE_MTU);

    if currentMode == Mode::FAST {
      // Max power for best range and speed;
      NimBLEDevice::setPower(BLE_TX_DBM_P9, PWR_ALL);   // max TX power everywhere
    } else if currentMode == Mode::LOW_POWER {
      // Min power for best battery life; adjust as needed for your environment
      NimBLEDevice::setPower(BLE_TX_DBM_N9, PWR_ADV);   // small ADV range to save power
      NimBLEDevice::setPower(BLE_TX_DBM_N9, PWR_SCAN);  // scanning (if you do it)
      NimBLEDevice::setPower(BLE_TX_DBM_N6, PWR_CONN);  // enough for typical indoor links
    } else if (currentMode == Mode::LONG_RANGE) {
      // long range
      NimBLEDevice::setPower(BLE_TX_DBM_P9, PWR_ALL);
    } else if (currentMode == Mode::BALANCED) {
      // balanced, visible enough, not wasteful
      NimBLEDevice::setPower(BLE_TX_DBM_N3, PWR_ADV);
      NimBLEDevice::setPower(BLE_TX_DBM_N6, PWR_SCAN);
      NimBLEDevice::setPower(BLE_TX_DBM_0,  PWR_CONN);
    }

    // Optional: fix address type (disable RPA) if you want a stable MAC:
    // BLE_OWN_ADDR_PUBLIC Use the chip’s factory-burned IEEE MAC (the “public” address). Stable, globally unique.
    // BLE_OWN_ADDR_RANDOM Use the static random address you’ve set with ble_hs_id_set_rnd(). Stable across reboots only if you persist it yourself.
    // BLE_OWN_ADDR_RPA_PUBLIC_DEFAULT Use a Resolvable Private Address (RPA) derived from your public identity. This gives privacy (rotating address) but still resolvable if the peer has your IRK (bonded).
    // BLE_OWN_ADDR_RPA_RANDOM_DEFAULT Use an RPA derived from your random static identity.
 
    if (BLE_SECURE) {
      NimBLEDevice::setOwnAddrType(BLE_OWN_ADDR_RPA_PUBLIC_DEFAULT);
      // your client will need to reacquire the address each time you want to connect
    } else {
      NimBLEDevice::setOwnAddrType(BLE_OWN_ADDR_PUBLIC);
      // address remains static and can be reused by the client
    }

      // Link preferences
    if (currentMode == Mode::FAST) {
      NimBLEDevice::setDefaultPhy(BLE_GAP_LE_PHY_2M_MASK, BLE_GAP_LE_PHY_2M_MASK);
    } else {
      NimBLEDevice::setDefaultPhy(BLE_GAP_LE_PHY_ANY_MASK, BLE_GAP_LE_PHY_ANY_MASK);
    }

    // Suggest max data length for future connections; use conservative 1M time
    // (we'll retune per-connection once we know the actual PHY)
    ble_gap_write_sugg_def_data_len(LL_MAX_TX_OCTETS, LL_TIME_1M_US);

    // Security posture
    if (BLE_SECURE) {
        NimBLEDevice::setSecurityAuth(/*bonding*/true, /*mitm*/true, /*sc*/true);
        NimBLEDevice::setSecurityPasskey(BLE_PASSKEY_VALUE);                              
        // IO capability: display only (ESP_IO_CAP_OUT)
        NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);  /** Display only passkey */
        // Key distribution (init/rsp) ~ ESP_BLE_SM_SET_INIT_KEY / SET_RSP_KEY
        NimBLEDevice::setSecurityInitKey(KEYDIST_ENC | KEYDIST_ID);
        NimBLEDevice::setSecurityRespKey(KEYDIST_ENC | KEYDIST_ID);
    } else {
        NimBLEDevice::setSecurityAuth(/*bonding*/false, /*mitm*/false, /*sc*/false); // no pairing needed
    }

    pServer = NimBLEDevice::createServer();
    pServer->setCallbacks(&serverCallBacks);

    pService = pServer->createService(SERVICE_UUID);

    if (BLE_SECURE) {
      pRxCharacteristic = pService->createCharacteristic(
        CHARACTERISTIC_UUID_RX,
        NIMBLE_PROPERTY::WRITE_NR_ENC | NIMBLE_PROPERTY::WRITE // require encryption for write without response and with response
      );
    } else {
      pRxCharacteristic = pService->createCharacteristic(
        CHARACTERISTIC_UUID_RX,
        NIMBLE_PROPERTY::WRITE_NR | NIMBLE_PROPERTY::WRITE // write without response (faster)
      );
    }
    pTxCharacteristic->setCallbacks(&transmitterCallBacks);

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

    // Start the service
    pService->start();

    // Primary Advertising: Flags and Service UUID
    pAdvertising = NimBLEDevice::getAdvertising();

    if (currentMode == Mode::FAST) {
      pAdvertising->setMinInterval(0x00A0); // 100 ms
      pAdvertising->setMaxInterval(0x00F0); // 150 ms
    } else if (currentMode == Mode::LOWPOWER) {
      pAdvertising->setMinInterval(0x0640); // 1.0 s
      pAdvertising->setMaxInterval(0x0C80); // 2.0 s
    } else { // LONGRANGE
      pAdvertising->setMinInterval(0x0320); // 0.5 s
      pAdvertising->setMaxInterval(0x0640); // 1.0 s
    }

    // Flags are recommended in primary ADV (general discoverable, no BR/EDR)
    advData.setFlags(BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP);
    // Put service UUID in the primary ADV
    advData.addServiceUUID(SERVICE_UUID);   
    // If you have multiple services, call addServiceUUID(...) for each:
    // advData.addServiceUUID(NimBLEUUID(SERVICE_UUID_2));
    // Apply primary ADV payload (replaces any previous content)
    advData.addTxPower();

    // Scan Response: put the full name here (saves ADV space)
    scanData.setName(DEVICE_NAME);
    scanData.setAppearance(BLE_APPEARANCE);
    const uint8_t mfg[] = { 0xFF, 0xFF, 'S','i','m',':','1','.','0' }; // 0xFFFF + 27 bytes max
    scanData.setManufacturerData(std::string((const char*)mfg, sizeof(mfg)));  

    pAdvertising->setAdvertisementData(advData);
    pAdvertising->setScanResponseData(scanData);
    
    pAdvertising->start();

    // Print MAC last (purely informational)
    deviceMac = NimBLEDevice::getAddress().toString();
    for (char &c : deviceMac) c = (char)toupper((unsigned char)c);
    if (DEBUG_LEVEL >= INFO) {  
      Serial.printf("MAC: %s\r\n", deviceMac.c_str());
    }

    randomSeed(analogRead(0));

  }

  void end() {
    // clean up BLE/UART resources
  };

  // Stream API
  int available() override { 
    // RX bytes ready
    return rxBuf.available(); 
  }

  int read(&out) override { 
    rxBuf.pop()
    return rxBuf.pop(); 
  };

   // Optional: convenience
  int readBytes(uint8_t* dst, size_t n) {
    return rxBuf.read(dst, n);
  };

  int peek() override { 
    return rxBuf.peek(); 
  };                    // next byte without consuming
  
  void flush() override { 
    while (txBuf.available() > 0) {
      // Wait until all data is sent
      pumpTx();
      delay(1); // yield to allow link processing
    }
  }; // drain TX ring to link (non-blocking loop until link busy/empty)
  
  size_t write(uint8_t b) override { 
    return txBuf.push(&b, 1, false);
  }; // enqueue single byte to TX
  
  size_t write(const uint8_t* b, size_t n) override {
    return txBuf.push(b, n, false);
  };

  bool readLine(char* dst, size_t maxLen, uint32_t timeout_ms = 0){

  };

  // Call regularly if you choose the polling model
  void update() {

    if (deviceConnected && clientSubscribed){

      // consume after previous was success
      if (txOkFlag && pendingLen > 0) {
        txBuffer.consume(pendingLen);
        txOkFlag = false;
        pendingLen = 0;
        size_t used = txBuffer.available();
        if (used <= lowWaterMark) {
          generationAllowed = true;
        }
      }

      // time to send next chunk?
      if ((currentTime - lastSend) >= sendInterval) {
        lastSend = currentTime;

        if (pendingLen == 0 && txBuffer.available() > 0) {
          pendingLen = txBuffer.peek(pending, txChunkSize);
          if (pendingLen > 0) generationAllowed = false;
        }

        if (pendingLen > 0) {
          if (pendingLen <= txChunkSize) {
            pTxCharacteristic->setValue(reinterpret_cast<uint8_t*>(pending), pendingLen);
            pTxCharacteristic->notify();
          } else {
            pendingLen = 0; // staged chunk no longer fits; drop it
            if (txBuffer.available() <= lowWaterMark) generationAllowed = true;
          }
        }
      }
    }

  };

  // Transport status helpers
  bool connected() const { 
    return linkReady; 
  }
  
  uint16_t mtu() const { 
    return negotiatedMTU; 
  }

private:
  // ===== GATT / ATT payload sizing =====
  inline constexpr uint16_t      ATT_HDR_BYTES         =    3;
  inline constexpr int8_t        RSSI_LOW_THRESHOLD    =  -80;   // low power threshold (increase power if in LOWPOWER mode)
  inline constexpr int8_t        RSSI_FAST_THRESHOLD   =  -65;   // Switch back to 2M/1M
  inline constexpr int8_t        RSSI_HYSTERESIS       =    4;   // Prevent oscillation
  inline constexpr int8_t        RSSI_S8_THRESHOLD     =  -82;   // go S=8 below this
  inline constexpr int8_t        RSSI_S2_THRESHOLD     =  -75;   // go S=2 below this
  inline constexpr uint32_t      RSSI_INTERVAL_US      = 500000UL; // 0.5s

  // ===== LL (Link-Layer) performance knobs =====
  // If MTU is larger than LL size the GATT packets need to be fragmented on the link layer
  // default LL size is 27
  // maximum is 251
  // Common BLE 4.2/5.0 DLE targets is 244
  inline constexpr uint16_t      LL_DEF_TX_OCTETS     =    27;    // 27..251
  inline constexpr uint16_t      LL_CONS_TX_OCTETS    =   244;    // 27..251
  inline constexpr uint16_t      LL_MAX_TX_OCTETS     =   251;    // 27..251
  inline constexpr uint16_t      LL_TIME_1M_US        =  2120;    // for 1M PHY
  inline constexpr uint16_t      LL_TIME_2M_US        =  1060;    // for 2M PHY
  inline constexpr uint16_t      LL_TIME_CODED_S2_US  =  4240;    // for Coded PHY (S2)
  inline constexpr uint16_t      LL_TIME_CODED_S8_US  = 16960;    // for Coded PHY (S8)

  // ===== UUIDs =====
  // Nordic UART Serial (NUS)
  inline constexpr const char SERVICE_UUID[]          = {"6E400001-B5A3-F393-E0A9-E50E24DCCA9E"};
  inline constexpr const char CHARACTERISTIC_UUID_RX[]= {"6E400002-B5A3-F393-E0A9-E50E24DCCA9E"};
  inline constexpr const char CHARACTERISTIC_UUID_TX[]= {"6E400003-B5A3-F393-E0A9-E50E24DCCA9E"};

  // BLE optimizations
  static constexpr uint16_t itvl_us(uint32_t us)    { return (uint16_t)((us * 4) / 5000); } // is in units of 1.25ms
  static constexpr uint16_t tout_ms(uint32_t ms)    { return (uint16_t)(ms / 10); }         // is in units of 10ms

  // aggressive speed
  inline constexpr const uint16_t MIN_BLE_INTERVAL_SPEED         = itvl_us( 7500);  // Minimum connection interval in microseconds 7.5ms to 4s
  inline constexpr const uint16_t MAX_BLE_INTERVAL_SPEED         = itvl_us(10000);  // Maximum connection interval in µs 7.5ms to 4s
  inline constexpr const uint16_t BLE_SLAVE_LATENCY_SPEED                    = 0;   // Slave latency: number of connection events that can be skipped
  inline constexpr const uint16_t BLE_SUPERVISION_TIMEOUT_SPEED   = tout_ms(4000);  // Supervision timeout in milli seconds 100ms to 32s, needs to be larger than 2 * (latency + 1) * (max_interval_ms)
  // low power
  inline constexpr const uint16_t MIN_BLE_INTERVAL_LOWPWR         = itvl_us(60000);  // 60ms
  inline constexpr const uint16_t MAX_BLE_INTERVAL_LOWPWR         = itvl_us(120000);  // 120ms
  inline constexpr const uint16_t BLE_SLAVE_LATENCY_LOWPWR                    = 8;   // can raise
  inline constexpr const uint16_t BLE_SUPERVISION_TIMEOUT_LOWPWR  = tout_ms( 6000);  // 6s
  // long range
  inline constexpr const uint16_t MIN_BLE_INTERVAL_LONG_RANGE         = itvl_us(30000);  // 30ms
  inline constexpr const uint16_t MAX_BLE_INTERVAL_LONG_RANGE         = itvl_us(60000);  // 60ms
  inline constexpr const uint16_t BLE_SLAVE_LATENCY_LONG_RANGE                    = 2;   // some dozing
  inline constexpr const uint16_t BLE_SUPERVISION_TIMEOUT_LONG_RANGE   = tout_ms(6000);  // 6s

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
  static NimBLEService         *pService              = nullptr;           // BLE Service
  static NimBLEAdvertisementData advData;
  static NimBLEAdvertisementData scanData;

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

  static char                   pending[MAX_FRAME_SIZE];                  // temp keep for sent frame
  volatile bool                 txLocked              = false;         // data producer is allowed to generate
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
  const uint32_t                maxSendIntervalUs     = 1000000;     // ceiling in µs

  volatile uint64_t             lastSend              = 0;            // last time data was sent/notify
  volatile size_t               pendingLen            = 0;            // length data that we attempted to send
  volatile bool                 txOkFlag              = false;        // no issues last data was sent
  volatile int                  successStreak         = 0;            // number of consecutive successful sends
  volatile int                  cooldownSuccess       = 0;            // successes since last backoff
  volatile bool                 recentlyBackedOff     = false;        // gate decreases after congestion
  volatile uint8_t              badDataRetries        = 0;            // EBADDATA soft fallback attempts
  inline constexpr uint8_t      badDataMaxRetries     = 8;            // limit EBADDATA chunk shrink attempts

  // ring buffers (power-of-two size)
  RingBuffer<uint8_t, 4096> rxBuf;
  RingBuffer<uint8_t, 4096> txBuf;

  // link state
  volatile bool deviceConnected = false;
  volatile bool clientSubscribed = false;
  volatile uint16_t mtu = 23;
  int8_t rssi                  = 0;                 // BLE signal strength
  int8_t f_rssi                = -50;   
  volatile bool                 phyIs2M               = false;
  volatile bool                 phyIsCODED            = false;
  static std::string            deviceMac;

  // TX pump and helpers
  void pumpTx();         // slice & send frames until busy
  size_t frameSize() const { return (negotiatedMTU > 3) ? (negotiatedMTU - 3) : 20; }

  // Low-water/high-water for flow control to producers
  const size_t highWater = txBuf.capacity() * 3 / 4;
  const size_t lowWater  = txBuf.capacity() / 4;

  // Backoff (for BLE EBUSY/ENOMEM/ETIMEOUT)
  uint32_t nextTryMs = 0;
  uint32_t backoffMs = 0;

  // === Tasks ===
  static TaskHandle_t           rssiTaskHandle        = nullptr;

  static inline uint16_t compute_txChunkSize(uint16_t mtu_val, uint16_t ll_octets) {
      // Base payload is MTU-3 (ATT header excluded). For SPEED profile, allow up to
      // 2 LL PDUs to reduce per-notify overhead; otherwise keep within a single LL PDU.
      if (mtu_val <= 3) return 20;
      const uint16_t att_payload = (uint16_t)(mtu_val - 3);

      // Max payload fitting N LL PDUs: N*ll_octets - (L2CAP 4 + ATT 3)
      const uint16_t one_pdu_max = (ll_octets > 7) ? (uint16_t)(ll_octets - 7) : 20;
      if (currentMode == Mode::FAST) {
        //const uint32_t two_pdu_calc = (uint32_t)ll_octets * 2u;
        //const uint16_t two_pdu_max  = (two_pdu_calc > 7u) ? (uint16_t)(two_pdu_calc - 7u) : one_pdu_max;
        //uint16_t llLimit = (two_pdu_max > one_pdu_max) ? two_pdu_max : one_pdu_max;
        uint16_t llLimit = one_pdu_max;
      } else {
        uint16_t llLimit = one_pdu_max;
      }

      // Final chunk is limited by both ATT MTU and chosen LL limit
      return (att_payload < llLimit) ? att_payload : llLimit;
  }

  static inline uint32_t compute_minSendIntervalUs(uint16_t chunkSize, uint16_t ll_octets, uint16_t ll_time_us) {
      // Estimate number of link-layer PDUs (ceil divide), then multiply by per-PDU time (+10% guard)
      uint16_t l2cap_plus_att = (uint16_t)(chunkSize + 4 /*L2CAP hdr*/ + 3 /*ATT hdr*/);
      uint16_t num_ll_pd   = (uint16_t)((l2cap_plus_att + ll_octets - 1) / ll_octets);
      // mode-specific guard
      if (currentMode == Mode::FAST) {
        const uint32_t guard_num = 103, guard_den = 100;  // +3%
      } else if (currentMode == Mode::LOW_POWER) {
        const uint32_t guard_num = 110, guard_den = 100;  // +10%
      } else {
        const uint32_t guard_num = 115, guard_den = 100;  // +15%
      }
      return (uint32_t)num_ll_pd * (uint32_t)ll_time_us * guard_num / guard_den;
  
  }

  static inline size_t update_lowWaterMark(size_t chunkSize) {
      size_t lw = 2 * (size_t)chunkSize;    // up to two outbound packets buffered
      size_t cap = TX_BUFFERSIZE / 4;       // don't let low water exceed 25% of buffer
      if (lw > cap) lw = cap;
      if (lw < chunkSize) lw = chunkSize;   // never below one chunk
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

    // Transport-specific shims (implemented in a derived or composed object)
  bool transportSend(const uint8_t* p, size_t n);  // returns true if accepted
  void onTransportWritable();                      // called when link becomes writable again
  void onTransportRx(const uint8_t* p, size_t n);  // push inbound bytes into rxBuf
  void onTransportEvent_MTU(uint16_t newMtu) { negotiatedMTU = newMtu; }
  void onTransportEvent_Link(bool up) { linkReady = up; }

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

};

// ===============================================================================================================================================================
// BLE Service and Characteristic Callbacks
// ===============================================================================================================================================================

// --------------------------------
// Server Callbacks 
// --------------------------------
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

    // Reset EBADDATA fallback budget
    badDataRetries = 0;

    // We can use the connection handle here to ask for different connection parameters.
    pServer->updateConnParams(
      g_connectHandle, 
      MIN_BLE_INTERVAL,
      MAX_BLE_INTERVAL,
      BLE_SLAVE_LATENCY,
      BLE_SUPERVISION_TIMEOUT
    );

    //PHY and DLE tuning
    if (currentMode == Mode::FAST) {
      // Max speed
      // Ask for 2M (if not supported, rc will be non-zero; that's OK)
      (void)ble_gap_set_prefered_le_phy(g_connectHandle, BLE_GAP_LE_PHY_2M_MASK, BLE_GAP_LE_PHY_2M_MASK, 0);
    } else if (currentMode == Mode::LOW_POWER) {
      // Low Power
      (void)ble_gap_set_prefered_le_phy(g_connectHandle, BLE_GAP_LE_PHY_1M_MASK, BLE_GAP_LE_PHY_1M_MASK, 0);
    } else {
      // Long Range
      (void)ble_gap_set_prefered_le_phy(
        g_connectHandle, 
        BLE_GAP_LE_PHY_CODED_MASK, 
        BLE_GAP_LE_PHY_CODED_MASK, 
        (desiredCodedScheme == 8) ? BLE_GAP_LE_PHY_CODED_S8 : BLE_GAP_LE_PHY_CODED_S2);
    }

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

    } else {
      // Fallback: assume 1M timings if we couldn't read
      (void)ble_gap_set_data_len(g_connectHandle, LL_TX_OCTETS, LL_TIME_1M_US);
    }

    if (currentMode == Mode::LOW_POWER) {
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
    }
 
    // Start Pairing

    if (BLE_SECURE) {
      NimBLEDevice::startSecurity(g_connectHandle);
    }

    if (DEBUG_LEVEL >= INFO) {
      Serial.printf("Client [%s] is connected.\r\n", connInfo.getAddress().toString().c_str());
    }

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
    badDataRetries  = 0;
    if (DEBUG_LEVEL >= INFO) {
      uint8_t hci =  (uint8_t)(reason & 0xFF);
      Serial.printf("Client [%s] is disconnected (raw=%d, %s). Advertising restarted.\r\n",
                    connInfo.getAddress().toString().c_str(), reason, hciDisconnectReasonStr(hci));
    }
  }

  // MTU updated
  void onMTUChange(uint16_t m, NimBLEConnInfo& connInfo) override {
    mtu = m;
    recompute_tx_timing();
    probing = false; probeSuccesses = 0; probeFailures = 0; lkgFailStreak = 0;
    recentlyBackedOff = false; cooldownSuccess = 0; successStreak = 0;
    lkgInterval = sendInterval;    
    badDataRetries = 0;
    if (DEBUG_LEVEL >= INFO) {
      Serial.printf("MTU updated: %u (conn=%u), tx chunk size=%u, min send interval=%u\r\n", 
        m, connInfo.getConnHandle(), txChunkSize, minSendIntervalUs);
    }
  }

  // Security callbacks 

  // Passkey display
  uint32_t onPassKeyDisplay() override {
    if (DEBUG_LEVEL >= WANTED) {
      Serial.printf("Server Passkey Display: %u\r\n", BLE_PASSKEY_VALUE);
    }
    // This should return a random 6 digit number for security
    //   or make your own static passkey as done here.
    return BLE_PASSKEY_VALUE;
 }

  // Request to confirm a passkey value match
  void onConfirmPassKey(NimBLEConnInfo& connInfo, uint32_t pass_key) override {
    /** Inject false if passkeys don't match. */
    if (pass_key == BLE_PASSKEY_VALUE) {
      NimBLEDevice::injectConfirmPasskey(connInfo, true);
      if (DEBUG_LEVEL >= INFO) {
        Serial.printf("The passkey: %" PRIu32 " matches\r\n", pass_key);
      }
    } else {
      NimBLEDevice::injectConfirmPasskey(connInfo, false);
      if (DEBUG_LEVEL >= INFO) {
        Serial.printf("The passkey: %" PRIu32 " does not match\r\n", pass_key);
      }
    }
  }

  // Authentication complete
  void onAuthenticationComplete(NimBLEConnInfo& connInfo) override {
    // Check that encryption was successful, if not we disconnect the client
    //   When security is turned off this will not be called
    if (!connInfo.isEncrypted()) {
      NimBLEDevice::getServer()->disconnect(connInfo.getConnHandle());
      if (DEBUG_LEVEL >= WARNING) {
        Serial.printf("Encrypt connection failed - disconnecting client\r\n");
      }
      return;
    }
    if (DEBUG_LEVEL >= INFO) {
      Serial.printf("Secured connection to: %s\r\n", connInfo.getAddress().toString().c_str());
    }
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
    if (DEBUG_LEVEL >= DEBUG) {
      Serial.printf("%s : onWrite(), value: %s\r\n",
                    pCharacteristic->getUUID().toString().c_str(),
                    v.c_str());
    }
  }


} receiverCallBacks;

// --------------------------------
// TX Callbacks
// --------------------------------

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
  Status codes:
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
          if (DEBUG_LEVEL >= INFO) {
            Serial.printf("Probe accepted. LKG=%u\r\n", lkgInterval);
          }
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
          if (DEBUG_LEVEL >= INFO) {
            Serial.printf("Probe start: %u -> %u\r\n", lkgInterval, sendInterval);
          }
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
          if (DEBUG_LEVEL >= INFO) {
            Serial.printf("EMSGSIZE: MTU adjusted, send interval: %u\r\n", sendInterval);
          }
        } else {
          uint16_t oldChunk = txChunkSize;
          txChunkSize = (uint16_t)max(20, (int)txChunkSize / 2);
          lowWaterMark = update_lowWaterMark(txChunkSize);
          minSendIntervalUs = compute_minSendIntervalUs(txChunkSize, g_ll_tx_octets, llTimeUS);
          if (sendInterval < minSendIntervalUs) sendInterval = minSendIntervalUs;
          if (DEBUG_LEVEL >= INFO) {
            Serial.printf("EMSGSIZE: Chunk reduced old=%u new=%u minSendIntervalUs=%u\r\n",
                          oldChunk, txChunkSize, minSendIntervalUs);
          }
        }
        pendingLen  = 0; // drop staged copy (ring still has it)
        // Keep generationAllowed = false so next loop re-peeks the same data with the new size
      } 
      else 
      {
        // We have issues adjusting chunk size, last try effort before disconnect
        if (DEBUG_LEVEL >= WARNING) {
          Serial.println("EMSGSIZE: retries exceeded");
        }
        if (txChunkSize > 20) {
          // One last fallback before disconnect: force minimum chunk and retry once
          txChunkSize = 20;
          lowWaterMark = update_lowWaterMark(txChunkSize);
          minSendIntervalUs = compute_minSendIntervalUs(txChunkSize, g_ll_tx_octets, llTimeUS);
          if (sendInterval < minSendIntervalUs) sendInterval = minSendIntervalUs;
          mtuRetryCount = 0; // give it another chance
        } else {
          if (DEBUG_LEVEL >= WARNING) {
            Serial.println("EMSGSIZE: retries exceeded, disconnecting");
          }
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

      const uint64_t now = micros();
      if ((now - lastPrint9Us) > 500000ULL) { // rate-limit: print at most ~2 Hz
        if (DEBUG_LEVEL >= WARNING) {
          if (suppressed9 > 0) {
            Serial.printf("EBADDATA: +%u suppressed\r\n", suppressed9);
          }
          Serial.printf("EBADDATA: code=%d (%s)\r\n", code, codeName(code));
        }
        lastPrint9Us = (uint32_t)now;
        suppressed9  = 0;
      } else {
        ++suppressed9; // quiet path
      }

      if (badDataRetries < badDataMaxRetries) {
        uint16_t oldChunk = txChunkSize;
        // shrink ~25% per attempt; floor at 20 bytes
        uint16_t newChunk = (uint16_t)max(20, (int)((oldChunk * 9) / 10));
        if (newChunk < oldChunk) {
          txChunkSize = newChunk;
          lowWaterMark = update_lowWaterMark(txChunkSize);
          minSendIntervalUs = compute_minSendIntervalUs(txChunkSize, g_ll_tx_octets, llTimeUS);
          if (sendInterval < minSendIntervalUs) sendInterval = minSendIntervalUs; // keep floor only
          ++badDataRetries;
          if (DEBUG_LEVEL >= INFO) {
            Serial.printf("EBADDATA: reduced chunk old=%u new=%u minSendIntervalUs=%u (retry %u/%u)\r\n",
                          oldChunk, txChunkSize, minSendIntervalUs, badDataRetries, badDataMaxRetries);
          }
        }
      }
      // Restage the same data at the new size; do not change pacing/probe state
      pendingLen    = 0;
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
        if (DEBUG_LEVEL >= INFO) {
          Serial.printf("Congestion: Probe failed, revert to LKG=%u\r\n", sendInterval);
        }
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
            if (DEBUG_LEVEL >= INFO) {
              Serial.printf("Congestion: Escalate LKG to %u\r\n", lkgInterval);
            }
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
      if (DEBUG_LEVEL >= WARNING) {
        Serial.println("Connection dropped or EOS");
      }
    } 

    else
    {
      // Unknown/unclassified error: log only; do not change pacing.
      if (probing) {
        probing       = false;
        sendInterval  = lkgInterval; // drop probe only
        lkgFailStreak = 0;
        if (DEBUG_LEVEL >= INFO) {
          Serial.printf("Unclassified issue %u (%s) while probing: revert to LKG=%u\r\n", code, codeName(code), sendInterval);
        }
      } else {
        if (DEBUG_LEVEL >= WARNING) {
          Serial.printf("Unclassified issue %u (%s) (no interval change)\r\n", code, codeName(code));
      }
      }
    }
  }

  // Peer subscribed to notifications/indications
  void onSubscribe(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo, uint16_t subValue) override {
    clientSubscribed = (bool)(subValue & 0x0001); // enable send data in main loop

    if (DEBUG_LEVEL >= INFO) {
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
      }
    } 

  } transmitterCallBacks;

// --------------------------------
// GAP Callbacks
// --------------------------------

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
      if (DEBUG_LEVEL >= INFO) {
        Serial.printf("DLE updated: tx=%u octets / %u ll time µs, rx =%u octets / ll time %u µs, tx chunk size=%u, min send interval=%u\r\n",
                      g_ll_tx_octets, g_ll_tx_time_us, g_ll_rx_octets, g_ll_rx_time_us, 
                      txChunkSize, minSendIntervalUs);
      }
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
      if (DEBUG_LEVEL >= INFO) {
        Serial.printf("PHY updated: tx=%u rx=%u %s ll time=%u, tx chunk size=%u, min send interval=%u\r\n",
                      p.tx_phy, p.rx_phy,
                      phyIsCODED ? (codedScheme==2 ? "CODED(S2)" : "CODED(S8)") :
                                   (phyIs2M ? "2M" : "1M"),
                      llTimeUS, txChunkSize, minSendIntervalUs);
      }

      break;
    }    

    default:
      break;
  }
  return 0;
}


class LineReader {
public:
  explicit LineReader(Stream& s): s_(s) {}
  // Non-blocking: returns true when a full line (CR, LF, or CRLF) is ready
  bool poll(char* out, size_t maxLen) {
    while (s_.available()) {
      int c = s_.read();
      if (c < 0) break;
      if (c == '\r') { sawCR_ = true; continue; }
      if (c == '\n' || sawCR_) {
        buf_[min(idx_, maxBuf_-1)] = '\0';
        strncpy(out, buf_, maxLen);
        idx_ = 0; sawCR_ = false;
        return true;
      }
      if (idx_ < maxBuf_-1) buf_[idx_++] = (char)c;
    }
    return false;
  }
private:
  Stream& s_;
  static constexpr size_t maxBuf_ = 128;
  char   buf_[maxBuf_]{};
  size_t idx_ = 0;
  bool   sawCR_ = false;
};

// In BLE onWrite callback (RX):
void BlePort::onWrite(NimBLECharacteristic* ch) {
  auto& data = ch->getValue();                 // std::string view
  driver.onTransportRx((uint8_t*)data.data(), data.size());
}

// In BLE notify path (TX):
bool DriverStream::transportSend(const uint8_t* p, size_t n) {
  // setValue(p, n); return characteristic->notify();
  // Return true on success; on failure set a transport error code if you want finer control
}
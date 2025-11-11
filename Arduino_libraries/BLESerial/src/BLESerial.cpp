// ****************************************************************************************************
// BLE Serial Library 
//
// BLE Serial Communication for Arduino using NimBLE
// This creates a Nordic UART Service (NUS) allowing to send and receive serial data over BLE
// in a similar fashion as Serial.print, Serial.read, etc.
// ****************************************************************************************************
// This code is maintained by
// Urs Utzinger, November 2025
// ****************************************************************************************************
#include <algorithm>
#include <cctype>
#include "BLESerial.h"

#ifdef ARDUINO_ARCH_ESP32
// forward declaration so we can pass it to xTaskCreatePinnedToCore
static void RssiTask(void* arg);
TaskHandle_t BLESerial::rssiTaskHandle = nullptr;
TaskHandle_t BLESerial::txTaskHandle   = nullptr;
#endif

BLESerial* BLESerial::active = nullptr;

bool BLESerial::begin(Mode newMode, const char* deviceName, bool newSecure) {
  // Minimal init; full feature set can be added incrementally
  mode   = newMode;
  secure = newSecure;
  logLevel = INFO;

  BLESerial::active = this;  // allow static GAP handler to reach our instance

  // Decide desired link behavior from mode (desired != current)
  int8_t dBmAdv, dBmScan, dBmConn;

  switch (mode) {
    case Mode::Fast:
      mtu                = BLE_SERIAL_MAX_MTU;
      desiredPhyMask     = BLE_GAP_LE_PHY_2MASK;
      desiredCodedScheme = 0;
      desiredLlOctets    = LL_MAX_OCTETS;
      desiredLlTimeUs    = LL_DEFAULT_TIME_US;
      dBmAdv             = BLE_TX_DBP9;
      dBmScan            = BLE_TX_DBP9;
      dBmConn            = BLE_TX_DBP9;
      break;
    case Mode::LowPower:
      mtu                = BLE_SERIAL_MIN_MTU;
      desiredPhyMask     = BLE_GAP_LE_PHY_1MASK;
      desiredCodedScheme = 0;
      desiredLlOctets    = LL_MAX_OCTETS;
      desiredLlTimeUs    = LL_DEFAULT_TIME_US;
      dBmAdv             = BLE_TX_DBN9;
      dBmScan            = BLE_TX_DBN9;
      dBmConn            = BLE_TX_DBN6;
      break;
    case Mode::LongRange:
      mtu                = BLE_SERIAL_DEFAULT_MTU;
      desiredPhyMask     = BLE_GAP_LE_PHY_CODED_MASK;
      desiredCodedScheme = 2;
      desiredLlOctets    = LL_MAX_OCTETS;
      desiredLlTimeUs    = LL_DEFAULT_TIME_US;
      dBmAdv             = BLE_TX_DBP9;
      dBmScan            = BLE_TX_DBP9;
      dBmConn            = BLE_TX_DBP9;
      break;
    case Mode::Balanced:
    default:
      mtu                = BLE_SERIAL_DEFAULT_MTU;
      desiredPhyMask     = BLE_GAP_LE_PHY_1MASK;
      desiredCodedScheme = 0;
      desiredLlOctets    = LL_MAX_OCTETS;
      desiredLlTimeUs    = LL_DEFAULT_TIME_US;
      dBmAdv             = BLE_TX_DBN6;
      dBmScan            = BLE_TX_DBN3;
      dBmConn            = BLE_TX_DB0;
      break;
  }

  // Current, negotiated state is unknown pre-connection
  phyIs2M                 = false;
  phyIsCoded              = false;
  codedScheme             = 0;

  // BLE: init stack, create service, start adv; UART: config UART  
  NimBLEDevice::init(deviceName);
  NimBLEDevice::setCustomGapHandler(&BLESerial::gapEventHandler);
  NimBLEDevice::setMTU(mtu);
  NimBLEDevice::setMaxConnections(1);
  NimBLEDevice::setPower(dBmAdv,  PWR_ADV);
  NimBLEDevice::setPower(dBmScan, PWR_SCAN);
  NimBLEDevice::setPower(dBmConn, PWR_CONN);

  powerAdv  = NimBLEDevice::getPower(PWR_ADV);
  powerScan = NimBLEDevice::getPower(PWR_SCAN);
  powerConn = NimBLEDevice::getPower(PWR_CONN);

  // Address type
  // Options:
  // BLE_OWN_ADDR_PUBLIC Use the chip’s factory-burned IEEE MAC (the “public” address). Stable, globally unique.
  // BLE_OWN_ADDR_RANDOM Use the static random address you’ve set with ble_hs_id_set_rnd(). Stable across reboots only if you persist it yourself.
  // BLE_OWN_ADDR_RPA_PUBLIC_DEFAULT Use a Resolvable Private Address (RPA) derived from your public identity. This gives privacy (rotating address) but still resolvable if the peer has your IRK (bonded).
  // BLE_OWN_ADDR_RPA_RANDODEFAULT Use an RPA derived from your random static identity.

  if (secure) {
      NimBLEDevice::setOwnAddrType(BLE_OWN_ADDR_RPA_PUBLIC_DEFAULT);
      // your client will need to reacquire the address each time you want to connect
  } else {
      NimBLEDevice::setOwnAddrType(BLE_OWN_ADDR_PUBLIC);
      // address remains static and can be reused by the client
  }

  NimBLEDevice::setDefaultPhy(desiredPhyMask, desiredPhyMask);

  // Suggested default data length: use safe, spec-aligned maximum (not dynamic). Typical: 251 octets, LL_DEFAULT_TIME_US µs.
  ble_gap_write_sugg_def_data_len(desiredLlOctets, desiredLlTimeUs);
  // Keep llOctets/llTimeUs as conservative defaults until connection/DLE updates event arrives.
  llOctets = desiredLlOctets;
  llTimeUs = desiredLlTimeUs;

  // Security posture
  if (secure) {
      NimBLEDevice::setSecurityAuth(/*bonding*/true, /*mitm*/true, /*sc*/true);
      // Optional: set a fixed passkey with 
      //    NimBLEDevice::setSecurityPasskey(...)
      // IO capability: display only (ESP_IO_CAP_OUT)
      NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);  /** Display only passkey */
      // Key distribution (init/rsp) ~ ESP_BLE_SSET_INIT_KEY / SET_RSP_KEY
      NimBLEDevice::setSecurityInitKey(KEYDIST_ENC | KEYDIST_ID);
      NimBLEDevice::setSecurityRespKey(KEYDIST_ENC | KEYDIST_ID);
  } else {
      NimBLEDevice::setSecurityAuth(/*bonding*/false, /*mitm*/false, /*sc*/false); // no pairing needed
  }

  // Create server and service
  server = NimBLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks(this));
  service = server->createService(BLE_SERIAL_SERVICE_UUID);

  // Characteristics
  if (secure) {
      rxChar = service->createCharacteristic(
          BLE_SERIAL_CHARACTERISTIC_UUID_RX,
          NIMBLE_PROPERTY::WRITE | 
          NIMBLE_PROPERTY::WRITE_NR |      // write without response (faster)
          NIMBLE_PROPERTY::WRITE_ENC       // require encryption for writes (triggers pairing)
      );

      txChar = service->createCharacteristic(
          BLE_SERIAL_CHARACTERISTIC_UUID_TX,
          NIMBLE_PROPERTY::NOTIFY |
          NIMBLE_PROPERTY::READ_ENC       // require encryption for notify subscription
      );
  } else {
      rxChar = service->createCharacteristic(
          BLE_SERIAL_CHARACTERISTIC_UUID_RX,
          NIMBLE_PROPERTY::WRITE |
          NIMBLE_PROPERTY::WRITE_NR       // write without response (faster)
      );
      txChar = service->createCharacteristic(
          BLE_SERIAL_CHARACTERISTIC_UUID_TX,
          NIMBLE_PROPERTY::NOTIFY
      );
  }

  // Set attribute max length for RX/TX characteristics.
  // GATT attribute values are limited to 512 bytes by spec; ATT payload per PDU is MTU-3.
  // Use min(512, mtu-3) as initial cap so we can accept/emit up to negotiated MTU later.
  {
  uint16_t attMax = (mtu > 3) ? (uint16_t)std::min<uint16_t>(BLE_SERIAL_MAX_GATT, (uint16_t)(mtu - 3)) : (uint16_t)20;
  if (rxChar) rxChar->setMaxLen(attMax);
  if (txChar) txChar->setMaxLen(attMax);
  }

  // Callbacks
  txChar->setCallbacks(new TxCallbacks(this));
  rxChar->setCallbacks(new RxCallbacks(this));

  // Start the service
  service->start();

  // Primary Advertising: Flags and Service UUID
  advertising = NimBLEDevice::getAdvertising();
  if (mode == Mode::Fast) {
      advertising->setMinInterval(0x00A0); // 100 ms
      advertising->setMaxInterval(0x00F0); // 150 ms
  } else if (mode == Mode::LowPower) {
      advertising->setMinInterval(0x0640); // 1.0 s
      advertising->setMaxInterval(0x0C80); // 2.0 s
  } else { // Long range or Balanced
      advertising->setMinInterval(0x0320); // 0.5 s
      advertising->setMaxInterval(0x0640); // 1.0 s
  }
  // Flags are recommended in primary ADV (general discoverable, no BR/EDR)
  advData.setFlags(BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP);
  // Put service UUID in the primary ADV
  advData.addServiceUUID(BLE_SERIAL_SERVICE_UUID);   
  // If you have multiple services, call addServiceUUID(...) for each:
  // advData.addServiceUUID(NimBLEUUID(SERVICE_UUID_2));
  // Apply primary ADV payload (replaces any previous content)
  advData.addTxPower();
  // Scan Response: put the full name here (saves ADV space)
  scanData.setName(deviceName);
  scanData.setAppearance(BLE_SERIAL_APPEARANCE);
  const uint8_t mfg[] = { 0xFF, 0xFF }; // 0xFFFF + 27 bytes max
  scanData.setManufacturerData(std::string((const char*)mfg, sizeof(mfg)));  
  advertising->setAdvertisementData(advData);
  advertising->setScanResponseData(scanData);
  advertising->start();

  // Initialize watermarks
  highWater = (txBuf.capacity() * 3) / 4;
  lowWater  = updateLowWaterMark(txChunkSize);

  #ifdef ARDUINO_ARCH_ESP32
    // Create RSSI task (suspended until connect)
    if (!BLESerial::rssiTaskHandle) {
      xTaskCreatePinnedToCore(
        RssiTask,
        "RssiTask",
        3072,
        this,
        2,
        &BLESerial::rssiTaskHandle,
        1);
      vTaskSuspend(BLESerial::rssiTaskHandle);
    }
    // Always create TX pump task once; it remains mostly idle until notifications
    startTxTask(); // creates if absent; does NOT actively pump until notified
  #endif

  // Print MAC (purely informational)
  deviceMac = NimBLEDevice::getAddress().toString();
  for (char &c : deviceMac) c = (char)toupper((unsigned char)c);
  if (logLevel >= INFO) {  
      Serial.printf("MAC: %s\r\n", deviceMac.c_str());
  }

  randomSeed(analogRead(0));
  return true;
}

void BLESerial::end() {
  // Stop RSSI task first (ESP32)
  #ifdef ARDUINO_ARCH_ESP32
    if (BLESerial::rssiTaskHandle) {
      vTaskSuspend(BLESerial::rssiTaskHandle);
      vTaskDelete(BLESerial::rssiTaskHandle);
      BLESerial::rssiTaskHandle = nullptr;
    }
    // Stop TX pump task (if running)
    stopTxTask();
  #endif

  // Stop advertising
  if (advertising) {
    advertising->stop();
  }

  // Disconnect active client (if any)
  if (server && connHandle != BLE_HS_CONN_HANDLE_NONE) {
    server->disconnect(connHandle);
    connHandle = BLE_HS_CONN_HANDLE_NONE;
  }

  // Stop service (characteristics live under service)
  if (service) {
    service->stop();
  }

  // Release NimBLE resources (frees server/service/chars/adv objects)
  NimBLEDevice::setCustomGapHandler(nullptr);
  NimBLEDevice::deinit(true);

  // Clear pointers after deinit
  server       = nullptr;
  service      = nullptr;
  rxChar       = nullptr;
  txChar       = nullptr;
  advertising  = nullptr;

  // Reset link/PHY state
  deviceConnected   = false;
  clientSubscribed  = false;
  phyIs2M           = false;
  phyIsCoded        = false;
  codedScheme       = 0;
  desiredCodedScheme= 0;
  connHandle        = BLE_HS_CONN_HANDLE_NONE;

  // Reset pacing/timing
  txOk              = false;
  pendingLen        = 0;
  lastTxUs          = 0;
  llOctets          = LL_MAX_OCTETS;
  llTimeUs          = LL_DEFAULT_TIME_US;
  recomputeTxTiming();
  sendIntervalUs    = MAX_SEND_INTERVAL_US;
  lkgIntervalUs     = sendIntervalUs;
  resetTxRamp(true);

  // Drain buffers
  // TX: drop any queued bytes
  size_t txUsed = txBuf.available();
  if (txUsed) txBuf.consume(txUsed);

  // RX: pop until empty
  uint8_t b;
  while (rxBuf.pop(b) == 1) { /* discard */ }

  // Reset stats/counters
  bytesRx          = 0;
  bytesTx          = 0;
  rxDrops          = 0;
  mtuRetryCount    = 0;
  badDataRetries   = 0;

  // Reset watermarks
  highWater = (txBuf.capacity() * 3) / 4;
  lowWater  = updateLowWaterMark(txChunkSize);

  // Detach active instance pointer
  if (BLESerial::active == this) {
      BLESerial::active = nullptr;
  }

  if (logLevel >= INFO) {
      Serial.println("BLESerial ended: BLE deinitialized and resources released.");
  }  
}

int BLESerial::available() {
  return (int)rxBuf.available();
}

int BLESerial::read() {
  // Assumes RingBuffer::pop() returns int (or -1 when empty)
  uint8_t b = 0;
  if (rxBuf.pop(b) == 1) return (int)b;
  return -1;
}

// Helper to read up to n bytes into dst using RingBuffer::pop(T*, n)
int BLESerial::read(uint8_t* dst, size_t n) {
  if (!dst || n == 0) return 0;
  return (int)rxBuf.pop(dst, n);
}

// Implement Stream::peek() using RingBuffer::peek(T&)
int BLESerial::peek() {
  uint8_t b = 0;
  if (rxBuf.peek(b) == 1) return (int)b;
  return -1;
}

// Helper to peak up to n bytes into dst using RingBuffer::peek(T*, n)
int BLESerial::peek(uint8_t* dst, size_t n) {
  if (!dst || n == 0) return 0;
  return (int)rxBuf.peek(dst, n);
}

void BLESerial::flush() {
  // Non-blocking drain: pump until empty or link busy
  while (txBuf.available() > 0) {
    pumpTx();
    delay(1);
  }
}

size_t BLESerial::write(uint8_t b) {
  size_t pushed = txBuf.push(&b, 1, false);
  #ifdef ARDUINO_ARCH_ESP32
    if (pushed && pumpMode == PumpMode::Task && deviceConnected && clientSubscribed) wakeTxTask();
  #endif
  return pushed;
}

size_t BLESerial::write(const uint8_t* p, size_t n) {
  size_t pushed = txBuf.push(p, n, false);
  #ifdef ARDUINO_ARCH_ESP32
    if (pushed && pumpMode == PumpMode::Task && deviceConnected && clientSubscribed) wakeTxTask();
  #endif
  return pushed;
}

size_t BLESerial::writeTimeout(const uint8_t* p, size_t n, uint32_t timeoutMs) {
  if (!p || n == 0) return 0;
  const uint32_t endAt = millis() + timeoutMs;
  size_t pushed = 0;
  while (pushed < n) {
    size_t s = txBuf.push(p + pushed, n - pushed, false);
    pushed += s;
    if (pushed == n) break;
    #ifdef ARDUINO_ARCH_ESP32
      if (pumpMode == PumpMode::Polling) {
        pumpTx();
      } else if (deviceConnected && clientSubscribed) {
        wakeTxTask();
      }
    #else
      pumpTx();
    #endif
    if ((int32_t)(millis() - endAt) >= 0) break; // timeout
    delay(1);
  }
  return pushed;
}

void BLESerial::update() {
  #ifdef ARDUINO_ARCH_ESP32
    // Use portable polling pump and not ESP32 FreeRTOS task
    if (pumpMode == PumpMode::Polling) {
      pumpTx();
    } 
  #else
    // Portable BLE transmit data (ESP32 uses FreeRTOS task)
    pumpTx();
    // Portable RSSI polling (ESP32 uses FreeRTOS task)
    if (deviceConnected && connHandle != BLE_HS_CONN_HANDLE_NONE) {
      uint32_t now = millis();
      if ((now - lastRssiMs) >= RSSI_INTERVAL_MS) {
        adjustLink();
      }
    }
  #endif  
}

void BLESerial::checkTxSuccess() {
  if (!deviceConnected || !clientSubscribed || txChar == nullptr) return;
  // If previous notify succeeded, consume the staged bytes now
  // txOk is set true if callback onStatus indicates success
  TX_CRITICAL_ENTER();
  if (txOk && pendingLen > 0) {
    txBuf.consume(pendingLen);
    bytesTx += pendingLen;
    txOk = false;
    pendingLen = 0;
    size_t used = txBuf.available();
    if (used <= lowWater) {
      txAvailable = true;
    }
  } // end if previous send was success
  TX_CRITICAL_EXIT();
}

bool BLESerial::stageTx() {
  // Nothing staged? Stage a new chunk from tx buffer
  if (pendingLen == 0) {
      const size_t avail = txBuf.available();
      if (!avail) return false;

      size_t toStage = txChunkSize <= avail ? txChunkSize : avail;
      // Peek without consuming so we can retry on failures; consume after success in onStatus path
      TX_CRITICAL_ENTER();
      pendingLen = txBuf.peek(pending, toStage);
      TX_CRITICAL_EXIT();
      if (pendingLen == 0) return false;
      // Indicate that producer should not push data into txBuf when previous sending is still pending
      txAvailable = false;
  } // end obtain next chunk

  // Send the staged chunk
  if (pendingLen && pendingLen <= txChunkSize) {
    TX_CRITICAL_ENTER();
    txOk = false; // will be set true on success by TxCallbacks::onStatus
    TX_CRITICAL_EXIT();
    txChar->setValue(reinterpret_cast<const uint8_t*>(pending), pendingLen);
    txChar->notify();
    return true;
  } else if (pendingLen > txChunkSize) {
    // staged larger than current chunk after renegotiation; drop and retry
    TX_CRITICAL_ENTER();
    pendingLen = 0;
    TX_CRITICAL_EXIT();
    if (txBuf.available() <= lowWater) txAvailable = true;
    return false;
  } // end sending chunk
  return false;
} // end stageTx

void BLESerial::pumpTx() {
  // Check if previous TX succeeded
  checkTxSuccess();
  // Time to send next chunk?
  uint32_t now = micros();
  if ((uint32_t)(now - lastTxUs) < sendIntervalUs) return;
  // Try to stage and send next chunk
  bool staged = stageTx();
  if (staged) lastTxUs = now;
} // end pumpTx

uint16_t BLESerial::computeTxChunkSize(uint16_t mtuVal,
                                       uint16_t llOctets,
                                       Mode modeVal,
                                       bool encrypted)
{

  // Base payload is MTU-3 (ATT header). For FAST mode, allow up to
  // 2 LL PDUs to reduce per-notify overhead; otherwise keep within a single LL PDU.
  // MIC is 4 when encryption is on, otherwise 0. MIC reduces available payload.

  // Max payload that fits in ONE LL PDU carrying an L2CAP SDU with ATT notify:
  // onePduMax = llOctets - (BLE_SERIAL_L2CAP_HDR_BYTES + BLE_SERIAL_ATT_HDR_BYTES + MIC)1
  //           = llOctets - 7 (-4 if encrypted)

  // ATT value limit from MTU (exclude 3B ATT value header)
  uint16_t attPayload = 0u;
  if (mtuVal > BLE_SERIAL_ATT_HDR_BYTES ) {
    attPayload = static_cast<uint16_t>(mtuVal - BLE_SERIAL_ATT_HDR_BYTES);
  }

  // Spec cap (common practice): 512 max attribute value
  if (attPayload > BLE_SERIAL_MAX_GATT) {
    attPayload = BLE_SERIAL_MAX_GATT;
  }

  const uint16_t hdrBytes = BLE_SERIAL_L2CAP_HDR_BYTES + BLE_SERIAL_ATT_HDR_BYTES; // 7
  const uint16_t micPerPdu = 0u;
  if (encrypted){
      micPerPdu = BLE_SERIAL_ENCRYPT_BYTES; // 4
  }

  // Max payload that fits in ONE LL PDU:
  //   fragment_len1_max = llOctets - 7 - MIC
  uint16_t onePduMax = 0u;
  if (llOctets > hdrBytes + micPerPdu) {
      onePduMax = static_cast<uint16_t>(llOctets - hdrBytes - micPerPdu);
  }

  // Max payload that fits in TWO LL PDUs:
  //   total_fragments_max = (llOctets - MIC) + (llOctets - MIC) - 7
  //                       = 2*llOctets - 7 - 2*MIC
  uint16_t twoPduMax = onePduMax;
  if (llOctets > (hdrBytes + micPerPdu)) {
      uint32_t total = 2u * llOctets;
      if (total > (hdrBytes + 2u * micPerPdu)) {
          uint32_t usable = total - hdrBytes - 2u * micPerPdu;
          if (usable > 0xFFFFu) usable = 0xFFFFu;
          twoPduMax = static_cast<uint16_t>(usable);
      }
  }

  // Choose limit by mode
  uint16_t limit = (modeVal == Mode::Fast) ? twoPduMax : onePduMax;

  // Cap by ATT MTU-derived payload
  if (attPayload < limit) limit = attPayload;

  // Keep a practical floor (legacy 1-PDU safe)
  if (limit < 20) limit = 20;

  return limit;
}


uint32_t BLESerial::computeMinSendIntervalUs(uint16_t chunkSize,
                                             uint16_t llOctets,
                                             uint16_t llTimeUsVal,
                                             Mode modeVal,
                                             bool encrypted)
{
    // mic per LL PDU (inside L)
    const uint16_t mic = 0u;
    if (encrypted) {
        const uint16_t mic = BLE_SERIAL_ENCRYPT_BYTES;
    }
    // Effective per-PDU capacity for SDU bytes
    const uint16_t M = 0;
    if (llOctets > mic) {
      M = static_cast<uint16_t>(llOctets - mic);
    }

    // If M is zero (shouldn't happen), bail out with a safe large interval
    if (M == 0) return 1000000u;

    // Number of LL PDUs required: N = ceil((chunk + 7) / (llOctets - mic))
    const uint32_t numer    = static_cast<uint32_t>(chunkSize) + BLE_SERIAL_ATT_HDR_BYTES + BLE_SERIAL_L2CAP_HDR_BYTES;
    const uint16_t numLLPdu = static_cast<uint16_t>((numer + M - 1u) / M);

    // Guard factor by mode
    uint32_t guardNum = 110; // +10%
    uint32_t guardDen = 100;
    switch (modeVal) {
        case Mode::Fast:       guardNum = 103; break; // +3%
        case Mode::Balanced:   guardNum = 108; break; // +8%
        case Mode::LongRange:  guardNum = 115; break; // +15%
        default:               guardNum = 112; break; // LowPower/other: +12%
    }

    // Conservative interval: assume each fragment costs ~llTimeUsVal
    return static_cast<uint32_t>(numLLPdu) * llTimeUsVal * guardNum / guardDen;
}

size_t BLESerial::updateLowWaterMark(size_t chunkSize) {
  size_t lw = 2 * chunkSize;                 // up to two outbound packets buffered
  const size_t cap25 = txBuf.capacity() / 4; // cap at 25% of buffer
  if (lw > cap25) lw = cap25;
  if (lw < chunkSize) lw = chunkSize;        // never below one chunk
  return lw;
}

void BLESerial::resetTxRamp(bool forceToMin) {
  probing             = false;
  probeSuccesses      = 0;
  probeFailures       = 0;
  lkgFailStreak       = 0;
  recentlyBackedOff   = false;
  cooldownSuccess     = 0;
  successStreak       = 0;

  // Clamp the active interval to the current floor if requested or out of bounds
  if (forceToMin || sendIntervalUs == 0 || sendIntervalUs < minSendIntervalUs) {
      sendIntervalUs = minSendIntervalUs;
  }
  lkgIntervalUs = sendIntervalUs;

}

void BLESerial::recomputeTxTiming() {
  // Recompute chunk and floor based on current negotiated parameters
  uint16_t prevChunk = txChunkSize;
  uint32_t prevSend  = sendIntervalUs;
  txChunkSize       = computeTxChunkSize(mtu, llOctets, mode, secure);
  minSendIntervalUs = computeMinSendIntervalUs(txChunkSize, llOctets, llTimeUs, mode, secure);

  // Keep current pacing at or above the floor
  if (sendIntervalUs < minSendIntervalUs) {
      sendIntervalUs = minSendIntervalUs;
  }

  // Refresh watermarks
  lowWater = updateLowWaterMark(static_cast<size_t>(txChunkSize));

  // Keep LKG coherent with the new floor
  if (lkgIntervalUs == 0 || lkgIntervalUs < minSendIntervalUs) {
      lkgIntervalUs = sendIntervalUs;
  }
  if (!probing && lkgIntervalUs > sendIntervalUs) {
      lkgIntervalUs = sendIntervalUs;
  }

  size_t used = txBuf.available();
  if (pendingLen == 0 && used <= lowWater) {
    txAvailable = true;
  }

  // Reset probing/backoff state to the new floor
  resetTxRamp(true);

  // Emit pacing change if values changed
  if (onPacingChanged && (prevChunk != txChunkSize || prevSend != sendIntervalUs)) {
    firePacingChanged(PacingReason::Recompute);
  }
}

/*
computeLlPduTimeUs:

Compute the time to transmit a Link Layer PDU of given octet length on
the selected PHY.

Let L = Octet Length (bytes) 
Max octet length = 251 bytes

payload = L - 4 (L2CAP) - 3 (ATT) - (4 (MIC) if encrypted) in bytes

LE 1M:
t_us = ( Preamble(8) + AA(32) + LLhdr(16) + 8*L + CRC(24) ) / 1 + IFS(150)
     = ( 80 + 8*L ) + 150

LE 2M:
t_us = ( Preamble(16) + AA(32) + LLhdr(16) + 8*L + CRC(24) ) / 2 + 150
     = ( 88 + 8*L ) / 2 + 150
     = 44 + 4*L + 150

LE  Coded:
t_us = Preamble(80)
     + AA(32)*8
     + (CI+TERM1)(5)*8
     + LLhdr(16)*8
     + (8*L + CRC(24))*S
     + IFS(150)

     = 504 + S*(8*L + 24) + 150

if L=251 and
1M: t = 80 + 8*251 + 150 = 80 + 2008 + 150                    = 2238 µs
2M: t = (88 + 8*251)/2 + 150 = 2096/2 + 150 = 1048 + 150      = 1198 µs
Coded S=2: t = 504 + 2*(8*251 + 24) + 150 = 504 + 4064 + 150  = 4718 µs
Coded S=8: t = 504 + 8*(8*251 + 24) + 150 = 504 + 16256 + 150 = 16910 µs

*/

uint32_t BLESerial::computeLlPduTimeUs(uint16_t llOctets,
                                       bool phy2M,
                                       bool phyCoded,
                                       uint8_t codedScheme) {
 
  // Inter-frame space (us)
  constexpr uint32_t IFS_US = 150;

  if (!phyCoded) {
    // ---------- Uncoded PHY ----------
    // LE 1M: t = 80 + 8*L + 150
    // LE 2M: t = (88 + 8*L)/2 + 150
    if (phy2M) {
      return ((88u + 8u * llOctets) / 2u) + IFS_US;
    } else {
      return (80u + 8u * llOctets) + IFS_US;
    }
  } else {
    // ---------- LE Coded PHY ----------
    // Access Address, CI/TERM1, and LL header are always S=8 coded.
    // Payload and CRC are coded at S (2 or 8).
    // t = 504 + S*(8*L + 24) + 150   [us], at 1 Msym/s
    const uint32_t S = (codedScheme == 2) ? 2u : 8u;
    return 504u + S * (8u * llOctets + 24u) + IFS_US;
  }
}

bool BLESerial::requestMTU(uint16_t newMtu) {
  if (newMtu < BLE_SERIAL_MIN_MTU) newMtu = BLE_SERIAL_MIN_MTU;
  if (newMtu > BLE_SERIAL_MAX_MTU) newMtu = BLE_SERIAL_MAX_MTU;

  // Remember desired MTU; actual will be delivered in onMTUChange after negotiation.
  mtu = newMtu;
  NimBLEDevice::setMTU(mtu);

  // Adjust attribute max lengths now to avoid EAPP on setValue/write.
  const uint16_t attMax = (mtu > BLE_SERIAL_ATT_HDR_BYTES)
      ? (uint16_t)std::min<int>(BLE_SERIAL_MAX_GATT, (int)mtu - BLE_SERIAL_ATT_HDR_BYTES)
      : (uint16_t)20;

  if (txChar) txChar->setMaxLen(attMax);
  if (rxChar) rxChar->setMaxLen(attMax);

  // Recompute local chunking against the requested MTU; onMTUChange will refine later.
  recomputeTxTiming();
  return true;
}

// Emit a pacing/backoff change event
void BLESerial::firePacingChanged(PacingReason r) {
  if (!onPacingChanged) return;
  PacingInfo info{sendIntervalUs, minSendIntervalUs, lkgIntervalUs, txChunkSize, mtu, llOctets, llTimeUs, probing};
  onPacingChanged(info, r);
  #ifdef ARDUINO_ARCH_ESP32
    if (pumpMode == PumpMode::Task) wakeTxTask();
  #endif
}

// ===============================================================================================================================================================
// RSSI monitor task: polls RSSI and adjusts PHY with hysteresis
// TX task: lightweight task to pump TX using direct-to-task notifications
// ===============================================================================================================================================================

#ifdef ARDUINO_ARCH_ESP32

static void RssiTask(void* arg) {
  BLESerial* self = static_cast<BLESerial*>(arg);
  for (;;) {
    if (self && self->deviceConnected && self->connHandle != BLE_HS_CONN_HANDLE_NONE) {
      self->adjustLink();
    }
    vTaskDelay(pdMS_TO_TICKS(RSSI_INTERVAL_MS));
  }
}

// Lightweight TX pump task using direct-to-task notifications for efficient wakeups.
static void pumpTxTask(void* arg) {
  BLESerial* self = static_cast<BLESerial*>(arg);
  for (;;) {
    if (!self) { 
      vTaskDelay(pdMS_TO_TICKS(200)); 
      continue; 
    }

    // Block until notified or timeout for periodic check
    if (self->deviceConnected && self->clientSubscribed) {
      ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(5));
    } else {
      ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(200));
    }

    if (!(self->deviceConnected && self->clientSubscribed)) {
      continue; // no active link
    }

    // Drain while data/pending
    while (self->deviceConnected && self->clientSubscribed) {
      self->checkTxSuccess();

      // If nothing staged and buffer empty, exit to wait for next notify
      if (self->txBuf.available() == 0 && self->pendingLen == 0) {
        break;
      }

      // Respect sendIntervalUs
      uint32_t now = micros();
      uint32_t elapsed = (uint32_t)(now - self->lastTxUs);

      if (elapsed < self->sendIntervalUs) {
        uint32_t remainUs = self->sendIntervalUs - elapsed;
        if (remainUs < TASK_DELAY_THRESHOLD_US) {
          // Sub-ms gap: micro sleep (cooperative)
          delayMicroseconds(remainUs);
        } else {
          // Convert to ticks (ceil)
          vTaskDelay(pdMS_TO_TICKS((remainUs + 999) / 1000));
        }
        continue; // recheck after wait
      }

      // Stage and Send
      if (!self->stageTx()) {
        // Staging failed (renegotiation); short yield then retry
        taskYIELD();
        continue;
      }
      self->lastTxUs = micros();

      // Optional cooperative yield after each send (remove if not needed)
      // taskYIELD();
    } // while connected/subscribed
  } // for (;;
} // pumpTxTask

void BLESerial::setPumpMode(PumpMode m) {
  if (pumpMode == m) return;
  pumpMode = m;
  if (pumpMode == PumpMode::Task) {
    startTxTask();
  } else {
    stopTxTask();
  }
}

void BLESerial::startTxTask() {
  if (txTaskHandle) return;
  BaseType_t rc = xTaskCreatePinnedToCore(
    pumpTxTask,
    "BLETxPump",
    2304,
    this,
    1,
    &txTaskHandle,
    1
  );
  if (rc != pdPASS) {
    txTaskHandle = nullptr;
    if (logLevel >= WARNING) Serial.println("BLESerial: TX task creation failed; staying in polling mode.");
  } else {
    // Keep task in a mostly idle state until notified or connected
    vTaskSuspend(txTaskHandle); // begin asleep as requested
    if (logLevel >= INFO) Serial.println("BLESerial: TX task created (suspended).");
  }
}

void BLESerial::stopTxTask() {
  if (!txTaskHandle) return;
  TaskHandle_t h = txTaskHandle;
  txTaskHandle = nullptr;
  vTaskDelete(h);
  if (logLevel >= INFO) Serial.println("BLESerial: TX task stopped.");
}

void BLESerial::wakeTxTask() {
  // Direct-to-task notification is very light-weight (few CPU cycles)
  if (txTaskHandle) {
    xTaskNotifyGive(txTaskHandle);
  }
}
#endif

/*
Adjust the link layer parameters (PHY, coded scheme) based on RSSI.

I believe this will not work as it would require disconnect and reconnect to change PHY
*/
void BLESerial::adjustLink() {

  if (!deviceConnected || connHandle == BLE_HS_CONN_HANDLE_NONE) return;

  lastRssiMs = millis();
  int8_t val = 0;
  if (ble_gap_conn_rssi(connHandle, &val) != 0) {
      return; // read failed; ignore
  }
  rssiRaw = val;
  // Simple EMA: weight new sample 1/5
  if (rssiAvg == 0) rssiAvg = rssiRaw;
  else rssiAvg = (int8_t)((4 * (int)rssiAvg + (int)rssiRaw) / 5);

  // Cooldown before any further link adaptation
  if ((millis() - lastRssiActionMs) < RSSI_ACTION_COOLDOWN_MS) return;

  // Decide target PHY / coded scheme
  uint8_t newDesiredCodedScheme = 0;
  uint8_t newDesiredPhyMask     = BLE_GAP_LE_PHY_1MASK;

  if (rssiAvg <= (RSSI_S8_THRESHOLD + RSSI_HYSTERESIS)) {
      newDesiredCodedScheme = 8;
  } else if (rssiAvg <= (RSSI_S2_THRESHOLD + RSSI_HYSTERESIS)) {
      newDesiredCodedScheme = 2;
  } else if (rssiAvg > (RSSI_FAST_THRESHOLD - RSSI_HYSTERESIS)) {
      newDesiredPhyMask = BLE_GAP_LE_PHY_2MASK;
  } // else stay 1M

  // Evaluate change necessity
  bool change = false;
  if (newDesiredCodedScheme > 0) {
      if (!phyIsCoded || codedScheme != newDesiredCodedScheme) {
          change = true;
      }
  } else if (newDesiredPhyMask == BLE_GAP_LE_PHY_2MASK) {
      if (!phyIs2M || phyIsCoded) {
          change = true;
      }
  } else {
      // Want 1M
      if (phyIs2M || phyIsCoded) {
          change = true;
      }
  }

  if (!change) return;

  // Apply PHY preference
  int rc = 0;
  desiredPhyMask     = (newDesiredCodedScheme > 0) ? BLE_GAP_LE_PHY_CODED_MASK : newDesiredPhyMask;
  desiredCodedScheme = newDesiredCodedScheme;
  if (desiredCodedScheme > 0) {
    // renegotiate coded PHY with selected scheme
    rc = ble_gap_set_prefered_le_phy(
          connHandle,
          BLE_GAP_LE_PHY_CODED_MASK,
          BLE_GAP_LE_PHY_CODED_MASK,
          (desiredCodedScheme == 2 ? BLE_GAP_LE_PHY_CODED_S2 : BLE_GAP_LE_PHY_CODED_S8)
    );
  } else if (desiredPhyMask == BLE_GAP_LE_PHY_2MASK) {
      desiredCodedScheme = 0;
      rc = ble_gap_set_prefered_le_phy(
          connHandle,
          BLE_GAP_LE_PHY_2MASK,
          BLE_GAP_LE_PHY_2MASK,
          desiredCodedScheme
      );
  } else { // 1M
      desiredCodedScheme = 0;
      rc = ble_gap_set_prefered_le_phy(
          connHandle,
          BLE_GAP_LE_PHY_1MASK,
          BLE_GAP_LE_PHY_1MASK,
          desiredCodedScheme
      );
  }

  if (rc == 0) {
      lastRssiActionMs = millis();
      if (logLevel >= INFO) {
        const char* target = (
          desiredCodedScheme ? (desiredCodedScheme==2 ? "CODED(S2)" : "CODED(S8)")
                             : (desiredPhyMask==BLE_GAP_LE_PHY_2MASK ? "2M" : "1M")
        );
        Serial.printf("RSSI adapt: avg=%d raw=%d -> %s\r\n", rssiAvg, rssiRaw, target);
      }
  } else {
      if (logLevel >= WARNING) {
        Serial.printf("PHY adapt failed (rc=%d)\r\n", rc);
      }
  }
} // end RSSI Link Adjust =======================================================================

// ===== Static GAP event handler ==============================================

int BLESerial::gapEventHandler(struct ble_gap_event* ev, void* /*arg*/) {

  if (!ev) return 0;
  BLESerial* inst = BLESerial::active;
  if (!inst) return 0;
  BLESerial& s = *inst;

  switch (ev->type) {
    // Fires whenever the controller updates data length for this link
    case BLE_GAP_EVENT_DATA_LEN_CHG: {
      const auto& p = ev->data_len_changed; // negotiated per-link values

      // Update LL payload/time; prefer tx metrics for our TX pacing
      // If you also store RX metrics, you can mirror them here.
      // Both names are set if present in your class; ignore if you only keep one.
      // Note: If your class only has llOctets (not llTxOctets), keep that one.
      s.llOctets = p.tx_octets;
      s.llTimeUs = p.tx_time;

      // Recompute pacing and reset soft state
      s.recomputeTxTiming();
      s.probing           = false;
      s.probeSuccesses    = 0;
      s.probeFailures     = 0;
      s.lkgFailStreak     = 0;
      s.recentlyBackedOff = false;
      s.cooldownSuccess   = 0;
      s.successStreak     = 0;
      s.lkgIntervalUs     = s.sendIntervalUs;
      s.badDataRetries    = 0;

      if (s.logLevel >= INFO) {
        Serial.printf("DLE updated: tx=%u octets / %u us, chunk=%u, minInterval=%u us\r\n",
                      (unsigned)s.llOctets, (unsigned)s.llTimeUs,
                      (unsigned)s.txChunkSize, (unsigned)s.minSendIntervalUs);
      }
      #ifdef ARDUINO_ARCH_ESP32
        if (s.pumpMode == PumpMode::Task) s.wakeTxTask();
      #endif
      break;
    }

    case BLE_GAP_EVENT_PHY_UPDATE_COMPLETE: {
      const auto& p = ev->phy_updated;

      s.phyIs2M    = (p.tx_phy == BLE_HCI_LE_PHY_2M)    && (p.rx_phy == BLE_HCI_LE_PHY_2M);
      s.phyIsCoded = (p.tx_phy == BLE_HCI_LE_PHY_CODED) && (p.rx_phy == BLE_HCI_LE_PHY_CODED);

      if (s.phyIsCoded) {
        s.codedScheme = (s.desiredCodedScheme == 2 ? 2 : 8);
      } else {
        s.codedScheme = 0;
      }

      // Update per-PDU time from PHY and recompute TX timing
      s.llTimeUs = s.computeLlPduTimeUs(s.llOctets, s.phyIs2M, s.phyIsCoded, s.codedScheme);

      s.recomputeTxTiming();

      // Reset soft state around probing/backoff on PHY change
      s.probing           = false;
      s.probeSuccesses    = 0;
      s.probeFailures     = 0;
      s.lkgFailStreak     = 0;
      s.recentlyBackedOff = false;
      s.cooldownSuccess   = 0;
      s.successStreak     = 0;
      s.lkgIntervalUs     = s.sendIntervalUs;
      s.badDataRetries    = 0;

      if (s.logLevel >= INFO) {
        Serial.printf("PHY updated: tx=%u rx=%u %s llTime=%u us, chunk=%u, minInterval=%u us\r\n",
          p.tx_phy, p.rx_phy,
          s.phyIsCoded ? (s.codedScheme==2 ? "CODED(S2)" : "CODED(S8)") :
                          (s.phyIs2M ? "2M" : "1M"),
          (unsigned)s.llTimeUs, (unsigned)s.txChunkSize, (unsigned)s.minSendIntervalUs);
      }
      #ifdef ARDUINO_ARCH_ESP32
        if (s.pumpMode == PumpMode::Task) s.wakeTxTask();
      #endif
      break;
    }

    case BLE_GAP_EVENT_ADV_COMPLETE: {
    // Resume advertising automatically when an advertising cycle completes
    NimBLEAdvertising* adv = NimBLEDevice::getAdvertising();
    if (adv) adv->start();
    break;
    }

  default:
    break;
  }
  return 0;
} // end gapEventHandler ========================================================================

// ===== Server Callbacks ================================================================
class BLESerial::ServerCallbacks : public NimBLEServerCallbacks {
public:
  explicit ServerCallbacks(BLESerial* owner) : owner(owner) {}

  void onConnect(NimBLEServer* srv, NimBLEConnInfo& connInfo) override {
    if (!owner) return;
    auto& s = *owner;

    s.deviceConnected = true;
    s.connHandle      = connInfo.getConnHandle();
    s.badDataRetries  = 0;


    uint16_t minItvl, maxItvl, latency, supTimeout;
    switch (s.mode) {
      case Mode::Fast:
        minItvl    = MIN_BLE_INTERVAL_SPEED;        maxItvl    = MAX_BLE_INTERVAL_SPEED;
        latency    = BLE_SLAVE_LATENCY_SPEED;       supTimeout = BLE_SUPERVISION_TIMEOUT_SPEED;
        break;
      case Mode::LowPower:
        minItvl    = MIN_BLE_INTERVAL_LOWPWR;       maxItvl    = MAX_BLE_INTERVAL_LOWPWR;
        latency    = BLE_SLAVE_LATENCY_LOWPWR;      supTimeout = BLE_SUPERVISION_TIMEOUT_LOWPWR;
        break;
      case Mode::LongRange:
        minItvl    = MIN_BLE_INTERVAL_LONG_RANGE;   maxItvl    = MAX_BLE_INTERVAL_LONG_RANGE;
        latency    = BLE_SLAVE_LATENCY_LONG_RANGE;  supTimeout = BLE_SUPERVISION_TIMEOUT_LONG_RANGE;
        break;
      case Mode::Balanced:
      default:
        minItvl    = MIN_BLE_INTERVAL_BALANCED;     maxItvl    = MAX_BLE_INTERVAL_BALANCED;
        latency    = BLE_SLAVE_LATENCY_BALANCED;    supTimeout = BLE_SUPERVISION_TIMEOUT_BALANCED;
        break;
    }
    (void)srv->updateConnParams(s.connHandle, minItvl, maxItvl, latency, supTimeout);

    // Ask for desired PHY per our current policy (adjustLink may change desired later)
    uint8_t codedSchemePref = 0;
    if (s.desiredPhyMask == BLE_GAP_LE_PHY_CODED_MASK && s.desiredCodedScheme) {
      codedSchemePref = (s.desiredCodedScheme == 2 ? BLE_GAP_LE_PHY_CODED_S2 : BLE_GAP_LE_PHY_CODED_S8);
    }
    (void)ble_gap_set_prefered_le_phy(s.connHandle, s.desiredPhyMask, s.desiredPhyMask, codedSchemePref);

    // Learn actual negotiated PHY
    uint8_t txPhy = 0, rxPhy = 0;
    if (ble_gap_read_le_phy(s.connHandle, &txPhy, &rxPhy) == 0) {
        s.phyIs2M    = (txPhy == BLE_HCI_LE_PHY_2M)    && (rxPhy == BLE_HCI_LE_PHY_2M);
        s.phyIsCoded = (txPhy == BLE_HCI_LE_PHY_CODED) && (rxPhy == BLE_HCI_LE_PHY_CODED);
        s.codedScheme = s.phyIsCoded ? (s.desiredCodedScheme ? s.desiredCodedScheme : 8) : 0; // best guess until event
      } else {
        // PHY read failed: fall back to 1M assumptions
        s.phyIs2M = false;
        s.phyIsCoded = false;
        s.codedScheme = 0;
      }

    s.desiredLLOctets = LL_MAX_OCTETS; // 251
    s.desiredLLTimeUs = s.computeLLPduTimeUs(s.desiredLLOctets, /*phy2M=*/s.phyIs2M, /*phyCoded=*/s.phyIsCoded, /*codedScheme=*/s.codedScheme);
    (void)ble_gap_set_data_len(s.connHandle, s.desiredLLOctets, s.desiredLLTimeUs);

    s.llOctets        = s.desiredLLOctets;
    s.llTimeUs        = s.desiredLLTimeUs;

    s.recomputeTxTiming(); // updates txChunkSize & minSendIntervalUs

    // Start security if enabled
    if (s.secure) {
        NimBLEDevice::startSecurity(s.connHandle);
    }

    // Resume RSSI task
    #ifdef ARDUINO_ARCH_ESP32
      if (BLESerial::rssiTaskHandle) vTaskResume(BLESerial::rssiTaskHandle);
      if (BLESerial::txTaskHandle)   vTaskResume(BLESerial::txTaskHandle);
    #endif

  if (s.logLevel >= INFO) {
    Serial.printf("Connected %s PHY=%s llOctets=%u llTimeUs=%u chunk=%u minIntUs=%u\r\n",
            connInfo.getAddress().toString().c_str(),
            s.phyIsCoded ? (s.codedScheme==2?"CODED(S2)":"CODED(S8)") : (s.phyIs2M?"2M":"1M"),
            s.llOctets, s.llTimeUs, s.txChunkSize, s.minSendIntervalUs);
  }
  if (s.onClientConnect) s.onClientConnect(connInfo.getAddress().toString());
  if (s.onPacingChanged) s.firePacingChanged(PacingReason::Recompute);
  }

  void onDisconnect(NimBLEServer* srv, NimBLEConnInfo &connInfo, int reason) override {
    if (!owner) return;
    auto& s = *owner;

    // Link down
    s.deviceConnected  = false;
    s.clientSubscribed = false;
    s.connHandle       = BLE_HS_CONN_HANDLE_NONE;

    // Reset PHY state and conservative LL timing defaults
    s.phyIs2M     = false;
    s.phyIsCoded  = false;
    s.codedScheme = 0;
    s.llTimeUs    = LL_DEFAULT_TIME_US;  
    s.llOctets    = LL_MAX_OCTETS;   // propose max octets next time (controller may downscale)

    // Reset pacing/backoff/probing state
    s.probing           = false;
    s.probeSuccesses    = 0;
    s.probeFailures     = 0;
    s.lkgFailStreak     = 0;
    s.recentlyBackedOff = false;
    s.cooldownSuccess   = 0;
    s.successStreak     = 0;
    s.lastEscalateAtUs  = 0;

    // Reset MTU/chunk/EBADDATA counters; drop any staged frame
    s.mtuRetryCount = 0;
    s.badDataRetries = 0;
    s.txOk = false;
    s.pendingLen = 0;
    s.lastTxUs = 0;

    // Recompute chunk/floor from current defaults, then pace conservatively
    s.recomputeTxTiming();
    s.sendIntervalUs = MAX_SEND_INTERVAL_US;
    s.lkgIntervalUs  = s.sendIntervalUs;

    // Restart advertising
    if (s.advertising) {
        s.advertising->start();
    } else {
        NimBLEDevice::startAdvertising();
    }

    #ifdef ARDUINO_ARCH_ESP32
      if (BLESerial::rssiTaskHandle) vTaskSuspend(BLESerial::rssiTaskHandle);
      if (BLESerial::txTaskHandle)   vTaskSuspend(BLESerial::txTaskHandle);
    #endif

  if (s.logLevel >= INFO) {
    const uint8_t hci = static_cast<uint8_t>(reason & 0xFF);
    Serial.printf("Client [%s] disconnected (reason=%u %s). Advertising restarted.\r\n",
            connInfo.getAddress().toString().c_str(),
            hci, hciDisconnectReasonStr(hci));
  }
  if (s.onClientDisconnect) {
    const uint8_t hci = static_cast<uint8_t>(reason & 0xFF);
    s.onClientDisconnect(connInfo.getAddress().toString(), hci);
  }
  if (s.onPacingChanged) s.firePacingChanged(PacingReason::DisconnectReset);

    // Legacy (kept for reference):
    // txAvailable = false;
  }

  void onMTUChange(uint16_t m, NimBLEConnInfo& connInfo) override {
    if (!owner) return;
    auto& s = *owner;

      // Update negotiated MTU
      s.mtu = m;

      // Recompute chunk size, floor interval, and watermarks
      s.recomputeTxTiming(); // also clamps sendIntervalUs and resets ramp to floor

    // Update attribute max lengths to reflect negotiated MTU (clamped to 512 per spec)
    uint16_t attMax = (m > 3) ? (uint16_t)std::min<uint16_t>(BLE_SERIAL_MAX_GATT, (uint16_t)(m - 3)) : (uint16_t)20;
    if (s.rxChar) s.rxChar->setMaxLen(attMax);
    if (s.txChar) s.txChar->setMaxLen(attMax);

      // Ensure pacing/probe/backoff state is coherent for the new floor
      s.probing           = false;
      s.probeSuccesses    = 0;
      s.probeFailures     = 0;
      s.lkgFailStreak     = 0;
      s.recentlyBackedOff = false;
      s.cooldownSuccess   = 0;
      s.successStreak     = 0;
      s.lkgIntervalUs     = s.sendIntervalUs;

      // Drop any staged frame; restage at new chunk size
      s.pendingLen        = 0;
      s.badDataRetries    = 0;

    if (s.logLevel >= INFO) {
      Serial.printf("MTU updated: %u (conn=%u), tx chunk=%u, min interval=%u us\r\n",
            m, connInfo.getConnHandle(), s.txChunkSize, (unsigned)s.minSendIntervalUs);
    }
    if (s.onMtuChanged) s.onMtuChanged(m);
    if (s.onPacingChanged) s.firePacingChanged(PacingReason::Recompute);
  }

  // Generate and return a random 6-digit passkey (000000–999999)
  uint32_t onPassKeyRequest() override {
    if (!owner) return 0;
    auto& s = *owner;

    // Generate random 6-digit code; ensure leading zeros possible on display
    uint32_t key = (uint32_t)random(0UL, 1000000UL);
    s.passkey = key;

    if (s.logLevel >= INFO) {
        Serial.printf("Server Passkey Request: %06u\r\n", key);
    }
    return key;
  }

    // Display callback (some stacks call this to show the key to the user)
  void onPassKeyDisplay(NimBLEConnInfo& /*connInfo*/, uint32_t key) override {
      if (!owner) return;
      auto& s = *owner;

      // Keep the displayed key in sync in case the stack provided it
      s.passkey = key;

      if (s.logLevel >= INFO) {
          Serial.printf("Server Passkey Display: %06u\r\n", key);
      }
  }

  // Confirm the passkey shown/entered by the peer
  void onConfirmPassKey(NimBLEConnInfo& connInfo, uint32_t peerKey) override {
      if (!owner) return;
      auto& s = *owner;

      bool match = (peerKey == s.passkey);
      NimBLEDevice::injectConfirmPasskey(connInfo, match);

      if (s.logLevel >= INFO) {
          Serial.printf("Confirm Passkey: local=%06u peer=%06u %s\r\n",
                        s.passkey, peerKey, match ? "MATCH" : "MISMATCH");
      }
  }

  void onAuthenticationComplete(NimBLEConnInfo& connInfo) override {
      if (!owner) return;
      auto& s = *owner;

      if (!connInfo.isEncrypted()) {
        NimBLEDevice::getServer()->disconnect(connInfo.getConnHandle());
        if (s.logLevel >= WARNING) {
          Serial.println("Encrypt connection failed - disconnecting client");
        }
        return;
      }
      if (s.logLevel >= INFO) {
        Serial.printf("Secured connection to: %s\r\n", connInfo.getAddress().toString().c_str());
      }
  }

private:

  BLESerial* owner{nullptr};

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

}; // end of ServerCallbacks ============================================================

// ===== RxCallbacks: handles incoming data =============================================
class BLESerial::RxCallbacks : public NimBLECharacteristicCallbacks {
public:
  explicit RxCallbacks(BLESerial* owner) : owner(owner) {}

  void onWrite(NimBLECharacteristic* ch, NimBLEConnInfo& connInfo) override {
    if (!owner) return;
    auto& s = *owner;

    const std::string &v = ch->getValue();
    if (v.empty()) return;

    // Push into RX ring; overwrite oldest to avoid blocking the NimBLE task.
    const uint8_t* data = reinterpret_cast<const uint8_t*>(v.data());
    size_t pushed = s.rxBuf.push(data, v.size(), true);

    // RX accounting (optional but handy)
    s.bytesRx += pushed;
    if (pushed < v.size()) {
        s.rxDrops += (v.size() - pushed);
    }
    s.lastRxUs = micros();

    // Clear last value held by the characteristic to free heap.
    ch->setValue(nullptr, 0);

  if (s.onDataReceived && pushed) s.onDataReceived(data, pushed);

  }
private:

  BLESerial* owner;

}; // end of RxCallbacks ================================================================

// ===== TxCallbacks: handles notification status =======================================
class BLESerial::TxCallbacks : public NimBLECharacteristicCallbacks {
public:
  explicit TxCallbacks(BLESerial* owner) : owner(owner) {}

  /* 
    Status codes:
    0                       → Success (notification queued/sent). 
    14 (BLE_HS_EDONE)       → Success for indication (confirmation received). 
    1  (BLE_HS_EAGAIN)      → Operation failed and should be retried later.
    2  (BLE_HS_EALREADY)    → Operation already in progress.
    3  (BLE_HS_EINVAL)      → Invalid parameters.
    4  (BLE_HS_EMSGSIZE)    → Payload too big for context. (For notifies you should already be ≤ MTU−3.)
    5  (BLE_HS_ENOENT)      → No such entry.
    6  (BLE_HS_ENOMEM)      → Out of buffers / resource exhaustion. You’re sending faster than the stack can drain, or mbufs are tight. Back off or throttle. 
    7  (BLE_HS_ENOTCONN)    → Connection went away / bad handle.
    8  (BLE_HS_ENOTSUP)     → Not supported.
    9  (BLE_HS_EAPP)        → Application error.
    10 (BLE_HS_EBADDATA)    → Malformed data.
    11 (BLE_HS_EOS)         → Operating system error.
    12 (BLE_HS_ECONTROLLER) → Controller error.
    13 (BLE_HS_ETIMEOUT)    → Operation timed out.
    15 (BLE_HS_EBUSY)       → Another LL/GATT procedure is in progress; try again later. 
    16 (BLE_HS_EREJECT)     → Operation rejected.
    17 (BLE_HS_EUNKNOWN)    → Unknown error.
    18 (BLE_HS_EROLE)       → Role error.
    19 (BLE_HS_ETIMEOUT_HCI)→ HCI timeout.
    20 (BLE_HS_ENOMEM_EVT)  → Out of memory to handle event.
    21 (BLE_HS_ENOADDR)     → No valid address.
    22 (BLE_HS_ENOTSYNCED)  → Host not synced with controller yet.
    23 (BLE_HS_EAUTHEN)     → Authentication failed.
    24 (BLE_HS_EAUTHOR)     → Authorization failed.
    25 (BLE_HS_EENCRYPT)    → Encryption failed.
    26 (BLE_HS_EENCRYPT_KEY_SZ) → Encryption key size insufficient.
    27 (BLE_HS_ESTORE_CAP)  → Storage capacity exceeded.
    28 (BLE_HS_ESTORE_FAIL) → Storage operation failed.
    29 (BLE_HS_EPREEMPTED)  → Operation preempted.
    30 (BLE_HS_EDISABLED)   → Feature disabled.
    31 (BLE_HS_ESTALLED)    → Operation stalled.
  */

  void onStatus(NimBLECharacteristic* ch, int code) override {
    if (!owner) return;
    auto& s = *owner;

    // Success path: OK or EDONE -------------------------------------------------------
    if (isOkOrDone(code)) {
      s.txOk = true;
      s.mtuRetryCount = 0;

      // Cooldown after a backoff before probing again
      if (s.recentlyBackedOff) {
        if (++s.cooldownSuccess >= COOL_SUCCESS_REQUIRED) {
          s.recentlyBackedOff = false;
          s.cooldownSuccess = 0;
          s.successStreak = 0;
          s.lkgFailStreak = 0;
        }
        return;
      }

      // Probe success handling
      if (s.probing) {
        if (++s.probeSuccesses >= PROBE_CONFIRM_SUCCESSES) {
          s.lkgIntervalUs = s.sendIntervalUs; // accept new floor
          s.probing = false;
          s.probeSuccesses = 0;
          s.probeFailures = 0;
          s.lkgFailStreak = 0;
          s.successStreak = 0;
          if (s.logLevel >= INFO) {
            Serial.printf("Probe accepted. LKG=%u\r\n", s.lkgIntervalUs);
          }
          if (s.onPacingChanged) s.firePacingChanged(PacingReason::ProbeAccepted);
        }
        return;
      }

      // Not probing: clear fail streak and maybe start a probe
      s.lkgFailStreak = 0;
      if (++s.successStreak >= PROBE_AFTER_SUCCESSES) {
        s.successStreak = 0;
        s.lkgIntervalUs = s.sendIntervalUs;
        uint32_t stepAbs = PROBE_STEP_US;
        uint32_t stepPct = (s.sendIntervalUs * PROBE_STEP_PCT) / 100u;
        uint32_t step = (stepPct > stepAbs) ? stepPct : stepAbs;
        uint32_t cand = (s.sendIntervalUs > step) ? (s.sendIntervalUs - step) : s.minSendIntervalUs;
        if (cand < s.minSendIntervalUs) cand = s.minSendIntervalUs;
        if (cand < s.sendIntervalUs) {
          s.sendIntervalUs = cand;
          s.probing = true;
          s.probeSuccesses = 0;
          s.probeFailures = 0;
          if (s.logLevel >= INFO) {
            Serial.printf("Starting probe: %u -> %u\r\n", s.lkgIntervalUs, s.sendIntervalUs);
          }
            if (s.onPacingChanged) s.firePacingChanged(PacingReason::ProbeStart);
        }
      }
      return;
    } // end of success path

    // EMSGSIZE: payload too big for context — adjust MTU/chunk, restage -----------------  
    if (isMsgSize(code)) {
      // For notifications this should rarely happen (already ≤ MTU-3). Treat as chunk sizing error.
      if (++s.mtuRetryCount <= BLESerial::kMtuRetryMax) {
        uint16_t oldChunk = s.txChunkSize;
        s.txChunkSize = (uint16_t)std::max(20, (int)s.txChunkSize / 2);
        s.lowWater = s.updateLowWaterMark(s.txChunkSize);
        s.minSendIntervalUs = BLESerial::computeMinSendIntervalUs(
          s.txChunkSize, s.llOctets, s.llTimeUs, s.mode, s.secure);
        if (s.sendIntervalUs < s.minSendIntervalUs) {
          s.sendIntervalUs = s.minSendIntervalUs;
        }
        if (s.logLevel >= INFO) {
          Serial.printf("Message Size Error: reduce chunk old=%u new=%u minSendIntervalUs=%u (retry %d/%d)\r\n",
                        oldChunk, s.txChunkSize, s.minSendIntervalUs, s.mtuRetryCount, BLESerial::kMtuRetryMax);
        }
        if (s.onPacingChanged && oldChunk != s.txChunkSize) s.firePacingChanged(PacingReason::ChunkShrink);
      } else {
        if (s.txChunkSize > 20) {
          if (s.logLevel >= WARNING) Serial.println("Message Size Error: fallback to 20 bytes");
          s.txChunkSize = 20;
          s.lowWater = s.updateLowWaterMark(s.txChunkSize);
          s.minSendIntervalUs = BLESerial::computeMinSendIntervalUs(
            s.txChunkSize, s.llOctets, s.llTimeUs, s.mode, s.secure);
          if (s.sendIntervalUs < s.minSendIntervalUs)
            s.sendIntervalUs = s.minSendIntervalUs;
          s.mtuRetryCount = 0;
          if (s.onPacingChanged) s.firePacingChanged(PacingReason::MsgSizeFallback);
        } else {
          if (s.logLevel >= WARNING) Serial.println("Message Size Error: persistent -> disconnect");
          if (s.server && s.connHandle != BLE_HS_CONN_HANDLE_NONE)
            s.server->disconnect(s.connHandle);
          s.mtuRetryCount = 0;
        }
        s.pendingLen = 0;
      }
      return;
    } // end of EMSGSIZE handling

    // Bad Data: 
    if (isBadData(code)) {
      if (s.logLevel >= WARNING) {
          Serial.printf("Malformed payload (program error). Dropping frame.\r\n");
      }      
      s.pendingLen = 0;
      return;
    } // Bad Data handling

    // Application Error: 
    if (isAppError(code)) {
      if (s.logLevel >= WARNING) {
          Serial.printf("Application error (program error). Dropping frame.\r\n");
      }      
      s.pendingLen = 0;
      return;
    } // Application Error handling


    // Congestion/timeouts/busy ----------------------------------------------------------
    if (isCongestion(code)) {
      s.successStreak = 0;
      s.recentlyBackedOff = true;
      s.cooldownSuccess = 0;

      if (s.probing) {
        s.probing = false;
        s.probeFailures++;
        s.sendIntervalUs = s.lkgIntervalUs;
        s.lkgFailStreak = 0;
        if (s.logLevel >= INFO) {
          Serial.printf("Probe failed, revert to LKG=%u\r\n", s.sendIntervalUs);
        }
        if (s.onPacingChanged) s.firePacingChanged(PacingReason::Backoff);
      } else {
        if (++s.lkgFailStreak >= LKG_ESCALATE_AFTER_FAILS) {
          uint32_t now = (uint32_t)micros();

          if ((now - s.lastEscalateAtUs) >= ESCALATE_COOLDOWN_US &&
                     s.txBuf.available() >= s.lowWater) {
              s.lastEscalateAtUs = now;
              s.lkgFailStreak    = 0;
              uint32_t next = (s.lkgIntervalUs * LKG_ESCALATE_NUM) / LKG_ESCALATE_DEN;
              if (next < s.minSendIntervalUs) next = s.minSendIntervalUs;
              if (next > MAX_SEND_INTERVAL_US) next = MAX_SEND_INTERVAL_US;
              s.lkgIntervalUs  = next;
              s.sendIntervalUs = next;
              if (s.logLevel >= INFO)
                  Serial.printf("Escalate LKG to %u\r\n", s.lkgIntervalUs);
              if (s.onPacingChanged) s.firePacingChanged(PacingReason::Escalate);
          }
        }
      }
      return;
    } // end of congestion handling

    // Disconnect or EOS-like ------------------------------------------------------------
    if (isDisconnectedOrEOS(code)) {
      s.successStreak = 0;
      s.recentlyBackedOff = false;
      s.cooldownSuccess = 0;
      s.probing = false;
      s.probeSuccesses = 0;
      s.probeFailures = 0;
      s.lkgFailStreak = 0;
      s.sendIntervalUs = MAX_SEND_INTERVAL_US;
      s.lkgIntervalUs = s.sendIntervalUs;
      if (s.logLevel >= WARNING) {
        Serial.println("Link closed (ENOTCONN/EOS)");
      }
      if (s.onPacingChanged) s.firePacingChanged(PacingReason::DisconnectReset);
      return;
    } // end of disconnect/EOS

    // Unclassified: drop probe if probing; otherwise no pacing change ------------
    if (s.probing) {
      s.probing = false;
      s.sendIntervalUs = s.lkgIntervalUs;
      s.lkgFailStreak = 0;
      if (s.logLevel >= INFO) {
        Serial.printf("Unclassified issue %u (%s) while probing: revert to LKG=%u\r\n", code, codeName(code), s.sendIntervalUs);
      }
      if (s.onPacingChanged) s.firePacingChanged(PacingReason::Backoff);
    } else {
        if (s.logLevel >= WARNING) {
            Serial.printf("Unclassified issue %u (%s)\r\n", code, codeName(code));
        }

    } // end of unclassified
  } 
  // end of onStatus ---------------------------------------------------------------------------------

  void onSubscribe(NimBLECharacteristic* ch, NimBLEConnInfo& connInfo, uint16_t subValue) override {
    if (!owner) return;
    auto& s = *owner;

    bool notify   = (subValue & 0x0001);
    bool indicate = (subValue & 0x0002);
    s.clientSubscribed = notify || indicate;

    if (s.logLevel >= INFO) {
      std::string addr = connInfo.getAddress().toString();
      std::string uuid = ch->getUUID().toString();
      if (subValue == 0)
        Serial.printf("Client %s unsubscribed %s\r\n", addr.c_str(), uuid.c_str());
      else
        Serial.printf("Client %s subscribed (%s%s) %s\r\n",
          addr.c_str(),
          notify ? "notify" : "",
          indicate ? (notify ? "+indicate" : "indicate") : "",
          uuid.c_str());
    }
    if (s.onSubscribeChanged) s.onSubscribeChanged(s.clientSubscribed);
  } 
  // end of onSubscribe -------------------------------------------------------------------------------------

private:
  BLESerial* owner;

  // ---- Status code normalization helpers ----
  static inline bool isOkOrDone(int code) {
    return (code == 0 || code == BLE_HS_EDONE);
  } // end of isOkOrDone

  static inline bool isMsgSize(int code) {
    return (code == BLE_HS_EMSGSIZE);
  } // end of isMsgSize

  static inline bool isBadData(int code) {
    return (code == BLE_HS_EBADDATA);
  } // end of isBadData

  static inline bool isAppError(int code) {
    return (code == BLE_HS_EAPP);
  } // end of isAppError

  static inline bool isCongestion(int code) {
    // Treat ENOMEM/ENOMEEVT/EBUSY/TIMEOUT as congestion. Accept observed integers too.
  return  (code == BLE_HS_EAGAIN ||
           code == BLE_HS_EALREADY ||
           code == BLE_HS_ENOMEM ||
           code == BLE_HS_EBUSY ||
           code == BLE_HS_ENOMEM_EVT ||
           code == BLE_HS_ESTALLED ||
           code == BLE_HS_EPREEMPTED ||
           code == BLE_HS_ETIMEOUT ||
           code == BLE_HS_ETIMEOUT_HCI
          );
  } // end of isCongestion

  static inline bool isDisconnectedOrEOS(int code) {
      // ENOTCONN and EOS; observed EOS sometimes 10/11 in logs
      return (code == BLE_HS_ENOTCONN || 
              code == BLE_HS_EOS);
  } // end of isDisconnectedOrEOS

  static const char* codeName(int code) {
    switch (code) {
      case 0:  return "OK(0)";                  // notify success
      case 1:  return "EAGAIN(1)";              // retry later
      case 2:  return "EALREADY(2)";            // op in progress
      case 3:  return "EINVAL(3)";
      case 4:  return "EMSGSIZE(4)";
      case 5:  return "ENOENT(5)";
      case 6:  return "ENOMEM(6)";
      case 7:  return "ENOTCONN(7)";
      case 8:  return "ENOTSUP(8)";
      case 9:  return "EAPP(9)";
      case 10: return "EBADDATA(10)";
      case 11: return "EOS(11)";
      case 12: return "ECONTROLLER(12)";
      case 13: return "ETIMEOUT(13)";
      case 14: return "EDONE(14)";              // indicate success
      case 15: return "EBUSY(15)";
      case 16: return "EREJECT(16)";
      case 17: return "EUNKNOWN(17)";
      case 18: return "EROLE(18)";
      case 19: return "ETIMEOUT_HCI(19)";
      case 20: return "ENOMEM_EVT(20)";
      case 21: return "ENOADDR(21)";
      case 22: return "ENOTSYNCED(22)";
      case 23: return "EAUTHEN(23)";
      case 24: return "EAUTHOR(24)";
      case 25: return "EENCRYPT(25)";
      case 26: return "EENCRYPT_KEY_SZ(26)";
      case 27: return "ESTORE_CAP(27)";
      case 28: return "ESTORE_FAIL(28)";
      case 29: return "EPREEMPTED(29)";
      case 30: return "EDISABLED(30)";
      case 31: return "ESTALLED(31)";
      default: return nullptr; // not a core code
    }
  } // end of codeName

}; // end of TxCallbacks =====================================================

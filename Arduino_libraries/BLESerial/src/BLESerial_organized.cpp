// ****************************************************************************************************
// BLE Serial Library 
// BLE Serial Communication for Arduino using NimBLE and Nordic UART Service (NUS)
// ****************************************************************************************************
// 
// ****************************************************************************************************
#include <algorithm>
#include <cctype>
#include "BLESerial.h"

#ifdef ARDUINO_ARCH_ESP32
// forward declaration so we can pass it to xTaskCreatePinnedToCore
static void RssiTask(void* arg);
TaskHandle_t BLESerial::rssiTaskHandle = nullptr;
#endif

BLESerial* BLESerial::active = nullptr;

bool BLESerial::begin(Mode newMode, const char* deviceName, uint16_t newMTU, bool newSecure) {
  // Minimal init; full feature set can be added incrementally
  mode   = newMode;
  secure = newSecure;
  mtu    = newMTU;

  logLevel = INFO;

  BLESerial::active = this;  // allow static GAP handler to reach our instance

  // BLE: init stack, create service, start adv; UART: config UART  
  NimBLEDevice::init(deviceName);
  NimBLEDevice::setCustomGapHandler(&BLESerial::gapEventHandler);
  NimBLEDevice::setMTU(mtu);

  // Power settings
  if (mode == Mode::Fast) {
    // Max power for best range and speed;
    NimBLEDevice::setPower(BLE_TX_DBP9, PWR_ALL);   // max TX power everywhere
  } else if (mode == Mode::LowPower) {
    // Min power for best battery life; adjust as needed for your environment
    NimBLEDevice::setPower(BLE_TX_DBN9, PWR_ADV);   // small ADV range to save power
    NimBLEDevice::setPower(BLE_TX_DBN9, PWR_SCAN);  // scanning (if you do it)
    NimBLEDevice::setPower(BLE_TX_DBN6, PWR_CONN);  // enough for typical indoor links
  } else if (mode == Mode::LongRange) {
    // long range
    NimBLEDevice::setPower(BLE_TX_DBP9, PWR_ALL);
  } else if (mode == Mode::Balanced) {
    // balanced, visible enough, not wasteful
    NimBLEDevice::setPower(BLE_TX_DBN3, PWR_ADV);
    NimBLEDevice::setPower(BLE_TX_DBN6, PWR_SCAN);
    NimBLEDevice::setPower(BLE_TX_DB0,  PWR_CONN);
  }

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

  // Default PHY preference
  if (mode == Mode::Fast) {
      // 2M PHY for faster data rates
      NimBLEDevice::setDefaultPhy(BLE_GAP_LE_PHY_2MASK, BLE_GAP_LE_PHY_2MASK);
  } else {
      // Any PHY for balanced or low power
      NimBLEDevice::setDefaultPhy(BLE_GAP_LE_PHY_ANY_MASK, BLE_GAP_LE_PHY_ANY_MASK);
  }

  // Suggest max data length for future connections; use conservative 1M time
  // (we'll retune per-connection once we know the actual PHY)
  ble_gap_write_sugg_def_data_len(LL_MAX_OCTETS, LL_TIME_1US);

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
          NIMBLE_PROPERTY::WRITE 
          | NIMBLE_PROPERTY::WRITE_NR        // write without response (faster)
          | NIMBLE_PROPERTY::WRITE_ENC       // require encryption for writes (triggers pairing)
      );

      txChar = service->createCharacteristic(
          BLE_SERIAL_CHARACTERISTIC_UUID_TX,
          NIMBLE_PROPERTY::NOTIFY 
          | NIMBLE_PROPERTY::READ_ENC                               // require encryption for notify subscription
      );
  } else {
      rxChar = service->createCharacteristic(
          BLE_SERIAL_CHARACTERISTIC_UUID_RX,
          NIMBLE_PROPERTY::WRITE 
          | NIMBLE_PROPERTY::WRITE_NR        // write without response (faster)
      );
      txChar = service->createCharacteristic(
          BLE_SERIAL_CHARACTERISTIC_UUID_TX,
          NIMBLE_PROPERTY::NOTIFY
      );
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
  const uint8_t mfg[] = { 0xFF, 0xFF, 'S','i','m',':','1','.','0' }; // 0xFFFF + 27 bytes max
  scanData.setManufacturerData(std::string((const char*)mfg, sizeof(mfg)));  
  advertising->setAdvertisementData(advData);
  advertising->setScanResponseData(scanData);
  advertising->start();

  // Print MAC last (purely informational)
  deviceMac = NimBLEDevice::getAddress().toString();
  for (char &c : deviceMac) c = (char)toupper((unsigned char)c);
  if (logLevel >= INFO) {  
      Serial.printf("MAC: %s\r\n", deviceMac.c_str());
  }

  #ifdef ARDUINO_ARCH_ESP32
  // Create RSSI task
    if (!BLESerial::rssiTaskHandle) {
      // Keep RSSI on core 1 to reduce interference with NimBLE host
      xTaskCreatePinnedToCore(
        RssiTask,     // task function
        "RssiTask",   // task name
        3072,         // stack size
        this,         // task parameter
        2,            // priority
        &BLESerial::rssiTaskHandle,  // task handle
        1
      );
      vTaskSuspend(BLESerial::rssiTaskHandle);
    }
  #endif

  randomSeed(analogRead(0));
  return true;
}

void BLESerial::end() {
  // TODO: stop advertising and dispose BLE objects
}

int BLESerial::available() {
  return (int)rxBuf.available();
}

int BLESerial::read(uint8_t* dst) {
  // Assumes RingBuffer::pop() returns int (or -1 when empty)
  return rxBuf.pop(uint8_t* dst, 1);
  return dst
}

int BLESerial::read(uint8_t* dst, size_t n) {
  return (int)rxBuf.read(dst, n);
}

bool BLESerial::readLine(char* /*dst*/, size_t /*maxLen*/, uint32_t /*timeoutMs*/) {
  // TODO: optional helper; not implemented yet
  return false;
}

int BLESerial::peek() {
  return rxBuf.peek();
}

void BLESerial::flush() {
  // Non-blocking drain: pump until empty or link busy
  while (txBuf.available() > 0) {
    pumpTx();
    delay(1);
  }
}

size_t BLESerial::write(uint8_t b) {
  return txBuf.push(&b, 1, false);
}

size_t BLESerial::write(const uint8_t* p, size_t n) {
  return txBuf.push(p, n, false);
}


void BLESerial::update() {
  // Polling pump placeholder
  pumpTx();
  #ifndef ARDUINO_ARCH_ESP32
    if (deviceConnected && connHandle != BLE_HS_CONN_HANDLE_NONE) {
        uint32_t now = millis();
        if ((now - lastRssiMs) >= RSSI_INTERVAL_MS) {
            adjustLink();
        }
    }
  #endif  
}

void BLESerial::pumpTx() {
  // Slice & send frames until busy; implement later

  if (!deviceConnected || !clientSubscribed || txChar == nullptr) return;

  // If previous notify succeeded, consume the staged bytes now
  if (txOk && pendingLen > 0) {
    txBuf.consume(pendingLen);
    txOk = false;
    pendingLen = 0;
    size_t used = txBuf.available();
    if (used <= lowWater) {
      txAvailable = true;
    }
  } // end if previous send was success

  // time to send next chunk?
  const uint32_t now = micros();
  if ((now - lastTxUs) < sendIntervalUs) return;

  // Nothing staged? Stage a new chunk from tx buffer
  if (pendingLen == 0) {
      const size_t avail = txBuf.available();
      if (!avail) return;

      size_t toStage = txChunkSize <= avail ? txChunkSize : avail;
      // Peek without consuming so we can retry on failures; consume after success in onStatus path
      pendingLen = txBuf.peek(pending, toStage);
      if (pendingLen == 0) return;
      // If you need to block producer when staging, add a flag here; otherwise omit
      txAvailable = false;
  } // end obtain next chunk

  // Send the staged chunk
  if (pendingLen && pendingLen <= txChunkSize) {
    txOk = false; // will be set true on success by TxCallbacks::onStatus
    txChar->setValue(reinterpret_cast<const uint8_t*>(pending), pendingLen);
    txChar->notify();
    lastTxUs = now;
  } else if (pendingLen > txChunkSize) {
      // staged larger than current chunk after renegotiation; drop and retry
      pendingLen = 0;
      if (txBuf.available() <= lowWater) txAvailable = true;
  } // end sending chunk
} // end pumpTx

uint16_t BLESerial::computeTxChunkSize(uint16_t mtuVal, uint16_t llOctets, Mode modeVal) {
  // Base payload is MTU-3 (ATT header excluded). For SPEED profile, allow up to
  // 2 LL PDUs to reduce per-notify overhead; otherwise keep within a single LL PDU.

  // Max payload that fits in ONE LL data PDU carrying an L2CAP SDU with ATT notif:
  // onePduMax = llOctets - (BLE_SERIAL_L2CAP_HDR_BYTES + BLE_SERIAL_ATT_HDR_BYTES)
  //           = llOctets - 7
  auto hdrBytes = BLE_SERIAL_ATT_HDR_BYTES + BLE_SERIAL_L2CAP_HDR_BYTES;
  // ATT notification value max = MTU - 3 (ATT header = 3)
  uint16_t attPayload = (mtuVal > BLE_SERIAL_ATT_HDR_BYTES) ? (uint16_t)(mtuVal - BLE_SERIAL_ATT_HDR_BYTES) : 0;

  auto minPdu = BLE_SERIAL_MIN_MTU - BLE_SERIAL_ATT_HDR_BYTES;
  uint16_t onePduMax = (llOctets > hdrBytes) ? (uint16_t)(llOctets - hdrBytes) : minPdu;

  // FAST mode may use up to TWO PDUs worth (single SDU fragmented), still subtract headers only once.
  uint16_t twoPduMax = onePduMax;
  // Max payload fitting N LL PDUs: N*ll_octets - (L2CAP 4 + ATT 3)
  uint32_t twoTotal = (uint32_t)llOctets * 2u;
  if (twoTotal > hdrBytes) {
    twoPduMax = (uint16_t)(twoTotal - hdrBytes);
  } else {
    twoPduMax = onePduMax;
  }

  // uint16_t limit = (modeVal == Mode::Fast) ? twoPduMax : onePduMax;
  uint16_t limit = onePduMax; // TEMPORARY: disable 2-PDU for now
  if (attPayload < limit) limit = attPayload;
  if (limit < 20) limit = 20; // keep a practical floor
  return limit;
}

uint32_t BLESerial::computeMinSendIntervalUs(uint16_t chunkSize, 
                                            uint16_t llOctets, 
                                            uint16_t llTimeUsVal, 
                                            Mode modeVal) 
{
  // Total L2CAP SDU size being carried is (chunk + L2CAP(4) + ATT(3))
  const uint32_t l2capPlusAtt = static_cast<uint32_t>(chunkSize) + BLE_SERIAL_ATT_HDR_BYTES + BLE_SERIAL_L2CAP_HDR_BYTES;

  // Number of LL PDUs required to carry this SDU (ceil-divide)
  const uint16_t numLlPdu = static_cast<uint16_t>((l2capPlusAtt + llOctets - 1u) / llOctets);

  // Guard factor by mode (percent). Fast gets smallest guard.
  uint32_t guardNum = 110; // +10%
  uint32_t guardDen = 100;
  if (modeVal == Mode::Fast) {
      guardNum = 103; // +3%
  } else if (modeVal == Mode::Balanced) {
      guardNum = 108; // +8%
  } else if (modeVal == Mode::LongRange) {
      guardNum = 115; // +15%
  } else { // LowPower or others
      guardNum = 112; // +12%
  }

  return static_cast<uint32_t>(numLlPdu) * static_cast<uint32_t>(llTimeUsVal) * guardNum / guardDen;
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
  txChunkSize       = computeTxChunkSize(mtu, llOctets, mode);
  minSendIntervalUs = computeMinSendIntervalUs(txChunkSize, llOctets, llTimeUs, mode);

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
}

void BLESerial::updateLlTime() {
  // Pick per-PDU transmit time from current PHY selection
  if (phyIsCoded) {
      // When coded PHY is active, choose S=2 vs S=8 if known; default to S=8 otherwise
      llTimeUs = (codedScheme == 2) ? LL_TIME_CODED_S2_US : LL_TIME_CODED_S8_US;
  } else if (phyIs2M) {
      llTimeUs = LL_TIME_2US;
  } else {
      llTimeUs = LL_TIME_1US;
  }

  // Any LL-time change alters the floor; recompute pacing
  recomputeTxTiming();
}

// ===============================================================================================================================================================
// RSSI monitor task: polls RSSI and adjusts PHY with hysteresis
// ===============================================================================================================================================================

static void RssiTask(void* arg) {
  BLESerial* self = static_cast<BLESerial*>(arg);
  for (;;) {
    if (self && self->deviceConnected && self->connHandle != BLE_HS_CONN_HANDLE_NONE) {
      self->adjustLink();
    }
    vTaskDelay(pdMS_TO_TICKS(RSSI_INTERVAL_MS));
  }
}

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
  bool    wantCoded       = false;
  uint8_t wantCodedScheme = 0;
  bool    want2M          = false;

  if (rssiAvg <= (RSSI_S8_THRESHOLD + RSSI_HYSTERESIS)) {
      wantCoded = true;
      wantCodedScheme = 8;
  } else if (rssiAvg <= (RSSI_S2_THRESHOLD + RSSI_HYSTERESIS)) {
      wantCoded = true;
      wantCodedScheme = 2;
  } else if (rssiAvg > (RSSI_FAST_THRESHOLD - RSSI_HYSTERESIS)) {
      want2M = true;
  } // else stay 1M

  // Current state
  bool    have2M    = phyIs2M;
  bool    haveCoded = phyIsCoded;
  uint8_t curScheme = codedScheme;

  // Evaluate change necessity
  bool change = false;
  if (wantCoded) {
      if (!haveCoded || curScheme != wantCodedScheme) {
          change = true;
      }
  } else if (want2M) {
      if (!have2M || haveCoded) {
          change = true;
      }
  } else {
      // Want 1M
      if (have2M || haveCoded) {
          change = true;
      }
  }

  if (!change) return;

  // Apply PHY preference
  int rc = 0;
  if (wantCoded) {
      desiredCodedScheme = wantCodedScheme;
      rc = ble_gap_set_prefered_le_phy(
          connHandle,
          BLE_GAP_LE_PHY_CODED_MASK,
          BLE_GAP_LE_PHY_CODED_MASK,
          (wantCodedScheme == 2 ? BLE_GAP_LE_PHY_CODED_S2 : BLE_GAP_LE_PHY_CODED_S8)
      );
  } else if (want2M) {
      desiredCodedScheme = 0;
      rc = ble_gap_set_prefered_le_phy(
          connHandle,
          BLE_GAP_LE_PHY_2MASK,
          BLE_GAP_LE_PHY_2MASK,
          0
      );
  } else { // 1M
      desiredCodedScheme = 0;
      rc = ble_gap_set_prefered_le_phy(
          connHandle,
          BLE_GAP_LE_PHY_1MASK,
          BLE_GAP_LE_PHY_1MASK,
          0
      );
  }

  if (rc == 0) {
      lastRssiActionMs = millis();
      if (logLevel >= INFO) {
          Serial.printf("RSSI adapt: avg=%d raw=%d -> %s%s\r\n",
                        rssiAvg, rssiRaw,
                        wantCoded ? (wantCodedScheme==2?"CODED(S2)":"CODED(S8)") :
                        (want2M ? "2M" : "1M"),
                        "");
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
      s.updateLlTime();

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
    s.badDataRetries  = 0;          // reset EBADDATA fallback budget


    uint16_t minItvl, maxItvl, latency, supTimeout;
    switch (s.mode) {
      case Mode::Fast:
        minItvl    = MIN_BLE_INTERVAL_SPEED;
        maxItvl    = MAX_BLE_INTERVAL_SPEED;
        latency    = BLE_SLAVE_LATENCY_SPEED;
        supTimeout = BLE_SUPERVISION_TIMEOUT_SPEED;
        break;
      case Mode::LowPower:
        minItvl    = MIN_BLE_INTERVAL_LOWPWR;
        maxItvl    = MAX_BLE_INTERVAL_LOWPWR;
        latency    = BLE_SLAVE_LATENCY_LOWPWR;
        supTimeout = BLE_SUPERVISION_TIMEOUT_LOWPWR;
        break;
      case Mode::LongRange:
        minItvl    = MIN_BLE_INTERVAL_LONG_RANGE;
        maxItvl    = MAX_BLE_INTERVAL_LONG_RANGE;
        latency    = BLE_SLAVE_LATENCY_LONG_RANGE;
        supTimeout = BLE_SUPERVISION_TIMEOUT_LONG_RANGE;
        break;
      case Mode::Balanced:
      default:
        minItvl    = MIN_BLE_INTERVAL_BALANCED;
        maxItvl    = MAX_BLE_INTERVAL_BALANCED;
        latency    = BLE_SLAVE_LATENCY_BALANCED;
        supTimeout = BLE_SUPERVISION_TIMEOUT_BALANCED;
        break;
    }
    (void)srv->updateConnParams(s.connHandle, minItvl, maxItvl, latency, supTimeout);

    // Set preferred PHY based on mode (controller may choose differently)
    uint8_t phyMask, codedScheme;
    switch (s.mode) {
      case Mode::Fast:
        phyMask = BLE_GAP_LE_PHY_2MASK;
        codedScheme = 0;
        break;
      case Mode::LowPower:
        phyMask = BLE_GAP_LE_PHY_1MASK;
        codedScheme = 0;
        break;
      case Mode::LongRange:
        phyMask = BLE_GAP_LE_PHY_CODED_MASK;
        codedScheme = (s.desiredCodedScheme == 2 ? BLE_GAP_LE_PHY_CODED_S2 : BLE_GAP_LE_PHY_CODED_S8);
        break;
      case Mode::Balanced:
      default:
        phyMask = BLE_GAP_LE_PHY_ANY_MASK;
        codedScheme = 0;
        break;
    }
    (void)ble_gap_set_prefered_le_phy(s.connHandle, phyMask, phyMask, 0);

    // Provisional data length (before reading actual PHY)
    if (s.mode == Mode::LowPower) {
        s.llOctets = LL_MIN_OCTETS;          // 27
        s.llTimeUs = LL_TIME_LOW_POWER;      // 328 µs
    } else if (s.mode == Mode::LongRange) {
        s.llOctets = LL_CONS_OCTETS;         // 244 (common coded target)
        s.llTimeUs = LL_TIME_CODED_S8_US;    // assume robust S=8 until confirmed
    } else if (s.mode == Mode::Fast) {
        s.llOctets = LL_MAX_OCTETS;          // 251
        s.llTimeUs = LL_TIME_2US;            // optimistic 2M until read
    } else { // Balanced
        s.llOctets = LL_MAX_OCTETS;
        s.llTimeUs = LL_TIME_1US;            // start with 1M
    }
    (void)ble_gap_set_data_len(s.connHandle, s.llOctets, s.llTimeUs);

    // Learn actual negotiated PHY
    uint8_t txPhy = 0, rxPhy = 0;
    if (ble_gap_read_le_phy(s.connHandle, &txPhy, &rxPhy) == 0) {
        s.phyIs2M    = (txPhy == BLE_HCI_LE_PHY_2M)    && (rxPhy == BLE_HCI_LE_PHY_2M);
        s.phyIsCoded = (txPhy == BLE_HCI_LE_PHY_CODED) && (rxPhy == BLE_HCI_LE_PHY_CODED);
        if (s.phyIsCoded) {
            s.codedScheme = (s.desiredCodedScheme == 2 ? 2 : 8);
            s.llTimeUs    = (s.codedScheme == 2 ? LL_TIME_CODED_S2_US : LL_TIME_CODED_S8_US);
        } else if (s.phyIs2M) {
            s.codedScheme = 0;
            s.llTimeUs    = LL_TIME_2US;
        } else { // 1M
            s.codedScheme = 0;
            s.llTimeUs    = LL_TIME_1US;
        }

        // Reapply data length with corrected timing if needed
        (void)ble_gap_set_data_len(s.connHandle, s.llOctets, s.llTimeUs);
    } else {
        // PHY read failed: fall back to 1M assumptions
        s.phyIs2M = false;
        s.phyIsCoded = false;
        s.codedScheme = 0;
        s.llTimeUs = LL_TIME_1US;
        (void)ble_gap_set_data_len(s.connHandle, s.llOctets, s.llTimeUs);
    }

    // Recompute TX timing and pacing floor
    s.updateLlTime();      // picks llTimeUs again based on flags, then
    s.recomputeTxTiming(); // updates txChunkSize & minSendIntervalUs
    s.resetTxRamp(true);   // start baseline pacing

    // Start security if enabled
    if (s.secure) {
        NimBLEDevice::startSecurity(s.connHandle);
    }

    // Resume RSSI task
    #ifdef ARDUINO_ARCH_ESP32
      if (BLESerial::rssiTaskHandle) vTaskResume(BLESerial::rssiTaskHandle);
    #endif

    if (s.logLevel >= INFO) {
        Serial.printf("Connected %s PHY=%s llOctets=%u llTimeUs=%u chunk=%u minIntUs=%u\r\n",
                      connInfo.getAddress().toString().c_str(),
                      s.phyIsCoded ? (s.codedScheme==2?"CODED(S2)":"CODED(S8)") : (s.phyIs2M?"2M":"1M"),
                      s.llOctets, s.llTimeUs, s.txChunkSize, s.minSendIntervalUs);
    }
  }

  void onDisconnect(NimBLEServer* /*srv*/, NimBLEConnInfo &/*connInfo*/, int /*reason*/) override {
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
    s.llTimeUs    = LL_TIME_1US;     // assume 1M when not connected
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
    s.sendIntervalUs = BLESerial::kMaxSendIntervalUs;
    s.lkgIntervalUs  = s.sendIntervalUs;

    // Restart advertising
    if (s.advertising) {
        s.advertising->start();
    } else {
        NimBLEDevice::startAdvertising();
    }

    #ifdef ARDUINO_ARCH_ESP32
      if (BLESerial::rssiTaskHandle) vTaskSuspend(BLESerial::rssiTaskHandle);
    #endif

    if (s.logLevel >= INFO) {
        const uint8_t hci = static_cast<uint8_t>(reason & 0xFF);
        Serial.printf("Client [%s] disconnected (reason=%u %s). Advertising restarted.\r\n",
                      connInfo.getAddress().toString().c_str(),
                      hci, hciDisconnectReasonStr(hci));
    }

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

    // Optional user hook (add a std::function<void()> onReceive in BLESerial if desired)
    // if (s.onReceive) s.onReceive();

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
    0                    → Success (notification queued/sent). 
    1 (BLE_HS_EUNKNOWN)  → Unknown error.
    14 (BLE_HS_EDONE)    → Success for indication (confirmation received). 
    6 (BLE_HS_ENOMEM)    → Out of buffers / resource exhaustion. You’re sending faster than the stack can drain, or mbufs are tight. Back off or throttle. 
    15 (BLE_HS_EBUSY)    → Another LL/GATT procedure is in progress; try again later. 
    13 (BLE_HS_ETIMEOUT) → Timed out (e.g., indication not confirmed). 
    7 (BLE_HS_ENOTCONN)  → Connection went away / bad handle. 
    3/2 (BLE_HS_EINVAL)  → Bad arg / state. 
    4 (BLE_HS_EMSGSIZE)  → Payload too big for context. (For notifies you should already be ≤ MTU−3.)
    5 (BLE_HS_EALREADY)  → Operation already in progress.
    8 (BLE_HS_EAPP)      → Application error.
    9 (BLE_HS_EBADDATA)  → Malformed data.
    10 (BLE_HS_EOS)      → Connection closed, end of stream.
    12 (BLE_HS_ENOMEEVT) → Out of memory for event allocation.
    16 (BLE_HS_EDISABLED) → BLE stack not enabled.
    18 (BLE_HS_ENOTSYNCED)→ Host not synced with controller yet.
    19 (BLE_HS_EAUTHEN)  → Authentication failed.
    20 (BLE_HS_EAUTHOR)  → Authorization failed.
    21 (BLE_HS_EENCRYPT) → Encryption failed.
    22 (BLE_HS_EENCRYPT_KEY_SZ) → Insufficient key size.
    23 (BLE_HS_ESTORE_CAP) → Storage capacity reached (bonding).
    24 (BLE_HS_ESTORE_FAIL) → Persistent storage write failed.
    25 (BLE_HS_EHCI)     → Low-level HCI failure.
  */

  void onStatus(NimBLECharacteristic* /*ch*/, int code) override {
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
          s.txChunkSize, s.llOctets, s.llTimeUs, s.mode);
        if (s.sendIntervalUs < s.minSendIntervalUs) {
          s.sendIntervalUs = s.minSendIntervalUs;
        }
        if (s.logLevel >= INFO) {
          Serial.printf("EMSGSIZE reduce chunk old=%u new=%u minSendIntervalUs=%u (retry %d/%d)\r\n",
                        oldChunk, s.txChunkSize, s.minSendIntervalUs, s.mtuRetryCount, BLESerial::kMtuRetryMax);
        }
        s.pendingLen = 0; // restage with new size
      } else {
        if (s.txChunkSize > 20) {
          if (s.logLevel >= WARNING) Serial.println("EMSGSIZE fallback to 20 bytes");
          s.txChunkSize = 20;
          s.lowWater = s.updateLowWaterMark(s.txChunkSize);
          s.minSendIntervalUs = BLESerial::computeMinSendIntervalUs(
            s.txChunkSize, s.llOctets, s.llTimeUs, s.mode);
          if (s.sendIntervalUs < s.minSendIntervalUs)
            s.sendIntervalUs = s.minSendIntervalUs;
          s.mtuRetryCount = 0;
        } else {
          if (s.logLevel >= WARNING) Serial.println("EMSGSIZE persistent -> disconnect");
          if (s.server && s.connHandle != BLE_HS_CONN_HANDLE_NONE)
            s.server->disconnect(s.connHandle);
          s.mtuRetryCount = 0;
        }
        s.pendingLen = 0;
      }
      return;
    } // end of EMSGSIZE handling

    // EBADDATA: shrink chunk a bit, do not change pacing/probe --------------------------
    if (isBadData(code)) {
      if (s.badDataRetries < BLESerial::kBadDataMaxRetries) {
        uint16_t oldChunk = s.txChunkSize;
        uint16_t newChunk = (uint16_t)std::max(20, (int)(oldChunk * 9) / 10); // ~10% shrink
        if (newChunk < oldChunk) {
          s.txChunkSize = newChunk;
          s.lowWater    = s.updateLowWaterMark(s.txChunkSize);
          s.minSendIntervalUs = BLESerial::computeMinSendIntervalUs(
            s.txChunkSize, s.llOctets, s.llTimeUs, s.mode);
          if (s.sendIntervalUs < s.minSendIntervalUs)
            s.sendIntervalUs = s.minSendIntervalUs;
          ++s.badDataRetries;
          if (s.logLevel >= INFO)
            Serial.printf("EBADDATA shrink %u->%u floor=%u (%u/%u)\r\n",
                          oldChunk, s.txChunkSize,
                          s.minSendIntervalUs,
                          s.badDataRetries, BLESerial::kBadDataMaxRetries);
        }
      } else {
        if (s.logLevel >= WARNING)
          Serial.printf("EBADDATA persistent (code=%d)\r\n", code);
      }
      s.pendingLen = 0;
      return;
    }

    // end of EBADDATA handling
  
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
      } else {
        if (++s.lkgFailStreak >= LKG_ESCALATE_AFTER_FAILS) {
          uint32_t now = (uint32_t)micros();

          if ((now - s.lastEscalateAtUs) >= ESCALATE_COOLDOWN_US &&
                    s.txBuf.available() >= s.lowWater) {
              s.lastEscalateAtUs = now;
              s.lkgFailStreak    = 0;
              uint32_t next = (s.lkgIntervalUs * LKG_ESCALATE_NUM) / LKG_ESCALATE_DEN;
              if (next < s.minSendIntervalUs) next = s.minSendIntervalUs;
              if (next > BLESerial::kMaxSendIntervalUs) next = BLESerial::kMaxSendIntervalUs;
              s.lkgIntervalUs  = next;
              s.sendIntervalUs = next;
              if (s.logLevel >= INFO)
                  Serial.printf("Escalate LKG to %u\r\n", s.lkgIntervalUs);
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
      s.sendIntervalUs = BLESerial::kMaxSendIntervalUs;
      s.lkgIntervalUs = s.sendIntervalUs;
      if (s.logLevel >= WARNING) {
        Serial.println("Link closed (ENOTCONN/EOS)");
      }
      return;
    } // enmd of disconnect/EOS

    // Unknown/unclassified: drop probe if probing; otherwise no pacing change ------------
    if (s.probing) {
      s.probing = false;
      s.sendIntervalUs = s.lkgIntervalUs;
      s.lkgFailStreak = 0;
    if (s.logLevel >= INFO) {
      Serial.printf("Unclassified issue %u (%s) while probing: revert to LKG=%u\r\n", code, codeName(code), s.sendIntervalUs);
    }
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
  } 
  // end of onSubscribe -------------------------------------------------------------------------------------

private:
  BLESerial* owner;

  // ---- Status code normalization helpers ----
  static inline bool isOkOrDone(int code) {
      return (code == 0 || code == BLE_HS_EDONE || code == 14);
  } // end of isOkOrDone

  static inline bool isMsgSize(int code) {
      return (code == BLE_HS_EMSGSIZE || code == 4);
  } // end of isMsgSize

  static inline bool isBadData(int code) {
      // EBADDATA observed as 9 and 10 across builds; include both
      return (code == BLE_HS_EBADDATA || code == 9 || code == 10);
  } // end of isBadData

  static inline bool isCongestion(int code) {
      // Treat ENOMEM/ENOMEEVT/EBUSY/TIMEOUT as congestion. Accept observed integers too.
      return (code == BLE_HS_ENOMEM     || code == 6  ||
              code == BLE_HS_ENOMEEVT   || code == 12 || code == 20 ||
              code == BLE_HS_EBUSY      || code == 15 ||
              code == BLE_HS_ETIMEOUT   || code == 13);
  } // end of isCongestion

  static inline bool isDisconnectedOrEOS(int code) {
      // ENOTCONN and EOS; observed EOS sometimes 10/11 in logs
      return (code == BLE_HS_ENOTCONN || code == 7 || 
              code == BLE_HS_EOS      || code == 10 || code == 11);
  } // end of isDisconnectedOrEOS

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
          case 12: return "ENOMEEVT(12)";
          case 13: return "ETIMEOUT(13)";
          case 14: return "EDONE(14)";
          case 15: return "EBUSY(15)";
          case 16: return "EDISABLED(16)";
          case 18: return "ENOTSYNCED(18)";
          case 19: return "EAUTHEN(19)";
          case 20: return "EAUTHOR/ENOMEEVT?(20)";
          default: return "UNKNOWN";
      }
  } // end of codeName

}; // end of TxCallbacks =====================================================

class BLESerial:LineReader {
public:
    explicit BLESerial(Stream& s): LineReader(s) {}
    // Non-blocking: returns true when a full line (CR, LF, or CRLF) is ready
    bool poll(char* out, size_t maxLen) {
        while (available()) {
            int c = read();
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

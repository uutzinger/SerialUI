# include <Arduino.h>
#include <BLESerial.h>
#include <Linereader.h>

constexpr unsigned long BAUDRATE     = 2'000'000UL;
constexpr uint8_t       LED_PIN      = LED_BUILTIN;
constexpr bool          useTaskPump  = true;   // set to 'false' to use polling mode

BLESerial               ble;
LineReader<128>         lr;

char                    line[128];                // command line buffer
char                    data[256];                // data output buffer
bool                    paused          = false;  // do not generated data
unsigned long           lastBlinkUs     = 0;      // last LED blink time (microseconds)
unsigned long           blinkIntervalUs = 800'000; // LED blink interval (microseconds)
bool                    ledState        = LOW;     // current LED state
unsigned long           lastDataUs      = 0;       // last data rate calc time (microseconds)
unsigned long           dataCount       = 0;
unsigned long           dataCountPrev   = 0;
unsigned long           currentTime;
unsigned long           rate            = 0;

void setup() {
  // Initialize LED
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.begin(BAUDRATE);
  while (!Serial && millis() < 5000) { delay(10); }

  Serial.println(F("=================================================================="));
  Serial.println(F("BLE Serial Test Program"));
  Serial.println(F("=================================================================="));

  // Initialize PSRAM (optional check)
  #ifdef ARDUINO_ARCH_ESP32
    if (psramInit()) {
      Serial.printf("PSRAM: total=%d free=%d\r\n", ESP.getPsramSize(), ESP.getFreePsram());
    } else {
      Serial.println("No PSRAM available.");
    }
  #endif

  #ifdef ARDUINO_ARCH_ESP32
    ble.setPumpMode(useTaskPump ? BLESerial::PumpMode::Task : BLESerial::PumpMode::Polling);
  #endif

  if (!ble.begin(
        BLESerial::Mode::Fast, 
        "BLESerialDevice", 
        false
       )
     )  {
    Serial.println(F("BLESerial begin() failed"));
    while (true) delay(1000);
  }

  // Optionally configure parameters before calling begin()
  // ble.setTxPower(BLE_TX_DBP9);    // set transmit power
  // ble.setMTU(517);                // set desired MTU

}


void loop() {
  currentTime = micros();

  // BLE Serial Update
  // =======================================================
  if (!useTaskPump) {
    ble.update(); // polling pump
  }

  // Command Receiver
  // =======================================================
  if (lr.poll(ble, line, sizeof(line))) 
  { 
    auto reply = [&](const char* msg){
      Serial.println(msg);
      ble.write(reinterpret_cast<const uint8_t*>(msg), strlen(msg));
      ble.write(reinterpret_cast<const uint8_t*>("\r\n"), 2);
    };

    if (strcasecmp(line, "pause") == 0) {
      paused = true;
      reply("TX paused");
    } else if (strcasecmp(line, "resume") == 0) {
      paused = false;
      reply("TX resumed");
    } else if (strcasecmp(line, "status") == 0) {
      const char* modeStr = "Balanced";
      switch (ble.modeValue()) {
        case BLESerial::Mode::Fast:      modeStr = "Fast";      break;
        case BLESerial::Mode::LowPower:  modeStr = "LowPower";  break;
        case BLESerial::Mode::LongRange: modeStr = "LongRange"; break;
        default: break;
      }
      snprintf(data, sizeof(data),
              "Status: connected=%d txBuffered=%u mode=%s rssi=%d",
              ble.connected(), (unsigned)ble.txBuffered(), modeStr, ble.rssi());
      reply(data);
  }

    
  // Data Generator
  // =======================================================
  if (!paused && ble.connected() && ble.writeReady()) {
    if (currentTime - lastDataUs >= 1'000'000UL) {
      rate          = dataCount - dataCountPrev;
      lastDataUs    = currentTime;
      dataCountPrev = dataCount;
    }

    int dataLen = snprintf(data, sizeof(data),
                   "count=%lu rate=%lu/s\r\n", dataCount++, rate);

    ble.write(reinterpret_cast<const uint8_t*>(data), (size_t)dataLen);
  }

  // Blink LED
  // =======================================================
  if ((currentTime - lastBlinkUs) >= blinkIntervalUs) {
    lastBlinkUs = currentTime;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
    blinkIntervalUs = ledState ? 200'000 : 800'000;
  }

}



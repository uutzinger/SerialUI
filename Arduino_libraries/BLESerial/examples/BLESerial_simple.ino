// ===== SERIAL ======
inline constexpr unsigned long BAUDRATE              = 2'000'000UL;

void setup() {

  pinMode(ledPin, OUTPUT);

  Serial.begin(BAUDRATE);

  currentTime = millis();
  while (!Serial && ( (millis() - currentTime) < 10000 )) { delay(5); }
  Serial.println("==================================================================");
  Serial.println("BLE Serial Test Program");
  Serial.println("==================================================================");

  // Initialize PSRAM (optional check)
  if (psramInit()) {
    Serial.println("PSRAM initialized successfully.");
    Serial.printf("Total PSRAM: %d bytes\r\n", ESP.getPsramSize());
    Serial.printf("Free PSRAM: %d bytes\r\n", ESP.getFreePsram());
  } else {
    Serial.println("No PSRAM available.");
  }


  // Initialize BLESerial driver
  driver.begin("BLESerialDevice");   // device name

  // Optionally configure parameters before calling begin()
  // driver.setTxPower(ESP_PWR_LVL_P9);    // set transmit power
  // driver.setMTU(517);                    // set desired MTU
  // driver.setConnectionInterval(24, 40); // set min/max connection interval (in units of 1.25ms)

    LineReader lr(driver);

}

void loop() {
    char line[128];
    if (lr.poll(line, sizeof(line))) {
    // parse command
    }

    driver.update();    // pumps TX and handles time-based backoff
    // rest of app
}



/*

  Main File

  This file handles the timing and main loop for data generation. It calls the appropriate data generation function based on the scenario.
  It also accepts commands over serial to change the interval, scenario, or pause the data generation.

  Commands:

    interval <value>: Sets the data generation interval to the specified value in milliseconds.
    scenario <value>: Changes the scenario to the specified value (1 to 5).
    pause: Pauses the data generation.
    resume: Resumes the data generation if it was paused.

*/

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

#include "esp_bt_device.h"
#include "esp_bt_main.h"
#include "esp_gap_ble_api.h"

#include "src/RingBuffer.h"

#include "src/dataGeneratorAgriculturalMonitoring.h" // Include the data generator for the Agricultural Monitoring System
#include "src/dataGeneratorCanSat.h"                 // Include the data generator for CanSat
#include "src/dataGeneratorEnvironmental.h"          // Include the data generator for the Environmental Monitoring System
#include "src/dataGeneratorMedicalMonitoring.h"      // Include the data generator for the Medical Monitoring System
#include "src/dataGeneratorPowerSystem.h"            // Include the data generator for the Power Monitoring System
#include "src/dataGeneratorSineWave.h"            // Include the data generator for the Power Monitoring System

// Serial Settings
#define BAUDRATE               500000 // 500 kBaud

// Low Energy Bluetooth
#define BLE_PASSKEY            123456 // Passkey
#define DEVICE_NAME    "MediBrick_BLE"// Name shown when BLE scans for devices
#define BLE_MTU                   247 // Max size in bytes to send at once. MAX ESP 517, Android 512, Nordic 247
// Nordic UART Serial (NUS)
#define SERVICE_UUID           "6E400001-B5A3-F393-E0A9-E50E24DCCA9E" // UART service UUID
#define CHARACTERISTIC_UUID_RX "6E400002-B5A3-F393-E0A9-E50E24DCCA9E" // UART RX characteristic
#define CHARACTERISTIC_UUID_TX "6E400003-B5A3-F393-E0A9-E50E24DCCA9E" // UART TX characteristic

BLEServer          *pServer              = NULL;                  // BLE Server
BLECharacteristic  *pTxCharacteristic;                            // BLE Characteristics 
bool                deviceConnected      = false;                 // Status
bool                devicePreviouslyConnected   = false;          // for automatic advertising
uint32_t            passkey              = BLE_PASSKEY;           // Define your passkey here
uint8_t             txValue              = 0;
size_t              bytesSent            = 0;

#define BUFFERSIZE               2048 // Buffer to hold data, should be a few times larger than FRAME_SIZE
#define FRAME_SIZE          BLE_MTU-3 // MTU minus ATT header size
#define TABLESIZE                 64  // Number of samples in one full cycle for sine, sawtooth etc

int           scenario = 7; // Default scenario 
                            // 1 Agriculture,   2 Satelite, 3 Environmental,
                            // 4  Medical,      5 Power,    6 Stereo Sinewave, 
                            // 7 Mono Sinewave, 8 Mono Sinewave Header, 
                            // 9 Mono Sawtooth, 10 64 Chars"

// Configuration (adjustable frequencyuencies and amplitudes)
float frequency   = 500.0;   // High frequency (Hz)
float amplitude   = 1024;    // Amplitude for Channel 1
int16_t signalTable[TABLESIZE];

unsigned long currentTime;
unsigned long interval = 10000; // Default interval at which to generate data
int           samplerate =  1000;           //
bool          paused = true;                // Flag to pause the data generation
String        receivedCommand = "";
char          data[1024];
static float  loc = 0;
unsigned long lastMeasurementTime  = 0;     // Last time data was produced

RingBuffer dataBuffer(BUFFERSIZE); // Create a ring buffer

// =============================================================================================
// BLE Service and Characteristic Callbacks

class MyBLEServerCallbacks : public BLEServerCallbacks
{
  void onConnect(BLEServer* pServer, esp_ble_gatts_cb_param_t *param) {
    deviceConnected = true;
    esp_ble_conn_update_params_t conn_params = {
        .min_int = 0x06,  // Minimum connection interval (7.5 ms) // high throughput
        .max_int = 0x0C,  // Maximum connection interval (15 ms)
        .latency = 0,     // Slave latency
        .timeout = 400    // Supervision timeout (4 seconds)
    };
    memcpy(conn_params.bda, param->connect.remote_bda, sizeof(esp_bd_addr_t));
    esp_ble_gap_update_conn_params(&conn_params);        
  }

  void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      pServer->startAdvertising();  // Restart advertising immediately
      Serial.println("Client disconnected. Advertising restarted.");
  }

};

class MyBLECharacteristicCallbacks : public BLECharacteristicCallbacks
{
  void onWrite(BLECharacteristic *pCharacteristic) {
    receivedCommand = pCharacteristic->getValue();

    if (receivedCommand.length() > 0) {
      Serial.print("Received: ");
      Serial.println(receivedCommand.c_str());
    }
  }

};

// =============================================================================================

void setup()
{
  Serial.begin(500000);
  
  Serial.println("=================================");
  Serial.println("Initializing BLE UART...");  

  // Initialize PSRAM (optional check)
  if (psramInit()) {
    Serial.println("PSRAM initialized successfully.");
    Serial.printf("Total PSRAM: %d bytes\n", ESP.getPsramSize());
    Serial.printf("Free PSRAM: %d bytes\n", ESP.getFreePsram());
  } else {
    Serial.println("PSRAM initialization failed. Ensure PSRAM is enabled in the board configuration.");
  }

  Serial.println("Setting up BLE Nordic UART.");

  // Create the BLE Device
  BLEDevice::init(DEVICE_NAME);
  BLEDevice::setMTU(BLE_MTU);

  // Retrieve and print the Bluetooth MAC address
  const uint8_t* mac = esp_bt_dev_get_address();
  if (mac) {
    Serial.print("MAC: ");
    for (int i = 0; i < 6; i++) {
      Serial.print(mac[i], HEX);
      if (i < 5) { Serial.print(":"); }
    }
    Serial.println();
  } else {
    Serial.println("Failed to retrieve MAC address.");
  }

  // Create the BLE Server
  BLEServer *pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyBLEServerCallbacks());

  // Set authentication requirements for encryption and MITM protection with bonding
  esp_ble_auth_req_t auth_req = ESP_LE_AUTH_REQ_SC_MITM_BOND;  // Secure Connections, MITM, and Bonding
  esp_ble_gap_set_security_param(ESP_BLE_SM_AUTHEN_REQ_MODE, &auth_req, sizeof(uint8_t));

  // Set the fixed passkey for pairing
  esp_ble_gap_set_security_param(ESP_BLE_SM_SET_STATIC_PASSKEY, &passkey, sizeof(uint32_t));

  // Set I/O capabilities to display only, requiring the user to enter a passkey
  uint8_t iocap = ESP_IO_CAP_OUT;  // ESP32 displays the passkey, user inputs it on the client device
  // uint8_t iocap = ESP_IO_CAP_IO;  // ESP32 display the passkey, user inputs it on the client device
  //uint8_t iocap = ESP_IO_CAP_IN;  // ESP32 does not display the passkey, user inputs it on the client device
  esp_ble_gap_set_security_param(ESP_BLE_SM_IOCAP_MODE, &iocap, sizeof(uint8_t));

  // Set key size to maximum (16 bytes)
  uint8_t key_size = 16;
  esp_ble_gap_set_security_param(ESP_BLE_SM_MAX_KEY_SIZE, &key_size, sizeof(uint8_t));

  // Configure key types for encryption
  uint8_t init_key = ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK;
  uint8_t rsp_key  = ESP_BLE_ENC_KEY_MASK | ESP_BLE_ID_KEY_MASK;
  esp_ble_gap_set_security_param(ESP_BLE_SM_SET_INIT_KEY, &init_key, sizeof(uint8_t));
  esp_ble_gap_set_security_param(ESP_BLE_SM_SET_RSP_KEY,  &rsp_key,  sizeof(uint8_t));

  // Create the BLE Service
  BLEService *pService = pServer->createService(SERVICE_UUID);

  // Create the BLE Characteristic for TX
  pTxCharacteristic = pService->createCharacteristic(
                      CHARACTERISTIC_UUID_TX,
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
  pTxCharacteristic->addDescriptor(new BLE2902());

 // Create the BLE Characteristic for RX
  BLECharacteristic * pRxCharacteristic = pService->createCharacteristic(
                                          CHARACTERISTIC_UUID_RX,
                                          BLECharacteristic::PROPERTY_WRITE
                                        );
  pRxCharacteristic->setCallbacks(new MyBLECharacteristicCallbacks());

  // Start the service
  pService->start();

 // Configure and start advertising
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
 // Add the service UUID to the advertisement
  pAdvertising->addServiceUUID(SERVICE_UUID);
  // Optionally, set the advertisement type and other parameters
  pAdvertising->setScanResponse(true);  // Enable scan response to include more data
  pAdvertising->setMinPreferred(0x06);  // Set minimum preferred connection interval in units of 1.25ms = 7.5ms
  pAdvertising->setMinPreferred(0x12);  // Set maximum preferred connection interval in units of 1.25ms =  22.5ms
  // Add Manufacturer Data or other advertisement data if needed
  // pAdvertising->addManufacturerData(0xFFFF, "Beta");
  // Start advertising
  pServer->startAdvertising();

  Serial.println("BLE UART Ready");


  Serial.println("=================================");
  Serial.println("Commands are:");
  Serial.println("pause");
  Serial.println("resume");
  Serial.println("interval >=0 ms");
  Serial.println("samplerate");
  Serial.println("scenario number: ");
  Serial.println("   1 Agriculture, 2 Satelite, 3 Environmental, 4 Medical, 5 Power");
  Serial.println("   6 Stereo Sinewave, 7 Mono Sinewave, 8 Mono Sinewave Header, 9 Mono Sawtooth, 10 Squarewave");
  Serial.println("  11 64 Chars");
  // Prints current settings
  Serial.println("=================================");
  Serial.println("Current Settings:");
  Serial.println("Interval:   " + String(interval) + " microseconds");
  Serial.println("Samplerate: " + String(samplerate) + " Hz");
  Serial.println("Scenario:   " + String(scenario));
  Serial.println("Paused:     " + String(paused ? "Yes" : "No"));

  randomSeed(analogRead(0));
  updateSignalTable(scenario);

  lastMeasurementTime  = micros();

}

// =============================================================================================

void loop()
{

  unsigned long currentTime = micros();
  size_t ret;

  // Handle Commands
  // -----------------------------------------------------------------------
  if (deviceConnected && !receivedCommand.isEmpty())
  {
    handleBLECommands();
    receivedCommand = ""; // Clear the command buffer
  }

  // Create Data
  // -----------------------------------------------------------------------
  if (!paused)
  {
    if (currentTime - lastMeasurementTime >= interval)
    {
      lastMeasurementTime = currentTime;
      unsigned int measurementTime = (unsigned int) currentTime;
      ret = generateData();
      if (ret == 0) {
        pTxCharacteristic->setValue("Buffer overflow!");
        pTxCharacteristic->notify();
      }
    }
  }

  // Send Data
  // ------------------------------------------------------------------------
  // If a device is connected, send data in chunks
  if (deviceConnected) {
    while ( dataBuffer.size() >= FRAME_SIZE ) {
      size_t bytesRead = dataBuffer.pop(data, FRAME_SIZE);
      pTxCharacteristic->setValue((uint8_t*)data, bytesRead);
      pTxCharacteristic->notify();  // Send the chunk
      Serial.println("Sent chunk.");

    }
  }

}

// =============================================================================================

void handleBLECommands()
{

  Serial.println("Command: " + receivedCommand);

  if (receivedCommand.length() >= 8 && receivedCommand.startsWith("interval"))
  {
    int newInterval = receivedCommand.substring(8).toInt();
    if (newInterval > 0)
    {
      interval = newInterval;
      pTxCharacteristic->setValue("Interval set to " + String(interval) + " micro secods");
      pTxCharacteristic->notify();
    }
    else
    {
      pTxCharacteristic->setValue("Invalid interval value.");
      pTxCharacteristic->notify();
    }
  }
  
  else if (receivedCommand.length() >= 10 && receivedCommand.startsWith("samplerate"))
  {
    int newSamplerate = receivedCommand.substring(10).toInt();
    if (newSamplerate > 0)
    {
      samplerate = newSamplerate;
      pTxCharacteristic->setValue("Samplerate set to " + String(samplerate) + " Hz");
      pTxCharacteristic->notify();
      if ((samplerate > 10000) && (interval > 5000)) {
        interval = 1000;
        Serial.println("Interval set to " + String(interval) + " micro seconds");
        pTxCharacteristic->setValue("Interval set to " + String(interval) + " micro secods");
        pTxCharacteristic->notify();
      }
    }
    else
    {
      pTxCharacteristic->setValue("Invalid samplerate value.");
      pTxCharacteristic->notify();
    }
  }

  else if (receivedCommand.length() >= 8 && receivedCommand.startsWith("scenario"))
  {
    int newScenario = receivedCommand.substring(8).toInt();
    if (newScenario >= 1 && newScenario <= 11)
    {
      scenario = newScenario;
      updateSignalTable(scenario);
      pTxCharacteristic->setValue("Scenario set to " + String(scenario));
      pTxCharacteristic->notify();
    }
    else
    {
      pTxCharacteristic->setValue("Invalid scenario value.");
      pTxCharacteristic->notify();
    }
  }

  else if (receivedCommand == "pause")
  {
    paused = true;
    pTxCharacteristic->setValue("Data generation paused.");
    pTxCharacteristic->notify();
  }

  else if (receivedCommand == "resume")
  {
    paused = false;
    pTxCharacteristic->setValue("Data generation resumed.");
    pTxCharacteristic->notify();
  }

  else if (receivedCommand.equals("?"))
    {
      // Prints current settings
      pTxCharacteristic->setValue("=================================");
      pTxCharacteristic->notify();
      pTxCharacteristic->setValue("Current Settings:");
      pTxCharacteristic->notify();
      pTxCharacteristic->setValue("Interval:   " + String(interval) + " microseconds");
      pTxCharacteristic->notify();
      pTxCharacteristic->setValue("Samplerate: " + String(samplerate) + " Hz");
      pTxCharacteristic->notify();
      pTxCharacteristic->setValue("Scenario:   " + String(scenario));
      pTxCharacteristic->notify();
      pTxCharacteristic->setValue("Frequency:  " + String(frequency) + " Hz");
      pTxCharacteristic->notify();
      pTxCharacteristic->setValue("Paused:     " + String(paused ? "Yes" : "No"));
      pTxCharacteristic->notify();
    }

  else
  {
    pTxCharacteristic->setValue("=================================");
    pTxCharacteristic->notify();
    pTxCharacteristic->setValue("Commands are:");
    pTxCharacteristic->notify();
    pTxCharacteristic->setValue("pause");
    pTxCharacteristic->notify();
    pTxCharacteristic->setValue("resume");
    pTxCharacteristic->notify();
    pTxCharacteristic->setValue("interval >=0 micro seconds");
    pTxCharacteristic->notify();
    pTxCharacteristic->setValue("samplerate");
    pTxCharacteristic->notify();
    pTxCharacteristic->setValue("scenario number: ");
    pTxCharacteristic->notify();
    pTxCharacteristic->setValue("   1 Agriculture, 2 Satelite, 3 Environmental, 4 Medical, 5 Power");
    pTxCharacteristic->notify();
    pTxCharacteristic->setValue("   6 Stereo Sinewave, 7 Mono Sinewave, 8 Mono Sinewave Header, 9 Mono Sawtooth, 10 Squarewave");
    pTxCharacteristic->notify();
    pTxCharacteristic->setValue("  11 64 Chars");
    pTxCharacteristic->notify();
  }
}

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
    return(generateDataStereo(samplerate, interval));
    break;
  case 7:
    return(generateData(samplerate, interval));
    break;
  case 8:
    return(generateData(samplerate, interval));
    break;
  case 9:
    return(generateData(samplerate, interval));
    break;
  case 10:
    return(generateData(samplerate, interval));
    break;
  case 11:
    return(generate64Chars());
    break;
  default:
    pTxCharacteristic->setValue("  11 64 Chars");
    pTxCharacteristic->notify();
    return 1;
    break;
  }
}

size_t generateDataHeader(int samplerate, unsigned long interval, String header) {
    char* ptr = data;
    int samples = (samplerate * interval) / 1000000;
    float stepSize = (TABLESIZE * frequency) / float(samplerate);

    for (int i = 0; i < samples; i++) {
        int idx = int(loc) % TABLESIZE;
        int16_t value = signalTable[idx];

        if (ptr >= data + sizeof(data) - 10) break; 
        ptr += snprintf(ptr, data + sizeof(data) - ptr, "%s: %d\n", header.c_str(), value);

        loc += stepSize;
    }

size_t length = min((size_t)strlen(data), sizeof(data) - 1);
    return dataBuffer.push(data, length, false);
}

size_t generateData(int samplerate, unsigned long interval) {
    char* ptr = data;
    int samples = (samplerate * interval) / 1000000;
    float stepSize = (TABLESIZE * frequency) / float(samplerate);

    for (int i = 0; i < samples; i++) {
        int idx = int(loc) % TABLESIZE;
        int16_t value = signalTable[idx];
        
        if (ptr >= data + sizeof(data) - 10) break; 
        ptr += snprintf(ptr, data + sizeof(data) - ptr, "%d\n", value);

        loc += stepSize;
    }

    size_t length = min((size_t)strlen(data), sizeof(data) - 1);
    return dataBuffer.push(data, length, false);
}

size_t generateDataStereo(int samplerate, unsigned long interval) {
    char* ptr = data;
    int samples = (samplerate * interval) / 1000000;
    float stepSize = (TABLESIZE * frequency) / float(samplerate);

    for (int i = 0; i < samples; i++) {
        int idx = int(loc) % TABLESIZE;
        int16_t value = signalTable[idx];

        if (ptr >= data + sizeof(data) - 10) break; 
        ptr += snprintf(ptr, data + sizeof(data) - ptr, "%d, %d\n", value, value);

        loc += stepSize;
    }

    size_t length = min((size_t)strlen(data), sizeof(data) - 1);

    return dataBuffer.push(data, length, false);
}

const char FIXED_64_CHAR[65] =  "ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZ.0123456789\n"; 

size_t generate64Chars() {
    return dataBuffer.push(FIXED_64_CHAR, 64, false);  // Push 64 bytes to ring buffer
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

// Corrected updateSineWaveTable function
void updateSineWaveTable() {
    pTxCharacteristic->setValue("Updating sine table...");
    pTxCharacteristic->notify();
    for (int i = 0; i < TABLESIZE; i++) {
        int16_t value1 = int16_t(amplitude       * sin(( 2.0 * M_PI * i) / float(TABLESIZE))); 
        int16_t value2 = int16_t((amplitude / 4) * sin((10.0 * M_PI * i) / float(TABLESIZE))); // Adjusted frequency
        signalTable[i] = value1 + value2;
    }
}


void updateSawToothTable() {
    pTxCharacteristic->setValue("Updating sawtooth table...");
    pTxCharacteristic->notify();

    for (int i = 0; i < TABLESIZE; i++) {
        int16_t value = int16_t(-amplitude + 2.* amplitude * (float(i) / float(TABLESIZE)));
        signalTable[i] = value;
    }
}

void updateSquareWaveTable() {
    pTxCharacteristic->setValue("Updating square table...");
    pTxCharacteristic->notify();

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


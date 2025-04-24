/*

  Main File

  This file handles the timing and main loop for data generation. It calls the appropriate data generation function based on the scenario.
  It also accepts commands over serial to change the interval, scenario, or pause the data generation.

  Serial Commands:

    interval <value>: Sets the data generation interval to the specified value in micro seconds.
    frequency <value> sets the frequency of the sine, saw tooth or squarewave in Hz
    scenario <value>: Changes the scenario to the specified value (1 to 5).
    pause: Pauses the data generation.
    resume: Resumes the data generation if it was paused.

*/

#include <cmath>
#include <RingBuffer.h>

// Serial Settings
#define BAUDRATE              1000000 // 1 MBaud

// Measurement
#define BUFFERSIZE              2048  // Buffer to hold data, should be a few times larger than FRAME_SIZE
#define FRAME_SIZE               128  // Max size in bytes to send at once.
#define TABLESIZE                 64  // Number of samples in one full cycle for sine, sawtooth etc

int           scenario = 20; // Default scenario 
                            // 1 Agriculture,   2 Satelite, 3 Environmental,
                            // 4  Medical,      5 Power,    6 Stereo Sinewave, 
                            // 7 Mono Sinewave, 8 Mono Sinewave Header, 
                            // 9 Mono Sawtooth, 10 64 Chars", 20 USB Speed Tester

// Configuration (adjustable frequencyuencies and amplitudes)
float frequency   = 100.0;   // Frequency (Hz)
float amplitude   = 1024;    // Amplitude for Channel 1
int16_t signalTable[TABLESIZE];
static float  loc = 0;
size_t ret;

RingBuffer<char, BUFFERSIZE> dataBuffer;

/*------------------------------------------------------------------------ 
General
--------------------------------------------------------------------------
*/

unsigned long currentTime;
unsigned long interval = 10000;             // Default interval at which to generate data in micro seconds
int           samplerate = 5000;            // Samples per second
bool          paused = true;                // Flag to pause the data generation
String        receivedCommand = "";
char          data[1024];                   // Serial data buffer
unsigned long lastDataGenerationTime  = 0;     // Last time data was produced

/*------------------------------------------------------------------------ 
USB SPeed Tester
--------------------------------------------------------------------------
*/

unsigned long lastUSBTime  = 0;     // Last time data was produced
unsigned long lastCounts = 10000000; 
unsigned long currentCounts = 10000000;     // Number of lines sent
unsigned long countsPerSecond = 0;

// =============================================================================================
// SETUP
// =============================================================================================

void setup()
{
  Serial.begin(BAUDRATE);
  while (!Serial) { delay(5); }

  Serial.println("=================================");
  Serial.println("Commands are:");
  Serial.println("pause");
  Serial.println("resume");
  Serial.println("interval >=1 micro seconds");
  Serial.println("samplerate");
  Serial.println("scenario ");
  Serial.println("   1 Agriculture, 2 Satelite, 3 Environmental, 4 Medical, 5 Power");
  Serial.println("   6 Stereo Sinewave, 7 Mono Sinewave, 8 Mono Sinewave Header, 9 Mono Sawtooth, 10 Squarewave");
  Serial.println("  11 64 Chars, 12 USB Tester");
  // Prints current settings
  Serial.println("=================================");
  Serial.println("Current Settings:");
  Serial.println("Interval:   " + String(interval) + " microseconds");
  Serial.println("Samplerate: " + String(samplerate) + " Hz");
  Serial.println("Scenario:   " + String(scenario));
  Serial.println("Frequency:  " + String(frequency));
  Serial.println("Paused:     " + String(paused ? "Yes" : "No"));

  updateSignalTable(scenario);

  lastDataGenerationTime = micros();
  lastUSBTime = micros();
}

// =============================================================================================
// LOOP
// =============================================================================================

void loop()
{

  currentTime = micros();

  // Handle Commands
  // -----------------------------------------------------------------------
  if (Serial.available() > 0)
  {
    handleSerialCommands();
  }

  // Create Data
  // -----------------------------------------------------------------------
  if (!paused)
  {
    if (currentTime - lastDataGenerationTime > interval)
    {
      lastDataGenerationTime = currentTime;
      ret = generateData();
      if (ret == 0) {
        Serial.println("Ring buffer overflow");
      }
    }
  }

  // Send Data
  // ------------------------------------------------------------------------
  while (dataBuffer.available() > 0) {
      size_t bytesRead = dataBuffer.pop(data, FRAME_SIZE);
      Serial.write(data, bytesRead);
  }
}

// =============================================================================================
// Support Functsion
// =============================================================================================

/* 
----------------------------------------------------------
 User Input
----------------------------------------------------------
*/
void handleSerialCommands()
{
  String command = Serial.readStringUntil('\n');
  command.trim(); // Remove any leading/trailing whitespace

  if (command.startsWith("interval"))
  {
    int newInterval = command.substring(8).toInt();
    if (newInterval > 0)
    {
      interval = newInterval;
      Serial.println("Interval set to " + String(interval) + " micro seconds");
      dataBuffer.clear();
      updateSignalTable(scenario);
    }
    else
    {
      Serial.println("Invalid interval value.");
    }
  }
  else if (command.startsWith("samplerate"))
  {
    int newSamplerate = command.substring(10).toInt();
    if (newSamplerate > 0)
    {
      samplerate = newSamplerate;
      Serial.println("Samplerate set to " + String(samplerate) + " Hz");
      if ((samplerate > 10000) && (interval > 5000)) {
        interval = 1000;
        Serial.println("Interval set to " + String(interval) + " micro seconds");
      }
    }
    else
    {
      Serial.println("Invalid samplerate value.");
    }
  }
  else if (command.startsWith("scenario"))
  {
    int newScenario = command.substring(8).toInt();
    if (newScenario >= 1 && newScenario <= 100)
    {
      scenario = newScenario;
      updateSignalTable(scenario);
      dataBuffer.clear();
      Serial.println("Scenario set to " + String(scenario));
    }
    else
    {
      Serial.println("Invalid scenario value.");
    }
  }
  else if (command.startsWith("frequency"))
  {
    float new_freq = command.substring(9).toFloat();
    if (new_freq >= 0 && new_freq <= 10000)
    {
      frequency = new_freq;
      updateSignalTable(scenario);
      dataBuffer.clear();
      Serial.println("Frequency set to " + String(frequency));
    }
    else
    {
      Serial.println("Invalid frequency value.");
    }
  }
  else if (command.equals("pause"))
  {
    paused = true;
    Serial.println("Data generation paused.");
  }
  else if (command.equals("resume"))
  {
    paused = false;
    dataBuffer.clear();
    Serial.println("Data generation resumed.");
  }
  else if (command.equals("?"))
    {
        // Prints current settings
        Serial.println("=================================");
        Serial.println("Current Settings:");
        Serial.println("Paused:     " + String(paused ? "Yes" : "No"));
        Serial.println("Scenario:   " + String(scenario));
        Serial.println("Interval:   " + String(interval) + " microseconds");
        Serial.println("Samplerate: " + String(samplerate) + " Hz");
        Serial.println("Frequency:  " + String(frequency) + " Hz");
    }
  else
  {
    Serial.println("=================================");
    Serial.println("Commands are:");
    Serial.println("pause");
    Serial.println("resume");
    Serial.println("interval >=0 ms");
    Serial.println("samplerate");
    Serial.println("frequency 0..10000");    
    Serial.println("scenario number: ");
    Serial.println("   1 Agriculture,    2 Satelite,             3 Environmental, ");
    Serial.println("   4 Medical,        5 Power                 6 Stereo Sinewave, ");
    Serial.println("   7 Mono Sinewave,  8 Mono Sinewave Header, 9 Mono Sawtooth, ");
    Serial.println("  10 Squarewave,    11 64 Chars,            20 USB Speed Tester");
  }
}

/* 
----------------------------------------------------------
 Data Generation Selector
----------------------------------------------------------
*/

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
    return(generateDataHeader(samplerate, interval, String("Sine")));
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
  case 20:
    return(generateStoffregen());
    break;
  default:
    Serial.println("Invalid scenario selected.");
    return 1;
    break;
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

// Corrected updateSineWaveTable function
void updateSineWaveTable() {
    Serial.println("Updating sine table...");
    for (int i = 0; i < TABLESIZE; i++) {
        int16_t value1 = int16_t(amplitude       * sin(( 2.0 * M_PI * i) / float(TABLESIZE))); 
        // int16_t value2 = int16_t((amplitude / 4) * sin((10.0 * M_PI * i) / float(TABLESIZE))); // Adjusted frequency
        // signalTable[i] = value1 + value2;
        signalTable[i] = value1;
    }
}


void updateSawToothTable() {
    Serial.println("Updating sawtooth table...");

    for (int i = 0; i < TABLESIZE; i++) {
        int16_t value = int16_t(-amplitude + 2.* amplitude * (float(i) / float(TABLESIZE)));
        signalTable[i] = value;
    }
}

void updateSquareWaveTable() {
    Serial.println("Updating square table...");

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

// =============================================================================================
// Data Generators
// =============================================================================================

/* 
----------------------------------------------------------
 Data Generation from Table with Header
----------------------------------------------------------
*/
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


/* 
----------------------------------------------------------
 Data Generator from Table
----------------------------------------------------------
*/
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

/* 
----------------------------------------------------------
 Data Generation from Table: Stereo
----------------------------------------------------------
*/

size_t generateDataStereo(int samplerate, unsigned long interval) {
    char* ptr = data;
    int samples = (samplerate * interval) / 1000000;
    float stepSize = (TABLESIZE * frequency) / float(samplerate);
    int offset = int(stepSize * 2);
    int idx;
    int16_t value1;
    int16_t value2;

    for (int i = 0; i < samples; i++) {
        idx = int(loc) % TABLESIZE;
        value1 = signalTable[idx];
        idx = int(loc + offset) % TABLESIZE;
        value2 = signalTable[idx];

        if (ptr >= data + sizeof(data) - 10) break; 
        ptr += snprintf(ptr, data + sizeof(data) - ptr, "%d, %d\n", value1, value2);

        loc += stepSize;
    }

    size_t length = min((size_t)strlen(data), sizeof(data) - 1);

    return dataBuffer.push(data, length, false);
}

/* 
----------------------------------------------------------
 Data Generator: 64 Characters
----------------------------------------------------------
*/

const char FIXED_64_CHAR[65] =  "ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZ.0123456789\n"; 

size_t generate64Chars() {
    return dataBuffer.push(FIXED_64_CHAR, 64, false);  // Push 64 bytes to ring buffer
}

/* 
----------------------------------------------------------
 Data Generator for USB test, includes line counter and lines per second
----------------------------------------------------------
*/
size_t generateStoffregen() {
  char line[40];  // Sufficient size: 15 (count) + 14 (text) + 6 (lines/sec) + 2 (\n\r) + 1 (\0 safety)
  size_t len;

  len = snprintf(line, sizeof(line), "count=%9lu, lines/sec=%6lu\n", currentCounts, countsPerSecond);

  if (len >= sizeof(line)) {
    len = sizeof(line) - 1;
    line[len] = '\0';
  }

  currentCounts++;

  // update every second
  if (currentTime - lastUSBTime > 1000000) {
    countsPerSecond = currentCounts - lastCounts;
    lastCounts = currentCounts;
    lastUSBTime = currentTime;
  }

  return dataBuffer.push(line, len, false);
}

/* 
----------------------------------------------------------
 Data Generator for Agriculture Data
----------------------------------------------------------
*/

size_t  generateAgriculturalMonitoringData()
{

  float soilMoisture = random(200, 800) / 10.0;          // Soil moisture in percentage
  float soilTemperature = random(100, 350) / 10.0;       // Soil temperature in Celsius
  float airTemperature = random(150, 350) / 10.0;        // Air temperature in Celsius
  float airHumidity = random(300, 900) / 10.0;           // Air humidity in percentage
  float lightIntensity = random(2000 / 100, 1000 / 100); // Light intensity in lux/100
  float pHLevel = random(50, 80) / 10.0;                 // Soil pH level
  int leafWetness = random(0, 15);                       // Leaf wetness
  float co2Level = random(300 / 10, 800 / 10);           // CO2 level in ppm/10
  float windSpeed = random(0, 200) / 10.0;               // Wind speed in m/s
  float rssi = random(-90, -30);                         // RSSI value

  sprintf(data,"SoilMoisture: %f, SoilTemperature: %f, AirTemperature: %f,AirHumidity: %f,LightIntensity: %f, PHLevel: %f, LeafWetness: %d, CO2Level: %f, WindSpeed: %f,RSSI: %f\n", 
          soilMoisture, soilTemperature, airTemperature, airHumidity,lightIntensity,pHLevel,leafWetness,co2Level,windSpeed,rssi);

  size_t length = min(strlen(data), sizeof(data));
  return(dataBuffer.push(data, length, false));

}

/*
  Data Generator for Power Monitoring System

  This file contains the data generation function for a power monitoring scenario.
*/
size_t generatePowerSystemData()
{
  float voltageSensor = random(300, 500) / 10.0;                // Voltage sensor
  float currentSensor = random(100, 200) / 10.0;                // Current sensor
  float powerSensor = voltageSensor * currentSensor;            // Power sensor
  float energySensor = powerSensor * random(10, 1000) / 1000.0; // Energy sensor
  float batteryLevel = random(0, 100);                          // Battery level percentage
  float temperatureBattery = random(200, 450) / 10.0;           // Battery temperature
  float rssi = random(-90, -30);                                // RSSI value

  char* ptr = data;

  ptr += sprintf(ptr, "VoltageSensor:%.1f,CurrentSensor:%.1f,", voltageSensor, currentSensor);
  ptr += sprintf(ptr, "PowerSensor:%.1f,EnergySensor:%.1f,BatteryLevel:%.1f,", powerSensor, energySensor, batteryLevel);
  ptr += sprintf(ptr, "TemperatureBattery:%.1f,RSSI:%.1f\n", temperatureBattery, rssi);

  size_t length = min(strlen(data), sizeof(data));
  return(dataBuffer.push(data, length, false));
}

/*
  Data Generator for Medical Monitoring System

  This file contains the data generation function for a medical monitoring system scenario.
*/

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
  float rssi = random(-90, -30);                     // RSSI value

  char* ptr = data;

  ptr += sprintf(ptr, "BodyTemp:%.1f,HeartRate:%d,", bodyTemp, heartRate);
  ptr += sprintf(ptr, "BloodPressure:%d/%d,BloodOxygenLevel:%.1f,", bloodPressureSystolic, bloodPressureDiastolic, bloodOxygenLevel);
  ptr += sprintf(ptr, "RespirationRate:%.1f,GlucoseLevel:%.1f,StepCount:%d,", respirationRate, glucoseLevel, stepCount);
  ptr += sprintf(ptr, "RSSI:%.1f\n", rssi);

  size_t length = min(strlen(data), sizeof(data));
  return(dataBuffer.push(data, length, false));
}

/*
  Data Generator for Environmental Monitoring System

  This file contains the data generation function for an environmental monitoring scenario.
*/

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
  float rssi = random(-90, -30);                     // RSSI value

  char* ptr = data;

  ptr += sprintf(ptr, "TempSensor1:%.1f,TempSensor2:%.1f,", tempSensor1, tempSensor2);
  ptr += sprintf(ptr, "HumiditySensor:%.1f,PressureSensor:%.1f,LightSensor:%.1f,", humiditySensor, pressureSensor, lightSensor);
  ptr += sprintf(ptr, "CO2Sensor:%d,AirQualityIndex:%.1f,NoiseLevel:%.1f,", co2Sensor, airQualityIndex, noiseLevel);
  ptr += sprintf(ptr, "RSSI:%.1f\n", rssi);

  size_t length = min(strlen(data), sizeof(data));
  return(dataBuffer.push(data, length, false));
}

/*
  Data Generator for CanSat

  This file contains the data generation function for the CanSat scenario: https://github.com/charles-the-forth/data-generator
*/
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
  int rssi = random(0, 60) - 90;
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

  char* ptr = data;

  ptr += sprintf(ptr, "LightIntensity:%lu,UVIndex:%.1f,", 
                  lightIntensity, uvIndex);
  ptr += sprintf(ptr, "TemperatureCanSat:%.1f,TemperatureMPU:%.1f,TemperatureExternal:%.1f,TemperatureSCD30:%.1f,AmbientTemp:%.1f,ObjectTemp:%.1f,", 
                  temperatureCanSat, temperatureMPU, temperatureExternal, temperatureSCD30, ambientTemp, objectTemp);
  ptr += sprintf(ptr, "HumidityCanSat:%.1f,HumidityExternal:%.1f,HumiditySCD30:%.1f,PressureCanSat:%.1f,", 
                  humidityCanSat, humidityExternal, humiditySCD30, pressureCanSat);
  ptr += sprintf(ptr, "PressureExternal:%.1f,AltitudeCanSat:%.1f,AltitudeExternal:%.1f,", 
                  pressureExternal, altitudeCanSat, altitudeExternal);
  ptr += sprintf(ptr, "AccelerationX:%.1f,AccelerationY:%.1f,AccelerationZ:%.1f,", 
                  accelerationX, accelerationY, accelerationZ);
  ptr += sprintf(ptr, "RotationX:%.1f,RotationY:%.1f,RotationZ:%.1f,MagnetometerX:%.1f,", 
                  rotationX, rotationY, rotationZ, magnetometerX);
  ptr += sprintf(ptr, "MagnetometerY:%.1f,MagnetometerZ:%.1f,LatInt:%u,LonInt:%u,", 
                  magnetometerY, magnetometerZ, latInt, lonInt);
  ptr += sprintf(ptr, "LatAfterDot:%lu,LonAfterDot:%lu,CO2SCD30:%d,CO2CCS811:%d,", 
                  latAfterDot, lonAfterDot, co2SCD30, co2CCS811);
  ptr += sprintf(ptr, "TVOC:%d,O2Concentration:%.1f,A:%.1f,B:%.1f,C:%.1f,D:%.1f,", 
                  tvoc, o2Concentration, a, b, c, d);
  ptr += sprintf(ptr, "E:%.1f,F:%.1f,G:%.1f,H:%.1f,I:%.1f,J:%.1f,K:%.1f,L:%.1f,", 
                  e, f, g, h, i, j, k, l);
  ptr += sprintf(ptr, "R:%.1f,S:%.1f,T:%.1f,U:%.1f,V:%.1f,W:%.1f,", 
                  r, s, t, u, v, w);
  ptr += sprintf(ptr, "NumberOfSatellites:%u,RSSI:%d", numberOfSatellites, rssi);

  ptr += sprintf(ptr, "\n");

  size_t length = min(strlen(data), sizeof(data));
  return(dataBuffer.push(data, length, false));

}
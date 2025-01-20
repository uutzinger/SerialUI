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

#include "src/dataGeneratorAgriculturalMonitoring.h" // Include the data generator for the Agricultural Monitoring System
#include "src/dataGeneratorCanSat.h"                 // Include the data generator for CanSat
#include "src/dataGeneratorEnvironmental.h"          // Include the data generator for the Environmental Monitoring System
#include "src/dataGeneratorMedicalMonitoring.h"      // Include the data generator for the Medical Monitoring System
#include "src/dataGeneratorPowerSystem.h"            // Include the data generator for the Power Monitoring System
#include "src/dataGeneratorSineWave.h"            // Include the data generator for the Power Monitoring System

#include "src/RingBuffer.h"

// Serial Settings
#define BAUDRATE               500000 // 500 kBaud

// Measurement
#define BUFFERSIZE              2048  // Buffer to hold data, should be a few times larger than FRAME_SIZE
#define FRAME_SIZE               128  // Max size in bytes to send at once.
#define TABLESIZE                64  // Number of samples in one full cycle for sine, sawtooth etc

int           scenario = 7; // Default scenario 
                            // 1 Agriculture,   2 Satelite, 3 Environmental,
                            // 4  Medical,      5 Power,    6 Stereo Sinewave, 
                            // 7 Mono Sinewave, 8 Mono Sinewave Header, 
                            // 9 Mono Sawtooth, 10 64 Chars"

unsigned long currentTime;
unsigned long interval = 10000;             // Default interval at which to generate data
int           samplerate =  1000;           //
unsigned long lastMeasurementTime  = 0;     // Last time data was produced
bool          paused = true;                // Flag to pause the data generation
String        receivedCommand = "";
char          data[1024];
static float  loc = 0;

// Configuration (adjustable frequencyuencies and amplitudes)
float frequency   = 500.0;   // High frequency (Hz)
float amplitude   = 1024;    // Amplitude for Channel 1
int16_t signalTable[TABLESIZE];

RingBuffer dataBuffer(BUFFERSIZE); // Create a ring buffer

void setup()
{
  Serial.begin(BAUDRATE);

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

  updateSignalTable(scenario);

  lastMeasurementTime = micros();
}

void loop()
{

  unsigned long currentTime = micros();
  size_t ret;

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
    if (currentTime - lastMeasurementTime >= interval)
    {
      lastMeasurementTime = currentTime;
      ret = generateData();
      if (ret == 0) {
        Serial.println("Ring buffer overflow");
      }
    }
  }

  // Send Data
  // ------------------------------------------------------------------------
  while (dataBuffer.size() > 0) {
      size_t bytesRead = dataBuffer.pop(data, FRAME_SIZE);
      Serial.write(data, bytesRead);
  }
}

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
    }
    else
    {
      Serial.println("Invalid interval value.");
    }
  }
  else if (command.startsWith("scenario"))
  {
    int newScenario = command.substring(8).toInt();
    if (newScenario >= 1 && newScenario <= 11)
    {
      scenario = newScenario;
      updateSignalTable(scenario);
      Serial.println("Scenario set to " + String(scenario));
    }
    else
    {
      Serial.println("Invalid scenario value.");
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
    Serial.println("Data generation resumed.");
  }
  else if (command.equals("?"))
    {
        // Prints current settings
        Serial.println("=================================");
        Serial.println("Current Settings:");
        Serial.println("Interval:   " + String(interval) + " microseconds");
        Serial.println("Samplerate: " + String(samplerate) + " Hz");
        Serial.println("Scenario:   " + String(scenario));
        Serial.println("Frequency:  " + String(frequency) + " Hz");
        Serial.println("Paused:     " + String(paused ? "Yes" : "No"));
    }
  else
  {
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
    Serial.println("Invalid scenario selected.");
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

const char FIXED_64_CHAR1[65] =  "ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZ.0123456789\n"; 

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
    Serial.println("Updating sine table...");
    for (int i = 0; i < TABLESIZE; i++) {
        int16_t value1 = int16_t(amplitude       * sin(( 2.0 * M_PI * i) / float(TABLESIZE))); 
        int16_t value2 = int16_t((amplitude / 4) * sin((10.0 * M_PI * i) / float(TABLESIZE))); // Adjusted frequency
        signalTable[i] = value1 + value2;
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

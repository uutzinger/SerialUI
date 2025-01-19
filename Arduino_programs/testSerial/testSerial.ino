/*

  Main File

  This file handles the timing and main loop for data generation. It calls the appropriate data generation function based on the scenario.
  It also accepts commands over serial to change the interval, scenario, or pause the data generation.

  Serial Commands:

    interval <value>: Sets the data generation interval to the specified value in milliseconds.
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
#define MEASUREMENT_INTERVAL      10  // 10 milli seconds
#define BUFFERSIZE              2048  // Buffer to hold data, should be a few times larger than FRAME_SIZE
#define FRAME_SIZE               128  // Max size in bytes to send at once.

int           scenario = 6; // Default scenario (1: CanSat, 2: Environmental, 3: Power, 4: Medical, 5: Agricultural)
unsigned long currentTime;
unsigned long interval = MEASUREMENT_INTERVAL; // Default interval at which to generate data
unsigned long lastMeasurementTime  = 0;                     // Last time data was produced
bool          paused = true;          // Flag to pause the data generation
String        receivedCommand = "";
char          data[1024];

RingBuffer dataBuffer(BUFFERSIZE); // Create a ring buffer

void setup()
{
  Serial.begin(BAUDRATE);
  Serial.println("System Ready");
  Serial.println("Commands are:");
  Serial.println("pause");
  Serial.println("resume");
  Serial.print("scenario number: ");
  Serial.println("1 Agricultur, 2 Satelite, 3 Environmental, 4 Medical, 5 Power, 6 Stereo Sinewave, 7 Mono Sinewave");
  lastMeasurementTime = millis();
}

void loop()
{

  unsigned long currentTime = millis();
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
      Serial.println("Interval set to " + String(interval) + " ms");
    }
    else
    {
      Serial.println("Invalid interval value.");
    }
  }
  else if (command.startsWith("scenario"))
  {
    int newScenario = command.substring(8).toInt();
    if (newScenario >= 1 && newScenario <= 8)
    {
      scenario = newScenario;
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
  else
  {
    Serial.println("Unknown command.");
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
    return(generateSineWaveData());
    break;
  case 7:
    return(generateSineWaveDataMono());
    break;
  case 8:
    return(generateSineWaveDataMonoHeader());
    break;
  default:
    Serial.println("Invalid scenario selected.");
    return 1;
    break;
  }
}

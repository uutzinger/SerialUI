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
#include "dataGeneratorAgriculturalMonitoring.h" // Include the data generator for the Agricultural Monitoring System
#include "dataGeneratorCanSat.h"                 // Include the data generator for CanSat
#include "dataGeneratorEnvironmental.h"          // Include the data generator for the Environmental Monitoring System
#include "dataGeneratorMedicalMonitoring.h"      // Include the data generator for the Medical Monitoring System
#include "dataGeneratorPowerSystem.h"            // Include the data generator for the Power Monitoring System

int scenario = 1; // Default scenario (1: CanSat, 2: Environmental, 3: Power, 4: Medical, 5: Agricultural)
unsigned long previousMillis = 0;
unsigned long interval = 500; // Default interval at which to generate data
bool paused = false;          // Flag to pause the data generation

void setup()
{
  Serial.begin(57600);
  Serial.println("System Ready");
}

void loop()
{
  if (Serial.available() > 0)
  {
    handleSerialCommands();
  }

  if (!paused)
  {
    unsigned long currentMillis = millis();
    if (currentMillis - previousMillis >= interval)
    {
      previousMillis = currentMillis;

      switch (scenario)
      {
      case 1:
        generateAgriculturalMonitoringData();
        break;
      case 2:
        generateCanSatData();
        break;
      case 3:
        generateEnvironmentalData();
        break;
      case 4:
        generateMedicalMonitoringData();
        break;
      case 5:
        generatePowerSystemData();
        break;
      default:
        Serial.println("Invalid scenario selected.");
        break;
      }
    }
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
    if (newScenario >= 1 && newScenario <= 5)
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

/*
  Data Generator for Medical Monitoring System

  This file contains the data generation function for a medical monitoring system scenario.
*/

#include "src/RingBuffer.h"
extern RingBuffer dataBuffer;
extern char data[1024];

void generateMedicalMonitoringData()
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

  size_t ret = dataBuffer.push(data, sizeof(data), false);
  if (ret == 0) {
    Serial.println("Ring buffer overflow");
  }
}
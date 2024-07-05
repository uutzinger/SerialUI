/*
  Data Generator for Medical Monitoring System

  This file contains the data generation function for a medical monitoring system scenario.
*/

int medMessageId = 0;

void generateMedicalMonitoringData() {
  medMessageId++;

  float bodyTemp = random(360, 380) / 10.0; // Body temperature in Celsius
  int heartRate = random(60, 100); // Heart rate in BPM
  int bloodPressureSystolic = random(90, 140); // Systolic blood pressure
  int bloodPressureDiastolic = random(60, 90); // Diastolic blood pressure
  float bloodOxygenLevel = random(950, 1000) / 10.0; // Blood oxygen level in percentage
  float respirationRate = random(12, 20); // Respiration rate in breaths per minute
  float glucoseLevel = random(70, 140); // Glucose level in mg/dL
  int stepCount = random(0, 10000); // Step count
  float rssi = random(-90, -30); // RSSI value

  Serial.print("BodyTemp:" + String(bodyTemp) + ",HeartRate:" + String(heartRate) + ",");
  Serial.print("BloodPressure:" + String(bloodPressureSystolic) + "/" + String(bloodPressureDiastolic) + ",BloodOxygenLevel:" + String(bloodOxygenLevel) + ",");
  Serial.print("RespirationRate:" + String(respirationRate) + ",GlucoseLevel:" + String(glucoseLevel) + ",StepCount:" + String(stepCount) + ",RSSI:" + String(rssi) + "\n");

  if (medMessageId > 1000) {
    medMessageId = 0;
  }
}

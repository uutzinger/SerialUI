/*
  Data Generator for Power Monitoring System

  This file contains the data generation function for a power monitoring scenario.
*/

int powerMessageId = 0;

void generatePowerSystemData() {
  powerMessageId++;

  float voltageSensor = random(300, 500) / 10.0; // Voltage sensor
  float currentSensor = random(100, 200) / 10.0; // Current sensor
  float powerSensor = voltageSensor * currentSensor; // Power sensor
  float energySensor = powerSensor * random(10, 1000) / 1000.0; // Energy sensor
  float batteryLevel = random(0, 100); // Battery level percentage
  float temperatureBattery = random(200, 450) / 10.0; // Battery temperature
  float rssi = random(-90, -30); // RSSI value

  Serial.print("VoltageSensor:" + String(voltageSensor) + ",CurrentSensor:" + String(currentSensor) + ",");
  Serial.print("PowerSensor:" + String(powerSensor) + ",EnergySensor:" + String(energySensor) + ",BatteryLevel:" + String(batteryLevel) + ",");
  Serial.print("TemperatureBattery:" + String(temperatureBattery) + ",RSSI:" + String(rssi) + "\n");

  if (powerMessageId > 1000) {
    powerMessageId = 0;
  }
}

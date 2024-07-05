/*
  Data Generator for Environmental Monitoring System

  This file contains the data generation function for an environmental monitoring scenario.
*/

int envMessageId = 0;

void generateEnvironmentalData() {
  envMessageId++;

  float tempSensor1 = random(200, 300) / 10.0; // Temperature sensor 1
  float tempSensor2 = random(150, 250) / 10.0; // Temperature sensor 2
  float humiditySensor = random(300, 800) / 10.0; // Humidity sensor
  float pressureSensor = random(9000, 10500) / 10.0; // Pressure sensor
  float lightSensor = random(200, 1000); // Light intensity sensor
  int co2Sensor = random(300, 600); // CO2 sensor
  float airQualityIndex = random(50, 150); // Air quality index
  float noiseLevel = random(30, 100); // Noise level in dB
  float rssi = random(-90, -30); // RSSI value

  Serial.print("TempSensor1:" + String(tempSensor1) + ",TempSensor2:" + String(tempSensor2) + ",");
  Serial.print("HumiditySensor:" + String(humiditySensor) + ",PressureSensor:" + String(pressureSensor) + ",LightSensor:" + String(lightSensor) + ",");
  Serial.print("CO2Sensor:" + String(co2Sensor) + ",AirQualityIndex:" + String(airQualityIndex) + ",NoiseLevel:" + String(noiseLevel) + ",RSSI:" + String(rssi) + "\n");

  if (envMessageId > 1000) {
    envMessageId = 0;
  }
}

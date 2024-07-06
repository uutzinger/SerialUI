/*
  Data Generator for Agricultural Monitoring System

  This file contains the data generation function for an agricultural monitoring system scenario.
*/

int agriMessageId = 0;

void generateAgriculturalMonitoringData()
{
  agriMessageId++;

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

  Serial.print("SoilMoisture:" + String(soilMoisture) + ",SoilTemperature:" + String(soilTemperature) + ",");
  Serial.print("AirTemperature:" + String(airTemperature) + ",AirHumidity:" + String(airHumidity) + ",LightIntensity:" + String(lightIntensity) + ",");
  Serial.print("PHLevel:" + String(pHLevel) + ",LeafWetness:" + String(leafWetness) + ",CO2Level:" + String(co2Level) + ",WindSpeed:" + String(windSpeed) + ",RSSI:" + String(rssi) + "\n");

  if (agriMessageId > 1000)
  {
    agriMessageId = 0;
  }
}

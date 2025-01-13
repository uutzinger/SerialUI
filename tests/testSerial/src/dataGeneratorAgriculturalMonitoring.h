/*
  Data Generator for Agricultural Monitoring System

  This file contains the data generation function for an agricultural monitoring system scenario.
*/

#include "src/RingBuffer.h"
extern RingBuffer dataBuffer;
extern char data[1024];

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

  return(dataBuffer.push(data, sizeof(data), false));

}

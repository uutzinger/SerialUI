/*
  Data Generator for Environmental Monitoring System

  This file contains the data generation function for an environmental monitoring scenario.
*/

#include <RingBuffer.h>
extern RingBuffer dataBuffer;
extern char data[1024];

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

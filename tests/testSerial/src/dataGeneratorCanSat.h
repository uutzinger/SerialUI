/*
  Data Generator for CanSat

  This file contains the data generation function for the CanSat scenario: https://github.com/charles-the-forth/data-generator
*/


#include "src/RingBuffer.h"
extern RingBuffer dataBuffer;
extern char data[1024];

size_t generateCanSatData()
{
  uint32_t lightIntensity = random(1000, 5000);
  float uvIndex = random(10, 25) / 10.0;
  float temperatureCanSat = random(239, 256) / 10.0;
  float temperatureExternal = random(239, 256) / 10.0;
  float temperatureMPU = random(239, 256) / 10.0;
  float ambientTemp = random(239, 256) / 10.0;
  float objectTemp = random(239, 256) / 10.0;
  float temperatureSCD30 = random(239, 256) / 10.0;
  float humidityCanSat = random(1, 1000) / 10.0;
  float humidityExternal = random(1, 1000) / 10.0;
  float humiditySCD30 = random(1, 1000) / 10.0;
  float pressureCanSat = random(9959, 10105) / 10.0;
  float pressureExternal = random(9959, 10105) / 10.0;
  float altitudeCanSat = random(2390, 10000) / 10.0;
  float altitudeExternal = random(2390, 10000) / 10.0;
  uint8_t numberOfSatellites = random(0, 6);
  uint16_t latInt = 5002;
  uint16_t lonInt = 1546;
  uint32_t latAfterDot = 2308;
  uint32_t lonAfterDot = 79412;
  int co2SCD30 = 100;
  int co2CCS811 = 200;
  int tvoc = 20;
  float o2Concentration = random(100, 1000) / 10.0;
  int rssi = random(0, 60) - 90;
  float accelerationX = random(10, 150) / 10.0;
  float accelerationY = random(10, 150) / 10.0;
  float accelerationZ = random(10, 150) / 10.0;
  float rotationX = random(10, 150) / 10.0;
  float rotationY = random(10, 150) / 10.0;
  float rotationZ = random(10, 150) / 10.0;
  float magnetometerX = random(10, 150) / 10.0;
  float magnetometerY = random(10, 150) / 10.0;
  float magnetometerZ = random(10, 150) / 10.0;
  float a = random(10, 500) / 10.0;
  float b = random(10, 500) / 10.0;
  float c = random(10, 500) / 10.0;
  float d = random(10, 500) / 10.0;
  float e = random(10, 500) / 10.0;
  float f = random(10, 500) / 10.0;
  float g = random(10, 500) / 10.0;
  float h = random(10, 500) / 10.0;
  float i = random(10, 500) / 10.0;
  float j = random(10, 500) / 10.0;
  float k = random(10, 500) / 10.0;
  float l = random(10, 500) / 10.0;
  float r = random(10, 500) / 10.0;
  float s = random(10, 500) / 10.0;
  float t = random(10, 500) / 10.0;
  float u = random(10, 500) / 10.0;
  float v = random(10, 500) / 10.0;
  float w = random(10, 500) / 10.0;

  char* ptr = data;

  ptr += sprintf(ptr, "LightIntensity:%lu,UVIndex:%.1f,", 
                  lightIntensity, uvIndex);
  ptr += sprintf(ptr, "TemperatureCanSat:%.1f,TemperatureMPU:%.1f,TemperatureExternal:%.1f,TemperatureSCD30:%.1f,AmbientTemp:%.1f,ObjectTemp:%.1f,", 
                  temperatureCanSat, temperatureMPU, temperatureExternal, temperatureSCD30, ambientTemp, objectTemp);
  ptr += sprintf(ptr, "HumidityCanSat:%.1f,HumidityExternal:%.1f,HumiditySCD30:%.1f,PressureCanSat:%.1f,", 
                  humidityCanSat, humidityExternal, humiditySCD30, pressureCanSat);
  ptr += sprintf(ptr, "PressureExternal:%.1f,AltitudeCanSat:%.1f,AltitudeExternal:%.1f,", 
                  pressureExternal, altitudeCanSat, altitudeExternal);
  ptr += sprintf(ptr, "AccelerationX:%.1f,AccelerationY:%.1f,AccelerationZ:%.1f,", 
                  accelerationX, accelerationY, accelerationZ);
  ptr += sprintf(ptr, "RotationX:%.1f,RotationY:%.1f,RotationZ:%.1f,MagnetometerX:%.1f,", 
                  rotationX, rotationY, rotationZ, magnetometerX);
  ptr += sprintf(ptr, "MagnetometerY:%.1f,MagnetometerZ:%.1f,LatInt:%u,LonInt:%u,", 
                  magnetometerY, magnetometerZ, latInt, lonInt);
  ptr += sprintf(ptr, "LatAfterDot:%lu,LonAfterDot:%lu,CO2SCD30:%d,CO2CCS811:%d,", 
                  latAfterDot, lonAfterDot, co2SCD30, co2CCS811);
  ptr += sprintf(ptr, "TVOC:%d,O2Concentration:%.1f,A:%.1f,B:%.1f,C:%.1f,D:%.1f,", 
                  tvoc, o2Concentration, a, b, c, d);
  ptr += sprintf(ptr, "E:%.1f,F:%.1f,G:%.1f,H:%.1f,I:%.1f,J:%.1f,K:%.1f,L:%.1f,", 
                  e, f, g, h, i, j, k, l);
  ptr += sprintf(ptr, "R:%.1f,S:%.1f,T:%.1f,U:%.1f,V:%.1f,W:%.1f,", 
                  r, s, t, u, v, w);
  ptr += sprintf(ptr, "NumberOfSatellites:%u,RSSI:%d", numberOfSatellites, rssi);

  return(dataBuffer.push(data, sizeof(data), false));

}

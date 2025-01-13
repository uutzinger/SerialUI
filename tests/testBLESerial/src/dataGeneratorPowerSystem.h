/*
  Data Generator for Power Monitoring System

  This file contains the data generation function for a power monitoring scenario.
*/

#include "src/RingBuffer.h"
extern RingBuffer dataBuffer;
extern char data[1024];

size_t generatePowerSystemData()
{
  float voltageSensor = random(300, 500) / 10.0;                // Voltage sensor
  float currentSensor = random(100, 200) / 10.0;                // Current sensor
  float powerSensor = voltageSensor * currentSensor;            // Power sensor
  float energySensor = powerSensor * random(10, 1000) / 1000.0; // Energy sensor
  float batteryLevel = random(0, 100);                          // Battery level percentage
  float temperatureBattery = random(200, 450) / 10.0;           // Battery temperature
  float rssi = random(-90, -30);                                // RSSI value

  char* ptr = data;

  ptr += sprintf(ptr, "VoltageSensor:%.1f,CurrentSensor:%.1f,", voltageSensor, currentSensor);
  ptr += sprintf(ptr, "PowerSensor:%.1f,EnergySensor:%.1f,BatteryLevel:%.1f,", powerSensor, energySensor, batteryLevel);
  ptr += sprintf(ptr, "TemperatureBattery:%.1f,RSSI:%.1f\n", temperatureBattery, rssi);

  return(dataBuffer.push(data, sizeof(data), false));
}

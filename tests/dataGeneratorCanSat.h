/*
  Data Generator for CanSat

  This file contains the data generation function for the CanSat scenario: https://github.com/charles-the-forth/data-generator
*/

int messageId = 0;

void generateCanSatData() {
  messageId++;

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

  Serial.print("LightIntensity:" + String(lightIntensity) + ",UVIndex:" + String(uvIndex) + ",");
  Serial.print("TemperatureCanSat:" + String(temperatureCanSat) + ",TemperatureMPU:" + String(temperatureMPU) + ",TemperatureExternal:" + String(temperatureExternal) + ",");
  Serial.print("TemperatureSCD30:" + String(temperatureSCD30) + ",AmbientTemp:" + String(ambientTemp) + ",ObjectTemp:" + String(objectTemp) + ",");
  Serial.print("HumidityCanSat:" + String(humidityCanSat) + ",HumidityExternal:" + String(humidityExternal) + ",HumiditySCD30:" + String(humiditySCD30) + ",");
  Serial.print("PressureCanSat:" + String(pressureCanSat) + ",PressureExternal:" + String(pressureExternal) + ",AltitudeCanSat:" + String(altitudeCanSat) + ",");
  Serial.print("AltitudeExternal:" + String(altitudeExternal) + ",AccelerationX:" + String(accelerationX) + ",AccelerationY:" + String(accelerationY) + ",");
  Serial.print("AccelerationZ:" + String(accelerationZ) + ",RotationX:" + String(rotationX) + ",RotationY:" + String(rotationY) + ",");
  Serial.print("RotationZ:" + String(rotationZ) + ",MagnetometerX:" + String(magnetometerX) + ",MagnetometerY:" + String(magnetometerY) + ",");
  Serial.print("MagnetometerZ:" + String(magnetometerZ) + ",LatInt:" + String(latInt) + ",LonInt:" + String(lonInt) + ",");
  Serial.print("LatAfterDot:" + String(latAfterDot) + ",LonAfterDot:" + String(lonAfterDot) + ",CO2SCD30:" + String(co2SCD30) + ",CO2CCS811:" + String(co2CCS811) + ",");
  Serial.print("TVOC:" + String(tvoc) + ",O2Concentration:" + String(o2Concentration) + ",");
  Serial.print("A:" + String(a) + ",B:" + String(b) + ",C:" + String(c) + ",D:" + String(d) + ",E:" + String(e) + ",F:" + String(f) + ",G:" + String(g) + ",H:" + String(h) + ",I:" + String(i) + ",J:" + String(j) + ",K:" + String(k) + ",L:" + String(l) + ",R:" + String(r) + ",S:" + String(s) + ",T:" + String(t) + ",U:" + String(u) + ",V:" + String(v) + ",W:" + String(w) + ",");
  Serial.println("NumberOfSatellites:" + String(numberOfSatellites) + ",RSSI:" + String(rssi));

  if (messageId > 1000) {
    messageId = 0;
  }
}

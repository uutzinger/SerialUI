/*
*****************************************************************************************************************
  Main File: testSerial.ino

  This program handles the timing and main loop for data generation. 
  It calls the appropriate data generation function based on the scenario.
  It also accepts commands over serial to change the interval, scenario, or pause the data generation.

  Commands:

    interval <value>: Sets the data generation interval to the specified value in micro seconds.
    frequency <value> sets the frequency of the sine, saw tooth or squarewave in Hz
    scenario <value>: Changes the scenario to the specified value (1 to 5).

    pause:            Pauses the data generation.
    resume:           Resumes the data generation if it was paused.

  ********************************************************************************************************************
*/

#define VERSION_STRING "Serial Tester 1.0.5"

#include <cmath>
#include "RingBuffer.h"

// Serial Settings
inline constexpr unsigned long BAUDRATE             = 2'000'000UL;

// Measurement
inline constexpr size_t        FRAME_SIZE           = 256;  // Max size in bytes to send at once. ESP 256, Teensy 64 ..
inline constexpr size_t        BUFFERSIZE           = 4096; // Buffer to hold data, should be a few times larger than FRAME_SIZE
inline constexpr size_t        TABLESIZE            = 512;  // Number of samples in one full cycle for sine, sawtooth etc, must be power of 2
inline constexpr size_t        highWaterMark        = BUFFERSIZE*3/4; // When to throttle data generation
inline constexpr size_t        lowWaterMark         = 2*FRAME_SIZE;   // When to resume data generation

// Add platform-specific defaults for fast modes
#if defined(ESP32)
  constexpr unsigned long SPEEDTEST_DEFAULT_INTERVAL_US = 20;  // stable on ESP32
#else
  constexpr unsigned long SPEEDTEST_DEFAULT_INTERVAL_US = 0;   // Teensy: run tight loop
#endif

// ===== Data generation globals =====
int                           scenario = 6;
float                         frequency = 100.0;   // Frequency (Hz)
float                         amplitude = 1024;     // Amplitude
int                           samplerate = 5000;   // Samples per second
int16_t                       signalTable[TABLESIZE];
bool                          genPermit = true; // true if data generation is allowed
constexpr uint32_t            sendInterval = 100; // results in up to FRAME_SIZE * 8 / sendinterval * 1_000_000 Mbit/sec [40 Mbits/s]

/*------------------------------------------------------------------------ 
General
--------------------------------------------------------------------------
*/

bool          paused = true;                // Flag to pause the data generation
String        receivedCommand = "";
char          data[1024];                   // Serial data buffer
const int     ledPin = LED_BUILTIN; 
int           ledState = LOW; 
unsigned long currentTime;
unsigned long interval = 10000;             // Default interval at which to generate data in micro seconds
unsigned long lastDataGenerationTime  = 0;     // Last time data was produced
unsigned long blinkInterval =  1000;
unsigned long lastBlink;
static bool   userSetInterval = false;
static bool   fastMode = false;              // true if scenario 11 or 20 (run as fast as possible)

// Add timing constraints and helpers (place near other globals)
constexpr int            MIN_SAMPLERATE_HZ = 1;
constexpr int            MAX_SAMPLERATE_HZ = 200000;      // 200kHz, limit for Stereo on Teensy is like 80ksps
constexpr unsigned long  MIN_INTERVAL_US   = 100;         // 0.1 ms minimum frame period
constexpr unsigned long  MAX_INTERVAL_US   = 500000;      // 500 ms maximum frame period


/*------------------------------------------------------------------------ 
USB Speed Tester
--------------------------------------------------------------------------
*/

unsigned long lastUSBTime  = 0;     // Last time data was produced
unsigned long lastSend = 0;
unsigned long lastCounts = 10000000; 
unsigned long currentCounts = 10000000;     // Number of lines sent
unsigned long countsPerSecond = 0;

/*------------------------------------------------------------------------ 
Scenarios
--------------------------------------------------------------------------
*/

// Fixed-point phase config
constexpr uint32_t ilog2_u32(uint32_t v) {
  uint32_t n = 0;
  while (v > 1) { v >>= 1; ++n; }
  return n;
}

constexpr uint32_t  INT_BITS = ilog2_u32((uint32_t)TABLESIZE);  // e.g. 9 for 512
constexpr uint32_t  FRAC     = 32u - INT_BITS;                  // e.g. 23 for 512
constexpr uint64_t  PHASE_MOD  = (uint64_t)TABLESIZE << FRAC;
constexpr uint64_t  PHASE_MASK = PHASE_MOD - 1ull;

static inline uint32_t phase_inc_from_hz(float hz, int sr) {
  if (hz <= 0.0f || sr <= 0) return 0u;
  return (uint32_t)((((uint64_t)TABLESIZE << FRAC) * (double)hz) / (double)sr);
}
static inline uint32_t advance_phase(uint32_t p, uint32_t inc) {
  return (p + inc) & (uint32_t)PHASE_MASK;
}
static inline int table_index(uint32_t p) {
  return (int)((p >> FRAC) & (TABLESIZE - 1));
}

static uint32_t     phase = 0;
float               stereo_drift_hz = 0.2f;               // adjust for faster/slower relative phase sweep
static uint32_t     stereo_offset_fp = 0;       // fixed‑point phase offset accumulator (8.24)

RingBuffer<char, BUFFERSIZE> dataBuffer;

// =============================================================================================
// SETUP
// =============================================================================================

void setup()
{
  pinMode(ledPin, OUTPUT);

  Serial.begin(BAUDRATE);

  currentTime = millis();
  while (!Serial && ( (millis() - currentTime) < 10000 )) { delay(5); }
  Serial.println("==================================================================");
  Serial.println(VERSION_STRING);
  Serial.println("==================================================================");

  #if defined(ESP32)
    // Initialize PSRAM (optional check)
    if (psramInit()) {
      Serial.println("PSRAM initialized successfully.");
      Serial.printf("Total PSRAM: %d bytes\r\n", ESP.getPsramSize());
      Serial.printf("Free PSRAM: %d bytes\r\n", ESP.getFreePsram());
    } else {
      Serial.println("PSRAM initialization failed. Ensure PSRAM is enabled in the board configuration.");
    }
  #endif

  if ((TABLESIZE & (TABLESIZE - 1)) != 0) {
    Serial.println("TABLESIZE must be a power of 2");
    while (true) delay(1000);
  }
  if (TABLESIZE < 8 || TABLESIZE > 16384) {
    Serial.println("TABLESIZE out of expected range");
    while (true) delay(1000);
  }


  Serial.println("=================================");
  Serial.println("Commands are:");
  Serial.println("pause");
  Serial.println("resume");
  Serial.println("interval <micro sec> >=0");
  Serial.println("samplerate <Hz>");
  Serial.println("scenario <number>: ");
  Serial.println("   1 Agriculture,     2 Satellite,           3 Environmental, ");
  Serial.println("   4 Medical,         5 Power                6 Stereo Sinewave, ");
  Serial.println("   7 Mono Sinewave,   8 Moo Sinewave Header, 9 Mono Sawtooth, ");
  Serial.println("   10 Squarewave     11 64 Chars,            20 USB Speed Tester");
  // Prints current settings
  Serial.println("=================================");
  Serial.println("Current Settings:");
  Serial.printf("Interval:   %d microseconds\r\n", interval);
  Serial.printf("Samplerate: %d Hz\r\n", samplerate);
  Serial.printf("Scenario:   %d\r\n", scenario);
  Serial.printf("Frequency:  %f\r\n", frequency);
  Serial.printf("Paused:     %s\r\n", paused ? "Yes" : "No");

  randomSeed(analogRead(0));
  updateSignalTable(scenario);

  lastDataGenerationTime = micros();
  lastUSBTime = micros();
  lastBlink = micros();
  lastSend = micros();

}

// =============================================================================================
// LOOP
// =============================================================================================

void loop()
{

  currentTime = micros();

  // Handle Commands
  // -----------------------------------------------------------------------
  if (Serial.available() > 0)
  {
    handleSerialCommands();
  }

  // Create Data
  // -----------------------------------------------------------------------
  if (!paused && genPermit)
  {
    if (currentTime - lastDataGenerationTime > interval)
    {
      lastDataGenerationTime = currentTime;
      size_t ret = generateData();
      size_t avail = dataBuffer.available();
      if (avail >= highWaterMark) {
          genPermit = false;
      }
      if (ret == 0) {
        Serial.println("Ring buffer overflow");
      }
    }
  }

  // Send Data
  // ------------------------------------------------------------------------
  size_t avail = dataBuffer.available();
  if (avail > 0) {
    // have something to send

    // bytes we are willing to send this pass (hysteresis: keep up to lowWaterMark queued)
    size_t sendBytes = (avail > lowWaterMark) ? (avail - lowWaterMark) : avail;
    // Always send at least one frame if anything is present
    if (sendBytes == 0) sendBytes = (avail < FRAME_SIZE) ? avail : FRAME_SIZE;

    while (sendBytes > 0) {
      size_t chunkReq  = sendBytes > FRAME_SIZE ? FRAME_SIZE : sendBytes;
      size_t bytesRead = dataBuffer.pop(data, chunkReq);
      if (bytesRead == 0) break;              // nothing left
      Serial.write(data, bytesRead);
      sendBytes -= bytesRead;
    }

    // start generating data if we are below waterMark
    if (dataBuffer.available() <= lowWaterMark) {
        genPermit = true;
    }
  }

  if ((currentTime - lastBlink) >= blinkInterval) {
    lastBlink = currentTime;
    if (ledState == LOW) {
      ledState = HIGH;
      blinkInterval = 200000; 
    } else {
      ledState = LOW;
      blinkInterval = 800000;
    }

    // set the LED with the ledState of the variable:
    digitalWrite(ledPin, ledState);  
  } // end blink

} // end main

// =============================================================================================
// Support Functions
// =============================================================================================

// ----------------------------------------------------------
//  User Input
// ----------------------------------------------------------

void handleSerialCommands()
{
  String command = Serial.readStringUntil('\n');
  command.trim(); // Remove any leading/trailing whitespace

  if (command.startsWith("interval "))
  {
    long newInterval = command.substring(9).toInt();
    if (newInterval >= 0)
    {
      interval = (unsigned long)newInterval;
      userSetInterval = true;
      sanitizeTiming();
      Serial.println("Interval set to " + String(interval) + " micro seconds");
      dataBuffer.clear();
      updateSignalTable(scenario);
    }
    else
    {
      Serial.println("Invalid interval value.");
    }
  }
  else if (command.startsWith("samplerate "))
  {
    int newSamplerate = command.substring(11).toInt();
    if (newSamplerate > 0)
    {
      samplerate = newSamplerate;
      sanitizeTiming();
      Serial.println("Samplerate set to " + String(samplerate) + " Hz");
    }
    else
    {
      Serial.println("Invalid samplerate value.");
    }
  }
  else if (command.startsWith("scenario "))
  {
    int newScenario = command.substring(9).toInt();
    if (newScenario >= 1 && newScenario <= 100)
    {
      scenario = newScenario;
      fastMode = (scenario == 11 || scenario == 20);
      if (fastMode && !userSetInterval) {
        interval = SPEEDTEST_DEFAULT_INTERVAL_US;
        Serial.println("Interval auto-set for fast mode: " + String(interval) + " microseconds");
      }
      sanitizeTiming();
      updateSignalTable(scenario);
      dataBuffer.clear();
      Serial.println("Scenario set to " + String(scenario));
    }
    else
    {
      Serial.println("Invalid scenario value.");
    }
  }
  else if (command.startsWith("frequency "))
  {
    float new_freq = command.substring(10).toFloat();
    if (new_freq >= 0 && new_freq <= 10000)
    {
      frequency = new_freq;
      sanitizeTiming();
      updateSignalTable(scenario);
      dataBuffer.clear();
      Serial.println("Frequency set to " + String(frequency));
    }
    else
    {
      Serial.println("Invalid frequency value.");
    }
  }
  else if (command.startsWith("pause"))
  {
    paused = true;
    Serial.println("Data generation paused.");
  }
  else if (command.startsWith("resume"))
  {
    paused = false;
    dataBuffer.clear();
    Serial.println("Data generation resumed.");
  }
  else if (command.startsWith("?"))
    {
        // Prints current settings
        Serial.println("=================================");
        Serial.println("Current Settings:");
        Serial.printf("Interval:   %d microseconds\r\n", interval);
        Serial.printf("Samplerate: %d Hz\r\n", samplerate);
        Serial.printf("Scenario:   %d\r\n", scenario);
        Serial.printf("Frequency:  %f\r\n", frequency);
        Serial.printf("Paused:     %s\r\n", paused ? "Yes" : "No");
    }
  else if (command.startsWith("."))
    {
    // Prints current ble status
    snprintf(data, sizeof(data),
      "==================================================================\r\n"
      "Settings:\r\n"
      "Chunk Size: %d\r\n"
      "Permission to generate data is %s\r\n"
      "Buffered used: %d bytes\r\n"
      "Buffer low watermark: %d - high watermark: %d size: %d bytes\r\n"
      "==================================================================\r\n",
      FRAME_SIZE,
      genPermit ? "on" : "off",
      dataBuffer.available(), 
      lowWaterMark,
      highWaterMark,
      dataBuffer.capacity()
    );
    Serial.print(data);
  }
  else
  {
    Serial.println("=================================");
    Serial.println("Commands are:");
    Serial.println("pause");
    Serial.println("resume");
    Serial.println("interval <micro sec> > 0");
    Serial.println("samplerate <Hz>");
    Serial.println("frequency <Hz> 0..10000");    
    Serial.println("scenario <number>: ");
    Serial.println("   1 Agriculture,    2 Satelite,             3 Environmental, ");
    Serial.println("   4 Medical,        5 Power                 6 Stereo Sinewave, ");
    Serial.println("   7 Mono Sinewave,  8 Mono Sinewave Header, 9 Mono Sawtooth, ");
    Serial.println("  10 Squarewave,    11 64 Chars,            20 USB Speed Tester");
  }
}

//----------------------------------------------------------
// Data Generation Selector
// ---------------------------------------------------------

size_t generateData()
{
  switch (scenario)
  {
  case 1:
    return(generateAgriculturalMonitoringData());
    break;
  case 2:
    return(generateCanSatData());
    break;
  case 3:
    return(generateEnvironmentalData());
    break;
  case 4:
    return(generateMedicalMonitoringData());
    break;
  case 5:
    return(generatePowerSystemData());
    break;
  case 6:
    return(generateStereo(samplerate, interval));
    break;
  case 7:
    return(generateMono(samplerate, interval));
    break;
  case 8:
    return(generateMonoHeader(samplerate, interval, String("Sine")));
    break;
  case 9:
    return(generateMono(samplerate, interval));
    break;
  case 10:
    return(generateMono(samplerate, interval));
    break;
  case 11:
    return(generate64Chars());
    break;
  case 20:
    return(generateStoffregen());
    break;
  default:
    Serial.println("Invalid scenario selected.");
    return 1;
    break;
  }
}

void updateSignalTable(int scenario){
  switch (scenario)
  {
    case 6:
      updateSineWaveTable();
      break;
    case 7:
      updateSineWaveTable();
      break;
    case 8:
      updateSineWaveTable();
      break;
    case 9:
      updateSawToothTable();
      break;
    case 10:
      updateSquareWaveTable();
      break;
    default:
      break;
  }
}

// Corrected updateSineWaveTable function
void updateSineWaveTable() {
    Serial.println("Updating sine table...");
    for (size_t i = 0; i < TABLESIZE; i++) {
        int16_t value1 = int16_t(amplitude       * sin(( 2.0 * M_PI * float(i)) / float(TABLESIZE))); 
        // int16_t value2 = int16_t((amplitude / 4) * sin((10.0 * M_PI * i) / float(TABLESIZE))); // Adjusted frequency
        // signalTable[i] = value1 + value2;
        signalTable[i] = value1;
    }

    int16_t mn = INT16_MAX, mx = INT16_MIN;
    for (size_t i = 0; i < TABLESIZE; ++i) { 
      mn = min(mn, signalTable[i]); 
      mx = max(mx, signalTable[i]);
    }
    Serial.printf("Sine table range: [%d, %d]\r\n", (int)mn, (int)mx);
  }

void updateSawToothTable() {
    Serial.println("Updating sawtooth table...");
    for (size_t i = 0; i < TABLESIZE; i++) {
        int16_t value = int16_t(-amplitude + 2.* amplitude * (float(i) / float(TABLESIZE)));
        signalTable[i] = value;
    }
}

void updateSquareWaveTable() {
    Serial.println("Updating square table...");
    for (size_t i = 0; i < TABLESIZE; i++) {
        int16_t value;
        if (i < TABLESIZE / 2) {  // Corrected missing parentheses
            value = int16_t(amplitude);
        } else {
            value = int16_t(-amplitude);
        }
        signalTable[i] = value;
    }
}

// =============================================================================================
// Data Generators
// =============================================================================================

// Estimate avg characters per sample for buffer sizing
static int avgCharsPerSample(int scen) {
  switch (scen) {
    case 1:  return 184; // Agriculture: "Temp: 23.45 C, Hum: 56.78 %, Soil: 12.34 %\r\n"
    case 2:  return 718; // CanSat: "T:23.45C,P:1013.25hPa,H:56.78%,A:123.
    case 3:  return 159; // Environmental: "Temp: 23.45 C, Hum: 56.78 %, CO2: 400 ppm\r\n"
    case 4:  return 138; // Medical: "HR: 72 bpm, SpO2: 98 %, BP: 120/80 mmHg, Temp: 36.5 C\r\n"
    case 5:  return 129; // Power: "Volt: 12.34 V, Curr: 1.23 A, Power: 15.00 W\r\n"
    case 6:  return  16; // Stereo: "-1024, -1024\r\n" ~ 14 → use 16
    case 7:  return   8; // Mono: "-1024\r\n" ~ 6–7 → use 16
    case 8:  return  14; // Header + value: "Sine: -1024\r\n" ~ 12–14 → use 16
    case 9:  return   8; // Mono: "-1024\r\n" ~ 6–7 → use 8
    case 10: return   8; // Mono: "-1024\r\n" ~ 6–7 → use 8
    case 11: return  64; // 64 chars + newline
    case 20: return  35; // Speed test: count=%9lu, lines/sec=%6lu\r\n
    default: return  64; // Other CSV scenarios build one line per call; keep generous
  }
}

// Compute max samples per frame that fit the per-call text buffer
static int maxSamplesForBuffer(int scen) {
  const int overhead = 32; // guard for final null and minor variation
  int avg = avgCharsPerSample(scen);
  if (avg < 1) avg = 8;
  return max(1, (int)((sizeof(data) - overhead) / avg));
}

// Clamp samplerate/interval and, if needed, shrink interval to keep samples per frame in bounds
static void sanitizeTiming() {
  // Clamp samplerate and interval
  samplerate = constrain(samplerate, MIN_SAMPLERATE_HZ, MAX_SAMPLERATE_HZ);
  // Fast modes (11, 20): do NOT clamp interval; allow 0
  if (scenario == 11 || scenario == 20) {
    return;
  }
  // Other scenarios: clamp interval into sane bounds
  interval   = constrain(interval, MIN_INTERVAL_US, MAX_INTERVAL_US);

  // Only waveform scenarios (6..10) use samplerate and interval
  if (scenario >= 6 && scenario <= 10) {
    const uint64_t ticks   = (uint64_t)samplerate * (uint64_t)interval;
    int requestedSamples   = (int)(ticks / 1000000ULL);
    int maxSamplesAllowed  = maxSamplesForBuffer(scenario);

    if (requestedSamples < 1) {
      requestedSamples = 1;
    }
    if (requestedSamples > maxSamplesAllowed) {
      // Reduce interval to fit in buffer while keeping samplerate
      // interval_us = samples * 1e6 / samplerate
      unsigned long newInterval = (unsigned long)((uint64_t)maxSamplesAllowed * 1000000ULL / (uint64_t)samplerate);
      newInterval = constrain(newInterval, MIN_INTERVAL_US, MAX_INTERVAL_US);
      if (newInterval != interval) {
        interval = newInterval;
        Serial.print("Note: interval reduced to fit buffer: ");
        Serial.print(interval);
        Serial.println("µs");
      }
    }
  }
}

// ----------------------------------------------------------
//  Data Generation from Table with Header
// ----------------------------------------------------------

size_t generateMonoHeader(int samplerate, unsigned long interval, String header) {
    char* ptr = data;
    
    const uint64_t ticks = (uint64_t)samplerate * (uint64_t)interval; // microsecond ticks
    int samples = (int)(ticks / 1000000ULL);
    if (samples <= 0) return 0;

    // Fixed‑point phase increment (TABLESIZE << FRAC scaled by freq / samplerate)
    const uint32_t inc = phase_inc_from_hz(frequency, samplerate);

    const char* h = header.c_str();
    uint32_t p = phase;

    for (int i = 0; i < samples; ++i) {
        size_t rem = sizeof(data) - (size_t)(ptr - data);
        if (rem <= 1) break;
        
        int idx = table_index(p);
        int wrote = snprintf(ptr, rem, "%s: %d\r\n", h, (int)signalTable[idx]);
        if (wrote <= 0 || wrote >= (int)rem) break;
        ptr += wrote;

        p = advance_phase(p, inc);
    }

    phase = p;

    const size_t len = (size_t)(ptr - data);
    return dataBuffer.push(data, len, false);
}

// ----------------------------------------------------------
// Data Generator from Table
// ----------------------------------------------------------


size_t generateMono(int samplerate, unsigned long interval) {
    char* ptr = data;
    const uint64_t ticks = (uint64_t)samplerate * (uint64_t)interval;
    int samples = (int)(ticks / 1000000ULL);
    if (samples <= 0) return 0;

    // phase increment: TABLESIZE steps per cycle
    const uint32_t inc = phase_inc_from_hz(frequency, samplerate);

    uint32_t p = phase;
        
    for (int i = 0; i < samples; ++i) {
        size_t rem = sizeof(data) - (size_t)(ptr - data);
        if (rem <= 1) break;
        
        int idx = table_index(p);
        int wrote = snprintf(ptr, rem, "%d\r\n", signalTable[idx]);
        if (wrote <= 0 || wrote >= (int)rem) break;
        ptr += wrote;

        p   = advance_phase(p, inc);
    }

    phase = p;

    const size_t len = (size_t)(ptr - data);
    return dataBuffer.push(data, len, false);
}

//----------------------------------------------------------
// Data Generation from Table: Stereo
//----------------------------------------------------------


size_t generateStereo(int samplerate, unsigned long interval) {
    char* ptr = data;
    const uint64_t ticks = (uint64_t)samplerate * (uint64_t)interval;
    int samples = (int)(ticks / 1000000ULL);
    if (samples <= 0) return 0;

    const uint32_t inc        = phase_inc_from_hz(frequency,        samplerate);
    const uint32_t inc_offset = phase_inc_from_hz(stereo_drift_hz,  samplerate);

    // Local working copies keep constant relative offset
    uint32_t p = phase;
    uint32_t off = stereo_offset_fp;

    for (int i = 0; i < samples; ++i) {
        size_t rem = sizeof(data) - (size_t)(ptr - data);
        if (rem <= 1) break;

        int idx1 = table_index(p);
        int idx2 = table_index(p + off);

        int wrote = snprintf(ptr, rem, "%d, %d\r\n", signalTable[idx1], signalTable[idx2]);
        if (wrote <= 0 || wrote >= (int)rem) break;
        ptr += wrote;

        p   = advance_phase(p, inc);
        off = advance_phase(off, inc_offset);
    }

    phase = p;
    stereo_offset_fp = off;
 
    const size_t len = (size_t)(ptr - data);
    return dataBuffer.push(data, len, false);
}

// ----------------------------------------------------------
// Data Generator: 64 Characters
// ----------------------------------------------------------

inline constexpr char FIXED_64_CHAR[65] =  "ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZ.012345678\r\n"; 

size_t generate64Chars() {
    return dataBuffer.push(FIXED_64_CHAR, 64, false);  // Push 64 bytes to ring buffer
}

// ----------------------------------------------------------
//  Data Generator for USB test, includes line counter and lines per second
// ----------------------------------------------------------

size_t generateStoffregen() {

  // 34 characters 
  size_t n = snprintf(data, sizeof(data), "count=%9lu, lines/sec=%6lu\r\n", currentCounts, countsPerSecond);
  // Sufficient size: 
  // count=: 6
  // counts: 9 
  // , lines/sec=: 12 
  // cps: 6
  // \r\n: 1
  // 0: 1
  // Total: 35

  currentCounts++;

  // update every second
  if (currentTime - lastUSBTime > 1000000) {
    countsPerSecond = currentCounts - lastCounts;
    lastCounts = currentCounts;
    lastUSBTime = currentTime;
  }

  return dataBuffer.push(data, n, false);
}

// ----------------------------------------------------------
// Data Generator for Agriculture Data
// ----------------------------------------------------------


size_t  generateAgriculturalMonitoringData()
{

  float soilMoisture    = random(200, 800) / 10.0;       // Soil moisture in percentage
  float soilTemperature = random(100, 350) / 10.0;       // Soil temperature in Celsius
  float airTemperature  = random(150, 350) / 10.0;       // Air temperature in Celsius
  float airHumidity     = random(300, 900) / 10.0;       // Air humidity in percentage
  float lightIntensity  = random(2000,10000) / 100.0;    // Light intensity in lux/100 (overcast)
  float pHLevel         = random(50, 80) / 10.0;         // Soil pH level
  int leafWetness       = random(0, 15);                 // Leaf wetness
  float co2Level        = random(300, 800) / 10.0;       // CO2 level in ppm/10
  float windSpeed       = random(0, 200) / 10.0;         // Wind speed in m/s
  float arssi           = random(-90, -30);              // RSSI value

  int n = snprintf(data, sizeof(data), 
         "SoilMoisture: %.1f, SoilTemperature: %.1f, AirTemperature: %.1f, AirHumidity: %.1f, LightIntensity: %.1f, PHLevel: %.2f, LeafWetness: %d, CO2Level: %.1f, WindSpeed: %.1f, RSSI: %.1f\r\n",
          soilMoisture, soilTemperature, airTemperature,
          airHumidity, lightIntensity, pHLevel, leafWetness,
          co2Level, windSpeed, arssi);

  size_t len = (n > 0 && n < (int)sizeof(data)) ? (size_t)n : (sizeof(data) - 1);
  return(dataBuffer.push(data, len, false));
}

// ----------------------------------------------------------
//  Data Generator for Power Monitoring System
// ----------------------------------------------------------

size_t generatePowerSystemData()
{
  float voltageSensor = random(300, 500) / 10.0;                // Voltage sensor
  float currentSensor = random(100, 200) / 10.0;                // Current sensor
  float powerSensor = voltageSensor * currentSensor;            // Power sensor
  float energySensor = powerSensor * random(10, 1000) / 1000.0; // Energy sensor
  float batteryLevel = random(0, 100);                          // Battery level percentage
  float temperatureBattery = random(200, 450) / 10.0;           // Battery temperature
  float prssi = random(-90, -30);                                // RSSI value

  int n = snprintf(data, sizeof(data),
    "VoltageSensor:%.1f,CurrentSensor:%.1f,"
    "PowerSensor:%.1f,EnergySensor:%.1f,BatteryLevel:%.1f,"
    "TemperatureBattery:%.1f,RSSI:%.1f\r\n",
    voltageSensor, currentSensor,
    powerSensor, energySensor, batteryLevel,
    temperatureBattery, prssi);

  size_t length = (n > 0 && n < (int)sizeof(data)) ? (size_t)n : sizeof(data)-1;
  return dataBuffer.push(data, length, false);
}

// ----------------------------------------------------------
// Data Generator for Medical Monitoring System
// ----------------------------------------------------------


size_t generateMedicalMonitoringData()
{
  float bodyTemp = random(360, 380) / 10.0;          // Body temperature in Celsius
  int heartRate = random(60, 100);                   // Heart rate in BPM
  int bloodPressureSystolic = random(90, 140);       // Systolic blood pressure
  int bloodPressureDiastolic = random(60, 90);       // Diastolic blood pressure
  float bloodOxygenLevel = random(950, 1000) / 10.0; // Blood oxygen level in percentage
  float respirationRate = random(12, 20);            // Respiration rate in breaths per minute
  float glucoseLevel = random(70, 140);              // Glucose level in mg/dL
  int stepCount = random(0, 10000);                  // Step count
  float mrssi = random(-90, -30);                     // RSSI value

  int n = snprintf(data, sizeof(data),
    "BodyTemp:%.1f,HeartRate:%d,"
    "BloodPressure:%d/%d,BloodOxygenLevel:%.1f,"
    "RespirationRate:%.1f,GlucoseLevel:%.1f,StepCount:%d,"
    "RSSI:%.1f\r\n",
    bodyTemp, heartRate,
    bloodPressureSystolic, bloodPressureDiastolic, bloodOxygenLevel,
    respirationRate, glucoseLevel, stepCount,
    mrssi);

  size_t length = min(strlen(data), sizeof(data));
  return(dataBuffer.push(data, length, false));
}

// ----------------------------------------------------------
//  Data Generator for Environmental Monitoring System
// ----------------------------------------------------------


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
  float erssi = random(-90, -30);                     // RSSI value

  int n = snprintf(data, sizeof(data),
    "TempSensor1:%.1f,TempSensor2:%.1f,"
    "HumiditySensor:%.1f,PressureSensor:%.1f,LightSensor:%.1f,"
    "CO2Sensor:%d,AirQualityIndex:%.1f,NoiseLevel:%.1f,"
    "RSSI:%.1f\r\n",
    tempSensor1, tempSensor2,
    humiditySensor, pressureSensor, lightSensor,
    co2Sensor, airQualityIndex, noiseLevel,
    erssi);

  size_t length = min(strlen(data), sizeof(data));
  return(dataBuffer.push(data, length, false));
}

// ----------------------------------------------------------
//  Data Generator for CanSat
// ----------------------------------------------------------

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
  int crssi = random(0, 60) - 90;
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

  int n = snprintf(data, sizeof(data),
    "LightIntensity:%lu,UVIndex:%.1f,"
    "TemperatureCanSat:%.1f,TemperatureMPU:%.1f,TemperatureExternal:%.1f,TemperatureSCD30:%.1f,AmbientTemp:%.1f,ObjectTemp:%.1f,"
    "HumidityCanSat:%.1f,HumidityExternal:%.1f,HumiditySCD30:%.1f,PressureCanSat:%.1f,"
    "PressureExternal:%.1f,AltitudeCanSat:%.1f,AltitudeExternal:%.1f,"
    "AccelerationX:%.1f,AccelerationY:%.1f,AccelerationZ:%.1f,"
    "RotationX:%.1f,RotationY:%.1f,RotationZ:%.1f,MagnetometerX:%.1f,"
    "MagnetometerY:%.1f,MagnetometerZ:%.1f,LatInt:%u,LonInt:%u,"
    "LatAfterDot:%lu,LonAfterDot:%lu,CO2SCD30:%d,CO2CCS811:%d,"
    "TVOC:%d,O2Concentration:%.1f,A:%.1f,B:%.1f,C:%.1f,D:%.1f,"
    "E:%.1f,F:%.1f,G:%.1f,H:%.1f,I:%.1f,J:%.1f,K:%.1f,L:%.1f,"
    "R:%.1f,S:%.1f,T:%.1f,U:%.1f,V:%.1f,W:%.1f,"
    "NumberOfSatellites:%u,RSSI:%d\r\n",
    lightIntensity, uvIndex,
    temperatureCanSat, temperatureMPU, temperatureExternal, temperatureSCD30, ambientTemp, objectTemp,
    humidityCanSat, humidityExternal, humiditySCD30, pressureCanSat,
    pressureExternal, altitudeCanSat, altitudeExternal,
    accelerationX, accelerationY, accelerationZ,
    rotationX, rotationY, rotationZ, magnetometerX,
    magnetometerY, magnetometerZ, latInt, lonInt,
    latAfterDot, lonAfterDot, co2SCD30, co2CCS811,
    tvoc, o2Concentration, a, b, c, d,
    e, f, g, h, i, j, k, l,
    r, s, t, u, v, w,
    numberOfSatellites, crssi);

  size_t length = min(strlen(data), sizeof(data));
  return(dataBuffer.push(data, length, false));

}
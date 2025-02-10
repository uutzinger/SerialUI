/*
  Data Generator for Sine Wave Generation
*/

#include <RingBuffer.h>
#include <cmath>
extern RingBuffer dataBuffer;
extern char data[1024];

// Persistent phase tracking
static float phaseChannel1 = 0.0;
static float phaseChannel2 = 0.0;

// Configuration (adjustable frequencies and amplitudes)
float freqChannel1 = 500.0;  // High frequency (Hz)
float freqChannel2 = 250.0;   // Half of Channel 1
float amplitude1   = 1024;    // Amplitude for Channel 1
float amplitude2   = 512;     // Amplitude for Channel 2
float sampleRate   = 10000.0; // Sample rate in Hz (adjust as needed)

size_t generateSineWaveData() {
    char* ptr = data;

    // Generate 32 samples for Channel 1
    for (int i = 0; i < 32; i++) {
        int16_t value1 = int16_t(amplitude1 * sin(phaseChannel1));
        ptr += sprintf(ptr, "%d ", value1);
        phaseChannel1 += (2.0 * M_PI * freqChannel1) / sampleRate;
        if (phaseChannel1 > 2.0 * M_PI) phaseChannel1 -= 2.0 * M_PI; // Keep phase within [0, 2π]
    }

    ptr += sprintf(ptr, ", ");

    // Generate 32 samples for Channel 2 (half frequency)
    for (int i = 0; i < 32; i++) {
        int16_t value2 = int16_t(amplitude2 * sin(phaseChannel2));
        phaseChannel2 += (2.0 * M_PI * freqChannel2) / sampleRate;
        ptr += sprintf(ptr, "%d ", value2);
        if (phaseChannel2 > 2.0 * M_PI) phaseChannel2 -= 2.0 * M_PI; // Keep phase within [0, 2π]
    }
    ptr += sprintf(ptr, "\n");

    size_t length = min(strlen(data), sizeof(data));
    return dataBuffer.push(data, length, false);
}

size_t generateSineWaveDataMono() {
    char* ptr = data;

    // Generate 32 samples for Channel 1
    for (int i = 0; i < 32; i++) {
        int16_t value1 = int16_t(amplitude1 * sin(phaseChannel1));
        int16_t value2 = int16_t(amplitude2 * sin(phaseChannel2));
        phaseChannel1 += (2.0 * M_PI * freqChannel1) / sampleRate;
        phaseChannel2 += (2.0 * M_PI * freqChannel2) / sampleRate;
        ptr += sprintf(ptr, "%d\n", value1+value2);
        if (phaseChannel1 > 2.0 * M_PI) phaseChannel1 -= 2.0 * M_PI; // Keep phase within [0, 2π]
        if (phaseChannel2 > 2.0 * M_PI) phaseChannel2 -= 2.0 * M_PI; // Keep phase within [0, 2π]
    }

    size_t length = min(strlen(data), sizeof(data));
    return dataBuffer.push(data, length, false);
}

size_t generateSineWaveDataMonoHeader() {
    char* ptr = data;

    // Generate 32 samples for Channel 1
    for (int i = 0; i < 32; i++) {
        int16_t value1 = int16_t(amplitude1 * sin(phaseChannel1));
        int16_t value2 = int16_t(amplitude2 * sin(phaseChannel2));
        phaseChannel1 += (2.0 * M_PI * freqChannel1) / sampleRate;
        phaseChannel2 += (2.0 * M_PI * freqChannel2) / sampleRate;
        ptr += sprintf(ptr, "Channel_1: %d\n", value1+value2);
        if (phaseChannel1 > 2.0 * M_PI) phaseChannel1 -= 2.0 * M_PI; // Keep phase within [0, 2π]
        if (phaseChannel2 > 2.0 * M_PI) phaseChannel2 -= 2.0 * M_PI; // Keep phase within [0, 2π]
    }

    size_t length = min(strlen(data), sizeof(data));
    return dataBuffer.push(data, length, false);
}

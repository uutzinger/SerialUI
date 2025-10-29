#include <Arduino.h>
#include "ADPCM.h"

ADPCM adpcm;

void setup() {
    Serial.begin(115200);
    while (!Serial) { ; }

    // Example: 10 raw PCM samples
    int16_t samples[10] = { 100, 200, 300, 1000, 2000, -100, -200, -300, 32767, -32768 };
    size_t numSamples = 10;

    // Prepare output buffer for ADPCM
    // For 10 samples => (10+1)/2 = 5 bytes needed
    uint8_t encodedData[5];
    
    // 1) Encode
    int adpcmBytes = adpcm.encode(samples, numSamples, encodedData, 5);
    Serial.print("Encoded "); Serial.print(numSamples); 
    Serial.print(" samples into "); Serial.print(adpcmBytes); Serial.println(" bytes:");

    for (int i = 0; i < adpcmBytes; i++) {
        Serial.print(encodedData[i], HEX);
        Serial.print(" ");
    }
    Serial.println();

    // 2) Reset before decoding
    adpcm.reset();

    // 3) Decode
    int16_t decodedSamples[10];
    int decodedCount = adpcm.decode(encodedData, adpcmBytes, decodedSamples, 10);

    // Print results
    Serial.print("Decoded "); Serial.print(decodedCount); Serial.println(" samples:");
    for (int i = 0; i < decodedCount; i++) {
        Serial.print(decodedSamples[i]);
        Serial.print(" ");
    }
    Serial.println();
}

void loop() {
    // empty
}

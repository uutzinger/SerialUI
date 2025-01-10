#ifndef ADPCM_H
#define ADPCM_H

#include <Arduino.h>

class adpcm {
public:
    ADPCM();

    // Reset the internal predictor/index to defaults
    void reset();

    // Encode a buffer of int16_t PCM samples to 4-bit IMA ADPCM (mono).
    //
    //  - samples: pointer to int16_t array
    //  - numSamples: number of int16_t samples to encode
    //  - outData: pointer to uint8_t buffer for encoded results
    //  - outBufferSize: size of outData in bytes
    //
    // Return value:
    //  - number of bytes written to outData ( = (numSamples+1)/2 ), or 0 if outBufferSize is insufficient.
    //
    // This uses an internal predictor/index for the entire stream.  
    // If you want to restart from a known state for each chunk, call reset() before each chunk.
    int encode(const int16_t* samples, size_t numSamples,
               uint8_t* outData, size_t outBufferSize);

    // Decode a buffer of 4-bit IMA ADPCM data (mono) back to int16_t samples.
    //
    //  - adpcmData: pointer to the encoded data
    //  - nBytes: number of bytes of ADPCM data
    //  - outSamples: pointer to int16_t buffer for decoded PCM samples
    //  - outSamplesMax: how many int16_t samples outSamples can hold
    //
    // Return value:
    //  - number of int16_t samples actually written to outSamples.
    //
    // Each byte of ADPCM contains 2 nibbles => 2 samples.
    // So total samples to decode = nBytes * 2.
    // If outSamplesMax < nBytes*2, decoding is truncated.
    int decode(const uint8_t* adpcmData, size_t nBytes,
               int16_t* outSamples, size_t outSamplesMax);


private:
    int16_t _pred;       // current predictor
    int32_t _index;      // index into step size table

    int32_t clampIndex(int32_t idx);

    // Step size table [0..88]
    static const int16_t STEP_SIZE_TABLE[89];
    // Index table for nibble bits
    static const int8_t INDEX_TABLE[16];
};

#endif

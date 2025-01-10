#include "ADPCM.h"

// IMA ADPCM step size table (length = 89)
const int16_t ADPCM::STEP_SIZE_TABLE[89] = {
     7,    8,     9,    10,    11,    12,    13,    14,
    16,   17,    19,    21,    23,    25,    28,    31,
    34,   37,    41,    45,    50,    55,    60,    66,
    73,   80,    88,    97,   107,   118,   130,   143,
   157,  173,   190,   209,   230,   253,   279,   307,
   337,  371,   408,   449,   494,   544,   598,   658,
   724,  796,   876,   963,  1060,  1166,  1282,  1411,
  1552, 1707,  1878,  2066,  2272,  2499,  2749,  3024,
  3327, 3660,  4026,  4428,  4871,  5358,  5894,  6484,
  7132, 7845,  8630,  9493, 10442, 11487, 12635, 13899,
 15289,16818, 18500, 20350, 22385, 24623, 27086, 29794,
 32767
};

// IMA ADPCM index adjust table [0..15]
const int8_t ADPCM::INDEX_TABLE[16] = {
   -1, -1, -1, -1, 2, 4, 6, 8,
   -1, -1, -1, -1, 2, 4, 6, 8
};

ADPCM::ADPCM()
{
    reset();
}

void ADPCM::reset()
{
    _pred = 0;    // initial predictor = 0
    _index = 0;   // initial index = 0
}

int32_t ADPCM::clampIndex(int32_t idx)
{
    if (idx < 0)   return 0;
    if (idx > 88)  return 88;
    return idx;
}

//----------------------------------------------------------------------------
// Encode function
//----------------------------------------------------------------------------
int ADPCM::encode(const int16_t* samples, size_t numSamples,
                      uint8_t* outData, size_t outBufferSize)
{
    // We need 1 nibble per sample -> 2 samples per output byte
    // The required out buffer size is (numSamples+1)/2
    size_t requiredSize = (numSamples + 1) / 2;
    if (requiredSize > outBufferSize) {
        // Not enough output buffer
        return 0;
    }

    size_t nibbleIndex = 0; // which nibble we are writing
    for (size_t i = 0; i < requiredSize; i++) {
        outData[i] = 0; // initialize
    }

    for (size_t i = 0; i < numSamples; i++) {
        int16_t sample = samples[i];
        int32_t step = STEP_SIZE_TABLE[_index];
        int32_t diff = sample - _pred;

        uint8_t encodedNibble = 0;
        if (diff < 0) {
            encodedNibble = 8; // sign bit
            diff = -diff;
        }

        // Quantize
        if (diff >= step) {
            encodedNibble |= 4;
            diff -= step;
        }
        if (diff >= (step >> 1)) {
            encodedNibble |= 2;
            diff -= (step >> 1);
        }
        if (diff >= (step >> 2)) {
            encodedNibble |= 1;
            diff -= (step >> 2);
        }

        // Update predictor
        int32_t diffq = (step >> 3);
        if (encodedNibble & 4) diffq += step;
        if (encodedNibble & 2) diffq += (step >> 1);
        if (encodedNibble & 1) diffq += (step >> 2);

        if (encodedNibble & 8) {
            _pred -= diffq;
        } else {
            _pred += diffq;
        }

        // Clamp predictor
        if (_pred > 32767)   _pred = 32767;
        else if (_pred < -32768)  _pred = -32768;

        // Update index
        _index += INDEX_TABLE[encodedNibble & 0x07];
        _index = clampIndex(_index);

        // Pack nibble
        size_t outByteIndex = nibbleIndex >> 1;
        if ((nibbleIndex & 1) == 0) {
            // low nibble
            outData[outByteIndex] = (outData[outByteIndex] & 0xF0) | (encodedNibble & 0x0F);
        } else {
            // high nibble
            outData[outByteIndex] = (outData[outByteIndex] & 0x0F) | ((encodedNibble & 0x0F) << 4);
        }
        nibbleIndex++;
    }

    return requiredSize;
}

//----------------------------------------------------------------------------
// Decode function
//----------------------------------------------------------------------------
int IMA_ADPCM::decode(const uint8_t* adpcmData, size_t nBytes,
                      int16_t* outSamples, size_t outSamplesMax)
{
    // Each byte of ADPCM contains two 4-bit nibbles => 2 samples per byte
    // So total samples from nBytes is nBytes * 2
    size_t totalSamples = nBytes * 2;
    if (totalSamples > outSamplesMax) {
        // If the output buffer is smaller than the total needed, we truncate
        totalSamples = outSamplesMax;
    }

    size_t nibbleIndex = 0; // which nibble across all data
    for (size_t i = 0; i < totalSamples; i++) {
        // get nibble from the adpcmData
        size_t byteIndex = nibbleIndex >> 1; // nibbleIndex / 2
        uint8_t encodedNibble;

        if ((nibbleIndex & 1) == 0) {
            // low nibble
            encodedNibble = adpcmData[byteIndex] & 0x0F;
        } else {
            // high nibble
            encodedNibble = (adpcmData[byteIndex] >> 4) & 0x0F;
        }
        nibbleIndex++;

        // Decode nibble
        int32_t step = STEP_SIZE_TABLE[_index];
        int32_t diffq = step >> 3; // base difference

        if (encodedNibble & 4) diffq += step;
        if (encodedNibble & 2) diffq += (step >> 1);
        if (encodedNibble & 1) diffq += (step >> 2);

        if (encodedNibble & 8) {
            // sign bit set => negative
            _pred -= diffq;
        } else {
            _pred += diffq;
        }

        // Clamp predictor
        if (_pred > 32767)  _pred = 32767;
        if (_pred < -32768) _pred = -32768;

        // Update index
        _index += INDEX_TABLE[encodedNibble & 0x07];
        _index = clampIndex(_index);

        // Store output sample
        outSamples[i] = _pred;
    }

    // number of samples written
    return (int)totalSamples;
}
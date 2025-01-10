#ifndef COBS_H
#define COBS_H

#include <Arduino.h>

class COBS {
public:
    /**
     * Encodes the input data using COBS.
     * 
     * @param input Pointer to the input byte array.
     * @param length Length of the input data.
     * @param output Pointer to the output byte array (must be pre-allocated).
     * @return Length of the encoded output.
     */
    static size_t encode(const uint8_t* input, size_t length, uint8_t* output);

    /**
     * Decodes the input data using COBS.
     * 
     * @param input Pointer to the encoded input byte array.
     * @param length Length of the encoded input data.
     * @param output Pointer to the output byte array (must be pre-allocated).
     * @return Length of the decoded output, or 0 if an error occurs.
     */
    static size_t decode(const uint8_t* input, size_t length, uint8_t* output);
};

#endif // COBS_H

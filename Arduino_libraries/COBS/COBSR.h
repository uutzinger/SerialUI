#ifndef COBSR_H
#define COBSR_H

#include <Arduino.h>

class COBSR {
public:
    /**
     * Encodes the input data using COBS/R.
     * 
     * @param input Pointer to the input byte array.
     * @param length Length of the input data.
     * @param output Pointer to the output byte array (must be pre-allocated).
     * @return Length of the encoded output.
     */
    static size_t encode(const uint8_t* input, size_t length, uint8_t* output);

    /**
     * Decodes the input data using COBS/R.
     * 
     * @param input Pointer to the encoded input byte array.
     * @param length Length of the encoded input data.
     * @param output Pointer to the output byte array (must be pre-allocated).
     * @return Length of the decoded output, or 0 if an error occurs.
     */
    static size_t decode(const uint8_t* input, size_t length, uint8_t* output);
};

#endif // COBSR_H

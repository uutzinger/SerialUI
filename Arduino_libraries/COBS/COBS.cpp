#include "COBS.h"

size_t COBS::encode(const uint8_t* input, size_t length, uint8_t* output) {
    const uint8_t* input_end = input + length;
    uint8_t* code_ptr = output;  // Points to the current code byte.
    uint8_t* write_ptr = output + 1;  // Points to the next output byte.
    uint8_t code = 1;  // Start code.

    while (input < input_end) {
        if (*input == 0) {
            // Write the current code and start a new code block.
            *code_ptr = code;
            code_ptr = write_ptr++;
            code = 1;
        } else {
            // Write the non-zero byte.
            *write_ptr++ = *input;
            code++;

            // If the code reaches 0xFF, write the current code and start a new block.
            if (code == 0xFF) {
                *code_ptr = code;
                code_ptr = write_ptr++;
                code = 1;
            }
        }
        input++;
    }

    // Write the final code byte.
    *code_ptr = code;

    // Return the total encoded length.
    return write_ptr - output;
}

size_t COBS::decode(const uint8_t* input, size_t length, uint8_t* output) {
    if (length == 0) return 0;  // No data to decode.

    const uint8_t* input_end = input + length;
    uint8_t* write_ptr = output;

    while (input < input_end) {
        uint8_t code = *input++;
        if (code == 0 || input + code - 1 > input_end) {
            // Invalid code or out of bounds.
            return 0;
        }

        // Copy the bytes specified by the code.
        for (uint8_t i = 1; i < code; i++) {
            *write_ptr++ = *input++;
        }

        // If the code is less than 0xFF, insert a zero byte.
        if (code < 0xFF && input < input_end) {
            *write_ptr++ = 0;
        }
    }

    // Return the total decoded length.
    return write_ptr - output;
}

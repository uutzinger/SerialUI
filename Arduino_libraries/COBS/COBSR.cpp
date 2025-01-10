#include "COBSR.h"

size_t COBSR::encode(const uint8_t* input, size_t length, uint8_t* output) {
    const uint8_t* input_end = input + length;
    uint8_t* code_ptr = output;       // Points to the current code byte.
    uint8_t* write_ptr = output + 1; // Points to the next output byte.
    uint8_t code = 1;                 // Start code.
    uint8_t last_byte = 0;

    while (input < input_end) {
        if (*input == 0) {
            // Found a zero byte; write the code and start a new block.
            *code_ptr = code;
            code_ptr = write_ptr++;
            code = 1;
        } else {
            // Write the non-zero byte.
            *write_ptr++ = *input;
            last_byte = *input;
            code++;

            // If the code reaches 0xFF, write it and start a new block.
            if (code == 0xFF) {
                *code_ptr = code;
                code_ptr = write_ptr++;
                code = 1;
            }
        }
        input++;
    }

    // Handle the final block for COBS/R.
    if (last_byte < code) {
        // Encode as normal COBS.
        *code_ptr = code;
    } else {
        // Special COBS/R encoding: replace code byte with last data byte.
        *code_ptr = last_byte;
        write_ptr--;
    }

    return write_ptr - output; // Return the encoded length.
}

size_t COBSR::decode(const uint8_t* input, size_t length, uint8_t* output) {
    if (length == 0) return 0; // No data to decode.

    const uint8_t* input_end = input + length;
    uint8_t* write_ptr = output;

    while (input < input_end) {
        uint8_t code = *input++;
        if (code == 0) return 0; // Invalid input (zero byte in encoded data).

        uint8_t copy_len = code - 1;
        if (input + copy_len > input_end) return 0; // Out-of-bounds check.

        // Copy non-zero bytes to the output.
        for (uint8_t i = 0; i < copy_len; i++) {
            *write_ptr++ = *input++;
        }

        // Add a zero byte unless this is the final block.
        if (code != 0xFF && input < input_end) {
            *write_ptr++ = 0;
        }
    }

    return write_ptr - output; // Return the decoded length.
}

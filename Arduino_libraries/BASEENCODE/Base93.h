#ifndef BASE93_H
#define BASE93_H

#include <Arduino.h>

// The encoding table
extern const char table[];
extern const size_t TABLE_SIZE;

// Lookup table for ASCII char -> value
extern int8_t char_to_val[256];

// Initialize the lookup table
void init_char_to_val();

// Encode binary data (up to 8 bytes) into a base93 string.
// data: pointer to input bytes
// length: number of bytes in data (1 to 8 for typical usage)
// output: char buffer to store the null-terminated encoded string
void encode(const uint8_t *data, size_t length, char *output);

// Decode a base93 string into binary data.
// input: null-terminated encoded string
// output: buffer to store decoded bytes
// out_length: number of bytes to decode (based on data type)
// returns 0 on success, -1 on failure (invalid character)
int decode(const char *input, uint8_t *output, size_t out_length);

#endif // BASE93_H

#include "Base93.h"
#include <string.h>

/****************************************************************
// How to use this code
// #include <Arduino.h>
// #include "Base93.h"

// void setup() {
//     Serial.begin(115200);
//     init_char_to_val(); // Initialize lookup table

//     // Example: Encode/Decode an int (4 bytes)
//     int testValue = 123456;
//     uint8_t *p = (uint8_t*)&testValue;
    
//     char encoded[32];
//     encode(p, sizeof(testValue), encoded);
//     Serial.print("Encoded int: ");
//     Serial.println(encoded);

//     int decodedValue = 0;
//     if (decode(encoded, (uint8_t*)&decodedValue, sizeof(decodedValue)) == 0) {
//         Serial.print("Decoded int: ");
//         Serial.println(decodedValue);
//     } else {
//         Serial.println("Decoding failed!");
//     }
// }
***************************************************************/

// Readable ASCII characters excluding space
const char table[] = {
    '!', '"', '#', '$', '%', '&', '\'', '(', ')', '*', '+', ',', '-', '.', '/', 
    '0', '1', '2', '3','4', '5', '6', '7', '8', '9', ';', '<', '=', '>', '?',
    '@','A', 'B', 'C', 'D', 'E', 'F','G', 'H', 'I', 'J', 'K', 'L','M', 'N', 'O',
    'P', 'Q', 'R','S', 'T', 'U', 'V', 'W', 'X','Y','Z', '[', '\\', ']', '^', '_',
    '`', 'a', 'b', 'c', 'd', 'e','f', 'g', 'h', 'i', 'j','k','l', 'm', 'n', 'o',
    'p', 'q','r', 's', 't', 'u', 'v','w', 'x', 'y', 'z', '{', '|', '}', '~'
};
const size_t TABLE_SIZE = sizeof(table) / sizeof(table[0]);

int8_t char_to_val[256];

void init_char_to_val() {
    // Set all to -1 initially
    for (int i = 0; i < 256; i++) {
        char_to_val[i] = -1;
    }
    // Set each character's value
    for (size_t i = 0; i < TABLE_SIZE; i++) {
        unsigned char c = (unsigned char)table[i];
        char_to_val[c] = (int8_t)i;
    }
}

void encode(const uint8_t *data, size_t length, char *output) {
    uint64_t value = 0;
    for (size_t i = 0; i < length; i++) {
        value = (value << 8) | data[i];
    }

    if (value == 0 && length > 0) {
        // If value is 0 but we had data, output a single '!' (table[0])
        output[0] = table[0];
        output[1] = '\0';
        return;
    } else if (length == 0) {
        // If no data, return empty string (choose how you want to handle this)
        output[0] = '\0';
        return;
    }

    char buffer[32];
    int pos = 0;
    while (value > 0) {
        uint64_t remainder = value % TABLE_SIZE;
        value = value / TABLE_SIZE;
        buffer[pos++] = table[remainder];
    }

    for (int i = 0; i < pos; i++) {
        output[i] = buffer[pos - i - 1];
    }
    output[pos] = '\0';
}

int decode(const char *input, uint8_t *output, size_t out_length) {
    uint64_t value = 0;
    size_t len = strlen(input);
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)input[i];
        int digit = char_to_val[c];
        if (digit < 0) {
            return -1; // invalid character
        }
        value = value * TABLE_SIZE + (uint64_t)digit;
    }

    for (size_t i = 0; i < out_length; i++) {
        size_t shift = (out_length - 1 - i) * 8;
        output[i] = (uint8_t)((value >> shift) & 0xFF);
    }

    return 0;
}

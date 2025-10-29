#include <COBS.h>

void setup() {
    Serial.begin(9600);

    // Test data
    uint8_t input[] = {0x11, 0x22, 0x00, 0x33, 0x44};
    size_t input_length = sizeof(input);

    // Allocate buffers
    uint8_t encoded[COBS_ENCODE_DST_BUF_LEN_MAX(input_length)];
    uint8_t decoded[COBS_DECODE_DST_BUF_LEN_MAX(input_length)];

    // Encode
    size_t encoded_length = COBS::encode(input, input_length, encoded);
    Serial.print("Encoded: ");
    for (size_t i = 0; i < encoded_length; i++) {
        Serial.print(encoded[i], HEX);
        Serial.print(" ");
    }
    Serial.println();

    // Decode
    size_t decoded_length = COBS::decode(encoded, encoded_length, decoded);
    if (decoded_length > 0) {
        Serial.print("Decoded: ");
        for (size_t i = 0; i < decoded_length; i++) {
            Serial.print(decoded[i], HEX);
            Serial.print(" ");
        }
        Serial.println();
    } else {
        Serial.println("Decoding failed!");
    }
}

void loop() {
    // Nothing to do in loop
}

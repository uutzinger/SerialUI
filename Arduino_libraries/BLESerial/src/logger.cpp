#include "logger.h"

int currentLogLevel = LOG_LEVEL_DEBUG; // Default log level
char binaryBuffer[9];  // Buffer for a single 8-bit binary string

void uint8ToBinaryString(char *buffer, uint8_t value) {
    for (int i = 7; i >= 0; i--) {
        buffer[7 - i] = ((value >> i) & 1) ? '1' : '0';
    }
    buffer[8] = '\0'; // Null-terminate the string
}

void logPrintLevelln(const char* level, const char* format, ...) {
    Serial.print("[");
    Serial.print(level);
    Serial.print("] ");

    va_list args;
    va_start(args, format);

    char buffer[256];
    size_t index = 0;

    while (*format) {
        if (*format == '%' && *(format + 1) == 'b') {  // Handle %b
            format += 2;
            uint8_t value = va_arg(args, int);  // uint8_t is promoted to int
            uint8ToBinaryString(binaryBuffer, value);
            index += snprintf(buffer + index, sizeof(buffer) - index, "%s", binaryBuffer);
        } else {
            buffer[index++] = *format++;
        }
        if (index >= sizeof(buffer) - 1) break;  // Prevent overflow
    }

    buffer[index] = '\0';
    va_end(args);

    Serial.println(buffer);
}

void logPrintLevel(const char* level, const char* format, ...) {
    Serial.print("[");
    Serial.print(level);
    Serial.print("] ");

    va_list args;
    va_start(args, format);

    char buffer[256];
    size_t index = 0;

    while (*format) {
        if (*format == '%' && *(format + 1) == 'b') {  // Handle %b
            format += 2;
            uint8_t value = va_arg(args, int);
            uint8ToBinaryString(binaryBuffer, value);
            index += snprintf(buffer + index, sizeof(buffer) - index, "%s", binaryBuffer);
        } else {
            buffer[index++] = *format++;
        }
        if (index >= sizeof(buffer) - 1) break;
    }

    buffer[index] = '\0';
    va_end(args);

    Serial.print(buffer);
}

void logPrint(const char* format, ...) {
    va_list args;
    va_start(args, format);

    char buffer[256];
    size_t index = 0;

    while (*format) {
        if (*format == '%' && *(format + 1) == 'b') {  // Handle %b
            format += 2;
            uint8_t value = va_arg(args, int);
            uint8ToBinaryString(binaryBuffer, value);
            index += snprintf(buffer + index, sizeof(buffer) - index, "%s", binaryBuffer);
        } else {
            buffer[index++] = *format++;
        }
        if (index >= sizeof(buffer) - 1) break;
    }

    buffer[index] = '\0';
    va_end(args);

    Serial.print(buffer);
}

void logPrintln(const char* format, ...) {
    va_list args;
    va_start(args, format);

    char buffer[256];
    size_t index = 0;

    while (*format) {
        if (*format == '%' && *(format + 1) == 'b') {  // Handle %b
            format += 2;
            uint8_t value = va_arg(args, int);
            uint8ToBinaryString(binaryBuffer, value);
            index += snprintf(buffer + index, sizeof(buffer) - index, "%s", binaryBuffer);
        } else {
            buffer[index++] = *format++;
        }
        if (index >= sizeof(buffer) - 1) break;
    }

    buffer[index] = '\0';
    va_end(args);

    Serial.println(buffer);
}

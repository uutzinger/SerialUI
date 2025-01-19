#include "RingBuffer.h"
#include <string.h> // for memcpy
#include <Arduino.h> // For embedded system compatibility

#define MIN(a, b) ((a) < (b) ? (a) : (b)) // Ensure Arduino-compatible min()

RingBuffer::RingBuffer(size_t size) : capacity(size), start(0), end(0), count(0) {
    buffer = (char*)malloc(size);
}

RingBuffer::~RingBuffer() {
    free(buffer);
}

size_t RingBuffer::push(const char* data, size_t data_len, bool overwrite) {
    if (data_len == 0 || !buffer) {
        // No data to push
        return 0;
    }

    // If data is larger than capacity, truncate it
    if (data_len > capacity) {
        data_len = capacity;
    }

    // Check if we have enough space. If not, handle overwrite
    size_t available = capacity - count;
    if (data_len > available) {
        if (!overwrite) {
            // Not enough space and not allowed to overwrite
            return 0;
        }

        // Overwriting: Need to advance start to free up space
        size_t overflow = data_len - available;
        start = (start + overflow) % capacity;
        count = min(capacity, count + data_len); 
    }

    // Now proceed with writing
    // There are two possible cases:
    // 1) The write does not wrap around the buffer end.
    // 2) The write wraps around and must be done in two parts.

    // Calculate how many bytes can be written in one go till the end of buffer
    size_t firstPart = MIN(data_len, capacity - end);
    memcpy(&buffer[end], data, firstPart);

    size_t secondPart = data_len - firstPart;
    if (secondPart > 0) {
        // Wrap around the buffer and write remaining bytes at the beginning
        memcpy(buffer, data + firstPart, secondPart);
    }

    // Update end and count
    end = (end + data_len) % capacity;
    count = MIN(capacity, count + data_len); 

    return data_len;
}

size_t RingBuffer::pop(char* output, size_t len) {
    if (count == 0 || !buffer) return 0; // Buffer empty

    size_t charsToRead = MIN(len, count);
    size_t firstPart = MIN(charsToRead, capacity - start);
    memcpy(output, &buffer[start], firstPart);

    size_t secondPart = charsToRead - firstPart;
    if (secondPart > 0) {
        memcpy(output + firstPart, buffer, secondPart);
    }

    start = (start + charsToRead) % capacity;
    count -= charsToRead;

    // Reset start & end when buffer becomes empty
    if (count == 0) {
        start = 0;
        end = 0;
    }

    return charsToRead;
}

bool RingBuffer::isFull() const {
    return count == capacity;
}

bool RingBuffer::isEmpty() const {
    return count == 0;
}

size_t RingBuffer::size() const {
    return count;
}

void RingBuffer::clear() {
    start = 0;
    end = 0;
    count = 0;
}
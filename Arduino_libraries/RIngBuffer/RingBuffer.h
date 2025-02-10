#ifndef RINGBUFFER_H
#define RINGBUFFER_H

#include <Arduino.h> // or <cstddef>, <cstring> if not using Arduino

class RingBuffer {
private:
    char* buffer;
    size_t capacity;
    size_t start;
    size_t end;
    size_t count;

public:
    // Constructor to initialize the buffer with a given capacity
    RingBuffer(size_t size);

    // Destructor to free memory
    ~RingBuffer();

    // Push data into the ring buffer
    // data: pointer to raw bytes
    // data_len: length of the data in bytes
    // overwrite: if true, older data is overwritten when buffer is full
    size_t push(const char* data, size_t data_len, bool overwrite = false);

    // Pop a specified number of characters from the ring buffer
    size_t pop(char* output, size_t len);

    bool isFull() const;
    bool isEmpty() const;
    size_t size() const;
    void clear();

};

#endif // RINGBUFFER_H

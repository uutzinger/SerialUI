// ************************************************************************
// RingBuffer.h
//
// Ring buffer (circular buffer) implementation in C++
// Thread safe on ESP32 using per-instance spinlocks
// Template class supporting any data type T
// Buffer size N must be a power of 2 for efficiency
//
// push
//   Push data into the ring buffer
//   If overwrite is true, older data is overwritten when buffer is full
// pop
//   Pop data from the ring buffer
// peek
//   Peek at data in the ring buffer without removing it
// consume
//   Remove data from the ring buffer without copying it out
// available
//   Get number of elements currently in the buffer
// capacity
//   Get total capacity of the buffer
// clear
//   Clear the buffer
//
// ************************************************************************
#ifndef RB_MIN
    #define RB_MIN(a, b) ((a) < (b) ? (a) : (b))
#endif

#ifndef RINGBUFFER_H
#define RINGBUFFER_H

#include <string.h>     // for memcpy
#include <stdint.h>     // for uint8_t, uint16_t
#include <type_traits>  // for std::conditional

#if defined(ESP32)
    # include "freertos/FreeRTOS.h"
    # include "freertos/portmacro.h"
#endif

// Define critical section helpers BEFORE class so they are visible where used.
// They reference 'this->mux_' which is a per-instance spinlock.
#ifdef ARDUINO_ARCH_ESP32
#  define RB_CRITICAL_ENTER() portENTER_CRITICAL(const_cast<portMUX_TYPE*>(&this->mux_))
#  define RB_CRITICAL_EXIT()  portEXIT_CRITICAL(const_cast<portMUX_TYPE*>(&this->mux_))
#else
#  define RB_CRITICAL_ENTER()
#  define RB_CRITICAL_EXIT()
#endif

template <typename T, size_t N>
class RingBuffer {
public:
    RingBuffer() : head(0), tail(0), count(0) {
        #if defined(ESP32)
        mux_ = portMUX_INITIALIZER_UNLOCKED;
        #endif
    }
    // Push data into the ring buffer
    // data: pointer to data that will be added to the buffer
    // data_len: number of data elements
    // overwrite: if true, older data is overwritten when buffer is full
    size_t push(const T& data, bool overwrite = false);
    size_t push(const T* data, size_t data_len, bool overwrite = false);

    // Pop a specified number of characters from the ring buffer
    size_t pop(T& output);
    size_t pop(T* output, size_t len);
    
    // Peek a specified number of characters from the ring buffer and leave them in the buffer
    size_t peek(T& output) const;
    size_t peek(T* output, size_t len) const;

    // Consume (remove) a specified number of characters from the ring buffer without copying them out
    size_t consume();
    size_t consume(size_t len);

    size_t available() const {
        // Snapshot under critical section to avoid torn reads
        #if defined(ESP32)
            RB_CRITICAL_ENTER();
            size_t c = count;
            RB_CRITICAL_EXIT();
        return c;
        #else
            return count;
        #endif
    }
    size_t capacity() const { return N; }
    void clear();

private:
    T buffer[N]; // fixed size buffer

    // Select optimal index type based on buffer size
    using IndexType = typename std::conditional<
        (N <= 256), uint8_t,
        typename std::conditional<(N <= 65536), uint16_t, size_t>::type
    >::type;

    IndexType head;
    IndexType tail;
    IndexType count;

    static constexpr bool isPowerOfTwo(size_t n) { return (n & (n - 1)) == 0; }
    static_assert(isPowerOfTwo(N), "RingBuffer capacity must be a power of 2 for efficiency");

#if defined(ESP32)
    // Per-instance spinlock for critical sections. Mark mutable so it can be used in const methods.
    mutable portMUX_TYPE mux_;
#endif
};

// Push a single element
template <typename T, size_t N>
size_t RingBuffer<T, N>::push(const T& data, bool overwrite) {
    return push(&data, 1, overwrite);
}

// Push multiple elements
template <typename T, size_t N>
size_t RingBuffer<T, N>::push(const T* data, size_t data_len, bool overwrite) {
    if (data_len == 0) return 0;
    RB_CRITICAL_ENTER();

    size_t available_space = N - count;
    if (data_len > available_space && !overwrite) {
        RB_CRITICAL_EXIT();
        return 0;
    }

    if (data_len > available_space) {
        // Overwriting: advance tail to free up space
        size_t overflow = data_len - available_space;
        tail = (tail + overflow) & (N - 1);
    }

    // Optimized single-element push
    if (data_len == 1) {
        buffer[head] = *data;
    } else {
        // Multi-element push
        size_t firstPart = RB_MIN(data_len, N - head);
        memcpy(&buffer[head], data, firstPart * sizeof(T));

        size_t secondPart = data_len - firstPart;
        if (secondPart > 0) {
            // Wrap around the buffer and write remaining bytes at the beginning
            memcpy(buffer, data + firstPart, secondPart * sizeof(T));
        }
    }

    // Update head and count
    head = (head + data_len) & (N - 1);
    count = RB_MIN(static_cast<size_t>(N), static_cast<size_t>(count + data_len));

    RB_CRITICAL_EXIT();
    return data_len;
}

// Pop a single element
template <typename T, size_t N>
size_t RingBuffer<T, N>::pop(T& output) {
    return pop(&output, 1);
}

// Pop multiple elements
template <typename T, size_t N>
size_t RingBuffer<T, N>::pop(T* output, size_t len) {
    if (len == 0) return 0;
    RB_CRITICAL_ENTER();

    if (count == 0) {
        RB_CRITICAL_EXIT();
        return 0; // Buffer empty
    }

    size_t charsToRead = RB_MIN(len, static_cast<size_t>(count));
    size_t firstPart   = RB_MIN(charsToRead, N - tail);

    if (charsToRead == 1) {
        *output = buffer[tail];
    } else {
        memcpy(output, &buffer[tail], firstPart * sizeof(T));
        size_t secondPart = charsToRead - firstPart;
        if (secondPart > 0) {
            // Wrap around the buffer and read remaining bytes from the beginning
            memcpy(output + firstPart, buffer, secondPart * sizeof(T));
        }
    }

    tail = (tail + charsToRead) & (N - 1);
    count -= charsToRead;

    // Reset tail & head when buffer becomes empty
    if (count == 0) {
        tail = 0;
        head = 0;
    }

    RB_CRITICAL_EXIT();
    return charsToRead;
}

// Peek at single element
template <typename T, size_t N>
size_t RingBuffer<T, N>::peek(T& output) const {
    RB_CRITICAL_ENTER();
    if (count == 0) {
        RB_CRITICAL_EXIT();
        return 0; // Buffer empty
    }
    output = buffer[tail]; // Read the element at tail without modifying it
    RB_CRITICAL_EXIT();
    return 1;
}

// Peek at multiple elements
template <typename T, size_t N>
size_t RingBuffer<T, N>::peek(T* output, size_t len) const {
    if (len == 0) return 0; // Nothing to peek
    RB_CRITICAL_ENTER();
    if (count == 0) {
        RB_CRITICAL_EXIT();
        return 0; // Nothing to peek
    }

    size_t peekLen = RB_MIN(len, static_cast<size_t>(count));
    size_t firstPart = RB_MIN(peekLen, N - tail);

    // Copy first segment
    memcpy(output, &buffer[tail], firstPart * sizeof(T));

    // Copy second segment if wrap-around occurs
    size_t secondPart = peekLen - firstPart;
    if (secondPart > 0) {
        memcpy(output + firstPart, buffer, secondPart * sizeof(T));
    }

    RB_CRITICAL_EXIT();
    return peekLen;
}

// Consume a single element
template <typename T, size_t N>
size_t RingBuffer<T, N>::consume() {
    RB_CRITICAL_ENTER();
    if (count == 0) {
        RB_CRITICAL_EXIT();
        return 0; // empty
    }
    tail = (tail + 1) & (N - 1);
    --count;
    if (count == 0) { tail = 0; head = 0; }
    RB_CRITICAL_EXIT();
    return 1;
}

// Consume multiple elements
template <typename T, size_t N>
size_t RingBuffer<T, N>::consume(size_t len) {
    if (len == 0) return 0;
    RB_CRITICAL_ENTER();
    if (count == 0) {
        RB_CRITICAL_EXIT();
        return 0;
    }
    size_t to_consume = RB_MIN(len, static_cast<size_t>(count));
    tail = (tail + to_consume) & (N - 1);
    count = static_cast<IndexType>(static_cast<size_t>(count) - to_consume);
    if (count == 0) { tail = 0; head = 0; }
    RB_CRITICAL_EXIT();
    return to_consume;
}

// Clear the buffer
template <typename T, size_t N>
void RingBuffer<T, N>::clear() {
    RB_CRITICAL_ENTER();
    head = 0;
    tail = 0;
    count = 0;
    RB_CRITICAL_EXIT();
}

#endif // RINGBUFFER_H

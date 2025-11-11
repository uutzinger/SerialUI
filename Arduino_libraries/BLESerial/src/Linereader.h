
#pragma once
#include <Arduino.h>

// Simple, non-blocking line reader for any Stream.
// Usage:
//   LineReader<128> lr;
//   char line[128];
//   if (lr.poll(bleSerial, line, sizeof(line))) { /* got a full line */ }
template <size_t N>
class LineReader {
public:
    LineReader() : idx_(0), sawCR_(false) {}

    // Returns true when a full line is collected; writes NUL-terminated line into out.
    // Lines end on '\n' or '\r\n' (CRLF). Carriage return alone also ends a line.
    bool poll(Stream& s, char* out, size_t outLen) {
        while (s.available() > 0) {
            int c = s.read();
            if (c < 0) break;

            if (c == '\r') {
                sawCR_ = true;
                continue;
            }
            if (c == '\n' || sawCR_) {
                // Finish line
                buf_[min(idx_, N - 1)] = '\0';
                copyOut(out, outLen);
                idx_ = 0;
                sawCR_ = false;
                return true;
            }

            if (idx_ < N - 1) {
                buf_[idx_++] = (char)c;
            } else {
                // Buffer full: terminate and emit as a line, then reset.
                buf_[N - 1] = '\0';
                copyOut(out, outLen);
                idx_ = 0;
                sawCR_ = false;
                return true;
            }
        }
        return false;
    }

    void reset() { idx_ = 0; sawCR_ = false; }

private:
    void copyOut(char* out, size_t outLen) {
        if (!out || outLen == 0) return;
        size_t n = min(outLen - 1, idx_);
        memcpy(out, buf_, n);
        out[n] = '\0';
    }

    char   buf_[N]{};
    size_t idx_;
    bool   sawCR_;
};
# BLE Serial Library

## Introduction

BLESerial is a library that allows serial communication over a BLE connection. It implements the Nordic UART Service (NUS).

You will need a program like SerialUI (https://github.com/uutzinger/SerialUI) to communicate with your micro controller as Arduino IDE Monitor does not yet have NUS support.

Functions:
 - begin(mode, deviceName, secure); 
 - end();
 - available();
 - read(); / read(*dst,n);
 - peek(); / peek(*dst, n);
 - write(b) / write(*b, n) override;
 - writeTimeout(t*p, n, timeoutMs);
 - writeReady()
 - writeAvailable(n)
 - flush()
 - update()

Setters:
- setLogLevel(level);
- requestMTU(mtu);

Status:
- connected();
- mtu();
- mode();
- bytesRx();
- bytesTx();
- rxDrops();
- txDrops();
- interval();
- rssi()
- mac();
- txBuffered();
- rxBuffered();


## Installation

Installation occurs through the Arduino library manager.

Requires a terminal application on a client computer that supports NUS.

## Dependencies

- NimBLE (https://github.com/h2zero/NimBLE-Arduino)
- RingBuffer (provided)

## Quick Start

```
#import BLESerial
#import LineReader

BLESerial               ble;
LineReader<128>         lr;

void setup() {
  ble.begin(BLESerial::Mode::Fast, "BLESerialDevice", false)
  ble.setPumpMode(BLESerial::PumpMode::Polling);
}

void loop(){

  ble.update();

  // read command
  if (lr.poll(ble, line, sizeof(line))) { 
      auto reply = [&](const char* msg){
        Serial.println(msg);
        ble.write(reinterpret_cast<const uint8_t*>(msg), strlen(msg));
        ble.write(reinterpret_cast<const uint8_t*>("\r\n"), 2);
      };

    if (strcasecmp(line, "?") == 0) {
      reply(helpmsg);
    } else if (...) {
        ...
    }
  }
  
  ... generate data
  
  ble.write(reinterpret_cast<const uint8_t*>(data), (size_t)dataLen);
}

```

# Contributing

Urs Utzinger 2025

# License

See [LICENSE](License.txt).

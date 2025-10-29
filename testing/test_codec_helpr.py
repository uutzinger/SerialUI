import os
import struct
import time
import matplotlib
import numpy as np
matplotlib.use('QtAgg') 
import matplotlib.pyplot as plt
from  cobs import cobs               # serial data encoding (byte stuffing)
import zlib                          # Standard Python zlib library
import tamp                          # tamp compression library


from Codec_helper import (
    GeneralCodec,
    PrintableCodec,
    Compressor,
    ADPCMCodec,
    ArduinoTextStreamProcessor,
    BinaryStreamProcessor
)

VERBOSE = False

text = """
The Fox and the Moonlit Night
In the forest deep where the shadows play,
A fox set out at the close of day.
His fur was bright, his step was light,
Beneath the stars and the moon so white.

He wandered far through the trees so tall,
Listening close to the owl's soft call.
With a leap and bound, he chased the breeze,
Darting swiftly between the trees.

The brook did glisten, the leaves did sway,
And the fox kept on till the break of day.
A rabbit peered from a thicket near,
The fox gave a smile, "You’ve nothing to fear."

Through meadows wide and hills so steep,
The fox’s journey would never sleep.
He climbed a ridge to behold the view,
Where the sky was painted in morning's hue.

The sun arose, and the stars grew dim,
The fox felt joy as he ran with vim.
For the forest calls and the winds do sigh,
To the quick brown fox 'neath the open sky.

In the heart of nature, he found his home,
Under the heavens, free to roam.
And so, dear reader, remember this tale,
Of the fox's journey through hill and dale.
"""

# General Codec with base 254 encoding [PASSED]

base = 254
codec = GeneralCodec(base)
max_digits = codec.compute_digits(8) # encode double with 8 bytes
original_data = 98.2
byte_data = struct.pack('d', original_data) # 'f' for float, 'd' for double
if VERBOSE: print(f"Original: {original_data}")
encoded = codec.encode(byte_data, length = 8)
if VERBOSE: print(f"Encoded (base254): {encoded}")
decoded = codec.decode(encoded, length = 8)
if VERBOSE: print(f"Decoded: {decoded}")
value = struct.unpack('d', decoded)[0]
if VERBOSE: print(f"Value: {value}")
assert byte_data == decoded


# Printable Codec [PASSED]

codec = PrintableCodec()
if VERBOSE: print(f"Table: {codec.table}")
if VERBOSE: print(f"Base: {codec.base}")
if VERBOSE: print(f"Base {codec.char_to_val}")
encoded = codec.encode(byte_data, length = 8)
if VERBOSE: print(f"Encoded (printable): {encoded}")
decoded = codec.decode(encoded, length = 8)
if VERBOSE: print(f"Decoded: {decoded}")
value = struct.unpack('d', decoded)[0]
if VERBOSE: print(f"Value: {value}")
assert byte_data == decoded

# Compressor RLE [PASSED]
# 30 microseconds encode for 1k text
# 5300 microseconds decode for 1k text !!!!!!!!!!!!!!!
byte_data = bytearray(text.encode('utf-8'))

compressor = Compressor("rle")
if VERBOSE: print(f"Original: {byte_data}")
compressed = compressor.compress(byte_data)
tic = time.perf_counter()
for i in range(100):
    compressed = compressor.compress(byte_data)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
if VERBOSE: print(f"Compressed (rle): {compressed}")
print(f"Elapsed time RLE compress: {len(byte_data)/time_elapsed/1024/1024} Mega bytes/sec")
tic = time.perf_counter()
for i in range(100):
    decompressed = compressor.decompress(compressed)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"Elapsed time RLE decompress: {len(decompressed)/time_elapsed/1024/1024} Mega bytes/sec")
print(f"Elapsed time RLE ratio: {len(compressed)/len(decompressed)*100.} [%]")
assert byte_data == decompressed

# Compressor ZIP  [PASSED]
# 200 microseconds for 1k text compress
# 1000 microseconds for 1k text decompress

compressor = Compressor("zlib")
if VERBOSE: print(f"Original: {byte_data}")
compressed = compressor.compress(byte_data)
tic = time.perf_counter()
for i in range(100):
    compressed = compressor.compress(byte_data)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
if VERBOSE:  print(f"Compressed (zip): {compressed}")
print(f"Elapsed time ZLIB compress: {len(byte_data)/time_elapsed/1024/1024} Mega bytes/sec")
decompressed = compressor.decompress(compressed)
tic = time.perf_counter()
for i in range(100):
    decompressed = compressor.decompress(compressed)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"Elapsed time ZLIB decompress: {len(decompressed)/time_elapsed/1024/1024} Mega bytes/sec")
print(f"Elapsed time ZLIB ratio: {len(compressed)/len(decompressed)*100.} [%]")
assert byte_data == decompressed

# Compressor TAMP  [PASSED]
# 620 microseconds for 1k text compress
# 230 microseconds for 1k text decompress

compressor = Compressor("tamp")
if VERBOSE: print(f"Original: {byte_data}")
compressed = compressor.compress(byte_data)
tic = time.perf_counter()
for i in range(100):
    compressed = compressor.compress(byte_data)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
if VERBOSE: print(f"Compressed (tamp): {compressed}")
print(f"Elapsed time TAMP compress: {len(byte_data)/time_elapsed/1024/1024} Mega bytes/sec")
decompressed = compressor.decompress(compressed)
tic = time.perf_counter()
for i in range(100):
    decompressed = compressor.decompress(compressed)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"Elapsed time TAMP decompress: {len(decompressed)/time_elapsed/1024/1024} Mega bytes/sec")
print(f"Elapsed time TAMP ratio: {len(compressed)/len(decompressed)*100.} [%]")
assert byte_data == decompressed

# COBS  [PASSED]
# 80 microseconds for 1k text encode
# 85 microseconds for 1k text decode`

data = os.urandom(1024)
if VERBOSE: print(f"Original: {data}")
encoded_packet = cobs.encode(data) + b'\x00'
tic = time.perf_counter()
for i in range(100):
    encoded_packet = cobs.encode(data) + b'\x00'
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
if VERBOSE: print(f"Encoded (cobs): {encoded_packet}")
print(f"Elapsed time COBS encode: {len(data)/time_elapsed/1024/1024} Mega bytes/sec")
packet = encoded_packet.split(b'\x00')[0]
decoded_packet = cobs.decode(packet)
tic = time.perf_counter()
for i in range(100):
    decoded_packet = cobs.decode(packet)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"Elapsed time COBS decode: {len(decoded_packet)/time_elapsed/1024/1024} Mega bytes/sec")
decoded_packet = cobs.decode(packet)
assert data == decoded_packet

# ADPCM

# Mono [PASSED]
# 780 micro seconds to encode 1000 samples 1.3 Mega samples per second
# 780 micro seconds to decode 1000 samples

num_samples = 1000
period = 100  # Period of the sine wave
x = np.arange(num_samples)  # Sample indices
sine_wave = np.sin(2 * np.pi * x / period)  # Sine wave
# Scale to np.int16 range (-32768 to 32767)
mono_data = (sine_wave * 32767).astype(np.int16)

# Plot data
if VERBOSE: 
    plt.ion()  # Enable interactive mode
    plt.figure(figsize=(10, 5))
    plt.plot(x, mono_data, label="Mono Data", color="blue")
    plt.title("Mono Sine Wave")
    plt.xlabel("Sample Index")
    plt.ylabel("Amplitude")
    plt.grid()
    plt.legend()
    plt.tight_layout()
    plt.show(block=True)

codec = ADPCMCodec(channels=1, sample_width=16)
encoded_data = codec.encode(mono_data)
tic = time.perf_counter()
for i in range(100):
    encoded_data = codec.encode(mono_data)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"ADPCM mono encode: {len(mono_data)/time_elapsed/1024/1024} Mega samples/sec")

#print(f"Encoded (ADPCM): {encoded_data}")
decoded_data = codec.decode(encoded_data)
tic = time.perf_counter()
for i in range(100):
    decoded_data = codec.decode(encoded_data)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"ADPCM mono decode: {len(decoded_data)/time_elapsed/1024/1024} Mega samples/sec")
print(f"Compression ratio ADPCM mono: {len(encoded_data)/len(mono_data)*100} [%]")
difference = (mono_data-decoded_data)
# difference_int = np.round(difference).astype(int)
# print(f"Decoded: {difference_int}")

# Create the figure and primary axis
fig, ax1 = plt.subplots(1, 1, figsize=(10, 5))
# Plot on the left y-axis
ax1.plot(x, mono_data, 'b-', label="Sine Wave")  # Blue line for y1
ax1.set_xlabel("X-Axis")
ax1.set_ylabel("Sine Wave", color="b")
ax1.tick_params(axis='y', colors="b")

# Create the secondary axis (right y-axis)
ax2 = ax1.twinx()  # Shares the same x-axis
ax2.plot(x, difference, 'r-', label="Difference")  # Red line for y2
ax2.set_ylabel("Difference", color="r")
ax2.tick_params(axis='y', colors="r")

# Optional: Add legends
ax1.legend(loc="upper left")
ax2.legend(loc="upper right")

# Display the plot
plt.title("Mono ADPCM")
plt.grid()
plt.tight_layout()
plt.show(block=True)

# Stereo [PASSED]
# 1250 micro seconds to encode 2000 samples 1.6 Mega samples per second
# 1150 micro seconds to decode 2000 samples 1.7 Mega samples per second

num_samples = 1000
period = 100  # Period of the sine wave
x = np.arange(num_samples)  # Sample indices
left_sine_wave = np.sin(2 * np.pi * x / period)  # Sine wave
right_sine_wave = np.sin(2 * np.pi * x / period + np.pi/4)  # Sine wave
# Scale to np.int16 range (-32768 to 32767)
left_channel = (left_sine_wave * 32767).astype(np.int16)
right_channel = (right_sine_wave * 32767).astype(np.int16)
stereo_data = np.empty((num_samples * 2,), dtype=np.int16)
stereo_data[0::2] = left_channel  # Left channel samples
stereo_data[1::2] = right_channel  # Right channel samples

# Plot data
if VERBOSE: 
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10))
    ax1.plot(x, stereo_data[0::2], label="Left Channel", color="blue")
    ax1.set_title("Stereo Sine Wave")
    ax1.set_xlabel("Sample Index")
    ax1.set_ylabel("Amplitude")
    ax1.grid()
    ax1.legend()
    ax2.plot(x, stereo_data[1::2], label="Right Channel", color="blue")
    ax2.set_title("Stereo Sine Wave")
    ax2.set_xlabel("Sample Index")
    ax2.set_ylabel("Amplitude")
    ax2.grid()
    ax2.legend()
    plt.tight_layout()
    plt.show(block=True)

#print(f"Original: {stereo_data}")
codec = ADPCMCodec(channels=2, sample_width=16)
encoded_data = codec.encode(stereo_data)
tic = time.perf_counter()
for i in range(100):
    encoded_data = codec.encode(stereo_data)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"ADPCM stereo encode: {len(stereo_data)/time_elapsed/1024/1024} Mega samples/sec")

#print(f"Encoded (ADPCM): {encoded_data}")
decoded_data = codec.decode(encoded_data)
tic = time.perf_counter()
for i in range(100):
    decoded_data = codec.decode(encoded_data)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"ADPCM stereo decode: {len(decoded_data)/time_elapsed/1024/1024} Mega samples/sec")
print(f"ADPCM stereo ratio: {len(encoded_data)/len(decoded_data)*100} %")
#  difference = ((stereo_data-decoded_data)/stereo_data*100)
difference = ((stereo_data-decoded_data))
#print(f"Decoded: {difference_int}")

# Create the figure and primary axis
fig, (ax1, ax3) = plt.subplots(2, 1, figsize=(10, 10))
# Plot on the left y-axis
ax1.plot(x, stereo_data[0::2], 'b-', label="Left Channel")  # Blue line for y1
ax1.plot(x, decoded_data[0::2], 'k-', label="Left Channel ADPCM")  # Blue line for y1
ax1.set_xlabel("X-Axis")
ax1.set_ylabel("Sine Wave", color="b")
ax1.tick_params(axis='y', colors="b")

# Create the secondary axis (right y-axis)
ax2 = ax1.twinx()  # Shares the same x-axis
ax2.plot(x, difference[0::2], 'r-', label="Difference")  # Red line for y2
ax2.set_ylabel("Difference", color="r")
ax2.tick_params(axis='y', colors="r")

# Optional: Add legends
ax1.legend(loc="upper left")
ax2.legend(loc="upper right")

ax3.plot(x, stereo_data[1::2], 'b-', label="Right Channel")  # Blue line for y1
ax3.plot(x, decoded_data[1::2], 'k-', label="Right Channel ADPCM")  # Blue line for y1
ax3.set_xlabel("X-Axis")
ax3.set_ylabel("Sine Wave", color="b")
ax3.tick_params(axis='y', colors="b")

# Create the secondary axis (right y-axis)
ax4 = ax3.twinx()  # Shares the same x-axis
ax4.plot(x, difference[1::2], 'r-', label="Difference")  # Red line for y2
ax4.set_ylabel("Difference", color="r")
ax4.tick_params(axis='y', colors="r")

# Optional: Add legends
ax3.legend(loc="upper left")
ax4.legend(loc="upper right")

# Display the plot
plt.title("Stereo ADPCM")
plt.grid()
plt.tight_layout()
plt.show(block=True)

# Arduino line processor [PASSED]
# Header 150 microsceonds
# No Header 160 milliseconds

processor = ArduinoTextStreamProcessor(eol=b'\n', encoding='utf-8')
data = b'Voltage: 12, 11.8, 11.6\nCurrent: 1.2, 1.3, 1.4\n'
if VERBOSE: print(f"Original: {data}")
results = processor.process(data, use_labels = True)
if VERBOSE: 
    for result in results:
        print(result)

data = b'Voltage: 12 11.8 11.6\nCurrent: 1.2 1.3 1.4\n'
if VERBOSE: print(f"Original: {data}")
results = processor.process(data, use_labels = True)
tic = time.perf_counter()
for i in range(100):
    results = processor.process(data, use_labels = True)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"Arduino Header decode: {len(data)/time_elapsed/1024/1024} Mega bytes per seconds")
if VERBOSE: 
    for result in results:
        print(result)

processor = ArduinoTextStreamProcessor(eol=b'\n', encoding='utf-8')
data = b'12, 11.8, 11.6\n1.2, 1.3, 1.4\n'
if VERBOSE:  print(f"Original: {data}")
results = processor.process(data, use_labels = False)
if VERBOSE: 
    for result in results:
        print(result)

data = b'12 11.8 11.6\n1.2 1.3 1.4\n'
if VERBOSE: print(f"Original: {data}")
results = processor.process(data, use_labels = False)
tic = time.perf_counter()
for i in range(100):
    results = processor.process(data, use_labels = False)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"Arduino no header decoder: {len(data)/time_elapsed/1024/1024} Mega bytes per seconds")
if VERBOSE: 
    for result in results:
        print(result)

# Binary stream processor 

# Straight 50 microseconds  1k text 20Mbytes/sec
# Zlib 285 microseconds  1k text 3.5Mbytes/sec
# Tamp 390 microseconds 1k text 2.5Mbytes/sec

# [PASSED]

processor = BinaryStreamProcessor()
data = struct.pack('B', processor.BYTE_ID) + os.urandom(1024)
np_data = np.frombuffer(data, dtype=np.uint8)
if VERBOSE:  print(f"Original: {np_data}")
encoded_packet = cobs.encode(data) + processor.EOP
# print(f"Encoded (cobs): {encoded_packet}")
results = processor.process(encoded_packet)
tic = time.perf_counter()
for i in range(100):
    results = processor.process(encoded_packet)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"Binary Stream: {len(data)/time_elapsed/1024/1024} Mega samples/sec")
if VERBOSE: 
    for result in results:
        print(result["data"])

# Binary stream processor with compression

# [PASSED]

data = struct.pack('B', processor.CHAR_ID) + text.encode('utf-8')
data_packet = cobs.encode(data) + processor.EOP
compressed_data_packet = zlib.compress(data_packet)
packet = struct.pack('B', processor.ZLIB_ID) + compressed_data_packet 
encoded_packet = cobs.encode(packet) + processor.EOP
results = processor.process(encoded_packet)
tic = time.perf_counter()
for i in range(100):
    results = processor.process(encoded_packet)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"Binary Processor decode ZLIB compressed text: {len(text)/time_elapsed/1024/1024} Mega bytes/sec")
if VERBOSE: 
    for result in results:
        print(result["data"])

# [PASSED]

data = struct.pack('B', processor.CHAR_ID) + text.encode('utf-8')
data_packet = cobs.encode(data) + processor.EOP
compressed_data_packet = tamp.compress(data_packet)
packet = struct.pack('B', processor.TAMP_ID) + compressed_data_packet 
encoded_packet = cobs.encode(packet) + processor.EOP
results = processor.process(encoded_packet)
tic = time.perf_counter()
for i in range(100):
    results = processor.process(encoded_packet)
toc = time.perf_counter()
time_elapsed = (toc - tic)/100
print(f"Binary Processor decode TAMP compressed text: {len(text)/time_elapsed/1024/1024} Mega bytes/sec")
if VERBOSE: 
    for result in results:
        print(result["data"])





############################################################################################
# Codec, Compressor and Serial Stream Processor Helper
############################################################################################
#
# - GeneralCodec: 
#       Encodes and decodes data to a limited set of alternatives: 0..BASE-1. 
#       No encoding is 0..255. BASE 10 is 0..9. BASE 2 is 0..1.
# - PrintableCodec: 
#       Encodes binary data to printable ASCII characters.
# - Compressor: 
#       Compresses and decompresses data using 
#           rle: Run-Length Encoding, 
#           zlib, 
#           tamp.
# - ADPCMCodec: 
#       Encodes and decodes audio data using 
#           raw on mono stereo int8 or int16 data
#           ADPCM on mono or stereo int8 or int16 data.
#          (can handle about 1-2 M samples/sec on Ryzen 7 laptop)
# - StreamProcessors: 
#       Binary Stream: 
#           Processes a stream of data packets separated by a packet separator.
#           Packets are encoded using COBS (Consistent Overhead Byte Stuffing) encoding, 
#             essentially removing b\\x00 bytes from the data and using it as end of packet marker
#           The first byte of each packet determines the data type, followed by the data.
#           (can handle about 20-30 MBytes/sec without compression and 2-4 MBytes/sec with compression on Ryzen 7 laptop)
#       Arduino Text Stream Processor:
#           Processes text data in a format similar to the Arduino Serial Plotter.
#           (can handle about 5-10k short lines/sec on Ryzen 7 laptop)
#
# Dependencies:
# 
# COBS: https://pypi.org/project/cobs/ 
#       uses C accelerated code
#       matching arduino library provided
#
# ZLIB  https://docs.python.org/3/library/zlib.html
#       regular part of python installation
#       arduino library not yet tested: https://github.com/bitbank2/zlib_turbo 
#
# TAMP  https://github.com/BrianPugh/tamp
#       uses C accelerated code
#       arduino library not yet made
#
# RLE   https://en.wikipedia.org/wiki/Run-length_encoding
#       custom Numba accelerated code
#       arduino library not yet made, need for image transmission
# 
# ADPCM https://en.wikipedia.org/wiki/Adaptive_differential_pulse-code_modulation
#       custom Numba accelerated code
#       matching arduino library provided
#
# SCIPY https://docs.scipy.org/doc/scipy/reference/fft.html
#       used for discrete cosine transformation for image compression/decompression
#       uses RLE compression
#       arduino library not yet made, needed for image transmission
#
# Notes:
#
# It is assumed that number of bytes used to represent the numeric data types is as following:
#
#  boolean                          1
#  byte                             1
#  character                        1
#  int8                             1: -128..127
#  short integer, int16             2
#  unsigned short integer, uint16   2
#  integer, int32                   4
#  unsigned integer uint32          4
#  long integer int64               8
#  unsigned long integer            8
#  float                            4
#  double                           8
#
# Nordic UART Service has typical 185 MTU and therefore it has a 182 bytes payload
# Max MTU for BLE is 247 and therefore a 244 bytes payload
# If packet size is larger, they need to be assembled from multiple payloads
#
# ------------------------------------------------
#
# Fall 2024: created
#
# This code is maintained by Urs Utzinger
############################################################################################

import math
import struct
import logging                       # logger
import time                          # time for timestamp
import re                            # regular expressions
from typing import List, Dict, Tuple # type hints
from scipy.fft import idct           # image decompression
from scipy.fft import dct            # image compression
import numpy as np                   # NumPy for numerical computing
from numba import njit, jit          # Numba for JIT compilation
from  cobs import cobs               # serial data encoding (byte stuffing)
import zlib                          # Standard Python zlib library
import tamp                          # tamp compression library

####################################################################################
# Universal Helper
####################################################################################

def to_numpy_array(data):
    """
    Safely convert various data types (bytes, list of int, NumPy array) to a NumPy uint8 array.
    """
    if isinstance(data, np.ndarray):
        if data.dtype != np.uint8:
            # Convert to uint8 if needed
            return data.astype(np.uint8)
        return data
    elif isinstance(data, bytes):
        return np.frombuffer(data, dtype=np.uint8)
    else:
        # Assume data is iterable of integers
        return np.array(data, dtype=np.uint8)

def to_bytes(data):
    """
    Safely convert data to bytes. 
    """
    if isinstance(data, bytes):
        return data
    elif isinstance(data, np.ndarray):
        return data.tobytes()
    else:
        # Assume data is an iterable of integers
        return bytes(data)

####################################################################################
# General BASE Codec
####################################################################################

class GeneralCodec:
    """
    General codec for base encoding and decoding data:
    A byte is split into two parts: 

    0...BASE-1 | BASE..255

    The lower part are acceptable numbers and the upper range will not be present in 
    the encoded data.

    For a 10 based encoding this represents the numbers 0..9 while 10..255 are not present.

    Output is padded to the maximum number of digits needed for the given byte length.
    E.g. For data represented with 4 bytes we need at least 5 bytes to encode them.
    """

    def __init__(self, base: int = 240):
        if not (1 < base < 256):
            raise ValueError("Base must be between 2 and 255 inclusive.")
        self.BASE = base
        # Pre-populate the cache for common lengths
        self._max_digits_cache = {}
        for length in [1, 2, 4, 8, 16]:
            self.compute_digits(length)

    def compute_digits(self, length: int) -> int:
        """
        Compute the maximum number of base digits required for a given byte length.
        """
        if length in self._max_digits_cache:
            return self._max_digits_cache[length]

        max_val = (1 << (8 * length)) - 1
        max_digits = 1 if max_val == 0 else math.ceil(math.log(max_val + 1, self.BASE))
        self._max_digits_cache[length] = max_digits
        return max_digits

    def encode(self, data: bytes, length: int) -> bytearray:
        """
        Encode the given data into base-BASE representation.
        """
        if len(data) == 0:
            return bytearray()

        return self._encode(data, base=self.BASE, max_digits=self.compute_digits(length))
    
    def decode(self, data, length: int):
        """
        Decode the given base-BASE data back into binary form.
        """
        if len(data) == 0:
            return bytearray()

        return self._decode(data, base=self.BASE, out_byte_length=length)

    @staticmethod
    def _encode(data: bytes, base: int, max_digits: int) -> bytearray:

        value = int.from_bytes(data, 'big', signed=False)

        encoded_digits = bytearray(max_digits)
        idx = max_digits - 1
        while value > 0 and idx >= 0:
            value, remainder = divmod(value, base)
            encoded_digits[idx] = remainder
            idx -= 1

        return encoded_digits

    @staticmethod
    def _decode(encoded: bytes, base: int, out_byte_length: int) -> bytearray:
        value = 0
        for b in encoded:
            if b >= base:
                raise ValueError("Invalid digit in base data.")
            value = value * base + b

        return value.to_bytes(out_byte_length, byteorder='big')

    # @staticmethod
    # @njit
    # def _encode_numba(data: np.ndarray, base: int, max_digits: int) -> np.ndarray:
    #     """
    #     Base encoding using Numba with fixed-width integers.
        
    #     Args:
    #         data (np.ndarray): Input data as a NumPy array of dtype uint8.
    #         base (int): The base for encoding.
    #         max_digits (int): Maximum number of digits per chunk in the encoded output.
        
    #     Returns:
    #         np.ndarray: Encoded data as a NumPy array of dtype uint8.
    #     """
    #     # Output array (maximum possible size: 2 * max_digits * len(data))
    #     encoded = np.zeros(max_digits * data.size, dtype=np.uint8)
    #     write_index = 0

    #     # Process each byte or small chunk
    #     for byte in data:
    #         chunk_value = np.uint64(byte)
    #         chunk_digits = np.zeros(max_digits, dtype=np.uint8)
    #         idx = max_digits - 1

    #         # Encode the chunk into base digits
    #         while chunk_value > 0 and idx >= 0:
    #             chunk_value, remainder = divmod(chunk_value, base)
    #             chunk_digits[idx] = remainder
    #             idx -= 1

    #         # Add the encoded chunk to the output
    #         for i in range(idx + 1, max_digits):
    #             encoded[write_index] = chunk_digits[i]
    #             write_index += 1

    #     # Return only the used portion of the output array
    #     return encoded[:write_index]

    # @staticmethod
    # @njit
    # def _decode_numba(encoded: np.ndarray, base: int, out_length: int) -> np.ndarray:
    #     """
    #     Base decoding using Numba with fixed-width integers.
        
    #     Args:
    #         encoded (np.ndarray): Encoded data as a NumPy array of dtype uint8.
    #         base (int): The base used for encoding.
    #         out_length (int): Length of the original data to decode.
        
    #     Returns:
    #         np.ndarray: Decoded binary data as a NumPy array of dtype uint8.
    #     """
    #     decoded = np.zeros(out_length, dtype=np.uint8)
    #     read_index = 0

    #     for i in range(out_length):
    #         value = np.uint64(0)

    #         # Decode each byte in reverse base encoding
    #         for _ in range(2):  # Assuming 2 base digits represent 1 byte
    #             if read_index >= encoded.size:
    #                 break
    #             value = value * base + encoded[read_index]
    #             read_index += 1

    #         decoded[i] = value

    #     return decoded

####################################################################################
# Convert to printable ASCII characters
####################################################################################

class PrintableCodec:
    """
    This codec provides encoding of binary data to printable ASCII characters.
    After encoding, data can be printed in a terminal or shell.
    Although text is not related to human readable numbers this might be useful when
    visualizing data or transmitting data on a terminal.

    Acceptable characters are: 32..126 (printable ASCII characters) and 161..255 (extended ASCII characters)
    Backspace, Delete, Escape, Nul, Horizontal Tab, Vertical Tab, Line Feed, Form Feed, Carriage Return 
    are control characters and not part of printable characters.
    """

    def __init__(self):
        ascii_chars = [chr(i) for i in range(32, 127)]
        extended_ascii_chars = [chr(i) for i in range(161, 256)]
        self.table = ''.join(ascii_chars + extended_ascii_chars)
        self.base = len(self.table)
        
        # Reverse map from char -> digit
        self.char_to_val = {c: i for i, c in enumerate(self.table)}

        # Pre-populate the cache for common lengths
        self._max_digits_cache = {}
        for length in [1, 2, 4, 8, 16]:
            self.compute_digits(length)

    def compute_digits(self, byte_length: int) -> int:
        """
        Compute how many base-N digits are needed to represent up to 'byte_length' bytes.
        """
        if byte_length in self._max_digits_cache:
            return self._max_digits_cache[byte_length]

        if byte_length <= 0:
            max_digits = 0
        else:
            # Maximum integer that fits in 'byte_length' bytes is (1 << (8*byte_length)) - 1
            max_val = (1 << (8 * byte_length)) - 1
            # Number of base-N digits needed to represent [0..max_val]
            max_digits = 1 if max_val == 0 else math.ceil(math.log(max_val + 1, self.base))

        self._max_digits_cache[byte_length] = max_digits
        return max_digits

    def encode(self, data: bytes, length:int) -> str:
        """
        Encode binary data into printable ASCII characters.
        """
        if len(data) == 0:
            return ''
        
        return self._encode(data, base=self.base, table=self.table, max_digits=self.compute_digits(length))

    def decode(self, encoded: str, length:int) -> bytearray:
        """
        Decode ASCII-encoded string back into binary data.
        """
        if len(encoded) == 0:
            return b""
        
        return self._decode(encoded, base=self.base, c2v=self.char_to_val, out_byte_length=length)

    def _encode(self, data: bytes, base: int, table:str, max_digits: int) -> str:
        """
        Encode binary data into printable ASCII characters.
        """
        value = int.from_bytes(data, 'big', signed=False)

        # Build a list of exactly 'max_digits' characters, from right to left
        encoded_chars = [table[0]] * max_digits   # pre-fill with the '0' digit (leading zero char)
        idx = max_digits - 1

        while value > 0 and idx >= 0:
            value, remainder = divmod(value, base)
            encoded_chars[idx] = table[remainder]
            idx -= 1

        return "".join(encoded_chars)

    def _decode(self, encoded: str, base: int, c2v: dict, out_byte_length: int) -> bytearray:
        """
        Decode ASCII-encoded string back into binary data.
        """
        value = 0
        for c in encoded:
            value = value * base + c2v[c]

        # Convert that integer to 'out_byte_length' bytes, big-endian
        return value.to_bytes(out_byte_length, byteorder='big', signed=False)
    
####################################################################################
# Compressor
####################################################################################

class Compressor:
    def __init__(self, compressor="rle"):
        """
        Initialize the Compressor.
        :param compressor: 
            "rle"  : Run-Length Encoding : Custom Implementation
            "zlib" : Standard Python zlib library and https://github.com/pfalcon/uzlib
            "tamp" : https://github.com/BrianPugh/tamp
        """
        self.compressor_format = compressor

        # Assign the appropriate compression and decompression functions
        if compressor == "rle":
            self.compress_func = self.rle_compress
            self.decompress_func = self.rle_decompress
        elif compressor == "zlib":
            self.compress_func = zlib.compress
            self.decompress_func = zlib.decompress
        elif compressor == "tamp":
            self.compress_func = tamp.compress
            self.decompress_func = tamp.decompress
        else:
            raise ValueError("Invalid compressor format. Must be 'rle', 'zlib', or 'tamp'.")

    def compress(self, data):
        """
        Compress data using the selected algorithm.
        :param data: Data to compress (bytearray or NumPy array)
        :return: Compressed data (bytearray or NumPy array)
        """
        return self.compress_func(data)

    def decompress(self, compressed_data):
        """
        Decompress data using the selected algorithm.
        :param compressed_data: Compressed data (bytearray or NumPy array)
        :return: Decompressed data (bytearray or NumPy array)
        """
        return self.decompress_func(compressed_data)
        
    def rle_compress(self, data):
        """
        Compress data using Run-Length Encoding.
        """
        encoded_data_np = self.rle_encode_numba(self.to_numpy_array(data))
        if isinstance(data, np.ndarray):
            return encoded_data_np
        else:
            return self.to_bytes(encoded_data_np)

    def rle_decompress(self, compressed_data):
        """
        Decompress data using Run-Length Encoding.
        """
        decoded_np = self.rle_decode_numba(self.to_numpy_array(compressed_data))
        if isinstance(compressed_data, np.ndarray):
            return decoded_np
        else:
            return self.to_bytes(decoded_np)

    @staticmethod
    def to_numpy_array(data):
        return np.frombuffer(data, dtype=np.uint8)

    @staticmethod
    def to_bytes(data):
        return data.tobytes()

    # - Compressor functions
    # ----------------------

    @staticmethod
    @njit
    def rle_encode_numba(data: np.ndarray) -> np.ndarray:
        """
        Numba-accelerated RLE encoding function.
        data: NumPy array of uint8.
        Returns: NumPy array of RLE-encoded data, where pairs of (value, count) are stored.
        """
        if data.size == 0:
            return np.empty(0, dtype=np.uint8)

        # Maximum possible encoded size is 2 * data.size (worst case: no runs)
        max_encoded_size = 2 * data.size
        encoded_array = np.empty(max_encoded_size, dtype=np.uint8)
        
        current_value = data[0]
        current_count = 1
        write_index = 0

        for i in range(1, data.size):
            if data[i] == current_value and current_count < 255:
                current_count += 1
            else:
                # Store the pair (value, count)
                encoded_array[write_index] = current_value
                encoded_array[write_index + 1] = current_count
                write_index += 2
                current_value = data[i]
                current_count = 1

        # Append the last pair
        encoded_array[write_index] = current_value
        encoded_array[write_index + 1] = current_count
        write_index += 2

        # Return only the used portion of the array
        return encoded_array[:write_index]


    @staticmethod
    @njit
    def rle_decode_numba(encoded_data: np.ndarray) -> np.ndarray:
        """
        Numba-accelerated RLE decoding function.
        encoded_data: NumPy array of (value, count) pairs in uint8.
        Returns: A NumPy array of the decoded sequence.
        """
        if encoded_data.size == 0 or (encoded_data.size % 2) != 0:
            return np.empty(0, dtype=np.uint8)
        
        # First pass: calculate the total length of the decoded array
        decoded_length = np.sum(encoded_data[1::2])

        # Preallocate the result array
        decoded_array = np.empty(decoded_length, dtype=np.uint8)

        write_index = 0
        for i in range(0, encoded_data.size, 2):
            value = encoded_data[i]
            count = encoded_data[i + 1]
            decoded_array[write_index:write_index + count] = value  # Slice assignment
            write_index += count

        return decoded_array
    
####################################################################################
# ADPCM Audio Codec
####################################################################################

class ADPCMCodec:
    """
    An IMA ADPCM encoder/decoder class supporting:
      - Mono (1 ch) or Stereo (2 ch)
      - 8-bit or 16-bit signed integer samples
      - 1D array input (stereo data interleaved: [L, R, L, R, ...])

    ADPCM encoding is a form of differential pulse-code modulation.
    It effectively compresses audio data to 1 Nibble (4 bits) for each sample. 
    """

    def __init__(self, channels=1, sample_width=16):
        """
        Args:
            channels     (int): number of channels, 1 for mono or 2 for stereo
            sample_width (int): 8 int8 samples, 16 for int16 samples
        """

        if channels not in (1, 2):
            raise ValueError("channels must be 1 or 2 (mono/stereo).")
        if sample_width not in (8, 16):
            raise ValueError("sample_width must be 8 (int8) or 16 (int16).")

        self.channels     = channels
        self.sample_width = sample_width

    def encode(self, data):
        """
        Encode raw PCM data to ADPCM (IMA).
        
        Args:
            data: 1D array-like of shape (N*channels,), containing int8 or int16 samples.
                  Acceptable inputs:
                    - NumPy array of dtype int8 or int16
                    - bytearray of length N*sample_width/8
        """

        # Convert to a NumPy array if needed
        if isinstance(data, bytearray):
            # interpret as int8 or int16
            dt = np.int8 if self.sample_width == 8 else np.int16
            data = np.frombuffer(data, dtype=dt)
            out_is_bytarray = True
        else:
            data = np.array(data, copy=False)
            out_is_bytarray = False

        if data.dtype not in (np.int8, np.int16):
            raise ValueError("Data must be int8 or int16.")

        # Ensure length is multiple of channels
        if data.shape[0] % self.channels != 0:
            raise ValueError("Input length must be multiple of channels.")

        encoded_data_np = self._encode_numba(data, self.channels)
        if out_is_bytarray:
            return encoded_data_np.tobytes()
        else: 
            return encoded_data_np

    def decode(self, adpcm_data):
        """
        Decode ADPCM (IMA) data back to raw PCM samples (int16).
        
        Args:
            adpcm_data (1D np.ndarray or bytearray): ADPCM data 
                stored as 4-bit nibbles packed in uint8.

        Returns:
            np.ndarray of shape (N,), dtype=int16 or bytearray
        """
        # Convert to a NumPy array if needed
        if isinstance(adpcm_data, bytearray):
            adpcm_data_np = np.frombuffer(adpcm_data, dtype=np.uint8)
            out_is_bytearray = True
        else:
            adpcm_data_np = np.array(adpcm_data, dtype=np.uint8, copy=False)
            out_is_bytearray = False

        # We know each byte has 2 samples (nibbles).
        # Let total_nibbles = adpcm_data.size * 2
        # number of samples = total_nibbles
        total_nibbles = adpcm_data.size * 2
        # But each channel uses its own nibble, so total samples in the array = total_nibbles.
        # We'll decode all nibbles in sequence. The number of 16-bit samples = total_nibbles.
        # (But keep in mind in stereo, half of them go to left, half to right, interleaved.)
        
        # We do need the final sample count, which should be total_nibbles.
        num_samples = total_nibbles
        decoded_data_np = self._decode_numba(adpcm_data_np, num_samples, self.channels)
        if out_is_bytearray:
            return decoded_data_np.tobytes()
        else:
            return decoded_data_np


    # IMA ADPCM step size table (length = 89)
    STEP_SIZE_TABLE = np.array([
           7,     8,     9,    10,    11,    12,    13,    14, 
          16,    17,    19,    21,    23,    25,    28,    31,
          34,    37,    41,    45,    50,    55,    60,    66,
          73,    80,    88,    97,   107,   118,   130,   143,
         157,   173,   190,   209,   230,   253,   279,   307,
         337,   371,   408,   449,   494,   544,   598,   658,
         724,   796,   876,   963,  1060,  1166,  1282,  1411,
        1552,  1707,  1878,  2066,  2272,  2499,  2749,  3024,
        3327,  3660,  4026,  4428,  4871,  5358,  5894,  6484,
        7132,  7845,  8630,  9493, 10442, 11487, 12635, 13899,
       15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794,
       32767,
    ], dtype=np.int32)

    # IMA ADPCM index adjust table for nibble [0..15]
    INDEX_TABLE = np.array([
        -1, -1, -1, -1, 2, 4, 6, 8,
        -1, -1, -1, -1, 2, 4, 6, 8
    ], dtype=np.int32)

    # - Encoder functions
    # -------------------

    @staticmethod
    @njit
    def _encode_numba(input_samples, channels, INDEX_TABLE: np.ndarray = INDEX_TABLE, STEP_SIZE_TABLE: np.ndarray = STEP_SIZE_TABLE):
        """
        Encode int8 or int16 samples (mono or stereo) to 4-bit IMA ADPCM nibble stream.
        
        Args:
            input_samples (np.ndarray): 1D NumPy array of shape (N * channels,).
                                        Must be int8 or int16.
            channels (int): 1 for mono, 2 for stereo
            sample_width (int): 1 if int8, 2 if int16

        Returns:
            np.ndarray of dtype=np.uint8 containing the ADPCM nibbles packed two-per-byte.
        """

        num_samples = input_samples.shape[0]  # total samples (including both channels if stereo)
        # We will produce 1 nibble per input sample.
        # Two nibbles get packed into one output byte.
        # Hence output size in bytes = (num_samples + 1) // 2
        out_size = (num_samples + 1) // 2
        adpcm_data = np.zeros(out_size, dtype=np.uint8)

        # State for each channel: predictor, index
        # For stereo, channel 0 = left, channel 1 = right
        preds   = np.zeros(channels, dtype=np.int32)
        indexes = np.zeros(channels, dtype=np.int32)

        # If the input is int8, upcast to int16 for easier math
        #  (We won't actually change the stored data type in memory, 
        #   but we'll interpret it as int16 in calculations.)
        # If sample_width=8, each sample fits in [-128..127]
        # If sample_width=16, each sample fits in [-32768..32767]
        # For simplicity, just treat all intermediate math as int32 in Numba.

        # We will loop over input_samples, compute nibbles, and pack them into adpcm_data.
        nibble_index = 0  # which nibble within the adpcm_data we are generating
        for i in range(num_samples):
            # Determine which channel we are in (for stereo)
            ch = i % channels

            # Current sample as int32
            sample_val = input_samples[i].item()

            # Get current step
            step = STEP_SIZE_TABLE[indexes[ch]]

            # Compute delta
            diff = sample_val - preds[ch]
            # Sign bit
            adpcm_nibble = 0
            if diff < 0:
                adpcm_nibble = 8
                diff = -diff

            # Quantize the difference
            mask = step >> 3  # step / 8
            if diff >= step:
                adpcm_nibble |= 4
                diff -= step
            step_part = step >> 1
            if diff >= step_part:
                adpcm_nibble |= 2
                diff -= step_part
            step_part >>= 1
            if diff >= step_part:
                adpcm_nibble |= 1
                diff -= step_part

            # Update predictor
            #   compute partial_diff from the nibble
            diffq = (step >> 3)
            if (adpcm_nibble & 4) != 0: diffq += step
            if (adpcm_nibble & 2) != 0: diffq += (step >> 1)
            if (adpcm_nibble & 1) != 0: diffq += (step >> 2)
            if (adpcm_nibble & 8) != 0: preds[ch] -= diffq
            else:                       preds[ch] += diffq

            # Clamp predictor
            if   preds[ch] >  32767: preds[ch] =  32767
            elif preds[ch] < -32768: preds[ch] = -32768

            # Update step index
            indexes[ch] += INDEX_TABLE[adpcm_nibble & 0x07]
            
            if   indexes[ch] <  0: indexes[ch] = 0
            elif indexes[ch] > 88: indexes[ch] = 88

            # Pack nibble into output
            #   nibble_index // 2 => which byte
            #   nibble_index % 2 == 0 => low nibble, else high nibble
            out_byte_index = nibble_index >> 1
            if (nibble_index & 0x1) == 0:
                # Low nibble
                adpcm_data[out_byte_index] = np.uint8(adpcm_nibble & 0x0F)
            else:
                # High nibble
                adpcm_data[out_byte_index] |= np.uint8((adpcm_nibble & 0x0F) << 4)

            nibble_index += 1

        return adpcm_data


    @staticmethod
    @njit
    def _decode_numba(adpcm_data, num_samples, channels, STEP_SIZE_TABLE: np.ndarray = STEP_SIZE_TABLE, INDEX_TABLE: np.ndarray = INDEX_TABLE):
        """
        Decode 4-bit IMA ADPCM nibble stream back to int16 samples.
        
        Args:
            adpcm_data (np.ndarray): 1D array of uint8 containing packed 4-bit nibbles.
            num_samples (int): total number of samples to decode
            channels (int): 1=mono, 2=stereo

        Returns:
            np.ndarray of shape (num_samples,), dtype=int16
        """
        output_samples = np.zeros(num_samples, dtype=np.int16)

        # State for each channel
        preds = np.zeros(channels, dtype=np.int32)
        indexes = np.zeros(channels, dtype=np.int32)

        nibble_index = 0
        for i in range(num_samples):
            ch = i % channels

            out_byte_index = nibble_index >> 1
            # low nibble or high nibble?
            if (nibble_index & 0x1) == 0:
                adpcm_nibble = adpcm_data[out_byte_index] & 0x0F
            else:
                adpcm_nibble = (adpcm_data[out_byte_index] >> 4) & 0x0F

            nibble_index += 1

            # decode nibble
            step = STEP_SIZE_TABLE[indexes[ch]]

            diffq = (step >> 3)
            if (adpcm_nibble & 4) != 0: diffq += step
            if (adpcm_nibble & 2) != 0: diffq += (step >> 1)
            if (adpcm_nibble & 1) != 0: diffq += (step >> 2)

            if (adpcm_nibble & 8) != 0: preds[ch] -= diffq
            else:                       preds[ch] += diffq

            # clamp
            if preds[ch]   >  32767: preds[ch] = 32767
            elif preds[ch] < -32768: preds[ch] = -32768

            indexes[ch] += INDEX_TABLE[adpcm_nibble & 0x07]
            if   indexes[ch] <  0: indexes[ch] = 0
            elif indexes[ch] > 88: indexes[ch] = 88
            
            output_samples[i] = np.int16(preds[ch])

        return output_samples

##############################################################################
# Stream Handlers:
# - Arduino Text Stream
# - Binary Data Stream
##############################################################################

class ArduinoTextStreamProcessor:
    """
    Encode and Decode data to a format that is similar to what Arduino Serial Plotter understands

    [[label:][{'\s' '\t' ''} value {',' ';' ''}]]
    ----------------------------------------------
    Example with label: V: 12.65 I: 0.25
    Example without label: 12.65, 0.25

    Decoding steps:
    1) Separate groups: "label1: value1 label2: value2" to "label1: value1" and "label2: value2".
    2) For each group separate labels from values: "label1: value1" to ("label1", "value1")
    3) For each set of values : "value1, value2; value3" to ["value1", "value2", "value3"].

    Scalars and vectors are separated by commas or semicolons.
    Vector elements are separated by whitespace.
    """

    def __init__(self, eol=b'\n', encoding='utf-8', logger=None):

        self.eol = eol # end of line
        self.encoding = encoding # text encoding
        self.partial_line = bytearray() # partial packet buffer
        
        # Regular expression pattern to separate data values
        # This precompiles the text parsers
        self.labeled_data_re  = re.compile(r',(?=\s*\w+:)')  # separate labeled data into segments
        self.label_data_re    = re.compile(r'(\w+):\s*(.+)') # separate segments into label and data
        self.vector_scalar_re = re.compile(r'[,]\s*')        # split on commas

        if logger == None:
            self.logger = logging.getLogger(__name__)

    def parse_line(self, line:bytes, labels:bool=True) -> List[Dict]:
        """
        Parses a text line for labels, vectors, scalars, or unlabeled data.

        If `labels` is False, data is not parsed for labels.

        Scalars and vectors are separated by commas or semicolons.
        Vector elements are separated by whitespace.

        Returns a list of dictionaries with parsed data.
        """

        results = []
        scalar_count = 0
        vector_count = 0

        _decoded_line = line.decode(self.encoding)
        decoded_line = _decoded_line.replace(';', ',') # replace semicolons with commas

        # 1) Separate groups: "label1: value1 label2: value2" to "label1: value1" and "label2: value2".
        segments = self.labeled_data_re.split(decoded_line) if labels else [decoded_line]

        for raw_segment in filter(None, segments):

            # remove trailing or preceding commas or spaces
            segment = raw_segment.strip(" ,")

            label = None
            data = segment
            # 2) For each group separate labels from values: "label1: value1" to ("label1", "value1")  
            if labels:
                match = self.label_data_re.match(segment)
                if match:
                    label, data = match.groups()

            # 3) Split data into scalar or vector elements
            data_elements = self.vector_scalar_re.split(data)

            for element in filter(None, data_elements):  # Filter out empty elements
                try:
                    numbers = list(map(float, element.split()))  # Convert to floats
                except ValueError:
                    continue  # Skip invalid entries

                if not numbers:
                    continue  # Skip empty lists

                # Assign a name based on label or generate one
                if label:
                    name = label
                elif len(numbers) == 1:
                    scalar_count += 1
                    name = f"S{scalar_count}"  # Scalar
                else:
                    vector_count += 1
                    name = f"V{vector_count}"  # Vector

                # Add the parsed data to results
                results.append({
                    "datatype": 10,
                    "name": name,
                    "data": numbers,
                    "timestamp": time.time(),  # Add a timestamp
                })

        return results
    
    # Potential alternative implementation for speed improvements
    # It needs some further tweaking until it matches the above implementation.
    #
    # def parse_line(line):
    #     # Step 1: replace all semicolons with commas
    #     line = line.replace(';', ',')
    #     # Step 2: split by space => "V:", "12.65,", "I:", "0.25"
    #     chunks = line.split()
    #
    #     results = []
    #     label = None
    #     for chunk in chunks:
    #         if ':' in chunk:
    #             # This chunk is like "V:" or "I:"
    #             part = chunk.split(':', 1)
    #             label = part[0].strip()
    #             # the chunk might end with a colon only
    #             data_portion = part[1].strip() if len(part) > 1 else ""
    #             if data_portion:
    #                 # parse the data portion for floats
    #                 data_list = data_portion.split(',')
    #                 for d in data_list:
    #                     d = d.strip()
    #                     if d:
    #                         results.append((label, float(d)))
    #         else:
    #             # This chunk might be numeric data, possibly "12.65," or "0.25"
    #             data_list = chunk.split(',')
    #             for d in data_list:
    #                 d = d.strip()
    #                 if d:
    #                     if label is None:
    #                         # no label so far => auto-generate or keep as None
    #                         label = "S"
    #                     results.append((label, float(d)))
    #
    #     return results    

    def process(self, new_data: bytes, labels: bool = True) -> List[Dict]:
        """
        Process new data for lines and parse each line.
        Retains partial lines for future processing.
        """

        if not new_data:
            return []

        # Add new data to the partial line buffer
        self.partial_line.extend(new_data)

        # Split into complete lines and retain the partial line
        lines = self.partial_line.split(self.eol)
        self.partial_line = lines.pop()  # Last element is the partial line

        # Process each complete line
        results = []
        for i, line in enumerate(lines):
            if line.strip():  # Skip empty lines
                self.logger.log(logging.DEBUG, f"Processing line {i}: {line}")
                results.extend(self.parse_line(line, labels=labels))  # Assume parse_line returns a list

        return results


class BinaryStreamProcessor:
    # Create a stream processor that separates data into packets and decodes them into values

    """ 
    ## General
    ==========================================

    | ID | datatype       | bytes | encoding |
    | -- | --------       | ----- |          |
    |  0 | character      | 1
    |  1 | boolean        | 1
    |  2 | byte           | 1
    |  3 | int8           | 1
    |  4 | short integer  | 2
    |  5 | unsigned short | 2
    |  6 | integer        | 4
    |  7 | unsigned int   | 4
    |  8 | long integer   | 8
    |  9 | unsigned long  | 8
    | 10 | float          | 4
    | 11 | double         | 8 
    | 12-15 | reserved for future basic data types | unknwn  

    ## Physics
    ===========================================

    | ID | Abr | measurement        | units       | datatype(s) |
    | -- | --- | -----------        | -----       | ----------- |
    | 16 | l   | Length             | meter       | float       |
    | 17 | m   | Mass               | kg          | float       |
    | 18 | t   | Time               | second      | float       |
    | 19 | I   | Current            | Ampere      | float       |
    | 20 | T   | Temperature        | Kelvin      | float       |
    | 21 | mol | Amount             | mol         | float       |
    | 22 |     | Luminous intensity | candela     | float       |
    | 23 |     | Brightness         | lumens      | float       |
    | -- | --  | Physics derived    | ---         | -----       |
    | 24 |     | Angle              | degrees     | float       |
    | 25 | A   | Area               | m^2         | float       |
    | 26 | V   | Volume             | m^3         | float       |
    | 27 | F   | Force              | Newtons     | float       |
    | 28 | v   | Velocity           | m/s         | float       |
    | 29 | a   | Acceleration       | m/s^2       | float       |
    | 31 | p   | Pressure           | Pascal      | float       |
    | 32 | p   | Pressure           | milliBar    | float       |
    | 33 | E   | Energy             | Joule       | float       |
    | 34 | P   | Power              | Watt        | float       |
    | 35 |     | Charge             | Coulomb     | float       |
    | 36 | V   | Voltage            | Volt        | float       |
    | 37 | R   | Resistance         | Ohm         | float       |
    | 38 | G   | Conductance = 1/R  | Siemens     | float       |
    | 39 | X   | Reactance          |             | float       |
    | 40 | Z   | Impedance = R +jX  |             | float,float |
    | 41 |     | Phase              | degrees     | float       |
    | 42 | L   | Inductance         | Henry       | float       |
    | 43 | C   | Capacitance        | Farad       | float       |
    | 44 |     | Magnetic Field     | Tesla       | float       |
    | 45 | f   | Frequency          | Hertz       | float       |
    | 46 | M   | Molarity           | moles/liter | float     |
    | 47 | eV  | electron Volts     | eV          | float       |
    | 50 |     | Optical Spectrum   | Wavelength, Intensity | float, float |
    | 51 |     | Frequency Spectrum | Frequency, Intensity  | float, float |

    ## Physiology measurements
    =======================

    | ID | Abr | measurement        | units        | datatype(s) |
    | -- | --- | -----------        | -----        | ----------- |
    | -- | --  | Most Common        | ---          | -----       |
    | 61 | T   | Temperature        | milliCelsius | u short   | 0...65.536 C
    | 62 | HR  | Hear Rate          | bpm          | u short    | 0...655.36 bpm
    | 63 | HRv | Heart Rate variability |  ms      | float      | 0...3.4028235E38 ms
    | 64 | RR  | Respiratory rate   | breaths/min  | u short    | 0...655.356 bpm
    | 65 | BP  | Blood Pressure     | mmHg         | u short    | 0...655.36 mmHg
    | 66 | BPsys| Blood Pressure Systolic | mmHg   | u short    | 0...655.36 mmHg
    | 67 | BPdua | Blood Pressure Diastolic | mmHg | u short    | 0...655.36 mmHg
    | 68 | SPO2 | SPO2              | %            | u short    | 0...100.00% 
    | -- | --  | Anthropometric     | ---          | -----      |
    | 70 | --  | Weight             | gr           | u int      | 0...4,294,967.295 gr
    | 71 |     | Height             | cm           | u short    | 0... 
    | 72 |     | Age                | years        | u short    | 0...655.36
    | 73 | BMI | Body Mass Index    | unitless     | u short    | 0...65.536
    | 74 |     | Waist circumference | cm          | u short    | 0...6553.6
    | 75 |     | Hip circumference   | cm          | u short    | 0...6553.6
    | 76 |     | Chest circumference | cm          | u short    | 0...6553.6
    | 77 |     | Thigh circumference | cm          | u short    | 0...6553.6
    | 78 |     | Arm circumference   | cm          | u short    | 0...6553.6
    | 79 |     | Calf circumference  | cm          | u short    | 0...6553.6
    | -- | --  | BioZ                | ---         | -----      |
    | 80 | Z(freq) | Frequency, Impedance |        | float, float, float
    | 81 |     | Fat free mass          | kg       | ushort     | 0...656.36 kg
    | 82 |     | Total body water       | liters   | ushort     | 0...655.36 liters
    | 83 |     | Extracellular water    | liters   | ushort     | 0...655.36 liters
    | 84 |     | Total body potassium   | grams    |
    | 85 |     | Body fat percentage    | %        |
    | 86 |     | Body water percentage  | %        |
    | 87 |     | Muscle mass percentage | %        |
    | -- | --  | Cardiovascular     | ---          | -----       |
    | 90 | ECG | Electro Cardio Gram two lead |  microV |  short |  0...32767 microV
    | 91 | ECG | ECG 12 lead        | microV       | short,..    | 0...32767 microV
    | -- | --  | Neurological       | ---          | -----       |
    | 92 | EEG | encephalogram      | microV       | short       |
    | 93 | EMG | myogram            | microV       | short       |
    | --  | --  | Respiratory       | ---          | -----       |
    | 100 |     | Forced Expiratory Volume in 1 sec
    | 101 |     | Lung Flow in ml/s              short int       2  0...32.767 l/s
    | 102 |     | Lung Volume in ml              unsigned short  2  0...65.536 l
    | --  | --  | Metabolic         | ---       | -----6|
    | 105 |     | Glucose level     | mg/dL
    | 106 |     | Cholesterol level | mg/dL
    | 107 |     | Base Metabolic Rate | kcal/day
    | --  | --  | Muscosceletal     | ---       | -----       |
    | 110 |     | Reaction Time     |
    | 111 |     | Range of Motion   |
    | 112 |     | Grip Strength     |

    ## 12 Lead ECG

    Created from measurements from 9 electrodes plus Right Leg Drive:
    RA, LA, LL, V1, V2, V3, V4, V5, V6, RL Drive

    | Lead	| Derived From	                    | Heart Wall/Region Viewed  |
    | ----- | ----------------------------------| ------------------------- |
    | I	    | LA (+) and RA (-)	                | Lateral | 
    | II	| LL (+) and RA (-)	                | Inferior | 
    | III	| LL (+) and LA (-)	                | Inferior | 
    | aVR	| RA	                            | Right atrium, cavity of the heart | 
    | aVL	| LA	                            | Lateral | 
    | aVF	| LL	                            | Inferior | 
    | V1	| Chest (4th ICS, right)	        | Right ventricle, septum | 
    | V2	| Chest (4th ICS, left)	            | Right ventricle, septum | 
    | V3	| Chest (between V2 and V4)	        | Anterior | 
    | V4	| Chest (5th ICS, midclavicular)	| Anterior | 
    | V5	| Chest (5th ICS, anterior axillary)| Lateral | 
    | V6	| Chest (5th ICS, midaxillary)    	| Lateral | 

    Analog Devices ADAS1000, measured 5 channels, EVAL-ADAS1000SDZ

    ## Motion and Position Sensors
    ===========================
    | ID  | Abr | measurement        | units     | datatype(s) |
    | --  | --- | -----------        | -----     | ----------- |
    | 120 |     | Acceleration 3D    | m/s^2      | float, float, float
    | 121 |     | Velocity 3D        | m/s        | float, float, float
    | 122 |     | Position 3D        | m          | float, float, float
    | 123 |     | Orientation YPR 3D | degrees    | float, float, float 
    | 124 |     | Orientation YPR 3D | centi deg  | short,sort,short | -/+ 180.00
    | 125 |     | Magnetometer 3D    | microTesla | float, float, float
    | 126 |     | Magnetometer 3D    | microTesla | float, float, float
    | 128 |     | Gyration 3D        | deg/sec    | float, float, float
    | 129 |     | Gyration 3D        | deg/sec    | float, float, float
    | 130 |     | Position Long,Lat,Alt | degrees, degrees, meters | float, float, float 
    | 131 |     | Altitude           | m          | float
    | 140 |     | Steps per minute   | 1/min      | short | 0...655.36
    | 141 |     | Steps total        | unitless   | uint

    ## Air Quality and Gas Sensors
    ===========================
    | ID  | Abr  | measurement        | units       | datatype(s) |
    | --  | ---  | -----------        | -----       | ----------- |
    | 150 | PM   | PM1.0, PM2.5, PM10 | micro gr/m^3 | float,float,float
    | 151 | PM1  | particulate matter | micro gr/m^3 | float
    | 152 | PM25 |                    | micro gr/m^3 | float
    | 153 | PM10 |                    | micro gr/m^3 | float
    | 155 | CO2ppm | carbon dioxide   | ppm         | u short
    | 156 | eCO2   |                  | arbitrary   | u short
    | 157 | VOCppb | volatile organic compounds
    | 158 | eVOC   |
    | 159 | NO2ppb | nitrogen dioxide
    | 160 | eNO2
    | 161 | SO2ppb | sulfur dioxide
    | 162 | eSO2
    | 163 | O3ppb  | ozone
    | 164 | eO3
    | 165 | COppm  | carbon monoxide
    | 166 | eCO
    | 167 | H2Sppb | hydrogen sulfide
    | 168 | eH2S
    | 169 | NH3ppb | ammonia
    | 170 | eNH3
    | 171 | H2ppm  | hydrogen
    | 172 | eH2
    | 173 | CH4ppm | methane
    | 174 | eCH4
    | 175 | C2H6ppm | ethane
    | 176 | eC2H6
    | 190 | IAC    | Indoor air quality |

    ## Audio
    ===========================
    Audio is usually bipolar.
    | ID  | Abr | measurement         | units     | datatype(s) |
    | --  | --- | -----------         | -----     | ----------- |
    | 200 |     | Audio Mono 8 bit    | unitless  | byte        |
    | 201 |     | Audio Stereo 8 bit  | unitless  |
    | 202 |     | Audio Mono 16 bit   |           |
    | 203 |     | Audio Stereo 16 bit |           |
    | 204 |     | Audio Mono 4bit ADPCM   (16 to 4 bit) | byte |
    | 205 |     | Audio Stereo 4bit ADPCM (16 to 4 bit) | byte |

    ## Image
    ===========================
    | ID  | Abr | measurement           |                       | datatype(s)     |
    | --  | --- | -----------           | -----                 | -----------     |
    | 220 |     | Image 8 bit grayscale | lines, bytes          | short, bytes... |
    | 221 |     | Image 8 bit color     | lines, palette, bytes | short, 256*rgb [byte,byte,byte], bytes
    | 222 |     | Image 24 bit color    | lines, bytes rgb      | short, [byte,byte,byte]...
    | 223 |     | Image 32 bit color    | lines, bytes rgba     | short, [byte,byte,byte,byte]... 
    | 224 |     | Image 8 bit grayscale RLE DCT | lines, bytes  | RLE compressed DCT converted image data
    | 225 |     | Image 24 bit color RLE DCT | lines, bytes     | RLE compressed DCT converted image data

    ## Do not use
    ===========================
    | ID  | Abr | measurement        | units     | datatype(s) |
    | --  | --- | -----------        | -----     | ----------- |
    | 252 | used to extend this table with zLib compressed data
    | 253 | used to extent this table tamp compressed data
    | 254 | used to extend this table, next byte is the index for the second table
    | 255 | reserved

    """

    def __init__(self, eop=b'\x00', logger = None):

        self.eop = eop                     # End of packet marker, default for COBS
        self.partial_packet = bytearray()  # Partial packet buffer

        # Audio ADPCM codecs
        self.mono_adpcm8    = ADPCMCodec(channels=1, sample_width=8)
        self.mono_adpcm16   = ADPCMCodec(channels=1, sample_width=16)
        self.stereo_adpcm8  = ADPCMCodec(channels=2, sample_width=8)
        self.stereo_adpcm16 = ADPCMCodec(channels=2, sample_width=16)

        self.rle_compressor = Compressor(compressor="rle")
        self.block_size_dct = 8 # DCT image compression block size

        # Map data type codes to handler functions
        # 0..255 with 254 reserved for extension table
        #  - general numeric data types
        #  - physics data types
        #  - physiology data types
        #  - motion data types
        #  - air quality data types
        #  - audio data types
        #  - image data types

        self.handlers = {
            0:  self.handle_char,
            1:  self.handle_bool,
            2:  self.handle_byte,
            3:  self.handle_int8,
            4:  self.handle_short,
            5:  self.handle_ushort,
            6:  self.handle_int,
            7:  self.handle_uint,
            8:  self.handle_long,
            9:  self.handle_ulong,
            10: self.handle_float,
            11: self.handle_double,
            12: self.handle_unknown,
            13: self.handle_unknown,
            14: self.handle_unknown,
            15: self.handle_unknown,
            16: self.handle_length,
            17: self.handle_mass,
            18: self.handle_time,
            19: self.handle_current,
            20: self.handle_temperature,
            21: self.handle_amount,
            22: self.handle_luminous_intensity,
            23: self.handle_brightness,
            24: self.handle_angle,
            25: self.handle_area,
            26: self.handle_volume,
            27: self.handle_force,
            28: self.handle_velocity,
            29: self.handle_acceleration,
            30: self.handle_unknown,
            31: self.handle_pressure_P,
            32: self.handle_pressure_mB,
            33: self.handle_energy,
            34: self.handle_power,
            35: self.handle_charge,
            36: self.handle_voltage,
            37: self.handle_resistance,
            38: self.handle_conductance,
            39: self.handle_reactance,
            40: self.handle_impedance,
            41: self.handle_phase,
            42: self.handle_inductance,
            43: self.handle_capacitance,
            44: self.handle_magnetic_field,
            45: self.handle_frequency,
            46: self.handle_molarity,
            47: self.handle_electron_volts,
            48: self.handle_unknown,
            49: self.handle_unknown,
            50: self.handle_optical_spectrum,
            51: self.handle_frequency_spectrum,
            52: self.handle_unknown,
            53: self.handle_unknown,
            54: self.handle_unknown,
            55: self.handle_unknown,
            56: self.handle_unknown,
            57: self.handle_unknown,
            58: self.handle_unknown,
            59: self.handle_unknown,
            60: self.handle_unknown,
            61: self.handle_Temperature_C,
            62: self.handle_HeartRate,
            63: self.handle_HeartRateVariability,
            64: self.handle_RespiratoryRate,
            65: self.handle_BloodPressure,
            66: self.handle_BloodPressureSystolic,
            67: self.handle_BloodPressureDiastolic,
            68: self.handle_SPO2,
            69: self.handle_unknown,
            70: self.handle_Weight,
            71: self.handle_Height,
            72: self.handle_Age,
            73: self.handle_BMI,
            74: self.handle_WaistCircumference,
            75: self.handle_HipCircumference,
            76: self.handle_ChestCircumference,
            77: self.handle_ThighCircumference,
            78: self.handle_ArmCircumference,
            79: self.handle_CalfCircumference,
            80: self.handle_BIOZ,
            81: self.handle_FatFreeMass,
            82: self.handle_TotalBodyWater,
            83: self.handle_ExtracellularWater,
            84: self.handle_TotalBodyPotassium,
            85: self.handle_BodyFatPercentage,
            86: self.handle_BodyWaterPercentage,
            87: self.handle_MuscleMassPercentage,
            88: self.handle_unknown,
            89: self.handle_unknown,
            90: self.handle_ECG,
            91: self.handle_ECG12,
            92: self.handle_EEG,
            93: self.handle_EMG,
            94: self.handle_unknown,
            95: self.handle_unknown,
            96: self.handle_unknown,
            97: self.handle_unknown,
            98: self.handle_unknown,
            99: self.handle_unknown,
            100: self.handle_ForcedExpiratoryVolume,
            101: self.handle_LungFlow,
            102: self.handle_LungVolume,
            105: self.handle_GlucoseLevel,
            106: self.handle_CholesterolLevel,
            107: self.handle_BaseMetabolicRate,
            108: self.handle_unknown,
            109: self.handle_unknown,
            110: self.handle_ReactionTime,
            111: self.handle_RangeOfMotion,
            112: self.handle_GripStrength,
            113: self.handle_unknown,
            114: self.handle_unknown,
            115: self.handle_unknown,
            116: self.handle_unknown,
            117: self.handle_unknown,
            118: self.handle_unknown,
            119: self.handle_unknown,
            120: self.handle_Acceleration3D,
            121: self.handle_Velocity3D,
            122: self.handle_Position3D,
            123: self.handle_OrientationYPR3D,
            124: self.handle_OrientationYPR3Dcenti,
            125: self.handle_Magnetometer3D,
            126: self.handle_Magnetometer3D,
            127: self.handle_unknown,
            128: self.handle_Gyration3D,
            129: self.handle_Gyration3D,
            130: self.handle_Position,
            131: self.handle_Altitude,
            132: self.handle_unknown,
            133: self.handle_unknown,
            134: self.handle_unknown,
            135: self.handle_unknown,
            136: self.handle_unknown,
            137: self.handle_unknown,
            138: self.handle_unknown,
            139: self.handle_unknown,
            140: self.handle_StepsPerMinute,
            141: self.handle_StepsTotal,
            142: self.handle_unknown,
            143: self.handle_unknown,
            144: self.handle_unknown,
            145: self.handle_unknown,
            146: self.handle_unknown,
            147: self.handle_unknown,
            148: self.handle_unknown,
            149: self.handle_unknown,
            150: self.handle_PM,
            151: self.handle_PM1,
            152: self.handle_PM2_5,
            153: self.handle_PM10,
            154: self.handle_unknown,
            155: self.handle_CO2ppm,
            156: self.handle_eCO2,
            157: self.handle_VOCppb,
            158: self.handle_eVOC,
            159: self.handle_NO2ppb,
            160: self.handle_eNO2,
            161: self.handle_SO2ppb,
            162: self.handle_eSO2,
            163: self.handle_O3ppb,
            164: self.handle_eO3,
            165: self.handle_COppm,
            166: self.handle_eCO,
            167: self.handle_H2Sppb,
            168: self.handle_eH2S,
            169: self.handle_NH3ppb,
            170: self.handle_eNH3,
            171: self.handle_H2ppm,
            172: self.handle_eH2,
            173: self.handle_CH4ppm,
            174: self.handle_eCH4,
            175: self.handle_C2H6ppm,
            176: self.handle_eC2H6,
            177: self.handle_unknown,
            178: self.handle_unknown,
            179: self.handle_unknown,
            180: self.handle_unknown,
            181: self.handle_unknown,
            182: self.handle_unknown,
            183: self.handle_unknown,
            184: self.handle_unknown,
            185: self.handle_unknown,
            186: self.handle_unknown,
            187: self.handle_unknown,
            188: self.handle_unknown,
            189: self.handle_unknown,
            190: self.handle_IAQ,
            191: self.handle_unknown,
            192: self.handle_unknown,
            193: self.handle_unknown,
            194: self.handle_unknown,
            195: self.handle_unknown,
            196: self.handle_unknown,
            197: self.handle_unknown,
            198: self.handle_unknown,
            199: self.handle_unknown,
            200: self.handle_audio_mono8,
            201: self.handle_audio_stereo8,
            202: self.handle_audio_mono16,
            203: self.handle_audio_stereo16,
            204: self.handle_audio_mono8_ADPCM,
            205: self.handle_audio_stereo8_ADPCM,
            206: self.handle_audio_mono16_ADPCM,
            207: self.handle_audio_stereo16_ADPCM,
            208: self.handle_unknown,
            209: self.handle_unknown,
            210: self.handle_unknown,
            211: self.handle_unknown,
            212: self.handle_unknown,
            213: self.handle_unknown,
            214: self.handle_unknown,
            215: self.handle_unknown,
            216: self.handle_unknown,
            217: self.handle_unknown,
            218: self.handle_unknown,
            219: self.handle_unknown,
            220: self.handle_image_gray8,
            221: self.handle_image_color8,
            222: self.handle_image_color24,
            223: self.handle_image_color32,
            224: self.handle_image_gray8_dct,
            225: self.handle_image_color24_dct,
            226: self.handle_unknown,
            227: self.handle_unknown,
            228: self.handle_unknown,
            229: self.handle_unknown,
            230: self.handle_unknown,
            231: self.handle_unknown,
            232: self.handle_unknown,
            233: self.handle_unknown,
            234: self.handle_unknown,
            235: self.handle_unknown,
            236: self.handle_unknown,
            237: self.handle_unknown,
            238: self.handle_unknown,
            239: self.handle_unknown,
            240: self.handle_unknown,
            241: self.handle_unknown,
            242: self.handle_unknown,
            243: self.handle_unknown,
            244: self.handle_unknown,
            245: self.handle_unknown,
            246: self.handle_unknown,
            247: self.handle_unknown,
            248: self.handle_unknown,
            249: self.handle_unknown,
            250: self.handle_unknown, # reserved
            251: self.handle_unknown, # reserved
            252: self.handle_unknown, # reserved for zlib
            253: self.handle_unknown, # reserved for tamp
            254: self.handle_unknown, # reserved for extension
            255: self.handle_unknown, # reserved
        }

        self.name = {
            0:  "char",
            1:  "bool",
            2:  "byte",
            3:  "int8",
            4:  "int16",
            5:  "uint16",
            6:  "int",
            7:  "uint",
            8:  "int64",
            9:  "uint64",
            10: "float",
            11: "double",
            11: "u/k",
            12: "u/k",
            13: "u/k",
            14: "u/k",
            15: "u/k",
            16: "length [m]",
            17: "mass [kg]",
            18: "time [s]",
            19: "current [A]",
            20: "temperature [K]",
            21: "amount [mol]",
            22: "luminous_intensity [cd]",
            23: "brightness [lm]",
            24: "angle [deg]",
            25: "area [m^2]",
            26: "volume [m^3]",
            27: "force [N]",
            28: "velocity [m/s]",
            29: "acceleration [m/s^2]",
            30: "u/k",
            31: "pressure_P [Pa]",
            32: "pressure_mB [mBar]",
            33: "energy [J]",
            34: "power [W]",
            35: "charge [C]",
            36: "voltage [V]",
            37: "resistance [Ohm]",
            38: "conductance [S]",
            39: "reactance [Ohm]",
            40: "impedance [Ohm]",
            41: "phase [deg]",
            42: "inductance [H]",
            43: "capacitance [F]",
            44: "magnetic_field [T]",
            45: "frequency [Hz]",
            46: "molarity [mol/l]",
            47: "electron volts [eV]",
            48: "u/k",
            49: "u/k",
            50: "optical spectrum",
            51: "frequency spectrum",
            52: "u/k",
            53: "u/k",
            54: "u/k",
            55: "u/k",
            56: "u/k",
            57: "u/k",
            58: "u/k",
            59: "u/k",
            60: "u/k",
            61: "Temperature [C]",
            62: "Heart Rate [bpm]",
            63: "Heart Rate Variability [ms]",
            64: "Respiratory Rate [bpm]",
            65: "Blood Pressure [mmHg]",
            66: "Blood Pressure Systolic [mmHg]",
            67: "Blood Pressure Diastolic [mmHg]",
            68: "SPO2 [%]",
            69: "u/k",
            70: "Weight [kg]",
            71: "Height [m]",
            72: "Age [yrs]",
            73: "BMI",
            74: "Waist Circumference [cm]",
            75: "Hip Circumference [cm]",
            76: "Chest Circumference [cm]",
            77: "Thigh Circumference [cm]",
            78: "Arm Circumference [cm]",
            79: "Calf Circumference [cm]",
            80: "BIOZ [Hz, Ohm, Ohm]",
            81: "Fat Free Mass [kg]",
            82: "Total Body Water [l]",
            83: "Extracellular Water [l]",
            84: "Total Body Potassium [gr]",
            85: "Body Fat [%]",
            86: "Body Water [%]",
            87: "Body Muscle [%]",
            88: "u/k",
            89: "u/k",
            90: "ECG [V]",
            91: "ECG 12 Lead [m]",
            92: "EEG [V]",
            93: "EMG [V]",
            94: "u/k",
            95: "u/k",
            96: "u/k",
            97: "u/k",
            98: "u/k",
            99: "u/k",
            100: "Forced Expiratory Volume [l/s]",
            101: "Lung Flow [l/s]",
            102: "Lung Volume [l]",
            105: "Glucose Level [mg/dl]",
            106: "Cholesterol Level [mg/dl]",
            107: "Base Metabolic Rate [kcal/day]",
            108: "u/k",
            109: "u/k",
            110: "Reaction Time [sec]",
            111: "Range of Motion [deg]",
            112: "Grip Strength [kg]",
            113: "u/k",
            114: "u/k",
            115: "u/k",
            116: "u/k",
            117: "u/k",
            118: "u/k",
            119: "u/k",
            120: "Acceleration 3D [m/s^2]",
            121: "Velocity 3D [m/s]",
            122: "Position 3D [m]",
            123: "Orientation YPR 3D [deg]",
            124: "Orientation YPR 3D [deg]",
            125: "Magnetometer 3D [microT]",
            126: "Magnetometer 3D [microT]",
            127: "u/k",
            128: "Gyration 3D [deg/sec]",
            129: "Gyration 3D [deg/sec]",
            130: "Position [deg.deg.m]",
            131: "Altitude [m]",
            132: "u/k",
            133: "u/k",
            134: "u/k",
            135: "u/k",
            136: "u/k",
            137: "u/k",
            138: "u/k",
            139: "u/k",
            140: "Steps [s/min]",
            141: "Steps",
            142: "u/k",
            143: "u/k",
            144: "u/k",
            145: "u/k",
            146: "u/k",
            147: "u/k",
            148: "u/k",
            149: "u/k",
            150: "PM [microgr/m^3]",
            151: "PM 1 [microgr/m^3]",
            152: "PM 2.5 [microgr/m^3]",
            153: "PM 10 [microgr/m^3]",
            154: "u/k",
            155: "CO2 [ppm]",
            156: "eCO2",
            157: "VOC [ppb]",
            158: "eVOC",
            159: "NO2 [ppb]",
            160: "eNO2",
            161: "SO2 [ppb]",
            162: "eSO2",
            163: "O3 [ppb]",
            164: "eO3",
            165: "CO [ppm]",
            166: "eCO",
            167: "H2S [ppb]",
            168: "eH2S",
            169: "NH3 [ppb]",
            170: "eNH3",
            171: "H2 [ppm]",
            172: "eH2",
            173: "CH4 [ppm]",
            174: "eCH4",
            175: "C2H6 [ppm]",
            176: "eC2H6",
            177: "u/k",
            178: "u/k",
            179: "u/k",
            180: "u/k",
            181: "u/k",
            182: "u/k",
            183: "u/k",
            184: "u/k",
            185: "u/k",
            186: "u/k",
            187: "u/k",
            188: "u/k",
            189: "u/k",
            190: "IAQ",
            191: "u/k",
            192: "u/k",
            193: "u/k",
            194: "u/k",
            195: "u/k",
            196: "u/k",
            197: "u/k",
            198: "u/k",
            199: "u/k",
            200: "audio mono 8",
            201: "audio stereo 8",
            202: "audio mono 16",
            203: "audio stereo 16",
            204: "audio mono 8 ADPCM",
            205: "audio stereo 8 ADPCM",
            206: "audio mono 16 ADPCM",
            207: "audio stereo 16 ADPCM",
            208: "u/k",
            209: "u/k",
            210: "u/k",
            211: "u/k",
            212: "u/k",
            213: "u/k",
            214: "u/k",
            215: "u/k",
            216: "u/k",
            217: "u/k",
            218: "u/k",
            219: "u/k",
            220: "image gray 8",
            221: "image color 8",
            222: "image color 24",
            223: "image color 32",
            224: "image gray 8 dct",
            225: "image color 24 dct",
            226: "u/k",
            227: "u/k",
            228: "u/k",
            229: "u/k",
            230: "u/k",
            231: "u/k",
            232: "u/k",
            233: "u/k",
            234: "u/k",
            235: "u/k",
            236: "u/k",
            237: "u/k",
            238: "u/k",
            239: "u/k",
            240: "u/k",
            241: "u/k",
            242: "u/k",
            243: "u/k",
            244: "u/k",
            245: "u/k",
            246: "u/k",
            247: "u/k",
            248: "u/k",
            249: "u/k",
            250: "u/k", # reserved
            251: "u/k", # reserved
            252: "zlib compression", # reserved
            253: "tamp compression", # reserved
            254: "general extension", # reserved
            255: "u/k", # reserved
        }

        if logger == None:
            self.logger = logging.getLogger(__name__)
    
    def process(self, new_data: bytes, local_partial_packet: bytearray = None):
        """
        Process new data, extract complete packets, decode them, and handle based on data type.

        Supports multiple compressed packets within a stream through recursive calls.
        Returns a list of results from successfully processed packets.
        """

        if not new_data:
            return []

        eop_marker = self.eop

        # Add new data to the partial packet buffer
        if local_partial_packet is None:
            local_partial_packet = self.partial_packet
        
        local_partial_packet.extend(new_data)

        # Split into packets using the EOP marker
        all_complete_packets = local_partial_packet.split(eop_marker)
        local_partial_packet.clear() # Clear the buffer
        local_partial_packet.extend(all_complete_packets.pop())

        results = []

        for i, packet in enumerate(all_complete_packets):
            if not packet:
                continue  # Skip empty packets

            self.logger.log(logging.DEBUG, f"Processing packet {i}: {packet}")

            try:
                # Decode the packet using COBS
                decoded_packet = cobs.decode(packet)
                if not decoded_packet:
                    self.logger.log(logging.WARNING, f"Empty decoded packet {i}")
                    continue

                # Extract data type and payload
                _data_type, *_payload = decoded_packet

                # Standard uncompressed data
                if _data_type < 250:
                    data_type = _data_type
                    payload = _payload

                # Zlib compressed data
                elif _data_type == 252:  # zlib compressed data
                    decompressed_data = zlib.decompress(bytes(_payload))
                    new_local_buffer = bytearray()
                    results.extend(self.process(decompressed_data, new_local_buffer))
                    continue

                # Tamp compressed data
                elif _data_type == 253:  # tamp compressed data
                    decompressed_data = tamp.decompress(bytes(_payload))
                    new_local_buffer = bytearray()
                    results.extend(self.process(decompressed_data, new_local_buffer))
                    continue

                # Extension table
                elif _data_type == 254:  # extension table
                    data_type, payload = self.handle_extension(_payload)

                # Whatever is left
                else:
                    data_type = _data_type
                    payload = _payload
            
                # Retrieve the handler for the data type
                handler = self.handlers.get(data_type)
                if handler:
                    decoded_data = handler(bytes(payload))  # Ensure payload is bytes
                    results.append({
                        "datatype": data_type,
                        "name": self.name.get(data_type, f"Unknown_{data_type}"),
                        "data": decoded_data,
                        "timestamp": time.time(),  # Add a timestamp
                    })
                else:
                    self.logger.log(logging.ERROR, f"Unknown data type: {data_type} in packet {i}")

            except Exception as e:
                self.logger.log(logging.ERROR, f"Error decoding packet {i}: {e}")

        return results

    #########################################################################################
    # Data Types
    #########################################################################################

    """ 
    ## General
    """

    def handle_unknown(self,payload):
        return None
    
    def handle_char(self,payload):
        strings = payload.split(b'\x00')
        return [s.decode('utf-8') for s in strings if s]

    def handle_byte(self,payload):
        if len(payload) == 1:
            # Return the single byte as an integer
            return payload[0]
        elif len(payload) > 1:
            # Convert the payload to a NumPy array if it contains multiple bytes
            return np.frombuffer(payload, dtype=np.uint8)
        else:
            # Handle empty payloads gracefully
            raise ValueError("Payload is empty")

    def handle_bool(self,payload: bytes):
        if len(payload) == 1:
            return bool(payload[0])  # Return a single byte as a boolean
        elif len(payload) > 1:
            return np.frombuffer(payload, dtype=np.uint8).astype(bool)
        else:
            raise ValueError("Payload is empty")

    def handle_int8(self,payload: bytes):
        if len(payload) == 1:
            return struct.unpack("b", payload)[0]
        elif len(payload) > 1:
            return np.frombuffer(payload, dtype=np.int8)
        else:
            raise ValueError("Payload is empty")

    def handle_short(self,payload: bytes):
        if len(payload) == 2:
            return struct.unpack("h", payload)[0]  # Single int16 value
        elif len(payload) % 2 == 0:
            return np.frombuffer(payload, dtype=np.int16)
        else:
            raise ValueError("Payload length is not a multiple of 2 for int16")

    def handle_ushort(self,payload: bytes):
        if len(payload) == 2:
            return struct.unpack("H", payload)[0]  # Single uint16 value
        elif len(payload) % 2 == 0:
            return np.frombuffer(payload, dtype=np.uint16)
        else:
            raise ValueError("Payload length is not a multiple of 2 for uint16")

    def handle_int(self,payload: bytes):
        if len(payload) == 4:
            return struct.unpack("i", payload)[0]  # Single int32 value
        elif len(payload) % 4 == 0:
            return np.frombuffer(payload, dtype=np.int32)
        else:
            raise ValueError("Payload length is not a multiple of 4 for int32")

    def handle_uint(self,payload: bytes):
        if len(payload) == 4:
            return struct.unpack("I", payload)[0]  # Single uint32 value
        elif len(payload) % 4 == 0:
            return np.frombuffer(payload, dtype=np.uint32)
        else:
            raise ValueError("Payload length is not a multiple of 4 for uint32")

    def handle_long(self,payload: bytes):
        if len(payload) == 8:
            return struct.unpack("q", payload)[0]  # Single int64 value
        elif len(payload) % 8 == 0:
            return np.frombuffer(payload, dtype=np.int64)
        else:
            raise ValueError("Payload length is not a multiple of 8 for int64")

    def handle_ulong(self,payload: bytes):
        if len(payload) == 8:
            return struct.unpack("Q", payload)[0]  # Single uint64 value
        elif len(payload) % 8 == 0:
            return np.frombuffer(payload, dtype=np.uint64)
        else:
            raise ValueError("Payload length is not a multiple of 8 for uint64")

    def handle_float(self,payload: bytes):
        if len(payload) == 4:
            return struct.unpack("f", payload)[0]  # Single float32 value
        elif len(payload) % 4 == 0:
            return np.frombuffer(payload, dtype=np.float32)
        else:
            raise ValueError("Payload length is not a multiple of 4 for float32")

    def handle_double(self,payload: bytes):
        if len(payload) == 8:
            return struct.unpack("d", payload)[0]  # Single float64 value
        elif len(payload) % 8 == 0:
            return np.frombuffer(payload, dtype=np.float64)
        else: 
            raise ValueError("Payload length is not a multiple of 8 for float64")

    """
    ## Extension
    """
    def handle_extension(self,payload):
        if len(payload) > 1:
            data_type, *data = payload
            # this will need to be further developed if we ever need extended data types
            return data_type, data
        else: 
            self.logger.log(logging.ERROR, f"Data of type extension needs to have more than 1 byte")
            return 0, b''
    
    """
    ## Compression

    Here we assume that only one packet is compressed and that data type id is second byte of packet
    """

    def handle_zlib(self,payload: bytes) -> Tuple[int, bytes]:
        if len(payload) > 1:
            data_type, *data = payload
            decompressed_data = zlib.decompress(data)
            return data_type, decompressed_data
        else: 
            self.logger.log(logging.ERROR, f"Data needs to have more than 1 byte")
            return 0, b''

    def handle_tamp(self,payload: bytes) -> Tuple[int, bytes]:
        if len(payload) >1:
            data_type, *data = payload
            decompressed_data = tamp.decompress(data)
            return data_type, decompressed_data
        else: 
            self.logger.log(logging.ERROR, f"Data needs to have more than 1 byte")
            return 0, b''

    """
    ## Physics    
    """
    def handle_length(self,payload):
        # returns meters
        return self.handle_float(payload)

    def handle_mass(self,payload):
        # returns kg
        return self.handle_float(payload)

    def handle_time(self,payload):
        # returns kg
        return self.handle_float(payload)
    
    def handle_current(self,payload):
        # returns Ampere
        return self.handle_float(payload)
    
    def handle_temperature(self,payload):
        # return Kelvin
        return self.handle_float(payload)
    
    def handle_amount(self,payload):
        # returns mol
        return self.handle_float(payload)
    
    def handle_luminous_intensity(self,payload):
        # return candela
        return self.handle_float(payload)
    
    def handle_brightness(self,payload):
        # return lumens
        return self.handle_float(payload)
    
    def handle_angle(self,payload):
        # return degrees
        return self.handle_float(payload)
    
    def handle_area(self,payload):
        return self.handle_float(payload)
    
    def handle_volume(self,payload): 
        return self.handle_float(payload)
    
    def handle_force(self,payload):
        return self.handle_float(payload)
    
    def handle_velocity(self,payload):
        return self.handle_float(payload)
    
    def handle_acceleration(self,payload):  
        return self.handle_float(payload)
    
    def handle_pressure_P(self,payload):
        return self.handle_float(payload)

    def handle_pressure_mB(self,payload):
        return self.handle_float(payload)

    def handle_energy(self,payload):
        return self.handle_float(payload)
    
    def handle_power(self,payload):
        return self.handle_float(payload)
    
    def handle_charge(self,payload):
        return self.handle_float(payload)
    
    def handle_voltage(self,payload):
        return self.handle_float(payload)
    
    def handle_resistance(self,payload):
        return self.handle_float(payload)
    
    def handle_conductance(self,payload):
        return self.handle_float(payload)
    
    def handle_reactance(self,payload):
        return self.handle_float(payload)
    
    def handle_impedance(self,payload): 
        # returns resistance, reactance
        values = self.handle_float(payload)
        if len(values) % 2 != 0:
            raise ValueError("Input array length must be even to reshape into wavelength-intensity pairs.")
        # Reshape the array
        return values.reshape(-1, 2)
        
    def handle_phase(self,payload):
        return self.handle_float(payload)
    
    def handle_inductance(self,payload):
        return self.handle_float(payload)
    
    def handle_capacitance(self,payload):
        return self.handle_float(payload)
    
    def handle_magnetic_field(self,payload):
        return self.handle_float(payload)
    
    def handle_frequency(self,payload):
        return self.handle_float(payload)
    
    def handle_molarity(self,payload):
        return self.handle_float(payload)
    
    def handle_electron_volts(self,payload):
        return self.handle_float(payload)
    
    def handle_optical_spectrum(self,payload):
        values = self.handle_float(payload)
        if len(values) % 2 != 0:
            raise ValueError("Input array length must be even to reshape into wavelength-intensity pairs.")
        # Wavelength, Intensity interleaved
        return values.reshape(-1, 2)
    
    def handle_frequency_spectrum(self,payload):
        values = self.handle_float(payload)
        if len(values) % 2 != 0:
            raise ValueError("Input array length must be even to reshape into frequency-intensity pairs.")
        # Frequency, Intensity interleaved
        return values.reshape(-1, 2)
        
    """
    ## Physiology measurements
    """

    def handle_Temperature_C(self,payload):
        # return Celsius 0...65.536 C
        return self.handle_ushort(payload) / 1000.0

    def handle_HeartRate(self,payload):
        # return beat per minutes 0...655.36 bpm
        return self.handle_ushort(payload) / 100.0

    def handle_HeartRateVariability(self,payload):
        # return ms float
        return self.handle_float(payload)

    def handle_RespiratoryRate(self,payload):
        # return breaths/min 0...655.36 bpm
        return self.handle_ushort(payload) / 100.0

    def handle_BloodPressure(self,payload):
        # return mmHg 0...655.35 mmHg
        return self.handle_ushort(payload) / 100.0
    
    def handle_BloodPressureSystolic(self,payload):
        # return mmHg 0...655.35 mmHg
        return self.handle_ushort(payload) / 100.0
    
    def handle_BloodPressureDiastolic(self,payload):
        # return mmHg 0...655.35 mmHg
        return self.handle_ushort(payload) / 100.0
    
    def handle_SPO2(self,payload):
        # return percentage 0..100.00%
        return self.handle_ushort(payload) / 100.0
    
    def handle_Weight(self,payload):
        # return kg 0...4294.967295 kg
        return self.handle_uint(payload) / 1000000.0
    
    def handle_Height(self,payload):
        # return meter 0...65.536
        return self.handle_ushort(payload) / 100.0
    
    def handle_Age(self,payload):
        # return years 0...655.36
        return self.handle_ushort(payload) /100.0
    
    def handle_BMI(self,payload):
        # return unitless 0...65.536
        return self.handle_ushort(payload) / 1000.0
    
    def handle_WaistCircumference(self,payload):
        # return meter 0...65.536
        return self.handle_ushort(payload) / 1000.0
    
    def handle_HipCircumference(self,payload):
        # return meter 0...65.536
        return self.handle_ushort(payload) / 1000.0
    
    def handle_ChestCircumference(self,payload):
        # return meter 0...65.536
        return self.handle_ushort(payload) / 1000.0
    
    def handle_ThighCircumference(self,payload):
        # return meter 0...65.536
        return self.handle_ushort(payload) / 1000.0
    
    def handle_ArmCircumference(self,payload):
        # return meter 0...65.536
        return self.handle_ushort(payload) / 1000.0
    
    def handle_CalfCircumference(self,payload):
        # return meter 0...65.536
        return self.handle_ushort(payload) / 1000.0
    
    def handle_BIOZ(self,payload):
        # return float, float, float
        values = self.handle_float(payload)
        if len(values) % 3 != 0:
            raise ValueError("Input array length must be multiple of 3 to reshape into frequency, resistance, reactance pairs.")
        return values.reshape(-1, 3)

    def handle_FatFreeMass(self,payload):
        # return kg 0...656.36 kg
        return self.handle_float(payload) / 100.0
    
    def handle_TotalBodyWater(self,payload):
        # return liters 0...655.36 liters
        return self.handle_float(payload) / 100.0
    
    def handle_ExtracellularWater(self,payload):
        # return liters 0...655.36 liters
        return self.handle_float(payload) / 100.0
    
    def handle_TotalBodyPotassium(self,payload):
        # return grams
        return self.handle_float(payload)
           
    def handle_BodyFatPercentage(self,payload):
        # return percentage
        return self.handle_float(payload)
    
    def handle_BodyWaterPercentage(self,payload):
        # return percentage
        return self.handle_float(payload) 
    
    def handle_MuscleMassPercentage(self,payload):
        # return percentage
        return self.handle_float(payload)
    
    def handle_ECG(self,payload):   
        # return V 0...0.032767 V
        return self.handle_short(payload) / 1000000.0

    def handle_ECG12(self,payload):   
        # return V 0...0.032767 V
        values = self.handle_short(payload) / 1000000.0
        if len(values) % 12 != 0:
            raise ValueError("Input array length must be multiple of 12 to reshape into 12 lead measurements.")
        return values.reshape(-1, 12)

    def handle_EEG(self,payload):
        # return V 0...0.032767 V
        return self.handle_short(payload) / 1000000.0

    def handle_EMG(self,payload):
        # return V 0...0.032767 V
        return self.handle_short(payload) / 1000000.0

    def handle_ForcedExpiratoryVolume(self,payload):
        # return liter 0...32.767 l/s
        return self.handle_short(payload) / 1000.0

    def handle_LungFlow(self,payload):        
        # return liter 0...65.536 l
        return self.handle_ushort(payload) / 1000.0
    
    def handle_LungVolume(self,payload):
        # return liter 0...65.536 l
        return self.handle_ushort(payload) / 1000.0
    
    def handle_GlucoseLevel(self,payload):
        # return mg/dL
        return self.handle_float(payload)
    
    def handle_CholesterolLevel(self,payload):
        # return mg/dL
        return self.handle_float(payload)
    
    def handle_BaseMetabolicRate(self,payload):
        # return kcal/day
        return self.handle_float(payload)
    
    def handle_ReactionTime(self,payload):
        # return ms
        return self.handle_float(payload) / 1000.
    
    def handle_RangeOfMotion(self,payload):
        # return degrees
        return self.handle_float(payload)
    
    def handle_GripStrength(self,payload):
        # return kg
        return self.handle_float(payload)
        
    """
    ## Motion and Position Sensors
    """

    def handle_Acceleration3D(self,payload):
        # return m/s^2
        values = self.handle_float(payload)
        if len(values) % 3 != 0:
            raise ValueError("Input array length must be multiple of 3 to reshape into x,y,z acceleration.")
        return values.reshape(-1, 3)

    def handle_Velocity3D(self,payload):
        # return m/s
        values = self.handle_float(payload)
        if len(values) % 3 != 0:
            raise ValueError("Input array length must be multiple of 3 to reshape into x,y,z velocity.")
        return values.reshape(-1, 3)

    def handle_Position3D(self,payload):
        # return m
        values = self.handle_float(payload)
        if len(values) % 3 != 0:
            raise ValueError("Input array length must be multiple of 3 to reshape into x,y,z position.")
        return values.reshape(-1, 3)

    def handle_OrientationYPR3D(self,payload):
        # return degrees
        values = self.handle_float(payload)
        if len(values) % 3 != 0:
            raise ValueError("Input array length must be multiple of 3 to reshape into yaw, pitch, roll angles.")
        return values.reshape(-1, 3)
    
    def handle_OrientationYPR3Dcenti(self,payload):
        # return centi degrees
        values = self.handle_short(payload) / 100.0
        if len(values) % 3 != 0:
            raise ValueError("Input array length must be multiple of 3 to reshape into yaw, pitch, roll angles.")
        return values.reshape(-1, 3)
    
    def handle_Magnetometer3D(self,payload):
        # return microTesla
        values = self.handle_float(payload)
        if len(values) % 3 != 0:
            raise ValueError("Input array length must be multiple of 3 to reshape into x,y,z magnetic field.")
        return values.reshape(-1, 3)
    
    def handle_Gyration3D(self,payload):
        # return deg/sec
        values = self.handle_float(payload)
        if len(values) % 3 != 0:
            raise ValueError("Input array length must be multiple of 3 to reshape into x,y,z gyration.")
        return values.reshape(-1, 3)
    
    def handle_Position(self,payload):
        # return degrees, degrees, meters
        values = self.handle_float(payload)
        if len(values) % 3 != 0:
            raise ValueError("Input array length must be multiple of 3 to reshape into longitude, latitude, altitude.")
        return values.reshape(-1, 3)
    
    def handle_Altitude(self,payload):
        # return meters
        return self.handle_float(payload)
    
    def handle_StepsPerMinute(self,payload):
        # return 1/min
        return self.handle_short(payload) / 100.0

    def handle_StepsTotal(self,payload):
        # return unitless
        return self.handle_uint(payload)

    """
    ## Air Quality and Gas Sensors
    """

    def handle_PM(self,payload):
        # return micro gr/m^3 0...65,536
        values = self.handle_float(payload)
        if len(values) % 3 != 0:
            raise ValueError("Input array length must be multiple of 3 to reshape into PM 1.0, PM 2.5 and PM 10.")
        return values.reshape(-1, 3)
    
    def handle_PM1(self,payload):
        # return micro gr/m^3 0...65,536
        return self.handle_float(payload)
    
    def handle_PM2_5(self,payload):
        # return micro gr/m^3 0...65,536
        return self.handle_float(payload)
    
    def handle_PM10(self,payload):
        # return micro gr/m^3 0...65,536
        return self.handle_float(payload)
    
    def handle_CO2ppm(self,payload):
        # return ppm 0...65,536 ppm
        return self.handle_ushort(payload)
    
    def handle_eCO2(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)
    
    def handle_VOCppb(self,payload):
        # return ppb 0...65,536 ppb
        return self.handle_ushort(payload)
    
    def handle_eVOC(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)
    
    def handle_NO2ppb(self,payload):
        # return ppb 0...65,536 ppb
        return self.handle_ushort(payload)
    
    def handle_eNO2(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)
    
    def handle_SO2ppb(self,payload):
        # return ppb 0...65,536 ppb
        return self.handle_ushort(payload)
    
    def handle_eSO2(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)
    
    def handle_O3ppb(self,payload):
        # return ppb 0...65,536 ppb
        return self.handle_ushort(payload)
    
    def handle_eO3(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)
    
    def handle_COppm(self,payload):
        # return ppm 0...65,536 ppm
        return self.handle_ushort(payload)
    
    def handle_eCO(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)
    
    def handle_H2Sppb(self,payload):
        # return ppb 0...65,536 ppb
        return self.handle_ushort(payload)
    
    def handle_eH2S(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)
    
    def handle_NH3ppb(self,payload):
        # return ppb 0...65,536 ppb
        return self.handle_ushort(payload)
    
    def handle_eNH3(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)
    
    def handle_H2ppm(self,payload):
        # return ppm 0...65,536 ppm
        return self.handle_ushort(payload)
    
    def handle_eH2(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)
    
    def handle_CH4ppm(self,payload):
        # return ppm 0...65,536 ppm
        return self.handle_ushort(payload)
    
    def handle_eCH4(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)
    
    def handle_C2H6ppm(self,payload):
        # return ppm 0...65,536 ppm
        return self.handle_ushort(payload)
    
    def handle_eC2H6(self,payload):
        # return arbitrary 0...65,536
        return self.handle_ushort(payload)    
    
    def handle_IAQ(self,payload):
        # return Indoor air quality 0...65,536
        return self.handle_ushort(payload)
    
    """
    ## Audio
    """
    
    def handle_audio_mono8(self,payload):
        return self.handle_int8(payload)

    def handle_audio_stereo8(self,payload):
        values = self.handle_int8(payload)
        if len(values) % 2 != 0:
            raise ValueError("The input array length must be even.")
        return values.reshape(-1, 2)

    def handle_audio_mono16(self,payload):
        return self.handle_short(payload)

    def handle_audio_stereo16(self,payload):
        values = self.handle_short(payload)
        if len(values) % 2 != 0:
            raise ValueError("The input array length must be even.")
        return values.reshape(-1, 2)

    def handle_audio_mono8_ADPCM(self,payload):
        return self.mono_adpcm8(payload)

    def handle_audio_stereo8_ADPCM(self,payload):
        return self.stereo_adpcm8(payload)

    def handle_audio_mono16_ADPCM(self,payload):
        return self.mono_adpcm16(payload)

    def handle_audio_stereo16_ADPCM(self,payload):
        return self.stereo_adpcm16(payload)

    """
    ## Image
    """
    
    def handle_image_gray8(self,payload):
        raw = self.handle_byte(payload)
        lines = np.frombuffer(raw[:2], dtype=np.uint16)[0]  # Extract as uint16
        image_data = raw[2:]  # Remaining bytes are the image data
        pixels_per_line = len(image_data) // lines
        if len(image_data) % lines != 0:
            raise ValueError("Image data size is not a multiple of the number of lines.")
        return image_data.reshape(lines, pixels_per_line)

    def handle_image_color8(self,payload):
        # 8bit image with color palette, each pixel is an index to the palette
        raw = self.handle_byte(payload)
        lines = np.frombuffer(raw[:2], dtype=np.uint16)[0]
        palette_data = raw[2:770]
        if len(palette_data) % 3 != 0:
            raise ValueError("Palette data size is not divisible by 3.")
        palette = palette_data.reshape(-1, 3)
        image_data = raw[770:]
        image_data_rgb = palette[image_data]  # Each index is replaced with its RGB triplet
        pixels_per_line = len(image_data) // lines
        if len(image_data) % lines != 0:
            raise ValueError("Image data size is not a multiple of the number of lines.")
        pixels_per_line = len(image_data) // lines
        return image_data_rgb.reshape(lines, pixels_per_line, 3)
        
    def handle_image_color24(self,payload):
        raw = self.handle_byte(payload)
        lines = np.frombuffer(raw[:2], dtype=np.uint16)[0]
        image_data = raw[2:]
        pixels_per_line = len(image_data) // (lines * 3)
        if len(image_data) % (lines * 3) != 0:
            raise ValueError("Image data size is not a multiple of the number of lines.")
        return image_data.reshape(lines, pixels_per_line, 3)
    
    def handle_image_color32(self,payload):
        raw = self.handle_byte(payload)
        lines = np.frombuffer(raw[:2], dtype=np.uint16)[0]
        image_data = raw[2:]
        pixels_per_line = len(image_data) // (lines * 4)
        if len(image_data) % (lines * 4) != 0:
            raise ValueError("Image data size is not a multiple of the number of lines.")
        return image_data.reshape(lines, pixels_per_line, 4)
    
    def handle_image_gray8_dct(self,payload):
        # Simple JPG type image: RLE-compressed DCT coefficients
        # Extract data
        raw = self.handle_byte(payload)
        lines = np.frombuffer(raw[:2], dtype=np.uint16)[0]
        compressed_image_data = raw[2:]  # Remaining bytes are the RLE-compressed DCT coefficients
        # RLE Decompress
        dct_coefficients = self.rle_compressor.decompress(compressed_image_data)
        # Inverse DCT
        num_blocks = len(dct_coefficients) // (self.block_size_dct ** 2)
        dct_coefficients = dct_coefficients[:num_blocks * self.block_size_dct ** 2].reshape(num_blocks, self.block_size_dct, self.block_size_dct)
        reconstructed_blocks = []
        for block in dct_coefficients:
            idct_block = idct(idct(block.T, norm='ortho').T, norm='ortho')
            reconstructed_blocks.append(idct_block)
        # Reconstruct image
        height = lines
        width = len(reconstructed_blocks) * self.block_size_dct // height
        reconstructed_image = np.vstack([np.hstack(reconstructed_blocks[i:i + width]) for i in range(0, len(reconstructed_blocks), width)])    
        return reconstructed_image
    
    def handle_image_color24_dct(self,payload):
        # Assume the payload is structured as RLE-compressed data for R, G, B channels consecutively
        raw = self.handle_byte(payload)
        lines = np.frombuffer(raw[:2], dtype=np.uint16)[0]
        compressed_data = raw[2:]  # Remaining bytes contain compressed data for all channels
        # Decompress the entire payload
        dct_coefficients = self.rle_compressor.decompress(compressed_data)
        # Split compressed data into three parts: R, G, B
        # This assumes equal size for each channel; adjust if header specifies sizes
        third_len = len(dct_coefficients) // 3
        dct_r = dct_coefficients[:third_len]
        dct_g = dct_coefficients[third_len:2*third_len]
        dct_b = dct_coefficients[2*third_len:]
        
        # Function to reconstruct an image channel
        def reconstruct_channel(dct_channel):
            num_blocks = len(dct_channel) // (self.block_size_dct ** 2)
            dct_channel = dct_channel[:num_blocks * self.block_size_dct ** 2].reshape(num_blocks, self.block_size_dct, self.block_size_dct)
            reconstructed_blocks = []
            for block in dct_channel:
                idct_block = idct(idct(block.T, norm='ortho').T, norm='ortho')
                reconstructed_blocks.append(idct_block)
            
            # Reconstruct image from blocks
            height = lines
            width = len(reconstructed_blocks) * self.block_size_dct // height
            reconstructed_channel = np.vstack([
                np.hstack(reconstructed_blocks[i:i + width]) for i in range(0, len(reconstructed_blocks), width)
            ])
            return reconstructed_channel

        # Reconstruct each channel
        channel_r = reconstruct_channel(dct_r)
        channel_g = reconstruct_channel(dct_g)
        channel_b = reconstruct_channel(dct_b)

        # Combine channels into an RGB image
        reconstructed_image = np.stack([channel_r, channel_g, channel_b], axis=-1)  # Shape: (height, width, 3)
        return reconstructed_image

    """    
    ## Do not use
    ===========================
    | ID  | Abr | measurement        | units     | datatype(s) |
    | --  | --- | -----------        | -----     | ----------- |
    | 254 | used to extend this table, next byte is the index for the second table
    | 255 | is reserved for separator
    """

    """
    ## Second Table
    ===========================
    Not needed yet
    """

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

if __name__ == "__main__":
    import os
    import matplotlib
    matplotlib.use('TkAgg') 
    import matplotlib.pyplot as plt
    
    # General Codec with base 254 encoding [PASSED]

    base = 254
    codec = GeneralCodec(base)
    max_digits = codec.compute_digits(8) # encode double with 8 bytes
    original_data = 98.2
    byte_data = struct.pack('d', original_data) # 'f' for float, 'd' for double
    print(f"Original: {original_data}")
    encoded = codec.encode(byte_data, length = 8)
    print(f"Encoded (base254): {encoded}")
    decoded = codec.decode(encoded, length = 8)
    print(f"Decoded: {decoded}")
    value = struct.unpack('d', decoded)[0]
    print(f"Value: {value}")
    assert byte_data == decoded


    # Printable Codec [PASSED]

    codec = PrintableCodec()
    print(f"Table: {codec.table}")
    print(f"Base: {codec.base}")
    print(f"Base {codec.char_to_val}")
    encoded = codec.encode(byte_data, length = 8)
    print(f"Encoded (printable): {encoded}")
    decoded = codec.decode(encoded, length = 8)
    print(f"Decoded: {decoded}")
    value = struct.unpack('d', decoded)[0]
    print(f"Value: {value}")
    assert byte_data == decoded

    # Compressor RLE [PASSED]
    # 30 microseconds encode for 1k text
    # 5300 microseconds decode for 1k text !!!!!!!!!!!!!!!
    byte_data = bytearray(text.encode('utf-8'))

    compressor = Compressor("rle")
    print(f"Original: {byte_data}")
    compressed = compressor.compress(byte_data)
    tic = time.perf_counter()
    for i in range(100):
        compressed = compressor.compress(byte_data)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time RLE compress: {time_elapsed} seconds for 1k text")
    print(f"Compressed (rle): {compressed}")
    tic = time.perf_counter()
    for i in range(100):
        decompressed = compressor.decompress(compressed)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time RLE decompress: {time_elapsed} seconds for 1k text")
    print(f"Decompressed: {decompressed}")
    assert byte_data == decompressed

    # Compressor ZIP  [PASSED]
    # 200 microseconds for 1k text compress
    # 1000 microseconds for 1k text decompress

    compressor = Compressor("zlib")
    print(f"Original: {byte_data}")
    compressed = compressor.compress(byte_data)
    tic = time.perf_counter()
    for i in range(100):
        compressed = compressor.compress(byte_data)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time ZLIB compress: {time_elapsed} seconds for 1k text")
    print(f"Compressed (zip): {compressed}")
    decompressed = compressor.decompress(compressed)
    tic = time.perf_counter()
    for i in range(100):
        decompressed = compressor.decompress(compressed)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time ZLIB decompress: {time_elapsed} seconds for 1k text")
    print(f"Decompressed: {decompressed}")
    assert byte_data == decompressed

    # Compressor TAMP  [PASSED]
    # 620 microseconds for 1k text compress
    # 230 microseconds for 1k text decompress

    compressor = Compressor("tamp")
    print(f"Original: {byte_data}")
    compressed = compressor.compress(byte_data)
    tic = time.perf_counter()
    for i in range(100):
        compressed = compressor.compress(byte_data)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time TAMP compress: {time_elapsed} seconds for 1k text")
    print(f"Compressed (tamp): {compressed}")
    decompressed = compressor.decompress(compressed)
    tic = time.perf_counter()
    for i in range(100):
        decompressed = compressor.decompress(compressed)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time TAMP decompress: {time_elapsed} seconds for 1k text")
    print(f"Decompressed: {decompressed}")
    assert byte_data == decompressed

    # COBS  [PASSED]
    # 80 microseconds for 1k text encode
    # 85 microseconds for 1k text decode`

    data = os.urandom(1024)
    print(f"Original: {data}")
    encoded_packet = cobs.encode(data) + b'\x00'
    tic = time.perf_counter()
    for i in range(100):
        encoded_packet = cobs.encode(data) + b'\x00'
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time COBS encode: {time_elapsed} seconds for 1024 bytes")
    print(f"Encoded (cobs): {encoded_packet}")
    packet = encoded_packet.split(b'\x00')[0]
    decoded_packet = cobs.decode(packet)
    tic = time.perf_counter()
    for i in range(100):
        decoded_packet = cobs.decode(packet)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time COBS decode: {time_elapsed} seconds for 1024 bytes")
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
    print(f"Elapsed time ADPCM mono encode: {time_elapsed} seconds 1000 samples")

    #print(f"Encoded (ADPCM): {encoded_data}")
    decoded_data = codec.decode(encoded_data)
    tic = time.perf_counter()
    for i in range(100):
        decoded_data = codec.decode(encoded_data)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time ADPCM mono decode: {time_elapsed} seconds 1000 samples")
    #print(f"Decoded: {decoded_data}")
    difference = ((mono_data-decoded_data)/mono_data*100)
    difference_int = np.round(difference).astype(int)
    #print(f"Decoded: {difference_int}")

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
    ax2.set_ylabel("Relative Difference [%]", color="r")
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
    print(f"Elapsed time ADPCM stereo encode: {time_elapsed} seconds 20000 samples")
    #print(f"Encoded (ADPCM): {encoded_data}")
    decoded_data = codec.decode(encoded_data)
    tic = time.perf_counter()
    for i in range(100):
       decoded_data = codec.decode(encoded_data)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time ADPCM stereo decode: {time_elapsed} seconds 2000 samples")
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
    print(f"Original: {data}")
    results = processor.process(data, labels = True)
    for result in results:
        print(result)

    data = b'Voltage: 12 11.8 11.6\nCurrent: 1.2 1.3 1.4\n'
    print(f"Original: {data}")
    results = processor.process(data, labels = True)
    tic = time.perf_counter()
    for i in range(100):
        results = processor.process(data, labels = True)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time Arduino Header: {time_elapsed} seconds")
    for result in results:
        print(result)

    processor = ArduinoTextStreamProcessor(eol=b'\n', encoding='utf-8')
    data = b'12, 11.8, 11.6\n1.2, 1.3, 1.4\n'
    print(f"Original: {data}")
    results = processor.process(data, labels = False)
    for result in results:
        print(result)

    data = b'12 11.8 11.6\n1.2 1.3 1.4\n'
    print(f"Original: {data}")
    results = processor.process(data, labels = False)
    tic = time.perf_counter()
    for i in range(100):
        results = processor.process(data, labels = False)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time Arduino no header: {time_elapsed} seconds")
    for result in results:
        print(result)

    # Binary stream processor 

    # Straight 50 microseconds  1k text 20Mbytes/sec
    # Zlib 285 microseconds  1k text 3.5Mbytes/sec
    # Tamp 390 microseconds 1k text 2.5Mbytes/sec

    # [PASSED]
    processor = BinaryStreamProcessor(eop=b'\x00')
    data = b'\x02' + os.urandom(1024)
    np_data = np.frombuffer(data, dtype=np.uint8)
    print(f"Original: {np_data}")
    encoded_packet = cobs.encode(data) + b'\x00'
    # print(f"Encoded (cobs): {encoded_packet}")
    results = processor.process(encoded_packet)
    tic = time.perf_counter()
    for i in range(100):
        results = processor.process(encoded_packet)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time Binary: {time_elapsed} seconds for 1024 bytes")
    for result in results:
        print(result["data"])

    # Binary stream processor with compression

    ZLIB_ID = 252
    TAMP_ID = 253
    CHAR_ID = 0

    # [PASSED]

    data = struct.pack('B', CHAR_ID) + text.encode('utf-8')
    data_packet = cobs.encode(data) + b'\x00'
    compressed_data_packet = zlib.compress(data_packet)
    packet = struct.pack('B', ZLIB_ID) + compressed_data_packet 
    encoded_packet = cobs.encode(packet) + b'\x00'
    results = processor.process(encoded_packet)
    tic = time.perf_counter()
    for i in range(100):
        results = processor.process(encoded_packet)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time binary ZLIB: {time_elapsed} seconds for 1k text")
    for result in results:
        print(result["data"])

    # [PASSED]

    data = struct.pack('B', CHAR_ID) + text.encode('utf-8')
    data_packet = cobs.encode(data) + b'\x00'
    compressed_data_packet = tamp.compress(data_packet)
    packet = struct.pack('B', TAMP_ID) + compressed_data_packet 
    encoded_packet = cobs.encode(packet) + b'\x00'
    results = processor.process(encoded_packet)
    tic = time.perf_counter()
    for i in range(100):
        results = processor.process(encoded_packet)
    toc = time.perf_counter()
    time_elapsed = (toc - tic)/100
    print(f"Elapsed time binary TAMP: {time_elapsed} seconds for 1k text")
    for result in results:
        print(result["data"])




# test_header_parser.py
from line_parsers import header_parser
import numpy as np

def print_results(arr, shape, names, debuglog=""):
    print("  array shape property:", arr.shape)
    print("  returned shape tuple:", shape)
    print("  variable names dict:", names)
    print("  array:\n", arr)
    if not(debuglog == ""):
        print("  debug log:\n", debuglog)

# ──── test : mixed headers + header-less data ─────

lines = [
    "temp:1 2 3 pressure:101,102",
    "temp:4 5 6 humidity:30, 40 50, 60",
    "humidity: 31,41 pressure:103, 104 temp: 7",
    "8 9, ,99 98",                         # no header here
    "10 11 12, humidity: 60, 70 80",       # start with no header followed by header"
]

"""
array
[[  1.  101. 102. NaN NaN NaN NaN NaN NaN]
 [  2.  NaN  NaN  NaN NaN NaN NaN NaN NaN]
 [  3.  NaN  NaN  NaN NaN NaN NaN NaN NaN]
 [  4.  NaN  NaN  30. 40. 60. NaN NaN NaN]
 [  5.  NaN  NaN  NaN 50. NaN NaN NaN NaN]
 [  6.  NaN  NaN  NaN NaN NaN NaN NaN NaN]
 [  7.  103. 104. 31. 41. NaN NaN NaN NaN]
 [ NaN  NaN  NaN  NaN NaN NaN   8 NaN  99]
 [ NaN  NaN  NaN  NaN NaN NaN   9 NaN  98]
 [ NaN  NaN  NaN  60. 70. NaN  10 NaN NaN]
 [ NaN  NaN  NaN  NaN 80. NaN  11 NaN NaN]
 [ NaN  NaN  NaN  NaN NaN NaN  12 NaN NaN]
 ]

 variable names
{'temp': 0, 'pressure_1': 1, 'pressure_2': 1, 'humidity_1': 3, 'humidity_2': 4, 'humidity_3': 5, '__unnamed_1':6,'__unnamed_2':6, '__unnamed_3':6}
"""

print("=== Test: mixed headers + implicit columns ===")
# arr, shape, names, debuglog = header_parser.parse_lines(lines, strict=False, gil_release=False, debug=False)
# print_results(arr, shape, names, debuglog)
arr, shape, names = header_parser.parse_lines(lines, strict=False, gil_release=False)
print_results(arr, shape, names)

# ─── test : Multiple headers with single or multiple sub channels ─────

lines = [
    "Numbers:1 2 3, 4 5 6, 7 8 9, 10 11 12",
    "Decimals: 10 20 30, 40, 50 60",
    "Numbers:7 8 9",
    "Hundreds: 101, 102, 103",
    "Hundreds: 104, 105, 106",
    "Hundreds: 107, 108, 109",
    "Decimals: 80 81 82,90 91 92, 93 94 95",
    "Hundreds: 107, 108, 109 Decimals: 70, 80, 90 Numbers: 13 14, 15 16, 17 18",
]


"""
=== Test: simple parsing ===
  array shape property: ()
  returned shape tuple: []
  variable names dict: 
  ['Numbers_1', 'Numbers_2', 'Numbers_3', 'Numbers_4', 'Decimals_1', 'Decimals_2', 'Decimals_3', 'Hundreds_1', 'Hundreds_2', 'Hundreds_3']
  array:
 [[ 1.   4.   7.  10.  nan  nan  nan  nan  nan  nan]
 [  2.   5.   8.  11.  nan  nan  nan  nan  nan  nan]
 [  3.   6.   9.  12.  nan  nan  nan  nan  nan  nan]
 [ nan  nan  nan  nan  10.  40.  50.  nan  nan  nan]
 [ nan  nan  nan  nan  20.  nan  60.  nan  nan  nan]
 [ nan  nan  nan  nan  30.  nan  nan  nan  nan  nan]
 [  7.  nan  nan  nan  nan  nan  nan  nan  nan  nan]
 [  8.  nan  nan  nan  nan  nan  nan  nan  nan  nan]
 [  9.  nan  nan  nan  nan  nan  nan  nan  nan  nan]
 [ nan  nan  nan  nan  nan  nan  nan 101. 102. 103.]
 [ nan  nan  nan  nan  nan  nan  nan 104. 105. 106.]
 [ nan  nan  nan  nan  nan  nan  nan 107. 108. 109.]
 [ nan  nan  nan  nan  80.  90.  93.  nan  nan  nan]
 [ nan  nan  nan  nan  81.  91.  94.  nan  nan  nan]
 [ nan  nan  nan  nan  82.  92.  95.  nan  nan  nan]
 [ 13.  15.  17.  nan  70.  80.  90. 107. 108. 109.]
 [ 14.  16.  18.  nan  nan  nan  nan  nan  nan  nan]]   
"""

print("=== Test: mixed headers ===")
# arr, shape, names, debuglog = header_parser.parse_lines(lines, strict=False, gil_release=False, debug=False)
# print_results(arr, shape, names, debuglog)
arr, shape, names = header_parser.parse_lines(lines, strict=False, gil_release=False)
print_results(arr, shape, names)

# ─── test : strict ─────
lines = ["A:1,2,foo"]            # “foo” won’t parse → NaN in default mode
print("=== Test: strict parsing (should raise parse error) ===")
try:
    # arr, shape, names, debuglog = header_parser.parse_lines(lines, strict=True)
    arr, shape, names = header_parser.parse_lines(lines, strict=True)
except Exception as e:
    print("Caught parse error:", e)

# ─── test : malformed tokens ─────
lines = [
    "A:1,2,foo",                # “foo” won’t parse → NaN in default mode
    "   ",                      # blank line → all-NaN row
    ",1,,2,",                   # empty segments + values, no headers
    "B:5,6 C:7",                # multiple headers with regular data, no malformed tokens
    "A: 107, 108, 109 B: 70, 80, 90 C: 13 14, garbage, 17 18 garbage" # malformed token "garbage", first one should create new column, second one should be in new row
]
"""
=== Test: default (non-strict) parsing ===
  array shape property: (7, 14)
  returned shape tuple: (7, 14)
  variable names dict: ['A_1', 'A_2', 'A_3', 
                        '__unnamed_1', '__unnamed_2', '__unnamed_3', '__unnamed_4', '__unnamed_5', 
                        'B_1', 'B_2', 'C_1', 'B_3', 'C_2', 'C_3']
  array:
  A_1   A_2   A_3  u_1  u_2  u_3  u_4  u_5  B_1  B_2  C_1  B_3  C_2  C_3
 [[  1.   2.  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan]
 [  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan]
 [  nan  nan  nan  nan   1.  nan   2.  nan  nan  nan  nan  nan  nan  nan]
 [  nan  nan  nan  nan  nan  nan  nan  nan   5.   6.   7.  nan  nan  nan]
 [ 107. 108. 109.  nan  nan  nan  nan  nan  70.  80.  13.  90.  nan  17.]
 [  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  14.  nan  nan  18.]
 [  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan  nan]]
"""

print("=== Test: default (non-strict) parsing ===")
# arr, shape, names, debuglog = header_parser.parse_lines(lines, strict=False, gil_release=False, debug=True)
# print_results(arr, shape, names, debuglog)
arr, shape, names = header_parser.parse_lines(lines, strict=False, gil_release=False)
print_results(arr, shape, names)


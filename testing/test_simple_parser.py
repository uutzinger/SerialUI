from line_parsers import simple_parser

def print_results(arr, shape, names):
    print("  array shape property:", arr.shape)
    print("  returned shape tuple:", shape)
    print("  variable names dict:", names)
    print("  array:\n", arr)
    print()

lines = [
    "1 2 3, 4 5 6, 7 8 9, 10 11 12",
    "10 20 30, 40, 50 60",
    "7 8 9",
    "101, 102, 103",
    "104, 105, 106",
    "107, 108, 109",
    "80 81 82,90 91 92, 93 94 95"
]

"""
Should result into:

=== Test: simple parsing ===
  array shape property: (15, 4)
  returned shape tuple: [15, 4]
  variable names dict: ['1', '2', '3', '4']
  array:
 [[  1.   4.   7.  10.]
 [  2.   5.   8.  11.]
 [  3.   6.   9.  12.]
 [ 10.  40.  50.  nan]
 [ 20.  nan  60.  nan]
 [ 30.  nan  nan  nan]
 [  7.  nan  nan  nan]
 [  8.  nan  nan  nan]
 [  9.  nan  nan  nan]
 [101. 102. 103.  nan]
 [104. 105. 106.  nan]
 [107. 108. 109.  nan]
 [ 80.  90.  93.  nan]
 [ 81.  91.  94.  nan]
 [ 82.  92.  95.  nan]]
"""

print("=== Test: simple parsing ===")
arr, shape, names = simple_parser.parse_lines(lines)
print_results(arr, shape, names)

print("=== Test: simple parsing with input channel_names as list, one missing ===")
arr, shape, names = simple_parser.parse_lines(lines, channel_names=['1', '2', '3'])
print_results(arr, shape, names)

print("=== Test: simple parsing with input channel_names as dict, one missing===")
arr, shape, names = simple_parser.parse_lines(lines, channel_names={'1':0, '2':1, '3':2})
print_results(arr, shape, names)

print("=== Test: simple parsing with input channel_names as dict, one missing===")
arr, shape, names = simple_parser.parse_lines(lines, channel_names={'one':0, 'two':1, 'three':2})
print_results(arr, shape, names)

print("=== Test: simple parsing with GIL released ===")
arr, shape, names = simple_parser.parse_lines(lines, gil_release=True)
print_results(arr, shape, names)

print("=== Test: simple parsing with strict ===")
arr, shape, names = simple_parser.parse_lines(lines, strict=True)
print_results(arr, shape, names)

# Broken lines
lines = [
    "   ",
    "",
    "1, 2, 3   4 5",
    "",
    "  5, 6, 7",
    "abc def",
    "   ",
    ",1 2 3,,2 3 4, 1 3 4,",
    "  , ,  ",
    " , , , , "
]

"""
Should result into:

=== Test: simple parsing with 'broken' tokes ===
  array shape property: (15, 6)
  returned shape tuple: [15, 6]
  variable names dict: ['1', '2', '3', '4', '5', '6']
  array:
 [[nan nan nan nan nan nan]
 [nan nan nan nan nan nan]
 [ 1.  2.  3. nan nan nan]
 [nan nan  4. nan nan nan]
 [nan nan  5. nan nan nan]
 [nan nan nan nan nan nan]
 [ 5.  6.  7. nan nan nan]
 [nan nan nan nan nan nan]
 [nan nan nan nan nan nan]
 [nan nan nan nan nan nan]
 [nan  1. nan  2.  1. nan]
 [nan  2. nan  3.  3. nan]
 [nan  3. nan  4.  4. nan]
 [nan nan nan nan nan nan]
 [nan nan nan nan nan nan]]
"""

# non‐strict (default)
print("=== Test: simple parsing with 'broken' tokes ===")
arr, shape, names = simple_parser.parse_lines(lines)
print_results(arr, shape, names)

# strict mode
try:
    simple_parser.parse_lines(lines, strict=True)
except ValueError as e:
    print("Caught parse error:", e)

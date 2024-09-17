import re

def split_labeled_data(input_string):
    # Regular expression to split before a word followed by a colon (lookahead)
    # The pattern ensures it only splits where there is a label ahead
    segments = re.split(r'\s+(?=\w+:)', input_string)

    return segments

# Example data strings
input_strings = [
    'Accel: 0.23 0.01 0.45, T1: 35.5',
    'Accel: 0.23 0.01 0.45 T1: 35.5'
]

for input_string in input_strings:
    result = split_labeled_data(input_string)
    print("Input:", input_string)
    print("Segments:", result)
    print()

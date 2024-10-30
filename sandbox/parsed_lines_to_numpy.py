import re
from collections import Counter, defaultdict
import numpy as np

# Regex to find labels and associated data
# labeled_data_re = re.compile(r'\s+(?=\w+:)')
labeled_data_re = re.compile(r'(?<=\s)(?=\w+:)')  # Lookahead for a label start after a space
# Regex to split labeld data into label and data
label_data_re = re.compile(r'(\w+):\s*(.+)')
# Regex to split on commas or semicolons for possible scalar separation
vector_scalar_re = re.compile(r'[;,]\s*')

def parse_lines(lines):

    if isinstance(lines, str):
        lines = [lines]  # Make it a list if it's a single string

    data_structure = []

    for line in lines:
        # First, extract potential labeled parts
        segments = labeled_data_re.split(line)
        scalar_count = 0
        vector_count = 0

        for segment in segments:
            if not segment:
                continue
            match = label_data_re.match(segment)
            if match:
                # labled data
                label, data = match.groups()
                data_elements = vector_scalar_re.split(data)
            else:
                # unlabeled data
                data_elements = vector_scalar_re.split(segment)
                label = None

            for data in data_elements:
                try:
                    numbers = list(map(float, data.split()))
                except ValueError:
                    continue  # Skip entries that cannot be converted to float
                
                if not numbers:
                    continue  # Skip empty data elements

                if label:
                    header = f"{label}"
                elif len(numbers) == 1:
                    scalar_count += 1
                    header = f"S{scalar_count}"
                else:
                    vector_count += 1
                    header = f"V{vector_count}"

                data_structure.append({'header': header, 'values': numbers, 'length': len(numbers)})

    return data_structure

# Example lines
lines = [
    "Accel: 0.23 0.01 0.45, T1: 35.5",
    "Accel: 0.23 0.01 0.45 T1: 35.5",
    "Accel:\t0.23\t0.01\t0.45\tT1:\t35.5",
    "0.23 0.01 0.45, 35.5",
]

# 1) Parsing the lines to data

parsed_results = parse_lines(lines)

# 2) Padding the data

# Determine the maximum number of data entries for each header
header_analysis = defaultdict(lambda: {'count': 0, 'max_length': 0})
for entry in parsed_results:
    header = entry['header']
    length = len(entry['values'])
    header_analysis[header]['count'] += 1
    header_analysis[header]['max_length'] = max(header_analysis[header]['max_length'], length)

# Find the maximum occurrence of any header
max_header_occurrence = max(details['count'] for details in header_analysis.values())

# Pad the data to ensure all data the same length for each header
padded_parsed_results = []

for header, details in header_analysis.items():
    # Existing entries for each header
    existing_entries = [entry for entry in parsed_results if entry['header'] == header]
    for entry in existing_entries:
        max_length = details['max_length']
        padded_values = entry['values'] + [float('-inf')] * (max_length - len(entry['values']))
        padded_parsed_results.append({'header': header, 'values': padded_values, 'length': max_length})

    # Padding for headers to match max occurrence
    padding_count = max_header_occurrence - details['count']
    max_length = details['max_length']
    padding_entry = {'header': header, 'values': [float('-inf')] * max_length, 'length': max_length}
    padded_parsed_results.extend([padding_entry] * padding_count)
    
# Output results for demonstration
for entry in padded_parsed_results:
    print(f"Header: {entry['header']}, Values: {entry['values']}, Length: {entry['length']}")

# 3) Conversion to numpy array

# Convert the parsed data to a numpy array and corresponding headers

sample_number = 0 
data_array_list = []
headers = []

# Create numpy data array for each header
for header, details in header_analysis.items():
    entries = [entry for entry in padded_parsed_results if entry['header'] == header]
    num_cols = details['max_length']

    # Prepare data for stacking
    data = np.array([entry['values'] for entry in entries], dtype=float)
    data_array_list.append(data)

    # Stack headers
    if num_cols > 1:
        header_labels = [f"{header}_{i+1}" for i in range(num_cols)]
        headers.extend(header_labels)
    else:
        headers.append(header)  

# Stack horizontally
if data_array_list:
    # Stack arrays
    data_array = np.hstack(data_array_list)

    # Add sample numbers as first column
    data_array_shape = data_array.shape
    if len(data_array_shape) == 2:
        num_rows, num_cols = data_array_shape
        sample_numbers = np.arange(sample_number, sample_number + num_rows).reshape(-1, 1)
        sample_number += num_rows

        data_array = np.hstack([sample_numbers, data_array])

# Show results
print()
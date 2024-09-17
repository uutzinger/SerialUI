import re

# Regex to find labels and associated data
labeled_data_re = re.compile(r'\s+(?=\w+:)')
# Regex to split labeld data into label and data
label_data_re = re.compile(r'(\w+):\s*(.+)')
# Regex to split on commas or semicolons for possible scalar separation
vector_scalar_re = re.compile(r'[;,]\s*')

def parse_sensor_data(lines):

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
    "Accel: 0.23, 0.01, 0.45, T1: 35.5",
    "0.23 0.01 0.45, 35.5",  # Unlabeled, mixed vector and scalar
    "0.23, 0.01, 0.45, 35.5",  # Unlabeled, treated as scalars
    "0.23 0.01 0.45"  # Unlabeled, treated as vector
]

for line in lines: 
    parsed_results = parse_sensor_data(line)
    for result in parsed_results:
        print("Legends:", result['header'])
        print("Data:", result['values'])
        print("Length:", result['length'])
    print()

# Legends: Accel
# Data: [0.23, 0.01, 0.45]
# Length: 3

# Legends: T1
# Data: [35.5]
# Length: 1

# Legends: Accel
# Data: [0.23, 0.01, 0.45]
# Length: 3

# Legends: T1
# Data: [35.5]
# Length: 1

# Legends: Accel
# Data: [0.23]
# Length: 1

# Legends: Accel
# Data: [0.01]
# Length: 1

# Legends: Accel
# Data: [0.45]
# Length: 1

# Legends: T1
# Data: [35.5]
# Length: 1

# Legends: V1
# Data: [0.23, 0.01, 0.45]
# Length: 3

# Legends: S1
# Data: [35.5]
# Length: 1

# Legends: S1
# Data: [0.23]
# Length: 1

# Legends: S2
# Data: [0.01]
# Length: 1

# Legends: S3
# Data: [0.45]
# Length: 1

# Legends: S4
# Data: [35.5]
# Length: 1

# Legends: V1
# Data: [0.23, 0.01, 0.45]
# Length: 3
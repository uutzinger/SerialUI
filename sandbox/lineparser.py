import re

def parse_sensor_data(lines):

    data_structure = []

    # Regex to find labels and associated data
    labeled_data_re = re.compile(r'\s+(?=\w+:)')
    # Regex to split labeld data into label and data
    label_data_re = re.compile(r'(\w+):\s*(.+)')
    # Regex to split on commas or semicolons for possible scalar separation
    vector_scalar_re = re.compile(r'[;,]\s*')

    for line in lines:
        # First, extract potential labeled parts
        segments = re.split(r'\s+(?=\w+:)', line)

        if segments:
            scalar_count = 0
            vector_count = 0
            for segment in segments:
                match = re.match(r'(\w+):\s*(.+)', segment)
                if match:
                    # labled data
                    label = match.group(1)
                    data = match.group(2)
                    # separate vectors and scalars
                    data_elements = re.split(r'[;,]\s*',data)
                    for data in data_elements:
                        numbers = list(map(float, data.split()))
                        if numbers:
                            header = f"{label}"
                            data_structure.append({'header': header, 'values': numbers, 'length': len(numbers)})    
                else:
                    # unlabeled data
                    data_elements = re.split(r'[;,]\s*',segment)
                    for data in data_elements:
                        numbers = list(map(float, data.split()))
                        if numbers:
                            if len(numbers) == 1:
                                # scalar
                                scalar_count += 1
                                header = f"S{scalar_count}"
                                data_structure.append({'header': header, 'values': numbers, 'length': len(numbers)})    
                            if len(numbers) > 1:
                                # vector (two or more elements)
                                vector_count += 1
                                header = f"V{vector_count}"
                                data_structure.append({'header': header, 'values': numbers, 'length': len(numbers)})    
        else:
            pass

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

parsed_results = parse_sensor_data(lines)
for result in parsed_results:
    print("Legends:", result['header'])
    print("Data:", result['values'])
    print("Length:", result['length'])
    print()

import numpy as np
from typing import List, Tuple
import re

vector_scalar_re = re.compile(r'[;,]\s*')

def parse_lines_simple(lines: List[bytes]) -> Tuple[List[np.ndarray], List[str]]:
    """
    Parses a list of byte strings into separate numpy arrays for each scalar or vector.
    Assumes that vectors are numbers separated by spaces or tabs, and different vectors/scalars
    are separated by commas or semicolons. Assumes each line has the same format.

    Args:
    lines (List[bytes]): List of byte strings to parse.

    Returns:
    Tuple[List[np.ndarray], List[str]]: A tuple containing:
        - A list of numpy arrays, each representing a column of scalars or vectors.
        - A list of headers indicating whether each column is a scalar (S1, S2, ...) or vector (V1, V2, ...).
    """

    vector_count = 0
    scalar_count = 0

    component_lists = []  # List of lists, each sub-list will be converted to a numpy array
    headers = []  # List to hold headers
    initialized = False  #

    for line in lines:
        # Decode the line from bytes to string
        decoded_line = line.decode('utf-8')

        # Split into major components (scalars or vector groups)
        components = vector_scalar_re.split(decoded_line)
        num_components = len(components)

        if not initialized:
            # Initialize lists for each component
            for idx in range(num_components):
                component_lists.append([])
                # Check if the component is a scalar or vector
                values = components[idx].strip().split()
                if len(values) == 1:
                    headers.append(f"S{len([h for h in headers if 'S' in h]) + 1}")
                else:
                    headers.append(f"V{len([h for h in headers if 'V' in h]) + 1}")
            initialized = True

        for idx, component in enumerate(components):
            # Split potential vectors by whitespace and convert to float
            values = [float(value) for value in component.strip().split() if value]
            component_lists[idx].append(values)

    # Convert each component list to a numpy array
    data_array_list = [np.array(component) for component in component_lists]

    return data_array_list, headers

# Example usage:
lines = [
    b'1.0 2.0 3.0, 4.0; 5.0 6.0',
    b'7.0 8.0 9.0, 10.0; 11.0 12.0'
]
data_arrays, headers = parse_lines_simple(lines)
print("Headers:", headers)
for array in data_arrays:
    print(array)
import timeit
import re

vector_scalar_re = re.compile(r'[;,]\s*')

# Your function that uses basic string operations
def split_on_commas_and_semicolons(text):
    parts = []
    for segment in text.split(';'):
        parts.extend([subpart.strip() for subpart in segment.split(',') if subpart.strip()])
    return parts

def optimized_split_on_commas_and_semicolons(text):
    # Using a single list comprehension to handle splitting and stripping
    return [subpart.strip() for segment in text.split(';') for subpart in segment.split(',') if subpart.strip()]

# The regex approach
def regex_split(text):
    return vector_scalar_re.split(text)

# Test input string
text = "value1, value2 ; value3 , value4;  value5 value6 value7"

# Using timeit to measure performance
manual_split_time = timeit.timeit('split_on_commas_and_semicolons(text)', globals=globals(), number=10000)
manual_split_time_optimized = timeit.timeit('optimized_split_on_commas_and_semicolons(text)', globals=globals(), number=10000)
regex_split_time = timeit.timeit('regex_split(text)', globals=globals(), number=10000)

print(f"Manual Split Time: {manual_split_time}")
print(f"Optimized Manual Split Time: {manual_split_time_optimized}")
print(f"Regex Split Time: {regex_split_time}")

result = split_on_commas_and_semicolons(text)
print(result)

result = optimized_split_on_commas_and_semicolons(text)
print(result)

elements = vector_scalar_re.split(text)
print(elements)

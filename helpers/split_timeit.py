import timeit
import re

# Setup for regex
regex_setup = """
import re
pattern = re.compile(r'\\s+')
text = '  this   is  an   example  '
"""
regex_time = timeit.timeit("pattern.split(text)", setup=regex_setup, number=10000)

# Setup for split
split_setup = """
text = '  this   is  an   example  '
"""
split_time = timeit.timeit("text.split()", setup=split_setup, number=10000)

print(f"Regex split time: {regex_time}")
print(f"Simple split time: {split_time}")
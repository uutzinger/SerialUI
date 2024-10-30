import serial.tools.list_ports as list_ports
import timeit

# Define the code to be timed
code_to_time = """
list_ports.comports()
"""

# Use timeit.timeit to measure the execution time
scan_time = timeit.timeit(code_to_time, globals=globals(), number=1000)

print(f"Serial ports scan time: {scan_time/1000.} seconds")
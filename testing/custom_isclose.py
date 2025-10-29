import time
from math import isclose
def changed(a, b, rel_tol=1e-9, abs_tol=0):
    if a is None or b is None:
        return True
    return abs(a - b) > max(abs_tol, rel_tol * max(abs(a), abs(b)))

tic = time.perf_counter()
for i in range(1000000):
    _ = changed(1.0, 1.0 + 1e-7, rel_tol=1e-9, abs_tol=0)
toc = time.perf_counter()
print(f"Time for 1000000 changed() calls: {toc - tic:.6f} seconds")

for i in range(1000000):
    _ = changed(1.0, 1.0 + 1e-7)
toc = time.perf_counter()
print(f"Time for 1000000 changed() calls: {toc - tic:.6f} seconds")

tic = time.perf_counter()
for i in range(1000000):
    _= not isclose(1.0, 1.0 + 1e-7, rel_tol=1e-9, abs_tol=0)
toc = time.perf_counter()
print(f"Time for 1000000 isclose() calls: {toc - tic:.6f} seconds")

tic = time.perf_counter()
for i in range(1000000):
    _= not isclose(1.0, 1.0 + 1e-7)
toc = time.perf_counter()
print(f"Time for 1000000 isclose() calls: {toc - tic:.6f} seconds")

tic = time.perf_counter()
for i in range(1000000):
    _ = 1.0 != 1.0 + 1e-7
toc = time.perf_counter()
print(f"Time for 1000000 inequality calls: {toc - tic:.6f} seconds")
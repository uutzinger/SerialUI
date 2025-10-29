# This script sets up the line_parsers Python package using setuptools.
# Use:
#   - `python setup.py build_ext --inplace -v`
#   - `pip install -e .`

from setuptools import setup, Extension, find_packages
import pybind11
import numpy
import os

DEBUG = False                                                                  # Set to True for debugging flags, False for production flags
BUILD_PROFILE = False                                                          # Set to True to generate profiling data, then include it with -fprofile-use in follow up build

this_dir = os.path.dirname(__file__)

if BUILD_PROFILE:
    # Build with profiling enabled
    extra_compile_args = [
        #'-Ofast',                  # aggressive optimizations (may break strict standards compliance)  
        '-O3',
        '-march=native',
        '-mtune=native',
        '-std=c++17',
        '-fprofile-generate',                                                  # ← instrument for PGO data collection
        '-fstrict-aliasing',
        '-funroll-loops',
        '-DNDEBUG',
    ]
    extra_link_args = [
        # no -flto or -fprofile-use on this first build
        '-fprofile-generate',                                                  # ⟵ include libgcov in the .so
    ]

elif DEBUG:
    # Debug build with ASan + UBSan
    extra_compile_args = [
        '-g',
        '-O0',
        '-fno-omit-frame-pointer',
        '-fsanitize=address',
        '-fsanitize=undefined',
        '-std=gnu++17',
        '-Wall',
        '-Wextra',
        '-Wpedantic',
    ]
    extra_link_args = [
        '-fsanitize=address',
        '-fsanitize=undefined',
        '-static-libasan', 
    ]

else:
    # Production compile flags
    extra_compile_args = [
        '-Ofast',                                                              # aggressive optimizations (may break strict standards compliance)  
        #'-O3',                     # high optimization level
        '-march=native',                                                       # compile for the current CPU architecture
        '-mtune=native',                                                       # tune for your exact CPU
        '-std=c++17',                                                          # your chosen C++ standard
        '-flto',                                                               # link-time optimization
        # '-fprofile-use',           # use profiling data to optimize code

        # code-generation tweaks
        # '-fvisibility=hidden',     # hide all symbols by default (smaller .so, faster load)
        '-fstrict-aliasing',                                                   # enable strict aliasing (better vectorization)
        '-funroll-loops',                                                      # unroll small loops automatically
        #'-fomit-frame-pointer',    # free up a register on x86(-64), might impact profilers, backtraces, and debuggers
        #'-ffast-math',             # *very* aggressive FP optimizations (breaks IEEE compliance), implied in -Ofast
        #'-ffunction-sections',     # place each function in its own section (better dead code elimination)
        #'-fdata-sections',         # place each data item in its own section (better dead code elimination)
        #'-fno-exceptions',         # disable exceptions (smaller binary, faster code)  
        #'-fno-rtti',               # disable RTTI (smaller binary, faster code)
        '-finline-limit=1000',                                                 # increase the inlining limit (more aggressive inlining)
        
        # warning-and-safety
        #'-Wall',                   # all the “obvious” warnings
        #'-Wextra',                 # more pedantic warnings
        #'-Wpedantic',              # enforce standard conformance
        #'-Wconversion',            # warn on implicit type conversions
        #'-Wsign-conversion',       # warn on signed<->unsigned conversions

        # disable C++ features you don’t need (smaller binary)
        # '-fno-exceptions',       # remove exception support
        # '-fno-rtti',             # remove RTTI/dynamic_cast support

        # define NDEBUG to strip out any assert() checks
        '-DNDEBUG',
    ]
    extra_link_args = [
        '-flto=4',                                                             # link-time optimization
        # '-Wl,--gc-sections',       # remove unused sections (dead code elimination)
        # '-s',                      # strip all symbols
    ]

common = dict(
    include_dirs=[
        pybind11.get_include(), 
        numpy.get_include(),
        os.path.join(this_dir, "line_parsers"),  
    ],
    language="c++",
    extra_compile_args=extra_compile_args,
    extra_link_args=extra_link_args,
)

simple_ext = Extension(
    'line_parsers.simple_parser',
    sources=[
        'line_parsers/simple_parser.cpp',
    ],
    **common
)
header_ext = Extension(
    'line_parsers.header_parser',
    sources=[
        'line_parsers/header_parser.cpp',
    ],
    **common
)

setup(
    name='line_parsers',
    version='1.5',
    packages=find_packages(),                                                  # finds line_parsers
    ext_modules=[simple_ext, header_ext],
    install_requires=['pybind11>=2.6.0','numpy'],
)
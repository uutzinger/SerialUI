#!/bin/bash
# This script runs the main_window.py Python script for the SerialUI application
# and redirects its output (both stdout and stderr) to a log file.

# Execute the main_window.py script using Python 3
# Redirect standard output (stdout) and standard error (stderr) to SerialUI.log
python3 /path/to/your/SerialUI/main_window.py > /path/to/your/SerialUI/SerialUI.log 2>&1

# python3 /home/uutzinger/Documents/GitHub/SerialUI/main_window.py > /home/uutzinger/Documents/GitHub/SerialUI/SerialUI.log 2>&1
# This script sets up the SerialUI application on a Linux or Unix system 
# by copying its desktop entry file, making necessary scripts executable, 
# and updating the desktop database.

# Copy the SerialUI.desktop file to the local user's applications directory
cp SerialUI.desktop ~/.local/share/applications/

# Make the SerialUI.desktop file executable
chmod +x ~/.local/share/applications/SerialUI.desktop

# Make the run.sh script executable
chmod +x run.sh

# Make the main_window.py script executable
chmod +x main_window.py

# Update the desktop database to include the new .desktop file
update-desktop-database ~/.local/share/applications/

#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Dynamically determine the script and parent directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")"
PYTHON_SETUP_SCRIPT="$SCRIPT_DIR/setup_environment.py"

# Ensure Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed. Installing Python 3..."
    sudo apt update
    sudo apt install -y python3
else
    echo "Python 3 is already installed."
fi

# Ensure python3-venv is installed
if ! dpkg -l | grep -q python3-venv; then
    echo "Installing python3-venv..."
    sudo apt update
    sudo apt install -y python3-venv
else
    echo "python3-venv is already installed."
fi

# Ensure DCMTK is installed (system-level dependency)
if ! command -v storescu &> /dev/null; then
    echo "Installing DCMTK..."
    sudo apt update
    sudo apt install -y dcmtk
else
    echo "DCMTK is already installed."
fi

# Run the Python setup script to handle the virtual environment and Python dependencies
if [ -f "$PYTHON_SETUP_SCRIPT" ]; then
    echo "Running Python setup script..."
    python3 "$PYTHON_SETUP_SCRIPT"
else
    echo "ERROR: Python setup script not found: $PYTHON_SETUP_SCRIPT"
    exit 1
fi

echo "Setup complete!"
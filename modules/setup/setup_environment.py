import os
import sys
import subprocess

def setup_virtualenv():
    # Dynamically determine the parent directory
    parent_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # Parent directory of IsalaOCR
    venv_path = os.path.join(os.path.dirname(parent_path), "venv")  # Virtual environment in the parent directory

    # Create the virtual environment if it doesn't exist
    if not os.path.exists(venv_path):
        print(f"Creating virtual environment at: {venv_path}")
        subprocess.run([sys.executable, "-m", "venv", venv_path], check=True)
    else:
        print(f"Virtual environment already exists at: {venv_path}")

    # Ensure pip is installed in the virtual environment
    python_path = os.path.join(venv_path, "Scripts" if os.name == "nt" else "bin", "python")
    pip_path = os.path.join(venv_path, "Scripts" if os.name == "nt" else "bin", "pip")
    if not os.path.exists(pip_path):
        print("Pip is missing in the virtual environment. Installing pip...")
        subprocess.run([python_path, "-m", "ensurepip", "--upgrade"], check=True)
        subprocess.run([python_path, "-m", "pip", "install", "--upgrade", "pip"], check=True)

    return venv_path

def install_requirements(venv_path):
    # Determine paths for pip and requirements.txt
    pip_path = os.path.join(venv_path, "Scripts" if os.name == "nt" else "bin", "pip")
    requirements_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")

    # Upgrade pip
    print("Upgrading pip...")
    subprocess.run([pip_path, "install", "--upgrade", "pip"], check=True)

    # Install requirements
    if os.path.exists(requirements_path):
        print(f"Installing required Python packages from {requirements_path}...")
        subprocess.run([pip_path, "install", "-r", requirements_path], check=True)
    else:
        print(f"ERROR: Requirements file not found: {requirements_path}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        # Set up the virtual environment
        venv_path = setup_virtualenv()

        # Install Python requirements
        install_requirements(venv_path)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Command failed with return code {e.returncode}: {e.cmd}")
        sys.exit(1)
import subprocess
import sys
import os

def setup_virtualenv():
    # Dynamisch het pad naar de bovenliggende map bepalen
    parent_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # Map boven IsalaOCR
    venv_path = os.path.join(os.path.dirname(parent_path), "venv")  # Virtuele omgeving in de map boven IsalaOCR
    if not os.path.exists(venv_path):
        print(f"Het aanmaken van de virtuele omgeving: {venv_path}")
        subprocess.run([sys.executable, "-m", "venv", venv_path])

def install_requirements():
    # Dynamisch het pad naar de bovenliggende map bepalen
    parent_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # Map boven IsalaOCR
    venv_path = os.path.join(os.path.dirname(parent_path), "venv")  # Virtuele omgeving in de map boven IsalaOCR
    pip_path = os.path.join(venv_path, "Scripts" if os.name == "nt" else "bin", "pip")
    requirements_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")  # Pad naar requirements.txt in modules/setup/
    print("Installeren van vereiste packages...")
    subprocess.run([pip_path, "install", "--upgrade", "pip"])
    if os.path.exists(requirements_path):
        subprocess.run([pip_path, "install", "-r", requirements_path])
    else:
        print(f"ERROR: Requirements-bestand niet gevonden: {requirements_path}")

if __name__ == "__main__":
    # Setup de virtuele omgeving
    setup_virtualenv()

    # Installeer vereisten
    install_requirements()
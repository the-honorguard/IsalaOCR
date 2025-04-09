import subprocess
import sys
import os

def setup_virtualenv():
    venv_path = "venv"
    if not os.path.exists(venv_path):
        print(f"Het aanmaken van de virtuele omgeving: {venv_path}")
        subprocess.run([sys.executable, "-m", "venv", venv_path])

def install_requirements():
    print("Installeren van vereiste packages...")
    subprocess.run([os.path.join("venv", "bin", "pip"), "install", "--upgrade", "pip"])
    subprocess.run([os.path.join("venv", "bin", "pip"), "install", "-r", "requirements.txt"])

def run_ocr_script():
    print("Runocr.py wordt uitgevoerd...")
    subprocess.run([os.path.join("venv", "bin", "python"), "runocr.py"])

if __name__ == "__main__":
    # Setup de virtuele omgeving
    setup_virtualenv()

    # Installeer vereisten
    install_requirements()

    # Voer het OCR-script uit
    #run_ocr_script()

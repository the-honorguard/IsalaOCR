import sys
import os
from datetime import datetime
import configparser
from dicomdumper import process_dicom_directory
from dcm2jpg import process_dicom_folder
import subprocess

# Dynamisch de hoofdmap bepalen
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Pad naar het logbestand
LOGFILE = os.path.join(BASE_DIR, "logs/run_logs.txt")

def log_message(message):
    """
    Log een bericht naar zowel de terminal als het logbestand.
    """
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{current_time}] {message}"
    print(log_entry)
    with open(LOGFILE, 'a') as log:
        log.write(log_entry + "\n")

# Laad de configuratie uit config.ini
CONFIG_PATH = os.path.join(BASE_DIR, "config/mainconfig.ini")
config = configparser.ConfigParser()
config.read(CONFIG_PATH)

# Haal de paden op uit de configuratie en converteer naar absolute paden
DCM_IN_FOLDER = os.path.join(BASE_DIR, config['paths']['dcm_in_folder'])
DICOMDUMPER_OUTPUT_FOLDER = os.path.join(BASE_DIR, config['paths']['dicomdumper_output_folder'])
IMAGE_FOLDER = os.path.join(BASE_DIR, config['paths']['jpg_out_folder'])

def process_file_with_run_script(file_path):
    """
    Voer het run.py script uit om het bestand te verwerken.
    """
    try:
        absolute_file_path = os.path.abspath(file_path)  # Zet het bestandspad om naar een absoluut pad
        print(f"Start run.py voor bestand: {absolute_file_path}")
        subprocess.run([sys.executable, RUN_SCRIPT, absolute_file_path], check=True)
        print(f"run.py succesvol uitgevoerd voor bestand: {absolute_file_path}")
    except subprocess.CalledProcessError as e:
        print(f"Fout bij uitvoeren van run.py: {e}")
    except Exception as e:
        print(f"Onverwachte fout bij uitvoeren van run.py: {e}")

def main():
    """
    Hoofdfunctie die de workflow uitvoert.
    """
    # Zorg ervoor dat de logmap en het logbestand bestaan
    log_dir = os.path.dirname(LOGFILE)
    os.makedirs(log_dir, exist_ok=True)
    with open(LOGFILE, 'w') as log:
        log.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Logbestand aangemaakt.\n")

    log_message("Script gestart.")

    # Log de gebruikte Python-interpreter (optioneel)
    print(f"✅ Gebruikte Python-interpreter: {sys.executable}")

    # Controleer of de inputmap bestaat
    if not os.path.isdir(DCM_IN_FOLDER):
        log_message(f"❌ Input pad is geen geldige map: {DCM_IN_FOLDER}")
        sys.exit(1)

    # Verwerk de map met dicomdumper.py
    try:
        log_message("Start dicomdumper...")
        process_dicom_directory(DCM_IN_FOLDER, DICOMDUMPER_OUTPUT_FOLDER)
        log_message("dicomdumper gestopt.")
    except Exception as e:
        log_message(f"Fout bij uitvoeren van dicomdumper: {e}")

    # Verwerk de map met dcm2jpg.py
    try:
        log_message("Start dcm2jpg...")
        process_dicom_folder(DCM_IN_FOLDER, IMAGE_FOLDER)
        log_message("dcm2jpg gestopt.")
    except Exception as e:
        log_message(f"Fout bij uitvoeren van dcm2jpg: {e}")

    log_message("Script geëindigd.")

if __name__ == "__main__":
    main()
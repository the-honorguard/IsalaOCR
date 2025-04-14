import sys
import os
from datetime import datetime
import configparser
from dicomdumper import process_dicom_directory
from dcm2jpg import process_dicom_folder

# Pad naar het logbestand
LOGFILE = "/home/isala/ocr/IsalaOCR/logs/run_logs.txt"

def log_message(message):
    """
    Log een bericht naar zowel de terminal als het logbestand.
    """
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{current_time}] {message}"
    print(log_entry)  # Print naar de terminal
    with open(LOGFILE, 'a') as log:
        log.write(log_entry + "\n")  # Schrijf naar het logbestand

# Laad de configuratie uit config.ini
CONFIG_PATH = "/home/isala/ocr/IsalaOCR/config/mainconfig.ini"
config = configparser.ConfigParser()
config.read(CONFIG_PATH)

# Haal de paden op uit de configuratie
DCM_IN_FOLDER = config['paths']['dcm_in_folder']
DICOMDUMPER_OUTPUT_FOLDER = config['paths']['dicomdumper_output_folder']
IMAGE_FOLDER = config['paths']['jpg_out_folder']  # Gebruik de juiste sleutel

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
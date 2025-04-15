import os
from datetime import datetime
import configparser
from dicomdumper import process_dicom_directory
from dcm2jpg import process_dicom_folder

# Dynamisch de hoofdmap bepalen
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Pad naar het logbestand
LOGFILE = os.path.join(BASE_DIR, "logs/run_logs.txt")

def log_message(message):
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{current_time}] {message}"
    print(log_entry)
    with open(LOGFILE, 'a') as log:
        log.write(log_entry + "\n")

# Laad de configuratie uit config.ini
CONFIG_PATH = os.path.join(BASE_DIR, "config/mainconfig.ini")
config = configparser.ConfigParser()
config.read(CONFIG_PATH)

DCM_IN_FOLDER = os.path.join(BASE_DIR, config['paths']['dcm_in_folder'])
DICOMDUMPER_OUTPUT_FOLDER = os.path.join(BASE_DIR, config['paths']['dicomdumper_output_folder'])
IMAGE_FOLDER = os.path.join(BASE_DIR, config['paths']['jpg_out_folder'])

def main():
    os.makedirs(os.path.dirname(LOGFILE), exist_ok=True)
    with open(LOGFILE, 'w') as log:
        log.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Logbestand aangemaakt.\n")

    log_message("Script gestart.")

    if not os.path.isdir(DCM_IN_FOLDER):
        log_message(f"❌ Input pad is geen geldige map: {DCM_IN_FOLDER}")
        return

    try:
        log_message("Start dicomdumper...")
        process_dicom_directory(DCM_IN_FOLDER, DICOMDUMPER_OUTPUT_FOLDER)
        log_message("dicomdumper gestopt.")
    except Exception as e:
        log_message(f"Fout bij dicomdumper: {e}")

    try:
        log_message("Start dcm2jpg...")
        process_dicom_folder(DCM_IN_FOLDER, IMAGE_FOLDER)
        log_message("dcm2jpg gestopt.")
    except Exception as e:
        log_message(f"Fout bij dcm2jpg: {e}")

    log_message("Script geëindigd.")

if __name__ == "__main__":
    main()

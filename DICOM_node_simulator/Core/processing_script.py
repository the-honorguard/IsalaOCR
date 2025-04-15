import sys
import os
import subprocess
from datetime import datetime

# Pad naar logbestand en het run-script
LOGFILE = "/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Logfiles/python_script_output.log"
RUN_SCRIPT = "/home/isala/ocr/IsalaOCR/modules/run.py"

# Pad naar virtuele omgeving
VENV_FOLDER = "/home/isala/ocr/venv/"  # Vervang dit pad met het pad naar jouw virtuele omgeving

def log_received_file(file_path):
    current_time = datetime.now().strftime('%a %b %d %H:%M:%S UTC %Y')
    with open(LOGFILE, 'a') as log:
        log.write(f"{current_time} - Bestanden succesvol ontvangen: {file_path}\n")
        log.write(f"{current_time} - Het is je gelukt topper!\n")

def run_additional_script(file_path):
    try:
        # Pad naar de python-interpreter in de virtuele omgeving
        VENV_PYTHON = os.path.join(VENV_FOLDER, "bin", "python3")  # Voor Linux/MacOS
        # VENV_PYTHON = os.path.join(VENV_FOLDER, "Scripts", "python.exe")  # Voor Windows

        # Voer het script uit binnen de virtuele omgeving
        result = subprocess.run(
            [VENV_PYTHON, RUN_SCRIPT, file_path],
            capture_output=True,
            text=True,
            check=True
        )
        with open(LOGFILE, 'a') as log:
            log.write(f"{datetime.now()} - run.py uitgevoerd met output:\n{result.stdout}\n")
    except subprocess.CalledProcessError as e:
        with open(LOGFILE, 'a') as log:
            log.write(f"{datetime.now()} - Fout bij uitvoeren van run.py:\n{e.stderr}\n")
    except Exception as e:
        with open(LOGFILE, 'a') as log:
            log.write(f"{datetime.now()} - Onverwachte fout bij uitvoeren van run.py:\n{str(e)}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Geen bestandspad opgegeven.")
        sys.exit(1)

    received_file = sys.argv[1]
    
    if not os.path.isfile(received_file):
        print(f"Het bestand {received_file} bestaat niet.")
        sys.exit(1)

    log_received_file(received_file)

    run_additional_script(received_file)

    print(f"Bestand {received_file} succesvol gelogd.")

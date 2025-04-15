import sys
import os
# import subprocess  ← optioneel: mag je ook tijdelijk uitzetten
from datetime import datetime

LOGFILE = "/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Logfiles/python_script_output.log"
RUN_SCRIPT = "/home/isala/ocr/IsalaOCR/modules/run.py"

def log_received_file(file_path):
    current_time = datetime.now().strftime('%a %b %d %H:%M:%S UTC %Y')
    with open(LOGFILE, 'a') as log:
        log.write(f"{current_time} - Bestanden succesvol ontvangen: {file_path}\n")
        log.write(f"{current_time} - Het is je gelukt topper!\n")

# Deze functie wordt voorlopig niet gebruikt
# def run_additional_script(file_path):
#     try:
#         result = subprocess.run(
#             ["python3", RUN_SCRIPT, file_path],
#             capture_output=True,
#             text=True,
#             check=True
#         )
#         with open(LOGFILE, 'a') as log:
#             log.write(f"{datetime.now()} - run.py uitgevoerd met output:\n{result.stdout}\n")
#     except subprocess.CalledProcessError as e:
#         with open(LOGFILE, 'a') as log:
#             log.write(f"{datetime.now()} - Fout bij uitvoeren van run.py:\n{e.stderr}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Geen bestandspad opgegeven.")
        sys.exit(1)

    received_file = sys.argv[1]
    
    if not os.path.isfile(received_file):
        print(f"Het bestand {received_file} bestaat niet.")
        sys.exit(1)

    log_received_file(received_file)

    # Tijdelijk uitgeschakeld
    # run_additional_script(received_file)

    print(f"Bestand {received_file} succesvol gelogd.")

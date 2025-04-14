import sys
import os
from datetime import datetime
import subprocess

# Dynamisch de hoofdmap bepalen
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))

# Pad naar je logbestand
LOGFILE = os.path.join(BASE_DIR, "DICOM_node_simulator/Logfiles/python_script_output.log")
RUN_SCRIPT = os.path.join(BASE_DIR, "modules/run.py")

def log_received_file(file_path):
    # Haal de huidige tijd op
    current_time = datetime.now().strftime('%a %b %d %H:%M:%S UTC %Y')
    
    # Open het logbestand en voeg een regel toe
    with open(LOGFILE, 'a') as log:
        log.write(f"{current_time} - Bestanden succesvol ontvangen: {file_path}\n")
        log.write(f"{current_time} - Het is je gelukt topper!\n")

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

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Geen bestandspad opgegeven.")
        sys.exit(1)

    # Verkrijg het bestandspad van de eerste commandoregelparameter
    received_file = sys.argv[1]
    
    # Controleer of het bestand bestaat
    if not os.path.isfile(received_file):
        print(f"Het bestand {received_file} bestaat niet.")
        sys.exit(1)

    # Log het ontvangen bestand
    log_received_file(received_file)
    print(f"Bestand {received_file} succesvol gelogd.")

    # Verwerk het bestand met run.py
    process_file_with_run_script(received_file)



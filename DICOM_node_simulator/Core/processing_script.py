import sys
import os
from datetime import datetime

# Pad naar je logbestand (bijgewerkt naar de nieuwe structuur)
LOGFILE = "/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Logfiles/python_script_output.log"

def log_received_file(file_path):
    # Haal de huidige tijd op
    current_time = datetime.now().strftime('%a %b %d %H:%M:%S UTC %Y')
    
    # Open het logbestand en voeg een regel toe
    with open(LOGFILE, 'a') as log:
        log.write(f"{current_time} - Bestanden succesvol ontvangen: {file_path}\n")
        log.write(f"{current_time} - Het is je gelukt topper!\n")  # Extra regel toegevoegd

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

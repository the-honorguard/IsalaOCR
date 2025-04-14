import os
from datetime import datetime

# Pad naar het logbestand
LOGFILE = "/home/isala/ocr/IsalaOCR/logs/run_script.log"

def log_message(message):
    """
    Log een bericht naar het logbestand.
    """
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{current_time}] {message}"
    print(log_entry)  # Optioneel: print het bericht naar de terminal
    with open(LOGFILE, 'a') as log:
        log.write(log_entry + "\n")

if __name__ == "__main__":
    # Controleer of de logmap bestaat, maak deze aan als dat niet zo is
    log_dir = os.path.dirname(LOGFILE)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Log dat het script is gestart
    log_message("run.py is gestart")
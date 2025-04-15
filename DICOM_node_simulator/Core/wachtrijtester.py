import os
import time
import logging
from datetime import datetime

# Pad naar de directories
RECEIVE_DIR = "/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Receive"
QUEUE_DIR = "/home/isala/ocr/IsalaOCR/DICOM_node_simulator/Queue"
LOG_FILE = "/home/isala/ocr/IsalaOCR/DICOM_node_simulator/log.txt"

# Logging instellen
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

def log_status():
    queue_files = os.listdir(QUEUE_DIR)
    receive_files = os.listdir(RECEIVE_DIR)
    
    logging.info(f"Aantal bestanden in wachtrij: {len(queue_files)}")
    logging.info(f"Aantal bestanden in receive map: {len(receive_files)}")

def process_receive_files():
    for filename in os.listdir(RECEIVE_DIR):
        filepath = os.path.join(RECEIVE_DIR, filename)
        if os.path.isfile(filepath):
            logging.info(f"Ontvangen bestand gevonden: {filename} - Wacht 10 seconden...")
            time.sleep(10)
            try:
                os.remove(filepath)
                logging.info(f"Bestand verwijderd na 10 seconden: {filename}")
            except Exception as e:
                logging.error(f"Fout bij verwijderen van bestand {filename}: {e}")

def main():
    logging.info("Start monitoring van Receive en Queue mappen...")
    while True:
        log_status()
        process_receive_files()
        time.sleep(5)

if __name__ == "__main__":
    main()

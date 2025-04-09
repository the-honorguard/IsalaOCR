import os
import time
import subprocess
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class DCMFileHandler(FileSystemEventHandler):
    """
    Event handler voor het detecteren van nieuwe .dcm bestanden.
    """
    def __init__(self, script_to_run):
        self.script_to_run = script_to_run

    def on_created(self, event):
        print(f"on_created aangeroepen voor: {event.src_path}")
        if event.is_directory:
            return
        # Controleer op bestanden die eindigen op .dcm of geen extensie hebben
        if event.src_path.endswith('.dcm') or '.' not in os.path.basename(event.src_path):
            print(f"Nieuw DICOM-bestand gedetecteerd: {event.src_path}")
            self.log_detected_file(event.src_path)
            self.run_script(event.src_path)

    def log_detected_file(self, dcm_file):
        """
        Log het gedetecteerde bestand naar de terminal.
        """
        print(f"Bestand gevonden: {dcm_file}")

    def run_script(self, dcm_file):
        """
        Voer het opgegeven script uit met het gedetecteerde DICOM-bestand als parameter.
        """
        try:
            print(f"Start script: {self.script_to_run} met bestand: {dcm_file}")
            subprocess.run(['python', self.script_to_run, dcm_file], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Fout bij het uitvoeren van het script: {e}")

def start_watchdog(directory_to_watch, script_to_run):
    """
    Start de watchdog om een map te monitoren op nieuwe .dcm bestanden.
    """
    event_handler = DCMFileHandler(script_to_run)
    observer = Observer()
    observer.schedule(event_handler, directory_to_watch, recursive=False)
    observer.start()
    print(f"Watchdog gestart. Monitoring map: {directory_to_watch}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Watchdog gestopt.")
        observer.stop()
    observer.join()

if __name__ == "__main__":
    # Map om te monitoren
    directory_to_watch = '/home/isala/ocr/IsalaOCR/dcm_in'

    # Script dat uitgevoerd moet worden
    script_to_run = '/home/isala/ocr/IsalaOCR/modules/dcm2jpg.py'

    # Start de watchdog
    start_watchdog(directory_to_watch, script_to_run)
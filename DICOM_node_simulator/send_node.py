import os
import time
import subprocess
from pathlib import Path
import threading
import signal
import sys

# Configuratie
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AETITLE_CALLING = "bob_AE"
AETITLE_CALLED = "badpak_AE"
HOST = "127.0.0.1"
PORT = "100"
SENDDIR = os.path.join(SCRIPT_DIR, "Send")
QUEUE_DIR = os.path.join(SCRIPT_DIR, "Queue")
LOGDIR = os.path.join(SCRIPT_DIR, "Logfiles")
LOGFILE = os.path.join(LOGDIR, "send_node.log")
STOPFILE = os.path.join(SCRIPT_DIR, "stop.flag")
PIDFILE = os.path.join(SCRIPT_DIR, "send_node.pid")

# Zorg ervoor dat de benodigde directories bestaan
def ensure_directory(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)
        log_message(f"Map aangemaakt: {directory}")

# Functie om logberichten te schrijven
def log_message(message):
    """Schrijf een logbericht naar zowel de terminal als het logbestand."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] {message}"
    print(formatted_message, flush=True)  # Directe uitvoer naar de terminal
    with open(LOGFILE, "a") as log_file:
        log_file.write(formatted_message + "\n")

# Controleer of een andere instantie draait
def check_existing_instance():
    if os.path.isfile(PIDFILE):
        try:
            with open(PIDFILE, "r") as pid_file:
                pid = int(pid_file.read().strip())
            if pid and os.path.exists(f"/proc/{pid}"):
                log_message(f"Een andere instantie draait al met PID {pid}.")
                sys.exit(1)
        except Exception as e:
            log_message(f"Fout bij het controleren van bestaande instantie: {str(e)}")

    with open(PIDFILE, "w") as pid_file:
        pid_file.write(str(os.getpid()))
    log_message(f"PID-bestand aangemaakt: {PIDFILE} (PID: {os.getpid()})")

# Verwijder het PID-bestand bij afsluiten
def cleanup_pidfile():
    if os.path.isfile(PIDFILE):
        os.remove(PIDFILE)
        log_message(f"PID-bestand verwijderd: {PIDFILE}")

# Controleer of de ontvanger online is
def check_receiver_online():
    log_message(f"Controleer of {HOST}:{PORT} bereikbaar is...")
    try:
        result = subprocess.run(
            ["nc", "-z", "-v", "-w5", HOST, PORT],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode == 0:
            log_message(f"Ontvangende node is online: {HOST}:{PORT}")
            return True
        else:
            log_message(f"Ontvangende node is NIET bereikbaar: {HOST}:{PORT}")
            return False
    except Exception as e:
        log_message(f"Fout bij controle van ontvanger: {str(e)}")
        return False

# Verwerk een bestand uit de wachtrij
def send_file(file_path):
    log_message(f"Probeer bestand te verzenden: {file_path}")
    if check_receiver_online():
        command = [
            "storescu",
            "--aetitle", AETITLE_CALLING,
            "--call", AETITLE_CALLED,
            HOST, str(PORT),
            str(file_path)
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            log_message(f"storescu gestart voor bestand: {file_path}")
            # Lees de uitvoer van het subprocess in realtime
            for line in process.stdout:
                log_message(line.strip())
            process.wait()
            if process.returncode == 0:
                log_message(f"Succesvol verzonden: {file_path}")
                os.remove(file_path)  # Verwijder bestand na succesvol verzenden
            else:
                log_message(f"Fout bij verzenden van {file_path}: {process.stderr.read().strip()}")
        except Exception as e:
            log_message(f"Fout bij het uitvoeren van storescu: {str(e)}")
    else:
        log_message(f"Ontvangende node is niet online. Bestand blijft in wachtrij: {file_path}")

# Verwerk de wachtrij
def process_queue():
    while True:
        # Controleer of stop-bestand aanwezig is
        if os.path.isfile(STOPFILE):
            log_message("STOP-signaalbestand gedetecteerd. Het script stopt.")
            break

        # Verwerk elk bestand in de wachtrij
        for file_path in Path(QUEUE_DIR).glob('*'):
            if file_path.is_file():
                send_file(file_path)

        # Wacht 10 seconden voordat je opnieuw controleert
        log_message("Sendnode is up and running...")  # Realtime logging
        time.sleep(10)

# Monitor de SENDDIR-map en verplaats nieuwe bestanden naar de wachtrij
def monitor_senddir():
    log_message(f"Monitoring map: {SENDDIR}")
    while True:
        if os.path.isfile(STOPFILE):
            log_message("STOP-signaalbestand gedetecteerd. Het script stopt.")
            break

        for file_path in Path(SENDDIR).glob('*'):
            if file_path.is_file():
                destination = os.path.join(QUEUE_DIR, file_path.name)
                os.rename(file_path, destination)
                log_message(f"Nieuw bestand gedetecteerd en verplaatst naar wachtrij: {destination}")
        time.sleep(2)

# Start de wachtrijverwerking
if __name__ == "__main__":
    # Zorg ervoor dat de benodigde directories bestaan
    ensure_directory(LOGDIR)
    ensure_directory(SENDDIR)
    ensure_directory(QUEUE_DIR)

    # Controleer of er al een andere instantie draait
    check_existing_instance()

    # Maak het logbestand leeg of aan als het niet bestaat
    with open(LOGFILE, "w") as log_file:
        log_file.write("")

    log_message(f"Starten van het proces voor het verzenden van DICOM-bestanden (PID: {os.getpid()}).")

    # Start de monitoring en wachtrijverwerking
    try:
        monitor_thread = threading.Thread(target=monitor_senddir, daemon=True)
        monitor_thread.start()
        process_queue()
    except KeyboardInterrupt:
        log_message("Script onderbroken door gebruiker.")
    finally:
        # Verwijder het PID-bestand en het STOP-signaalbestand als het bestaat
        cleanup_pidfile()
        if os.path.isfile(STOPFILE):
            os.remove(STOPFILE)
            log_message("STOP-signaalbestand verwijderd.")

import os
import time
import subprocess
import signal
from pathlib import Path

# Configuratie
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AETITLE_CALLED = "TestSend2"
HOST = "127.0.0.1"
PORT = 2345
QUEUE_DIR = os.path.join(SCRIPT_DIR, "Queue")
LOGDIR = os.path.join(SCRIPT_DIR, "Logfiles")
LOGFILE = os.path.join(LOGDIR, "store_node.log")
PIDFILE = os.path.join(SCRIPT_DIR, "storescp.pid")
STOPFILE = os.path.join(SCRIPT_DIR, "stop.flag")

# Globale variabele voor het storescp-proces
storescp_process = None

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

# Start de DICOM-server
def start_storescp():
    global storescp_process
    log_message(f"Start de DICOM-server op {HOST}:{PORT}...")
    try:
        storescp_process = subprocess.Popen(
            [
                "storescp",
                "--aetitle", AETITLE_CALLED,
                "--output-directory", QUEUE_DIR,
                str(PORT)
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid  # Zorgt voor een nieuwe process group
        )
        # Sla het PID op in een PID-bestand
        with open(PIDFILE, "w") as pid_file:
            pid_file.write(str(storescp_process.pid))
        log_message(f"storescp gestart met PID {storescp_process.pid}.")
    except Exception as e:
        log_message(f"Fout bij het starten van storescp: {str(e)}")

# Stop de DICOM-server
def stop_storescp():
    """Stop het storescp-proces als het actief is."""
    global storescp_process
    if storescp_process and storescp_process.poll() is None:
        log_message(f"Stoppen van storescp PID {storescp_process.pid}...")
        try:
            os.killpg(os.getpgid(storescp_process.pid), signal.SIGTERM)
            storescp_process.wait()
            log_message("storescp is gestopt.")
        except Exception as e:
            log_message(f"Fout bij het stoppen van storescp: {str(e)}")
    if os.path.isfile(PIDFILE):
        os.remove(PIDFILE)
        log_message("PID-bestand verwijderd.")

# Controleer op het STOP-signaalbestand
def monitor_stop_signal():
    """Controleer regelmatig op het STOP-signaalbestand."""
    while True:
        if os.path.isfile(STOPFILE):
            log_message("STOP-signaalbestand gedetecteerd. Stop de node.")
            stop_storescp()
            try:
                os.remove(STOPFILE)
                log_message("STOP-signaalbestand verwijderd.")
            except Exception as e:
                log_message(f"Fout bij het verwijderen van het STOP-signaalbestand: {str(e)}")
            break

        # Log elke 10 seconden dat de node actief is
        log_message("Storenode is up and running...")
        time.sleep(10)

# Start de DICOM-server en monitor het STOP-signaalbestand
if __name__ == "__main__":
    ensure_directory(LOGDIR)
    ensure_directory(QUEUE_DIR)

    # Maak het logbestand leeg of aan als het niet bestaat
    with open(LOGFILE, "w") as log_file:
        log_file.write("")

    log_message("Starten van de DICOM-server en monitoring.")

    try:
        start_storescp()
        monitor_stop_signal()
    except KeyboardInterrupt:
        log_message("Script onderbroken door gebruiker.")
    finally:
        stop_storescp()

import os
import subprocess
from pathlib import Path
import time
import datetime

# Pad naar de configuratie van de monitor
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "modules/DICOM Node tools/Core/config/nodes_config.txt"
LOG_FILE = BASE_DIR / "modules/DICOM Node tools/Core/logging/startup_log.txt"

def log_message(message):
    """Schrijf een logbericht naar het logfile."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{timestamp}] {message}"
    with LOG_FILE.open("a") as log:
        log.write(formatted_message + "\n")
    print(formatted_message)  # Optioneel: ook naar de terminal loggen

def read_config():
    """Lees de configuratie van de nodes uit het configuratiebestand."""
    nodes = []
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("r") as config:
            for line in config:
                try:
                    label, path, status, pid = line.strip().split("|")
                    nodes.append({
                        "label": label,
                        "path": path,
                        "status": status,
                        "pid": pid
                    })
                except ValueError:
                    log_message(f"Fout bij het lezen van configuratieregel: {line.strip()}")
    else:
        log_message(f"Configuratiebestand niet gevonden: {CONFIG_FILE}")
    return nodes

def start_node(node):
    """Start een node als deze niet actief is."""
    script_path = Path(node["path"])
    if not script_path.exists():
        log_message(f"Script niet gevonden voor node: {node['label']}")
        return

    # Controleer of de node al actief is
    pidfile = script_path.parent / ("send_node.pid" if "send_node" in script_path.name else "storescp.pid")
    if pidfile.exists():
        try:
            with pidfile.open("r") as pid_file:
                pid = int(pid_file.read().strip())
            if pid and Path(f"/proc/{pid}").exists():
                log_message(f"Node '{node['label']}' is al actief met PID {pid}.")
                return
        except Exception as e:
            log_message(f"Fout bij het controleren van PID-bestand voor node '{node['label']}': {e}")

    # Start de node
    try:
        process = subprocess.Popen(
            ["python3", str(script_path)],
            stdout=subprocess.DEVNULL,  # Geen uitvoer naar de terminal
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid  # Start in een nieuwe process group
        )
        log_message(f"Node '{node['label']}' gestart met PID {process.pid}.")
    except Exception as e:
        log_message(f"Fout bij het starten van node '{node['label']}': {e}")

def main():
    """Hoofdprogramma om alle nodes te starten."""
    log_message("Starten van services op basis van configuratie...")
    nodes = read_config()
    for node in nodes:
        if node["status"] == "stopped":
            start_node(node)
    log_message("Alle services zijn gestart.")

if __name__ == "__main__":
    main()
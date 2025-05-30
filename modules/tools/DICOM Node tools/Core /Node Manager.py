import sys
import os  # Voeg deze regel toe
import subprocess
import signal
import threading
import datetime
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QListWidget, QFileDialog, QListWidgetItem, QMessageBox, QHBoxLayout,
    QTextEdit, QInputDialog, QLabel, QSpacerItem, QSizePolicy, QFormLayout, QGroupBox, QLineEdit, QComboBox
)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import QTimer, QMetaObject, Q_ARG, QSize


class NodeCreator(QWidget):
    """Node Creator integrated into the Monitor."""
    def __init__(self):
        super().__init__()

        # Set the title of the application
        self.setWindowTitle("DICOM Node Configurator")
        self.setGeometry(100, 100, 500, 400)  # Set the window size

        self.initUI()

    def initUI(self):
        # Main layout
        main_layout = QVBoxLayout()

        # Group connection settings in a QGroupBox for better organization
        connection_group = QGroupBox("Connection Settings")

        # Connection settings
        connection_layout = QFormLayout()
        self.connection_type_combo = QComboBox(self)
        self.connection_type_combo.addItems(["Send", "Store"])
        connection_layout.addRow("Connection Type:", self.connection_type_combo)

        self.ip_input = QLineEdit(self)
        connection_layout.addRow("IP Address:", self.ip_input)

        self.port_input = QLineEdit(self)
        connection_layout.addRow("Port Number:", self.port_input)

        self.local_aet_input = QLineEdit(self)
        connection_layout.addRow("Local AE Title:", self.local_aet_input)

        self.remote_aet_input = QLineEdit(self)
        connection_layout.addRow("Remote AE Title:", self.remote_aet_input)

        connection_group.setLayout(connection_layout)

        # Add sections to the main layout
        main_layout.addWidget(connection_group)

        # Add the "Save as .py" button
        self.save_py_button = QPushButton("Save as .py", self)
        self.save_py_button.setFixedHeight(40)
        self.save_py_button.clicked.connect(self.onSavePy)

        main_layout.addWidget(self.save_py_button)

        # Set the main layout
        self.setLayout(main_layout)

    def onSavePy(self):
        # Get the input data
        ip = self.ip_input.text().strip()
        port = self.port_input.text().strip()
        local_aet = self.local_aet_input.text().strip()
        remote_aet = self.remote_aet_input.text().strip()
        connection_type = self.connection_type_combo.currentText()

        # Validate required fields
        if not ip or not port or not local_aet or not remote_aet:
            QMessageBox.warning(self, "Missing Fields", "All fields must be filled.")
            return

        # Generate the content of the .py file based on the connection type
        if connection_type == "Send":
            script_content = f"""import os
import time
import subprocess
from pathlib import Path
import threading
import signal
import sys

# Configuratie
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AETITLE_CALLING = "{local_aet}"
AETITLE_CALLED = "{remote_aet}"
HOST = "{ip}"
PORT = "{port}"
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
        log_message(f"Map aangemaakt: {{directory}}")

# Functie om logberichten te schrijven
def log_message(message):
    \"\"\"Schrijf een logbericht naar zowel de terminal als het logbestand.\"\"\"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{{timestamp}}] {{message}}"
    print(formatted_message, flush=True)  # Directe uitvoer naar de terminal
    with open(LOGFILE, "a") as log_file:
        log_file.write(formatted_message + "\\n")

# Controleer of een andere instantie draait
def check_existing_instance():
    if os.path.isfile(PIDFILE):
        try:
            with open(PIDFILE, "r") as pid_file:
                pid = int(pid_file.read().strip())
            if pid and os.path.exists(f"/proc/{{pid}}"):
                log_message(f"Een andere instantie draait al met PID {{pid}}.")
                sys.exit(1)
        except Exception as e:
            log_message(f"Fout bij het controleren van bestaande instantie: {{str(e)}}")

    with open(PIDFILE, "w") as pid_file:
        pid_file.write(str(os.getpid()))
    log_message(f"PID-bestand aangemaakt: {{PIDFILE}} (PID: {{os.getpid()}})")

# Verwijder het PID-bestand bij afsluiten
def cleanup_pidfile():
    if os.path.isfile(PIDFILE):
        os.remove(PIDFILE)
        log_message(f"PID-bestand verwijderd: {{PIDFILE}}")

# Controleer of de ontvanger online is
def check_receiver_online():
    log_message(f"Controleer of {{HOST}}:{{PORT}} bereikbaar is...")
    try:
        result = subprocess.run(
            ["nc", "-z", "-v", "-w5", HOST, PORT],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode == 0:
            log_message(f"Ontvangende node is online: {{HOST}}:{{PORT}}")
            return True
        else:
            log_message(f"Ontvangende node is NIET bereikbaar: {{HOST}}:{{PORT}}")
            return False
    except Exception as e:
        log_message(f"Fout bij controle van ontvanger: {{str(e)}}")
        return False

# Verwerk een bestand uit de wachtrij
def send_file(file_path):
    log_message(f"Probeer bestand te verzenden: {{file_path}}")
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
            log_message(f"storescu gestart voor bestand: {{file_path}}")
            # Lees de uitvoer van het subprocess in realtime
            for line in process.stdout:
                log_message(line.strip())
            process.wait()
            if process.returncode == 0:
                log_message(f"Succesvol verzonden: {{file_path}}")
                os.remove(file_path)  # Verwijder bestand na succesvol verzenden
            else:
                log_message(f"Fout bij verzenden van {{file_path}}: {{process.stderr.read().strip()}}")
        except Exception as e:
            log_message(f"Fout bij het uitvoeren van storescu: {{str(e)}}")
    else:
        log_message(f"Ontvangende node is niet online. Bestand blijft in wachtrij: {{file_path}}")

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
    log_message(f"Monitoring map: {{SENDDIR}}")
    while True:
        if os.path.isfile(STOPFILE):
            log_message("STOP-signaalbestand gedetecteerd. Het script stopt.")
            break

        for file_path in Path(SENDDIR).glob('*'):
            if file_path.is_file():
                destination = os.path.join(QUEUE_DIR, file_path.name)
                os.rename(file_path, destination)
                log_message(f"Nieuw bestand gedetecteerd en verplaatst naar wachtrij: {{destination}}")
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

    log_message(f"Starten van het proces voor het verzenden van DICOM-bestanden (PID: {{os.getpid()}}).")

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
"""
        elif connection_type == "Store":
            script_content = f"""import os
import time
import subprocess
import signal
from pathlib import Path

# Configuratie
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AETITLE_CALLED = "{remote_aet}"
HOST = "{ip}"
PORT = {port}
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
        log_message(f"Map aangemaakt: {{directory}}")

# Functie om logberichten te schrijven
def log_message(message):
    \"\"\"Schrijf een logbericht naar zowel de terminal als het logbestand.\"\"\"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    formatted_message = f"[{{timestamp}}] {{message}}"
    print(formatted_message, flush=True)  # Directe uitvoer naar de terminal
    with open(LOGFILE, "a") as log_file:
        log_file.write(formatted_message + "\\n")

# Start de DICOM-server
def start_storescp():
    global storescp_process
    log_message(f"Start de DICOM-server op {{HOST}}:{{PORT}}...")
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
        log_message(f"storescp gestart met PID {{storescp_process.pid}}.")
    except Exception as e:
        log_message(f"Fout bij het starten van storescp: {{str(e)}}")

# Stop de DICOM-server
def stop_storescp():
    \"\"\"Stop het storescp-proces als het actief is.\"\"\"
    global storescp_process
    if storescp_process and storescp_process.poll() is None:
        log_message(f"Stoppen van storescp PID {{storescp_process.pid}}...")
        try:
            os.killpg(os.getpgid(storescp_process.pid), signal.SIGTERM)
            storescp_process.wait()
            log_message("storescp is gestopt.")
        except Exception as e:
            log_message(f"Fout bij het stoppen van storescp: {{str(e)}}")
    if os.path.isfile(PIDFILE):
        os.remove(PIDFILE)
        log_message("PID-bestand verwijderd.")

# Controleer op het STOP-signaalbestand
def monitor_stop_signal():
    \"\"\"Controleer regelmatig op het STOP-signaalbestand.\"\"\"
    while True:
        if os.path.isfile(STOPFILE):
            log_message("STOP-signaalbestand gedetecteerd. Stop de node.")
            stop_storescp()
            try:
                os.remove(STOPFILE)
                log_message("STOP-signaalbestand verwijderd.")
            except Exception as e:
                log_message(f"Fout bij het verwijderen van het STOP-signaalbestand: {{str(e)}}")
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
"""
        else:
            QMessageBox.warning(self, "Invalid Type", "Invalid connection type selected.")
            return

        # Open a file dialog to choose a save location
        options = QFileDialog.Options()
        default_name = "send_node.py" if connection_type == "Send" else "store_node.py"
        file_path, _ = QFileDialog.getSaveFileName(self, "Save .py", default_name, "Python Script Files (*.py);;All Files (*)", options=options)

        if file_path:
            # Save the script content to the chosen path
            with open(file_path, 'w') as py_file:
                py_file.write(script_content)
            QMessageBox.information(self, "Success", f".py script saved to {file_path}")


class StatusWidget(QWidget):
    def __init__(self, label, status="stopped"):
        super().__init__()
        self.label = label
        self.status = status  # "running" or "stopped"

        self.layout = QHBoxLayout()
        self.node_label = QLabel(label)

        self.layout.addWidget(self.node_label)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.setLayout(self.layout)

    def set_status(self, status):
        self.status = status

    def update_label(self, status_text):
        self.node_label.setText(f"{self.label} ({status_text})")


class NodeManager(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Node Manager")
        self.resize(600, 500)

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_button = QPushButton("Voeg node toe")
        self.remove_button = QPushButton("Verwijder node")
        self.start_button = QPushButton("Start node")
        self.stop_button = QPushButton("Stop node")
        self.create_node_button = QPushButton("Maak nieuwe node")  # New button for Node Creator
        

        btn_layout.addWidget(self.add_button)
        btn_layout.addWidget(self.remove_button)
        btn_layout.addWidget(self.start_button)
        btn_layout.addWidget(self.stop_button)
        btn_layout.addWidget(self.create_node_button)  # Add the new button
        

        self.layout.addLayout(btn_layout)

        # Node list
        self.node_list = QListWidget()
        self.layout.addWidget(self.node_list)

        # Log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.layout.addWidget(self.log_output)

        # Internal data: path -> { label, path, process, widget }
        self.node_data = {}

        # Configuration and logging directories
        self.base_dir = Path(__file__).resolve().parent
        self.config_dir = self.base_dir / "config"
        self.logging_dir = self.base_dir / "logging"
        self.config_file = self.config_dir / "nodes_config.txt"
        self.log_file = self.logging_dir / "monitor_log.txt"

        self.ensure_directories()
        self.load_config()

        # Connect signals
        self.add_button.clicked.connect(self.add_node)
        self.remove_button.clicked.connect(self.remove_node)
        self.start_button.clicked.connect(self.start_node)
        self.stop_button.clicked.connect(self.stop_node)
        self.create_node_button.clicked.connect(self.open_node_creator)  # Connect the button to Node Creator
        self.node_list.currentItemChanged.connect(self.change_selected_node)

        # Timer to check statuses
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_statuses)
        self.timer.start(2000)

    def ensure_directories(self):
        """Ensure that configuration and logging directories exist."""
        for directory in [self.config_dir, self.logging_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    def log_action(self, action, label):
        """Write an action to the log file."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {action}: {label}\n"
        with self.log_file.open("a") as log:
            log.write(log_entry)
        self.log_output.append(log_entry.strip())

    def save_config(self):
        """Sla de configuratie van de nodes op in een bestand."""
        with self.config_file.open("w") as config:
            for path, data in self.node_data.items():
                status = data["widget"].status
                pid = data["process"].pid if data["process"] and data["process"].poll() is None else ""
                config.write(f"{data['label']}|{path}|{status}|{pid}\n")

    def load_config(self):
        """Laad de configuratie van de nodes uit een bestand."""
        if self.config_file.exists():
            with self.config_file.open("r") as config:
                for line in config:
                    try:
                        label, path, status, pid = line.strip().split("|")
                        node_widget = StatusWidget(label, status=status)
                        item = QListWidgetItem()
                        item.setSizeHint(QSize(200, 40))
                        self.node_list.addItem(item)
                        self.node_list.setItemWidget(item, node_widget)

                        # Controleer of de node actief is en koppel de uitvoer opnieuw
                        if status == "running" and pid:
                            try:
                                pid = int(pid)
                                if Path(f"/proc/{pid}").exists():
                                    process = subprocess.Popen(
                                        ["tail", "-f", f"/proc/{pid}/fd/1"],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        text=True
                                    )
                                    threading.Thread(target=self.read_process_output, args=(process, node_widget)).start()
                                    node_widget.set_status("running")
                                    node_widget.update_label("Running")
                                    item.setBackground(QColor("lightgreen"))
                                else:
                                    node_widget.set_status("stopped")
                                    node_widget.update_label("Stopped")
                                    item.setBackground(QColor("lightgray"))
                            except Exception as e:
                                print(f"Fout bij het koppelen van PID {pid} voor {label}: {e}")
                                node_widget.set_status("stopped")
                                node_widget.update_label("Stopped")
                                item.setBackground(QColor("lightgray"))
                        else:
                            node_widget.set_status("stopped")
                            node_widget.update_label("Stopped")
                            item.setBackground(QColor("lightgray"))

                        self.node_data[path] = {
                            "label": label,
                            "path": path,
                            "process": None,
                            "widget": node_widget
                        }
                    except ValueError as e:
                        print(f"Fout bij het laden van configuratieregel: {line.strip()} - {e}")

    def open_node_creator(self):
        """Open the Node Creator as a separate window."""
        self.node_creator = NodeCreator()
        self.node_creator.show()

    def add_node(self):
        path, _ = QFileDialog.getOpenFileName(self, "Kies een Python-script", "", "Python scripts (*.py)")
        if not path:
            return

        label, ok = QInputDialog.getText(self, "Node label", "Naam voor deze node:")
        if ok and label:
            if path in self.node_data:
                QMessageBox.warning(self, "Node bestaat al", "Er bestaat al een node met dit script.")
                return

            # Create a StatusWidget with the name of the node and the status "stopped"
            node_widget = StatusWidget(label, status="stopped")
            item = QListWidgetItem()
            item.setSizeHint(QSize(200, 40))
            self.node_list.addItem(item)
            self.node_list.setItemWidget(item, node_widget)

            self.node_data[path] = {
                "label": label,
                "path": path,
                "process": None,
                "widget": node_widget
            }

            # Log the action and save the configuration
            self.log_action("Node toegevoegd", label)
            self.save_config()

    def remove_node(self):
        selected = self.node_list.currentItem()
        if selected:
            # Find the path based on the selected widget
            for path, data in self.node_data.items():
                if data["widget"] == self.node_list.itemWidget(selected):
                    label = data["label"]
                    self.stop_and_cleanup(path)
                    self.node_data.pop(path)
                    self.node_list.takeItem(self.node_list.currentRow())
                    self.log_output.clear()

                    # Log the action and save the configuration
                    self.log_action("Node verwijderd", label)
                    self.save_config()
                    break

    def start_node(self):
        selected = self.node_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "Geen selectie", "Selecteer een node om te starten.")
            return

        # Find the path based on the selected widget
        for path, data in self.node_data.items():
            if data["widget"] == self.node_list.itemWidget(selected):
                node = data
                break
        else:
            QMessageBox.warning(self, "Ongeldige node", "De geselecteerde node bestaat niet.")
            return

        if node["process"] is None or node["process"].poll() is not None:
            try:
                # Start het proces en lees de uitvoer
                process = subprocess.Popen(
                    ["python3", node["path"]],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    preexec_fn=os.setsid  # Start in een nieuwe process group
                )

                # Bewaar het proces in de node-data
                node["process"] = process

                # Start threads om de uitvoer van het proces te lezen
                threading.Thread(target=self.read_process_output, args=(process, node["widget"])).start()

                node["widget"].set_status("running")
                node["widget"].update_label("Running")
                selected.setBackground(QColor("lightgreen"))

                # Log the action
                self.log_action("Node gestart", node["label"])
            except Exception as e:
                QMessageBox.critical(self, "Fout bij starten", str(e))

    def stop_node(self):
        selected = self.node_list.currentItem()
        if selected:
            # Zoek het pad en de gegevens van de geselecteerde node
            for path, data in self.node_data.items():
                if data["widget"] == self.node_list.itemWidget(selected):
                    node = data
                    break
            else:
                return

            # Maak het STOP-signaalbestand aan
            try:
                stop_flag_path = Path(node["path"]).parent / "stop.flag"
                stop_flag_path.write_text("STOP")
                self.log_action("STOP-signaalbestand aangemaakt", node["label"])
            except Exception as e:
                QMessageBox.critical(self, "Fout bij stoppen", f"Kan STOP-signaalbestand niet aanmaken: {str(e)}")
                return

            # Controleer of het proces actief is en stop het
            pidfile = Path(node["path"]).parent / "send_node.pid" if "send_node" in node["path"] else Path(node["path"]).parent / "storescp.pid"
            if pidfile.exists():
                try:
                    with pidfile.open("r") as pid_file:
                        pid = int(pid_file.read().strip())
                    if pid and Path(f"/proc/{pid}").exists():
                        os.killpg(os.getpgid(pid), signal.SIGTERM)  # Stop het proces
                        self.log_action(f"Node gestopt met PID {pid}", node["label"])
                        pidfile.unlink()  # Verwijder het PID-bestand
                    else:
                        self.log_action("Geen actief proces gevonden om te stoppen", node["label"])
                except Exception as e:
                    QMessageBox.critical(self, "Fout bij stoppen", f"Kan proces niet stoppen: {str(e)}")
            else:
                self.log_action("Geen actief proces gevonden om te stoppen", node["label"])

            # Update de UI
            node["process"] = None
            node["widget"].set_status("stopped")
            node["widget"].update_label("Stopped")
            selected.setBackground(QColor("lightgray"))

            # Log de actie
            self.log_action("Node gestopt", node["label"])

    def read_process_output(self, process, widget):
        """Lees de uitvoer van het proces en toon deze alleen als het de geselecteerde node is."""
        def read_stream(stream, widget):
            while True:
                output = stream.readline()
                if output == "" and process.poll() is not None:
                    break
                if output:
                    # Controleer of de widget overeenkomt met de geselecteerde node
                    selected_node = self.get_selected_node()
                    if selected_node and selected_node["widget"] == widget:
                        QMetaObject.invokeMethod(
                            self.log_output,
                            "append",
                            Q_ARG(str, f"{selected_node['label']}: {output.strip()}")
                        )

        threading.Thread(target=read_stream, args=(process.stdout, widget), daemon=True).start()
        threading.Thread(target=read_stream, args=(process.stderr, widget), daemon=True).start()

    def stop_and_cleanup(self, path):
        node = self.node_data.get(path)
        if not node:
            return

        proc = node["process"]

        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait()
            except Exception as e:
                print(f"Fout bij stoppen van node {node['label']}: {e}")

        node["process"] = None
        node["widget"].set_status("stopped")
        node["widget"].update_label("Stopped")

    def update_statuses(self):
        """Werk de status van alle nodes bij."""
        for i in range(self.node_list.count()):
            item = self.node_list.item(i)
            widget = self.node_list.itemWidget(item)
            node = None

            # Zoek de juiste node op basis van de widget
            for path, data in self.node_data.items():
                if data["widget"] == widget:
                    node = data
                    break

            if not node:
                continue

            # Controleer of de node actief is op basis van het PID-bestand
            pidfile = Path(node["path"]).parent / "send_node.pid" if "send_node" in node["path"] else Path(node["path"]).parent / "storescp.pid"
            if pidfile.exists():
                try:
                    with pidfile.open("r") as pid_file:
                        pid = int(pid_file.read().strip())
                    if pid and Path(f"/proc/{pid}").exists():
                        # Node is actief
                        if node["process"] is None:
                            # Koppel de uitvoer opnieuw
                            process = subprocess.Popen(
                                ["tail", "-f", f"/proc/{pid}/fd/1"],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True
                            )
                            threading.Thread(target=self.read_process_output, args=(process, widget)).start()
                            node["process"] = process

                        widget.set_status("running")
                        widget.update_label("Running")
                        item.setBackground(QColor("lightgreen"))
                    else:
                        # Node is niet actief
                        widget.set_status("stopped")
                        widget.update_label("Stopped")
                        item.setBackground(QColor("lightgray"))
                except Exception as e:
                    print(f"Fout bij het controleren van PID-bestand voor {node['label']}: {e}")
                    widget.set_status("stopped")
                    widget.update_label("Stopped")
                    item.setBackground(QColor("lightgray"))
            else:
                # Geen PID-bestand gevonden, node is gestopt
                widget.set_status("stopped")
                widget.update_label("Stopped")
                item.setBackground(QColor("lightgray"))

    def change_selected_node(self):
        """Wis de logweergave bij het wijzigen van de geselecteerde node."""
        self.log_output.clear()
        selected_node = self.get_selected_node()
        if selected_node:
            self.log_action("Node geselecteerd", selected_node["label"])

    def get_selected_node(self):
        """Retourneer de gegevens van de geselecteerde node."""
        selected = self.node_list.currentItem()
        if not selected:
            return None
        for path, data in self.node_data.items():
            if data["widget"] == self.node_list.itemWidget(selected):
                return data
        return None

    def closeEvent(self, event):
        """Sluit de monitor zonder de actieve nodes te stoppen."""
        # Log dat de monitor wordt afgesloten
        self.log_action("Monitor afgesloten", "Monitor")
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NodeManager()
    window.show()
    sys.exit(app.exec_())

import sys
import shutil
import subprocess
import json
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QMessageBox, QLineEdit, QListWidget, QDialog, QWidget
)
from PyQt5.QtGui import QColor


class DockerStartGUI(QMainWindow):
    CONFIG_DIR = Path("Docker_config_streams")  # Directory voor configuratiebestanden

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Docker Manager")
        self.setGeometry(100, 100, 800, 400)

        # Zorg dat de configuratiemap bestaat
        self.CONFIG_DIR.mkdir(exist_ok=True)

        # Main layout
        self.main_layout = QVBoxLayout()

        # Active Docker Streams
        self.active_streams_list = QListWidget()
        self.refresh_button = QPushButton("Refresh Active Streams")
        self.refresh_button.clicked.connect(self.refresh_active_streams)

        # Start and Stop Buttons
        self.start_button = QPushButton("Start Docker Stream")
        self.start_button.clicked.connect(self.start_docker_stream)

        self.stop_button = QPushButton("Stop Docker Stream")
        self.stop_button.clicked.connect(self.stop_docker_stream)

        # Add Docker Button
        self.add_docker_button = QPushButton("Add Docker")
        self.add_docker_button.clicked.connect(self.open_add_docker_window)

        # Add widgets to layout
        self.main_layout.addWidget(QLabel("Active Docker Streams:"))
        self.main_layout.addWidget(self.active_streams_list)
        self.main_layout.addWidget(self.refresh_button)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.start_button)
        buttons_layout.addWidget(self.stop_button)
        self.main_layout.addLayout(buttons_layout)

        self.main_layout.addWidget(self.add_docker_button)

        # Set central widget
        central_widget = QWidget()
        central_widget.setLayout(self.main_layout)
        self.setCentralWidget(central_widget)

        # Refresh active streams on startup
        self.refresh_active_streams()

    def refresh_active_streams(self):
        """Refresh the list of active Docker streams and check against configurations."""
        self.active_streams_list.clear()
        try:
            # Haal actieve containers op
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}: {{.Status}}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if result.returncode != 0:
                # Als het `docker`-commando niet werkt, laat de lijst leeg
                return

            active_containers = result.stdout.strip().split("\n") if result.stdout.strip() else []

            # Controleer tegen configuratiebestanden
            for config_file in self.CONFIG_DIR.glob("*.json"):
                stream_name = config_file.stem  # Naam van de stream (zonder extensie)
                item_text = f"{stream_name}: Running" if any(stream_name in container for container in active_containers) else f"{stream_name}: Stopped"
                item = QListWidget.QListWidgetItem(item_text)
                if "Running" in item_text:
                    item.setBackground(QColor("lightgreen"))
                self.active_streams_list.addItem(item)
        except FileNotFoundError:
            # Als het `docker`-commando niet gevonden wordt, laat de lijst leeg zonder waarschuwing
            pass
        except Exception:
            # Andere fouten afvangen, maar geen foutmelding tonen
            pass

    def start_docker_stream(self):
        """Start the selected Docker stream."""
        selected_item = self.active_streams_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "No Selection", "Please select a Docker stream to start.")
            return

        stream_name = selected_item.text().split(":")[0]
        config_file = self.CONFIG_DIR / f"{stream_name}.json"
        if not config_file.exists():
            QMessageBox.critical(self, "Error", f"Configuration for '{stream_name}' not found.")
            return

        with config_file.open("r") as file:
            config = json.load(file)

        try:
            subprocess.Popen(
                ["bash", config["docker_script"], config["config_file"]],
                cwd=config["docker_map"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            QMessageBox.information(self, "Success", f"Docker stream '{stream_name}' started successfully.")
            self.refresh_active_streams()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start Docker stream '{stream_name}': {e}")

    def stop_docker_stream(self):
        """Stop the selected Docker stream."""
        selected_item = self.active_streams_list.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "No Selection", "Please select a Docker stream to stop.")
            return

        stream_name = selected_item.text().split(":")[0]
        try:
            subprocess.run(
                ["docker", "stop", stream_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            QMessageBox.information(self, "Success", f"Docker stream '{stream_name}' stopped successfully.")
            self.refresh_active_streams()
        except subprocess.CalledProcessError:
            QMessageBox.critical(self, "Error", f"Failed to stop Docker stream '{stream_name}'.")

    def open_add_docker_window(self):
        """Open the Add Docker window."""
        self.add_docker_window = AddDockerWindow(self)
        self.add_docker_window.show()


class AddDockerWindow(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Add Docker Stream")
        self.setGeometry(150, 150, 600, 400)

        self.parent = parent

        # Layout
        layout = QVBoxLayout()

        # Stream Name
        self.stream_name_label = QLabel("Stream Name:")
        self.stream_name_input = QLineEdit(self)
        self.stream_name_input.setPlaceholderText("Enter a unique name for the Docker stream...")

        layout.addWidget(self.stream_name_label)
        layout.addWidget(self.stream_name_input)

        # Input Map
        self.input_map_label = QLabel("Input Map:")
        self.input_map_path = QLineEdit(self)
        self.input_map_path.setPlaceholderText("Select the input map...")
        self.input_map_button = QPushButton("Browse")
        self.input_map_button.clicked.connect(self.select_input_map)

        input_map_layout = QHBoxLayout()
        input_map_layout.addWidget(self.input_map_path)
        input_map_layout.addWidget(self.input_map_button)

        layout.addWidget(self.input_map_label)
        layout.addLayout(input_map_layout)

        # Docker Start Script
        self.docker_script_label = QLabel("Docker Start Script (.sh):")
        self.docker_script_path = QLineEdit(self)
        self.docker_script_path.setPlaceholderText("Select the Docker start script...")
        self.docker_script_button = QPushButton("Browse")
        self.docker_script_button.clicked.connect(self.select_docker_script)

        docker_script_layout = QHBoxLayout()
        docker_script_layout.addWidget(self.docker_script_path)
        docker_script_layout.addWidget(self.docker_script_button)

        layout.addWidget(self.docker_script_label)
        layout.addLayout(docker_script_layout)

        # Docker Start Map
        self.docker_map_label = QLabel("Docker Start Map:")
        self.docker_map_path = QLineEdit(self)
        self.docker_map_path.setPlaceholderText("Select the Docker start map...")
        self.docker_map_button = QPushButton("Browse")
        self.docker_map_button.clicked.connect(self.select_docker_map)

        docker_map_layout = QHBoxLayout()
        docker_map_layout.addWidget(self.docker_map_path)
        docker_map_layout.addWidget(self.docker_map_button)

        layout.addWidget(self.docker_map_label)
        layout.addLayout(docker_map_layout)

        # Docker Config File
        self.config_file_label = QLabel("Docker Config File:")
        self.config_file_path = QLineEdit(self)
        self.config_file_path.setPlaceholderText("Select the Docker config file...")
        self.config_file_button = QPushButton("Browse")
        self.config_file_button.clicked.connect(self.select_config_file)

        config_file_layout = QHBoxLayout()
        config_file_layout.addWidget(self.config_file_path)
        config_file_layout.addWidget(self.config_file_button)

        layout.addWidget(self.config_file_label)
        layout.addLayout(config_file_layout)

        # Buttons
        self.save_button = QPushButton("Save Docker Stream")
        self.save_button.clicked.connect(self.save_docker_stream)

        layout.addWidget(self.save_button)

        self.setLayout(layout)

    def select_input_map(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Input Map")
        if directory:
            self.input_map_path.setText(directory)

    def select_docker_script(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Docker Start Script", filter="Shell Scripts (*.sh)")
        if file:
            self.docker_script_path.setText(file)

    def select_docker_map(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Docker Start Map")
        if directory:
            self.docker_map_path.setText(directory)

    def select_config_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Docker Config File", filter="Config Files (*.conf *.json *.yaml *.yml)")
        if file:
            self.config_file_path.setText(file)

    def save_docker_stream(self):
        """Save the Docker stream configuration."""
        stream_name = self.stream_name_input.text().strip()
        if not stream_name:
            QMessageBox.warning(self, "Invalid Input", "Stream name cannot be empty.")
            return

        config = {
            "input_map": self.input_map_path.text(),
            "docker_script": self.docker_script_path.text(),
            "docker_map": self.docker_map_path.text(),
            "config_file": self.config_file_path.text()
        }

        if not all(config.values()):
            QMessageBox.warning(self, "Invalid Input", "All fields must be filled.")
            return

        # Save the configuration to a file
        config_file = self.parent.CONFIG_DIR / f"{stream_name}.json"
        if config_file.exists():
            QMessageBox.warning(self, "Duplicate Stream", f"A stream with the name '{stream_name}' already exists.")
            return

        with config_file.open("w") as file:
            json.dump(config, file)

        QMessageBox.information(self, "Success", f"Docker stream '{stream_name}' saved successfully.")
        self.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DockerStartGUI()
    window.show()
    sys.exit(app.exec_())
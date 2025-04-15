import sys
import json
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QFileDialog, QComboBox, QFormLayout, QGroupBox

class MyApp(QWidget):
    def __init__(self):
        super().__init__()

        # Stel de titel van de applicatie in op "Dicom Node Configurator"
        self.setWindowTitle("Dicom Node Configurator")
        self.setGeometry(100, 100, 500, 500)  # Stel het vensterformaat in

        self.initUI()

    def initUI(self):
        # Hoofd lay-out
        main_layout = QVBoxLayout()

        # Groeperen van secties in een QGroupBox voor een nette uitstraling
        connection_group = QGroupBox("Verbinding Instellingen")
        path_group = QGroupBox("Pad Instellingen")
        script_group = QGroupBox("Verwerkingsscript")

        # Verbinding Instellingen
        connection_layout = QFormLayout()
        self.connection_type_combo = QComboBox(self)
        self.connection_type_combo.addItems(["Send", "Store"])
        self.connection_type_combo.currentIndexChanged.connect(self.onConnectionTypeChanged)
        connection_layout.addRow("Verbindingstype:", self.connection_type_combo)

        self.node_name_input = QLineEdit(self)
        connection_layout.addRow("Naam dicom node:", self.node_name_input)

        self.ip_input = QLineEdit(self)
        connection_layout.addRow("IP adres:", self.ip_input)

        self.port_input = QLineEdit(self)
        connection_layout.addRow("Poortnummer:", self.port_input)

        self.local_aet_input = QLineEdit(self)
        connection_layout.addRow("Local AE Title:", self.local_aet_input)

        self.remote_aet_input = QLineEdit(self)
        connection_layout.addRow("Remote AE Title:", self.remote_aet_input)

        connection_group.setLayout(connection_layout)

        # Pad Instellingen
        path_layout = QFormLayout()
        self.watchdir_button = QPushButton("Selecteer WATCHDIR", self)
        self.watchdir_button.clicked.connect(self.selectWatchDir)
        self.watchdir_input = QLineEdit(self)
        self.watchdir_input.setReadOnly(True)
        path_layout.addRow("WATCHDIR (Ontvangstmappen):", self.watchdir_button)
        path_layout.addRow("", self.watchdir_input)

        self.queue_dir_button = QPushButton("Selecteer QUEUE_DIR", self)
        self.queue_dir_button.clicked.connect(self.selectQueueDir)
        self.queue_dir_input = QLineEdit(self)
        self.queue_dir_input.setReadOnly(True)
        path_layout.addRow("QUEUE_DIR (Wachtrijmap):", self.queue_dir_button)
        path_layout.addRow("", self.queue_dir_input)

        self.logdir_button = QPushButton("Selecteer LOGDIR", self)
        self.logdir_button.clicked.connect(self.selectLogDir)
        self.logdir_input = QLineEdit(self)
        self.logdir_input.setReadOnly(True)
        path_layout.addRow("LOGDIR (Logmap):", self.logdir_button)
        path_layout.addRow("", self.logdir_input)

        path_group.setLayout(path_layout)

        # Verwerkingsscript Instellingen
        script_layout = QFormLayout()
        self.process_script_button = QPushButton("Selecteer PROCESS_SCRIPT", self)
        self.process_script_button.clicked.connect(self.selectProcessScript)
        self.process_script_input = QLineEdit(self)
        self.process_script_input.setReadOnly(True)
        script_layout.addRow("PROCESS_SCRIPT (Verwerkingsscript):", self.process_script_button)
        script_layout.addRow("", self.process_script_input)

        script_group.setLayout(script_layout)

        # Voeg de secties toe aan de hoofd lay-out
        main_layout.addWidget(connection_group)
        main_layout.addWidget(path_group)
        main_layout.addWidget(script_group)

        # Voeg de "Save as JSON" knop toe
        self.save_json_button = QPushButton("Save as JSON", self)
        self.save_json_button.setFixedHeight(40)
        self.save_json_button.clicked.connect(self.onSaveJson)

        main_layout.addWidget(self.save_json_button)

        # Stel de hoofd lay-out in
        self.setLayout(main_layout)

    def onConnectionTypeChanged(self):
        # Haal de geselecteerde verbindingstype op
        connection_type = self.connection_type_combo.currentText()
        print(f"Verbindingstype gewijzigd naar: {connection_type}")

    def selectWatchDir(self):
        # Bestandsdialoog om een map te selecteren voor WATCHDIR
        dir_path = QFileDialog.getExistingDirectory(self, "Selecteer WATCHDIR", "")
        if dir_path:
            self.watchdir_input.setText(dir_path)

    def selectQueueDir(self):
        # Bestandsdialoog om een map te selecteren voor QUEUE_DIR
        dir_path = QFileDialog.getExistingDirectory(self, "Selecteer QUEUE_DIR", "")
        if dir_path:
            self.queue_dir_input.setText(dir_path)

    def selectLogDir(self):
        # Bestandsdialoog om een map te selecteren voor LOGDIR
        dir_path = QFileDialog.getExistingDirectory(self, "Selecteer LOGDIR", "")
        if dir_path:
            self.logdir_input.setText(dir_path)

    def selectProcessScript(self):
        # Bestandsdialoog om een bestand te selecteren voor PROCESS_SCRIPT
        file_path, _ = QFileDialog.getOpenFileName(self, "Selecteer PROCESS_SCRIPT", "", "Python Files (*.py);;All Files (*)")
        if file_path:
            self.process_script_input.setText(file_path)

    def onSaveJson(self):
        # Verkrijg de gegevens
        node_name = self.node_name_input.text()
        ip = self.ip_input.text()
        port = self.port_input.text()
        local_aet = self.local_aet_input.text()
        remote_aet = self.remote_aet_input.text()
        connection_type = self.connection_type_combo.currentText()  # Dit is de verbindingstype

        # Nieuwe gegevens voor de DICOM-configuratie
        watchdir = self.watchdir_input.text()
        queue_dir = self.queue_dir_input.text()
        logdir = self.logdir_input.text()
        process_script = self.process_script_input.text()

        # Maak een dictionary met de gegevens
        data = {
            "Node Name": node_name,
            "IP": ip,
            "Port": port,
            "Local AE Title": local_aet,
            "Remote AE Title": remote_aet,
            "Connection Type": connection_type,  # Voeg verbindingstype toe aan de output
            "WATCHDIR": watchdir,
            "QUEUE_DIR": queue_dir,
            "LOGDIR": logdir,
            "PROCESS_SCRIPT": process_script
        }

        # Open een bestand dialoog om een locatie te kiezen
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(self, "Save JSON", "", "JSON Files (*.json);;All Files (*)", options=options)

        if file_path:
            # Sla de gegevens op in het gekozen pad
            with open(file_path, 'w') as json_file:
                json.dump(data, json_file, indent=4)
            print(f"JSON saved to {file_path}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = MyApp()
    ex.show()
    sys.exit(app.exec_())

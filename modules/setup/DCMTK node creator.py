import sys
import subprocess
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QFileDialog, QLabel, QHBoxLayout, QMessageBox
from PyQt5.QtCore import Qt

class StoreNodeConfig(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("DICOM Store SCP Configurator")
        self.setGeometry(100, 100, 400, 300)

        # Layouts
        self.main_layout = QVBoxLayout()
        self.form_layout = QFormLayout()
        self.button_layout = QHBoxLayout()

        # Variabelen voor input
        self.ae_title_input = QLineEdit(self)
        self.port_input = QLineEdit(self)
        self.storage_path_input = QLineEdit(self)
        self.dcmtk_path_input = QLineEdit(self)

        # Bestanden kiezen knoppen
        self.storage_browse_button = QPushButton("Browse", self)
        self.dcmtk_browse_button = QPushButton("Browse", self)

        # Voeg velden toe aan formulier
        self.form_layout.addRow("AE Title:", self.ae_title_input)
        self.form_layout.addRow("Poort:", self.port_input)
        self.form_layout.addRow("Opslagmap:", self.storage_path_input)
        self.form_layout.addRow("", self.storage_browse_button)
        self.form_layout.addRow("Pad naar storescp:", self.dcmtk_path_input)
        self.form_layout.addRow("", self.dcmtk_browse_button)

        # Start button
        self.start_button = QPushButton("Start DICOM Store", self)
        self.start_button.clicked.connect(self.start_listener)

        self.button_layout.addWidget(self.start_button)
        self.main_layout.addLayout(self.form_layout)
        self.main_layout.addLayout(self.button_layout)

        self.setLayout(self.main_layout)

        # Verbinden van knoppen
        self.storage_browse_button.clicked.connect(self.browse_folder)
        self.dcmtk_browse_button.clicked.connect(self.browse_dcmtk)

        # Vul het storescp-pad automatisch in als het niet is ingevuld
        self.auto_fill_storescp_path()

    def auto_fill_storescp_path(self):
        """Automatisch het pad naar storescp invullen als dit niet handmatig is opgegeven"""
        if not self.dcmtk_path_input.text():
            try:
                storescp_path = subprocess.check_output(['which', 'storescp'], stderr=subprocess.STDOUT).decode('utf-8').strip()
                if storescp_path:
                    self.dcmtk_path_input.setText(storescp_path)
            except subprocess.CalledProcessError:
                self.show_error_message("Fout", "Kon het pad naar 'storescp' niet vinden. Zorg ervoor dat DCMTK is geïnstalleerd.")

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Kies Opslagmap")
        if folder:
            self.storage_path_input.setText(folder)

    def browse_dcmtk(self):
        file, _ = QFileDialog.getOpenFileName(self, "Kies storescp executable", "", "Executables (*.exe *.bin)")
        if file:
            self.dcmtk_path_input.setText(file)

    def start_listener(self):
        ae_title = self.ae_title_input.text()
        port = self.port_input.text()
        storage_path = self.storage_path_input.text()
        storescp_path = self.dcmtk_path_input.text()

        if not all([ae_title, port, storage_path, storescp_path]):
            self.show_error_message("Fout", "Vul alle velden in.")
            return

        try:
            command = [storescp_path, port, "-aet", ae_title, "-od", storage_path]
            subprocess.Popen(command)
            self.show_info_message("Succes", f"storescp gestart op poort {port} met AE Title '{ae_title}'")
        except Exception as e:
            self.show_error_message("Fout bij starten", str(e))

    def show_error_message(self, title, message):
        error_dialog = QMessageBox()
        error_dialog.setIcon(QMessageBox.Critical)
        error_dialog.setWindowTitle(title)
        error_dialog.setText(message)
        error_dialog.exec_()

    def show_info_message(self, title, message):
        info_dialog = QMessageBox()
        info_dialog.setIcon(QMessageBox.Information)
        info_dialog.setWindowTitle(title)
        info_dialog.setText(message)
        info_dialog.exec_()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = StoreNodeConfig()
    window.show()
    sys.exit(app.exec_())

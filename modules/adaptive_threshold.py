import os
import sys
import cv2
import easyocr
import importlib
import configparser
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog, QTextEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from tqdm import tqdm
import numpy as np

# ========== CONFIG LOADING ==========
# Config inladen
config = configparser.ConfigParser()
config.read('config.ini')

# Waarden uitlezen
image_folder = config['paths']['image_folder']
output_file = config['paths']['output_file']
modules_folder = config['paths']['modules_folder']
preread_folder = config['paths']['preread_folder']  # Lees de map voor preread images

ocr_language = config['ocr']['language']
generate_image = config.getboolean('ocr', 'generate_image')

# ========== MODULE LOADER ==========
def modules_loadorder(config_path='config.ini'):
    config = configparser.ConfigParser()
    config.read(config_path)

    modules_folder = config['paths']['modules_folder']
    enabled_modules = [m.strip() for m in config['modules']['enabled'].split(',')]

    loaded_modules = []
    for mod_name in enabled_modules:
        try:
            module = importlib.import_module(f"{modules_folder}.{mod_name}")
            if getattr(module, 'enabled', True):  # standaard True als 'enabled' ontbreekt
                loaded_modules.append(module)
                print(f"Module geladen: {mod_name}")
            else:
                print(f"Module uitgeschakeld (enabled=False): {mod_name}")
        except Exception as e:
            print(f"Fout bij laden van module '{mod_name}': {e}")
    return loaded_modules

# ========== PROCESS IMAGE ==========
def process_image_with_modules(modules, image_path):
    img_data = cv2.imread(image_path)  # Laad het originele plaatje
    used_modules = []
    try:
        for module in modules:
            if hasattr(module, 'process'):
                img_data = module.process(img_data, image_path)  # Werk de afbeelding bij met de module
                used_modules.append(module.__name__)
            else:
                print(f"Module {module.__name__} heeft geen 'process' functie.")
    except Exception as e:
        print(f"Fout bij het verwerken van de afbeelding met modules: {e}")
    return img_data, used_modules

# ========== OCR ==========
def perform_ocr(img_data):
    try:
        reader = easyocr.Reader([ocr_language], gpu=False)
        results = reader.readtext(img_data)  # Voer OCR uit op de bewerkte afbeelding
        return results
    except Exception as e:
        print(f"Fout bij het uitvoeren van OCR: {e}")
        sys.exit(1)

# ========== GUI ==========
class OCRApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OCR Module Tool")
        self.setMinimumWidth(800)

        # Widgets
        self.label_image = QLabel("Laad een afbeelding om te beginnen.")
        self.label_image.setAlignment(Qt.AlignCenter)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)

        self.button_load = QPushButton("Laad afbeelding")
        self.button_load.clicked.connect(self.load_image)

        self.button_process = QPushButton("Verwerk en OCR")
        self.button_process.clicked.connect(self.process_and_ocr)

        self.modules = modules_loadorder()  # Laad de modules

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.label_image)
        layout.addWidget(self.text_edit)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.button_load)
        button_layout.addWidget(self.button_process)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        self.image_path = None

    def load_image(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Kies een afbeelding", "", "Afbeeldingen (*.jpg *.png *.jpeg)")
        if file_name:
            self.image_path = file_name
            pixmap = self.convert_cv_to_qpixmap(cv2.imread(self.image_path))
            self.label_image.setPixmap(pixmap.scaled(600, 400, Qt.KeepAspectRatio))

    def convert_cv_to_qpixmap(self, cv_img):
        """Zet OpenCV afbeelding om naar QPixmap voor weergave in QLabel."""
        rgb_image = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        q_img = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        return QPixmap.fromImage(q_img)

    def process_and_ocr(self):
        if not self.image_path:
            self.text_edit.setText("Geen afbeelding geladen!")
            return

        # Laad de afbeelding en verwerk deze met de modules
        try:
            img_data, used_modules = process_image_with_modules(self.modules, self.image_path)

            # Voer OCR uit op de bewerkte afbeelding
            results = perform_ocr(img_data)

            # Toon de OCR resultaten in de tekst edit
            self.text_edit.clear()
            self.text_edit.append(f"Gebruikte modules: {', '.join(used_modules)}\n")
            for result in results:
                self.text_edit.append(f"Tekst: {result[1]}")
            
        except Exception as e:
            self.text_edit.setText(f"Er is een fout opgetreden: {e}")

# ========== MAIN ==========
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OCRApp()
    window.show()
    sys.exit(app.exec())

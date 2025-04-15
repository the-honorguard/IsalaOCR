import os
import sys
import cv2
import easyocr
import importlib
import configparser
from tqdm import tqdm
import numpy as np

# Dynamisch de hoofdmap bepalen
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# ========== CONFIG LOADING ==========
# Config inladen
config = configparser.ConfigParser()
config.read(os.path.join(BASE_DIR, 'config/mainconfig.ini'))

# Waarden uitlezen
image_folder = os.path.join(BASE_DIR, config['paths']['cropped_roi_folder'])
output_file = os.path.join(BASE_DIR, config['paths']['output_folder'])
modules_folder = os.path.join(BASE_DIR, config['paths']['modules_folder'])
ocr_language = config['ocr']['language']
generate_image = config.getboolean('ocr', 'generate_image')

# ========== MODULE LOADER ==========
def modules_loadorder(config_path=os.path.join(BASE_DIR, 'config/mainconfig.ini')):
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

# ========== SAVE RESULTAAT ==========
def save_ocr_results(results, image_path, used_modules):
    try:
        base_filename = os.path.splitext(os.path.basename(image_path))[0]
        output_file_path = os.path.join(output_file, f"{base_filename}_ocr_results.txt")

        with open(output_file_path, 'a') as f:
            f.write(f"Resultaten voor afbeelding: {image_path}\n")
            f.write(f"Gebruikte modules: {', '.join(used_modules) if used_modules else 'Geen modules gebruikt'}\n")
            for result in results:
                text = result[1]
                if text.strip():
                    f.write(f"{text}\n")
            f.write("\n")
        print(f"Resultaten opgeslagen in {output_file_path}")
    except Exception as e:
        print(f"Fout bij opslaan van OCR-resultaten: {e}")

# ========== MAIN ==========
if __name__ == "__main__":
    try:
        print("Starten van het script...")

        # Laad modules volgens volgorde in config
        modules = modules_loadorder()

        # Zoek alle afbeeldingen
        image_files = [f for f in os.listdir(image_folder) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]

        for image_file in tqdm(image_files, desc="Verwerken van afbeeldingen"):
            image_path = os.path.join(image_folder, image_file)

            if not os.path.exists(image_path):
                print(f"Afbeelding niet gevonden: {image_path}")
                continue

            print(f"Verwerken van {image_file}...")
            used_modules = []
            results = []

            if modules:
                # Verwerk de afbeelding met de geselecteerde modules
                img_data, used_modules = process_image_with_modules(modules, image_path)
                # Voer OCR uit op de bewerkte afbeelding
                results = perform_ocr(img_data)
            else:
                # Als er geen modules zijn, voer dan gewoon OCR uit op de originele afbeelding
                results = perform_ocr(cv2.imread(image_path))

            # Sla de OCR resultaten op
            save_ocr_results(results, image_path, used_modules)

    except Exception as e:
        print(f"Er is een fout opgetreden tijdens de uitvoering van het script: {e}")
        sys.exit(1)

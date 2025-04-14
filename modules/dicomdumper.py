import pydicom
import json
import os
import configparser
import argparse
from datetime import datetime

# === PAD NAAR CONFIG BESTAND ===
config_file_path = "/home/isala/ocr/IsalaOCR/config/mainconfig.ini"  # Zet hier het pad naar je config bestand

# === CONFIG INLEZEN uit INI bestand (specifieke sectie dicomdumper) ===
config = configparser.ConfigParser()
config.read(config_file_path)

dcm_in_folder = config['paths']['dcm_in_folder']  # Gebruik dcm_in_folder in plaats van input_folder
output_folder = config['paths']['dicomdumper_output_folder']

# Pad naar het logbestand
LOGFILE = "/home/isala/ocr/IsalaOCR/logs/dicomdumper_logs.txt"

# === FUNCTIES ===

def log_message(message):
    """
    Log een bericht naar zowel de terminal als het logbestand.
    """
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{current_time}] {message}"
    print(log_entry)  # Print naar de terminal
    with open(LOGFILE, 'a') as log:
        log.write(log_entry + "\n")  # Schrijf naar het logbestand

def dicom_dataset_to_dict(ds):
    """Recursieve omzetting van pydicom Dataset naar JSON-serialiseerbare dict."""
    output = {}

    # Voeg expliciet de naam van de patiënt en patiëntnummer toe
    patient_name = getattr(ds, "PatientName", "UNKNOWN")
    patient_id = getattr(ds, "PatientID", "UNKNOWN")
    output["PatientName"] = str(patient_name)
    output["PatientID"] = str(patient_id)

    for elem in ds:
        tag = f"{elem.tag} {elem.name}"
        if elem.VR == "SQ":  # Sequence
            output[tag] = [dicom_dataset_to_dict(item) for item in elem.value]
        else:
            try:
                value = elem.value
                if isinstance(value, bytes):
                    value = value.hex()[:100] + "..."  # truncate binary data
                else:
                    value = str(value)
                output[tag] = value
            except Exception as e:
                output[tag] = f"UNREADABLE ({e})"
    return output

def dicom_to_json(dcm_path, output_dir):
    """Leest een DICOM-bestand en schrijft de volledige header weg als JSON."""
    try:
        ds = pydicom.dcmread(dcm_path)
        full_dict = dicom_dataset_to_dict(ds)

        # Haal PatientName en PatientID op voor de bestandsnaam
        patient_name = str(getattr(ds, "PatientName", "UNKNOWN")).replace("^", "_").replace(" ", "_")
        patient_id = str(getattr(ds, "PatientID", "UNKNOWN"))
        json_filename = f"{patient_name}_{patient_id}.json"
        json_path = os.path.join(output_dir, json_filename)

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(full_dict, f, indent=4, ensure_ascii=False)

        log_message(f"✅ DICOM header succesvol als JSON opgeslagen: {json_path}")

    except Exception as e:
        log_message(f"❌ Fout bij verwerken van DICOM-bestand: {e}")

def is_dicom_file(filepath):
    """Controleer of een bestand een geldig DICOM-bestand is."""
    try:
        with open(filepath, 'rb') as f:
            preamble = f.read(132)
            return preamble[128:132] == b'DICM'
    except Exception:
        return False

def process_dicom_directory(input_dir, output_dir):
    """
    Verwerk een map met DICOM-bestanden.
    """
    log_message(f"Start verwerking van DICOM-bestanden in {input_dir}")
    os.makedirs(output_dir, exist_ok=True)
    for root, _, files in os.walk(input_dir):
        for file in files:
            dcm_path = os.path.join(root, file)
            if is_dicom_file(dcm_path):  # Controleer of het een geldig DICOM-bestand is
                log_message(f"Verwerken van bestand: {dcm_path}")
                dicom_to_json(dcm_path, output_dir)
            else:
                log_message(f"Bestand overgeslagen (geen DICOM): {file}")
    log_message(f"Verwerking voltooid. Output opgeslagen in {output_dir}")

# === SCRIPT UITVOERING ===

if os.path.isdir(dcm_in_folder):  # Gebruik dcm_in_folder in plaats van input_folder
    process_dicom_directory(dcm_in_folder, output_folder)
else:
    print(f"❌ Input pad is geen geldige map: {dcm_in_folder}")

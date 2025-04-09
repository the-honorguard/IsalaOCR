import pydicom
import json
import os
import configparser
import argparse

# === PAD NAAR CONFIG BESTAND ===
config_file_path = "/home/isala/ocr/IsalaOCR/config/mainconfig.ini"  # Zet hier het pad naar je config bestand

# === CONFIG INLEZEN uit INI bestand (specifieke sectie dicomdumper) ===
config = configparser.ConfigParser()
config.read(config_file_path)

input_path = config['dicomdumper']['input_path']
output_path = config['dicomdumper']['output_path']

# === FUNCTIES ===

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
        patient_name = getattr(ds, "PatientName", "UNKNOWN").replace("^", "_").replace(" ", "_")
        patient_id = getattr(ds, "PatientID", "UNKNOWN")
        json_filename = f"{patient_name}_{patient_id}.json"
        json_path = os.path.join(output_dir, json_filename)

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(full_dict, f, indent=4, ensure_ascii=False)

        print(f"✅ DICOM header succesvol als JSON opgeslagen: {json_path}")

    except Exception as e:
        print(f"❌ Fout bij verwerken van DICOM-bestand: {e}")

def is_dicom_file(filepath):
    """Controleer of een bestand een geldig DICOM-bestand is."""
    try:
        with open(filepath, 'rb') as f:
            preamble = f.read(132)
            return preamble[128:132] == b'DICM'
    except Exception:
        return False

def process_dicom_directory(input_dir, output_dir):
    """Verwerkt alle DICOM-bestanden in een map en slaat ze op als JSON."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    for root, _, files in os.walk(input_dir):
        for file in files:
            dcm_path = os.path.join(root, file)
            if is_dicom_file(dcm_path):  # Controleer of het een geldig DICOM-bestand is
                dicom_to_json(dcm_path, output_dir)

# === SCRIPT UITVOERING ===

if os.path.isdir(input_path):
    process_dicom_directory(input_path, output_path)
else:
    print(f"❌ Input pad is geen geldige map: {input_path}")

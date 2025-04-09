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

def dicom_to_json(dcm_path, json_path):
    """Leest een DICOM-bestand en schrijft de volledige header weg als JSON."""
    try:
        ds = pydicom.dcmread(dcm_path)
        full_dict = dicom_dataset_to_dict(ds)

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(full_dict, f, indent=4, ensure_ascii=False)

        print(f"✅ DICOM header succesvol als JSON opgeslagen: {json_path}")

    except Exception as e:
        print(f"❌ Fout bij verwerken van DICOM-bestand: {e}")

# === SCRIPT UITVOERING ===

dicom_to_json(input_path, output_path)

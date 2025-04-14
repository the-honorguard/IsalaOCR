import os
import configparser
from datetime import datetime
from PIL import Image
import SimpleITK as sitk

# Pad naar het logbestand
LOGFILE = "/home/isala/ocr/IsalaOCR/logs/dcm2jpg_logs.txt"

def log_message(message):
    """
    Log een bericht naar zowel de terminal als het logbestand.
    """
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{current_time}] {message}"
    print(log_entry)
    with open(LOGFILE, 'a') as log:
        log.write(log_entry + "\n")

def dcm_to_jpg(dcm_path, output_dir):
    """Zet een DICOM-bestand om naar JPG."""
    try:
        dicom_image = sitk.ReadImage(dcm_path)
        sop_instance_uid = dicom_image.GetMetaData("0008|0018")
        log_message(f"SOP Instance UID: {sop_instance_uid}")

        pixel_data = sitk.GetArrayFromImage(dicom_image)
        for i in range(pixel_data.shape[0]):
            slice_data = pixel_data[i, :, :]
            image = Image.fromarray(slice_data)
            if image.mode != 'RGB':
                image = image.convert('RGB')
            output_path = os.path.join(output_dir, f"{sop_instance_uid}_slice_{i+1}.jpg")
            image.save(output_path, 'JPEG')
            log_message(f"Slice {i+1} opgeslagen als {output_path}")

    except Exception as e:
        log_message(f"Fout bij het converteren van DICOM naar JPG: {e}")

def is_dicom_file(file_path):
    """
    Controleer of een bestand een geldig DICOM-bestand is door de header te lezen.
    """
    try:
        with open(file_path, 'rb') as f:
            f.seek(128)  # Ga naar byte-offset 128
            header = f.read(4)  # Lees de volgende 4 bytes
            return header == b'DICM'  # Controleer of de header 'DICM' is
    except Exception as e:
        log_message(f"Fout bij controleren van bestand {file_path}: {e}")
        return False

def process_dicom_folder(input_dir, output_dir):
    """
    Doorzoek een map naar DICOM-bestanden en converteer ze naar JPG.
    """
    log_message(f"Start verwerking van DICOM-bestanden in {input_dir}")
    for root, _, files in os.walk(input_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if is_dicom_file(file_path):
                log_message(f"Verwerken van bestand: {file_path}")
                dcm_to_jpg(file_path, output_dir)
            else:
                log_message(f"Bestand overgeslagen (geen geldig DICOM-bestand): {file}")
    log_message(f"Verwerking voltooid. Output opgeslagen in {output_dir}")

if __name__ == "__main__":
    # Laad de configuratie
    config = configparser.ConfigParser()
    config_path = '/home/isala/ocr/IsalaOCR/config/mainconfig.ini'
    config.read(config_path)

    # Haal de juiste paden op uit de configuratie
    input_dir = config['paths']['dcm_in_folder']  # Map met DICOM-bestanden
    output_dir = config['paths']['jpg_out_folder']  # Map voor geconverteerde JPG-bestanden

    # Zorg ervoor dat de uitvoermap bestaat, anders maken we die aan
    os.makedirs(output_dir, exist_ok=True)

    # Zorg ervoor dat de logmap en het logbestand bestaan
    log_dir = os.path.dirname(LOGFILE)
    os.makedirs(log_dir, exist_ok=True)
    with open(LOGFILE, 'w') as log:
        log.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Logbestand aangemaakt.\n")

    # Verwerk alle DICOM-bestanden in de map
    process_dicom_folder(input_dir, output_dir)
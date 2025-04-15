import os
import configparser
from PIL import Image

# Bestanden & paden
INI_FILE = "/home/isala/ocr/IsalaOCR/config/roiconfig.ini"
IMAGE_FILE = "/home/isala/ocr/IsalaOCR/processing/jpg_out/1.3.6.1.4.1.49282.99.1.20250407111731.303881.1.1_slice_1.jpg"
OUTPUT_DIR = "/home/isala/ocr/IsalaOCR/processing/cropped_roi"

def read_roi_config(ini_file):
    """Lees ROI-configuraties uit .ini bestand en retourneer als dict {label: (left, top, right, bottom)}."""
    config = configparser.ConfigParser()
    config.read(ini_file)

    rois = {}
    for key, value in config['ROI'].items():
        try:
            label, coords = value.split(":")
            coords = tuple(map(int, coords.strip().split(',')))
            if len(coords) == 4:
                rois[label.strip()] = coords
            else:
                print(f"⚠️ Ongeldige coördinaten voor {key}: {coords}")
        except Exception as e:
            print(f"⚠️ Fout bij parsen van {key}: {e}")
    
    return rois

def crop_roi(image_file, coords):
    """Open afbeelding en crop het gebied."""
    try:
        with Image.open(image_file) as img:
            return img.crop(coords)
    except Exception as e:
        print(f"⚠️ Fout bij openen/croppen afbeelding: {e}")
        return None

def save_cropped(cropped_image, output_dir, label, original_filename):
    """Sla cropped afbeelding op met label achter bestandsnaam."""
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(original_filename))[0]
    output_path = os.path.join(output_dir, f"{base_name}_{label}.jpg")
    cropped_image.save(output_path)
    print(f"✅ Opgeslagen: {output_path}")

def main():
    rois = read_roi_config(INI_FILE)
    original_image_name = os.path.basename(IMAGE_FILE)

    for label, coords in rois.items():
        cropped = crop_roi(IMAGE_FILE, coords)
        if cropped:
            save_cropped(cropped, OUTPUT_DIR, label, IMAGE_FILE)

if __name__ == "__main__":
    main()

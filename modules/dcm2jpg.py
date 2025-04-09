import os
import SimpleITK as sitk
from PIL import Image
import numpy as np

def dcm_to_jpg(dcm_path, output_dir):
    """
    Zet een DICOM bestand met meerdere lagen (3D) om naar meerdere JPG afbeeldingen.
    
    Parameters:
    - dcm_path: pad naar het DICOM bestand.
    - output_dir: de map waar de gegenereerde JPG bestanden moeten worden opgeslagen.
    """
    try:
        # Lees het DICOM bestand met SimpleITK
        dicom_image = sitk.ReadImage(dcm_path)

        # Haal de SOP Instance UID op uit de metadata
        sop_instance_uid = dicom_image.GetMetaData("0008|0018")
        print(f"SOP Instance UID: {sop_instance_uid}")

        # Haal de 3D pixeldata op als een numpy array
        pixel_data = sitk.GetArrayFromImage(dicom_image)
        print(f"Pixeldata van het DICOM bestand: {pixel_data.shape}")

        # Controleer of het DICOM bestand meerdere lagen heeft (3D)
        if len(pixel_data.shape) < 3:
            raise ValueError(f"Het DICOM bestand is 2D, niet 3D. Dit script ondersteunt alleen 3D DICOM bestanden.")

        # Loop door alle lagen (slices) en sla ze op als JPG
        for i in range(pixel_data.shape[0]):
            # Verkrijg de laag (slice)
            slice_data = pixel_data[i, :, :]

            # Converteer de numpy array naar een PIL afbeelding
            image = Image.fromarray(slice_data)

            # Als de afbeelding een andere kleurmodus heeft, converteer deze naar RGB
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Sla de afbeelding op als JPG met de SOP Instance UID en slice nummer
            output_path = os.path.join(output_dir, f"{sop_instance_uid}_slice_{i+1}.jpg")
            image.save(output_path, 'JPEG')
            print(f"Slice {i+1} opgeslagen als {output_path}")

    except Exception as e:
        print(f"Fout bij het converteren van DICOM naar JPG: {e}")

if __name__ == "__main__":
    # Definieer de locatie van het DICOM-bestand en de uitvoermap
    dcm_path = '/home/isala/ocr/IsalaOCR/dcm_in/EE352F8D'  # Geef het pad naar het DICOM-bestand op
    output_dir = '/home/isala/ocr/IsalaOCR/processing/jpg_out'  # Geef de uitvoermap op

    # Zorg ervoor dat de uitvoermap bestaat, anders maken we die aan
    os.makedirs(output_dir, exist_ok=True)

    # Converteer het DICOM-bestand naar JPG
    dcm_to_jpg(dcm_path, output_dir)

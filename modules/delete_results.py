import os

# Pad naar het OCR-resultatenbestand
output_file = '/home/isala/ocr/ocr_results.txt'

def process(img_data, image_path):
    try:
        # Verwijder het bestand als het bestaat
        if os.path.exists(output_file):
            os.remove(output_file)
            print(f"{output_file} is verwijderd.")
        else:
            print(f"{output_file} bestaat niet, geen bestand om te verwijderen.")
        
        # Retourneer de img_data ongewijzigd (hier zou je meer logica kunnen toevoegen als dat nodig is)
        return img_data

    except Exception as e:
        print(f"Fout bij het verwijderen van het resultaatbestand: {e}")
        return img_data

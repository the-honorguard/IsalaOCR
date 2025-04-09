import cv2
import os
import configparser

# Pad naar de hoofdmap waar de config.ini zich bevindt
config_path = os.path.join(os.path.dirname(__file__), '..', 'config.ini')

# Config inladen
config = configparser.ConfigParser()
config.read(config_path)

# Gebruik de map voor preread images uit de config
preread_folder = config['paths']['preread_folder']

def process(img_data, image_path):
    """
    Toon de afbeelding zoals deze uitgelezen zal worden door OCR en sla deze op in de gedefinieerde map.
    
    Parameters:
    - img_data: de afbeelding die moet worden verwerkt.
    - image_path: het pad naar de afbeelding.
    
    Retourneert:
    - img_data: de originele of bewerkte afbeelding (zoals deze door OCR gelezen gaat worden).
    """
    if img_data is None:
        img_data = cv2.imread(image_path)

    if img_data is None:
        raise ValueError(f"De afbeelding op {image_path} kon niet worden geladen.")

    # Toon de afbeelding die we gaan uitlezen
    cv2.imshow('Afbeelding voor OCR', img_data)
    cv2.waitKey(0)  # Wacht op een toets om verder te gaan
    cv2.destroyAllWindows()

    # Verkrijg de naam van het bestand en sla de afbeelding op in de gedefinieerde map
    output_image_path = os.path.join(preread_folder, os.path.basename(image_path))
    cv2.imwrite(output_image_path, img_data)
    print(f"Afbeelding opgeslagen in {output_image_path}")

    # Retourneer de afbeelding (die eventueel nog verder verwerkt kan worden)
    return img_data

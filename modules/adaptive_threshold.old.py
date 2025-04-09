import cv2
import numpy as np
from screeninfo import get_monitors

def process(img_data, image_path):
    if img_data is None:
        img_data = cv2.imread(image_path)

    if img_data is None:
        raise ValueError(f"De afbeelding op {image_path} kon niet worden geladen.")

    # Zet de afbeelding om naar grijswaarden (om eenvoudiger de drempel te kunnen toepassen)
    gray = cv2.cvtColor(img_data, cv2.COLOR_BGR2GRAY)

    # Verkrijg de resolutie van het primaire scherm
    monitor = get_monitors()[0]
    screen_width = monitor.width
    screen_height = monitor.height

    # Verklein de afbeelding voor de voorvertoning zodat het past op je scherm
    height, width = gray.shape
    scaling_factor = min(screen_width / width, screen_height / height)  # Bepaal de schaalverhouding

    # Verklein de afbeelding voor de voorvertoning
    resized_image = cv2.resize(gray, (int(width * scaling_factor), int(height * scaling_factor)))

    # Functie om de adaptive threshold toe te passen met de opgegeven parameters
    def apply_adaptive_threshold(val):
        # Zorg ervoor dat de drempelparameter binnen een geldig bereik valt (bijv. maxValue = 255)
        max_value = 255
        adaptive_thresh = cv2.adaptiveThreshold(
            resized_image, max_value, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 11, val)
        cv2.imshow("Adaptive Threshold Voorvertoning", adaptive_thresh)

    # Maak een window om de afbeelding te tonen
    cv2.imshow("Adaptive Threshold Voorvertoning", resized_image)

    # Maak een slider voor de drempelwaarde (de laatste parameter van de adaptiveThreshold)
    cv2.createTrackbar("C (Aangepaste drempel)", "Adaptive Threshold Voorvertoning", 10, 50, apply_adaptive_threshold)

    # Wacht totdat de gebruiker het venster sluit
    print("Gebruik de slider om de C-waarde aan te passen. Druk op 'q' om te bevestigen en het venster te sluiten.")
    while True:
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):  # Druk op 'q' om de afbeelding op te slaan en het venster te sluiten
            break

    # Haal de C-waarde op van de slider en pas de adaptive threshold toe op de originele afbeelding
    C_value = cv2.getTrackbarPos("C (Aangepaste drempel)", "Adaptive Threshold Voorvertoning")
    max_value = 255
    final_adaptive_thresh = cv2.adaptiveThreshold(
        gray, max_value, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 11, C_value)

    # Sluit het OpenCV venster
    cv2.destroyAllWindows()

    return final_adaptive_thresh

# Voorbeeld van hoe je de module kunt aanroepen
if __name__ == "__main__":
    img_path = "pad/naar/jouw/afbeelding.jpg"  # Vul het pad naar de afbeelding in
    final_image = process(None, img_path)

    # Toon de verwerkte afbeelding met adaptive threshold
    cv2.imshow("Verwerkte Afbeelding", final_image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

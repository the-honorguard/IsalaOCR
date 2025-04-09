import cv2
import numpy as np
from screeninfo import get_monitors

def process(img_data, image_path):
    if img_data is None:
        img_data = cv2.imread(image_path)

    if img_data is None:
        raise ValueError(f"De afbeelding op {image_path} kon niet worden geladen.")

    # Zet de afbeelding om naar grijswaarden
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

    # Verklein de afbeelding met 10% extra (daarna krijgen we een 10% kleinere weergave)
    resized_image = cv2.resize(resized_image, (int(resized_image.shape[1] * 0.9), int(resized_image.shape[0] * 0.9)))

    # Functie om de afbeelding met drempel aan te passen
    def update_threshold(val):
        _, bw_image = cv2.threshold(resized_image, val, 255, cv2.THRESH_BINARY)
        cv2.imshow("Zwart-Wit Voorvertoning", bw_image)

    # Maak een window om de afbeelding te tonen
    cv2.imshow("Zwart-Wit Voorvertoning", resized_image)

    # Maak een slider voor de drempelwaarde
    cv2.createTrackbar("Drempel", "Zwart-Wit Voorvertoning", 127, 255, update_threshold)

    # Wacht totdat de gebruiker het venster sluit
    print("Gebruik de slider om de drempelwaarde aan te passen. Druk op 'q' om te bevestigen en de afbeelding op te slaan.")
    while True:
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):  # Druk op 'q' om de afbeelding op te slaan en het venster te sluiten
            break

    # Haal de drempelwaarde op en voer de definitieve conversie uit
    threshold_value = cv2.getTrackbarPos("Drempel", "Zwart-Wit Voorvertoning")
    _, final_bw_image = cv2.threshold(gray, threshold_value, 255, cv2.THRESH_BINARY)

    # Sluit het OpenCV venster
    cv2.destroyAllWindows()

    return final_bw_image

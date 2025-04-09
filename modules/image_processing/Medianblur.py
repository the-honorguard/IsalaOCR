import cv2
import numpy as np
from screeninfo import get_monitors

def process(img_data, image_path):
    if img_data is None:
        img_data = cv2.imread(image_path)

    if img_data is None:
        raise ValueError(f"De afbeelding op {image_path} kon niet worden geladen.")

    # Zet de afbeelding om naar grijswaarden (optioneel)
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

    # Functie om de median blur toe te passen met de opgegeven kernelgrootte
    def apply_median_blur(val):
        # Zorg ervoor dat de kernelgrootte altijd een oneven getal is
        if val % 2 == 0:
            val += 1
        blurred_image = cv2.medianBlur(resized_image, val)
        cv2.imshow("Median Blur Voorvertoning", blurred_image)

    # Maak een window om de afbeelding te tonen
    cv2.imshow("Median Blur Voorvertoning", resized_image)

    # Maak een slider voor de kernelgrootte
    cv2.createTrackbar("Kernel grootte", "Median Blur Voorvertoning", 3, 49, apply_median_blur)

    # Wacht totdat de gebruiker het venster sluit
    print("Gebruik de slider om de kernelgrootte aan te passen. Druk op 'q' om te bevestigen en het venster te sluiten.")
    while True:
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):  # Druk op 'q' om de afbeelding op te slaan en het venster te sluiten
            break

    # Haal de kernelgrootte op en pas median blur toe op de originele afbeelding
    kernel_size = cv2.getTrackbarPos("Kernel grootte", "Median Blur Voorvertoning")
    if kernel_size % 2 == 0:
        kernel_size += 1  # Zorg ervoor dat het een oneven getal is

    final_blurred_image = cv2.medianBlur(gray, kernel_size)

    # Sluit het OpenCV venster
    cv2.destroyAllWindows()

    return final_blurred_image

# Voorbeeld van hoe je de module kunt aanroepen
if __name__ == "__main__":
    img_path = "pad/naar/jouw/afbeelding.jpg"  # Vul het pad naar de afbeelding in
    final_image = process(None, img_path)

    # Toon de verwerkte afbeelding met median blur
    cv2.imshow("Verwerkte Afbeelding", final_image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

import cv2

# Variabelen voor muisinteracties
drawing = False  # True als de muis wordt ingedrukt
ix, iy = -1, -1

def select_roi_manueel(img):
    """
    Laat de gebruiker een regio van de afbeelding selecteren door een rechthoek te tekenen.
    
    Parameters:
    - img: De afbeelding waaruit de regio geselecteerd moet worden.

    Retourneert:
    - Het geselecteerde gedeelte van de afbeelding.
    """
    drawing = False  # Variabele die bijhoudt of er wordt getekend
    ix, iy = -1, -1  # Startpositie van het rechthoek
    rect = (0, 0, 0, 0)  # Dit is de regio die we zullen selecteren
    offset = 5  # Het aantal pixels dat de groene border buiten de geselecteerde regio zichtbaar is

    def draw_rectangle(event, x, y, flags, param):
        nonlocal drawing, ix, iy, rect, img, offset
        if event == cv2.EVENT_LBUTTONDOWN:
            drawing = True
            ix, iy = x, y
        elif event == cv2.EVENT_MOUSEMOVE:
            if drawing:
                # Maak een kopie van de originele afbeelding om de tekening te updaten
                clone = img.copy()
                # Teken de groene border met een offset buiten het geselecteerde gebied
                cv2.rectangle(clone, (ix - offset, iy - offset), (x + offset, y + offset), (0, 255, 0), 2)
                cv2.imshow("Selecteer regio (druk op 's' om op te slaan)", clone)
        elif event == cv2.EVENT_LBUTTONUP:
            drawing = False
            # Werk de rect bij na het loslaten van de muisknop
            rect = (min(ix, x), min(iy, y), abs(x - ix), abs(y - iy))
            # Teken de groene border met een offset buiten het geselecteerde gebied
            cv2.rectangle(img, (ix - offset, iy - offset), (x + offset, y + offset), (0, 255, 0), 2)
            cv2.imshow("Selecteer regio (druk op 's' om op te slaan)", img)

    cv2.namedWindow("Selecteer regio (druk op 's' om op te slaan)")
    cv2.setMouseCallback("Selecteer regio (druk op 's' om op te slaan)", draw_rectangle)

    while True:
        cv2.imshow("Selecteer regio (druk op 's' om op te slaan)", img)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("s"):  # Sla de geselecteerde regio op
            break
        elif key == 27:  # ESC om af te sluiten zonder selectie
            rect = (0, 0, 0, 0)
            break

    cv2.destroyAllWindows()

    # Retourneer de geselecteerde regio zonder de groene border
    x, y, w, h = rect
    if w == 0 or h == 0:
        print("Geen regio geselecteerd.")
        return None
    # Zorg ervoor dat we de originele afbeelding gebruiken zonder de groene border
    return img[y:y + h, x:x + w]

def process(img_data, image_path):
    """
    Verwerk de afbeelding door een regio handmatig te selecteren en toon de groene rechthoek alleen tijdens het tekenen.
    
    Parameters:
    - img_data: de afbeelding die moet worden verwerkt.
    - image_path: het pad naar de afbeelding (wordt alleen gebruikt als img_data None is).

    Retourneert:
    - Het geselecteerde gedeelte van de afbeelding.
    """
    if img_data is None:
        img_data = cv2.imread(image_path)

    if img_data is None:
        raise ValueError(f"De afbeelding op {image_path} kon niet worden geladen.")

    print(f"Afbeelding ingelezen: {image_path}")
    print(f"Afbeelding grootte: {img_data.shape}")

    if len(img_data.shape) != 3:
        img_data = cv2.cvtColor(img_data, cv2.COLOR_GRAY2BGR)

    # Laat de gebruiker een regio selecteren
    geselecteerde_regio = select_roi_manueel(img_data)
    
    # De geselecteerde regio wordt hier niet opgeslagen, enkel teruggegeven
    return geselecteerde_regio

# Voorbeeld van gebruik
if __name__ == "__main__":
    img_path = "pad/naar/jouw/afbeelding.jpg"  # Vul het pad naar de afbeelding in
    geselecteerde_regio = process(None, img_path)
    
    # Je kunt hier de geselecteerde regio gebruiken zoals gewenst
    if geselecteerde_regio is not None:
        cv2.imshow("Geselecteerde Regio", geselecteerde_regio)
        cv2.waitKey(0)
        cv2.destroyAllWindows()

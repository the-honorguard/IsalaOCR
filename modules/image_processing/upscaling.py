import cv2

def process(img_data, image_path, scale_factor=2):
    if img_data is None:
        img_data = cv2.imread(image_path)

    # Verkrijg de huidige afmetingen van de afbeelding
    height, width, channels = img_data.shape

    # Bereken de nieuwe afmetingen
    new_width = int(width * scale_factor)
    new_height = int(height * scale_factor)

    # Upscale de afbeelding met de nieuwe afmetingen
    upscaled_img = cv2.resize(img_data, (new_width, new_height), interpolation=cv2.INTER_CUBIC)

    return upscaled_img

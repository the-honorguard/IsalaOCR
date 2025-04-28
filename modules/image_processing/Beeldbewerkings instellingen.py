import sys
import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QPushButton, QSlider, QFileDialog, QLineEdit, QHBoxLayout
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QImage

class ImageProcessingApp(QWidget):
    def __init__(self):
        super().__init__()

        self.init_ui()
        
    def init_ui(self):
        # Initialize the layout and widgets
        self.setWindowTitle('Adaptive Threshold and Gaussian Blur')
        self.setGeometry(100, 100, 800, 600)
        
        # Layouts
        self.layout = QVBoxLayout(self)
        
        # Image Display Label
        self.image_label = QLabel(self)
        self.layout.addWidget(self.image_label)
        
        # Buttons and Sliders for Image Processing
        self.load_button = QPushButton('Load Image', self)
        self.layout.addWidget(self.load_button)
        self.load_button.clicked.connect(self.load_image)
        
        # Adaptive Threshold Block Size Slider
        self.adaptive_thresh_block_label = QLabel('Adaptive Threshold Block Size: 3', self)
        self.layout.addWidget(self.adaptive_thresh_block_label)
        self.adaptive_thresh_block_slider = QSlider(Qt.Horizontal, self)
        self.adaptive_thresh_block_slider.setRange(3, 21)  # Block size (odd numbers)
        self.adaptive_thresh_block_slider.setValue(3)
        self.layout.addWidget(self.adaptive_thresh_block_slider)
        self.adaptive_thresh_block_slider.valueChanged.connect(self.update_image)
        
        # Adaptive Threshold Constant Slider
        self.adaptive_thresh_c_label = QLabel('Adaptive Threshold C: 2', self)
        self.layout.addWidget(self.adaptive_thresh_c_label)
        self.adaptive_thresh_c_slider = QSlider(Qt.Horizontal, self)
        self.adaptive_thresh_c_slider.setRange(0, 20)  # C constant
        self.adaptive_thresh_c_slider.setValue(2)
        self.layout.addWidget(self.adaptive_thresh_c_slider)
        self.adaptive_thresh_c_slider.valueChanged.connect(self.update_image)
        
        # Gaussian Blur Slider
        self.gaussian_blur_label = QLabel('Gaussian Blur: 1', self)
        self.layout.addWidget(self.gaussian_blur_label)
        self.gaussian_blur_slider = QSlider(Qt.Horizontal, self)
        self.gaussian_blur_slider.setRange(1, 15)
        self.gaussian_blur_slider.setValue(1)
        self.layout.addWidget(self.gaussian_blur_slider)
        self.gaussian_blur_slider.valueChanged.connect(self.update_image)
        
        # Values Output
        self.config_output_label = QLabel('Config Output:', self)
        self.layout.addWidget(self.config_output_label)
        
        self.config_output = QLineEdit(self)
        self.layout.addWidget(self.config_output)
        
        # Show the GUI
        self.show()
        
        # Variables for the image and processing values
        self.image = None
        self.processed_image = None

    def load_image(self):
        # Let the user select an image file
        file_path, _ = QFileDialog.getOpenFileName(self, 'Open Image', '', 'Images (*.png *.jpg *.bmp)')
        if file_path:
            self.image = cv2.imread(file_path)
            self.update_image()

    def update_image(self):
        if self.image is None:
            return
        
        # Get the current slider values
        adaptive_thresh_block_size = self.adaptive_thresh_block_slider.value()
        adaptive_thresh_c = self.adaptive_thresh_c_slider.value()
        gaussian_blur_value = self.gaussian_blur_slider.value()

        # Apply Gaussian Blur
        blurred_image = cv2.GaussianBlur(self.image, (gaussian_blur_value * 2 + 1, gaussian_blur_value * 2 + 1), 0)

        # Apply Adaptive Thresholding
        thresh_image = cv2.adaptiveThreshold(
            cv2.cvtColor(blurred_image, cv2.COLOR_BGR2GRAY),
            255,
            cv2.ADAPTIVE_THRESH_MEAN_C,
            cv2.THRESH_BINARY,
            adaptive_thresh_block_size | 1,  # Block size must be odd (set to odd number)
            adaptive_thresh_c  # Constant subtracted from the mean
        )

        # Convert to RGB for displaying in PyQt
        height, width = thresh_image.shape
        bytes_per_line = width
        q_image = QImage(thresh_image.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(q_image)

        # Update the image label with the processed image
        self.image_label.setPixmap(pixmap)
        
        # Update the config output
        config_string = f'Block Size: {adaptive_thresh_block_size}, C: {adaptive_thresh_c}, Gaussian Blur: {gaussian_blur_value}'
        self.config_output.setText(config_string)

    def get_config_values(self):
        # Return the current configuration values as a string
        adaptive_thresh_block_size = self.adaptive_thresh_block_slider.value()
        adaptive_thresh_c = self.adaptive_thresh_c_slider.value()
        gaussian_blur_value = self.gaussian_blur_slider.value()
        return f'Block Size: {adaptive_thresh_block_size}, C: {adaptive_thresh_c}, Gaussian Blur: {gaussian_blur_value}'

def main():
    app = QApplication(sys.argv)
    window = ImageProcessingApp()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()

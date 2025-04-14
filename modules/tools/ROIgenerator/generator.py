import sys
import configparser
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QFileDialog, QVBoxLayout, QWidget, QSlider, QHBoxLayout, QLineEdit,
    QMessageBox, QInputDialog, QScrollArea, QDialog
)
from PyQt5.QtGui import QPixmap, QPainter, QPen
from PyQt5.QtCore import Qt, QRect, QPointF, QPoint


class ScrollLabel(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)  # Pijl cursor in plaats van handje
        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
            self._drag_pos = event.globalPos()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos:
            diff = event.globalPos() - self._drag_pos
            self._drag_pos = event.globalPos()
            scroll_area = self.parent().parent()
            scroll_area.horizontalScrollBar().setValue(scroll_area.horizontalScrollBar().value() - diff.x())
            scroll_area.verticalScrollBar().setValue(scroll_area.verticalScrollBar().value() - diff.y())
            event.accept()

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.ArrowCursor)  # Cursor weer terug naar pijl
        self._drag_pos = None
        event.accept()


class CropImageApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Cropper with Zoom & Pan (PyQt5)")

        self.image_label = ScrollLabel(self)
        self.image_label.setStyleSheet("background-color: white")

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setWidgetResizable(True)

        self.load_button = QPushButton("Laad Afbeelding")
        self.load_button.clicked.connect(self.load_image)

        self.zoom_slider = QSlider(Qt.Vertical)
        self.zoom_slider.setMinimum(10)
        self.zoom_slider.setMaximum(300)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setTickInterval(10)
        self.zoom_slider.setTickPosition(QSlider.TicksRight)  # Tics aan de rechterkant
        self.zoom_slider.valueChanged.connect(self.zoom_changed)

        self.zoom_label = QLabel("Zoom: 100%")
        self.zoom_slider.valueChanged.connect(self.update_zoom_label)

        self.label_input = QLineEdit()
        self.confirm_button = QPushButton("Bevestig ROI")
        self.confirm_button.clicked.connect(self.confirm_roi)

        self.roi_list = QListWidget()
        self.roi_list.itemDoubleClicked.connect(self.edit_roi_label)

        self.edit_button = QPushButton("Bewerk geselecteerde ROI")
        self.edit_button.clicked.connect(self.edit_selected_roi)

        self.remove_button = QPushButton("Verwijder geselecteerde ROI")
        self.remove_button.clicked.connect(self.remove_selected_roi)

        self.save_button = QPushButton("Exporteer ROIs naar INI")
        self.save_button.clicked.connect(self.export_rois)

        # Knop voor het aanmaken van een nieuw config-bestand
        self.new_config_button = QPushButton("Maak nieuw Config bestand")
        self.new_config_button.clicked.connect(self.create_new_config_file)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.load_button)
        right_layout.addWidget(QLabel("Zoom"))
        right_layout.addWidget(self.zoom_slider)
        right_layout.addWidget(self.zoom_label)  # Voeg zoom label toe
        right_panel = QWidget()
        right_panel.setLayout(right_layout)

        control_layout = QVBoxLayout()
        control_layout.addWidget(QLabel("Label"))
        control_layout.addWidget(self.label_input)
        control_layout.addWidget(self.confirm_button)
        control_layout.addWidget(self.roi_list)
        control_layout.addWidget(self.edit_button)
        control_layout.addWidget(self.remove_button)
        control_layout.addWidget(self.save_button)
        control_layout.addWidget(self.new_config_button)  # Voeg de knop toe voor nieuw config-bestand
        control_panel = QWidget()
        control_panel.setLayout(control_layout)

        main_layout = QHBoxLayout()
        main_layout.addWidget(self.scroll_area)
        main_layout.addWidget(right_panel)
        main_layout.addWidget(control_panel)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.original_pixmap = None
        self.zoom_factor = 1.0
        self.rois = []

        self.drawing = False
        self.start_point = None
        self.end_point = None

        self.image_label.mousePressEvent = self.start_draw
        self.image_label.mouseMoveEvent = self.update_draw
        self.image_label.mouseReleaseEvent = self.finish_draw

        # Config laden bij de start van de applicatie
        self.config = configparser.ConfigParser()

        self.load_ini_on_start()

    def load_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Image", "", "Image Files (*.png *.jpg *.jpeg)")
        if file_path:
            self.original_pixmap = QPixmap(file_path)
            self.zoom_factor = self.zoom_slider.value() / 100.0
            self.display_image()

    def display_image(self):
        if self.original_pixmap:
            scaled = self.original_pixmap.scaled(
                self.original_pixmap.size() * self.zoom_factor,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
            self.repaint_image_with_roi_preview()

    def zoom_changed(self, value):
        self.zoom_factor = value / 100.0
        self.display_image()

    def update_zoom_label(self, value):
        """Update de zoomwaarde in de UI bij schuiven van de zoomslider."""
        self.zoom_label.setText(f"Zoom: {value}%")

    def to_original_coords(self, point):
        return QPointF(point.x() / self.zoom_factor, point.y() / self.zoom_factor)

    def to_scaled_coords(self, x, y):
        return int(x * self.zoom_factor), int(y * self.zoom_factor)

    def start_draw(self, event):
        if event.button() == Qt.RightButton:
            return ScrollLabel.mousePressEvent(self.image_label, event)
        self.drawing = True
        self.start_point = event.pos()
        self.end_point = self.start_point

    def update_draw(self, event):
        if self.drawing:
            self.end_point = event.pos()
            self.repaint_image_with_roi_preview()
        else:
            ScrollLabel.mouseMoveEvent(self.image_label, event)

    def finish_draw(self, event):
        if event.button() == Qt.RightButton:
            return ScrollLabel.mouseReleaseEvent(self.image_label, event)
        self.drawing = False
        self.end_point = event.pos()
        self.repaint_image_with_roi_preview()

    def repaint_image_with_roi_preview(self):
        if not self.original_pixmap:
            return

        scaled = self.original_pixmap.scaled(
            self.original_pixmap.size() * self.zoom_factor,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        painter = QPainter(scaled)
        pen = QPen(Qt.red, 2, Qt.SolidLine)
        painter.setPen(pen)

        if self.start_point and self.end_point:
            rect = QRect(self.start_point, self.end_point)
            painter.drawRect(rect)

        for label, (x1, y1, x2, y2) in self.rois:
            sx1, sy1 = self.to_scaled_coords(x1, y1)
            sx2, sy2 = self.to_scaled_coords(x2, y2)
            painter.drawRect(QRect(sx1, sy1, sx2 - sx1, sy2 - sy1))
            painter.drawText(sx1 + 2, sy1 - 4, label)

        painter.end()
        self.image_label.setPixmap(scaled)

    def confirm_roi(self):
        if self.start_point and self.end_point:
            label = self.label_input.text().strip()
            if not label:
                QMessageBox.warning(self, "Leeg label", "Geef een label op voor de ROI.")
                return

            sp = self.to_original_coords(self.start_point)
            ep = self.to_original_coords(self.end_point)
            x1, y1 = int(min(sp.x(), ep.x())), int(min(sp.y(), ep.y()))
            x2, y2 = int(max(sp.x(), ep.x())), int(max(sp.y(), ep.y()))
            self.rois.append((label, (x1, y1, x2, y2)))
            self.roi_list.addItem(f"{label}: ({x1}, {y1}, {x2}, {y2})")

            self.label_input.clear()
            self.repaint_image_with_roi_preview()

    def remove_selected_roi(self):
        index = self.roi_list.currentRow()
        if index >= 0:
            del self.rois[index]
            self.roi_list.takeItem(index)
            self.repaint_image_with_roi_preview()

    def edit_roi_label(self, item: QListWidgetItem):
        index = self.roi_list.row(item)
        current_label, coords = self.rois[index]
        new_label, ok = QInputDialog.getText(self, "Bewerk label", "Nieuw label:", text=current_label)
        if ok and new_label.strip():
            self.rois[index] = (new_label.strip(), coords)
            self.roi_list.item(index).setText(f"{new_label.strip()}: {coords}")
            self.repaint_image_with_roi_preview()

    def edit_selected_roi(self):
        index = self.roi_list.currentRow()
        if index >= 0:
            current_label, current_coords = self.rois[index]
            dialog = EditRoiDialog(self, current_label, current_coords)
            if dialog.exec_():
                result = dialog.get_data()
                if result:
                    label, coords = result
                    self.rois[index] = (label, coords)
                    self.roi_list.item(index).setText(f"{label}: {coords}")
                    self.repaint_image_with_roi_preview()
                else:
                    QMessageBox.warning(self, "Ongeldige invoer", "Alle waarden moeten gehele getallen zijn.")

    def export_rois(self):
        if not self.rois:
            QMessageBox.information(self, "Geen ROIs", "Er zijn geen ROIs om op te slaan.")
            return

        # Bijwerken van de 'rois' sectie in het INI-bestand
        for index, (label, (x1, y1, x2, y2)) in enumerate(self.rois):
            self.config.set('ROI', f'roi_{index + 1}', f'{label}:{x1},{y1},{x2},{y2}')

        # Schrijf het bijgewerkte INI-bestand naar disk
        with open('config.ini', 'w') as configfile:
            self.config.write(configfile)

        QMessageBox.information(self, "Succes", "ROIs zijn succesvol opgeslagen in config.ini.")

    def load_ini_on_start(self):
        # Laad de ROIs en andere configuratie bij opstarten
        try:
            self.config.read('config.ini')
            if 'ROI' in self.config.sections():
                for key in self.config['ROI']:
                    label, coords = self.config[key].split(':')
                    x1, y1, x2, y2 = map(int, coords.split(','))
                    self.rois.append((label, (x1, y1, x2, y2)))
                    self.roi_list.addItem(f"{label}: ({x1}, {y1}, {x2}, {y2})")
                self.repaint_image_with_roi_preview()
        except Exception as e:
            QMessageBox.warning(self, "Fout", f"Kon de config niet laden: {str(e)}")

    def create_new_config_file(self):
        # Dialoogvenster om het bestand op te slaan
        file_path, _ = QFileDialog.getSaveFileName(self, "Opslaan als nieuw Config bestand", "", "INI Files (*.ini)")
        if file_path:
            # Maak een nieuwe ConfigParser instantie
            config = configparser.ConfigParser()

            # Voeg secties en configuratie toe
            config.add_section('paths')
            config.set('paths', 'image_folder', 'jpg_out')
            config.set('paths', 'output_file', 'report_out')
            config.set('paths', 'modules_folder', 'modules')
            config.set('paths', 'preread_folder', 'preread_image')
            config.set('paths', 'temp_folder', 'temp')

            config.add_section('ocr')
            config.set('ocr', 'language', 'en')
            config.set('ocr', 'generate_image', 'false')

            config.add_section('modules')
            config.set('modules', 'enabled', 'delete_results, select_region, adaptive_threshold, preread_image_display')

            # Voeg de ROIs toe aan de 'ROI' sectie van de nieuwe config
            if self.rois:
                config.add_section('ROI')  # Voeg de ROI sectie toe
                for index, (label, (x1, y1, x2, y2)) in enumerate(self.rois):
                    config.set('ROI', f'roi_{index + 1}', f'{label}:{x1},{y1},{x2},{y2}')

            # Sla het nieuwe config-bestand op
            with open(file_path, 'w') as configfile:
                config.write(configfile)

            QMessageBox.information(self, "Succes", f"Het nieuwe config-bestand is succesvol opgeslagen: {file_path}")


class EditRoiDialog(QDialog):
    def __init__(self, parent, label, coords):
        super().__init__(parent)
        self.setWindowTitle("Bewerk ROI")
        self.label = QLineEdit(label, self)
        self.coords = [QLineEdit(str(coord), self) for coord in coords]

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Label"))
        layout.addWidget(self.label)

        for i, coord in enumerate(self.coords):
            layout.addWidget(QLabel(f"Coördinaat {i+1}"))
            layout.addWidget(coord)

        self.save_button = QPushButton("Opslaan", self)
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)

        self.setLayout(layout)

    def get_data(self):
        try:
            label = self.label.text().strip()
            coords = [int(coord.text()) for coord in self.coords]
            if len(coords) == 4:
                return label, tuple(coords)
            return None
        except ValueError:
            return None

    def save(self):
        data = self.get_data()
        if data:
            self.accept()
        else:
            QMessageBox.warning(self, "Fout", "Alle velden moeten ingevuld zijn met geldige waarden.")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = CropImageApp()
    window.show()
    sys.exit(app.exec_())

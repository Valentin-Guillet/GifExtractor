import argparse
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, QUrl
from PyQt6.QtGui import QBrush, QKeyEvent, QMouseEvent, QPainter, QPen
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


def parseArgs():
    parser = argparse.ArgumentParser()
    parser.add_argument("videoPath", type=str, nargs="?")
    return parser.parse_args()


class Overlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setStyleSheet("background: red;")

        self.startPos: Optional[QPoint] = None
        self.endPos: Optional[QPoint] = None

    def paintEvent(self, _):
        if self.startPos is None or self.endPos is None:
            return

        print("PAINTING")
        x1, x2 = min(self.startPos.x(), self.endPos.x()), max(self.startPos.x(), self.endPos.x())
        y1, y2 = min(self.startPos.y(), self.endPos.y()), max(self.startPos.y(), self.endPos.y())
        selectionRect = QRect(QPoint(x1, y1), QPoint(x2, y2))
        painter = QPainter(self)
        painter.setPen(QPen(Qt.GlobalColor.red, 2))
        painter.setBrush(QBrush(Qt.GlobalColor.red))
        painter.drawRect(selectionRect)
        painter.end()


class VideoPlayer(QMainWindow):
    def __init__(self, videoPath):
        super().__init__()

        self.setWindowTitle("MP4 to GIF Extractor")
        self.showMaximized()

        self.mediaPlayer = QMediaPlayer(self)
        self.videoWidget = QVideoWidget(self)
        self.mediaPlayer.setVideoOutput(self.videoWidget)

        # Overlay for drawing
        # self.overlay = Overlay(self)
        self.overlay = Overlay(self.videoWidget)
        self.overlay.setGeometry(self.videoWidget.geometry())
        self.overlay.raise_()
        self.overlay.show()

        self.startFrame = None
        self.endFrame = None
        self.playbackSpeeds = [0.25, 0.5, 1, 1.5, 2, 3, 4, 8]
        self.currentSpeedIndex = self.playbackSpeeds.index(1)
        self.timer = QTimer(self)
        self.timer.setInterval(15)
        self.timer.timeout.connect(self.updateProgressBar)

        self.initUi()
        self.loadVideo(videoPath)

    def initUi(self):
        # Main layout
        centralWidget = QWidget(self)
        layout = QVBoxLayout()
        centralWidget.setLayout(layout)
        self.setCentralWidget(centralWidget)

        # Video display
        layout.addWidget(self.videoWidget)
        # layout.addWidget(self.overlay)
        self.overlay.setGeometry(self.videoWidget.geometry())

        # Controls
        self.progressSlider = QSlider(Qt.Orientation.Horizontal, self)
        self.progressSlider.setRange(0, 1000)
        self.progressSlider.sliderReleased.connect(self.seekVideo)
        layout.addWidget(self.progressSlider)

        controls = QWidget(self)
        controlLayout = QVBoxLayout(controls)

        self.openButton = QPushButton("Open Video", self)
        self.openButton.clicked.connect(self.openVideo)
        controlLayout.addWidget(self.openButton)

        self.startButton = QPushButton("Mark Start Frame", self)
        self.startButton.clicked.connect(self.markStartFrame)
        controlLayout.addWidget(self.startButton)

        self.endButton = QPushButton("Mark End Frame", self)
        self.endButton.clicked.connect(self.markEndFrame)
        controlLayout.addWidget(self.endButton)

        self.extractButton = QPushButton("Extract GIF", self)
        self.extractButton.clicked.connect(self.extractGif)
        controlLayout.addWidget(self.extractButton)

        self.statusLabel = QLabel("Status: Ready", self)
        controlLayout.addWidget(self.statusLabel)

        layout.addWidget(controls)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'overlay'):
            self.overlay.setGeometry(self.videoWidget.geometry())

    def openVideo(self):
        filePath, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "", "Video Files (*.mp4 *.avi *.mkv)"
        )
        self.loadVideo(filePath)

    def loadVideo(self, filePath):
        if not filePath:
            return
        if not Path(filePath).is_file():
            print(f"No such file {filePath}")
        self.mediaPlayer.setSource(QUrl.fromLocalFile(str(filePath)))
        self.mediaPlayer.play()
        self.timer.start()

    def markStartFrame(self):
        self.startFrame = self.mediaPlayer.position()
        self.statusLabel.setText(f"Start frame marked at {self.startFrame} ms")

    def markEndFrame(self):
        self.endFrame = self.mediaPlayer.position()
        self.statusLabel.setText(f"End frame marked at {self.endFrame} ms")

    def extractGif(self):
        pass
        # if (
        #     self.startFrame is not None
        #     and self.endFrame is not None
        #     and self.selectionRect.isValid()
        # ):
        #     # Placeholder for GIF extraction logic
        #     self.statusLabel.setText("GIF extraction started...")
        #     # Implement GIF extraction with tools like MoviePy or FFmpeg here.
        # else:
        #     self.statusLabel.setText("Please mark start and end frames, and crop area.")

    def seekVideo(self):
        newPosition = int(
            self.progressSlider.value() / 1000 * self.mediaPlayer.duration()
        )
        self.mediaPlayer.setPosition(newPosition)

    def updateProgressBar(self):
        if self.mediaPlayer.duration() <= 0:
            return
        progress = self.mediaPlayer.position() / self.mediaPlayer.duration() * 1000
        self.progressSlider.setValue(int(progress))

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()

        if key == Qt.Key.Key_O and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.openVideo()
        elif key in {Qt.Key.Key_H, Qt.Key.Key_L}:
            sign = 1 if key == Qt.Key.Key_L else -1
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                delay = 100
            elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                delay = 1000
            else:
                delay = 3000
            self.seekRelative(sign * delay)
        elif key == Qt.Key.Key_Greater:
            self.changePlaybackSpeed(1)
        elif key == Qt.Key.Key_Less:
            self.changePlaybackSpeed(-1)
        elif key == Qt.Key.Key_Period:
            self.stepFrame(1)
        elif key == Qt.Key.Key_Comma:
            self.stepFrame(-1)
        elif event.text().isdigit():
            self.seekPercent(int(event.text()))
        elif key in {Qt.Key.Key_K, Qt.Key.Key_Space}:
            self.togglePlayback()
        elif key == Qt.Key.Key_Q:
            self.close()

    def togglePlayback(self):
        if self.mediaPlayer.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.mediaPlayer.pause()
        else:
            self.mediaPlayer.play()

    def seekRelative(self, milliseconds):
        newPosition = self.mediaPlayer.position() + milliseconds
        self.mediaPlayer.setPosition(
            max(0, min(newPosition, self.mediaPlayer.duration()))
        )

    def seekPercent(self, percent):
        newPosition = int(self.mediaPlayer.duration() * percent / 10)
        self.mediaPlayer.setPosition(newPosition)

    def changePlaybackSpeed(self, direction):
        self.currentSpeedIndex = max(
            0, min(self.currentSpeedIndex + direction, len(self.playbackSpeeds) - 1)
        )
        self.mediaPlayer.setPlaybackRate(self.playbackSpeeds[self.currentSpeedIndex])
        self.statusLabel.setText(
            f"Playback Speed: x{self.playbackSpeeds[self.currentSpeedIndex]}"
        )

    def stepFrame(self, direction):
        self.mediaPlayer.pause()
        currentPosition = self.mediaPlayer.position()
        frameDuration = 1000 // 30  # Assuming 30 FPS
        self.mediaPlayer.setPosition(int(currentPosition + direction * frameDuration))

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.overlay.startPos = event.pos() - self.overlay.pos()
            self.overlay.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self.overlay.geometry().contains(event.pos()):
            return

        self.overlay.endPos = event.pos() - self.overlay.pos()
        self.overlay.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.overlay.update()


if __name__ == "__main__":
    args = parseArgs()

    app = QApplication(sys.argv)
    player = VideoPlayer(args.videoPath)
    player.show()
    sys.exit(app.exec())

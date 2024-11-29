import argparse
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QBrush,
    QCloseEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPaintEvent,
)
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


def parseArgs() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("videoPath", type=str, nargs="?")
    return parser.parse_args()


class Overlay(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.startPos: Optional[QPoint] = None
        self.endPos: Optional[QPoint] = None

    def paintEvent(self, a0: Optional[QPaintEvent]):
        del a0
        if self.startPos is None or self.endPos is None:
            return

        x1 = min(self.startPos.x(), self.endPos.x()) - 10
        x2 = max(self.startPos.x(), self.endPos.x()) - 10
        y1 = min(self.startPos.y(), self.endPos.y()) - 10
        y2 = max(self.startPos.y(), self.endPos.y()) - 10
        selectionRect = QRect(QPoint(x1, y1), QPoint(x2, y2))
        painter = QPainter(self)
        painter.setPen(QPen(Qt.GlobalColor.red, 2))
        painter.setBrush(QBrush(Qt.GlobalColor.red))
        painter.drawRect(selectionRect)
        painter.end()


class VideoPlayer(QMainWindow):
    def __init__(self, videoPath) -> None:
        super().__init__()

        self.setWindowTitle("MP4 to GIF Extractor")
        self.setGeometry(100, 100, 800, 600)
        self.showMaximized()

        self.mediaPlayer = QMediaPlayer(self)
        self.videoWidget = QVideoWidget(self)
        self.mediaPlayer.setVideoOutput(self.videoWidget)

        # # Overlay for drawing
        self.overlay = Overlay()
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

    def initUi(self) -> None:
        # Main layout
        centralWidget = QWidget(self)
        layout = QVBoxLayout()
        centralWidget.setLayout(layout)
        self.setCentralWidget(centralWidget)

        # Video display
        layout.addWidget(self.videoWidget)

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

    def setOverlayPos(self) -> None:
        if hasattr(self, "overlay"):
            videoWidgetGeometry = self.videoWidget.geometry()
            globalPos = self.videoWidget.mapToGlobal(
                videoWidgetGeometry.topLeft() - QPoint(10, 10)
            )
            self.overlay.setGeometry(QRect(globalPos, videoWidgetGeometry.size()))

    def resizeEvent(self, a0) -> None:
        super().resizeEvent(a0)
        self.setOverlayPos()

    def moveEvent(self, a0) -> None:
        super().moveEvent(a0)
        self.setOverlayPos()

    def openVideo(self) -> None:
        filePath, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "", "Video Files (*.mp4 *.avi *.mkv)"
        )
        self.loadVideo(filePath)

    def loadVideo(self, filePath) -> None:
        if not filePath:
            return
        if not Path(filePath).is_file():
            print(f"No such file {filePath}")
        self.mediaPlayer.setSource(QUrl.fromLocalFile(str(filePath)))
        self.mediaPlayer.play()
        self.timer.start()

    def markStartFrame(self) -> None:
        self.startFrame = self.mediaPlayer.position()
        self.statusLabel.setText(f"Start frame marked at {self.startFrame} ms")

    def markEndFrame(self) -> None:
        self.endFrame = self.mediaPlayer.position()
        self.statusLabel.setText(f"End frame marked at {self.endFrame} ms")

    def extractGif(self) -> None:
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

    def seekVideo(self) -> None:
        newPosition = int(
            self.progressSlider.value() / 1000 * self.mediaPlayer.duration()
        )
        self.mediaPlayer.setPosition(newPosition)

    def updateProgressBar(self) -> None:
        if self.mediaPlayer.duration() <= 0:
            return
        progress = self.mediaPlayer.position() / self.mediaPlayer.duration() * 1000
        self.progressSlider.setValue(int(progress))

    def keyPressEvent(self, a0: Optional[QKeyEvent]) -> None:
        if not a0:
            return
        key = a0.key()

        if key == Qt.Key.Key_O and a0.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.openVideo()
        elif key in {Qt.Key.Key_H, Qt.Key.Key_L}:
            sign = 1 if key == Qt.Key.Key_L else -1
            if a0.modifiers() & Qt.KeyboardModifier.AltModifier:
                delay = 100
            elif a0.modifiers() & Qt.KeyboardModifier.ShiftModifier:
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
        elif a0.text().isdigit():
            self.seekPercent(int(a0.text()))
        elif key in {Qt.Key.Key_K, Qt.Key.Key_Space}:
            self.togglePlayback()
        elif key == Qt.Key.Key_Q:
            self.close()

    def togglePlayback(self) -> None:
        if self.mediaPlayer.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.mediaPlayer.pause()
        else:
            self.mediaPlayer.play()

    def seekRelative(self, milliseconds) -> None:
        newPosition = self.mediaPlayer.position() + milliseconds
        self.mediaPlayer.setPosition(
            max(0, min(newPosition, self.mediaPlayer.duration()))
        )

    def seekPercent(self, percent) -> None:
        newPosition = int(self.mediaPlayer.duration() * percent / 10)
        self.mediaPlayer.setPosition(newPosition)

    def changePlaybackSpeed(self, direction) -> None:
        self.currentSpeedIndex = max(
            0, min(self.currentSpeedIndex + direction, len(self.playbackSpeeds) - 1)
        )
        self.mediaPlayer.setPlaybackRate(self.playbackSpeeds[self.currentSpeedIndex])
        self.statusLabel.setText(
            f"Playback Speed: x{self.playbackSpeeds[self.currentSpeedIndex]}"
        )

    def stepFrame(self, direction) -> None:
        self.mediaPlayer.pause()
        currentPosition = self.mediaPlayer.position()
        frameDuration = 1000 // 30  # Assuming 30 FPS
        self.mediaPlayer.setPosition(int(currentPosition + direction * frameDuration))

    def mousePressEvent(self, a0: Optional[QMouseEvent]) -> None:
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            if not self.videoWidget.geometry().contains(a0.pos()):
                return
            self.overlay.startPos = a0.pos()
            self.overlay.endPos = None
            self.overlay.update()

    def mouseMoveEvent(self, a0: Optional[QMouseEvent]) -> None:
        if not a0 or not self.videoWidget.geometry().contains(a0.pos()):
            return
        self.overlay.endPos = a0.pos()
        self.overlay.update()

    def closeEvent(self, a0: Optional[QCloseEvent]) -> None:
        self.overlay.close()
        if a0:
            a0.accept()


if __name__ == "__main__":
    args = parseArgs()

    app = QApplication(sys.argv)
    player = VideoPlayer(args.videoPath)
    player.show()
    sys.exit(app.exec())

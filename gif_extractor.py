# TODO: add preview window
# TODO: add tick to progress bar when setting startFrame and endFrame
# TODO: keybinding to go to startFrame and endFrame
# TODO: `c` or `<C-L>` to clear selection
# TODO: window that recap all keybindings

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, cast

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QColorConstants,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QMoveEvent,
    QPainter,
    QPen,
    QPaintEvent,
    QResizeEvent,
)
from PyQt6.QtMultimedia import QMediaMetaData, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


def parseArgs() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("videoPath", type=str, nargs="?")
    return parser.parse_args()


def format_time(seconds: int) -> str:
    """Format time in seconds to MM:SS or HH:MM:SS format."""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


class SelectionWindow(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.startPos: Optional[QPoint] = None
        self.endPos: Optional[QPoint] = None

    def getRect(self) -> Optional[QRect]:
        if self.startPos is None or self.endPos is None:
            return None

        x1 = min(self.startPos.x(), self.endPos.x()) - 10
        x2 = max(self.startPos.x(), self.endPos.x()) - 10
        y1 = min(self.startPos.y(), self.endPos.y()) - 10
        y2 = max(self.startPos.y(), self.endPos.y()) - 10
        return QRect(QPoint(x1, y1), QPoint(x2, y2))

    def paintEvent(self, a0: Optional[QPaintEvent]):
        del a0
        selectionRect = self.getRect()
        if selectionRect is None:
            return

        painter = QPainter(self)
        color = cast(QColor, QColorConstants.White)
        color.setAlphaF(0.4)
        painter.setPen(QPen(color, 2))
        painter.setBrush(QBrush(color))
        painter.drawRect(selectionRect)
        painter.end()

    def isValid(self) -> bool:
        return self.startPos is not None and self.endPos is not None

    def clearSelection(self) -> None:
        self.startPos = None
        self.endPos = None
        self.update()


class FFmpegWorker(QObject):
    taskStarted = pyqtSignal()
    taskFinished = pyqtSignal(bool, str)

    def __init__(self, parent: Optional['QObject'] = None, cmd: Optional[list[str]] = None) -> None:
        super().__init__(parent)
        self.isRunning = False
        self.extractCmd = cmd

    def run(self) -> None:
        if self.extractCmd is None:
            return

        self.taskStarted.emit()
        self.isRunning = True
        try:
            self.process = subprocess.Popen(self.extractCmd, stderr=subprocess.DEVNULL)
            self.process.wait()
            self.isRunning = False
            if self.process.returncode == 0:
                self.taskFinished.emit(True, "Gif extracted!")
            else:
                self.taskFinished.emit(False, "Error in extraction process...")

        except Exception as e:
            self.isRunning = False
            self.taskFinished.emit(False, f"Exception during process: {e}")

    def stop(self) -> None:
        if self.isRunning and self.process is not None:
            self.process.terminate()
            self.isRunning = False
            self.taskFinished.emit(False, "Task was interrupted")


class VideoPlayer(QMainWindow):
    def __init__(self, videoPath: Optional[str]) -> None:
        super().__init__()

        self.setWindowTitle("MP4 to GIF Extractor")
        self.setGeometry(100, 100, 800, 600)
        self.showMaximized()

        self.isLoaded = False
        self.mediaPlayer = QMediaPlayer(self)
        self.videoWidget = QVideoWidget(self)
        self.mediaPlayer.setVideoOutput(self.videoWidget)
        self.mediaPlayer.mediaStatusChanged[QMediaPlayer.MediaStatus].connect(self.mediaLoaded)
        self.videoTrueGeometry = QRect()

        self.tmpFileName = Path("/tmp/gif_extractor_tmpfile.gif")
        self.extractThread = QThread()
        self.extractWorker: Optional[FFmpegWorker] = None

        # Overlays for selection and preview
        self.selectionWindow = SelectionWindow(self)


        self.startGifTime = None
        self.endGifTime = None
        self.playbackSpeeds = [0.25, 0.5, 1, 1.5, 2, 3, 4, 8, 16]
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
        self.videoWidget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.videoWidget)

        # Progress bar
        progress = QWidget(self)
        progressLayout = QHBoxLayout(progress)

        self.currTimeLabel = QLabel("00:00", self)
        progressLayout.addWidget(self.currTimeLabel)

        self.speedLabel = QLabel("[x1]", self)
        self.speedLabel.setFixedWidth(45)
        self.speedLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progressLayout.addWidget(self.speedLabel)

        self.progressSlider = QSlider(Qt.Orientation.Horizontal, self)
        self.progressSlider.setRange(0, 1000)
        self.progressSlider.sliderReleased.connect(self.seekVideo)
        progressLayout.addWidget(self.progressSlider)

        self.totalTimeLabel = QLabel("00:00", self)
        progressLayout.addWidget(self.totalTimeLabel)

        layout.addWidget(progress)

        # Controls
        controls = QWidget(self)
        controls.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)
        controlLayout = QHBoxLayout(controls)

        self.openButton = QPushButton(QIcon.fromTheme("document-open"), None, self)
        self.openButton.clicked.connect(self.openVideo)
        controlLayout.addWidget(self.openButton)

        self.playButton = QPushButton(QIcon.fromTheme("media-playback-start"), None, self)
        self.playButton.clicked.connect(self.togglePlayback)
        controlLayout.addWidget(self.playButton)

        self.stopButton = QPushButton(QIcon.fromTheme("media-playback-stop"), None, self)
        self.stopButton.clicked.connect(self.stopPlayback)
        controlLayout.addWidget(self.stopButton)

        self.startButton = QPushButton("Mark Start", self)
        self.startButton.clicked.connect(self.markStartFrame)
        controlLayout.addWidget(self.startButton)

        self.endButton = QPushButton("Mark End", self)
        self.endButton.clicked.connect(self.markEndFrame)
        controlLayout.addWidget(self.endButton)

        self.extractButton = QPushButton("Extract", self)
        self.extractButton.clicked.connect(self.extractGif)
        controlLayout.addWidget(self.extractButton)

        self.statusLabel = QLabel(self)
        controlLayout.addWidget(self.statusLabel)

        layout.addWidget(controls)

    def updateBlackBars(self) -> None:
        if self.widgetAspectRatio > self.videoAspectRatio:
            # Black bars on the left and right
            scaledHeight = self.widgetHeight
            scaledWidth = int(self.videoAspectRatio * scaledHeight)
            xOffset = (self.widgetWidth - scaledWidth) // 2
            yOffset = 0

        else:
            # Black bars on the top and bottom
            scaledWidth = self.widgetWidth
            scaledHeight = int(scaledWidth / self.videoAspectRatio)
            xOffset = 0
            yOffset = (self.widgetHeight - scaledHeight) // 2

        self.videoTrueGeometry = QRect(xOffset, yOffset, scaledWidth, scaledHeight)

    def setOverlaysPos(self) -> None:
        if not hasattr(self, "isLoaded") or not self.isLoaded:
            return

        self.updateBlackBars()
        globalPos = self.videoWidget.mapToGlobal(self.videoTrueGeometry.topLeft())
        self.selectionWindow.setGeometry(QRect(globalPos, self.videoTrueGeometry.size()))
        self.selectionWindow.show()

    def resizeEvent(self, a0: Optional[QResizeEvent]) -> None:
        super().resizeEvent(a0)
        if not hasattr(self, "videoWidget"):
            return

        self.widgetWidth = self.videoWidget.width()
        self.widgetHeight = self.videoWidget.height()
        self.widgetAspectRatio = self.widgetWidth / self.widgetHeight
        self.setOverlaysPos()

    def moveEvent(self, a0: Optional[QMoveEvent]) -> None:
        super().moveEvent(a0)
        self.setOverlaysPos()

    def openVideo(self) -> None:
        filePath, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "", "Video Files (*.mp4 *.avi *.mkv)"
        )
        self.loadVideo(filePath)

    def loadVideo(self, filePath: Optional[str]) -> None:
        self.isLoaded = False
        self.stopPlayback()
        if filePath is None:
            return

        if not Path(filePath).is_file():
            print(f"No such file {filePath}")
        self.mediaPlayer.setSource(QUrl.fromLocalFile(str(filePath)))
        self.statusLabel.setText("Loading media...")

    def mediaLoaded(self, status: QMediaPlayer.MediaStatus) -> None:
        if self.isLoaded or status != QMediaPlayer.MediaStatus.LoadedMedia:
            return

        self.statusLabel.setText("Media loaded!")
        self.isLoaded = True
        self.togglePlayback()
        self.totalTimeLabel.setText(format_time(self.mediaPlayer.duration() // 1000))
        self.timer.start()
        self.videoWidth = self.mediaPlayer.metaData().value(QMediaMetaData.Key.Resolution).width()
        self.videoHeight = self.mediaPlayer.metaData().value(QMediaMetaData.Key.Resolution).height()
        self.videoAspectRatio = self.videoWidth / self.videoHeight
        self.setOverlaysPos()

    def markStartFrame(self) -> None:
        if self.isLoaded and self.mediaPlayer.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.statusLabel.setText("Mark start frame")
            self.startGifTime = self.mediaPlayer.position()

    def markEndFrame(self) -> None:
        if self.isLoaded and self.mediaPlayer.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.statusLabel.setText("Mark end frame")
            self.endGifTime = self.mediaPlayer.position()
            self.extractGif()

    def setPreviewWindow(self) -> None:
        print("SETTING PREVIEW")

    def onExtractStarted(self) -> None:
        self.statusLabel.setText("Extraction started!")

    def onExtractFinished(self, status: bool, msg: str) -> None:
        self.statusLabel.setText(msg)

        self.extractThread.started.disconnect()
        if self.extractWorker is not None:
            self.extractWorker.taskFinished.disconnect()
            self.extractWorker = None

        if status:
            self.setPreviewWindow()

    def getExtractCmd(self) -> Optional[list[str]]:
        sel = self.selectionWindow.getRect()
        if self.startGifTime is None or self.endGifTime is None or sel is None:
            return None

        widthRatio = self.videoWidth / self.videoTrueGeometry.width()
        heightRatio = self.videoHeight / self.videoTrueGeometry.height()
        x = int(sel.x() * widthRatio)
        y = int(sel.y() * heightRatio)
        w = int(sel.width() * widthRatio)
        h = int(sel.height() * heightRatio)

        filePath = self.mediaPlayer.source().path()
        cropStr = f"{w}:{h}:{x}:{y}"
        startTimeStr = f"{format_time(self.startGifTime // 1000)}.{self.startGifTime % 1000}"
        clipLength = self.endGifTime - self.startGifTime
        endTimeStr = f"{format_time(clipLength // 1000)}.{clipLength % 1000}"

        cmd = ["ffmpeg", "-y", "-an", "-i", filePath, "-vf", f"crop={cropStr}",
                "-ss", startTimeStr, "-t", endTimeStr, str(self.tmpFileName)]
        return cmd

    def extractGif(self) -> None:
        cmd = self.getExtractCmd()
        if cmd is None:
            return

        if self.extractWorker is not None:
            self.extractWorker.stop()
            self.extractThread.quit()
            self.extractThread.wait()

        self.extractWorker = FFmpegWorker(cmd=cmd)
        self.extractWorker.moveToThread(self.extractThread)

        self.extractThread.started.connect(self.extractWorker.run)
        self.extractWorker.taskStarted.connect(self.onExtractStarted)
        self.extractWorker.taskFinished.connect(self.onExtractFinished)
        self.extractWorker.taskFinished.connect(self.extractThread.quit)

        if not self.extractThread.isRunning():
            self.extractThread.start()

    def saveGif(self) -> None:
        filePath, _ = QFileDialog.getSaveFileName(self, "Save File", "", "Gif Files (*.gif)")
        if not filePath:
            return

        if not filePath.endswith(".gif"):
            filePath += ".gif"
        if self.tmpFileName.exists():
            self.tmpFileName.rename(filePath)
            self.statusLabel.setText("Gif saved!")
        else:
            self.statusLabel.setText("No clip selected")

    def seekVideo(self) -> None:
        newPosition = self.progressSlider.value() * self.mediaPlayer.duration() // 1000
        self.mediaPlayer.setPosition(newPosition)

    def updateProgressBar(self) -> None:
        if self.mediaPlayer.duration() <= 0:
            return
        progress = self.mediaPlayer.position() / self.mediaPlayer.duration() * 1000
        self.progressSlider.setValue(int(progress))
        self.currTimeLabel.setText(format_time(self.mediaPlayer.position() // 1000))

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
        elif key == Qt.Key.Key_Escape:
            self.stopPlayback()
        elif key == Qt.Key.Key_S:
            self.markStartFrame()
        elif key == Qt.Key.Key_E:
            self.markEndFrame()
        elif key == Qt.Key.Key_X:
            self.extractGif()
        elif key == Qt.Key.Key_G:
            self.saveGif()
        elif key == Qt.Key.Key_Q:
            self.close()

    def togglePlayback(self) -> None:
        if self.mediaPlayer.mediaStatus() == QMediaPlayer.MediaStatus.NoMedia:
            return

        if self.mediaPlayer.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.mediaPlayer.pause()
            self.playButton.setIcon(QIcon.fromTheme("media-playback-start"))
        else:
            self.mediaPlayer.play()
            self.playButton.setIcon(QIcon.fromTheme("media-playback-pause"))

    def stopPlayback(self) -> None:
        self.mediaPlayer.stop()
        self.playButton.setIcon(QIcon.fromTheme("media-playback-start"))
        self.selectionWindow.hide()
        self.selectionWindow.clearSelection()
        self.startGifTime = None
        self.endGifTime = None
        self.statusLabel.setText("")

    def seekRelative(self, milliseconds: int) -> None:
        newPosition = self.mediaPlayer.position() + milliseconds
        self.mediaPlayer.setPosition(
            max(0, min(newPosition, self.mediaPlayer.duration()))
        )

    def seekPercent(self, percent: int) -> None:
        newPosition = int(self.mediaPlayer.duration() * percent / 10)
        self.mediaPlayer.setPosition(newPosition)

    def changePlaybackSpeed(self, direction: int) -> None:
        if not (0 <= self.currentSpeedIndex + direction < len(self.playbackSpeeds)):
            return

        self.currentSpeedIndex += direction
        self.mediaPlayer.setPlaybackRate(self.playbackSpeeds[self.currentSpeedIndex])
        self.speedLabel.setText(f"[x{self.playbackSpeeds[self.currentSpeedIndex]}]")

    def stepFrame(self, direction: int) -> None:
        self.mediaPlayer.pause()
        currentPosition = self.mediaPlayer.position()
        frameDuration = 1000 // 30  # Assuming 30 FPS
        self.mediaPlayer.setPosition(int(currentPosition + direction * frameDuration))

    def mousePressEvent(self, a0: Optional[QMouseEvent]) -> None:
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            if not self.videoTrueGeometry.contains(a0.pos()):
                return

            clickPos = a0.pos() - self.videoTrueGeometry.topLeft()
            self.selectionWindow.startPos = clickPos
            self.selectionWindow.endPos = None
            self.selectionWindow.update()

    def mouseMoveEvent(self, a0: Optional[QMouseEvent]) -> None:
        if not a0 or not self.videoTrueGeometry.contains(a0.pos()):
            return

        clickPos = a0.pos() - self.videoTrueGeometry.topLeft()
        self.selectionWindow.endPos = clickPos
        self.selectionWindow.update()

    def mouseReleaseEvent(self, a0: Optional[QMouseEvent]) -> None:
        del a0
        self.selectionWindow.update()
        self.extractGif()

    def closeEvent(self, a0: Optional[QCloseEvent]) -> None:
        self.tmpFileName.unlink(missing_ok=True)
        self.selectionWindow.close()
        if self.extractWorker is not None:
            self.extractWorker.stop()

        self.extractThread.quit()
        self.extractThread.wait()
        self.extractThread.deleteLater()

        if a0:
            a0.accept()


if __name__ == "__main__":
    args = parseArgs()

    app = QApplication(sys.argv)
    player = VideoPlayer(args.videoPath)
    player.show()
    sys.exit(app.exec())

# TODO: don't reset selection rect and preview on resize but compute their new positions
# TODO: write README

"""
GIF Extractor - Extract GIFs from MP4 Videos

This script provides a GUI application for extracting GIFs from MP4 videos. Users can select a crop region, mark start and end frames, and export the selected clip as a GIF using FFmpeg.

Key features:
- Video playback with support for seeking and playback speed adjustments.
- Selection overlay for defining the cropped region.
- GIF preview functionality.
- Keyboard shortcuts for various operations.
- Built with PyQt6 for the GUI and FFmpeg for video processing.

Usage:
    python gif_extractor.py [videoPath]

Args:
    videoPath (optional): Path to the MP4 video to open initially.
"""

import argparse
import enum
import shutil
import sys
from pathlib import Path
from subprocess import DEVNULL, PIPE, Popen
from typing import Callable, Optional, cast

from PyQt6.QtCore import (
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QColorConstants,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QMoveEvent,
    QMovie,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PyQt6.QtMultimedia import QMediaMetaData, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStyle,
    QStyleOptionSlider,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)

TMP_MP4_TRIM_FILE = Path("/tmp/gif_extractor_trimmed.mp4")
TMP_PREVIEW_FILE = Path("/tmp/gif_extractor_preview.gif")
TMP_OUTPUT_FILE = Path("/tmp/gif_extractor_output.gif")


def parseArgs() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract GIFs from MP4 videos.")
    parser.add_argument("videoPath", type=str, nargs="?", help="Path to the video file to open.")
    return parser.parse_args()


def format_time(seconds: int) -> str:
    """Format time in seconds to MM:SS or HH:MM:SS format."""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


class TickSlider(QSlider):
    """
    Custom QSlider class with tick marks and that responds to mouse clicks for navigation.
    The code is loosely based on these two threads:
    https://stackoverflow.com/questions/68179408/i-need-to-put-several-marks-on-a-qslider
    https://stackoverflow.com/questions/52689047/moving-qslider-to-mouse-click-position
    """

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: Optional[QWidget],
        clickCb: Callable[[], None],
        moveCb: Callable[[], None],
        releaseCb: Callable[[], None],
    ) -> None:
        super().__init__(orientation, parent)
        self.startTick: Optional[int] = None
        self.endTick: Optional[int] = None

        self.hasClickedSlider = False
        self.clickCb = clickCb
        self.moveCb = moveCb
        self.releaseCb = releaseCb

    def setStartTick(self) -> None:
        self.startTick = self.value()

    def setEndTick(self) -> None:
        self.endTick = self.value()

    def clearTicks(self) -> None:
        self.startTick = None
        self.endTick = None

    def mousePressEvent(self, ev: Optional[QMouseEvent]) -> None:
        if ev is None or ev.button() != Qt.MouseButton.LeftButton:
            return

        super().mousePressEvent(ev)
        self.hasClickedSlider = True
        val = self.pixelPosToRangeValue(ev.pos())
        if val is not None:
            self.setValue(val)
            self.clickCb()
            self.moveCb()

    def mouseMoveEvent(self, ev: Optional[QMouseEvent]) -> None:
        if ev is None or not self.hasClickedSlider:
            return

        super().mousePressEvent(ev)
        val = self.pixelPosToRangeValue(ev.pos())
        if val is not None:
            self.setValue(val)
            self.moveCb()

    def mouseReleaseEvent(self, ev: Optional[QMouseEvent]) -> None:
        if ev is None or not self.hasClickedSlider:
            return
        super().mouseReleaseEvent(ev)

        self.hasClickedSlider = False
        self.releaseCb()

    def pixelPosToRangeValue(self, pos: QPoint) -> Optional[int]:
        opt = QStyleOptionSlider()
        style = self.style()
        if style is None:
            return None
        self.initStyleOption(opt)

        gr = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
        sr = style.subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)

        if self.orientation() == Qt.Orientation.Horizontal:
            sliderLength = sr.width()
            sliderMin = gr.x()
            sliderMax = gr.right() - sliderLength + 1
        else:
            sliderLength = sr.height()
            sliderMin = gr.y()
            sliderMax = gr.bottom() - sliderLength + 1
        pr = pos - sr.center() + sr.topLeft()
        p = pr.x() if self.orientation() == Qt.Orientation.Horizontal else pr.y()
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), p - sliderMin, sliderMax - sliderMin, opt.upsideDown,
        )

    def paintEvent(self, ev: Optional[QPaintEvent]) -> None:
        """Override painting to add ticks on startTick and endTick positions"""
        if self.startTick is None and self.endTick is None:
            super().paintEvent(ev)
            return

        qp = QStylePainter(self)
        opt = QStyleOptionSlider()
        style = self.style()
        if style is None:
            return
        self.initStyleOption(opt)

        # Draw slider groove
        opt.subControls = QStyle.SubControl.SC_SliderGroove
        qp.drawComplexControl(QStyle.ComplexControl.CC_Slider, opt)

        sliderMin = self.minimum()
        sliderMax = self.maximum()
        sliderLength = style.pixelMetric(QStyle.PixelMetric.PM_SliderLength, opt, self)
        span = style.pixelMetric(QStyle.PixelMetric.PM_SliderSpaceAvailable, opt, self)

        qp.save()
        qp.translate(opt.rect.x() + sliderLength / 2, 0)
        grooveRect = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove,
        )
        grooveTop = grooveRect.top()
        grooveBottom = grooveRect.bottom()
        bottom = self.height()

        # Draw start tick
        if self.startTick is not None:
            qp.setPen(QPen(QColorConstants.Green, 2))
            x = style.sliderPositionFromValue(sliderMin, sliderMax, self.startTick, span)
            qp.drawLine(x, 0, x, grooveTop)
            qp.drawLine(x, grooveBottom, x, bottom)

        # Draw end tick
        if self.endTick is not None:
            qp.setPen(QPen(QColorConstants.Red, 2))
            x = style.sliderPositionFromValue(sliderMin, sliderMax, self.endTick, span)
            qp.drawLine(x, 0, x, grooveTop)
            qp.drawLine(x, grooveBottom, x, bottom)

        qp.restore()

        # Draw slider handle
        opt.subControls = QStyle.SubControl.SC_SliderHandle
        opt.activeSubControls = QStyle.SubControl.SC_SliderHandle
        if self.isSliderDown():
            opt.state |= QStyle.StateFlag.State_Sunken
        qp.drawComplexControl(QStyle.ComplexControl.CC_Slider, opt)


class SelectionWindow(QWidget):
    """
    Overlay widget to allow users to select a rectangular region for cropping.
    This widget draws a translucent rectangle to show the selected crop area.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.startPos: Optional[QPoint] = None
        self.endPos: Optional[QPoint] = None
        self.validatedSel: Optional[QRect] = None

    def getRect(self) -> Optional[QRect]:
        """Returns the selected crop area as a QRect, or None if not selected."""
        if self.startPos is None or self.endPos is None:
            return None

        x1 = min(self.startPos.x(), self.endPos.x()) - 10
        x2 = max(self.startPos.x(), self.endPos.x()) - 10
        y1 = min(self.startPos.y(), self.endPos.y()) - 10
        y2 = max(self.startPos.y(), self.endPos.y()) - 10
        return QRect(QPoint(x1, y1), QPoint(x2, y2))

    def validate(self) -> None:
        self.validatedSel = self.getRect()

    def paintEvent(self, a0: Optional[QPaintEvent]) -> None:
        """Draws a translucent rectangle to show the selected crop area."""
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

        # Draw translucent green rectangle for validated selection
        if self.validatedSel is not None:
            color = cast(QColor, QColorConstants.Green)
            color.setAlphaF(0.2)
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(color))
            painter.drawRect(self.validatedSel)

        painter.end()

    def isValid(self) -> bool:
        return self.startPos is not None and self.endPos is not None

    def clearSelection(self) -> None:
        self.startPos = None
        self.endPos = None
        self.validatedSel = None
        self.update()


class PreviewWindow(QWidget):
    """
    Overlay widget to show a preview of the selected crop area.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.resize(self.size())
        self.label.setScaledContents(True)
        self.movie: Optional[QMovie] = None

    def resizeEvent(self, a0: Optional[QResizeEvent]) -> None:
        self.label.resize(self.size())
        if a0:
            a0.accept()

    def hasMedia(self) -> bool:
        return self.movie is not None

    def loadGif(self, path: str) -> None:
        self.stop()
        self.movie = QMovie(path)
        self.label.setMovie(self.movie)
        self.movie.start()

    def getSize(self) -> tuple[int, int]:
        if self.movie is None:
            return (-1, -1)
        frame = self.movie.currentPixmap()
        return frame.width(), frame.height()

    def toggle(self) -> None:
        if self.movie is None:
            return

        if self.isVisible():
            self.movie.stop()
            self.hide()
        else:
            self.movie.start()
            self.show()

    def stop(self) -> None:
        if self.movie is not None:
            self.movie.stop()
            self.movie = None


class WorkerStatus(enum.Enum):
    SUCCESS = enum.auto()
    FAILURE = enum.auto()
    ERROR = enum.auto()


class Worker(QObject):
    taskProgress = pyqtSignal(int, float)
    taskFinished = pyqtSignal(WorkerStatus, str)

    def __init__(self, cmd: list[str]) -> None:
        super().__init__()
        self.process: Optional[Popen] = None
        self.cmd = cmd
        self.interrupt = False

    def run(self) -> None:
        try:
            if "-progress" in self.cmd:
                self.process = Popen(self.cmd, stdout=PIPE, stderr=DEVNULL)
                if self.process.stdout is not None:
                    savedFrame = 0
                    for data in iter(self.process.stdout.readline, b""):
                        if data.startswith(b"frame="):
                            savedFrame = int(data[6:])
                        elif data.startswith(b"fps="):
                            self.taskProgress.emit(savedFrame, float(data[4:]))
                self.process.wait()
            else:
                self.process = Popen(self.cmd, stdout=DEVNULL, stderr=DEVNULL)
                self.process.wait()

            if self.interrupt:
                return

            if self.process.returncode == 0:
                self.taskFinished.emit(WorkerStatus.SUCCESS, "")
            else:
                self.taskFinished.emit(WorkerStatus.FAILURE, "")

        except Exception as e:
            self.taskFinished.emit(WorkerStatus.ERROR, f"Exception during process: {e}")

        finally:
            self.process = None

    def stop(self) -> None:
        if self.process is not None:
            self.interrupt = True
            self.process.terminate()


class WorkerRunner:
    def __init__(
        self,
        callback: Callable[[WorkerStatus, str], None],
        progressCallback: Optional[Callable[[int, float], None]] = None,
    ) -> None:
        self.thread = QThread()
        self.worker: Optional[Worker] = None
        self.callback = callback
        self.progressCallback = progressCallback

    def interrupt(self) -> None:
        if self.worker is not None:
            self.thread.started.disconnect()
            self.worker.stop()
            self.worker = None

        self.thread.quit()
        self.thread.wait()

    def run(self, cmd: list[str]) -> None:
        self.interrupt()

        self.worker = Worker(cmd)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.taskFinished.connect(self.callback)
        self.worker.taskFinished.connect(self.interrupt)
        if self.progressCallback is not None:
            self.worker.taskProgress.connect(self.progressCallback)

        if not self.thread.isRunning():
            self.thread.start()

    def close(self) -> None:
        self.interrupt()
        self.thread.deleteLater()


class HelpBox(QMessageBox):
    def keyPressEvent(self, a0: Optional[QKeyEvent]) -> None:
        if a0 is not None and a0.key() == Qt.Key.Key_Question:
            self.close()
        else:
            super().keyPressEvent(a0)


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

        self.extractionRunning = False
        self.trimWorker = WorkerRunner(self.onTrimFinished)
        self.previewWorker = WorkerRunner(self.onPreviewFinished)
        self.conversionWorker = WorkerRunner(self.onConversionFinished, self.onConversionProgress)
        self.optimizationWorker = WorkerRunner(self.onOptimizationFinished)

        # Overlays for selection and preview
        self.previewEnabled = True
        self.selectionWindow = SelectionWindow(self)
        self.previewWindow = PreviewWindow(self)
        self.previewAnchor: Optional[QPoint] = None
        self.clickPreviewVec: Optional[QPoint] = None

        self.hasClickedVideo = False
        self.startGifTime: Optional[int] = None
        self.endGifTime: Optional[int] = None
        self.playbackSpeeds = [0.25, 0.5, 1, 1.5, 2, 3, 4, 8, 16]
        self.currentSpeedIndex = self.playbackSpeeds.index(1)

        # Update progress bar every 15ms
        self.progressBarTimer = QTimer(self)
        self.progressBarTimer.setInterval(15)
        self.progressBarTimer.timeout.connect(self.updateProgressBar)

        self.initUi()
        self.loadVideo(videoPath)

    def initUi(self) -> None:
        # Main layout
        centralWidget = QWidget(self)
        layout = QVBoxLayout()
        centralWidget.setLayout(layout)
        self.setCentralWidget(centralWidget)

        # Video display
        self.videoWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.videoWidget.setMinimumHeight(100)
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

        self.progressSlider = TickSlider(
            Qt.Orientation.Horizontal,
            self,
            self.sliderPressed,
            self.sliderMoved,
            self.sliderReleased,
        )
        self.progressSlider.setRange(0, 1000)
        self.sliderSavedStateIsPlaying: Optional[bool] = None
        self.progressSlider.sliderPressed.connect(self.sliderPressed)
        self.progressSlider.sliderMoved.connect(self.sliderMoved)
        self.progressSlider.sliderReleased.connect(self.sliderReleased)
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

        self.saveButton = QPushButton("Save GIF", self)
        self.saveButton.clicked.connect(self.saveGif)
        controlLayout.addWidget(self.saveButton)

        self.optimizationBox = QCheckBox("&Optimize", self)
        self.optimizationBox.setChecked(True)
        self.optimizationBox.checkStateChanged.connect(self.toggleOptimizationField)
        controlLayout.addWidget(self.optimizationBox)

        self.optimizationLabel = QLabel("Level", self)
        controlLayout.addWidget(self.optimizationLabel)

        self.optimizationField = QSpinBox(self)
        self.optimizationField.setRange(5, 200)
        self.optimizationField.setValue(80)
        controlLayout.addWidget(self.optimizationField)

        self.statusLabel = QLabel(self)
        controlLayout.addWidget(self.statusLabel)

        layout.addWidget(controls)

    def updateBlackBars(self) -> None:
        """Compute the geometry of the video without the black bars"""
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

    def setSelectOverlayPos(self) -> None:
        """Set the position of the selection overlay to the video geometry"""
        if not hasattr(self, "isLoaded") or not self.isLoaded:
            return

        self.updateBlackBars()
        globalPos = self.videoWidget.mapToGlobal(self.videoTrueGeometry.topLeft())
        self.selectionWindow.setGeometry(QRect(globalPos, self.videoTrueGeometry.size()))
        self.selectionWindow.show()

    def setPreviewPos(self) -> None:
        """Set the position of the preview window to the video geometry"""
        if not hasattr(self, "previewWindow") or not self.previewWindow.hasMedia():
            return

        gifWidth, gifHeight = self.previewWindow.getSize()
        maxWidth, maxHeight = self.widgetWidth // 3, self.widgetHeight // 3
        if gifWidth / gifHeight > maxWidth / maxHeight:
            previewWidth = min(gifWidth, maxWidth)
            previewHeight = previewWidth * gifHeight // gifWidth
        else:
            previewHeight = min(gifHeight, maxHeight)
            previewWidth = previewHeight * gifWidth // gifHeight

        # Preview has been moved via a click and drag
        if self.previewAnchor is not None:
            topLeftPos = self.previewAnchor
        else:
            topLeftPos = QPoint(
                self.videoTrueGeometry.right() - previewWidth,
                self.videoTrueGeometry.top(),
            )

        self.previewRelGeometry = QRect(topLeftPos, QSize(previewWidth, previewHeight))
        globalPos = self.videoWidget.mapToGlobal(topLeftPos)
        self.previewWindow.setGeometry(QRect(globalPos, QSize(previewWidth, previewHeight)))
        if self.previewEnabled:
            self.previewWindow.show()

    def resizeEvent(self, a0: Optional[QResizeEvent]) -> None:
        super().resizeEvent(a0)
        if not hasattr(self, "videoWidget"):
            return

        self.previewAnchor = None
        self.selectionWindow.clearSelection()
        self.widgetWidth = self.videoWidget.width()
        self.widgetHeight = self.videoWidget.height()
        self.widgetAspectRatio = self.widgetWidth / self.widgetHeight
        self.setSelectOverlayPos()
        self.setPreviewPos()

    def moveEvent(self, a0: Optional[QMoveEvent]) -> None:
        super().moveEvent(a0)
        self.setSelectOverlayPos()
        self.setPreviewPos()

    def openVideo(self) -> None:
        filePath, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "", "Video Files (*.mp4 *.avi *.mkv)",
        )
        self.loadVideo(filePath)

    def loadVideo(self, filePath: Optional[str]) -> None:
        self.isLoaded = False
        self.stopPlayback()
        if filePath is None:
            return

        if not Path(filePath).is_file():
            self.statusLabel.setText(f"No such file {filePath}")
            return

        self.mediaPlayer.setSource(QUrl.fromLocalFile(str(filePath)))
        self.statusLabel.setText("Loading media...")

    def mediaLoaded(self, status: QMediaPlayer.MediaStatus) -> None:
        if self.isLoaded or status != QMediaPlayer.MediaStatus.LoadedMedia:
            return

        self.statusLabel.setText("Media loaded!")
        self.isLoaded = True
        self.togglePlayback()
        self.totalTimeLabel.setText(format_time(self.mediaPlayer.duration() // 1000))
        self.progressBarTimer.start()
        self.videoWidth = self.mediaPlayer.metaData().value(QMediaMetaData.Key.Resolution).width()
        self.videoHeight = self.mediaPlayer.metaData().value(QMediaMetaData.Key.Resolution).height()
        self.videoAspectRatio = self.videoWidth / self.videoHeight
        self.setSelectOverlayPos()

    def sliderPressed(self) -> None:
        if not self.isLoaded:
            return

        self.sliderSavedStateIsPlaying = (
            self.mediaPlayer.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        self.mediaPlayer.pause()

    def sliderMoved(self) -> None:
        if not self.isLoaded:
            return

        newPosition = self.progressSlider.value() * self.mediaPlayer.duration() // 1000
        self.mediaPlayer.setPosition(newPosition)

    def sliderReleased(self) -> None:
        if not self.isLoaded:
            return

        if self.sliderSavedStateIsPlaying:
            self.mediaPlayer.play()
        self.sliderSavedStateIsPlaying = None

    def toggleOptimizationField(self) -> None:
        status = not self.optimizationField.isEnabled()
        self.optimizationField.setEnabled(status)
        self.optimizationLabel.setEnabled(status)

    def updateProgressBar(self) -> None:
        if self.sliderSavedStateIsPlaying is not None or self.mediaPlayer.duration() <= 0:
            return
        progress = self.mediaPlayer.position() / self.mediaPlayer.duration() * 1000
        self.progressSlider.setValue(int(progress))
        self.currTimeLabel.setText(format_time(self.mediaPlayer.position() // 1000))

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
        self.previewWindow.stop()
        self.previewWindow.hide()
        self.startGifTime = None
        self.endGifTime = None
        self.statusLabel.setText("")

    def seekRelative(self, milliseconds: int) -> None:
        newPosition = self.mediaPlayer.position() + milliseconds
        newPosition = max(0, min(newPosition, self.mediaPlayer.duration()))
        self.mediaPlayer.setPosition(newPosition)

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

    def markStartFrame(self) -> None:
        if self.isLoaded and self.mediaPlayer.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.statusLabel.setText("Mark start frame")
            self.startGifTime = self.mediaPlayer.position()
            if self.endGifTime is not None and self.startGifTime >= self.endGifTime:
                self.endGifTime = None
                self.progressSlider.clearTicks()
            self.progressSlider.setStartTick()
            self.progressSlider.update()

            if self.endGifTime is not None:
                self.gifTrim()

    def markEndFrame(self) -> None:
        if self.isLoaded and self.mediaPlayer.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.statusLabel.setText("Mark end frame")
            self.endGifTime = self.mediaPlayer.position()
            if self.startGifTime is not None and self.endGifTime <= self.startGifTime:
                self.startGifTime = None
                self.progressSlider.clearTicks()
            self.progressSlider.setEndTick()
            self.progressSlider.update()

            if self.startGifTime is not None:
                self.gifTrim()

    def gotoStartFrame(self) -> None:
        if self.startGifTime is not None:
            self.mediaPlayer.setPosition(self.startGifTime)

    def gotoEndFrame(self) -> None:
        if self.endGifTime is not None:
            self.mediaPlayer.setPosition(self.endGifTime)

    def getCropCoords(self) -> str:
        sel = cast(QRect, self.selectionWindow.getRect())

        widthRatio = self.videoWidth / self.videoTrueGeometry.width()
        heightRatio = self.videoHeight / self.videoTrueGeometry.height()
        x = int(sel.x() * widthRatio)
        y = int(sel.y() * heightRatio)
        w = int(sel.width() * widthRatio)
        h = int(sel.height() * heightRatio)
        return f"{w}:{h}:{x}:{y}"

    def gifTrim(self) -> None:
        if self.startGifTime is None or self.endGifTime is None:
            return
        self.statusLabel.setText("Trimming video...")

        # Stop preview generation when user has selected another clip
        self.previewWorker.interrupt()

        filePath = self.mediaPlayer.source().path()
        startTimeStr = f"{format_time(self.startGifTime // 1000)}.{self.startGifTime % 1000}"
        clipLength = self.endGifTime - self.startGifTime
        lengthStr = f"{format_time(clipLength // 1000)}.{clipLength % 1000}"

        # Nb frames = 30fps * clipLength (in s)
        self.clipNbFrames = 30 * clipLength // 1000

        trimCmd = ["ffmpeg", "-y", "-an", "-ss", startTimeStr, "-t", lengthStr,
                   "-i", filePath, "-c", "copy", str(TMP_MP4_TRIM_FILE)]
        self.trimWorker.run(trimCmd)

    def gifPreview(self) -> None:
        if not TMP_MP4_TRIM_FILE.exists() or not self.selectionWindow.isValid():
            return

        cropCoords = self.getCropCoords()
        self.selectionWindow.validate()
        self.selectionWindow.update()

        previewCmd = ["ffmpeg", "-y", "-i", str(TMP_MP4_TRIM_FILE),
                      "-vf", f"crop={cropCoords}", str(TMP_PREVIEW_FILE)]
        self.previewWorker.run(previewCmd)

    def gifConversion(self) -> None:
        if not TMP_MP4_TRIM_FILE.exists() or not self.selectionWindow.isValid():
            return

        self.statusLabel.setText("Converting video...")

        # Stop optimization when another clip is being converted
        self.optimizationWorker.interrupt()
        TMP_OUTPUT_FILE.unlink(missing_ok=True)

        cropCoords = self.getCropCoords()
        filterStr = (
            f"crop={cropCoords}, split [s0][s1];"
            " [s0] palettegen=max_colors=64:stats_mode=diff [pal];"
            " [s1] fifo [s1] ; [s1] [pal] paletteuse=dither=bayer"
        )

        conversionCmd = ["ffmpeg", "-y", "-v", "quiet", "-progress", "pipe:1",
                         "-i", str(TMP_MP4_TRIM_FILE), "-vf", filterStr, str(TMP_OUTPUT_FILE)]
        self.extractionRunning = True
        self.conversionWorker.run(conversionCmd)

    def gifOptimization(self) -> None:
        if not TMP_OUTPUT_FILE.exists():
            return

        if shutil.which("gifsicle") is None:
            self.statusLabel.setText("Executable `gifsicle` not found!")
            return

        self.statusLabel.setText("Optimizing GIF, this can take a while...")
        optimizationCmd = ["gifsicle", "-O3", f"--lossy={self.optimizationField.value()}",
                           "-o", str(TMP_OUTPUT_FILE), str(TMP_OUTPUT_FILE)]
        self.optimizationWorker.run(optimizationCmd)

    def onTrimFinished(self, status: WorkerStatus, msg: str) -> None:
        if status == WorkerStatus.SUCCESS:
            self.statusLabel.setText("Video trimmed!")
            self.gifPreview()
            self.gifConversion()

        elif status == WorkerStatus.FAILURE:
            self.extractionRunning = False
            self.statusLabel.setText("Something went wrong when trimming file")

        elif status == WorkerStatus.ERROR:
            self.extractionRunning = False
            self.statusLabel.setText(f"Error occured in worker task: {msg}")

    def onPreviewFinished(self, status: WorkerStatus, _: str) -> None:
        if status == WorkerStatus.SUCCESS:
            self.previewWindow.loadGif(str(TMP_PREVIEW_FILE))
            self.setPreviewPos()

    def onConversionProgress(self, frame: int, fps: float) -> None:
        try:
            progressPercent = min(100, 100 * frame // self.clipNbFrames)
            progressETA = int((self.clipNbFrames - frame) / fps)
        except ZeroDivisionError:
            progressPercent = "-"
            progressETA = 0
        progressMsg = f"Conversion: {progressPercent}%, ETA: {format_time(progressETA)}"
        self.statusLabel.setText(progressMsg)

    def onConversionFinished(self, status: WorkerStatus, msg: str) -> None:
        if status == WorkerStatus.SUCCESS:
            if self.optimizationBox.isChecked():
                self.gifOptimization()
            else:
                self.extractionRunning = False
                self.statusLabel.setText("Gif extracted successfully!")

        elif status == WorkerStatus.FAILURE:
            self.statusLabel.setText("Something went wrong when converting file")

        elif status == WorkerStatus.ERROR:
            self.statusLabel.setText(f"Error occured in worker task: {msg}")

    def onOptimizationFinished(self, status: WorkerStatus, msg: str) -> None:
        self.extractionRunning = False
        if status == WorkerStatus.SUCCESS:
            self.statusLabel.setText("Gif extracted successfully!")

        elif status == WorkerStatus.FAILURE:
            self.statusLabel.setText("Something went wrong when converting file")

        elif status == WorkerStatus.ERROR:
            self.statusLabel.setText(f"Error occured in worker task: {msg}")

    def saveGif(self) -> None:
        if self.conversionWorker.worker is not None:
            self.statusLabel.setText("GIF is converting!")
            return

        if self.optimizationWorker.worker is not None:
            self.statusLabel.setText("Clip is being optimized, this can take a while...")
            return

        if not TMP_OUTPUT_FILE.exists():
            self.statusLabel.setText("No clip selected!")
            return

        filePath, _ = QFileDialog.getSaveFileName(self, "Save File", "", "Gif Files (*.gif)")
        if not filePath:
            return

        if not filePath.endswith(".gif"):
            filePath += ".gif"

        TMP_OUTPUT_FILE.rename(filePath)
        self.statusLabel.setText("Gif saved!")

    def keyPressEvent(self, a0: Optional[QKeyEvent]) -> None:
        if not a0:
            return
        key = a0.key()

        if key == Qt.Key.Key_O and a0.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.openVideo()

        elif (
            key == Qt.Key.Key_S and a0.modifiers() & Qt.KeyboardModifier.ControlModifier
            or key == Qt.Key.Key_X
        ):
            self.saveGif()

        elif key == Qt.Key.Key_L and a0.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.selectionWindow.clearSelection()
            self.startGifTime = None
            self.endGifTime = None
            self.previewAnchor = None
            self.setPreviewPos()
            self.previewWindow.hide()

        elif key in [Qt.Key.Key_J, Qt.Key.Key_L]:
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

        elif key == Qt.Key.Key_A:
            self.gotoStartFrame()

        elif key == Qt.Key.Key_D:
            self.gotoEndFrame()

        elif key == Qt.Key.Key_P:
            self.previewEnabled = not self.previewEnabled
            self.previewWindow.toggle()

        elif key == Qt.Key.Key_C:
            self.selectionWindow.clearSelection()

        elif key == Qt.Key.Key_R:
            self.previewAnchor = None
            self.setPreviewPos()

        elif key == Qt.Key.Key_Q:
            self.closeWithConfirm()

        elif key == Qt.Key.Key_Question:
            self.showHelp()

    def cropAnchor(self, anchor: QPoint) -> QPoint:
        vx = self.videoWidget.geometry().width()
        dx = self.previewRelGeometry.width()
        x = max(0, min(anchor.x(), vx - dx))

        vy = self.videoWidget.geometry().height()
        dy = self.previewRelGeometry.height()
        y = max(0, min(anchor.y(), vy - dy))

        return QPoint(x, y)

    def mousePressEvent(self, a0: Optional[QMouseEvent]) -> None:
        super().mousePressEvent(a0)
        if a0 is None:
            return

        self.optimizationField.clearFocus()

        if a0.button() == Qt.MouseButton.MiddleButton:
            self.selectionWindow.clearSelection()
            return

        if a0.button() != Qt.MouseButton.LeftButton:
            return

        # Click on preview window
        if self.previewWindow.isVisible() and self.previewRelGeometry.contains(a0.pos()):
            self.clickPreviewVec = self.previewRelGeometry.topLeft() - a0.pos()
            return

        # Click outside of video widget
        if not self.videoTrueGeometry.contains(a0.pos()):
            return

        self.hasClickedVideo = True
        self.selectionWindow.startPos = a0.pos() - self.videoTrueGeometry.topLeft()
        self.selectionWindow.endPos = None
        self.selectionWindow.update()

    def mouseMoveEvent(self, a0: Optional[QMouseEvent]) -> None:
        super().mouseMoveEvent(a0)
        if a0 is None:
            return

        # Move preview window
        if self.clickPreviewVec is not None and self.previewWindow.isVisible():
            self.previewAnchor = self.cropAnchor(a0.pos() + self.clickPreviewVec)
            self.previewRelGeometry.moveTopLeft(self.previewAnchor)
            globalPos = self.videoWidget.mapToGlobal(self.previewAnchor)
            self.previewWindow.setGeometry(QRect(globalPos, self.previewRelGeometry.size()))
            return

        # Move outside of video widget
        if not self.hasClickedVideo or not self.videoTrueGeometry.contains(a0.pos()):
            return

        self.previewWindow.hide()
        self.selectionWindow.endPos = a0.pos() - self.videoTrueGeometry.topLeft()
        self.selectionWindow.update()

    def mouseReleaseEvent(self, a0: Optional[QMouseEvent]) -> None:
        super().mouseMoveEvent(a0)
        if a0 is None or not self.hasClickedVideo:
            return

        self.hasClickedVideo = False
        self.clickPreviewVec = None

        self.selectionWindow.update()

        self.gifPreview()
        self.gifConversion()

    def closeWithConfirm(self) -> None:
        if not self.extractionRunning and not TMP_OUTPUT_FILE.exists():
            self.close()
            return

        confirmBox = QMessageBox()
        if self.extractionRunning:
            msg = "A GIF is being extracted right now, do you want to quit anyway?"
        else:
            msg = "A GIF has been extracted but not saved, do you want to quit anyway?"
        confirmBox.setText(msg)
        confirmBox.setStandardButtons(
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )

        quitValue = confirmBox.exec()
        if quitValue == QMessageBox.StandardButton.Ok:
            self.close()

    def closeEvent(self, a0: Optional[QCloseEvent]) -> None:
        self.selectionWindow.close()
        self.previewWindow.close()

        self.trimWorker.close()
        self.previewWorker.close()
        self.conversionWorker.close()
        self.optimizationWorker.close()

        TMP_MP4_TRIM_FILE.unlink(missing_ok=True)
        TMP_PREVIEW_FILE.unlink(missing_ok=True)
        TMP_OUTPUT_FILE.unlink(missing_ok=True)

        super().closeEvent(a0)

    def showHelp(self) -> None:
        """Display a help box with keybindings."""
        helpBox = HelpBox(self)
        helpBox.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        helpBox.setText(
            "<b>Hotkeys:</b><br>"
            "<b>&lt;C-O></b>: Open video<br>"
            "<b>&lt;C-S></b> OR <b>x</b>: Save clip<br>"
            "<b>Space</b> OR <b>K</b>: Play/pause<br>"
            "<b>, </b>: Previous frame<br>"
            "<b>. </b>: Next frame<br>"
            "<b>> </b>: Increase playback speed<br>"
            "<b>&lt; </b>: Decrease playback speed<br>"
            "<b>L / J</b>: Go +/-3s<br>"
            "<b>&lt;C-L> / &lt;C-J></b>: Go +/-1s<br>"
            "<b>&lt;M-L> / &lt;M-J></b>: Go +/-0.1s<br>"
            "<b>[n]</b>: Go to [n]% of the video<br>"
            "<b>S</b>: Mark start frame<br>"
            "<b>E</b>: Mark end frame<br>"
            "<b>A</b>: Go to start frame<br>"
            "<b>D</b>: Go to end frame<br>"
            "<b>C</b>: Clear selection<br>"
            "<b>P</b>: Toggle preview<br>"
            "<b>R</b>: Reset preview<br>"
            "<b>&lt;C-l></b>: Clear selection and preview<br>"
            "<b>Q</b>: Quit<br>"
            "<b>Escape</b>: Stop playback<br>"
            "<b>?</b>: Toggle this help<br>"
        )
        helpBox.exec()
        self.activateWindow()  # Ensure main window regains focus


if __name__ == "__main__":
    args = parseArgs()

    app = QApplication(sys.argv)
    player = VideoPlayer(args.videoPath)
    player.show()
    sys.exit(app.exec())

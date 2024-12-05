# TODO: add button to save gif
# TODO: reduce gif size -> maybe ugly version in preview and beautiful version when saving?
# TODO: bind `?` to window that recap all keybindings

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
import shutil
import subprocess
import sys
from pathlib import Path
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
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)


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
            self.minimum(), self.maximum(), p - sliderMin, sliderMax - sliderMin, opt.upsideDown
        )

    def paintEvent(self, ev: Optional[QPaintEvent]) -> None:
        """Override painting to add ticks on startTick and endTick positions"""
        if self.startTick is None and self.endTick is None:
            return super().paintEvent(ev)

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
            QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove
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


class FFmpegWorker(QObject):
    """
    Worker class to run the FFmpeg command in a separate thread.
    """
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

        self.tmpGifFile = Path("/tmp/gif_extractor_tmpfile.gif")
        self.extractThread = QThread()
        self.extractWorker: Optional[FFmpegWorker] = None

        # Overlays for selection and preview
        self.previewEnabled = True
        self.selectionWindow = SelectionWindow(self)
        self.previewWindow = PreviewWindow(self)
        self.previewAnchor: Optional[QPoint] = None
        self.clickOnPreview: Optional[QPoint] = None

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
            pos = self.previewAnchor
        else:
            pos = QPoint(self.videoTrueGeometry.right() - previewWidth, self.videoTrueGeometry.top())

        self.previewTrueGeometry = QRect(pos, QSize(previewWidth, previewHeight))
        globalPos = self.videoWidget.mapToGlobal(pos)
        self.previewWindow.setGeometry(QRect(globalPos, QSize(previewWidth, previewHeight)))
        if self.previewEnabled:
            self.previewWindow.show()

    def resizeEvent(self, a0: Optional[QResizeEvent]) -> None:
        super().resizeEvent(a0)
        if not hasattr(self, "videoWidget"):
            return

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
            self, "Open Video", "", "Video Files (*.mp4 *.avi *.mkv)"
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
                self.extractGif()

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
                self.extractGif()

    def gotoStartFrame(self) -> None:
        if self.startGifTime is not None:
            self.mediaPlayer.setPosition(self.startGifTime)

    def gotoEndFrame(self) -> None:
        if self.endGifTime is not None:
            self.mediaPlayer.setPosition(self.endGifTime)

    def onExtractStarted(self) -> None:
        self.statusLabel.setText("Extraction started...")

    def onExtractFinished(self, status: bool, msg: str) -> None:
        self.statusLabel.setText(msg)

        self.extractThread.started.disconnect()
        if self.extractWorker is not None:
            self.extractWorker.taskFinished.disconnect()
            self.extractWorker = None

        if status:
            self.previewWindow.loadGif(str(self.tmpGifFile))
            self.setPreviewPos()

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
                "-ss", startTimeStr, "-t", endTimeStr, str(self.tmpGifFile)]
        return cmd

    def extractGif(self) -> None:
        cmd = self.getExtractCmd()
        if cmd is None:
            return

        self.selectionWindow.validate()
        self.selectionWindow.update()

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
        if self.tmpGifFile.exists():
            shutil.copy(self.tmpGifFile, filePath)
            self.statusLabel.setText("Gif saved!")
        else:
            self.statusLabel.setText("No clip selected")

    def keyPressEvent(self, a0: Optional[QKeyEvent]) -> None:
        if not a0:
            return
        key = a0.key()

        if key == Qt.Key.Key_O and a0.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.openVideo()

        elif key == Qt.Key.Key_L and a0.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.selectionWindow.clearSelection()
            self.startGifTime = None
            self.endGifTime = None
            self.previewAnchor = None
            self.setPreviewPos()
            self.previewWindow.hide()

        elif key in {Qt.Key.Key_J, Qt.Key.Key_L}:
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

        elif key == Qt.Key.Key_G:
            self.saveGif()

        elif key == Qt.Key.Key_P:
            self.previewEnabled = not self.previewEnabled
            self.previewWindow.toggle()

        elif key == Qt.Key.Key_C:
            self.selectionWindow.clearSelection()

        elif key == Qt.Key.Key_R:
            self.previewAnchor = None
            self.setPreviewPos()

        elif key == Qt.Key.Key_Q:
            self.close()

    def mousePressEvent(self, a0: Optional[QMouseEvent]) -> None:
        super().mousePressEvent(a0)
        if a0 is None:
            return

        if a0.button() == Qt.MouseButton.MiddleButton:
            self.selectionWindow.clearSelection()
            return

        if a0.button() != Qt.MouseButton.LeftButton:
            return

        self.hasClickedVideo = True
        if self.previewWindow.isVisible() and self.previewTrueGeometry.contains(a0.pos()):
            self.clickOnPreview = a0.pos()
            return

        if not self.videoTrueGeometry.contains(a0.pos()):
            return

        clickPos = a0.pos() - self.videoTrueGeometry.topLeft()
        self.selectionWindow.startPos = clickPos
        self.selectionWindow.endPos = None
        self.selectionWindow.update()
        self.previewWindow.hide()

    def mouseMoveEvent(self, a0: Optional[QMouseEvent]) -> None:
        super().mouseMoveEvent(a0)
        if a0 is None or not self.hasClickedVideo:
            return

        if (
            self.clickOnPreview is not None
            and self.previewWindow.isVisible()
            and self.videoWidget.geometry().contains(a0.pos())
        ):
            self.previewAnchor = self.previewTrueGeometry.topLeft() + a0.pos() - self.clickOnPreview
            self.clickOnPreview = a0.pos()
            self.setPreviewPos()
            return

        if not self.videoTrueGeometry.contains(a0.pos()):
            return

        clickPos = a0.pos() - self.videoTrueGeometry.topLeft()
        self.selectionWindow.endPos = clickPos
        self.selectionWindow.update()

    def mouseReleaseEvent(self, a0: Optional[QMouseEvent]) -> None:
        super().mouseMoveEvent(a0)
        if a0 is None or not self.hasClickedVideo:
            return

        self.hasClickedVideo = False
        if self.clickOnPreview is not None:
            self.clickOnPreview = None
            return

        self.selectionWindow.update()
        self.extractGif()

    def closeEvent(self, a0: Optional[QCloseEvent]) -> None:
        self.tmpGifFile.unlink(missing_ok=True)
        self.selectionWindow.close()
        self.previewWindow.close()
        if self.extractWorker is not None:
            self.extractWorker.stop()

        self.extractThread.quit()
        self.extractThread.wait()
        self.extractThread.deleteLater()

        super().closeEvent(a0)


if __name__ == "__main__":
    args = parseArgs()

    app = QApplication(sys.argv)
    player = VideoPlayer(args.videoPath)
    player.show()
    sys.exit(app.exec())

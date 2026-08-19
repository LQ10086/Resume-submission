from __future__ import annotations

import codecs
from pathlib import Path
import shlex
import subprocess
import threading
from typing import Optional

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QInputMethodEvent, QKeyEvent, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from wcwidth import wcwidth

try:
    from winpty import PtyProcess, WinptyError
except ImportError:  # pragma: no cover
    PtyProcess = None
    WinptyError = OSError

try:
    import pyte
except ImportError:  # pragma: no cover
    pyte = None

from qt_core import (
    CODEX_BOOTSTRAP_MARKER,
    DEFAULT_TERMINAL_FONT,
    build_codex_startup_prompt,
    is_codex_command,
    normalize_terminal_font_size,
    resolve_terminal_cwd,
    terminal_process_spec,
)


def quote_terminal_argument(value: str, shell: str) -> str:
    if shell == "cmd":
        return '"' + value.replace('"', '""') + '"'
    return "'" + value.replace("'", "''") + "'"


def decode_terminal_chunk(decoder, chunk: object) -> str:
    if isinstance(chunk, bytes):
        return decoder.decode(chunk)
    return str(chunk)


def resolve_monospace_font(preferred: str) -> str:
    families = set(QFontDatabase.families())
    for name in (preferred, "Cascadia Mono", "Cascadia Code", "JetBrains Mono", "Consolas", "Courier New"):
        if name in families:
            return name
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family() or DEFAULT_TERMINAL_FONT


def terminal_column_to_text_index(text: str, column: int) -> int:
    used = 0
    for index, character in enumerate(text):
        width = max(0, wcwidth(character))
        if used + width > column:
            return index
        used += width
        if used == column:
            return index + 1
    return len(text)


class TerminalWorker(QThread):
    ready = Signal()
    output = Signal(str)
    failed = Signal(str)
    finished_with_code = Signal(int)

    def __init__(self, shell: str, cwd: Path, rows: int, columns: int) -> None:
        super().__init__()
        self.shell = shell
        self.cwd = cwd
        self.rows = rows
        self.columns = columns
        self.process = None
        self.pipe_process: Optional[subprocess.Popen] = None
        self._stop_requested = threading.Event()

    def run(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            command, environment = terminal_process_spec(self.shell)
            if PtyProcess is not None:
                self.process = PtyProcess.spawn(
                    subprocess.list2cmdline(command),
                    cwd=str(self.cwd),
                    env=environment,
                    dimensions=(self.rows, self.columns),
                )
                self.ready.emit()
                while not self._stop_requested.is_set() and self.process.isalive():
                    try:
                        chunk = self.process.read(4096)
                    except (EOFError, OSError, WinptyError):
                        break
                    if not chunk or chunk == b"0011Ignore":
                        continue
                    text = decode_terminal_chunk(decoder, chunk)
                    if text:
                        self.output.emit(text)
                code = self.process.exitstatus if self.process.exitstatus is not None else 0
            else:
                self.pipe_process = subprocess.Popen(
                    command,
                    cwd=str(self.cwd),
                    env=environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                self.ready.emit()
                if self.pipe_process.stdout is not None:
                    for line in self.pipe_process.stdout:
                        if self._stop_requested.is_set():
                            break
                        self.output.emit(line)
                code = self.pipe_process.wait()
            self.finished_with_code.emit(int(code or 0))
        except Exception as exc:  # terminal failures must be visible in the panel
            self.failed.emit(str(exc))

    def write(self, text: str) -> bool:
        if not text:
            return True
        try:
            if self.process is not None:
                self.process.write(text)
                return True
            if self.pipe_process is not None and self.pipe_process.stdin is not None:
                self.pipe_process.stdin.write(text)
                self.pipe_process.stdin.flush()
                return True
        except (OSError, ValueError, WinptyError):
            return False
        return False

    def resize_terminal(self, rows: int, columns: int) -> None:
        self.rows, self.columns = rows, columns
        if self.process is not None:
            try:
                self.process.setwinsize(rows, columns)
            except (OSError, WinptyError):
                pass

    def stop_terminal(self) -> None:
        self._stop_requested.set()
        try:
            if self.process is not None and self.process.isalive():
                self.process.terminate(force=True)
        except (OSError, WinptyError):
            pass
        try:
            if self.pipe_process is not None and self.pipe_process.poll() is None:
                self.pipe_process.terminate()
        except OSError:
            pass


class ImagePreviewDialog(QDialog):
    def __init__(self, image: QImage, title: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 680)
        self.image = image.copy()
        self.scale = 1.0

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(f"{image.width()} × {image.height()}"))
        toolbar.addStretch(1)
        for text, factor in (("－", 0.8), ("100%", 0.0), ("＋", 1.25)):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, f=factor: self._zoom(f))
            toolbar.addWidget(button)
        layout.addLayout(toolbar)

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("background:#17181a; padding:16px;")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.label)
        layout.addWidget(scroll, 1)
        self._render()

    def _zoom(self, factor: float) -> None:
        self.scale = 1.0 if factor == 0 else max(0.2, min(5.0, self.scale * factor))
        self._render()

    def _render(self) -> None:
        size = self.image.size() * self.scale
        pixmap = QPixmap.fromImage(self.image).scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.label.setPixmap(pixmap)
        self.label.resize(pixmap.size())


class AttachmentButton(QToolButton):
    def __init__(self, number: int, image: QImage, parent: QWidget) -> None:
        super().__init__(parent)
        self.number = number
        self.image = image.copy()
        preview = QPixmap.fromImage(image).scaled(
            QSize(52, 42), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.setIcon(preview)
        self.setIconSize(QSize(52, 42))
        self.setText(f"Image #{number}\n点击预览")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击在应用内查看原图")
        self.clicked.connect(self.open_preview)

    def open_preview(self) -> None:
        dialog = ImagePreviewDialog(self.image, f"Image #{self.number}", self.window())
        dialog.exec()


class TerminalView(QPlainTextEdit):
    paste_requested = Signal()
    raw_input = Signal(str)
    resized = Signal(int, int)
    page_requested = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setCursorWidth(0)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.document().setMaximumBlockCount(2100)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self._terminal_cursor_position = 0
        self._preedit_text = ""

    def set_terminal_cursor_position(self, position: int) -> None:
        self._terminal_cursor_position = max(0, min(int(position), self.document().characterCount() - 1))
        self.viewport().update()
        QApplication.inputMethod().update(Qt.InputMethodQuery.ImCursorRectangle)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        self._preedit_text = event.preeditString()
        committed = event.commitString()
        if committed:
            self.raw_input.emit(committed)
        self.viewport().update()
        event.accept()

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImEnabled:
            return True
        cursor = QTextCursor(self.document())
        cursor.setPosition(self._terminal_cursor_position)
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            return self.cursorRect(cursor)
        if query in {Qt.InputMethodQuery.ImCursorPosition, Qt.InputMethodQuery.ImAnchorPosition}:
            return self._terminal_cursor_position
        if query == Qt.InputMethodQuery.ImSurroundingText:
            return self.toPlainText()
        if query == Qt.InputMethodQuery.ImCurrentSelection:
            return self.textCursor().selectedText().replace("\u2029", "\n")
        return super().inputMethodQuery(query)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.hasFocus() or self.textCursor().hasSelection():
            return
        cursor = QTextCursor(self.document())
        cursor.setPosition(self._terminal_cursor_position)
        rect = self.cursorRect(cursor)
        painter = QPainter(self.viewport())
        color = self.palette().text().color()
        if self._preedit_text:
            metrics = self.fontMetrics()
            width = max(metrics.horizontalAdvance(self._preedit_text), metrics.horizontalAdvance("M"))
            text_rect = rect.adjusted(1, 0, width, 0)
            painter.fillRect(text_rect, self.palette().base())
            painter.setPen(color)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._preedit_text)
            painter.drawLine(text_rect.bottomLeft(), text_rect.bottomRight())
        else:
            painter.fillRect(rect.x(), rect.y(), 2, rect.height(), color)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        modifiers = event.modifiers()
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        key = event.key()

        if control and shift and key == Qt.Key.Key_C:
            self.copy()
            return
        if control and key == Qt.Key.Key_C:
            if self.textCursor().hasSelection():
                self.copy()
            else:
                self.raw_input.emit("\x03")
            return
        if control and key == Qt.Key.Key_Insert:
            self.copy()
            return
        if (control and key == Qt.Key.Key_V) or (shift and key == Qt.Key.Key_Insert):
            self.paste_requested.emit()
            return
        sequences = {
            Qt.Key.Key_Return: "\r", Qt.Key.Key_Enter: "\r", Qt.Key.Key_Backspace: "\x08",
            Qt.Key.Key_Tab: "\t", Qt.Key.Key_Escape: "\x1b", Qt.Key.Key_Up: "\x1b[A",
            Qt.Key.Key_Down: "\x1b[B", Qt.Key.Key_Right: "\x1b[C", Qt.Key.Key_Left: "\x1b[D",
            Qt.Key.Key_Home: "\x1b[H", Qt.Key.Key_End: "\x1b[F", Qt.Key.Key_Delete: "\x1b[3~",
            Qt.Key.Key_PageUp: "\x1b[5~", Qt.Key.Key_PageDown: "\x1b[6~",
        }
        if key in sequences:
            self.raw_input.emit(sequences[key])
            return
        if event.text() and not control:
            self.raw_input.emit(event.text())
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return
        self.page_requested.emit(-1 if event.angleDelta().y() > 0 else 1)
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        metrics = self.fontMetrics()
        columns = max(20, self.viewport().width() // max(1, metrics.horizontalAdvance("M")))
        rows = max(6, self.viewport().height() // max(1, metrics.lineSpacing()))
        self.resized.emit(rows, columns)


class TerminalWidget(QFrame):
    status_changed = Signal(str)

    def __init__(
        self,
        settings: dict,
        palette: dict[str, str],
        global_shortcuts: Optional[set[str]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.palette = palette
        self.global_shortcuts = global_shortcuts or set()
        self.shell = "cmd" if str(settings.get("terminal_shell", "powershell")).lower() == "cmd" else "powershell"
        self.cwd = resolve_terminal_cwd(settings.get("terminal_cwd", "tmp"))
        self.startup_command = str(settings.get("terminal_command", "") or "").strip()
        self.codex_prompt = build_codex_startup_prompt(self.cwd)
        self.worker: Optional[TerminalWorker] = None
        self.rows, self.columns = 30, 100
        self._ready = False
        self._closing = False
        self._bootstrap = is_codex_command(self.startup_command)
        self._bootstrap_complete = not self._bootstrap
        self._pending_render = False
        self._generation = 0
        self._startup_sent = False
        self._last_render_state: tuple[str, int] = ("", -1)
        self._attachment_count = 0
        self._attachments: list[QImage] = []
        self._pending_terminal_size: Optional[tuple[int, int]] = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self._apply_pending_terminal_resize)

        if pyte is not None:
            self.screen = pyte.screens.HistoryScreen(self.columns, self.rows, history=2000, ratio=0.5)
            self.stream = pyte.Stream(self.screen)
        else:
            self.screen = None
            self.stream = None

        self._build_ui()
        self.apply_theme(palette)
        QTimer.singleShot(0, self.start_terminal)

    def _build_ui(self) -> None:
        self.setObjectName("terminalPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("terminalHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 8, 8)
        self.title_label = QLabel(f"终端  ·  {self.shell.upper()}  ·  {self.cwd}")
        self.title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(self.title_label, 1)
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self.clear_output)
        self.retry_button = QPushButton("手动重试")
        self.retry_button.clicked.connect(self.restart_terminal)
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self.stop_terminal)
        for button in (self.clear_button, self.retry_button, self.stop_button):
            button.setFlat(True)
            header_layout.addWidget(button)
        layout.addWidget(header)

        self.state_frame = QFrame()
        state_layout = QHBoxLayout(self.state_frame)
        state_layout.setContentsMargins(18, 10, 18, 10)
        self.state_label = QLabel("终端正在准备…")
        self.state_label.setObjectName("terminalState")
        state_layout.addWidget(self.state_label)
        state_layout.addStretch(1)
        layout.addWidget(self.state_frame)

        self.attachment_area = QScrollArea()
        self.attachment_area.setWidgetResizable(True)
        self.attachment_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.attachment_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.attachment_area.setFixedHeight(72)
        self.attachment_host = QWidget()
        self.attachment_layout = QHBoxLayout(self.attachment_host)
        self.attachment_layout.setContentsMargins(8, 6, 8, 6)
        self.attachment_layout.setSpacing(8)
        self.attachment_layout.addStretch(1)
        self.attachment_area.setWidget(self.attachment_host)
        self.attachment_area.hide()
        layout.addWidget(self.attachment_area)

        self.view = TerminalView()
        family = resolve_monospace_font(str(self.settings.get("terminal_font", DEFAULT_TERMINAL_FONT)))
        font = QFont(family, normalize_terminal_font_size(self.settings.get("terminal_font_size")))
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.view.setFont(font)
        self.view.raw_input.connect(self.send_raw)
        self.view.paste_requested.connect(self.paste_clipboard)
        self.view.resized.connect(self.resize_terminal)
        self.view.page_requested.connect(self.scroll_history)
        layout.addWidget(self.view, 1)

    def apply_theme(self, palette: dict[str, str]) -> None:
        self.palette = palette
        self.setStyleSheet(
            f"""
            QFrame#terminalPanel {{ background:{palette['terminal']}; border-left:1px solid {palette['border']}; }}
            QFrame#terminalHeader {{ background:{palette['panel']}; border-bottom:1px solid {palette['border']}; }}
            QLabel {{ color:{palette['text']}; }}
            QLabel#terminalState {{ color:{palette['muted']}; font-weight:600; }}
            QPlainTextEdit {{ background:{palette['terminal']}; color:{palette['terminal_text']}; border:0;
                              selection-background-color:{palette['accent']}; padding:10px; }}
            QScrollArea {{ background:{palette['terminal']}; border:0; }}
            QToolButton {{ background:{palette['attachment']}; color:{palette['text']};
                           border:1px solid {palette['border']}; border-radius:8px; padding:4px 10px; }}
            QToolButton:hover {{ border-color:{palette['accent']}; }}
            QPushButton {{ color:{palette['muted']}; padding:3px 6px; }}
            QPushButton:hover {{ color:{palette['accent']}; }}
            """
        )

    def start_terminal(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self._generation += 1
        generation = self._generation
        self._ready = False
        self._startup_sent = False
        self._bootstrap = is_codex_command(self.startup_command)
        self._bootstrap_complete = not self._bootstrap
        self._last_render_state = ("", -1)
        self.state_frame.show()
        self.state_label.setText(
            f"Codex 正在准备（第 {generation} 次，仅点击“手动重试”才会重新启动）…"
            if self._bootstrap else "终端正在准备…"
        )
        self.view.setVisible(not self._bootstrap)
        self.retry_button.setEnabled(False)
        self.worker = TerminalWorker(self.shell, self.cwd, self.rows, self.columns)
        self.worker.ready.connect(self._on_ready)
        self.worker.output.connect(self._append_output)
        self.worker.failed.connect(self._on_failed)
        self.worker.finished_with_code.connect(self._on_finished)
        self.worker.start()

    def _on_ready(self) -> None:
        sender = self.sender()
        if sender is not None and sender is not self.worker:
            return
        if self._startup_sent:
            return
        self._ready = True
        self._startup_sent = True
        self.retry_button.setEnabled(True)
        if not self._bootstrap:
            self.state_frame.hide()
            self.view.show()
            self.status_changed.emit(f"终端已打开：{self.cwd}")
        if self.startup_command:
            QTimer.singleShot(350, lambda: self.send_line(self.startup_command))
        QTimer.singleShot(100, self.view.setFocus)
        if self._bootstrap:
            generation = self._generation
            QTimer.singleShot(30000, lambda g=generation: self._bootstrap_slow(g))
            QTimer.singleShot(90000, lambda g=generation: self._bootstrap_timeout(g))

    def _bootstrap_slow(self, generation: int) -> None:
        if generation == self._generation and self._bootstrap and not self._bootstrap_complete and not self._closing:
            self.state_label.setText("Codex 仍在准备；当前会话没有自动重试。首次启动或加载插件可能需要更久。")

    def _bootstrap_timeout(self, generation: int) -> None:
        if generation == self._generation and self._bootstrap and not self._bootstrap_complete and not self._closing:
            self.state_label.setText("Codex 准备超时，程序不会自动重试；需要时请点击“手动重试”。")
            self.retry_button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        sender = self.sender()
        if sender is not None and sender is not self.worker:
            return
        self.state_frame.show()
        self.state_label.setText(f"终端启动失败：{message}")
        self.retry_button.setEnabled(True)
        self.status_changed.emit("终端启动失败")

    def _on_finished(self, code: int) -> None:
        # A stopped worker can deliver its queued finished signal after a new
        # worker has already been installed by restart_terminal().  Ignore the
        # stale signal so it cannot replace the new session's preparing state.
        if self.sender() is not self.worker:
            return
        if self._closing:
            return
        self._ready = False
        self.state_frame.show()
        self.state_label.setText(f"终端已退出（代码 {code}），不会自动重试；可点击“手动重试”。")
        self.retry_button.setEnabled(True)

    def _append_output(self, text: str) -> None:
        sender = self.sender()
        if sender is not None and sender is not self.worker:
            return
        if self._closing:
            return
        if "\ufffd" in text:
            self.status_changed.emit("检测到终端替换字符，请检查输出编码。")
        if self.stream is not None:
            self.stream.feed(text)
            if not self._pending_render:
                self._pending_render = True
                # Codex redraws spinners and status lines very frequently. A
                # coalesced 10 FPS repaint keeps the embedded view stable
                # without losing any ConPTY bytes or terminal state.
                QTimer.singleShot(100, self._render_screen)
        else:
            self.view.moveCursor(QTextCursor.MoveOperation.End)
            self.view.insertPlainText(text)
            self.view.moveCursor(QTextCursor.MoveOperation.End)

    def _render_screen(self) -> None:
        self._pending_render = False
        if self.screen is None:
            return
        lines = list(self.screen.display)
        cursor_row = max(0, min(int(self.screen.cursor.y), len(lines) - 1)) if lines else 0
        if self._bootstrap:
            marker_row = next((index for index, line in enumerate(lines) if CODEX_BOOTSTRAP_MARKER in line), None)
            if marker_row is None:
                if not self._bootstrap_complete:
                    return
                self._bootstrap = False
            else:
                if not self._bootstrap_complete:
                    self._bootstrap_complete = True
                    self.state_frame.hide()
                    self.view.show()
                    self.view.setFocus()
                    self.status_changed.emit("Codex 已准备完成。")
                lines = ["Codex 已准备完成。"] + lines[marker_row + 1 :]
                cursor_row = max(0, int(self.screen.cursor.y) - marker_row)
        cursor_row = max(0, min(cursor_row, len(lines) - 1)) if lines else 0
        display_lines: list[str] = []
        for row, line in enumerate(lines):
            if row == cursor_row:
                cursor_index = terminal_column_to_text_index(line, int(self.screen.cursor.x))
                display_lines.append(line[: max(cursor_index, len(line.rstrip()))])
            else:
                display_lines.append(line.rstrip())
        rendered = "\n".join(display_lines).rstrip("\n")
        cursor_column = terminal_column_to_text_index(display_lines[cursor_row], int(self.screen.cursor.x)) if display_lines else 0
        cursor_position = sum(len(line) + 1 for line in display_lines[:cursor_row]) + cursor_column
        cursor_position = max(0, min(cursor_position, len(rendered)))
        if (rendered, cursor_position) == self._last_render_state:
            return
        self._last_render_state = (rendered, cursor_position)
        cursor = self.view.textCursor()
        had_selection = cursor.hasSelection()
        selected = cursor.selectedText() if had_selection else ""
        scrollbar = self.view.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum() - 2
        previous_scroll = scrollbar.value()
        self._replace_rendered_text(rendered)
        self.view.set_terminal_cursor_position(self._qt_text_position(rendered, cursor_position))
        if follow and not had_selection:
            scrollbar.setValue(scrollbar.maximum())
        elif not follow:
            scrollbar.setValue(min(previous_scroll, scrollbar.maximum()))
        if had_selection and selected:
            # A terminal repaint must not silently overwrite the clipboard;
            # selection is retained whenever the same text still exists.
            document_text = self.view.toPlainText()
            index = document_text.find(selected.replace("\u2029", "\n"))
            if index >= 0:
                restored = self.view.textCursor()
                restored.setPosition(self._qt_text_position(document_text, index))
                restored.setPosition(
                    self._qt_text_position(document_text, index + len(selected)),
                    QTextCursor.MoveMode.KeepAnchor,
                )
                self.view.setTextCursor(restored)

    @staticmethod
    def _qt_text_position(text: str, python_index: int) -> int:
        """Convert a Python character index to Qt's UTF-16 document offset."""
        python_index = max(0, min(int(python_index), len(text)))
        return len(text[:python_index].encode("utf-16-le")) // 2

    def _replace_rendered_text(self, rendered: str) -> None:
        """Patch only the changed terminal text instead of clearing the view.

        Codex frequently updates a spinner or one status line.  QPlainTextEdit's
        setPlainText() destroys and recreates the whole document, which causes
        a visible white/black flash.  A common-prefix/suffix patch keeps the
        existing document and repaints only the changed fragment.
        """
        previous = self.view.toPlainText()
        if previous == rendered:
            return

        prefix = 0
        shared = min(len(previous), len(rendered))
        while prefix < shared and previous[prefix] == rendered[prefix]:
            prefix += 1

        suffix = 0
        previous_remaining = len(previous) - prefix
        rendered_remaining = len(rendered) - prefix
        while (
            suffix < previous_remaining
            and suffix < rendered_remaining
            and previous[len(previous) - 1 - suffix] == rendered[len(rendered) - 1 - suffix]
        ):
            suffix += 1

        previous_end = len(previous) - suffix
        rendered_end = len(rendered) - suffix
        patch_cursor = QTextCursor(self.view.document())
        patch_cursor.beginEditBlock()
        patch_cursor.setPosition(self._qt_text_position(previous, prefix))
        patch_cursor.setPosition(
            self._qt_text_position(previous, previous_end),
            QTextCursor.MoveMode.KeepAnchor,
        )
        patch_cursor.insertText(rendered[prefix:rendered_end])
        patch_cursor.endEditBlock()

    def scroll_history(self, direction: int) -> None:
        if self.screen is None:
            bar = self.view.verticalScrollBar()
            bar.setValue(bar.value() + direction * bar.pageStep())
            return
        try:
            if direction < 0:
                self.screen.prev_page()
            else:
                self.screen.next_page()
            self._render_screen()
        except AttributeError:
            pass

    def send_line(self, line: str) -> None:
        actual = line
        if is_codex_command(line) and self.codex_prompt:
            if "--no-alt-screen" not in actual:
                actual += " --no-alt-screen"
            actual = f"{actual} {quote_terminal_argument(self.codex_prompt, self.shell)}"
        self._write_raw(actual + "\r\n")

    def send_raw(self, text: str) -> None:
        if self._bootstrap and not self._bootstrap_complete and self._ready:
            return
        self._write_raw(text)

    def _write_raw(self, text: str) -> None:
        worker = self.worker
        if worker is None or not worker.write(text):
            if self._ready:
                self.status_changed.emit("无法向终端发送输入。")

    def paste_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime is not None and mime.hasImage():
            image = clipboard.image()
            if image.isNull():
                data = mime.imageData()
                if isinstance(data, QImage):
                    image = data
            if not image.isNull():
                self.add_image_attachment(image)
                # Preserve the native image clipboard. Codex needs a modified
                # V key event rather than the bare SYN byte. Standard Alt+V is
                # represented by ESC+V in a VT stream and Codex accepts it as
                # the image-paste shortcut, so the user's Ctrl+V works through
                # ConPTY without rewriting the clipboard into a file path.
                self.send_raw("\x1bv")
                self.status_changed.emit("图片已粘贴到 Codex；点击附件可在应用内查看。")
                return
        text = clipboard.text()
        if text:
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            self.send_raw("\x1b[200~" + normalized + "\x1b[201~")
            self.status_changed.emit("文本已粘贴到终端。")

    def add_image_attachment(self, image: QImage) -> AttachmentButton:
        self._attachment_count += 1
        copied = image.copy()
        self._attachments.append(copied)
        button = AttachmentButton(self._attachment_count, copied, self.attachment_host)
        self.attachment_layout.insertWidget(self.attachment_layout.count() - 1, button)
        self.attachment_area.show()
        return button

    def resize_terminal(self, rows: int, columns: int) -> None:
        rows = max(6, int(rows))
        columns = max(20, int(columns))
        requested = (rows, columns)
        if requested == (self.rows, self.columns) and self._pending_terminal_size is None:
            return
        # Window and splitter drags can generate dozens of resize events per
        # second.  Coalesce them so pyte and ConPTY only see the final size.
        self._pending_terminal_size = requested
        self._resize_timer.start()

    def _apply_pending_terminal_resize(self) -> None:
        requested = self._pending_terminal_size
        self._pending_terminal_size = None
        if requested is None or requested == (self.rows, self.columns):
            return
        rows, columns = requested
        self.rows, self.columns = requested
        if self.screen is not None:
            self.screen.resize(lines=rows, columns=columns)
        if self.worker is not None:
            self.worker.resize_terminal(rows, columns)
        if self.screen is not None:
            self._render_screen()

    def clear_output(self) -> None:
        if self.screen is not None:
            self.screen.reset()
        self._last_render_state = ("", -1)
        self.view.clear()

    def stop_terminal(self) -> None:
        if self.worker is not None:
            self.worker.stop_terminal()

    def restart_terminal(self) -> None:
        old = self.worker
        if old is not None:
            try:
                old.finished_with_code.disconnect(self._on_finished)
            except (RuntimeError, TypeError):
                pass
            old.stop_terminal()
            if not old.wait(3000):
                self.state_frame.show()
                self.state_label.setText("正在停止旧终端，请稍后再试。")
                self.retry_button.setEnabled(True)
                return
        self.worker = None
        self.clear_output()
        self.start_terminal()

    def close_terminal(self) -> None:
        self._closing = True
        self._resize_timer.stop()
        self._pending_terminal_size = None
        if self.worker is not None:
            self.worker.stop_terminal()
            self.worker.wait(2000)

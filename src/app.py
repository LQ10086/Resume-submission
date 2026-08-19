from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Optional
import webbrowser

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QIcon, QKeySequence, QMouseEvent, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from qt_core import (
    APP_NAME,
    BASIC_GROUP,
    DATA_ROOT,
    DATABASE_DIR,
    DB_DIR,
    DEFAULT_DB,
    DEFAULT_GROUP,
    DEFAULT_SHORTCUTS,
    DEFAULT_TERMINAL_FONT,
    ITEM_TYPE_FILE,
    ITEM_TYPE_FOLDER,
    ITEM_TYPE_LABELS,
    ITEM_TYPE_LINK,
    ITEM_TYPE_SHORT_LABELS,
    ITEM_TYPE_TEXT,
    PROJECT_ROOT,
    ROOT,
    SAMPLE_DATA,
    SETTINGS_PATH,
    SHORTCUT_LABELS,
    TERMINAL_FONT_CANDIDATES,
    TERMINAL_POSITION_LABELS,
    THEME_LABELS,
    WindowsPasteHelper,
    build_open_with_argv,
    clean_filename,
    infer_group_name,
    load_settings,
    normalize_group_name,
    normalize_item_type,
    normalize_shortcut,
    normalize_terminal_font_size,
    normalize_terminal_position,
    normalize_theme,
    read_json_file,
    safe_enumerate_open_with_handlers,
    save_settings,
    theme_palette,
    truncate_text,
    write_json_file,
)
from terminal_qt import TerminalWidget, resolve_monospace_font


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if child_layout is not None:
            clear_layout(child_layout)
        if widget is not None:
            widget.deleteLater()


def find_item_name_replacements(
    keys: list[str],
    find_text: str,
    replacement: str,
    match_case: bool,
) -> list[tuple[str, str]]:
    """Return matching item-name replacements in visual order."""
    if not find_text:
        raise ValueError("查找内容不能为空。")
    flags = 0 if match_case else re.IGNORECASE
    pattern = re.compile(re.escape(find_text), flags)
    matches: list[tuple[str, str]] = []
    for key in keys:
        updated = pattern.sub(lambda _match: replacement, key).strip()
        if updated != key:
            matches.append((key, updated))
    return matches


def plan_item_name_replacements(
    keys: list[str],
    find_text: str,
    replacement: str,
    match_case: bool,
) -> dict[str, str]:
    """Build an atomic rename plan and reject empty or duplicate results."""
    matches = find_item_name_replacements(keys, find_text, replacement, match_case)
    mapping = dict(matches)
    for key, updated in matches:
        if not updated:
            raise ValueError(f"条目“{key}”替换后名称为空。")
    final_names = [mapping.get(key, key) for key in keys]
    duplicates = sorted({name for name in final_names if final_names.count(name) > 1})
    if duplicates:
        preview = "、".join(duplicates[:3])
        raise ValueError(f"替换后会产生重名：{preview}")
    return mapping


class FlowLayout(QLayout):
    """A wrapping Qt layout used by each entry group."""

    def __init__(self, parent: Optional[QWidget] = None, margin: int = 0, hspacing: int = 8, vspacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._hspacing = hspacing
        self._vspacing = vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def insertWidget(self, index: int, widget: QWidget) -> None:
        self.addChildWidget(widget)
        self._items.insert(max(0, min(index, len(self._items))), QWidgetItem(widget))
        self.invalidate()

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = effective.x(), effective.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._hspacing
            if next_x - self._hspacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + self._vspacing
                next_x = x + hint.width() + self._hspacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class CollapsibleSideTabs(QTabWidget):
    """A side container whose contents must not impose a splitter minimum."""

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)


class ShrinkablePanel(QWidget):
    """A splitter pane that can shrink continuously instead of snapping."""

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)


class ChipButton(QPushButton):
    activated = Signal(str, object)
    context_requested = Signal(str, QPoint)

    def __init__(self, key: str, text: str, value: str, parent: QWidget) -> None:
        super().__init__(text, parent)
        self.item_key = key
        self.item_value = value
        self._press_pos = QPoint()
        self._dragging = False
        self.setObjectName("entryChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(34)
        self.setToolTip(key)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return super().mouseMoveEvent(event)
        if (event.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._dragging = True
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-resume-quick-item", self.item_key.encode("utf-8"))
        mime.setText(self.item_value)
        drag.setMimeData(mime)
        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(self._press_pos)
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        dragging = self._dragging
        self._dragging = False
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and not dragging and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self.item_key, event.modifiers())

    def contextMenuEvent(self, event) -> None:
        self.context_requested.emit(self.item_key, event.globalPos())


class GroupWidget(QGroupBox):
    item_dropped = Signal(str, str, int)

    def __init__(self, group: str, parent: QWidget) -> None:
        super().__init__(group, parent)
        self.group = group
        self.setObjectName("entryGroup")
        self.setAcceptDrops(True)
        self.flow = FlowLayout(self, margin=12, hspacing=8, vspacing=8)
        self.setLayout(self.flow)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-resume-quick-item"):
            event.acceptProposedAction()
            self.setProperty("dropTarget", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dropTarget", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self.setProperty("dropTarget", False)
        self.style().unpolish(self)
        self.style().polish(self)
        raw = bytes(event.mimeData().data("application/x-resume-quick-item"))
        try:
            key = raw.decode("utf-8")
        except UnicodeDecodeError:
            return
        position = event.position().toPoint()
        chips = [self.flow.itemAt(i).widget() for i in range(self.flow.count())]
        chips = [chip for chip in chips if isinstance(chip, ChipButton) and chip.item_key != key]
        index = len(chips)
        for idx, chip in enumerate(chips):
            center = chip.geometry().center()
            if position.y() < center.y() or (abs(position.y() - center.y()) <= chip.height() // 2 and position.x() < center.x()):
                index = idx
                break
        self.item_dropped.emit(key, self.group, index)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()


class ItemDialog(QDialog):
    def __init__(
        self,
        title: str,
        groups: list[str],
        initial_key: str = "",
        initial_value: str = "",
        initial_group: str = DEFAULT_GROUP,
        initial_type: str = ITEM_TYPE_TEXT,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(680, 430)
        self.groups = list(groups)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.key_edit = QLineEdit(initial_key)
        form.addRow("键名", self.key_edit)
        group_row = QHBoxLayout()
        self.group_combo = QComboBox()
        self.group_combo.setEditable(False)
        self.group_combo.addItems(self.groups)
        normalized_initial_group = normalize_group_name(initial_group)
        initial_group_index = self.group_combo.findText(normalized_initial_group)
        if initial_group_index < 0:
            self.group_combo.addItem(normalized_initial_group)
            initial_group_index = self.group_combo.count() - 1
        self.group_combo.setCurrentIndex(initial_group_index)
        group_row.addWidget(self.group_combo, 1)
        new_group = QPushButton("新建分组")
        new_group.clicked.connect(self._new_group)
        group_row.addWidget(new_group)
        form.addRow("分组", group_row)
        self.type_combo = QComboBox()
        for item_type, label in ITEM_TYPE_LABELS.items():
            self.type_combo.addItem(label, item_type)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(normalize_item_type(initial_type))))
        self.type_combo.currentIndexChanged.connect(self._update_browse)
        form.addRow("条目类型", self.type_combo)
        layout.addLayout(form)

        content_header = QHBoxLayout()
        content_header.addWidget(QLabel("内容、网址或本地路径"))
        content_header.addStretch(1)
        self.file_button = QPushButton("选择文件")
        self.folder_button = QPushButton("选择文件夹")
        self.file_button.clicked.connect(self._browse_file)
        self.folder_button.clicked.connect(self._browse_folder)
        content_header.addWidget(self.file_button)
        content_header.addWidget(self.folder_button)
        layout.addLayout(content_header)
        self.value_edit = QTextEdit(initial_value)
        layout.addWidget(self.value_edit, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_browse()
        (self.value_edit if initial_key else self.key_edit).setFocus()

    def _new_group(self) -> None:
        name, ok = QInputDialog.getText(self, "新建分组", "输入新分组名称：")
        if ok and name.strip():
            group = normalize_group_name(name)
            if self.group_combo.findText(group) < 0:
                self.group_combo.addItem(group)
            self.group_combo.setCurrentText(group)

    def _update_browse(self) -> None:
        item_type = self.type_combo.currentData()
        self.file_button.setEnabled(item_type in {ITEM_TYPE_FILE, ITEM_TYPE_LINK})
        self.folder_button.setEnabled(item_type in {ITEM_TYPE_FOLDER, ITEM_TYPE_LINK})

    def _browse_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择文件")
        if path:
            self.value_edit.setPlainText(path)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            self.value_edit.setPlainText(path)

    def _validate(self) -> None:
        if not self.key_edit.text().strip():
            QMessageBox.warning(self, "缺少键名", "请先填写键名。")
            return
        if not self.value_edit.toPlainText().strip():
            QMessageBox.warning(self, "缺少内容", "请填写文本、文件路径、文件夹路径或网址。")
            return
        self.accept()

    def result_value(self) -> tuple[str, str, str, str]:
        return (
            self.key_edit.text().strip(),
            self.value_edit.toPlainText(),
            normalize_group_name(self.group_combo.currentText()),
            normalize_item_type(self.type_combo.currentData()),
        )


class SearchReplaceDialog(QDialog):
    def __init__(self, keys: list[str], initial_find: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.keys = list(keys)
        self.setWindowTitle("查找并替换条目名称")
        self.resize(520, 230)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.find_edit = QLineEdit(initial_find)
        self.find_edit.setClearButtonEnabled(True)
        self.replace_edit = QLineEdit()
        self.replace_edit.setClearButtonEnabled(True)
        form.addRow("查找名称中的", self.find_edit)
        form.addRow("替换为", self.replace_edit)
        layout.addLayout(form)
        self.match_case = QCheckBox("区分大小写")
        layout.addWidget(self.match_case)
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setObjectName("muted")
        layout.addWidget(self.preview_label)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setText("开始逐项替换")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.find_edit.textChanged.connect(self._update_preview)
        self.replace_edit.textChanged.connect(self._update_preview)
        self.match_case.toggled.connect(self._update_preview)
        self._update_preview()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def _update_preview(self, *_args) -> None:
        find_text = self.find_edit.text()
        if not find_text:
            self.preview_label.setText("请输入要查找的名称片段。")
            return
        try:
            matches = find_item_name_replacements(
                self.keys,
                find_text,
                self.replace_edit.text(),
                self.match_case.isChecked(),
            )
        except ValueError as exc:
            self.preview_label.setText(str(exc))
            return
        self.preview_label.setText(f"找到 {len(matches)} 个匹配项，将逐项询问是否替换。")

    def _validate(self) -> None:
        try:
            matches = find_item_name_replacements(
                self.keys,
                self.find_edit.text(),
                self.replace_edit.text(),
                self.match_case.isChecked(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "无法替换", str(exc))
            return
        if not matches:
            QMessageBox.information(self, "没有匹配", "没有找到需要替换的条目名称。")
            return
        self.accept()

    def result_value(self) -> tuple[str, str, bool]:
        return self.find_edit.text(), self.replace_edit.text(), self.match_case.isChecked()


class ItemInfoPanel(QWidget):
    """Inline editor shown beside the item grid in the shared side panel."""

    save_requested = Signal(str, str, str, str, str)
    dialog_requested = Signal()
    reload_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.loaded_key: Optional[str] = None
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("infoHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 9, 10, 9)
        title = QLabel("条目信息")
        title.setObjectName("infoTitle")
        header_layout.addWidget(title)
        header_layout.addStretch(1)
        self.dialog_button = QPushButton("弹窗编辑")
        self.dialog_button.setFlat(True)
        self.dialog_button.clicked.connect(self.dialog_requested)
        header_layout.addWidget(self.dialog_button)
        outer.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        content = QVBoxLayout(self.host)
        content.setContentsMargins(16, 14, 16, 16)
        content.setSpacing(12)

        self.empty_label = QLabel("点击左侧一个条目后，可在这里查看并修改信息。")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setObjectName("infoEmpty")
        content.addWidget(self.empty_label, 1)

        self.editor = QWidget()
        editor_layout = QVBoxLayout(self.editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(10)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.key_edit = QLineEdit()
        form.addRow("键名", self.key_edit)
        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        form.addRow("分组", self.group_combo)
        self.type_combo = QComboBox()
        for item_type, label in ITEM_TYPE_LABELS.items():
            self.type_combo.addItem(label, item_type)
        self.type_combo.currentIndexChanged.connect(self._update_browse_buttons)
        form.addRow("条目类型", self.type_combo)
        editor_layout.addLayout(form)

        value_header = QHBoxLayout()
        value_header.addWidget(QLabel("内容、网址或本地路径"))
        value_header.addStretch(1)
        self.file_button = QPushButton("选择文件")
        self.folder_button = QPushButton("选择文件夹")
        self.file_button.clicked.connect(self._browse_file)
        self.folder_button.clicked.connect(self._browse_folder)
        value_header.addWidget(self.file_button)
        value_header.addWidget(self.folder_button)
        editor_layout.addLayout(value_header)
        self.value_edit = QTextEdit()
        self.value_edit.setMinimumHeight(180)
        editor_layout.addWidget(self.value_edit, 1)

        self.state_label = QLabel("修改后点击“保存修改”。")
        self.state_label.setObjectName("muted")
        self.state_label.setWordWrap(True)
        editor_layout.addWidget(self.state_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.reset_button = QPushButton("重置")
        self.reset_button.clicked.connect(self.reset_current)
        self.save_button = QPushButton("保存修改")
        self.save_button.setProperty("accent", True)
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.save_button)
        editor_layout.addLayout(buttons)
        content.addWidget(self.editor, 1)
        self.scroll.setWidget(self.host)
        outer.addWidget(self.scroll, 1)

        for editor in (self.key_edit, self.group_combo.lineEdit(), self.value_edit):
            if editor is not None:
                editor.textChanged.connect(self._mark_dirty)
        self.type_combo.currentIndexChanged.connect(self._mark_dirty)
        self.show_message("点击左侧一个条目后，可在这里查看并修改信息。")

    def show_message(self, message: str) -> None:
        self.loaded_key = None
        self.empty_label.setText(message)
        self.empty_label.show()
        self.editor.hide()
        self.dialog_button.setEnabled(False)

    def load_item(
        self,
        key: str,
        value: str,
        group: str,
        item_type: str,
        groups: list[str],
        *,
        force: bool = False,
    ) -> None:
        if self.loaded_key == key and not force:
            self._loading = True
            self.set_groups(groups)
            self._loading = False
            return
        self._loading = True
        self.set_groups(groups)
        self.loaded_key = key
        self.key_edit.setText(key)
        self.group_combo.setCurrentText(normalize_group_name(group))
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(normalize_item_type(item_type))))
        self.value_edit.setPlainText(value)
        self._loading = False
        self.state_label.setText("修改后点击“保存修改”。")
        self.empty_label.hide()
        self.editor.show()
        self.dialog_button.setEnabled(True)
        self._update_browse_buttons()

    def set_groups(self, groups: list[str]) -> None:
        current = self.group_combo.currentText()
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItems(groups)
        self.group_combo.setCurrentText(current)
        self.group_combo.blockSignals(False)

    def _mark_dirty(self, *_args) -> None:
        if not self._loading and self.loaded_key is not None:
            self.state_label.setText("有尚未保存的修改。")

    def _update_browse_buttons(self) -> None:
        item_type = self.type_combo.currentData()
        self.file_button.setEnabled(item_type in {ITEM_TYPE_FILE, ITEM_TYPE_LINK})
        self.folder_button.setEnabled(item_type in {ITEM_TYPE_FOLDER, ITEM_TYPE_LINK})

    def _browse_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择文件")
        if path:
            self.value_edit.setPlainText(path)

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            self.value_edit.setPlainText(path)

    def _save(self) -> None:
        if self.loaded_key is None:
            return
        key = self.key_edit.text().strip()
        value = self.value_edit.toPlainText()
        if not key:
            self.state_label.setText("键名不能为空。")
            self.key_edit.setFocus()
            return
        if not value.strip():
            self.state_label.setText("内容不能为空。")
            self.value_edit.setFocus()
            return
        self.save_requested.emit(
            self.loaded_key,
            key,
            value,
            normalize_group_name(self.group_combo.currentText()),
            normalize_item_type(self.type_combo.currentData()),
        )

    def reset_current(self) -> None:
        if self.loaded_key is not None:
            self.state_label.setText("正在恢复已保存内容…")
            self.reload_requested.emit()


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(640, 560)
        self.settings = dict(settings)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        shortcut_page, shortcut_form = self._scroll_form()
        self.shortcut_edits = {}
        for name, label in SHORTCUT_LABELS.items():
            from PySide6.QtWidgets import QKeySequenceEdit
            edit = QKeySequenceEdit(QKeySequence(str(settings.get("shortcuts", {}).get(name, DEFAULT_SHORTCUTS[name]))))
            edit.setClearButtonEnabled(True)
            shortcut_form.addRow(label, edit)
            self.shortcut_edits[name] = edit
        tabs.addTab(shortcut_page, "快捷键")

        terminal_page, terminal_form = self._scroll_form()
        self.shell_combo = QComboBox()
        self.shell_combo.addItem("PowerShell", "powershell")
        self.shell_combo.addItem("CMD", "cmd")
        self.shell_combo.setCurrentIndex(max(0, self.shell_combo.findData(settings.get("terminal_shell", "powershell"))))
        terminal_form.addRow("终端类型", self.shell_combo)
        self.cwd_edit = QLineEdit(str(settings.get("terminal_cwd", "tmp")))
        terminal_form.addRow("工作目录", self.cwd_edit)
        self.command_edit = QLineEdit(str(settings.get("terminal_command", "codex") or ""))
        terminal_form.addRow("启动命令", self.command_edit)
        self.position_combo = QComboBox()
        for key, label in TERMINAL_POSITION_LABELS.items():
            self.position_combo.addItem(label, key)
        self.position_combo.setCurrentIndex(max(0, self.position_combo.findData(normalize_terminal_position(settings.get("terminal_position")))))
        terminal_form.addRow("停靠位置", self.position_combo)
        self.font_combo = QComboBox()
        self.font_combo.setEditable(True)
        self.font_combo.addItems(TERMINAL_FONT_CANDIDATES)
        self.font_combo.setCurrentText(str(settings.get("terminal_font", DEFAULT_TERMINAL_FONT)))
        terminal_form.addRow("终端字体", self.font_combo)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 24)
        self.font_size.setValue(normalize_terminal_font_size(settings.get("terminal_font_size")))
        terminal_form.addRow("终端字号", self.font_size)
        tabs.addTab(terminal_page, "终端")

        appearance_page, appearance_form = self._scroll_form()
        self.theme_combo = QComboBox()
        for key, label in THEME_LABELS.items():
            self.theme_combo.addItem(label, key)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(normalize_theme(settings.get("theme")))))
        appearance_form.addRow("主题", self.theme_combo)
        width_note = QLabel("主窗口默认采用更宽的左右布局；终端宽度可直接拖动分隔条调整。")
        width_note.setWordWrap(True)
        appearance_form.addRow(width_note)
        tabs.addTab(appearance_page, "外观")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _scroll_form(self) -> tuple[QScrollArea, QFormLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        form = QFormLayout(host)
        form.setContentsMargins(18, 18, 18, 18)
        form.setVerticalSpacing(14)
        scroll.setWidget(host)
        return scroll, form

    def _validate(self) -> None:
        shortcuts = {}
        for name, edit in self.shortcut_edits.items():
            text = edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
            normalized = normalize_shortcut(text)
            if not normalized:
                QMessageBox.warning(self, "快捷键为空", f"请为“{SHORTCUT_LABELS[name]}”设置快捷键。")
                return
            shortcuts[name] = normalized
        duplicates = {value for value in shortcuts.values() if list(shortcuts.values()).count(value) > 1}
        if duplicates:
            QMessageBox.warning(self, "快捷键冲突", "以下快捷键被重复使用：" + "、".join(sorted(duplicates)))
            return
        self.accept()

    def values(self) -> dict:
        shortcuts = {
            name: normalize_shortcut(edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText))
            for name, edit in self.shortcut_edits.items()
        }
        return {
            "shortcuts": shortcuts,
            "terminal_hotkey": shortcuts["terminal_toggle"],
            "terminal_shell": self.shell_combo.currentData(),
            "terminal_cwd": self.cwd_edit.text().strip() or "tmp",
            "terminal_command": self.command_edit.text().strip(),
            "terminal_position": self.position_combo.currentData(),
            "terminal_font": self.font_combo.currentText().strip() or DEFAULT_TERMINAL_FONT,
            "terminal_font_size": self.font_size.value(),
            "theme": self.theme_combo.currentData(),
        }


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.shortcuts = dict(self.settings["shortcuts"])
        self.palette = theme_palette(self.settings.get("theme"))
        self.current_db = ""
        self.data: dict[str, str] = {}
        self.item_order: list[str] = []
        self.item_type_by_key: dict[str, str] = {}
        self.group_by_key: dict[str, str] = {}
        self.group_order: list[str] = []
        self.selected_key: Optional[str] = None
        self.selected_keys: set[str] = set()
        self.chips: dict[str, ChipButton] = {}
        self.group_widgets: dict[str, GroupWidget] = {}
        self.explorer_reveal_armed = False
        self.terminal: Optional[TerminalWidget] = None
        self.terminal_tab_index = -1
        self._shortcuts: list[QShortcut] = []

        self.setWindowTitle(APP_NAME)
        self.resize(int(self.settings.get("window_width", 1240)), int(self.settings.get("window_height", 720)))
        self.setMinimumSize(360, 300)
        self._ensure_default_files()
        self.paste_helper = WindowsPasteHelper(lambda text: QApplication.clipboard().setText(text))
        self._build_ui()
        self.apply_theme()
        self._install_shortcuts()
        self.refresh_databases()
        self.apply_topmost()
        self.foreground_timer = QTimer(self)
        self.foreground_timer.timeout.connect(self.poll_foreground)
        self.foreground_timer.start(300)

    def _ensure_default_files(self) -> None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        bundled = ROOT / DATABASE_DIR
        if not any(DB_DIR.glob("*.json")) and bundled.resolve() != DB_DIR.resolve() and bundled.exists():
            for source in bundled.glob("*.json"):
                destination = DB_DIR / source.name
                if not destination.exists():
                    shutil.copy2(source, destination)
        if not any(DB_DIR.glob("*.json")):
            write_json_file(DB_DIR / DEFAULT_DB, SAMPLE_DATA)

    def _build_ui(self) -> None:
        settings_menu = self.menuBar().addMenu("设置")
        settings_menu.addAction("设置", self.open_settings)
        settings_menu.addAction("打开/隐藏终端", self.toggle_terminal)
        settings_menu.addAction("显示条目信息", self.show_info_panel)
        item_menu = self.menuBar().addMenu("条目")
        item_menu.addAction("搜索条目（Ctrl+F）", self.focus_item_search)
        item_menu.addAction("查找并替换名称（Ctrl+R）", self.replace_item_names)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        toolbar = QFrame()
        toolbar.setObjectName("toolbar")
        self.toolbar_grid = QGridLayout(toolbar)
        self.toolbar_grid.setContentsMargins(14, 12, 14, 10)
        self.toolbar_grid.setHorizontalSpacing(9)
        self.toolbar_grid.setVerticalSpacing(9)
        self.db_label = QLabel("资料库")
        self.db_combo = QComboBox()
        self.db_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.db_combo.currentTextChanged.connect(self._database_changed)
        self.db_buttons: list[QPushButton] = []
        for text, callback in (("新建库", self.new_database), ("重命名", self.rename_database), ("删除库", self.delete_database)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            if text == "删除库":
                button.setProperty("danger", True)
            self.db_buttons.append(button)

        self.search_label = QLabel("搜索")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索条目名称或内容（Ctrl+F）")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.refresh_items)
        self.add_button = QPushButton("新增条目")
        self.add_button.setProperty("accent", True)
        self.add_button.clicked.connect(self.add_item)
        self.auto_paste = QCheckBox("点击后自动粘贴")
        self.auto_paste.setChecked(bool(self.settings.get("auto_paste", False)))
        self.auto_paste.toggled.connect(self.save_user_settings)
        self.topmost = QCheckBox("窗口置顶")
        self.topmost.setChecked(bool(self.settings.get("topmost", True)))
        self.topmost.toggled.connect(self.apply_topmost)
        self._toolbar_widgets = (
            self.db_label,
            self.db_combo,
            *self.db_buttons,
            self.search_label,
            self.search_edit,
            self.add_button,
            self.auto_paste,
            self.topmost,
        )
        self._toolbar_compact: Optional[bool] = None
        self._relayout_toolbar(self.width() < 760)
        root.addWidget(toolbar)

        orientation = Qt.Orientation.Horizontal if normalize_terminal_position(self.settings.get("terminal_position")) == "right" else Qt.Orientation.Vertical
        self.splitter = QSplitter(orientation)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setOpaqueResize(True)
        self.splitter.setHandleWidth(7)
        root.addWidget(self.splitter, 1)

        self.main_panel = ShrinkablePanel()
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)
        self.item_scroll = QScrollArea()
        self.item_scroll.setWidgetResizable(True)
        self.item_host = QWidget()
        self.item_layout = QVBoxLayout(self.item_host)
        self.item_layout.setContentsMargins(4, 4, 4, 4)
        self.item_layout.setSpacing(10)
        self.item_layout.addStretch(1)
        self.item_scroll.setWidget(self.item_host)
        main_layout.addWidget(self.item_scroll, 1)

        selection = QFrame()
        selection.setObjectName("selectionBar")
        selection_layout = QHBoxLayout(selection)
        selection_layout.setContentsMargins(4, 4, 4, 4)
        self.selected_label = QLabel("未选择条目")
        self.preview_label = QLabel("")
        self.preview_label.setObjectName("muted")
        selection_layout.addWidget(self.selected_label)
        selection_layout.addWidget(self.preview_label, 1)
        self.edit_button = QPushButton("编辑")
        self.edit_button.clicked.connect(self.edit_selected)
        self.group_button = QPushButton("分组")
        self.group_button.clicked.connect(self.change_group_selected)
        self.delete_button = QPushButton("删除")
        self.delete_button.setProperty("danger", True)
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.edit_button, self.group_button, self.delete_button):
            selection_layout.addWidget(button)
            button.hide()
        main_layout.addWidget(selection)

        footer = QHBoxLayout()
        self.status_label = QLabel("先点击目标输入框，再点击快捷按钮。")
        self.status_label.setObjectName("muted")
        self.target_label = QLabel("上一个目标窗口：未捕获")
        self.target_label.setObjectName("muted")
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.target_label)
        main_layout.addLayout(footer)
        self.splitter.addWidget(self.main_panel)

        self.side_tabs = CollapsibleSideTabs()
        self.side_tabs.setObjectName("sideTabs")
        self.info_panel = ItemInfoPanel(self.side_tabs)
        self.info_panel.save_requested.connect(self.save_info_item)
        self.info_panel.dialog_requested.connect(self.edit_selected)
        self.info_panel.reload_requested.connect(lambda: self.sync_info_panel(force=True))
        self.info_tab_index = self.side_tabs.addTab(self.info_panel, "信息")
        self.splitter.addWidget(self.side_tabs)
        self.splitter.setCollapsible(0, True)
        self.splitter.setCollapsible(1, True)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.side_tabs.hide()

    def _relayout_toolbar(self, compact: bool) -> None:
        if self._toolbar_compact == compact:
            return
        for widget in self._toolbar_widgets:
            self.toolbar_grid.removeWidget(widget)
        for column in range(5):
            self.toolbar_grid.setColumnStretch(column, 0)

        if compact:
            self.toolbar_grid.addWidget(self.db_label, 0, 0)
            self.toolbar_grid.addWidget(self.db_combo, 0, 1, 1, 3)
            for column, button in enumerate(self.db_buttons, 1):
                self.toolbar_grid.addWidget(button, 1, column)
            self.toolbar_grid.addWidget(self.search_label, 2, 0)
            self.toolbar_grid.addWidget(self.search_edit, 2, 1, 1, 2)
            self.toolbar_grid.addWidget(self.add_button, 2, 3)
            self.toolbar_grid.addWidget(self.auto_paste, 3, 1, 1, 2)
            self.toolbar_grid.addWidget(self.topmost, 3, 3)
            self.toolbar_grid.setColumnStretch(1, 1)
            self.toolbar_grid.setColumnStretch(2, 1)
        else:
            self.toolbar_grid.addWidget(self.db_label, 0, 0)
            self.toolbar_grid.addWidget(self.db_combo, 0, 1)
            for column, button in enumerate(self.db_buttons, 2):
                self.toolbar_grid.addWidget(button, 0, column)
            self.toolbar_grid.addWidget(self.search_label, 1, 0)
            self.toolbar_grid.addWidget(self.search_edit, 1, 1)
            self.toolbar_grid.addWidget(self.add_button, 1, 2)
            self.toolbar_grid.addWidget(self.auto_paste, 1, 3)
            self.toolbar_grid.addWidget(self.topmost, 1, 4)
            self.toolbar_grid.setColumnStretch(1, 1)
        self._toolbar_compact = compact
        self.toolbar_grid.invalidate()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "toolbar_grid"):
            self._relayout_toolbar(self.width() < 760)

    def apply_theme(self) -> None:
        self.palette = theme_palette(self.settings.get("theme"))
        p = self.palette
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ background:{p['bg']}; color:{p['text']}; font-family:'Microsoft YaHei UI'; font-size:14px; }}
            QSplitter::handle {{ background:{p['border']}; }}
            QSplitter::handle:hover {{ background:{p['accent']}; }}
            QFrame#toolbar, QFrame#selectionBar {{ background:{p['panel']}; }}
            QLineEdit, QTextEdit, QComboBox, QSpinBox {{ background:{p['input']}; color:{p['text']};
                border:1px solid {p['border']}; border-radius:6px; padding:6px 8px; min-height:22px; }}
            QPushButton {{ background:{p['control']}; color:{p['text']}; border:1px solid {p['border']};
                border-radius:6px; padding:6px 12px; min-height:22px; }}
            QPushButton:hover {{ border-color:{p['accent']}; background:{p['accent_light']}; }}
            QPushButton[accent='true'] {{ background:{p['accent']}; color:{p['selected_text']}; border-color:{p['accent']}; }}
            QPushButton[danger='true'] {{ color:{p['danger']}; }}
            QPushButton#entryChip {{ background:{p['chip']}; border:1px solid {p['chip_border']}; padding:6px 12px; }}
            QPushButton#entryChip:hover {{ background:{p['chip_hover']}; border-color:{p['accent']}; }}
            QPushButton#entryChip[selected='true'] {{ background:{p['accent']}; color:{p['selected_text']}; border-color:{p['accent']}; }}
            QGroupBox#entryGroup {{ background:{p['panel']}; border:1px solid {p['group_border']}; border-radius:10px;
                margin-top:12px; padding-top:8px; font-weight:600; }}
            QGroupBox#entryGroup::title {{ subcontrol-origin:margin; left:14px; padding:0 6px; }}
            QGroupBox#entryGroup[dropTarget='true'] {{ border:2px solid {p['accent']}; }}
            QScrollArea {{ border:0; background:{p['panel']}; }}
            QLabel#muted {{ color:{p['muted']}; }}
            QMenuBar, QMenu {{ background:{p['panel']}; color:{p['text']}; }}
            QMenu::item:selected {{ background:{p['accent_light']}; }}
            QTabWidget::pane {{ border:1px solid {p['border']}; }}
            QTabBar::tab {{ background:{p['control']}; padding:8px 16px; }}
            QTabBar::tab:selected {{ background:{p['panel']}; color:{p['accent']}; }}
            QTabWidget#sideTabs::pane {{ border:0; border-left:1px solid {p['border']}; }}
            QFrame#infoHeader {{ background:{p['panel']}; border-bottom:1px solid {p['border']}; }}
            QLabel#infoTitle {{ font-weight:600; }}
            QLabel#infoEmpty {{ color:{p['muted']}; padding:28px; }}
            """
        )
        if self.terminal is not None:
            self.terminal.apply_theme(p)

    def _install_shortcuts(self) -> None:
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts = []
        actions = {
            "terminal_toggle": self.toggle_terminal,
            "add_item": self.add_item,
            "edit_item": self.edit_selected,
            "move_left": lambda: self.move_selected_within_group(-1),
            "move_right": lambda: self.move_selected_within_group(1),
            "move_group_up": lambda: self.move_selected_group(-1),
            "move_group_down": lambda: self.move_selected_group(1),
            "explorer_reveal": self.toggle_explorer_reveal,
            "search_items": self.focus_item_search,
            "replace_item_names": self.replace_item_names,
        }
        for name, callback in actions.items():
            shortcut = QShortcut(QKeySequence(self.shortcuts[name]), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            if name == "explorer_reveal":
                shortcut.setAutoRepeat(False)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def save_user_settings(self) -> None:
        self.settings["auto_paste"] = self.auto_paste.isChecked()
        self.settings["topmost"] = self.topmost.isChecked()
        self.settings["shortcuts"] = dict(self.shortcuts)
        self.settings["terminal_hotkey"] = self.shortcuts["terminal_toggle"]
        save_settings(self.settings)

    def apply_topmost(self) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.topmost.isChecked())
        self.show()
        self.save_user_settings()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        terminal_was_visible = (
            self.terminal is not None
            and self.side_tabs.isVisible()
            and self.side_tabs.currentWidget() is self.terminal
        )
        if self.terminal is not None:
            self.terminal.close_terminal()
            index = self.side_tabs.indexOf(self.terminal)
            if index >= 0:
                self.side_tabs.removeTab(index)
            self.terminal.deleteLater()
            self.terminal = None
            self.terminal_tab_index = -1
        self.settings.update(dialog.values())
        self.shortcuts = dict(self.settings["shortcuts"])
        self.splitter.setOrientation(
            Qt.Orientation.Horizontal if self.settings["terminal_position"] == "right" else Qt.Orientation.Vertical
        )
        self._install_shortcuts()
        self.apply_theme()
        self.save_user_settings()
        if terminal_was_visible:
            self.show_terminal()
        elif self.side_tabs.isVisible():
            self.show_info_panel()
        self.status_label.setText("设置已保存。")

    def refresh_databases(self) -> None:
        files = sorted(path.name for path in DB_DIR.glob("*.json"))
        if not files:
            write_json_file(DB_DIR / DEFAULT_DB, SAMPLE_DATA)
            files = [DEFAULT_DB]
        preferred = str(self.settings.get("current_db") or DEFAULT_DB)
        if preferred not in files:
            preferred = files[0]
        self.db_combo.blockSignals(True)
        self.db_combo.clear()
        self.db_combo.addItems(files)
        self.db_combo.setCurrentText(preferred)
        self.db_combo.blockSignals(False)
        self.load_database(preferred)

    def _database_changed(self, name: str) -> None:
        if name and name != self.current_db:
            self.load_database(name)

    def load_database(self, name: str) -> None:
        try:
            self.data, self.item_type_by_key, self.group_by_key, self.group_order = read_json_file(DB_DIR / name)
        except ValueError as exc:
            QMessageBox.critical(self, "资料库无法打开", f"{name}\n\n{exc}")
            self.data, self.item_type_by_key, self.group_by_key, self.group_order = {}, {}, {}, []
        self.item_order = list(self.data)
        self.current_db = name
        self.selected_key = None
        self.selected_keys.clear()
        self.settings["current_db"] = name
        self.save_user_settings()
        self.refresh_items()
        self.status_label.setText(f"已打开资料库：{name}")

    def save_database_to_disk(self) -> None:
        if self.current_db:
            write_json_file(DB_DIR / self.current_db, self.data, self.item_type_by_key, self.group_by_key, self.group_order, self.item_order)

    def new_database(self) -> None:
        name, ok = QInputDialog.getText(self, "新建资料库", "输入新资料库名称：")
        if not ok or not name.strip():
            return
        filename = clean_filename(name)
        path = DB_DIR / filename
        if path.exists():
            QMessageBox.warning(self, "名称已存在", f"{filename} 已经存在。")
            return
        write_json_file(path, {})
        self.refresh_databases()
        self.db_combo.setCurrentText(filename)

    def rename_database(self) -> None:
        if not self.current_db:
            return
        old = DB_DIR / self.current_db
        name, ok = QInputDialog.getText(self, "重命名资料库", "输入新的资料库名称：", text=old.stem)
        if not ok or not name.strip():
            return
        filename = clean_filename(name)
        new = DB_DIR / filename
        if new.exists() and new.resolve() != old.resolve():
            QMessageBox.warning(self, "名称已存在", f"{filename} 已经存在。")
            return
        old.rename(new)
        self.settings["current_db"] = filename
        self.refresh_databases()

    def delete_database(self) -> None:
        if not self.current_db:
            return
        if QMessageBox.question(self, "删除资料库", f"确定删除 {self.current_db}？\n此操作会删除对应 JSON 文件。") != QMessageBox.StandardButton.Yes:
            return
        (DB_DIR / self.current_db).unlink()
        self.current_db = ""
        self.refresh_databases()

    def _normalize_orders(self) -> None:
        self.item_order = [key for index, key in enumerate(self.item_order) if key in self.data and key not in self.item_order[:index]]
        self.item_order.extend(key for key in self.data if key not in self.item_order)
        for key in self.data:
            self.group_by_key[key] = normalize_group_name(self.group_by_key.get(key) or infer_group_name(key))
            self.item_type_by_key[key] = normalize_item_type(self.item_type_by_key.get(key))
        normalized: list[str] = []
        for group in self.group_order:
            group = normalize_group_name(group)
            if group not in normalized and any(self.group_by_key.get(key) == group for key in self.data):
                normalized.append(group)
        for key in self.item_order:
            group = self.group_by_key[key]
            if group not in normalized:
                normalized.append(group)
        self.group_order = normalized

    def refresh_items(self) -> None:
        self._normalize_orders()
        query = self.search_edit.text().strip().lower()
        visible = [key for key in self.item_order if not query or query in key.lower() or query in self.data[key].lower()]
        self.selected_keys.intersection_update(self.data)
        self.chips = {}
        self.group_widgets = {}
        clear_layout(self.item_layout)
        for group in self.group_order:
            keys = [key for key in visible if self.group_by_key.get(key) == group]
            if not keys:
                continue
            box = GroupWidget(group, self.item_host)
            box.item_dropped.connect(self.move_item_to_group_slot)
            for key in keys:
                item_type = normalize_item_type(self.item_type_by_key.get(key))
                chip = ChipButton(key, f"[{ITEM_TYPE_SHORT_LABELS[item_type]}] {key}", self.data[key], box)
                chip.activated.connect(self.use_item)
                chip.context_requested.connect(self.show_context_menu)
                chip.set_selected(key in self.selected_keys)
                box.flow.addWidget(chip)
                self.chips[key] = chip
            self.item_layout.addWidget(box)
            self.group_widgets[group] = box
        if not visible:
            empty = QLabel("暂无匹配条目")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.item_layout.addWidget(empty)
        self.item_layout.addStretch(1)
        self.update_selection()

    def focus_item_search(self) -> None:
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()
        self.status_label.setText("输入关键词搜索条目名称或内容；按 Esc 或清空搜索框显示全部。")

    def replace_item_names(self) -> None:
        self._normalize_orders()
        dialog = SearchReplaceDialog(self.item_order, self.search_edit.text().strip(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        find_text, replacement, match_case = dialog.result_value()
        try:
            matches = find_item_name_replacements(self.item_order, find_text, replacement, match_case)
        except ValueError as exc:
            QMessageBox.warning(self, "无法替换", str(exc))
            return
        replaced = 0
        skipped = 0
        stopped = False
        total = len(matches)
        for index, (old_key, new_key) in enumerate(matches, 1):
            decision = self.confirm_item_name_replacement(old_key, new_key, index, total)
            if decision == "stop":
                stopped = True
                break
            if decision == "skip":
                skipped += 1
                continue
            if not new_key:
                QMessageBox.warning(self, "无法替换", f"条目“{old_key}”替换后名称为空，已跳过。")
                skipped += 1
                continue
            if new_key in self.data and new_key != old_key:
                QMessageBox.warning(self, "无法替换", f"条目名称“{new_key}”已存在，已跳过“{old_key}”。")
                skipped += 1
                continue
            self.rename_item_key(old_key, new_key)
            replaced += 1

        if replaced:
            self.save_database_to_disk()
            self.search_edit.clear()
            self.refresh_items()
            self.sync_info_panel(force=True)
        suffix = "；已提前结束" if stopped else ""
        self.status_label.setText(f"逐项替换完成：已替换 {replaced} 项，跳过 {skipped} 项{suffix}。")

    def confirm_item_name_replacement(self, old_key: str, new_key: str, index: int, total: int) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("逐项替换条目名称")
        box.setText(f"第 {index}/{total} 个匹配项")
        box.setInformativeText(f"原名称：{old_key}\n新名称：{new_key or '（空名称）'}")
        replace_button = box.addButton("替换此项", QMessageBox.ButtonRole.AcceptRole)
        skip_button = box.addButton("跳过", QMessageBox.ButtonRole.ActionRole)
        stop_button = box.addButton("结束", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(replace_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is replace_button:
            return "replace"
        if clicked is skip_button:
            return "skip"
        if clicked is stop_button:
            return "stop"
        return "stop"

    def rename_item_key(self, old_key: str, new_key: str) -> None:
        if old_key == new_key or old_key not in self.data:
            return
        self.data = {new_key if key == old_key else key: value for key, value in self.data.items()}
        self.item_order = [new_key if key == old_key else key for key in self.item_order]
        self.item_type_by_key[new_key] = self.item_type_by_key.pop(old_key, ITEM_TYPE_TEXT)
        self.group_by_key[new_key] = self.group_by_key.pop(old_key, DEFAULT_GROUP)
        if old_key in self.selected_keys:
            self.selected_keys.remove(old_key)
            self.selected_keys.add(new_key)
        if self.selected_key == old_key:
            self.selected_key = new_key

    def add_item(self) -> None:
        dialog = ItemDialog("新增条目", self.group_order, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.save_item(None, *dialog.result_value())

    def edit_selected(self) -> None:
        selected = self.ordered_selected_keys()
        if len(selected) != 1:
            QMessageBox.information(self, "没有可编辑的条目", "请只选择一个条目后再编辑。")
            return
        key = selected[0]
        dialog = ItemDialog(
            "编辑条目", self.group_order, key, self.data[key], self.group_by_key.get(key, DEFAULT_GROUP),
            self.item_type_by_key.get(key, ITEM_TYPE_TEXT), self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.save_item(key, *dialog.result_value())

    def save_item(self, old_key: Optional[str], key: str, value: str, group: str, item_type: str) -> bool:
        if old_key != key and key in self.data:
            if QMessageBox.question(self, "覆盖已有条目", f"{key} 已存在，是否覆盖？") != QMessageBox.StandardButton.Yes:
                return False
        if old_key and old_key != key and old_key in self.data:
            new_data = {}
            for existing, existing_value in self.data.items():
                if existing == old_key:
                    new_data[key] = value
                elif existing != key:
                    new_data[existing] = existing_value
            self.data = new_data
            self.item_order = [key if existing == old_key else existing for existing in self.item_order if existing != key]
            self.group_by_key.pop(old_key, None)
            self.item_type_by_key.pop(old_key, None)
        else:
            self.data[key] = value
            if key not in self.item_order:
                self.item_order.append(key)
        self.item_type_by_key[key] = normalize_item_type(item_type)
        self.group_by_key[key] = normalize_group_name(group)
        if group not in self.group_order:
            self.group_order.append(group)
        self.save_database_to_disk()
        self.selected_key, self.selected_keys = key, {key}
        self.refresh_items()
        self.status_label.setText(f"已保存：{key}")
        self.sync_info_panel(force=True)
        return True

    def save_info_item(self, old_key: str, key: str, value: str, group: str, item_type: str) -> None:
        if self.save_item(old_key, key, value, group, item_type):
            self.show_info_panel()
            self.info_panel.state_label.setText("修改已保存。")
            self.status_label.setText(f"已保存：{key}")

    def change_group_selected(self) -> None:
        selected = self.ordered_selected_keys()
        if not selected:
            QMessageBox.information(self, "没有可调整的条目", "请先选择一个或多个条目。")
            return
        current_groups = {self.group_by_key[key] for key in selected}
        initial = next(iter(current_groups)) if len(current_groups) == 1 else DEFAULT_GROUP
        group, ok = QInputDialog.getItem(self, "调整分组", "选择或输入分组：", self.group_order, max(0, self.group_order.index(initial) if initial in self.group_order else 0), True)
        if not ok or not group.strip():
            return
        group = normalize_group_name(group)
        for key in selected:
            self.group_by_key[key] = group
        if group not in self.group_order:
            self.group_order.append(group)
        remaining = [key for key in self.item_order if key not in selected]
        target = [index for index, key in enumerate(remaining) if self.group_by_key.get(key) == group]
        insert = target[-1] + 1 if target else len(remaining)
        remaining[insert:insert] = selected
        self.item_order = remaining
        self.save_database_to_disk()
        self.refresh_items()
        self.status_label.setText(f"已将 {len(selected)} 个条目调整到分组：{group}")

    def delete_selected(self) -> None:
        selected = self.ordered_selected_keys()
        if not selected:
            QMessageBox.information(self, "没有可删除的条目", "请先选择条目。")
            return
        if QMessageBox.question(self, "删除条目", f"确定删除选中的 {len(selected)} 个条目？") != QMessageBox.StandardButton.Yes:
            return
        for key in selected:
            self.data.pop(key, None)
            self.item_type_by_key.pop(key, None)
            self.group_by_key.pop(key, None)
        self.item_order = [key for key in self.item_order if key not in selected]
        self.selected_key = None
        self.selected_keys.clear()
        self.save_database_to_disk()
        self.refresh_items()
        self.status_label.setText(f"已删除 {len(selected)} 个条目。")

    def ordered_selected_keys(self) -> list[str]:
        return [key for key in self.item_order if key in self.selected_keys]

    def use_item(self, key: str, modifiers) -> None:
        if key not in self.data:
            return
        item_type = normalize_item_type(self.item_type_by_key.get(key))
        resource = item_type in {ITEM_TYPE_LINK, ITEM_TYPE_FILE, ITEM_TYPE_FOLDER}
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if resource and self.explorer_reveal_armed:
            self.explorer_reveal_armed = False
            self.selected_key, self.selected_keys = key, {key}
            self.refresh_items()
            self.open_item_resource(key, reveal=True)
            return
        if control and shift and resource:
            self.open_item_resource(key)
            return
        if control and resource:
            self.copy_item(key)
            return
        if shift:
            if key in self.selected_keys:
                self.selected_keys.remove(key)
            else:
                self.selected_keys.add(key)
            self.selected_key = key if key in self.selected_keys else None
            self.refresh_items()
            self.status_label.setText(f"已选择 {len(self.selected_keys)} 个条目。")
            return
        self.selected_key, self.selected_keys = key, {key}
        result = self.paste_helper.copy_or_paste(self.data[key], self.auto_paste.isChecked() or control)
        self.refresh_items()
        self.status_label.setText(f"已{'粘贴' if result == 'pasted' else '复制'}{ITEM_TYPE_LABELS[item_type]}：{key}")

    def copy_item(self, key: str) -> None:
        self.paste_helper.copy_to_clipboard(self.data[key])
        self.selected_key, self.selected_keys = key, {key}
        self.refresh_items()
        self.status_label.setText(f"已复制：{key}")

    def move_item_to_group_slot(self, key: str, group: str, index: int) -> None:
        if key not in self.data:
            return
        old_group = self.group_by_key.get(key, DEFAULT_GROUP)
        self.group_by_key[key] = group
        if group not in self.group_order:
            self.group_order.append(group)
        remaining = [item for item in self.item_order if item != key]
        anchors = [item for item in remaining if self.group_by_key.get(item) == group]
        index = max(0, min(index, len(anchors)))
        if anchors and index < len(anchors):
            global_index = remaining.index(anchors[index])
        elif anchors:
            global_index = remaining.index(anchors[-1]) + 1
        else:
            global_index = len(remaining)
        remaining.insert(global_index, key)
        self.item_order = remaining
        self.selected_key, self.selected_keys = key, {key}
        self.save_database_to_disk()
        self.refresh_items()
        action = "调整位置" if old_group == group else f"移动到分组“{group}”"
        self.status_label.setText(f"已{action}：{key}")

    def move_selected_within_group(self, direction: int) -> None:
        selected = self.ordered_selected_keys()
        if len(selected) != 1:
            self.status_label.setText("请先只选择一个条目，再调整组内位置。")
            return
        key = selected[0]
        group = self.group_by_key[key]
        group_keys = [item for item in self.item_order if self.group_by_key.get(item) == group]
        current = group_keys.index(key)
        target = current + (1 if direction > 0 else -1)
        if not 0 <= target < len(group_keys):
            self.status_label.setText(f"{key} 已经在分组边界。")
            return
        group_keys[current], group_keys[target] = group_keys[target], group_keys[current]
        positions = [index for index, item in enumerate(self.item_order) if self.group_by_key.get(item) == group]
        for idx, position in enumerate(positions):
            self.item_order[position] = group_keys[idx]
        self.save_database_to_disk()
        self.refresh_items()

    def move_selected_group(self, direction: int) -> None:
        selected = self.ordered_selected_keys()
        groups = {self.group_by_key[key] for key in selected}
        if not selected or len(groups) != 1:
            self.status_label.setText("请先选择同一分组中的条目。")
            return
        group = next(iter(groups))
        current = self.group_order.index(group)
        target = current + (1 if direction > 0 else -1)
        if not 0 <= target < len(self.group_order):
            self.status_label.setText(f"分组“{group}”已经在边界位置。")
            return
        self.group_order[current], self.group_order[target] = self.group_order[target], self.group_order[current]
        self.save_database_to_disk()
        self.refresh_items()

    def show_context_menu(self, key: str, global_pos: QPoint) -> None:
        self.selected_key, self.selected_keys = key, {key}
        self.refresh_items()
        menu = QMenu(self)
        item_type = normalize_item_type(self.item_type_by_key.get(key))
        resource = item_type in {ITEM_TYPE_LINK, ITEM_TYPE_FILE, ITEM_TYPE_FOLDER}
        path = self.local_resource_path(key, warn=False) if resource else None
        if resource:
            menu.addAction("打开（系统默认方式）", lambda: self.open_item_resource(key))
            if path is not None:
                menu.addAction("打开文件夹", lambda: self.open_resource_folder(key))
                open_with = menu.addMenu("打开方式")
                handlers = safe_enumerate_open_with_handlers(path)
                for label, template in handlers:
                    open_with.addAction(label, lambda _checked=False, t=template: self.open_resource_with(key, t))
                if handlers:
                    open_with.addSeparator()
                open_with.addAction("选择其他应用…", lambda: self.choose_resource_app(key))
            menu.addSeparator()
        menu.addAction("编辑", self.edit_selected)
        menu.addAction("复制", lambda: self.copy_item(key))
        menu.addAction("分组", self.change_group_selected)
        menu.addSeparator()
        menu.addAction("删除", self.delete_selected)
        menu.exec(global_pos)

    def local_resource_path(self, key: str, warn: bool = True) -> Optional[Path]:
        value = self.data.get(key, "").strip()
        if re.match(r"^(https?|ftp|mailto):", value, re.IGNORECASE):
            return None
        path = Path(os.path.expandvars(os.path.expanduser(value)))
        if not path.exists():
            if warn:
                QMessageBox.warning(self, "本地资源不存在", str(path))
            return None
        return path

    def open_item_resource(self, key: str, reveal: bool = False) -> None:
        value = self.data.get(key, "").strip()
        try:
            is_web_resource = bool(re.match(r"^(https?|ftp|mailto):", value, re.IGNORECASE))
            if reveal:
                if is_web_resource:
                    self.status_label.setText(f"无法在资源管理器中定位网址：{key}")
                    return
                path = self.local_resource_path(key)
                if path is None:
                    self.status_label.setText(f"未能定位资源：{key}")
                    return
                self.reveal_local_path(path)
                self.status_label.setText(f"已在资源管理器中定位：{key}")
                return
            if is_web_resource:
                webbrowser.open(value)
            else:
                path = self.local_resource_path(key)
                if path is None:
                    return
                try:
                    os.startfile(str(path), "open")
                except OSError as exc:
                    if getattr(exc, "winerror", None) == 1155:
                        self.choose_resource_app(key)
                    else:
                        raise
            self.status_label.setText(f"已打开资源：{key}")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "打开资源失败", str(exc))

    @staticmethod
    def reveal_local_path(path: Path) -> None:
        if path.is_dir():
            subprocess.Popen(["explorer.exe", str(path)])
        else:
            subprocess.Popen(["explorer.exe", "/select,", str(path)])

    def open_resource_folder(self, key: str) -> None:
        path = self.local_resource_path(key)
        if path is None:
            return
        self.reveal_local_path(path)

    def open_resource_with(self, key: str, template: list[str]) -> None:
        path = self.local_resource_path(key)
        if path is not None:
            subprocess.Popen(build_open_with_argv(template, path), cwd=str(path.parent))

    def choose_resource_app(self, key: str) -> None:
        path = self.local_resource_path(key)
        if path is None:
            return
        try:
            os.startfile(str(path), "openas")
        except OSError:
            subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", str(path)])

    def toggle_explorer_reveal(self) -> None:
        self.explorer_reveal_armed = not self.explorer_reveal_armed
        self.status_label.setText(
            "资源管理器定位模式已启用：下一次点击资源会定位文件。" if self.explorer_reveal_armed else "资源管理器定位模式已取消。"
        )

    def update_selection(self) -> None:
        selected = self.ordered_selected_keys()
        count = len(selected)
        if count == 1:
            key = selected[0]
            item_type = normalize_item_type(self.item_type_by_key.get(key))
            self.selected_label.setText(f"当前条目：[{ITEM_TYPE_LABELS[item_type]}] {truncate_text(key, 28)}")
            self.preview_label.setText(truncate_text(self.data[key].replace("\n", " "), 54))
            self.edit_button.setEnabled(True)
            self.delete_button.setText("删除")
        elif count > 1:
            self.selected_label.setText(f"已选择 {count} 个条目")
            self.preview_label.setText("多选状态下可调整分组或批量删除。")
            self.edit_button.setEnabled(False)
            self.delete_button.setText(f"删除 {count} 项")
        else:
            self.selected_label.setText("未选择条目")
            self.preview_label.clear()
        for button in (self.edit_button, self.group_button, self.delete_button):
            button.setVisible(count > 0)

        self.sync_info_panel()

    def sync_info_panel(self, *, force: bool = False) -> None:
        selected = self.ordered_selected_keys()
        if len(selected) == 1:
            key = selected[0]
            self.info_panel.load_item(
                key,
                self.data[key],
                self.group_by_key.get(key, DEFAULT_GROUP),
                self.item_type_by_key.get(key, ITEM_TYPE_TEXT),
                self.group_order,
                force=force,
            )
        elif len(selected) > 1:
            self.info_panel.show_message("当前选择了多个条目。请只选择一个条目后查看或修改信息。")
        else:
            self.info_panel.show_message("点击左侧一个条目后，可在这里查看并修改信息。")

    def _show_side_panel(self) -> None:
        self.side_tabs.show()
        if self.splitter.orientation() == Qt.Orientation.Horizontal:
            total = max(0, self.splitter.width() - self.splitter.handleWidth())
            preferred = int(self.settings.get("terminal_width", 520))
        else:
            total = max(0, self.splitter.height() - self.splitter.handleWidth())
            preferred = int(self.settings.get("terminal_height", 300))
        if total <= 0:
            return
        minimum_visible = min(120, total // 2)
        side_size = max(minimum_visible, min(preferred, total - minimum_visible))
        self.splitter.setSizes([total - side_size, side_size])

    def show_info_panel(self) -> None:
        self.sync_info_panel()
        self._show_side_panel()
        self.side_tabs.setCurrentWidget(self.info_panel)
        if len(self.ordered_selected_keys()) == 1:
            self.status_label.setText("已在右侧显示条目信息，可直接修改并保存。")
        else:
            self.status_label.setText("请在左侧选择一个条目。")

    def show_terminal(self) -> None:
        created = False
        if self.terminal is None:
            self.terminal = TerminalWidget(self.settings, self.palette, set(self.shortcuts.values()), self.side_tabs)
            self.terminal.status_changed.connect(self.status_label.setText)
            self.terminal_tab_index = self.side_tabs.insertTab(0, self.terminal, "终端")
            created = True
        self._show_side_panel()
        self.side_tabs.setCurrentWidget(self.terminal)
        if created:
            self.status_label.setText("终端正在准备…")
        elif self.terminal._bootstrap and not self.terminal._bootstrap_complete:
            self.status_label.setText("Codex 仍在准备…")
        else:
            self.status_label.setText("终端已显示。")

    def toggle_terminal(self) -> None:
        if self.side_tabs.isVisible():
            self.side_tabs.hide()
            suffix = "；终端进程仍在后台运行。" if self.terminal is not None else "。"
            self.status_label.setText("右侧面板已隐藏" + suffix)
            return
        self.show_terminal()

    def poll_foreground(self) -> None:
        self.paste_helper.poll_foreground()
        title = self.paste_helper.last_external_title
        if title:
            self.target_label.setText("上一个目标窗口：" + truncate_text(title, 44))

    def closeEvent(self, event) -> None:
        self.settings["window_width"] = self.width()
        self.settings["window_height"] = self.height()
        if self.side_tabs.isVisible():
            sizes = self.splitter.sizes()
            if len(sizes) > 1:
                if self.splitter.orientation() == Qt.Orientation.Horizontal:
                    if sizes[1] > 0:
                        self.settings["terminal_width"] = sizes[1]
                else:
                    if sizes[1] > 0:
                        self.settings["terminal_height"] = sizes[1]
        if self.terminal is not None:
            self.terminal.close_terminal()
        self.save_user_settings()
        super().closeEvent(event)


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    try:
        window = MainWindow()
        window.show()
        return app.exec()
    except Exception as exc:
        QMessageBox.critical(None, "程序无法启动", f"无法初始化程序数据目录：\n{DATA_ROOT}\n\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

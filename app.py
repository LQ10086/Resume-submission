# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable, Optional
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter.font as tkfont

try:
    from winpty import PtyProcess, WinptyError
except ImportError:
    PtyProcess = None
    WinptyError = OSError

try:
    import pyte
except ImportError:
    pyte = None


APP_NAME = "投递文本助手"
DATABASE_DIR = "databases"
SETTINGS_FILE = "app_settings.json"
DEFAULT_DB = "默认投递资料.json"
MOD_SHIFT = 0x0001
MOD_CONTROL = 0x0004
DEFAULT_GROUP = "未分组"
BASIC_GROUP = "基本信息"
ITEM_TYPE_TEXT = "text"
ITEM_TYPE_IMAGE = "image"
ITEM_TYPE_LINK = "link"
ITEM_TYPE_FILE = "file"
ITEM_TYPE_FOLDER = "folder"
ITEM_TYPE_LABELS = {
    ITEM_TYPE_TEXT: "文本",
    ITEM_TYPE_LINK: "超链接",
    ITEM_TYPE_FILE: "文件",
    ITEM_TYPE_FOLDER: "文件夹",
}
ITEM_TYPE_SHORT_LABELS = {
    ITEM_TYPE_TEXT: "文",
    ITEM_TYPE_LINK: "链",
    ITEM_TYPE_FILE: "件",
    ITEM_TYPE_FOLDER: "夹",
}


SAMPLE_DATA = {
    "姓名": "XXX",
    "手机号": "XXX",
    "邮箱": "XXX",
    "实习经历-实习A-经历名称": "XXX",
    "实习经历-实习A-经历角色": "XXX",
    "实习经历-实习A-经历详情": "工作内容：XXX。1) XXX。2) XXX。3) XXX。",
    "科研经历-科研项目A-经历名称": "XXX",
    "科研经历-科研项目A-经历角色": "XXX",
    "科研经历-科研项目A-经历详情": "论文内容：XXX。1) XXX。2) XXX。3) XXX。",
}


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = app_root()
DB_DIR = ROOT / DATABASE_DIR
SETTINGS_PATH = ROOT / SETTINGS_FILE
PROJECT_ROOT = ROOT.parent if getattr(sys, "frozen", False) and ROOT.name.lower() == "release" else ROOT
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
DEFAULT_SHORTCUTS = {
    "terminal_toggle": "ctrl+j",
    "edit_item": "ctrl+e",
    "move_left": "ctrl+left",
    "move_right": "ctrl+right",
    "explorer_reveal": "ctrl+shift+e",
}
SHORTCUT_LABELS = {
    "terminal_toggle": "打开/隐藏终端",
    "edit_item": "编辑选中条目",
    "move_left": "组内向左移动",
    "move_right": "组内向右移动",
    "explorer_reveal": "资源管理器定位模式",
}


def load_shortcuts(settings: dict) -> dict[str, str]:
    shortcuts = dict(DEFAULT_SHORTCUTS)
    stored = settings.get("shortcuts")
    if isinstance(stored, dict):
        for name in shortcuts:
            value = normalize_shortcut(stored.get(name))
            if value:
                shortcuts[name] = value
    legacy_terminal = normalize_shortcut(settings.get("terminal_hotkey"))
    if legacy_terminal and not isinstance(stored, dict):
        shortcuts["terminal_toggle"] = legacy_terminal
    return shortcuts


def default_settings() -> dict:
    return {
        "auto_paste": False,
        "topmost": True,
        "terminal_hotkey": "ctrl+j",
        "shortcuts": dict(DEFAULT_SHORTCUTS),
        "terminal_shell": "powershell",
        "terminal_cwd": "tmp",
        "terminal_command": "codex",
    }


def normalize_shortcut(value: object) -> str:
    parts = [part.strip().lower() for part in str(value or "").split("+") if part.strip()]
    if not parts:
        return ""
    modifiers = []
    aliases = {"control": "ctrl", "ctl": "ctrl", "option": "alt", "windows": "win", "command": "win"}
    for part in parts[:-1]:
        part = aliases.get(part, part)
        if part in {"ctrl", "shift", "alt", "win"} and part not in modifiers:
            modifiers.append(part)
    key = parts[-1]
    if key in {"ctrl", "shift", "alt", "win", "control", "alt_l", "alt_r"}:
        return ""
    key_aliases = {"space": "space", "return": "enter", "esc": "escape", "pageup": "page_up", "pagedown": "page_down"}
    key = key_aliases.get(key, key)
    return "+".join(modifiers + [key])


def shortcut_display(value: object) -> str:
    normalized = normalize_shortcut(value)
    if not normalized:
        return "未设置"
    labels = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win"}
    parts = normalized.split("+")
    return "+".join(labels.get(part, part.upper() if len(part) == 1 else part.title().replace("_", " ")) for part in parts)


def shortcut_from_event(event: tk.Event) -> str:
    modifiers = []
    if event.state & MOD_CONTROL:
        modifiers.append("ctrl")
    if event.state & MOD_SHIFT:
        modifiers.append("shift")
    if event.state & 0x0008:
        modifiers.append("alt")
    keysym = str(event.keysym or "").lower()
    if keysym in {"control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r", "win_l", "win_r"}:
        return ""
    if keysym == "space":
        key = "space"
    elif len(keysym) == 1:
        key = keysym
    else:
        key = keysym
    return normalize_shortcut("+".join(modifiers + [key]))


def clean_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(" .")
    if not name:
        name = "新资料库"
    if not name.lower().endswith(".json"):
        name += ".json"
    return name


def truncate_text(text: str, max_chars: int = 24) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def normalize_group_name(group_name: object) -> str:
    text = str(group_name or "").strip()
    return text or DEFAULT_GROUP


def normalize_item_type(item_type: object) -> str:
    item_type = str(item_type or "").strip().lower()
    if item_type == ITEM_TYPE_IMAGE:
        return ITEM_TYPE_FILE
    if item_type in {ITEM_TYPE_LINK, ITEM_TYPE_FILE, ITEM_TYPE_FOLDER}:
        return item_type
    return ITEM_TYPE_TEXT


def infer_group_name(key: str) -> str:
    key = key.strip()
    basic_keys = {"姓名", "手机号", "邮箱", "微信", "所在地", "求职方向", "性别", "籍贯"}
    if key in basic_keys:
        return BASIC_GROUP
    if key.startswith(("技能", "荣誉", "证书", "语言")):
        return "技能证书"
    parts = key.split("-")
    if len(parts) >= 3 and parts[1].strip():
        return parts[1].strip()
    if len(parts) >= 2 and parts[0].strip():
        return parts[0].strip()
    return DEFAULT_GROUP


def _coerce_items(raw_items: object) -> tuple[dict[str, str], dict[str, str]]:
    if not isinstance(raw_items, dict):
        return {}, {}
    data: dict[str, str] = {}
    item_type_by_key: dict[str, str] = {}
    for key, value in raw_items.items():
        if key is None:
            continue
        text_key = str(key).strip()
        if not text_key:
            continue
        item_type = ITEM_TYPE_TEXT
        item_value = value
        if isinstance(value, dict) and "type" in value:
            item_type = normalize_item_type(value.get("type"))
            item_value = value.get("value")
            if item_value is None:
                item_value = value.get("path") or value.get("url")
        if isinstance(item_value, str):
            data[text_key] = item_value
        else:
            data[text_key] = json.dumps(item_value, ensure_ascii=False, indent=2)
        item_type_by_key[text_key] = item_type
    return data, item_type_by_key


def read_json_file(path: Path) -> tuple[dict[str, str], dict[str, str], dict[str, str], list[str]]:
    if not path.exists():
        return {}, {}, {}, []
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 格式错误：第 {exc.lineno} 行，第 {exc.colno} 列") from exc

    if not isinstance(raw, dict):
        raise ValueError("资料库必须是 JSON 对象，例如 {\"groups\": {\"基本信息\": {\"姓名\": \"XXX\"}}}")

    data: dict[str, str] = {}
    item_type_by_key: dict[str, str] = {}
    group_by_key: dict[str, str] = {}
    group_order: list[str] = []

    groups = raw.get("groups")
    if isinstance(groups, dict):
        for group_name, raw_items in groups.items():
            group = normalize_group_name(group_name)
            items, item_types = _coerce_items(raw_items)
            if group not in group_order:
                group_order.append(group)
            for key, value in items.items():
                data[key] = value
                item_type_by_key[key] = item_types.get(key, ITEM_TYPE_TEXT)
                group_by_key[key] = group
        return data, item_type_by_key, group_by_key, group_order

    if isinstance(groups, list):
        for raw_group in groups:
            if not isinstance(raw_group, dict):
                continue
            group = normalize_group_name(raw_group.get("name"))
            items, item_types = _coerce_items(raw_group.get("items"))
            if group not in group_order:
                group_order.append(group)
            for key, value in items.items():
                data[key] = value
                item_type_by_key[key] = item_types.get(key, ITEM_TYPE_TEXT)
                group_by_key[key] = group
        return data, item_type_by_key, group_by_key, group_order

    if isinstance(raw.get("items"), dict):
        flat_items, flat_item_types = _coerce_items(raw["items"])
    else:
        flat_items, flat_item_types = _coerce_items(raw)
    for key, value in flat_items.items():
        group = infer_group_name(key)
        data[key] = value
        item_type_by_key[key] = flat_item_types.get(key, ITEM_TYPE_TEXT)
        group_by_key[key] = group
        if group not in group_order:
            group_order.append(group)
    return data, item_type_by_key, group_by_key, group_order


def write_json_file(
    path: Path,
    data: dict[str, str],
    item_type_by_key: Optional[dict[str, str]] = None,
    group_by_key: Optional[dict[str, str]] = None,
    group_order: Optional[list[str]] = None,
    item_order: Optional[list[str]] = None,
) -> None:
    item_type_by_key = item_type_by_key or {}
    group_by_key = group_by_key or {}
    group_order = group_order or []
    ordered_keys: list[str] = []
    for key in item_order or []:
        if key in data and key not in ordered_keys:
            ordered_keys.append(key)
    for key in data:
        if key not in ordered_keys:
            ordered_keys.append(key)
    ordered_groups: list[str] = []
    for group in group_order:
        group = normalize_group_name(group)
        if group not in ordered_groups:
            ordered_groups.append(group)
    for key in ordered_keys:
        group = normalize_group_name(group_by_key.get(key) or infer_group_name(key))
        if group not in ordered_groups:
            ordered_groups.append(group)

    grouped: dict[str, dict[str, object]] = {}
    for group in ordered_groups:
        items: dict[str, object] = {}
        for key in ordered_keys:
            value = data[key]
            if normalize_group_name(group_by_key.get(key) or infer_group_name(key)) != group:
                continue
            item_type = normalize_item_type(item_type_by_key.get(key))
            if item_type == ITEM_TYPE_TEXT:
                items[key] = value
            else:
                items[key] = {"type": item_type, "value": value}
        if items:
            grouped[group] = items

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"groups": grouped}, f, ensure_ascii=False, indent=2)
        f.write("\n")

class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [
        ("ki", KeyBdInput),
        ("mi", MouseInput),
        ("hi", HardwareInput),
    ]


class Input(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", InputUnion),
    ]


class WindowsPasteHelper:
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    GA_ROOT = 2
    SW_RESTORE = 9
    SW_SHOWMINIMIZED = 2
    VK_CONTROL = 0x11
    VK_V = 0x56

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.available = sys.platform.startswith("win")
        self.last_external_hwnd: Optional[int] = None
        self.last_external_title = ""
        self._own_pid = os.getpid()

        if self.available:
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            self.user32.GetForegroundWindow.restype = wintypes.HWND
            self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
            self.user32.GetWindowTextLengthW.restype = ctypes.c_int
            self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            self.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            self.user32.IsWindow.argtypes = [wintypes.HWND]
            self.user32.IsWindow.restype = wintypes.BOOL
            self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            self.user32.SetForegroundWindow.restype = wintypes.BOOL
            self.user32.BringWindowToTop.argtypes = [wintypes.HWND]
            self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            self.user32.IsIconic.argtypes = [wintypes.HWND]
            self.user32.IsIconic.restype = wintypes.BOOL
            self.user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            self.user32.GetAncestor.restype = wintypes.HWND
            self.user32.WindowFromPoint.argtypes = [wintypes.POINT]
            self.user32.WindowFromPoint.restype = wintypes.HWND
            self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
            self.user32.mouse_event.argtypes = [
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.c_size_t,
            ]
            self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
            self.user32.SendInput.restype = wintypes.UINT
            self.user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
            self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        else:
            self.user32 = None
            self.kernel32 = None

    def poll_foreground(self) -> None:
        if not self.available:
            return
        hwnd = int(self.user32.GetForegroundWindow())
        if hwnd and not self._is_own_process(hwnd):
            root_hwnd = self._root_window(hwnd)
            self.last_external_hwnd = root_hwnd
            self.last_external_title = self._window_title(root_hwnd)

    def copy_to_clipboard(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

    def copy_or_paste(self, text: str, auto_paste: bool) -> str:
        self.copy_to_clipboard(text)
        if not auto_paste or not self.available:
            return "copied"
        hwnd = self.last_external_hwnd
        if not hwnd or not self.user32.IsWindow(hwnd):
            return "copied"
        if not self._focus_window(hwnd):
            return "copied"
        time.sleep(0.08)
        self._send_ctrl_v()
        return "pasted"

    def type_at_point(self, text: str, x: int, y: int) -> str:
        self.copy_to_clipboard(text)
        if not self.available:
            return "copied"
        if not self._focus_point(x, y):
            return "copied"
        time.sleep(0.08)
        self._send_unicode_text(text)
        return "typed"

    def _is_own_process(self, hwnd: int) -> bool:
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == self._own_pid

    def _root_window(self, hwnd: int) -> int:
        root_hwnd = int(self.user32.GetAncestor(hwnd, self.GA_ROOT))
        return root_hwnd or int(hwnd)

    def _window_title(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return "未命名窗口"
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value or "未命名窗口"

    def _focus_window(self, hwnd: int) -> bool:
        root_hwnd = self._root_window(hwnd)
        if self._is_own_process(root_hwnd):
            return False

        target_pid = wintypes.DWORD()
        target_thread = self.user32.GetWindowThreadProcessId(root_hwnd, ctypes.byref(target_pid))
        current_thread = self.kernel32.GetCurrentThreadId()

        attached = False
        if target_thread and target_thread != current_thread:
            attached = bool(self.user32.AttachThreadInput(current_thread, target_thread, True))
        try:
            if self.user32.IsIconic(root_hwnd):
                self.user32.ShowWindow(root_hwnd, self.SW_RESTORE)
            self.user32.BringWindowToTop(root_hwnd)
            self.user32.SetForegroundWindow(root_hwnd)
        finally:
            if attached:
                self.user32.AttachThreadInput(current_thread, target_thread, False)

        time.sleep(0.08)
        return int(self.user32.GetForegroundWindow()) == int(root_hwnd)

    def _focus_point(self, x: int, y: int) -> bool:
        point = wintypes.POINT(int(x), int(y))
        hwnd = int(self.user32.WindowFromPoint(point))
        if not hwnd:
            return False
        root_hwnd = self._root_window(hwnd)
        if self._is_own_process(root_hwnd):
            return False
        if not self._focus_window(root_hwnd):
            return False

        self.user32.SetCursorPos(int(x), int(y))
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return True

    def _send_ctrl_v(self) -> None:
        self._send_key(self.VK_CONTROL, keyup=False)
        self._send_key(self.VK_V, keyup=False)
        self._send_key(self.VK_V, keyup=True)
        self._send_key(self.VK_CONTROL, keyup=True)

    def _send_key(self, vk: int, keyup: bool) -> None:
        flags = self.KEYEVENTF_KEYUP if keyup else 0
        inp = Input()
        inp.type = self.INPUT_KEYBOARD
        inp.u.ki = KeyBdInput(vk, 0, flags, 0, 0)
        self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(Input))

    def _send_unicode_text(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        for char in normalized:
            if char == "\n":
                units = [0x000D]
            else:
                raw = char.encode("utf-16-le", errors="surrogatepass")
                units = [int.from_bytes(raw[i : i + 2], "little") for i in range(0, len(raw), 2)]
            for unit in units:
                self._send_unicode_unit(unit, keyup=False)
                self._send_unicode_unit(unit, keyup=True)

    def _send_unicode_unit(self, unit: int, keyup: bool) -> None:
        flags = self.KEYEVENTF_UNICODE | (self.KEYEVENTF_KEYUP if keyup else 0)
        inp = Input()
        inp.type = self.INPUT_KEYBOARD
        inp.u.ki = KeyBdInput(0, unit, flags, 0, 0)
        self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(Input))


class ChipButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Widget,
        item_key: str,
        display_text: str,
        width: int,
        height: int,
        click_command,
        context_command,
        drag_command,
        drag_preview_command,
        wheel_command,
        font: tkfont.Font,
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            bg="#ffffff",
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.item_key = item_key
        self.display_text = display_text
        self.chip_width = width
        self.chip_height = height
        self.click_command = click_command
        self.context_command = context_command
        self.drag_command = drag_command
        self.drag_preview_command = drag_preview_command
        self.wheel_command = wheel_command
        self.font = font
        self.selected = False
        self.hover = False
        self.dragging = False
        self.pointer_grabbed = False
        self.drop_target = False
        self.press_xy = (0, 0)
        self.press_state = 0

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Button-3>", self._on_context)
        self.bind("<MouseWheel>", self.wheel_command)
        self.bind("<Button-4>", self.wheel_command)
        self.bind("<Button-5>", self.wheel_command)
        self._draw()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self._draw()

    def set_drop_target(self, target: bool) -> None:
        self.drop_target = target
        self._draw()

    def _on_enter(self, _event: tk.Event) -> None:
        self.hover = True
        self._draw()

    def _on_leave(self, _event: tk.Event) -> None:
        self.hover = False
        self._draw()

    def _on_press(self, event: tk.Event) -> str:
        self.press_xy = (event.x_root, event.y_root)
        self.press_state = getattr(event, "state", 0)
        self.dragging = False
        try:
            self.grab_set_global()
            self.pointer_grabbed = True
        except tk.TclError:
            try:
                self.grab_set()
                self.pointer_grabbed = True
            except tk.TclError:
                self.pointer_grabbed = False
        return "break"

    def _on_motion(self, event: tk.Event) -> str:
        dx = abs(event.x_root - self.press_xy[0])
        dy = abs(event.y_root - self.press_xy[1])
        if dx + dy > 7:
            self.dragging = True
            self.drag_preview_command(self.item_key, event.x_root, event.y_root, True)
        return "break"

    def _on_release(self, event: tk.Event) -> str:
        state = self.press_state | getattr(event, "state", 0)
        try:
            if self.dragging:
                self.drag_preview_command(self.item_key, event.x_root, event.y_root, False)
                self.drag_command(self.item_key, event.x_root, event.y_root)
            else:
                self.click_command(self.item_key, state)
        finally:
            if self.pointer_grabbed:
                try:
                    self.grab_release()
                except tk.TclError:
                    pass
                self.pointer_grabbed = False
        return "break"

    def _on_context(self, event: tk.Event) -> str:
        self.context_command(self.item_key, event.x_root, event.y_root)
        return "break"

    def _draw(self) -> None:
        self.delete("all")
        if self.drop_target:
            fill = "#fef3c7"
            outline = "#f59e0b"
            text_fill = "#92400e"
        elif self.selected:
            fill = "#2563eb"
            outline = "#1d4ed8"
            text_fill = "#ffffff"
        elif self.hover:
            fill = "#dbeafe"
            outline = "#93c5fd"
            text_fill = "#1f2937"
        else:
            fill = "#eef2ff"
            outline = "#c7d2fe"
            text_fill = "#1f2937"
        self._rounded_rect(1, 1, self.chip_width - 1, self.chip_height - 1, 12, fill=fill, outline=outline)
        self.create_text(
            12,
            self.chip_height / 2,
            anchor="w",
            text=self.display_text,
            fill=text_fill,
            font=self.font,
        )

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.create_polygon(points, smooth=True, splinesteps=16, **kwargs)


class ItemDialog:
    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        initial_key: str = "",
        initial_value: str = "",
        initial_group: str = DEFAULT_GROUP,
        initial_type: str = ITEM_TYPE_TEXT,
        groups: Optional[list[str]] = None,
        topmost: bool = False,
    ) -> None:
        self.result: Optional[tuple[str, str, str, str]] = None
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("720x400")
        self.window.minsize(580, 340)
        self.window.transient(parent)
        self.window.configure(bg="#f6f7f9")
        if topmost:
            self.window.attributes("-topmost", True)

        initial_group = normalize_group_name(initial_group)
        self.groups: list[str] = []
        for group in groups or []:
            normalized = normalize_group_name(group)
            if normalized not in self.groups:
                self.groups.append(normalized)
        if initial_group not in self.groups:
            self.groups.append(initial_group)
        if not self.groups:
            self.groups.append(DEFAULT_GROUP)
        self.key_var = tk.StringVar(value=initial_key)
        self.group_var = tk.StringVar(value=initial_group)
        self.type_var = tk.StringVar(value=ITEM_TYPE_LABELS[normalize_item_type(initial_type)])
        self._build_ui()
        self.text.insert("1.0", initial_value)
        self.window.bind("<Control-s>", lambda _event: self._save())
        self.window.bind("<Escape>", lambda _event: self._cancel())
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.grab_set()
        if initial_key:
            self.text.focus_set()
        else:
            self.key_entry.focus_set()
        parent.wait_window(self.window)

    def _build_ui(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        outer = ttk.Frame(self.window, padding=14)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        outer.columnconfigure(2, weight=0)
        outer.rowconfigure(3, weight=1)

        ttk.Label(outer, text="键名").grid(row=0, column=0, sticky="w")
        ttk.Label(outer, text="分组").grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(outer, text="条目类型").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.key_entry = ttk.Entry(outer, textvariable=self.key_var)
        self.key_entry.grid(row=1, column=0, sticky="ew", pady=(4, 12))
        group_shell = ttk.Frame(outer)
        group_shell.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(4, 12))
        group_shell.columnconfigure(0, weight=1)
        self.group_combo = ttk.Combobox(
            group_shell,
            textvariable=self.group_var,
            values=self.groups,
            state="readonly",
        )
        self.group_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(group_shell, text="新建分组", command=self._create_group).grid(row=0, column=1, padx=(6, 0))
        self.type_combo = ttk.Combobox(
            outer,
            textvariable=self.type_var,
            values=list(ITEM_TYPE_LABELS.values()),
            state="readonly",
            width=10,
        )
        self.type_combo.grid(row=1, column=2, sticky="ew", padx=(10, 0), pady=(4, 12))
        self.type_combo.bind("<<ComboboxSelected>>", self._on_type_selected)

        self.content_label = ttk.Label(outer, text="文本内容")
        self.content_label.grid(row=2, column=0, columnspan=2, sticky="w")
        browse_shell = ttk.Frame(outer)
        browse_shell.grid(row=2, column=2, sticky="e", padx=(10, 0))
        self.browse_button = ttk.Button(browse_shell, text="选文件", command=self._browse_file, width=7)
        self.browse_button.grid(row=0, column=0, padx=(0, 4))
        self.folder_button = ttk.Button(browse_shell, text="选文件夹", command=self._browse_folder, width=8)
        self.folder_button.grid(row=0, column=1)
        text_shell = ttk.Frame(outer)
        text_shell.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(4, 12))
        text_shell.columnconfigure(0, weight=1)
        text_shell.rowconfigure(0, weight=1)
        self.text = tk.Text(
            text_shell,
            wrap="word",
            undo=True,
            font=("Microsoft YaHei UI", 10),
            height=8,
            padx=8,
            pady=8,
            borderwidth=1,
            relief="solid",
        )
        scroll = ttk.Scrollbar(text_shell, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        actions = ttk.Frame(outer)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Button(actions, text="取消", command=self._cancel).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="保存", command=self._save, style="Accent.TButton").grid(row=0, column=2)
        self._on_type_selected()

    def _selected_type(self) -> str:
        selected_label = self.type_var.get()
        for item_type, label in ITEM_TYPE_LABELS.items():
            if label == selected_label:
                return item_type
        return ITEM_TYPE_TEXT

    def _create_group(self) -> None:
        name = simpledialog.askstring("新建分组", "输入新分组名称：", parent=self.window)
        if not name:
            return
        group = normalize_group_name(name)
        if group not in self.groups:
            self.groups.append(group)
            self.group_combo.configure(values=self.groups)
        self.group_var.set(group)

    def _on_type_selected(self, _event: Optional[tk.Event] = None) -> None:
        item_type = self._selected_type()
        if item_type == ITEM_TYPE_FILE:
            self.content_label.configure(text="文件路径")
            self.browse_button.state(["!disabled"])
            self.folder_button.state(["disabled"])
        elif item_type == ITEM_TYPE_FOLDER:
            self.content_label.configure(text="文件夹路径")
            self.browse_button.state(["disabled"])
            self.folder_button.state(["!disabled"])
        elif item_type == ITEM_TYPE_LINK:
            self.content_label.configure(text="网址或本地资源路径")
            self.browse_button.state(["!disabled"])
            self.folder_button.state(["!disabled"])
        else:
            self.content_label.configure(text="文本内容")
            self.browse_button.state(["disabled"])
            self.folder_button.state(["disabled"])

    def _browse_file(self) -> None:
        item_type = self._selected_type()
        if item_type == ITEM_TYPE_FILE:
            filetypes = [
                ("所有文件", "*.*"),
            ]
            selected = filedialog.askopenfilename(title="选择文件", filetypes=filetypes, parent=self.window)
        elif item_type == ITEM_TYPE_LINK:
            selected = filedialog.askopenfilename(title="选择本地资源", parent=self.window)
        else:
            return
        if selected:
            self.text.delete("1.0", "end")
            self.text.insert("1.0", selected)

    def _browse_folder(self) -> None:
        selected = filedialog.askdirectory(title="选择文件夹", parent=self.window)
        if selected:
            self.text.delete("1.0", "end")
            self.text.insert("1.0", selected)

    def _save(self) -> None:
        key = self.key_var.get().strip()
        group = normalize_group_name(self.group_var.get())
        value = self.text.get("1.0", "end-1c")
        item_type = self._selected_type()
        if not key:
            messagebox.showwarning("缺少键名", "请先填写键名。", parent=self.window)
            return
        if not value.strip():
            messagebox.showwarning("缺少内容", "请填写文本、文件路径、文件夹路径或网址。", parent=self.window)
            return
        self.result = (key, value, group, item_type)
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.destroy()


class GroupDialog:
    def __init__(
        self,
        parent: tk.Tk,
        groups: list[str],
        initial_group: str = "",
        topmost: bool = False,
    ) -> None:
        self.result: Optional[str] = None
        self.groups = [normalize_group_name(group) for group in groups]
        self.window = tk.Toplevel(parent)
        self.window.title("调整分组")
        self.window.geometry("420x180")
        self.window.minsize(360, 160)
        self.window.transient(parent)
        self.window.configure(bg="#f6f7f9")
        if topmost:
            self.window.attributes("-topmost", True)

        self.existing_var = tk.StringVar(value=initial_group if initial_group in self.groups else "")
        self.new_var = tk.StringVar()
        self._build_ui()
        self.window.bind("<Control-s>", lambda _event: self._save())
        self.window.bind("<Return>", lambda _event: self._save())
        self.window.bind("<Escape>", lambda _event: self._cancel())
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.grab_set()
        if initial_group:
            self.combo.focus_set()
        else:
            self.new_entry.focus_set()
        parent.wait_window(self.window)

    def _build_ui(self) -> None:
        self.window.columnconfigure(0, weight=1)

        outer = ttk.Frame(self.window, padding=14)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)

        ttk.Label(outer, text="选择现有分组").grid(row=0, column=0, sticky="w")
        self.combo = ttk.Combobox(outer, textvariable=self.existing_var, values=self.groups, state="readonly")
        self.combo.grid(row=1, column=0, sticky="ew", pady=(4, 12))

        ttk.Label(outer, text="或输入新分组名").grid(row=2, column=0, sticky="w")
        self.new_entry = ttk.Entry(outer, textvariable=self.new_var)
        self.new_entry.grid(row=3, column=0, sticky="ew", pady=(4, 14))

        actions = ttk.Frame(outer)
        actions.grid(row=4, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Button(actions, text="取消", command=self._cancel).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="保存", command=self._save, style="Accent.TButton").grid(row=0, column=2)

    def _save(self) -> None:
        raw_group = self.new_var.get().strip() or self.existing_var.get().strip()
        if not raw_group:
            messagebox.showwarning("缺少分组名", "请选择现有分组或输入新分组名。", parent=self.window)
            return
        group = normalize_group_name(raw_group)
        self.result = group
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.destroy()


class ShortcutCaptureDialog:
    def __init__(self, parent: tk.Toplevel, initial_shortcut: str, topmost: bool = False) -> None:
        self.result: Optional[str] = None
        self.window = tk.Toplevel(parent)
        self.window.title("更改快捷键")
        self.window.geometry("420x220")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.configure(bg="#f6f7f9")
        if topmost:
            self.window.attributes("-topmost", True)
        self.value_var = tk.StringVar(value=shortcut_display(initial_shortcut))

        outer = ttk.Frame(self.window, padding=18)
        outer.grid(row=0, column=0, sticky="nsew")
        ttk.Label(outer, text="请在下方输入框中按下快捷键组合").grid(row=0, column=0, sticky="w")
        ttk.Label(outer, text="例如 Ctrl+J、Alt+Shift+T；不能只设置单个修饰键。", style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(5, 12)
        )
        self.entry = ttk.Entry(outer, textvariable=self.value_var, justify="center", font=("Segoe UI", 14))
        self.entry.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        self.entry.bind("<KeyPress>", self._on_key)
        actions = ttk.Frame(outer)
        actions.grid(row=3, column=0, sticky="e")
        ttk.Button(actions, text="取消", command=self._cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="确定", command=self._save, style="Accent.TButton").grid(row=0, column=1)

        self.window.bind("<Escape>", lambda _event: self._cancel())
        self.window.bind("<Return>", lambda _event: self._save())
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.grab_set()
        self.entry.focus_set()
        self.entry.selection_range(0, "end")
        parent.wait_window(self.window)

    def _on_key(self, event: tk.Event) -> str:
        shortcut = shortcut_from_event(event)
        if shortcut:
            self.value_var.set(shortcut_display(shortcut))
            self.result = shortcut
        return "break"

    def _save(self) -> None:
        if not self.result:
            messagebox.showwarning("快捷键无效", "请先按下一个包含具体按键的快捷键组合。", parent=self.window)
            return
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.destroy()


class SettingsDialog:
    def __init__(self, parent: tk.Tk, settings: dict, topmost: bool = False) -> None:
        self.result: Optional[dict] = None
        self.parent = parent
        self.settings = settings
        self.topmost = topmost
        self.window = tk.Toplevel(parent)
        self.window.title("设置")
        self.window.geometry("650x430")
        self.window.minsize(580, 380)
        self.window.transient(parent)
        self.window.configure(bg="#f6f7f9")
        if topmost:
            self.window.attributes("-topmost", True)

        self.shortcuts = load_shortcuts(settings)
        self.shortcut_vars: dict[str, tk.StringVar] = {
            name: tk.StringVar(value=shortcut_display(value)) for name, value in self.shortcuts.items()
        }
        shell = str(settings.get("terminal_shell", "powershell")).lower()
        self.shell_var = tk.StringVar(value="CMD" if shell == "cmd" else "PowerShell")
        self.cwd_var = tk.StringVar(value=str(settings.get("terminal_cwd", "tmp") or "tmp"))
        self.command_var = tk.StringVar(value=str(settings.get("terminal_command", "") or ""))
        self.cwd_hint_var = tk.StringVar()
        self._update_cwd_hint()
        self._build_ui()
        self.window.bind("<Control-s>", lambda _event: self._save())
        self.window.bind("<Escape>", lambda _event: self._cancel())
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.grab_set()
        parent.wait_window(self.window)

    def _build_ui(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        outer = ttk.Frame(self.window, padding=14)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(outer)
        notebook.grid(row=0, column=0, sticky="nsew")
        shortcut_tab = ttk.Frame(notebook, padding=16)
        terminal_tab = ttk.Frame(notebook, padding=16)
        notebook.add(shortcut_tab, text="快捷键")
        notebook.add(terminal_tab, text="终端")

        shortcut_tab.columnconfigure(1, weight=1)
        ttk.Label(shortcut_tab, text="快捷键配置", font=("Microsoft YaHei UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(shortcut_tab, text="点击对应的“更改”按钮后，直接按下新的快捷键组合。", style="Muted.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 16)
        )
        for row, (name, label) in enumerate(SHORTCUT_LABELS.items(), start=2):
            ttk.Label(shortcut_tab, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 14))
            shortcut_shell = ttk.Frame(shortcut_tab)
            shortcut_shell.grid(row=row, column=1, sticky="ew", pady=3)
            shortcut_shell.columnconfigure(0, weight=1)
            ttk.Entry(shortcut_shell, textvariable=self.shortcut_vars[name], state="readonly", justify="center").grid(
                row=0, column=0, sticky="ew"
            )
            ttk.Button(shortcut_shell, text="更改", command=lambda shortcut_name=name: self._capture_shortcut(shortcut_name)).grid(
                row=0, column=1, padx=(10, 0)
            )
        ttk.Label(
            shortcut_tab,
            text="支持 Ctrl、Shift、Alt、Win 与字母、数字、方向键、功能键等组合；保存后立即生效。",
            style="Muted.TLabel",
        ).grid(row=2 + len(SHORTCUT_LABELS), column=0, columnspan=2, sticky="w", pady=(12, 0))

        terminal_tab.columnconfigure(1, weight=1)
        ttk.Label(terminal_tab, text="终端类型").grid(row=0, column=0, sticky="w", pady=(0, 12))
        ttk.Combobox(terminal_tab, textvariable=self.shell_var, values=["PowerShell", "CMD"], state="readonly", width=18).grid(
            row=0, column=1, sticky="w", pady=(0, 12)
        )
        ttk.Label(terminal_tab, text="默认路径").grid(row=1, column=0, sticky="w", pady=(0, 12))
        cwd_shell = ttk.Frame(terminal_tab)
        cwd_shell.grid(row=1, column=1, sticky="ew", pady=(0, 12))
        cwd_shell.columnconfigure(0, weight=1)
        ttk.Entry(cwd_shell, textvariable=self.cwd_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(cwd_shell, text="浏览", command=self._browse_cwd).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(terminal_tab, textvariable=self.cwd_hint_var, style="Muted.TLabel").grid(
            row=2, column=1, sticky="w", pady=(0, 14)
        )
        ttk.Label(terminal_tab, text="自动输入命令").grid(row=3, column=0, sticky="w", pady=(0, 12))
        ttk.Entry(terminal_tab, textvariable=self.command_var).grid(row=3, column=1, sticky="ew", pady=(0, 12))
        ttk.Label(
            terminal_tab,
            text="路径支持相对项目目录的写法，例如 tmp；留空命令则只进入终端。",
            style="Muted.TLabel",
        ).grid(row=4, column=1, sticky="w")

        actions = ttk.Frame(outer)
        actions.grid(row=1, column=0, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="取消", command=self._cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="保存", command=self._save, style="Accent.TButton").grid(row=0, column=1)

    def _capture_shortcut(self, name: str) -> None:
        dialog = ShortcutCaptureDialog(self.window, self.shortcuts[name], topmost=self.topmost)
        if dialog.result:
            self.shortcuts[name] = dialog.result
            self.shortcut_vars[name].set(shortcut_display(dialog.result))

    def _browse_cwd(self) -> None:
        raw_path = self.cwd_var.get().strip() or "tmp"
        selected = filedialog.askdirectory(title="选择终端默认路径", initialdir=str(resolve_terminal_cwd(raw_path)), parent=self.window)
        if selected:
            try:
                selected_path = Path(selected).resolve()
                self.cwd_var.set(str(selected_path.relative_to(PROJECT_ROOT)))
            except ValueError:
                self.cwd_var.set(selected)
            self._update_cwd_hint()

    def _update_cwd_hint(self) -> None:
        try:
            self.cwd_hint_var.set(f"实际路径：{resolve_terminal_cwd(self.cwd_var.get())}")
        except (OSError, ValueError):
            self.cwd_hint_var.set("路径将在保存时检查并创建。")

    def _save(self) -> None:
        cwd = self.cwd_var.get().strip() or "tmp"
        if any(not value for value in self.shortcuts.values()):
            messagebox.showwarning("快捷键无效", "请为每个功能设置快捷键组合。", parent=self.window)
            return
        if len(set(self.shortcuts.values())) != len(self.shortcuts):
            messagebox.showwarning("快捷键重复", "不同功能不能使用相同的快捷键，请重新设置。", parent=self.window)
            return
        try:
            resolve_terminal_cwd(cwd).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("路径不可用", f"无法创建终端目录：\n{exc}", parent=self.window)
            return
        self.result = {
            "terminal_hotkey": self.shortcuts["terminal_toggle"],
            "shortcuts": dict(self.shortcuts),
            "terminal_shell": "cmd" if self.shell_var.get() == "CMD" else "powershell",
            "terminal_cwd": cwd,
            "terminal_command": self.command_var.get().strip(),
        }
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.destroy()


def resolve_terminal_cwd(raw_path: object) -> Path:
    value = str(raw_path or "tmp").strip() or "tmp"
    path = Path(os.path.expandvars(os.path.expanduser(value)))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def is_codex_command(command: str) -> bool:
    command = command.strip()
    if not command:
        return False
    executable = command.split(maxsplit=1)[0].strip('"')
    return Path(executable).stem.lower() == "codex"


def build_codex_startup_prompt(cwd: Path) -> str:
    return (
        "你正在协助维护本机 Windows 项目“投递文本助手”。"
        f"项目根目录：{PROJECT_ROOT}；当前终端工作目录：{cwd}。"
        "这是一个管理简历投递 JSON 条目的 Tkinter 桌面工具。"
        "请先阅读项目根目录中的 UPGRADE_FOR_CODEX.md 和 README.md（若存在），"
        "再处理用户请求，例如“批量导入条目”。"
        "所有修改仅限此项目；不得覆盖或删除 databases、release/databases、resumes_by_role、"
        "release/resumes_by_role 或 app_settings.json 中的用户数据；新增设置必须兼容旧设置。"
        "完成后运行针对性验证；如需要发布版请运行 build_exe.ps1，并用中文简洁说明结果。"
        "现在请确认已理解项目约定，并等待用户的下一项任务。"
    )


class TerminalPanel:
    def __init__(
        self,
        parent: tk.Misc,
        shell: str,
        cwd: Path,
        startup_command: str,
        codex_prompt: str = "",
        is_global_shortcut: Optional[Callable[[tk.Event], bool]] = None,
    ) -> None:
        self.background = "#f6f7f9"
        self.panel_background = "#ffffff"
        self.border = "#bfdbfe"
        self.text_color = "#1f2937"
        self.muted_color = "#64748b"
        self.accent = "#2563eb"
        self.accent_light = "#dbeafe"
        self.window = tk.Frame(
            parent,
            bg=self.panel_background,
            height=300,
            highlightbackground=self.border,
            highlightthickness=1,
        )
        self.window.grid_propagate(False)
        self.visible = False
        self.shell = shell
        self.cwd = cwd
        self.startup_command = startup_command
        self.codex_prompt = codex_prompt
        self.is_global_shortcut = is_global_shortcut
        self.pty_process = None
        self.process: Optional[subprocess.Popen] = None
        self._closing = False
        self._render_pending = False
        self._resize_pending = False
        self.preferred_height = 300
        self.terminal_rows = 24
        self.terminal_columns = 120
        self._codex_prompt_sent = False
        self._codex_prompt_attempts = 0
        self.terminal_font = tkfont.Font(family="Cascadia Mono", size=10)
        self.screen = pyte.Screen(self.terminal_columns, self.terminal_rows) if pyte is not None else None
        self.stream = pyte.Stream(self.screen) if self.screen is not None else None
        self._build_ui()
        self._start_process()

    def _build_ui(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        header = tk.Frame(self.window, bg=self.background, height=36)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(2, weight=1)
        tk.Label(header, text="输出", fg=self.muted_color, bg=self.background, font=("Segoe UI", 10)).grid(
            row=0, column=0, padx=(14, 14), pady=8
        )
        terminal_tab = tk.Frame(header, bg=self.panel_background)
        terminal_tab.grid(row=0, column=1, sticky="ns")
        tk.Label(terminal_tab, text="终端", fg=self.accent, bg=self.panel_background, font=("Segoe UI", 10, "bold")).pack(
            padx=12, pady=(8, 5)
        )
        tk.Frame(terminal_tab, bg=self.accent, height=2).pack(fill="x")
        tk.Label(header, text=f"{self.shell.upper()}  ·  {self.cwd}", fg=self.muted_color, bg=self.background, anchor="w").grid(
            row=0, column=2, sticky="ew", pady=8, padx=(12, 6)
        )
        tk.Button(
            header, text="清空", command=self._clear_output, relief="flat", borderwidth=0,
            bg=self.background, fg=self.muted_color, activebackground=self.accent_light, activeforeground=self.accent,
        ).grid(row=0, column=3, padx=(4, 6))
        tk.Button(
            header, text="停止", command=self._stop_process, relief="flat", borderwidth=0,
            bg=self.background, fg=self.muted_color, activebackground=self.accent_light, activeforeground=self.accent,
        ).grid(row=0, column=4, padx=(0, 10))

        output_shell = tk.Frame(self.window, bg=self.panel_background)
        output_shell.grid(row=1, column=0, sticky="nsew")
        output_shell.columnconfigure(0, weight=1)
        output_shell.rowconfigure(0, weight=1)
        self.output = tk.Text(
            output_shell, bg=self.panel_background, fg=self.text_color, insertbackground=self.text_color,
            selectbackground=self.accent_light, relief="flat", borderwidth=0, wrap="none",
            font=self.terminal_font, padx=12, pady=8,
        )
        scroll = tk.Scrollbar(output_shell, command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        self.output.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.output.configure(state="disabled")

        self.output.bind("<KeyPress>", self._on_terminal_key)
        self.output.bind("<Button-1>", self._focus_terminal, add="+")
        self.window.bind("<Button-1>", self._focus_terminal, add="+")
        self.output.bind("<Configure>", self._on_output_configure, add="+")

    def _focus_terminal(self, _event: Optional[tk.Event] = None) -> str:
        if self.visible:
            self.window.after_idle(self.output.focus_force)
        return ""

    def _on_output_configure(self, _event: tk.Event) -> None:
        if not self._resize_pending:
            self._resize_pending = True
            self.window.after_idle(self._sync_terminal_size)

    def mount(self) -> None:
        parent = self.window.master
        if str(self.window) not in parent.panes():
            parent.add(self.window)
        self.visible = True
        self.window.after(80, self._place_initial_sash)
        self.window.after(100, self._focus_terminal)

    def _place_initial_sash(self) -> None:
        parent = self.window.master
        if len(parent.panes()) < 2:
            return
        sash_y = max(160, parent.winfo_height() - self.preferred_height)
        parent.sash_place(0, 0, sash_y)
        self._sync_terminal_size()

    def _sync_terminal_size(self) -> None:
        self._resize_pending = False
        width = self.output.winfo_width()
        height = self.output.winfo_height()
        if width < 80 or height < 40:
            return
        char_width = max(self.terminal_font.measure("0"), 7)
        line_height = max(self.terminal_font.metrics("linespace"), 14)
        columns = max(40, (width - 24) // char_width)
        rows = max(8, (height - 16) // line_height)
        if (rows, columns) == (self.terminal_rows, self.terminal_columns):
            return
        self.terminal_rows, self.terminal_columns = rows, columns
        if self.screen is not None:
            self.screen.resize(lines=rows, columns=columns)
            self._render_terminal()
        if self.pty_process is not None:
            try:
                self.pty_process.setwinsize(rows, columns)
            except (OSError, WinptyError):
                pass

    def _start_process(self) -> None:
        try:
            self._codex_prompt_sent = False
            self._codex_prompt_attempts = 0
            self.cwd.mkdir(parents=True, exist_ok=True)
            if self.shell == "cmd":
                command_text = "cmd.exe /Q /K"
            else:
                command_text = "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass"
            if PtyProcess is not None:
                self.pty_process = PtyProcess.spawn(
                    command_text,
                    cwd=str(self.cwd),
                    dimensions=(self.terminal_rows, self.terminal_columns),
                )
                threading.Thread(target=self._read_pty_output, args=(self.pty_process,), daemon=True).start()
            else:
                command = command_text.split()
                self.process = subprocess.Popen(
                    command,
                    cwd=str(self.cwd),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                threading.Thread(target=self._read_output, args=(self.process,), daemon=True).start()
        except (OSError, ValueError) as exc:
            self._append_output(f"无法启动终端：{exc}\n")
            return
        if self.startup_command:
            self.window.after(350, lambda: self._send_line(self.startup_command))
        self.window.after(80, self._focus_terminal)

    def _read_pty_output(self, process) -> None:
        while process.isalive():
            try:
                chunk = process.read(4096)
            except (EOFError, OSError, WinptyError):
                break
            if not chunk:
                break
            try:
                self.window.after(0, self._append_output, chunk)
            except tk.TclError:
                return
        code = process.exitstatus if process.exitstatus is not None else 0
        try:
            self.window.after(0, self._process_finished, process, code)
        except tk.TclError:
            pass

    def _read_output(self, process: subprocess.Popen) -> None:
        if process.stdout is not None:
            for line in process.stdout:
                try:
                    self.window.after(0, self._append_output, line)
                except tk.TclError:
                    return
        try:
            code = process.wait()
        except OSError:
            code = -1
        try:
            self.window.after(0, self._process_finished, process, code)
        except tk.TclError:
            pass

    def _process_finished(self, process, code: int) -> None:
        if self.process is process or self.pty_process is process:
            self.process = None
            self.pty_process = None
            self._append_output(f"\n[终端已退出，代码 {code}]\n")

    def _append_output(self, text: str) -> None:
        if self._closing or not self.window.winfo_exists():
            return
        if self.stream is not None:
            self.stream.feed(text)
            if not self._render_pending:
                self._render_pending = True
                self.window.after(16, self._render_terminal)
            return
        text = ANSI_ESCAPE_RE.sub("", text)
        self.output.configure(state="normal")
        self.output.insert("end", text)
        self.output.see("end")
        self.output.configure(state="disabled")

    def _queue_codex_prompt(self) -> None:
        if not self.codex_prompt:
            return
        self._codex_prompt_sent = False
        self._codex_prompt_attempts = 0
        self.window.after(700, self._send_codex_prompt_when_ready)

    def _send_codex_prompt_when_ready(self) -> None:
        if self._closing or self._codex_prompt_sent:
            return
        if self.pty_process is None and self.process is None:
            return
        self._codex_prompt_attempts += 1
        if self._codex_ready() or self._codex_prompt_attempts >= 40:
            self._codex_prompt_sent = True
            self._send_line(self.codex_prompt, detect_codex=False)
            return
        self.window.after(500, self._send_codex_prompt_when_ready)

    def _codex_ready(self) -> bool:
        if self.screen is not None:
            content = "\n".join(self.screen.display).lower()
        else:
            content = self.output.get("1.0", "end").lower()
        markers = ("ask codex", "有什么想一起完成", "what would you like", "how can i help")
        return any(marker in content for marker in markers)

    def _render_terminal(self) -> None:
        self._render_pending = False
        if self._closing or self.screen is None or not self.window.winfo_exists():
            return
        lines = list(self.screen.display)
        cursor = self.screen.cursor
        if 0 <= cursor.y < len(lines) and 0 <= cursor.x < len(lines[cursor.y]):
            line = lines[cursor.y]
            lines[cursor.y] = f"{line[:cursor.x]}▌{line[cursor.x + 1:]}"
        rendered = "\n".join(line.rstrip() for line in lines).rstrip()
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        if rendered:
            self.output.insert("1.0", rendered)
        self.output.see("end")
        self.output.configure(state="disabled")

    def _send_line(self, line: str, detect_codex: bool = True) -> None:
        if self.pty_process is None and self.process is None:
            self._start_process()
        try:
            if self.pty_process is not None:
                self.pty_process.write(line + "\r\n")
            elif self.process is not None and self.process.stdin is not None:
                self.process.stdin.write(line + "\n")
                self.process.stdin.flush()
        except (OSError, ValueError):
            self._append_output("\n[无法向终端发送命令]\n")
            return
        if detect_codex and is_codex_command(line):
            self._queue_codex_prompt()

    def _send_raw(self, text: str) -> None:
        if not text:
            return
        if self.pty_process is None and self.process is None:
            self._start_process()
        try:
            if self.pty_process is not None:
                self.pty_process.write(text)
            elif self.process is not None and self.process.stdin is not None:
                self.process.stdin.write(text)
                self.process.stdin.flush()
        except (OSError, ValueError):
            self._append_output("\n[无法向终端发送输入]\n")

    def _on_terminal_key(self, event: tk.Event) -> str:
        if self.is_global_shortcut is not None and self.is_global_shortcut(event):
            return ""

        key_sequences = {
            "Return": "\r",
            "KP_Enter": "\r",
            "BackSpace": "\x08",
            "Tab": "\t",
            "Escape": "\x1b",
            "Up": "\x1b[A",
            "Down": "\x1b[B",
            "Right": "\x1b[C",
            "Left": "\x1b[D",
            "Home": "\x1b[H",
            "End": "\x1b[F",
            "Delete": "\x1b[3~",
            "Prior": "\x1b[5~",
            "Next": "\x1b[6~",
        }
        sequence = key_sequences.get(event.keysym)
        if sequence is not None:
            self._send_raw(sequence)
            return "break"

        if event.state & MOD_CONTROL and event.keysym.lower() == "v":
            try:
                self._send_raw(self.window.clipboard_get())
            except tk.TclError:
                pass
            return "break"

        if event.char:
            self._send_raw(event.char)
        return "break"

    def _clear_output(self) -> None:
        if self.screen is not None:
            self.screen.reset()
            self._render_terminal()
            return
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    def _stop_process(self) -> None:
        pty_process = self.pty_process
        if pty_process is not None:
            try:
                pty_process.terminate()
            except OSError:
                pass
            self.pty_process = None
            return
        process = self.process
        if process is None:
            return
        try:
            process.terminate()
        except OSError:
            pass
        self.process = None

    def hide(self) -> None:
        self.preferred_height = max(160, self.window.winfo_height())
        self.visible = False
        self.window.master.forget(self.window)

    def show(self) -> None:
        if self.pty_process is None and self.process is None:
            self._start_process()
        self.visible = True
        if str(self.window) not in self.window.master.panes():
            self.window.master.add(self.window)
        self.window.after(80, self._place_initial_sash)
        self.window.after(80, self._focus_terminal)

    def toggle(self) -> None:
        if not self.visible:
            self.show()
        else:
            self.hide()

    def close(self) -> None:
        self._closing = True
        self._stop_process()
        if str(self.window) in self.window.master.panes():
            self.window.master.forget(self.window)
        if self.window.winfo_exists():
            self.window.destroy()


class QuickTextApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("760x480")
        self.root.minsize(560, 360)

        self.settings = self._load_settings()
        self.shortcuts = load_shortcuts(self.settings)
        self.current_db = ""
        self.data: dict[str, str] = {}
        self.item_order: list[str] = []
        self.item_type_by_key: dict[str, str] = {}
        self.group_by_key: dict[str, str] = {}
        self.group_order: list[str] = []
        self.filtered_keys: list[str] = []
        self.selected_key: Optional[str] = None
        self.selected_keys: set[str] = set()
        self.chips: dict[str, ChipButton] = {}
        self.group_canvases: dict[str, tk.Canvas] = {}
        self.drop_target_group: Optional[str] = None
        self.drop_target_item: Optional[str] = None
        self.explorer_key_held = False
        self.drag_ghost: Optional[tk.Toplevel] = None
        self.drag_ghost_label: Optional[tk.Label] = None
        self.terminal_panel: Optional[TerminalPanel] = None
        self.paste_helper = WindowsPasteHelper(root)

        self.db_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="先点击目标输入框，再点击快捷按钮。资源条目 Ctrl+点击复制路径，Ctrl+Shift+点击直接打开，资源管理器定位快捷键+左键定位资源。")
        self.target_var = tk.StringVar(value="上一个目标窗口：未捕获")
        self.selected_var = tk.StringVar(value="未选择条目")
        self.preview_var = tk.StringVar(value="")
        self.auto_paste_var = tk.BooleanVar(value=bool(self.settings.get("auto_paste", False)))
        self.topmost_var = tk.BooleanVar(value=bool(self.settings.get("topmost", True)))
        self.chip_font = tkfont.Font(family="Microsoft YaHei UI", size=9)

        self._ensure_default_files()
        self._configure_style()
        self._build_ui()
        self._wire_events()
        self._refresh_databases()
        self._apply_topmost()
        self._tick_foreground()

    def _ensure_default_files(self) -> None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        if not any(DB_DIR.glob("*.json")):
            write_json_file(DB_DIR / DEFAULT_DB, SAMPLE_DATA)

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        bg = "#f6f7f9"
        panel = "#ffffff"
        text = "#1f2937"
        accent = "#2563eb"
        self.root.configure(bg=bg)
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("TLabel", background=bg, foreground=text)
        style.configure("Panel.TLabel", background=panel, foreground=text)
        style.configure("Muted.TLabel", background=bg, foreground="#6b7280")
        style.configure("PanelMuted.TLabel", background=panel, foreground="#6b7280")
        style.configure("Accent.TButton", padding=(10, 6), foreground="#ffffff", background=accent)
        style.map("Accent.TButton", background=[("active", "#1d4ed8")])
        style.configure("Danger.TButton", padding=(10, 6), foreground="#991b1b")

    def _build_ui(self) -> None:
        self._build_menu()
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=(12, 8, 12, 6))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)

        ttk.Label(toolbar, text="资料库").grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.db_combo = ttk.Combobox(toolbar, textvariable=self.db_var, state="readonly", width=26)
        self.db_combo.grid(row=0, column=1, sticky="ew")
        ttk.Button(toolbar, text="新建库", command=self.new_database).grid(row=0, column=2, padx=(10, 4))
        ttk.Button(toolbar, text="重命名", command=self.rename_database).grid(row=0, column=3, padx=4)
        ttk.Button(toolbar, text="删除库", command=self.delete_database, style="Danger.TButton").grid(row=0, column=4, padx=4)

        ttk.Label(toolbar, text="搜索").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(toolbar, textvariable=self.search_var).grid(row=1, column=1, sticky="ew", pady=(8, 0))
        ttk.Button(toolbar, text="新增条目", command=self.add_item, style="Accent.TButton").grid(row=1, column=2, padx=(10, 4), pady=(8, 0))
        ttk.Checkbutton(toolbar, text="点击后自动粘贴", variable=self.auto_paste_var, command=self._save_settings).grid(
            row=1, column=3, padx=4, pady=(8, 0)
        )
        ttk.Checkbutton(toolbar, text="窗口置顶", variable=self.topmost_var, command=self._apply_topmost).grid(
            row=1, column=4, padx=4, pady=(8, 0)
        )

        self.content_pane = tk.PanedWindow(
            self.root,
            orient="vertical",
            bg="#bfdbfe",
            sashwidth=6,
            sashrelief="flat",
            bd=0,
            relief="flat",
        )
        self.content_pane.grid(row=1, column=0, sticky="nsew")
        self.main_content = ttk.Frame(self.content_pane)
        self.main_content.columnconfigure(0, weight=1)
        self.main_content.rowconfigure(0, weight=1)
        self.content_pane.add(self.main_content)

        quick_shell = ttk.Frame(self.main_content, padding=(12, 0, 12, 8))
        quick_shell.grid(row=0, column=0, sticky="nsew")
        quick_shell.columnconfigure(0, weight=1)
        quick_shell.rowconfigure(0, weight=1)

        self.quick_canvas = tk.Canvas(quick_shell, borderwidth=0, highlightthickness=0, bg="#ffffff")
        self.quick_scroll = ttk.Scrollbar(quick_shell, orient="vertical", command=self.quick_canvas.yview)
        self.quick_frame = tk.Frame(self.quick_canvas, bg="#ffffff")
        self.quick_window = self.quick_canvas.create_window((0, 0), window=self.quick_frame, anchor="nw")
        self.quick_canvas.configure(yscrollcommand=self.quick_scroll.set)
        self.quick_canvas.grid(row=0, column=0, sticky="nsew")
        self.quick_scroll.grid(row=0, column=1, sticky="ns")

        selection = ttk.Frame(self.main_content, padding=(12, 0, 12, 8))
        selection.grid(row=1, column=0, sticky="ew")
        selection.columnconfigure(1, weight=1)
        ttk.Label(selection, textvariable=self.selected_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(selection, textvariable=self.preview_var, style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 8))
        self.edit_button = ttk.Button(selection, text="编辑", command=self.edit_selected)
        self.group_button = ttk.Button(selection, text="分组", command=self.change_group_selected)
        self.delete_button = ttk.Button(selection, text="删除", command=self.delete_selected, style="Danger.TButton")
        self.edit_button.grid(row=0, column=2, padx=(8, 4))
        self.group_button.grid(row=0, column=3, padx=4)
        self.delete_button.grid(row=0, column=4, padx=4)
        self.edit_button.grid_remove()
        self.group_button.grid_remove()
        self.delete_button.grid_remove()

        footer = ttk.Frame(self.main_content, padding=(12, 0, 12, 10))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.target_var, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root, tearoff=False)
        settings_menu = tk.Menu(menubar, tearoff=False)
        settings_menu.add_command(label="设置", command=self.open_settings)
        settings_menu.add_command(label="打开终端", command=self.toggle_terminal)
        menubar.add_cascade(label="设置", menu=settings_menu)
        self.root.configure(menu=menubar)

    def _wire_events(self) -> None:
        self.db_combo.bind("<<ComboboxSelected>>", self.on_database_selected)
        self.search_var.trace_add("write", lambda *_: self.refresh_items())
        self.root.bind_all("<KeyPress>", self._on_global_key_press, add="+")
        self.root.bind_all("<KeyRelease>", self._on_global_key_release, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.quick_canvas.bind("<Configure>", self._on_quick_canvas_configure)
        self.quick_canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.quick_canvas.bind("<Button-4>", self._on_mouse_wheel)
        self.quick_canvas.bind("<Button-5>", self._on_mouse_wheel)
        self.quick_frame.bind("<MouseWheel>", self._on_mouse_wheel)
        self.quick_frame.bind("<Button-4>", self._on_mouse_wheel)
        self.quick_frame.bind("<Button-5>", self._on_mouse_wheel)

    def _on_global_key_press(self, event: tk.Event) -> str:
        shortcut = shortcut_from_event(event)
        focused = self.root.focus_get()
        if focused is not None:
            try:
                focused_top = focused.winfo_toplevel()
            except tk.TclError:
                return ""
            allowed_tops = {self.root}
            if self.terminal_panel is not None:
                allowed_tops.add(self.terminal_panel.window)
            if focused_top not in allowed_tops:
                return ""
        if shortcut == self.shortcuts["explorer_reveal"]:
            self.explorer_key_held = True
            return "break"
        if shortcut == self.shortcuts["terminal_toggle"]:
            self.toggle_terminal()
            return "break"
        if shortcut == self.shortcuts["edit_item"]:
            self.edit_selected()
            return "break"
        if shortcut == self.shortcuts["move_left"]:
            return self._on_ctrl_arrow(-1)
        if shortcut == self.shortcuts["move_right"]:
            return self._on_ctrl_arrow(1)
        return ""

    def _is_configured_shortcut(self, event: tk.Event) -> bool:
        return shortcut_from_event(event) in set(self.shortcuts.values())

    def _on_global_key_release(self, event: tk.Event) -> None:
        explorer_key = self.shortcuts["explorer_reveal"].split("+")[-1]
        if str(event.keysym or "").lower() == explorer_key:
            self.explorer_key_held = False

    def _on_ctrl_arrow(self, direction: int) -> str:
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text, ttk.Entry)):
            return ""
        self.move_selected_within_group(direction)
        return "break"

    def _load_settings(self) -> dict:
        defaults = default_settings()
        if not SETTINGS_PATH.exists():
            return defaults
        try:
            with SETTINGS_PATH.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                defaults.update(loaded)
                return defaults
        except (OSError, json.JSONDecodeError):
            pass
        return defaults

    def _save_settings(self) -> None:
        self.settings["auto_paste"] = bool(self.auto_paste_var.get())
        self.settings["topmost"] = bool(self.topmost_var.get())
        self.settings["shortcuts"] = dict(self.shortcuts)
        self.settings["terminal_hotkey"] = self.shortcuts["terminal_toggle"]
        self.settings["terminal_shell"] = "cmd" if str(self.settings.get("terminal_shell", "powershell")).lower() == "cmd" else "powershell"
        self.settings["terminal_cwd"] = str(self.settings.get("terminal_cwd", "tmp") or "tmp")
        self.settings["terminal_command"] = str(self.settings.get("terminal_command", "") or "")
        self.settings["current_db"] = self.current_db
        try:
            with SETTINGS_PATH.open("w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as exc:
            self.status_var.set(f"设置保存失败：{exc}")

    def open_settings(self) -> None:
        previous_terminal = (
            self.settings.get("terminal_shell"),
            self.settings.get("terminal_cwd"),
            self.settings.get("terminal_command"),
        )
        dialog = SettingsDialog(self.root, self.settings, topmost=bool(self.topmost_var.get()))
        if dialog.result is None:
            return
        self.settings.update(dialog.result)
        self.shortcuts = load_shortcuts(self.settings)
        current_terminal = (
            self.settings.get("terminal_shell"),
            self.settings.get("terminal_cwd"),
            self.settings.get("terminal_command"),
        )
        if self.terminal_panel is not None and previous_terminal != current_terminal:
            self.terminal_panel.close()
            self.terminal_panel = None
        self._save_settings()
        self.status_var.set(f"设置已保存。终端快捷键：{shortcut_display(self.shortcuts['terminal_toggle'])}")

    def toggle_terminal(self) -> None:
        if self.terminal_panel is not None:
            self.terminal_panel.toggle()
            return
        try:
            cwd = resolve_terminal_cwd(self.settings.get("terminal_cwd", "tmp"))
            cwd.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as exc:
            messagebox.showerror("终端目录不可用", f"无法创建终端目录：\n{exc}", parent=self.root)
            return
        shell = "cmd" if str(self.settings.get("terminal_shell", "powershell")).lower() == "cmd" else "powershell"
        self.terminal_panel = TerminalPanel(
            self.content_pane,
            shell=shell,
            cwd=cwd,
            startup_command=str(self.settings.get("terminal_command", "") or "").strip(),
            codex_prompt=build_codex_startup_prompt(cwd),
            is_global_shortcut=self._is_configured_shortcut,
        )
        self.terminal_panel.mount()
        self.status_var.set(f"终端已打开：{cwd}")

    def _refresh_databases(self) -> None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        dbs = sorted(path.name for path in DB_DIR.glob("*.json"))
        if not dbs:
            write_json_file(DB_DIR / DEFAULT_DB, SAMPLE_DATA)
            dbs = [DEFAULT_DB]
        self.db_combo["values"] = dbs

        preferred = self.settings.get("current_db") or DEFAULT_DB
        if preferred not in dbs:
            preferred = dbs[0]
        self.db_var.set(preferred)
        self.load_database(preferred)

    def load_database(self, name: str) -> None:
        try:
            self.data, self.item_type_by_key, self.group_by_key, self.group_order = read_json_file(DB_DIR / name)
            self.item_order = list(self.data)
        except ValueError as exc:
            messagebox.showerror("资料库无法打开", f"{name}\n\n{exc}")
            self.data = {}
            self.item_order = []
            self.item_type_by_key = {}
            self.group_by_key = {}
            self.group_order = []
        self.current_db = name
        self.selected_key = None
        self.selected_keys.clear()
        self._save_settings()
        self.refresh_items()
        self._update_selection()
        self.status_var.set(f"已打开资料库：{name}")

    def save_database_to_disk(self) -> None:
        if self.current_db:
            write_json_file(
                DB_DIR / self.current_db,
                self.data,
                self.item_type_by_key,
                self.group_by_key,
                self.group_order,
                self.item_order,
            )

    def on_database_selected(self, _event: tk.Event) -> None:
        selected = self.db_var.get()
        if selected:
            self.load_database(selected)

    def new_database(self) -> None:
        name = simpledialog.askstring("新建资料库", "输入新资料库名称：", parent=self.root)
        if not name:
            return
        filename = clean_filename(name)
        path = DB_DIR / filename
        if path.exists():
            messagebox.showwarning("名称已存在", f"{filename} 已经存在。")
            return
        write_json_file(path, {}, {}, [])
        self._refresh_databases()
        self.db_var.set(filename)
        self.load_database(filename)

    def rename_database(self) -> None:
        if not self.current_db:
            return
        old = DB_DIR / self.current_db
        name = simpledialog.askstring(
            "重命名资料库",
            "输入新的资料库名称：",
            initialvalue=old.stem,
            parent=self.root,
        )
        if not name:
            return
        filename = clean_filename(name)
        new = DB_DIR / filename
        if new.exists() and new.resolve() != old.resolve():
            messagebox.showwarning("名称已存在", f"{filename} 已经存在。")
            return
        old.rename(new)
        self.current_db = filename
        self.settings["current_db"] = filename
        self._refresh_databases()
        self.db_var.set(filename)
        self.status_var.set(f"资料库已重命名为：{filename}")

    def delete_database(self) -> None:
        if not self.current_db:
            return
        if not messagebox.askyesno("删除资料库", f"确定删除 {self.current_db}？\n此操作会删除对应 JSON 文件。"):
            return
        path = DB_DIR / self.current_db
        try:
            path.unlink()
        except OSError as exc:
            messagebox.showerror("删除失败", str(exc))
            return
        self.current_db = ""
        self._refresh_databases()

    def refresh_items(self) -> None:
        self._normalize_item_order()
        query = self.search_var.get().strip().lower()
        if query:
            self.filtered_keys = [
                key for key in self.item_order if query in key.lower() or query in self.data[key].lower()
            ]
        else:
            self.filtered_keys = list(self.item_order)

        self._normalize_group_state()
        self.item_type_by_key = {
            key: normalize_item_type(self.item_type_by_key.get(key)) for key in self.data
        }
        self.selected_keys = {key for key in self.selected_keys if key in self.data}
        if not self.selected_keys:
            self.selected_key = None
        elif self.selected_key not in self.selected_keys:
            self.selected_key = self._ordered_selected_keys()[0]
        self.root.after_idle(self._layout_quick_buttons)
        self._update_selection()

    def _layout_quick_buttons(self) -> None:
        self._set_drop_target_item(None)
        for child in self.quick_frame.winfo_children():
            child.destroy()
        self.chips = {}
        self.group_canvases = {}

        width = max(self.quick_canvas.winfo_width() - 8, 320)
        y = 8
        row_height = 34
        gap_x = 8
        gap_y = 8

        if not self.filtered_keys:
            label = ttk.Label(self.quick_frame, text="暂无匹配条目", style="PanelMuted.TLabel")
            label.place(x=12, y=12)
            self._bind_wheel(label)
            self.quick_frame.configure(width=width, height=52)
            self.quick_canvas.configure(scrollregion=(0, 0, width, 52))
            return

        group_width = max(width - 16, 300)
        for group, keys in self._filtered_groups():
            positions: list[tuple[str, str, int, int, int]] = []
            x = 16
            inner_y = 34
            inner_width = max(group_width - 32, 260)
            for key in keys:
                display = self._chip_display_text(key)
                chip_width = min(max(self.chip_font.measure(display) + 28, 58), 260)
                if x + chip_width > inner_width + 16 and x > 16:
                    x = 16
                    inner_y += row_height + gap_y
                positions.append((key, display, chip_width, x, inner_y))
                x += chip_width + gap_x

            group_height = inner_y + row_height + 14
            group_canvas = tk.Canvas(
                self.quick_frame,
                width=group_width,
                height=group_height,
                bg="#ffffff",
                highlightthickness=0,
                bd=0,
            )
            group_canvas.place(x=8, y=y)
            self.group_canvases[group] = group_canvas
            self._bind_wheel(group_canvas)
            self._draw_group_box(group_canvas, group_width, group_height, group)

            for key, display, chip_width, chip_x, chip_y in positions:
                chip = ChipButton(
                    group_canvas,
                    item_key=key,
                    display_text=display,
                    width=chip_width,
                    height=row_height,
                    click_command=self.use_item,
                    context_command=self.show_context_menu,
                    drag_command=self.drag_item,
                    drag_preview_command=self.update_drag_preview,
                    wheel_command=self._on_mouse_wheel,
                    font=self.chip_font,
                )
                chip.place(x=chip_x, y=chip_y)
                chip.set_selected(key in self.selected_keys)
                self.chips[key] = chip

            y += group_height + gap_y

        total_height = y + 2
        self.quick_frame.configure(width=width, height=total_height)
        self.quick_canvas.itemconfigure(self.quick_window, width=width)
        self.quick_canvas.configure(scrollregion=(0, 0, width, total_height))

    def _draw_group_box(self, canvas: tk.Canvas, width: int, height: int, group: str) -> None:
        radius = 12
        x1, y1, x2, y2 = 1, 12, width - 1, height - 1
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        canvas.create_polygon(
            points,
            smooth=True,
            splinesteps=16,
            fill="#ffffff",
            outline="#2563eb" if group == self.drop_target_group else "#d8dee9",
            width=2 if group == self.drop_target_group else 1,
            tags=("group-border",),
        )
        title = truncate_text(group, 22)
        title_width = self.chip_font.measure(title) + 18
        canvas.create_rectangle(12, 3, 12 + title_width, 21, fill="#ffffff", outline="#ffffff")
        canvas.create_text(20, 12, anchor="w", text=title, fill="#374151", font=("Microsoft YaHei UI", 9, "bold"))

    def _bind_wheel(self, widget: tk.Widget) -> None:
        widget.bind("<MouseWheel>", self._on_mouse_wheel)
        widget.bind("<Button-4>", self._on_mouse_wheel)
        widget.bind("<Button-5>", self._on_mouse_wheel)

    def _normalize_group_state(self) -> None:
        for key in self.data:
            self.group_by_key[key] = normalize_group_name(self.group_by_key.get(key) or infer_group_name(key))

        seen: list[str] = []
        for group in self.group_order:
            group = normalize_group_name(group)
            if group not in seen and any(self.group_by_key.get(key) == group for key in self.data):
                seen.append(group)
        for key in self.data:
            group = self.group_by_key[key]
            if group not in seen:
                seen.append(group)
        self.group_order = seen

    def _normalize_item_order(self) -> None:
        ordered: list[str] = []
        for key in self.item_order:
            if key in self.data and key not in ordered:
                ordered.append(key)
        for key in self.data:
            if key not in ordered:
                ordered.append(key)
        self.item_order = ordered

    def _filtered_groups(self) -> list[tuple[str, list[str]]]:
        self._normalize_group_state()
        grouped: list[tuple[str, list[str]]] = []
        for group in self.group_order:
            keys = [key for key in self.item_order if key in self.filtered_keys and self.group_by_key.get(key) == group]
            if keys:
                grouped.append((group, keys))
        return grouped

    def _chip_display_text(self, key: str) -> str:
        item_type = normalize_item_type(self.item_type_by_key.get(key))
        prefix = ITEM_TYPE_SHORT_LABELS[item_type]
        return truncate_text(f"[{prefix}] {key}", 24)

    def _group_at_point(self, x: int, y: int) -> Optional[str]:
        for group, canvas in self.group_canvases.items():
            if not canvas.winfo_exists() or not canvas.winfo_ismapped():
                continue
            left = canvas.winfo_rootx()
            top = canvas.winfo_rooty()
            right = left + canvas.winfo_width()
            bottom = top + canvas.winfo_height()
            if left <= x < right and top <= y < bottom:
                return group
        return None

    def _item_at_point(self, x: int, y: int) -> Optional[str]:
        for key, chip in self.chips.items():
            if not chip.winfo_exists() or not chip.winfo_ismapped():
                continue
            left = chip.winfo_rootx()
            top = chip.winfo_rooty()
            right = left + chip.winfo_width()
            bottom = top + chip.winfo_height()
            if left <= x < right and top <= y < bottom:
                return key
        return None

    def _reorder_item_within_group(self, key: str, x: int, y: int) -> bool:
        source_group = normalize_group_name(self.group_by_key.get(key) or infer_group_name(key))
        group_keys = [
            item_key for item_key in self.data if self.group_by_key.get(item_key) == source_group
        ]
        if key not in group_keys:
            return False

        target_key = self._item_at_point(x, y)
        if target_key == key:
            return False
        target_key = target_key if target_key in group_keys else None
        reordered = [item_key for item_key in group_keys if item_key != key]
        if target_key is None:
            reordered.append(key)
        else:
            target_index = reordered.index(target_key)
            target_chip = self.chips[target_key]
            target_center = target_chip.winfo_rootx() + target_chip.winfo_width() / 2
            target_center_y = target_chip.winfo_rooty() + target_chip.winfo_height() / 2
            after = y > target_center_y or (y == target_center_y and x >= target_center)
            insert_at = target_index + 1 if after else target_index
            reordered.insert(insert_at, key)

        if reordered == group_keys:
            return False

        data_keys = list(self.item_order)
        group_positions = [index for index, item_key in enumerate(data_keys) if item_key in group_keys]
        for index, position in enumerate(group_positions):
            data_keys[position] = reordered[index]
        self.item_order = data_keys
        self.save_database_to_disk()
        self.selected_key = key
        self.selected_keys = {key}
        self.refresh_items()
        return True

    def move_selected_within_group(self, direction: int) -> None:
        selected = self._ordered_selected_keys()
        if len(selected) != 1:
            self.status_var.set(
                f"请先只选择一个条目，再使用 {shortcut_display(self.shortcuts['move_left'])}/"
                f"{shortcut_display(self.shortcuts['move_right'])} 调整位置。"
            )
            return

        key = selected[0]
        group = normalize_group_name(self.group_by_key.get(key) or infer_group_name(key))
        group_keys = [
            item_key for item_key in self.item_order if self.group_by_key.get(item_key) == group
        ]
        current_index = group_keys.index(key)
        target_index = current_index + (1 if direction > 0 else -1)
        if target_index < 0 or target_index >= len(group_keys):
            self.status_var.set(f"{key} 已经在分组“{group}”的边界位置。")
            return

        group_keys[current_index], group_keys[target_index] = group_keys[target_index], group_keys[current_index]
        group_positions = [
            index for index, item_key in enumerate(self.item_order) if item_key in group_keys
        ]
        for index, position in enumerate(group_positions):
            self.item_order[position] = group_keys[index]
        self.save_database_to_disk()
        self.selected_key = key
        self.selected_keys = {key}
        self.refresh_items()
        direction_label = "右" if direction > 0 else "左"
        self.status_var.set(f"已将“{key}”向{direction_label}移动一格。")

    def _set_drop_target_group(self, group: Optional[str]) -> None:
        group = normalize_group_name(group) if group else None
        if group == self.drop_target_group:
            return
        self.drop_target_group = group
        for canvas_group, canvas in self.group_canvases.items():
            if canvas.winfo_exists():
                canvas.itemconfigure(
                    "group-border",
                    outline="#2563eb" if canvas_group == group else "#d8dee9",
                    width=2 if canvas_group == group else 1,
                )

    def _set_drop_target_item(self, key: Optional[str]) -> None:
        self.drop_target_item = key
        for item_key, chip in self.chips.items():
            if chip.winfo_exists():
                chip.set_drop_target(item_key == key)

    def update_drag_preview(self, key: str, x: int, y: int, visible: bool) -> None:
        if not visible:
            self._set_drop_target_group(None)
            self._set_drop_target_item(None)
            if self.drag_ghost is not None:
                self.drag_ghost.withdraw()
            return
        target_group = self._group_at_point(x, y)
        source_group = normalize_group_name(self.group_by_key.get(key) or infer_group_name(key))
        target_item = self._item_at_point(x, y)
        if target_group != source_group or target_item == key:
            target_item = None
        self._set_drop_target_group(target_group)
        self._set_drop_target_item(target_item)
        if self.drag_ghost is None:
            self.drag_ghost = tk.Toplevel(self.root)
            self.drag_ghost.overrideredirect(True)
            self.drag_ghost.attributes("-topmost", True)
            try:
                self.drag_ghost.attributes("-alpha", 0.78)
            except tk.TclError:
                pass
            self.drag_ghost_label = tk.Label(
                self.drag_ghost,
                bg="#dbeafe",
                fg="#1f2937",
                bd=1,
                relief="solid",
                padx=10,
                pady=5,
                font=("Microsoft YaHei UI", 9),
            )
            self.drag_ghost_label.pack()
        if self.drag_ghost_label is not None:
            target_hint = ""
            if target_item:
                target_chip = self.chips.get(target_item)
                if target_chip is not None:
                    target_center_x = target_chip.winfo_rootx() + target_chip.winfo_width() / 2
                    target_center_y = target_chip.winfo_rooty() + target_chip.winfo_height() / 2
                    after = y > target_center_y or (y == target_center_y and x >= target_center_x)
                    target_hint = f" → {truncate_text(target_item, 16)}{'后' if after else '前'}"
            elif target_group:
                target_hint = f" → {target_group}（默认位置）"
            self.drag_ghost_label.configure(text=truncate_text(self._chip_display_text(key) + target_hint, 34))
        self.drag_ghost.geometry(f"+{int(x) + 16}+{int(y) + 16}")
        self.drag_ghost.deiconify()
        self.drag_ghost.lift()

    def _on_quick_canvas_configure(self, event: tk.Event) -> None:
        self.quick_canvas.itemconfigure(self.quick_window, width=event.width)
        self.root.after_idle(self._layout_quick_buttons)

    def _on_mouse_wheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            steps = -3
        elif getattr(event, "num", None) == 5:
            steps = 3
        elif getattr(event, "delta", 0) > 0:
            steps = -3
        else:
            steps = 3
        self.quick_canvas.yview_scroll(steps, "units")
        return "break"

    def add_item(self) -> None:
        dialog = ItemDialog(
            self.root,
            "新增条目",
            groups=self.group_order,
            topmost=bool(self.topmost_var.get()),
        )
        if not dialog.result:
            return
        key, value, group, item_type = dialog.result
        self._save_item(None, key, value, group, item_type)

    def show_context_menu(self, key: str, x: int, y: int) -> None:
        if key not in self.data:
            return
        self.selected_key = key
        self.selected_keys = {key}
        self._update_selection()
        self._highlight_selected_chip()

        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="编辑", command=self.edit_selected)
        menu.add_command(label="复制", command=lambda: self.copy_item(key))
        menu.add_command(label="分组", command=self.change_group_selected)
        menu.add_separator()
        menu.add_command(label="删除", command=self.delete_selected)
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def copy_item(self, key: str) -> None:
        if key not in self.data:
            return
        self.paste_helper.copy_to_clipboard(self.data[key])
        self.selected_key = key
        self.selected_keys = {key}
        self._update_selection()
        self._highlight_selected_chip()
        item_type = normalize_item_type(self.item_type_by_key.get(key))
        self.status_var.set(f"已复制{ITEM_TYPE_LABELS[item_type]}：{key}")

    def edit_selected(self) -> None:
        selected = self._ordered_selected_keys()
        if len(selected) != 1:
            if selected:
                messagebox.showinfo("不能同时编辑", "当前已选择多个条目。请只选择一个条目后再编辑。")
            else:
                messagebox.showinfo("没有可编辑的条目", "请先点击一个快捷按钮。")
            return
        old_key = selected[0]
        dialog = ItemDialog(
            self.root,
            "编辑条目",
            initial_key=old_key,
            initial_value=self.data[old_key],
            initial_group=self.group_by_key.get(old_key, infer_group_name(old_key)),
            initial_type=self.item_type_by_key.get(old_key, ITEM_TYPE_TEXT),
            groups=self.group_order,
            topmost=bool(self.topmost_var.get()),
        )
        if not dialog.result:
            return
        key, value, group, item_type = dialog.result
        self._save_item(old_key, key, value, group, item_type)

    def _save_item(self, old_key: Optional[str], key: str, value: str, group: str, item_type: str) -> None:
        group = normalize_group_name(group)
        item_type = normalize_item_type(item_type)
        if old_key != key and key in self.data:
            if not messagebox.askyesno("覆盖已有条目", f"{key} 已存在，是否覆盖？"):
                return

        if old_key and old_key in self.data and old_key != key:
            new_data: dict[str, str] = {}
            for item_key, item_value in self.data.items():
                if item_key == old_key:
                    new_data[key] = value
                elif item_key != key:
                    new_data[item_key] = item_value
            self.data = new_data
            self.item_order = [
                key if item_key == old_key else item_key
                for item_key in self.item_order
                if item_key != key
            ]
            self.group_by_key.pop(old_key, None)
            self.item_type_by_key.pop(old_key, None)
        else:
            self.data[key] = value
            if key not in self.item_order:
                self.item_order.append(key)

        self.item_type_by_key[key] = item_type
        self.group_by_key[key] = group
        if group not in self.group_order:
            self.group_order.append(group)
        self._normalize_group_state()
        self.save_database_to_disk()
        self.selected_key = key
        self.selected_keys = {key}
        self.refresh_items()
        self.status_var.set(f"已保存：{key}")

    def change_group_selected(self) -> None:
        selected = self._ordered_selected_keys()
        if not selected:
            messagebox.showinfo("没有可调整的条目", "请先点击一个快捷按钮，或用 Shift+点击选择多个条目。")
            return

        self._normalize_group_state()
        selected_groups = {self.group_by_key.get(key, infer_group_name(key)) for key in selected}
        initial_group = next(iter(selected_groups)) if len(selected_groups) == 1 else ""
        dialog = GroupDialog(
            self.root,
            groups=self.group_order,
            initial_group=initial_group,
            topmost=bool(self.topmost_var.get()),
        )
        if not dialog.result:
            return

        changed_count = self._move_keys_to_group(selected, dialog.result)
        if changed_count == 1:
            self.status_var.set(f"已调整分组：{selected[0]} -> {dialog.result}")
        elif changed_count > 1:
            self.status_var.set(f"已将 {changed_count} 个条目调整到分组：{dialog.result}")

    def _move_keys_to_group(self, keys: list[str], group: str) -> int:
        group = normalize_group_name(group)
        valid_keys = [key for key in keys if key in self.data]
        if not valid_keys:
            return 0

        changed_group = any(
            normalize_group_name(self.group_by_key.get(key) or infer_group_name(key)) != group
            for key in valid_keys
        )
        for key in valid_keys:
            self.group_by_key[key] = group
        if group not in self.group_order:
            self.group_order.append(group)

        if changed_group:
            data_keys = [key for key in self.item_order if key not in valid_keys]
            target_positions = [
                index for index, key in enumerate(data_keys) if self.group_by_key.get(key) == group
            ]
            insert_at = target_positions[-1] + 1 if target_positions else len(data_keys)
            data_keys[insert_at:insert_at] = valid_keys
            self.item_order = data_keys

        self._normalize_group_state()
        self.save_database_to_disk()
        self.selected_keys = set(valid_keys)
        if self.selected_key not in self.selected_keys:
            self.selected_key = valid_keys[-1]
        self.refresh_items()
        return len(valid_keys)

    def delete_selected(self) -> None:
        selected = self._ordered_selected_keys()
        if not selected:
            messagebox.showinfo("没有可删除的条目", "请先点击一个快捷按钮。")
            return
        if len(selected) == 1:
            message = f"确定删除「{selected[0]}」？"
        else:
            preview = "\n".join(f"- {key}" for key in selected[:6])
            if len(selected) > 6:
                preview += f"\n...等 {len(selected)} 项"
            message = f"确定删除选中的 {len(selected)} 个条目？\n\n{preview}"
        if not messagebox.askyesno("删除条目", message):
            return
        for key in selected:
            self.data.pop(key, None)
            self.item_order = [item_key for item_key in self.item_order if item_key != key]
            self.item_type_by_key.pop(key, None)
            self.group_by_key.pop(key, None)
        self._normalize_group_state()
        self.save_database_to_disk()
        self.selected_key = None
        self.selected_keys.clear()
        self.refresh_items()
        if len(selected) == 1:
            self.status_var.set(f"已删除：{selected[0]}")
        else:
            self.status_var.set(f"已批量删除 {len(selected)} 个条目")

    def use_item(self, key: str, state: int = 0) -> None:
        if key not in self.data:
            return
        item_type = normalize_item_type(self.item_type_by_key.get(key))
        type_label = ITEM_TYPE_LABELS[item_type]
        has_ctrl = bool(state & MOD_CONTROL)
        has_shift = bool(state & MOD_SHIFT)
        is_resource = item_type in {ITEM_TYPE_LINK, ITEM_TYPE_FILE, ITEM_TYPE_FOLDER}
        if has_ctrl and has_shift:
            self.open_item_resource(key, reveal_in_explorer=self.explorer_key_held)
            return
        if has_ctrl and is_resource:
            self.copy_item(key)
            self.status_var.set(f"已复制{type_label}路径：{key}")
            return
        if has_shift:
            self._toggle_selection(key)
            count = len(self.selected_keys)
            if count:
                self.status_var.set(f"已选择 {count} 个条目。可继续 Shift+点击增减选择，或点击删除批量删除。")
            else:
                self.status_var.set("已取消选择。")
            return

        self.selected_key = key
        self.selected_keys = {key}
        self._update_selection()
        self._highlight_selected_chip()
        force_paste = has_ctrl
        should_paste = self.auto_paste_var.get() or force_paste
        result = self.paste_helper.copy_or_paste(self.data[key], should_paste)
        if result == "pasted":
            if force_paste and not self.auto_paste_var.get():
                self.status_var.set(f"已通过 Ctrl+点击粘贴{type_label}：{key}")
            else:
                self.status_var.set(f"已粘贴{type_label}：{key}")
        else:
            if force_paste:
                self.status_var.set(f"已复制{type_label}：{key}。Ctrl+点击未能自动填入，请在目标输入框按 Ctrl+V。")
            else:
                self.status_var.set(f"已复制{type_label}：{key}。需要直接填入时可 Ctrl+点击。")

    def drag_item(self, key: str, x: int, y: int) -> None:
        if key not in self.data:
            return
        target_group = self._group_at_point(x, y) or self.drop_target_group
        self._set_drop_target_group(None)
        if target_group:
            current_group = normalize_group_name(self.group_by_key.get(key) or infer_group_name(key))
            if current_group == target_group:
                if self._reorder_item_within_group(key, x, y):
                    self.status_var.set(f"已在分组“{target_group}”内调整：{key}")
                else:
                    self.status_var.set(f"{key} 在分组“{target_group}”内的位置未改变。")
                return
            self._move_keys_to_group([key], target_group)
            self.status_var.set(f"已将“{key}”拖动到分组“{target_group}”，按默认顺序放置。")
            return
        self.selected_key = key
        self.selected_keys = {key}
        self._update_selection()
        self._highlight_selected_chip()
        result = self.paste_helper.type_at_point(self.data[key], x, y)
        if result == "typed":
            self.status_var.set(f"已拖动输入：{key}")
        else:
            self.status_var.set(f"已复制：{key}。拖动位置未识别为外部输入框，请手动 Ctrl+V。")

    def open_item_resource(self, key: str, reveal_in_explorer: bool = False) -> None:
        if key not in self.data:
            return
        value = self.data[key].strip()
        item_type = normalize_item_type(self.item_type_by_key.get(key))
        if item_type == ITEM_TYPE_TEXT:
            self.status_var.set("只有超链接、文件或文件夹条目支持 Ctrl+Shift+点击打开资源。")
            return
        try:
            if re.match(r"^(https?|ftp|mailto):", value, re.IGNORECASE):
                webbrowser.open(value)
                self.status_var.set(f"已打开网址：{key}")
                return

            resource_path = Path(os.path.expandvars(os.path.expanduser(value)))
            if not resource_path.is_absolute():
                resource_path = ROOT / resource_path
            resource_path = resource_path.resolve()
            if not resource_path.exists():
                messagebox.showwarning("资源不存在", f"找不到本地资源：\n{resource_path}", parent=self.root)
                return
            if reveal_in_explorer:
                if resource_path.is_dir():
                    os.startfile(str(resource_path))
                else:
                    subprocess.Popen(["explorer.exe", f"/select,{resource_path}"])
            else:
                os.startfile(str(resource_path))
            action = "已在资源管理器中定位" if reveal_in_explorer else "已直接打开"
            self.status_var.set(f"{action}本地资源：{key}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("打开资源失败", str(exc), parent=self.root)

    def _update_selection(self) -> None:
        selected = self._ordered_selected_keys()
        count = len(selected)
        if count == 1:
            key = selected[0]
            self.selected_key = key
            item_type = normalize_item_type(self.item_type_by_key.get(key))
            self.selected_var.set(f"当前条目：[{ITEM_TYPE_LABELS[item_type]}] {truncate_text(key, 26)}")
            preview = self.data[key].replace("\n", " ")
            self.preview_var.set(truncate_text(preview, 48))
            self.edit_button.grid()
            self.group_button.grid()
            self.delete_button.grid()
            self.edit_button.configure(state="normal")
            self.group_button.configure(state="normal")
            self.delete_button.configure(text="删除", state="normal")
        elif count > 1:
            self.selected_key = selected[-1]
            self.selected_var.set(f"已选择 {count} 个条目")
            self.preview_var.set("多选状态下可调整分组或批量删除。")
            self.edit_button.grid()
            self.group_button.grid()
            self.delete_button.grid()
            self.edit_button.configure(state="disabled")
            self.group_button.configure(state="normal")
            self.delete_button.configure(text=f"删除 {count} 项", state="normal")
        else:
            self.selected_key = None
            self.selected_var.set("未选择条目")
            self.preview_var.set("")
            self.edit_button.grid_remove()
            self.group_button.grid_remove()
            self.delete_button.grid_remove()

    def _highlight_selected_chip(self) -> None:
        for key, chip in self.chips.items():
            chip.set_selected(key in self.selected_keys)

    def _ordered_selected_keys(self) -> list[str]:
        return [key for key in self.item_order if key in self.selected_keys]

    def _toggle_selection(self, key: str) -> None:
        if key in self.selected_keys:
            self.selected_keys.remove(key)
            if self.selected_key == key:
                ordered = self._ordered_selected_keys()
                self.selected_key = ordered[-1] if ordered else None
        else:
            self.selected_keys.add(key)
            self.selected_key = key
        self._update_selection()
        self._highlight_selected_chip()

    def _apply_topmost(self) -> None:
        self.root.attributes("-topmost", bool(self.topmost_var.get()))
        self._save_settings()

    def _tick_foreground(self) -> None:
        self.paste_helper.poll_foreground()
        title = self.paste_helper.last_external_title
        if title:
            if len(title) > 42:
                title = title[:39] + "..."
            self.target_var.set(f"上一个目标窗口：{title}")
        self.root.after(300, self._tick_foreground)

    def on_close(self) -> None:
        self._save_settings()
        if self.terminal_panel is not None:
            self.terminal_panel.close()
        if self.drag_ghost is not None:
            self.drag_ghost.destroy()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    QuickTextApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

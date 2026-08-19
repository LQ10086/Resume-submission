# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
from ctypes import wintypes
import codecs
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import winreg
from pathlib import Path
from typing import Callable, Optional
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter.font as tkfont
from wcwidth import wcwidth

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


def _directory_is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".resume_quick_paste_", dir=path, delete=True):
            pass
        return True
    except (OSError, ValueError):
        return False


def app_data_root(application_dir: Path) -> Path:
    override = str(os.environ.get("RESUME_QUICK_PASTE_HOME", "")).strip()
    if override:
        try:
            candidate = Path(os.path.expandvars(os.path.expanduser(override))).resolve()
            if _directory_is_writable(candidate):
                return candidate
        except (OSError, ValueError):
            pass
    if _directory_is_writable(application_dir):
        return application_dir
    local_app_data = str(os.environ.get("LOCALAPPDATA", "")).strip()
    try:
        candidate = (
            Path(local_app_data).resolve() / "ResumeQuickPaste"
            if local_app_data
            else Path.home() / "AppData" / "Local" / "ResumeQuickPaste"
        )
    except (OSError, ValueError):
        candidate = application_dir
    if _directory_is_writable(candidate):
        return candidate
    return application_dir


ROOT = app_root()
DATA_ROOT = app_data_root(ROOT)
DB_DIR = DATA_ROOT / DATABASE_DIR
SETTINGS_PATH = DATA_ROOT / SETTINGS_FILE
PROJECT_ROOT = ROOT.parent if getattr(sys, "frozen", False) and ROOT.name.lower() == "release" else ROOT
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
DEFAULT_SHORTCUTS = {
    "terminal_toggle": "ctrl+j",
    "add_item": "ctrl+n",
    "edit_item": "ctrl+e",
    "move_left": "ctrl+left",
    "move_right": "ctrl+right",
    "move_group_up": "ctrl+up",
    "move_group_down": "ctrl+down",
    "explorer_reveal": "ctrl+shift+e",
}
SHORTCUT_LABELS = {
    "terminal_toggle": "打开/隐藏终端",
    "add_item": "新增条目",
    "edit_item": "编辑选中条目",
    "move_left": "组内向左移动",
    "move_right": "组内向右移动",
    "move_group_up": "分组向上移动",
    "move_group_down": "分组向下移动",
    "explorer_reveal": "资源管理器定位模式",
}
THEME_LABELS = {
    "light": "明亮蓝",
    "soft_gray": "柔和灰",
    "jetbrains_gray": "JetBrains 灰色",
}
TERMINAL_POSITION_LABELS = {
    "right": "右侧",
    "bottom": "底部",
}
DEFAULT_TERMINAL_FONT = "Consolas"
DEFAULT_TERMINAL_FONT_SIZE = 11
TERMINAL_FONT_CANDIDATES = (
    "JetBrains Mono",
    "Cascadia Code",
    "Consolas",
    "Cascadia Mono",
    "Lucida Console",
    "Courier New",
)
THEME_PALETTES = {
    "light": {
        "bg": "#f6f7f9", "panel": "#ffffff", "input": "#ffffff", "control": "#eef2f7",
        "text": "#1f2937", "muted": "#6b7280", "accent": "#2563eb", "accent_hover": "#1d4ed8",
        "accent_light": "#dbeafe", "border": "#bfdbfe", "group_border": "#d8dee9",
        "chip": "#eef2ff", "chip_border": "#c7d2fe", "chip_hover": "#dbeafe",
        "chip_hover_border": "#93c5fd", "selected_text": "#ffffff", "danger": "#991b1b",
        "drop": "#fef3c7", "drop_border": "#f59e0b", "drop_text": "#92400e",
    },
    "soft_gray": {
        "bg": "#e7e9ec", "panel": "#f4f5f7", "input": "#ffffff", "control": "#dfe3e7",
        "text": "#2f3337", "muted": "#687078", "accent": "#596f84", "accent_hover": "#465c70",
        "accent_light": "#d4dbe2", "border": "#b8c0c8", "group_border": "#c5cbd1",
        "chip": "#e2e6ea", "chip_border": "#bec6ce", "chip_hover": "#d3d9df",
        "chip_hover_border": "#9da8b3", "selected_text": "#ffffff", "danger": "#9b3a3a",
        "drop": "#eee2c7", "drop_border": "#bd8b35", "drop_text": "#704b16",
    },
    "jetbrains_gray": {
        "bg": "#2b2d30", "panel": "#1e1f22", "input": "#2b2d30", "control": "#393b40",
        "text": "#bcbec4", "muted": "#8b8d92", "accent": "#3574f0", "accent_hover": "#2f65ca",
        "accent_light": "#2f415f", "border": "#43454a", "group_border": "#4e5157",
        "chip": "#393b40", "chip_border": "#4e5157", "chip_hover": "#434b55",
        "chip_hover_border": "#5e6c7a", "selected_text": "#ffffff", "danger": "#ff6b68",
        "drop": "#5a4630", "drop_border": "#f0a732", "drop_text": "#ffc66d",
    },
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
        "terminal_position": "right",
        "terminal_font": DEFAULT_TERMINAL_FONT,
        "terminal_font_size": DEFAULT_TERMINAL_FONT_SIZE,
        "theme": "light",
    }


def normalize_terminal_position(value: object) -> str:
    position = str(value or "right").strip().lower()
    return position if position in TERMINAL_POSITION_LABELS else "right"


def normalize_terminal_font(value: object) -> str:
    family = str(value or DEFAULT_TERMINAL_FONT).strip()
    return family[:80] or DEFAULT_TERMINAL_FONT


def normalize_terminal_font_size(value: object) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = DEFAULT_TERMINAL_FONT_SIZE
    return min(max(size, 8), 24)


def installed_terminal_fonts(widget: tk.Misc) -> list[str]:
    installed = {name.casefold(): name for name in tkfont.families(widget) if not name.startswith("@")}
    choices = [installed[name.casefold()] for name in TERMINAL_FONT_CANDIDATES if name.casefold() in installed]
    if not choices:
        choices.append(str(tkfont.nametofont("TkFixedFont").actual("family")))
    return choices


def resolve_terminal_font(widget: tk.Misc, requested: object) -> str:
    installed = {name.casefold(): name for name in tkfont.families(widget) if not name.startswith("@")}
    wanted = normalize_terminal_font(requested)
    if wanted.casefold() in installed:
        return installed[wanted.casefold()]
    for candidate in TERMINAL_FONT_CANDIDATES:
        if candidate.casefold() in installed:
            return installed[candidate.casefold()]
    return str(tkfont.nametofont("TkFixedFont").actual("family"))


def decode_terminal_chunk(decoder, chunk: object) -> str:
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, (bytes, bytearray, memoryview)):
        return decoder.decode(bytes(chunk), final=False)
    return str(chunk)


def terminal_process_spec(shell: str) -> tuple[list[str], dict[str, str]]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    if shell == "cmd":
        command = ["cmd.exe", "/Q", "/K", "chcp 65001>nul"]
    else:
        utf8_setup = (
            "$utf8 = [System.Text.UTF8Encoding]::new($false); "
            "[Console]::InputEncoding = $utf8; "
            "[Console]::OutputEncoding = $utf8; "
            "$global:OutputEncoding = $utf8; "
            "$global:PSDefaultParameterValues['Get-Content:Encoding'] = 'utf8'"
        )
        command = [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-NoExit",
            "-Command",
            utf8_setup,
        ]
    return command, environment


def windows_clipboard_has_image() -> bool:
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    image_formats = (2, 8, 17)  # CF_BITMAP, CF_DIB, CF_DIBV5
    try:
        png_format = int(user32.RegisterClipboardFormatW("PNG"))
        if png_format:
            image_formats += (png_format,)
        return any(bool(user32.IsClipboardFormatAvailable(fmt)) for fmt in image_formats)
    except (AttributeError, OSError):
        return False


def terminal_symbol_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start: Optional[int] = None
    for index, character in enumerate(text):
        codepoint = ord(character)
        is_symbol = 0x2600 <= codepoint <= 0x27BF or 0x1F000 <= codepoint <= 0x1FAFF
        if is_symbol and start is None:
            start = index
        elif not is_symbol and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, len(text)))
    return ranges


def normalize_theme(value: object) -> str:
    theme = str(value or "light").strip().lower()
    return theme if theme in THEME_PALETTES else "light"


def theme_palette(value: object) -> dict[str, str]:
    return dict(THEME_PALETTES[normalize_theme(value)])


def widget_palette(widget: tk.Misc) -> dict[str, str]:
    try:
        top = widget.winfo_toplevel()
        palette = getattr(top, "_theme_palette", None)
        if isinstance(palette, dict):
            return palette
    except tk.TclError:
        pass
    return theme_palette("light")


OPEN_WITH_APP_NAMES = {
    "excel.exe": "Microsoft Excel",
    "winword.exe": "Microsoft Word",
    "powerpnt.exe": "Microsoft PowerPoint",
    "et.exe": "WPS 表格",
    "wps.exe": "WPS 文字",
    "wpp.exe": "WPS 演示",
    "scalc.exe": "LibreOffice Calc",
    "simpress.exe": "LibreOffice Impress",
    "soffice.exe": "LibreOffice",
    "devenv.exe": "Microsoft Visual Studio",
    "code.exe": "Visual Studio Code",
    "notepad.exe": "记事本",
    "notepad++.exe": "Notepad++",
    "pycharm64.exe": "PyCharm",
}


def _registry_views() -> tuple[int, ...]:
    return tuple(dict.fromkeys((0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0))))


def _registry_value(root, key_path: str, name: str = "") -> Optional[str]:
    for view in _registry_views():
        try:
            with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | view) as key:
                value, _ = winreg.QueryValueEx(key, name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except OSError:
            continue
    return None


def _registry_value_names(root, key_path: str) -> list[str]:
    names: list[str] = []
    for view in _registry_views():
        try:
            with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | view) as key:
                index = 0
                while True:
                    try:
                        name, _value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    if name and name not in names:
                        names.append(name)
        except OSError:
            pass
    return names


def _registry_subkey_names(root, key_path: str) -> list[str]:
    names: list[str] = []
    for view in _registry_views():
        try:
            with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ | view) as key:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    if name not in names:
                        names.append(name)
        except OSError:
            pass
    return names


def _resolve_indirect_string(value: str) -> str:
    if not value.startswith("@"):
        return value
    buffer = ctypes.create_unicode_buffer(512)
    try:
        loader = ctypes.windll.shlwapi.SHLoadIndirectString
        loader.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, ctypes.c_void_p]
        loader.restype = wintypes.LONG
        result = loader(value, buffer, len(buffer), None)
    except (AttributeError, OSError, TypeError, ctypes.ArgumentError):
        return ""
    return buffer.value.strip() if result == 0 else ""


def _command_line_to_argv(command: str) -> list[str]:
    argc = ctypes.c_int()
    shell32 = ctypes.windll.shell32
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    argv_ptr = shell32.CommandLineToArgvW(command, ctypes.byref(argc))
    if not argv_ptr:
        return []
    try:
        return [argv_ptr[index] for index in range(argc.value)]
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(argv_ptr)


def _find_registered_executable(executable: str) -> Optional[str]:
    executable = os.path.expandvars(executable.strip().strip('"'))
    if Path(executable).is_file():
        return str(Path(executable))
    name = Path(executable).name
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        found = _registry_value(root, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{name}")
        if found and Path(os.path.expandvars(found)).is_file():
            return os.path.expandvars(found)
    return shutil.which(name)


def _handler_from_command(command: str, label_hint: str = "") -> Optional[tuple[str, list[str]]]:
    try:
        argv = _command_line_to_argv(os.path.expandvars(command))
    except (AttributeError, OSError, TypeError, ctypes.ArgumentError):
        return None
    if not argv:
        return None
    executable = _find_registered_executable(argv[0])
    if not executable:
        return None
    argv[0] = executable
    exe_name = Path(executable).name.lower()
    friendly = _registry_value(winreg.HKEY_CLASSES_ROOT, rf"Applications\{exe_name}", "FriendlyAppName")
    label = (
        OPEN_WITH_APP_NAMES.get(exe_name)
        or _resolve_indirect_string(friendly or "")
        or _resolve_indirect_string(label_hint)
        or (label_hint if not label_hint.startswith("@") else "")
        or Path(executable).stem
    )
    return label, argv


def enumerate_open_with_handlers(path: Path) -> list[tuple[str, list[str]]]:
    if path.is_dir():
        handlers: list[tuple[str, list[str]]] = []
        seen_executables: set[str] = set()
        for verb in _registry_subkey_names(winreg.HKEY_CLASSES_ROOT, r"Directory\shell"):
            key_path = rf"Directory\shell\{verb}"
            command = _registry_value(winreg.HKEY_CLASSES_ROOT, key_path + r"\command")
            label = (
                _registry_value(winreg.HKEY_CLASSES_ROOT, key_path, "MUIVerb")
                or _registry_value(winreg.HKEY_CLASSES_ROOT, key_path)
                or verb
            )
            handler = _handler_from_command(command, label) if command else None
            if handler:
                executable_key = str(Path(handler[1][0])).lower()
                if executable_key not in seen_executables:
                    handlers.append(handler)
                    seen_executables.add(executable_key)
        return handlers
    extension = path.suffix.lower()
    if not extension:
        return []
    progids: list[tuple[str, str]] = []
    default_progid = _registry_value(winreg.HKEY_CLASSES_ROOT, extension)
    if default_progid:
        progids.append((default_progid, ""))
    for root, key_path in (
        (winreg.HKEY_CLASSES_ROOT, rf"{extension}\OpenWithProgids"),
        (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{extension}\OpenWithProgids"),
    ):
        for progid in _registry_value_names(root, key_path):
            if all(existing != progid for existing, _label in progids):
                progids.append((progid, ""))

    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in _registry_views():
            try:
                with winreg.OpenKey(
                    root, r"Software\RegisteredApplications", 0, winreg.KEY_READ | view
                ) as registered:
                    index = 0
                    while True:
                        try:
                            app_name, capabilities_path, _kind = winreg.EnumValue(registered, index)
                        except OSError:
                            break
                        index += 1
                        if not isinstance(capabilities_path, str):
                            continue
                        progid = _registry_value(root, capabilities_path + r"\FileAssociations", extension)
                        if progid and all(existing != progid for existing, _label in progids):
                            progids.append((progid, str(app_name)))
            except OSError:
                pass

    executable_names = _registry_subkey_names(
        winreg.HKEY_CLASSES_ROOT, rf"{extension}\OpenWithList"
    )
    open_with_list = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{extension}\OpenWithList"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, open_with_list) as key:
            index = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if name != "MRUList" and isinstance(value, str) and value.lower().endswith(".exe"):
                    if value not in executable_names:
                        executable_names.append(value)
    except OSError:
        pass

    handlers: list[tuple[str, list[str]]] = []
    seen_executables: set[str] = set()
    for progid, label_hint in progids:
        command = _registry_value(winreg.HKEY_CLASSES_ROOT, rf"{progid}\shell\open\command")
        handler = _handler_from_command(command, label_hint) if command else None
        if handler:
            executable_key = Path(handler[1][0]).name.lower()
            if executable_key not in seen_executables:
                handlers.append(handler)
                seen_executables.add(executable_key)
    for executable_name in executable_names:
        command = _registry_value(winreg.HKEY_CLASSES_ROOT, rf"Applications\{executable_name}\shell\open\command")
        handler = _handler_from_command(command or executable_name)
        if handler:
            executable_key = Path(handler[1][0]).name.lower()
            if executable_key not in seen_executables:
                handlers.append(handler)
                seen_executables.add(executable_key)
    return handlers


def safe_enumerate_open_with_handlers(path: Path) -> list[tuple[str, list[str]]]:
    try:
        return enumerate_open_with_handlers(path)
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        return []


def build_open_with_argv(template: list[str], path: Path) -> list[str]:
    path_text = str(path)
    result: list[str] = []
    inserted = False
    for argument in template:
        if argument == "%*" or argument.lower() == "/dde":
            continue
        replaced = re.sub(r"%(?:1|l|v)", lambda _match: path_text, argument, flags=re.IGNORECASE)
        if replaced != argument:
            inserted = True
        result.append(replaced)
    if not inserted:
        result.append(path_text)
    return result


def compute_drop_index(
    rectangles: list[tuple[str, int, int, int, int]], x: int, y: int
) -> int:
    """Return the visual insertion slot for a pointer among wrapped chips."""
    if not rectangles:
        return 0

    rows: list[list[tuple[str, int, int, int, int]]] = []
    for rectangle in sorted(rectangles, key=lambda value: (value[2], value[1])):
        center_y = (rectangle[2] + rectangle[4]) / 2
        if not rows:
            rows.append([rectangle])
            continue
        previous_centers = [(value[2] + value[4]) / 2 for value in rows[-1]]
        previous_center = sum(previous_centers) / len(previous_centers)
        previous_height = max(value[4] - value[2] for value in rows[-1])
        current_height = rectangle[4] - rectangle[2]
        if abs(center_y - previous_center) <= max(previous_height, current_height) * 0.45:
            rows[-1].append(rectangle)
        else:
            rows.append([rectangle])

    row_centers = [
        sum((value[2] + value[4]) / 2 for value in row) / len(row)
        for row in rows
    ]
    selected_row = len(rows) - 1
    for index in range(len(rows) - 1):
        if y < (row_centers[index] + row_centers[index + 1]) / 2:
            selected_row = index
            break

    offset = sum(len(row) for row in rows[:selected_row])
    row = sorted(rows[selected_row], key=lambda value: value[1])
    for index, rectangle in enumerate(row):
        center_x = (rectangle[1] + rectangle[3]) / 2
        if x < center_x:
            return offset + index
    return offset + len(row)


def terminal_column_to_text_index(text: str, terminal_column: int) -> int:
    """Map a terminal display column to a Python string index."""
    display_column = 0
    for index, character in enumerate(text):
        width = max(0, wcwidth(character))
        if display_column + width > terminal_column:
            return index
        display_column += width
        if display_column == terminal_column:
            return index + 1
    return len(text)


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
        palette: dict[str, str],
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=palette["panel"],
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
        self.palette = palette
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
            fill = self.palette["drop"]
            outline = self.palette["drop_border"]
            text_fill = self.palette["drop_text"]
        elif self.selected:
            fill = self.palette["accent"]
            outline = self.palette["accent_hover"]
            text_fill = self.palette["selected_text"]
        elif self.hover:
            fill = self.palette["chip_hover"]
            outline = self.palette["chip_hover_border"]
            text_fill = self.palette["text"]
        else:
            fill = self.palette["chip"]
            outline = self.palette["chip_border"]
            text_fill = self.palette["text"]
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
        self.palette = widget_palette(parent)
        self.window = tk.Toplevel(parent)
        self.window._theme_palette = self.palette
        self.window.title(title)
        self.window.geometry("720x400")
        self.window.minsize(580, 340)
        self.window.transient(parent)
        self.window.configure(bg=self.palette["bg"])
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
            bg=self.palette["input"],
            fg=self.palette["text"],
            insertbackground=self.palette["text"],
            selectbackground=self.palette["accent_light"],
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
        self.palette = widget_palette(parent)
        self.window = tk.Toplevel(parent)
        self.window._theme_palette = self.palette
        self.window.title("调整分组")
        self.window.geometry("420x180")
        self.window.minsize(360, 160)
        self.window.transient(parent)
        self.window.configure(bg=self.palette["bg"])
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
        self.palette = widget_palette(parent)
        self.window = tk.Toplevel(parent)
        self.window._theme_palette = self.palette
        self.window.title("更改快捷键")
        self.window.geometry("420x220")
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.configure(bg=self.palette["bg"])
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
        self.palette = widget_palette(parent)
        self.window = tk.Toplevel(parent)
        self.window._theme_palette = self.palette
        self.window.title("设置")
        self.window.geometry("650x430")
        self.window.minsize(580, 380)
        self.window.transient(parent)
        self.window.configure(bg=self.palette["bg"])
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
        self.terminal_position_var = tk.StringVar(
            value=TERMINAL_POSITION_LABELS[normalize_terminal_position(settings.get("terminal_position"))]
        )
        self.terminal_font_options = installed_terminal_fonts(parent)
        resolved_font = resolve_terminal_font(parent, settings.get("terminal_font"))
        if resolved_font not in self.terminal_font_options:
            self.terminal_font_options.insert(0, resolved_font)
        self.terminal_font_var = tk.StringVar(value=resolved_font)
        self.terminal_font_size_var = tk.StringVar(
            value=str(normalize_terminal_font_size(settings.get("terminal_font_size")))
        )
        self.theme_var = tk.StringVar(value=THEME_LABELS[normalize_theme(settings.get("theme"))])
        self.cwd_hint_var = tk.StringVar()
        self.notebook: Optional[ttk.Notebook] = None
        self.settings_scroll_canvases: dict[str, tk.Canvas] = {}
        self._update_cwd_hint()
        self._build_ui()
        self.window.bind("<Control-s>", lambda _event: self._save())
        self.window.bind("<Escape>", lambda _event: self._cancel())
        self.window.bind("<MouseWheel>", self._on_settings_mousewheel, add="+")
        self.window.bind("<Button-4>", self._on_settings_mousewheel, add="+")
        self.window.bind("<Button-5>", self._on_settings_mousewheel, add="+")
        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.grab_set()
        parent.wait_window(self.window)

    def _add_scrollable_tab(self, notebook: ttk.Notebook, title: str) -> ttk.Frame:
        page = ttk.Frame(notebook)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        canvas = tk.Canvas(
            page,
            bg=self.palette["panel"],
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        content = ttk.Frame(canvas, padding=16)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind(
            "<Configure>",
            lambda _event, target=canvas: target.configure(scrollregion=target.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event, target=canvas, window_id=content_window: target.itemconfigure(
                window_id, width=max(1, event.width)
            ),
        )
        notebook.add(page, text=title)
        self.settings_scroll_canvases[str(page)] = canvas
        return content

    def _on_settings_mousewheel(self, event: tk.Event) -> str:
        if self.notebook is None:
            return ""
        canvas = self.settings_scroll_canvases.get(self.notebook.select())
        if canvas is None or not canvas.winfo_exists():
            return ""
        if getattr(event, "num", None) == 4:
            steps = -3
        elif getattr(event, "num", None) == 5:
            steps = 3
        else:
            delta = int(getattr(event, "delta", 0))
            if delta == 0:
                return ""
            repeats = max(1, abs(delta) // 120)
            steps = -3 * repeats if delta > 0 else 3 * repeats
        canvas.yview_scroll(steps, "units")
        return "break"

    def _build_ui(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        outer = ttk.Frame(self.window, padding=14)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        notebook = ttk.Notebook(outer)
        self.notebook = notebook
        notebook.grid(row=0, column=0, sticky="nsew")
        shortcut_tab = self._add_scrollable_tab(notebook, "快捷键")
        terminal_tab = self._add_scrollable_tab(notebook, "终端")
        appearance_tab = self._add_scrollable_tab(notebook, "外观")

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
        shell_combo = ttk.Combobox(terminal_tab, textvariable=self.shell_var, values=["PowerShell", "CMD"], state="readonly", width=18)
        shell_combo.grid(
            row=0, column=1, sticky="w", pady=(0, 12)
        )
        shell_combo.bind("<MouseWheel>", self._on_settings_mousewheel)
        ttk.Label(terminal_tab, text="停靠位置").grid(row=1, column=0, sticky="w", pady=(0, 12))
        position_combo = ttk.Combobox(
            terminal_tab,
            textvariable=self.terminal_position_var,
            values=list(TERMINAL_POSITION_LABELS.values()),
            state="readonly",
            width=18,
        )
        position_combo.grid(row=1, column=1, sticky="w", pady=(0, 12))
        position_combo.bind("<MouseWheel>", self._on_settings_mousewheel)
        ttk.Label(terminal_tab, text="终端字体").grid(row=2, column=0, sticky="w", pady=(0, 12))
        font_shell = ttk.Frame(terminal_tab)
        font_shell.grid(row=2, column=1, sticky="w", pady=(0, 12))
        font_combo = ttk.Combobox(
            font_shell,
            textvariable=self.terminal_font_var,
            values=self.terminal_font_options,
            state="readonly",
            width=24,
        )
        font_combo.grid(row=0, column=0, sticky="w")
        font_combo.bind("<MouseWheel>", self._on_settings_mousewheel)
        ttk.Label(font_shell, text="字号").grid(row=0, column=1, padx=(14, 6))
        font_size = ttk.Spinbox(
            font_shell,
            from_=8,
            to=24,
            textvariable=self.terminal_font_size_var,
            width=5,
        )
        font_size.grid(row=0, column=2)
        ttk.Label(terminal_tab, text="默认路径").grid(row=3, column=0, sticky="w", pady=(0, 12))
        cwd_shell = ttk.Frame(terminal_tab)
        cwd_shell.grid(row=3, column=1, sticky="ew", pady=(0, 12))
        cwd_shell.columnconfigure(0, weight=1)
        ttk.Entry(cwd_shell, textvariable=self.cwd_var).grid(row=0, column=0, sticky="ew")
        ttk.Button(cwd_shell, text="浏览", command=self._browse_cwd).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(terminal_tab, textvariable=self.cwd_hint_var, style="Muted.TLabel").grid(
            row=4, column=1, sticky="w", pady=(0, 14)
        )
        ttk.Label(terminal_tab, text="自动输入命令").grid(row=5, column=0, sticky="w", pady=(0, 12))
        ttk.Entry(terminal_tab, textvariable=self.command_var).grid(row=5, column=1, sticky="ew", pady=(0, 12))
        ttk.Label(
            terminal_tab,
            text="路径支持相对项目目录的写法，例如 tmp；留空命令则只进入终端。",
            style="Muted.TLabel",
        ).grid(row=6, column=1, sticky="w")

        appearance_tab.columnconfigure(1, weight=1)
        ttk.Label(appearance_tab, text="界面主题").grid(row=0, column=0, sticky="w", padx=(0, 16), pady=(0, 12))
        theme_combo = ttk.Combobox(
            appearance_tab,
            textvariable=self.theme_var,
            values=list(THEME_LABELS.values()),
            state="readonly",
            width=24,
        )
        theme_combo.grid(row=0, column=1, sticky="w", pady=(0, 12))
        theme_combo.bind("<MouseWheel>", self._on_settings_mousewheel)
        ttk.Label(
            appearance_tab,
            text="主题会同时应用于主界面、条目卡片、设置窗口和内置终端。",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w")

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
        try:
            font_size = int(self.terminal_font_size_var.get())
        except ValueError:
            messagebox.showwarning("字号无效", "终端字号必须是 8 到 24 之间的整数。", parent=self.window)
            return
        if not 8 <= font_size <= 24:
            messagebox.showwarning("字号无效", "终端字号必须是 8 到 24 之间的整数。", parent=self.window)
            return
        self.result = {
            "terminal_hotkey": self.shortcuts["terminal_toggle"],
            "shortcuts": dict(self.shortcuts),
            "terminal_shell": "cmd" if self.shell_var.get() == "CMD" else "powershell",
            "terminal_cwd": cwd,
            "terminal_command": self.command_var.get().strip(),
            "terminal_position": next(
                (
                    name
                    for name, label in TERMINAL_POSITION_LABELS.items()
                    if label == self.terminal_position_var.get()
                ),
                "right",
            ),
            "terminal_font": normalize_terminal_font(self.terminal_font_var.get()),
            "terminal_font_size": font_size,
            "theme": next(
                (name for name, label in THEME_LABELS.items() if label == self.theme_var.get()),
                "light",
            ),
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
        "请先阅读项目根目录中的 UPGRADE_FOR_CODEX.md 和 README.md（若存在）；"
        "在 Windows PowerShell 中读取 UTF-8 文本必须显式使用 Get-Content -Encoding UTF8，"
        "不得用系统默认 ANSI 编码读取中文文件。"
        "再处理用户请求，例如“批量导入条目”。"
        "所有修改仅限此项目；不得覆盖或删除 databases、release/databases、resumes_by_role、"
        "release/resumes_by_role 或 app_settings.json 中的用户数据；新增设置必须兼容旧设置。"
        "完成后运行针对性验证；如需要发布版请运行 build_exe.ps1，并用中文简洁说明结果。"
        "完成阅读后不要解释，只回复由 RS_READY_ 与 7C2A 拼接成的一行标记，然后等待用户的下一项任务。"
    )


CODEX_BOOTSTRAP_MARKER = "RS_READY_7C2A"
CODEX_BOOTSTRAP_TIMEOUT_MS = 45_000


def quote_terminal_argument(value: str, shell: str) -> str:
    if shell == "cmd":
        return subprocess.list2cmdline([value])
    return "'" + value.replace("'", "''") + "'"


class TerminalPanel:
    def __init__(
        self,
        parent: tk.Misc,
        shell: str,
        cwd: Path,
        startup_command: str,
        codex_prompt: str = "",
        is_global_shortcut: Optional[Callable[[tk.Event], bool]] = None,
        palette: Optional[dict[str, str]] = None,
        dock_position: str = "right",
        font_family: str = DEFAULT_TERMINAL_FONT,
        font_size: int = DEFAULT_TERMINAL_FONT_SIZE,
    ) -> None:
        self.palette = dict(palette or theme_palette("light"))
        self.background = self.palette["bg"]
        self.panel_background = self.palette["panel"]
        self.border = self.palette["border"]
        self.text_color = self.palette["text"]
        self.muted_color = self.palette["muted"]
        self.accent = self.palette["accent"]
        self.accent_light = self.palette["accent_light"]
        self.window = tk.Frame(
            parent,
            bg=self.panel_background,
            width=440,
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
        self.dock_position = normalize_terminal_position(dock_position)
        self.is_global_shortcut = is_global_shortcut
        self.pty_process = None
        self.process: Optional[subprocess.Popen] = None
        self._closing = False
        self._render_pending = False
        self._resize_pending = False
        self.preferred_height = 300
        self.preferred_width = 440
        self.terminal_rows = 24
        self.terminal_columns = 120
        self._codex_bootstrap_active = False
        self._codex_bootstrap_complete = False
        self._codex_bootstrap_timed_out = False
        self._codex_bootstrap_error = ""
        self._codex_bootstrap_generation = 0
        self._terminal_follow_output = True
        self._selection_frozen = False
        self._mouse_selecting = False
        self.font_family = resolve_terminal_font(parent, font_family)
        self.font_size = normalize_terminal_font_size(font_size)
        self.terminal_font = tkfont.Font(family=self.font_family, size=self.font_size)
        symbol_family = "Segoe UI Emoji" if "Segoe UI Emoji" in tkfont.families(parent) else "Segoe UI Symbol"
        self.terminal_symbol_font = tkfont.Font(family=symbol_family, size=self.font_size)
        self.screen = (
            pyte.HistoryScreen(self.terminal_columns, self.terminal_rows, history=2000, ratio=0.18)
            if pyte is not None else None
        )
        self.stream = pyte.Stream(self.screen) if self.screen is not None else None
        self._build_ui()
        self._start_process()

    def _build_ui(self) -> None:
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)

        self.header = tk.Frame(self.window, bg=self.background, height=36)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.columnconfigure(2, weight=1)
        self.output_title = tk.Label(self.header, text="输出", fg=self.muted_color, bg=self.background, font=("Segoe UI", 10))
        self.output_title.grid(
            row=0, column=0, padx=(14, 14), pady=8
        )
        self.terminal_tab = tk.Frame(self.header, bg=self.panel_background)
        self.terminal_tab.grid(row=0, column=1, sticky="ns")
        self.terminal_title = tk.Label(self.terminal_tab, text="终端", fg=self.accent, bg=self.panel_background, font=("Segoe UI", 10, "bold"))
        self.terminal_title.pack(
            padx=12, pady=(8, 5)
        )
        self.terminal_indicator = tk.Frame(self.terminal_tab, bg=self.accent, height=2)
        self.terminal_indicator.pack(fill="x")
        self.path_label = tk.Label(self.header, text=f"{self.shell.upper()}  ·  {self.cwd}", fg=self.muted_color, bg=self.background, anchor="w")
        self.path_label.grid(
            row=0, column=2, sticky="ew", pady=8, padx=(12, 6)
        )
        self.clear_button = tk.Button(
            self.header, text="清空", command=self._clear_output, relief="flat", borderwidth=0,
            bg=self.background, fg=self.muted_color, activebackground=self.accent_light, activeforeground=self.accent,
        )
        self.clear_button.grid(row=0, column=3, padx=(4, 6))
        self.retry_button = tk.Button(
            self.header, text="重试", command=self._restart_process, relief="flat", borderwidth=0, state="disabled",
            bg=self.background, fg=self.muted_color, activebackground=self.accent_light, activeforeground=self.accent,
        )
        self.retry_button.grid(row=0, column=4, padx=(0, 6))
        self.stop_button = tk.Button(
            self.header, text="停止", command=self._stop_process, relief="flat", borderwidth=0,
            bg=self.background, fg=self.muted_color, activebackground=self.accent_light, activeforeground=self.accent,
        )
        self.stop_button.grid(row=0, column=5, padx=(0, 10))

        self.output_shell = tk.Frame(self.window, bg=self.panel_background)
        self.output_shell.grid(row=1, column=0, sticky="nsew")
        self.output_shell.columnconfigure(0, weight=1)
        self.output_shell.rowconfigure(0, weight=1)
        self.output = tk.Text(
            self.output_shell, bg=self.panel_background, fg=self.text_color, insertbackground=self.text_color,
            selectbackground=self.accent_light, relief="flat", borderwidth=0, wrap="none",
            font=self.terminal_font, padx=12, pady=8,
        )
        self.scroll = tk.Scrollbar(self.output_shell, command=self._on_terminal_scrollbar)
        self.output.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.output.configure(state="disabled")
        self.output.tag_configure("terminal_symbol", font=self.terminal_symbol_font)

        self.output.bind("<KeyPress>", self._on_terminal_key)
        self.output.bind("<MouseWheel>", self._on_terminal_mousewheel)
        self.output.bind("<Button-4>", self._on_terminal_mousewheel)
        self.output.bind("<Button-5>", self._on_terminal_mousewheel)
        self.output.bind("<ButtonPress-1>", self._on_terminal_button_press, add="+")
        self.output.bind("<ButtonRelease-1>", self._on_terminal_button_release, add="+")
        self.output.bind("<Button-3>", self._show_terminal_context_menu)
        self.window.bind("<Button-1>", self._focus_terminal, add="+")
        self.output.bind("<Configure>", self._on_output_configure, add="+")
        self.apply_theme(self.palette)

        self.terminal_context_menu = tk.Menu(self.output, tearoff=False)
        self.terminal_context_menu.add_command(label="复制", command=self._copy_terminal_selection)
        self.terminal_context_menu.add_command(label="全选", command=self._select_all_terminal_text)

    def _focus_terminal(self, _event: Optional[tk.Event] = None) -> str:
        if self.visible:
            self.window.after_idle(self.output.focus_force)
        return ""

    def _terminal_has_selection(self) -> bool:
        try:
            return bool(self.output.tag_ranges("sel"))
        except tk.TclError:
            return False

    def _on_terminal_button_press(self, _event: tk.Event) -> str:
        self._mouse_selecting = True
        self._selection_frozen = True
        return self._focus_terminal()

    def _on_terminal_button_release(self, _event: tk.Event) -> str:
        self._mouse_selecting = False
        self.window.after_idle(self._finish_terminal_selection)
        return ""

    def _finish_terminal_selection(self) -> None:
        self._selection_frozen = self._terminal_has_selection()
        if not self._selection_frozen:
            self._render_terminal()

    def _copy_terminal_selection(self) -> bool:
        try:
            selected = self.output.get("sel.first", "sel.last")
        except tk.TclError:
            return False
        if not selected:
            return False
        self.window.clipboard_clear()
        self.window.clipboard_append(selected)
        self.window.update_idletasks()
        return True

    def _select_all_terminal_text(self) -> None:
        self.output.tag_add("sel", "1.0", "end-1c")
        self._selection_frozen = True
        self.output.focus_force()

    def _show_terminal_context_menu(self, event: tk.Event) -> str:
        copy_state = "normal" if self._terminal_has_selection() else "disabled"
        self.terminal_context_menu.entryconfigure("复制", state=copy_state)
        try:
            self.terminal_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.terminal_context_menu.grab_release()
        return "break"

    def _paste_terminal_clipboard(self) -> None:
        codex_active = is_codex_command(self.startup_command)
        if self.pty_process is not None and codex_active and windows_clipboard_has_image():
            # Codex reserves the Ctrl+V key event for reading an image from the
            # native clipboard and inserting an [Image #N] attachment.
            self._send_raw("\x16")
            return
        try:
            clipboard_text = self.window.clipboard_get()
        except tk.TclError:
            if self.pty_process is not None and codex_active:
                self._send_raw("\x16")
            return
        if not clipboard_text:
            return
        if self.pty_process is not None and codex_active:
            # Codex receives terminal text paste as a bracketed Paste event;
            # a raw Ctrl+V is intentionally image-only in the Codex TUI.
            self._send_raw(f"\x1b[200~{clipboard_text}\x1b[201~")
        else:
            self._send_raw(clipboard_text)

    def _on_terminal_mousewheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0:
            direction = -1
        else:
            direction = 1
        repeats = max(1, abs(int(getattr(event, "delta", 0))) // 120)
        first, last = self.output.yview()
        if direction < 0 and first > 0.0001:
            self._terminal_follow_output = False
            self.output.yview_scroll(-3 * repeats, "units")
            self._update_terminal_scrollbar()
            return "break"
        if direction > 0 and last < 0.9999:
            self.output.yview_scroll(3 * repeats, "units")
            first, last = self.output.yview()
            if last >= 0.9999 and self._terminal_history_at_bottom():
                self._terminal_follow_output = True
            self._update_terminal_scrollbar()
            return "break"
        if self.screen is None or pyte is None or not isinstance(self.screen, pyte.HistoryScreen):
            self.output.yview_scroll(3 * direction * repeats, "units")
            self._update_terminal_scrollbar()
            return "break"
        self._terminal_follow_output = direction > 0 and self._terminal_history_at_bottom()
        self._scroll_terminal_history(direction, repeats)
        if direction < 0:
            self._terminal_follow_output = False
        elif self._terminal_history_at_bottom():
            self._terminal_follow_output = True
        return "break"

    def _terminal_history_at_bottom(self) -> bool:
        if self.screen is None or pyte is None or not isinstance(self.screen, pyte.HistoryScreen):
            return True
        return self.screen.history.position >= self.screen.history.size

    def _on_terminal_scrollbar(self, *args: str) -> None:
        if self.screen is None or pyte is None or not isinstance(self.screen, pyte.HistoryScreen):
            self.output.yview(*args)
            return
        if not args:
            return
        if not self.screen.history.top and not self.screen.history.bottom:
            self.output.yview(*args)
            self._terminal_follow_output = self.output.yview()[1] >= 0.9999
            self._update_terminal_scrollbar()
            return
        if args[0] == "scroll" and len(args) >= 2:
            count = int(args[1])
            self._scroll_terminal_history(-1 if count < 0 else 1, max(1, abs(count)))
            return
        if args[0] == "moveto" and len(args) >= 2:
            target = min(max(float(args[1]), 0.0), 1.0)
            history = self.screen.history
            total_history = len(history.top) + len(history.bottom)
            target_before = round(target * total_history)
            for _ in range(600):
                before = len(self.screen.history.top)
                if abs(before - target_before) <= max(1, int(self.screen.lines * self.screen.history.ratio)):
                    break
                if before > target_before:
                    self.screen.prev_page()
                else:
                    self.screen.next_page()
            self._render_terminal()

    def _scroll_terminal_history(self, direction: int, repeats: int = 1) -> None:
        if self.screen is None or pyte is None or not isinstance(self.screen, pyte.HistoryScreen):
            return
        for _ in range(repeats):
            if direction < 0:
                self.screen.prev_page()
            else:
                self.screen.next_page()
        self._render_terminal()

    def _update_terminal_scrollbar(self) -> None:
        if self.screen is None or pyte is None or not isinstance(self.screen, pyte.HistoryScreen):
            self.scroll.set(*self.output.yview())
            return
        before = len(self.screen.history.top)
        after = len(self.screen.history.bottom)
        total = before + self.screen.lines + after
        if not before and not after:
            self.scroll.set(*self.output.yview())
            return
        self.scroll.set(before / total, (before + self.screen.lines) / total)

    def apply_theme(self, palette: dict[str, str]) -> None:
        self.palette = dict(palette)
        self.background = self.palette["bg"]
        self.panel_background = self.palette["panel"]
        self.border = self.palette["border"]
        self.text_color = self.palette["text"]
        self.muted_color = self.palette["muted"]
        self.accent = self.palette["accent"]
        self.accent_light = self.palette["accent_light"]
        self.window.configure(bg=self.panel_background, highlightbackground=self.border)
        self.header.configure(bg=self.background)
        self.terminal_tab.configure(bg=self.panel_background)
        self.output_shell.configure(bg=self.panel_background)
        self.output_title.configure(bg=self.background, fg=self.muted_color)
        self.terminal_title.configure(bg=self.panel_background, fg=self.accent)
        self.terminal_indicator.configure(bg=self.accent)
        self.path_label.configure(bg=self.background, fg=self.muted_color)
        for button in (self.clear_button, self.retry_button, self.stop_button):
            button.configure(
                bg=self.background,
                fg=self.muted_color,
                activebackground=self.accent_light,
                activeforeground=self.accent,
            )
        self.output.configure(
            bg=self.panel_background,
            fg=self.text_color,
            insertbackground=self.text_color,
            selectbackground=self.accent_light,
        )
        self.scroll.configure(
            bg=self.palette["control"],
            troughcolor=self.panel_background,
            activebackground=self.accent_light,
            highlightbackground=self.border,
        )

    def _on_output_configure(self, _event: tk.Event) -> None:
        if not self._resize_pending:
            self._resize_pending = True
            self.window.after_idle(self._sync_terminal_size)

    def mount(self) -> None:
        parent = self.window.master
        if str(self.window) not in parent.panes():
            parent.add(self.window, minsize=280, stretch="always")
        self.visible = True
        self.window.after(80, self._place_initial_sash)
        self.window.after(100, self._focus_terminal)

    def _place_initial_sash(self) -> None:
        parent = self.window.master
        if len(parent.panes()) < 2:
            return
        if self.dock_position == "right":
            available_width = max(parent.winfo_width(), 600)
            terminal_width = min(self.preferred_width, max(300, int(available_width * 0.48)))
            sash_x = max(280, available_width - terminal_width)
            parent.sash_place(0, sash_x, 0)
        else:
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
        if is_codex_command(self.startup_command) and self.codex_prompt:
            self._begin_codex_bootstrap()
        try:
            self.cwd.mkdir(parents=True, exist_ok=True)
            command, terminal_environment = terminal_process_spec(self.shell)
            command_text = subprocess.list2cmdline(command)
            if PtyProcess is not None:
                self.pty_process = PtyProcess.spawn(
                    command_text,
                    cwd=str(self.cwd),
                    env=terminal_environment,
                    dimensions=(self.terminal_rows, self.terminal_columns),
                )
                threading.Thread(target=self._read_pty_output, args=(self.pty_process,), daemon=True).start()
            else:
                self.process = subprocess.Popen(
                    command,
                    cwd=str(self.cwd),
                    env=terminal_environment,
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
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while process.isalive():
            try:
                # pywinpty.read() keeps reading when a UTF-8 codepoint straddles
                # two pipe packets. Bypassing it and decoding recv() directly
                # can turn valid Codex box-drawing updates into U+FFFD.
                chunk = process.read(4096)
            except (EOFError, OSError, WinptyError):
                break
            if not chunk:
                break
            if chunk == b"0011Ignore":
                continue
            chunk = decode_terminal_chunk(decoder, chunk)
            if not chunk:
                continue
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
            if self._codex_bootstrap_active and not self._codex_bootstrap_complete:
                self._show_codex_bootstrap_error(f"Codex 准备失败（终端退出代码 {code}）。")
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

    def _begin_codex_bootstrap(self) -> None:
        self._codex_bootstrap_generation += 1
        generation = self._codex_bootstrap_generation
        self._codex_bootstrap_active = True
        self._codex_bootstrap_complete = False
        self._codex_bootstrap_timed_out = False
        self._codex_bootstrap_error = ""
        self.retry_button.configure(state="disabled")
        self._render_terminal()
        self.window.after(CODEX_BOOTSTRAP_TIMEOUT_MS, self._mark_codex_bootstrap_timeout, generation)

    def _mark_codex_bootstrap_timeout(self, generation: int) -> None:
        if generation != self._codex_bootstrap_generation:
            return
        if not self._codex_bootstrap_active or self._codex_bootstrap_complete:
            return
        self._show_codex_bootstrap_error("Codex 准备超时，请检查网络或登录状态后重试。")

    def _show_codex_bootstrap_error(self, message: str) -> None:
        self._codex_bootstrap_timed_out = True
        self._codex_bootstrap_error = message
        self.retry_button.configure(state="normal")
        self._render_terminal()

    def _mask_codex_bootstrap(
        self, lines: list[str], cursor_y: int
    ) -> tuple[list[str], Optional[int]]:
        marker_index = next((index for index, line in enumerate(lines) if CODEX_BOOTSTRAP_MARKER in line), None)
        if marker_index is not None:
            self._codex_bootstrap_complete = True
            self._codex_bootstrap_timed_out = False
            self._codex_bootstrap_error = ""
            self.retry_button.configure(state="disabled")
            visible_lines = ["Codex 已准备完成。"] + lines[marker_index + 1 :]
            visible_cursor_y = cursor_y - marker_index if cursor_y > marker_index else None
            return visible_lines, visible_cursor_y
        if self._codex_bootstrap_complete:
            self._codex_bootstrap_active = False
            return lines, cursor_y
        if self._codex_bootstrap_timed_out:
            return [self._codex_bootstrap_error, "点击右上角“重试”重新启动。"], None
        return ["Codex 正在准备，请稍候…"], None

    def _render_terminal(self) -> None:
        self._render_pending = False
        if self._closing or self.screen is None or not self.window.winfo_exists():
            return
        if self._mouse_selecting or (self._selection_frozen and self._terminal_has_selection()):
            return
        previous_top = self.output.yview()[0] if self.output.winfo_exists() else 0.0
        lines = list(self.screen.display)
        cursor = self.screen.cursor
        cursor_y: Optional[int] = cursor.y
        if self._codex_bootstrap_active:
            lines, cursor_y = self._mask_codex_bootstrap(lines, cursor.y)
        if cursor_y is not None and 0 <= cursor_y < len(lines):
            line = lines[cursor_y]
            cursor_index = terminal_column_to_text_index(line, cursor.x)
            if cursor_index < len(line):
                lines[cursor_y] = f"{line[:cursor_index]}▌{line[cursor_index + 1:]}"
            else:
                lines[cursor_y] = f"{line}▌"
        rendered = "\n".join(line.rstrip() for line in lines).rstrip()
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        if rendered:
            self.output.insert("1.0", rendered)
            for start, end in terminal_symbol_ranges(rendered):
                self.output.tag_add("terminal_symbol", f"1.0+{start}c", f"1.0+{end}c")
        if self._terminal_follow_output:
            self.output.see("end")
        else:
            self.output.yview_moveto(previous_top)
        self.output.configure(state="disabled")
        self._update_terminal_scrollbar()

    def _send_line(self, line: str, detect_codex: bool = True) -> None:
        if self.pty_process is None and self.process is None:
            self._start_process()
        if detect_codex and is_codex_command(line) and self.codex_prompt:
            if not self._codex_bootstrap_active:
                self._begin_codex_bootstrap()
            line = f"{line} {quote_terminal_argument(self.codex_prompt, self.shell)}"
        try:
            if self.pty_process is not None:
                self.pty_process.write(line + "\r\n")
            elif self.process is not None and self.process.stdin is not None:
                self.process.stdin.write(line + "\n")
                self.process.stdin.flush()
        except (OSError, ValueError):
            self._append_output("\n[无法向终端发送命令]\n")
            return

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
        if self._codex_bootstrap_active and not self._codex_bootstrap_complete:
            return "break"
        self._terminal_follow_output = True

        control_pressed = bool(event.state & MOD_CONTROL)
        shift_pressed = bool(event.state & MOD_SHIFT)
        key = event.keysym.lower()

        if control_pressed and shift_pressed and key == "c":
            self._copy_terminal_selection()
            self._selection_frozen = self._terminal_has_selection()
            return "break"

        if control_pressed and key == "c":
            if self._copy_terminal_selection():
                self._selection_frozen = True
            else:
                self._send_raw("\x03")
            return "break"

        if control_pressed and event.keysym == "Insert":
            self._copy_terminal_selection()
            self._selection_frozen = self._terminal_has_selection()
            return "break"

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

        if (control_pressed and key == "v") or (shift_pressed and event.keysym == "Insert"):
            self._paste_terminal_clipboard()
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
            if self._codex_bootstrap_active and not self._codex_bootstrap_complete:
                self._show_codex_bootstrap_error("Codex 准备已停止。")
            return
        process = self.process
        if process is None:
            return
        try:
            process.terminate()
        except OSError:
            pass
        self.process = None

    def _restart_process(self) -> None:
        self._codex_bootstrap_generation += 1
        self._stop_process()
        if self.screen is not None:
            self.screen.reset()
        else:
            self.output.configure(state="normal")
            self.output.delete("1.0", "end")
            self.output.configure(state="disabled")
        self.window.after(250, self._start_process)

    def hide(self) -> None:
        if self.dock_position == "right":
            self.preferred_width = max(280, self.window.winfo_width())
        else:
            self.preferred_height = max(160, self.window.winfo_height())
        self.visible = False
        self.window.master.forget(self.window)

    def show(self) -> None:
        if self.pty_process is None and self.process is None:
            self._start_process()
        self.visible = True
        if str(self.window) not in self.window.master.panes():
            self.window.master.add(self.window, minsize=280, stretch="always")
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
        self.drop_target_index: Optional[int] = None
        self.explorer_reveal_armed = False
        self.explorer_reveal_shortcut_down = False
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
        bundled_database_dir = ROOT / DATABASE_DIR
        if not any(DB_DIR.glob("*.json")) and bundled_database_dir.resolve() != DB_DIR.resolve():
            for source in bundled_database_dir.glob("*.json"):
                destination = DB_DIR / source.name
                if not destination.exists():
                    shutil.copy2(source, destination)
        if not any(DB_DIR.glob("*.json")):
            write_json_file(DB_DIR / DEFAULT_DB, SAMPLE_DATA)

    def _configure_style(self) -> None:
        self.palette = theme_palette(self.settings.get("theme"))
        self.root._theme_palette = self.palette
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        bg = self.palette["bg"]
        panel = self.palette["panel"]
        text = self.palette["text"]
        muted = self.palette["muted"]
        accent = self.palette["accent"]
        control = self.palette["control"]
        border = self.palette["border"]
        self.root.configure(bg=bg)
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=bg)
        style.configure("Panel.TFrame", background=panel)
        style.configure("TLabel", background=bg, foreground=text)
        style.configure("Panel.TLabel", background=panel, foreground=text)
        style.configure("Muted.TLabel", background=bg, foreground=muted)
        style.configure("PanelMuted.TLabel", background=panel, foreground=muted)
        style.configure("TButton", background=control, foreground=text, bordercolor=border, padding=(8, 5))
        style.map("TButton", background=[("active", self.palette["accent_light"])])
        style.configure("Accent.TButton", padding=(10, 6), foreground=self.palette["selected_text"], background=accent)
        style.map("Accent.TButton", background=[("active", self.palette["accent_hover"])])
        style.configure("Danger.TButton", padding=(10, 6), foreground=self.palette["danger"], background=control)
        style.configure("TCheckbutton", background=bg, foreground=text)
        style.map("TCheckbutton", background=[("active", bg)], foreground=[("active", text)])
        style.configure("TEntry", fieldbackground=self.palette["input"], foreground=text, insertcolor=text, bordercolor=border)
        style.configure("TCombobox", fieldbackground=self.palette["input"], background=control, foreground=text, arrowcolor=text, bordercolor=border)
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.palette["input"])],
            foreground=[("readonly", text)],
            selectbackground=[("readonly", self.palette["input"])],
            selectforeground=[("readonly", text)],
        )
        style.configure("TNotebook", background=bg, bordercolor=border)
        style.configure("TNotebook.Tab", background=control, foreground=text, padding=(12, 7))
        style.map("TNotebook.Tab", background=[("selected", panel)], foreground=[("selected", accent)])
        style.configure("Vertical.TScrollbar", background=control, troughcolor=panel, bordercolor=border, arrowcolor=text)
        self.root.option_add("*TCombobox*Listbox.background", self.palette["input"])
        self.root.option_add("*TCombobox*Listbox.foreground", text)

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
            orient=(
                "horizontal"
                if normalize_terminal_position(self.settings.get("terminal_position")) == "right"
                else "vertical"
            ),
            bg=self.palette["border"],
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

        self.quick_canvas = tk.Canvas(quick_shell, borderwidth=0, highlightthickness=0, bg=self.palette["panel"])
        self.quick_scroll = ttk.Scrollbar(quick_shell, orient="vertical", command=self.quick_canvas.yview)
        self.quick_frame = tk.Frame(self.quick_canvas, bg=self.palette["panel"])
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
        menu_options = {
            "bg": self.palette["panel"],
            "fg": self.palette["text"],
            "activebackground": self.palette["accent_light"],
            "activeforeground": self.palette["text"],
        }
        menubar = tk.Menu(self.root, tearoff=False, **menu_options)
        settings_menu = tk.Menu(menubar, tearoff=False, **menu_options)
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
            if self.explorer_reveal_shortcut_down:
                return "break"
            self.explorer_reveal_shortcut_down = True
            return self._arm_explorer_reveal()
        if shortcut == self.shortcuts["terminal_toggle"]:
            self.toggle_terminal()
            return "break"
        if shortcut == self.shortcuts["add_item"]:
            self.add_item()
            return "break"
        if shortcut == self.shortcuts["edit_item"]:
            self.edit_selected()
            return "break"
        if shortcut == self.shortcuts["move_left"]:
            return self._on_ctrl_arrow(-1)
        if shortcut == self.shortcuts["move_right"]:
            return self._on_ctrl_arrow(1)
        if shortcut == self.shortcuts["move_group_up"]:
            return self._on_ctrl_group_arrow(-1)
        if shortcut == self.shortcuts["move_group_down"]:
            return self._on_ctrl_group_arrow(1)
        return ""

    def _is_configured_shortcut(self, event: tk.Event) -> bool:
        return shortcut_from_event(event) in set(self.shortcuts.values())

    def _arm_explorer_reveal(self) -> str:
        self.explorer_reveal_armed = not self.explorer_reveal_armed
        if self.explorer_reveal_armed:
            self.status_var.set("资源管理器定位模式已启用：下一次点击文件或文件夹条目会在资源管理器中定位。再次按快捷键可取消。")
        else:
            self.status_var.set("资源管理器定位模式已取消。Ctrl+Shift+点击将按默认方式打开资源。")
        return "break"

    def _on_global_key_release(self, event: tk.Event) -> None:
        trigger_key = self.shortcuts["explorer_reveal"].split("+")[-1]
        released_key = normalize_shortcut(str(event.keysym or "")).split("+")[-1]
        if released_key == trigger_key:
            self.explorer_reveal_shortcut_down = False

    def _on_ctrl_arrow(self, direction: int) -> str:
        focused = self.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text, ttk.Entry)):
            return ""
        self.move_selected_within_group(direction)
        return "break"

    def _on_ctrl_group_arrow(self, direction: int) -> str:
        self.move_selected_group(direction)
        return "break"

    def _load_settings(self) -> dict:
        defaults = default_settings()
        settings_source = SETTINGS_PATH
        bundled_settings = ROOT / SETTINGS_FILE
        if not settings_source.exists() and DATA_ROOT != ROOT and bundled_settings.exists():
            settings_source = bundled_settings
        if not settings_source.exists():
            return defaults
        try:
            with settings_source.open("r", encoding="utf-8") as f:
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
        self.settings["terminal_position"] = normalize_terminal_position(
            self.settings.get("terminal_position")
        )
        self.settings["terminal_font"] = normalize_terminal_font(self.settings.get("terminal_font"))
        self.settings["terminal_font_size"] = normalize_terminal_font_size(
            self.settings.get("terminal_font_size")
        )
        self.settings["theme"] = normalize_theme(self.settings.get("theme"))
        self.settings["current_db"] = self.current_db
        try:
            with SETTINGS_PATH.open("w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as exc:
            self.status_var.set(f"设置保存失败：{exc}")

    def open_settings(self) -> None:
        previous_theme = normalize_theme(self.settings.get("theme"))
        previous_terminal = (
            self.settings.get("terminal_shell"),
            self.settings.get("terminal_cwd"),
            self.settings.get("terminal_command"),
            normalize_terminal_position(self.settings.get("terminal_position")),
            resolve_terminal_font(self.root, self.settings.get("terminal_font")),
            normalize_terminal_font_size(self.settings.get("terminal_font_size")),
        )
        dialog = SettingsDialog(self.root, self.settings, topmost=bool(self.topmost_var.get()))
        if dialog.result is None:
            return
        self.settings.update(dialog.result)
        self.shortcuts = load_shortcuts(self.settings)
        theme_changed = normalize_theme(self.settings.get("theme")) != previous_theme
        current_terminal = (
            self.settings.get("terminal_shell"),
            self.settings.get("terminal_cwd"),
            self.settings.get("terminal_command"),
            normalize_terminal_position(self.settings.get("terminal_position")),
            resolve_terminal_font(self.root, self.settings.get("terminal_font")),
            normalize_terminal_font_size(self.settings.get("terminal_font_size")),
        )
        if self.terminal_panel is not None and previous_terminal != current_terminal:
            self.terminal_panel.close()
            self.terminal_panel = None
        self.content_pane.configure(
            orient="horizontal" if current_terminal[3] == "right" else "vertical"
        )
        if theme_changed:
            self._configure_style()
            self._build_menu()
            self.content_pane.configure(bg=self.palette["border"])
            self.quick_canvas.configure(bg=self.palette["panel"])
            self.quick_frame.configure(bg=self.palette["panel"])
            if self.drag_ghost_label is not None:
                self.drag_ghost_label.configure(bg=self.palette["accent_light"], fg=self.palette["text"])
            if self.terminal_panel is not None:
                self.terminal_panel.apply_theme(self.palette)
            self.refresh_items()
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
            palette=self.palette,
            dock_position=normalize_terminal_position(self.settings.get("terminal_position")),
            font_family=normalize_terminal_font(self.settings.get("terminal_font")),
            font_size=normalize_terminal_font_size(self.settings.get("terminal_font_size")),
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
                bg=self.palette["panel"],
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
                    palette=self.palette,
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
            fill=self.palette["panel"],
            outline=self.palette["accent"] if group == self.drop_target_group else self.palette["group_border"],
            width=2 if group == self.drop_target_group else 1,
            tags=("group-border",),
        )
        title = truncate_text(group, 22)
        title_width = self.chip_font.measure(title) + 18
        canvas.create_rectangle(
            12, 3, 12 + title_width, 21,
            fill=self.palette["panel"], outline=self.palette["panel"],
        )
        canvas.create_text(
            20, 12, anchor="w", text=title,
            fill=self.palette["text"], font=("Microsoft YaHei UI", 9, "bold"),
        )

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

    def _drop_slot(self, group: str, dragged_key: str, x: int, y: int) -> tuple[list[str], int]:
        visible_keys = [
            item_key
            for item_key in self.item_order
            if item_key != dragged_key
            and self.group_by_key.get(item_key) == group
            and item_key in self.chips
        ]
        rectangles: list[tuple[str, int, int, int, int]] = []
        for item_key in visible_keys:
            chip = self.chips[item_key]
            if not chip.winfo_exists() or not chip.winfo_ismapped():
                continue
            left = chip.winfo_rootx()
            top = chip.winfo_rooty()
            rectangles.append((item_key, left, top, left + chip.winfo_width(), top + chip.winfo_height()))
        rectangle_keys = {rectangle[0] for rectangle in rectangles}
        visible_keys = [item_key for item_key in visible_keys if item_key in rectangle_keys]
        return visible_keys, compute_drop_index(rectangles, x, y)

    def _move_item_to_slot(
        self, key: str, target_group: str, visible_keys: list[str], insert_at: int
    ) -> bool:
        if key not in self.data:
            return False
        old_order = list(self.item_order)
        old_group = normalize_group_name(self.group_by_key.get(key) or infer_group_name(key))
        target_group = normalize_group_name(target_group)
        new_order = [item_key for item_key in self.item_order if item_key != key]
        anchors = [item_key for item_key in visible_keys if item_key in new_order]
        insert_at = max(0, min(insert_at, len(anchors)))
        if anchors and insert_at < len(anchors):
            global_index = new_order.index(anchors[insert_at])
        elif anchors:
            global_index = new_order.index(anchors[-1]) + 1
        else:
            target_keys = [
                item_key for item_key in new_order if self.group_by_key.get(item_key) == target_group
            ]
            global_index = new_order.index(target_keys[-1]) + 1 if target_keys else len(new_order)
        new_order.insert(global_index, key)
        if new_order == old_order and old_group == target_group:
            return False
        self.item_order = new_order
        self.group_by_key[key] = target_group
        if target_group not in self.group_order:
            self.group_order.append(target_group)
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

    def move_selected_group(self, direction: int) -> None:
        selected = self._ordered_selected_keys()
        if not selected:
            self.status_var.set("请先选择目标分组中的一个条目，再调整分组顺序。")
            return

        groups = {
            normalize_group_name(self.group_by_key.get(key) or infer_group_name(key))
            for key in selected
        }
        if len(groups) != 1:
            self.status_var.set("当前条目来自多个分组，请只选择同一分组中的条目。")
            return

        self._normalize_group_state()
        group = next(iter(groups))
        if group not in self.group_order:
            self.status_var.set(f"未找到分组“{group}”。")
            return

        current_index = self.group_order.index(group)
        target_index = current_index + (1 if direction > 0 else -1)
        if target_index < 0 or target_index >= len(self.group_order):
            direction_label = "下" if direction > 0 else "上"
            self.status_var.set(f"分组“{group}”已经在最{direction_label}方。")
            return

        self.group_order[current_index], self.group_order[target_index] = (
            self.group_order[target_index],
            self.group_order[current_index],
        )
        self.save_database_to_disk()
        self.refresh_items()
        direction_label = "下" if direction > 0 else "上"
        self.status_var.set(f"已将分组“{group}”向{direction_label}移动一格。")

    def _set_drop_target_group(self, group: Optional[str]) -> None:
        group = normalize_group_name(group) if group else None
        if group == self.drop_target_group:
            return
        self.drop_target_group = group
        for canvas_group, canvas in self.group_canvases.items():
            if canvas.winfo_exists():
                canvas.itemconfigure(
                    "group-border",
                    outline=self.palette["accent"] if canvas_group == group else self.palette["group_border"],
                    width=2 if canvas_group == group else 1,
                )

    def _set_drop_target_item(self, key: Optional[str]) -> None:
        self.drop_target_item = key
        for item_key, chip in self.chips.items():
            if chip.winfo_exists():
                chip.set_drop_target(item_key == key)

    def _clear_drop_insertion(self) -> None:
        for canvas in self.group_canvases.values():
            if canvas.winfo_exists():
                canvas.delete("drop-insertion")

    def _draw_drop_insertion(self, group: str, visible_keys: list[str], insert_at: int) -> None:
        self._clear_drop_insertion()
        canvas = self.group_canvases.get(group)
        if canvas is None or not canvas.winfo_exists():
            return
        anchors = [item_key for item_key in visible_keys if item_key in self.chips]
        if not anchors:
            line_x, line_top, line_bottom = 16, 34, 68
        else:
            insert_at = max(0, min(insert_at, len(anchors)))
            anchor_key = anchors[insert_at] if insert_at < len(anchors) else anchors[-1]
            chip = self.chips[anchor_key]
            line_x = chip.winfo_x() - 4 if insert_at < len(anchors) else chip.winfo_x() + chip.winfo_width() + 4
            line_top = chip.winfo_y() + 2
            line_bottom = chip.winfo_y() + chip.winfo_height() - 2
        color = self.palette["accent"]
        canvas.create_line(
            line_x, line_top, line_x, line_bottom,
            fill=color, width=3, capstyle=tk.ROUND, tags=("drop-insertion",),
        )
        canvas.create_oval(
            line_x - 2, line_top - 2, line_x + 2, line_top + 2,
            fill=color, outline=color, tags=("drop-insertion",),
        )
        canvas.create_oval(
            line_x - 2, line_bottom - 2, line_x + 2, line_bottom + 2,
            fill=color, outline=color, tags=("drop-insertion",),
        )
        canvas.tag_raise("drop-insertion")

    def update_drag_preview(self, key: str, x: int, y: int, visible: bool) -> None:
        if not visible:
            self._set_drop_target_group(None)
            self._set_drop_target_item(None)
            self.drop_target_index = None
            self._clear_drop_insertion()
            if self.drag_ghost is not None:
                self.drag_ghost.withdraw()
            return
        target_group = self._group_at_point(x, y)
        visible_keys: list[str] = []
        insert_at: Optional[int] = None
        target_item: Optional[str] = None
        if target_group:
            visible_keys, insert_at = self._drop_slot(target_group, key, x, y)
            target_item = visible_keys[insert_at] if insert_at < len(visible_keys) else None
        self._set_drop_target_group(target_group)
        self._set_drop_target_item(target_item)
        self.drop_target_index = insert_at
        if target_group and insert_at is not None:
            self._draw_drop_insertion(target_group, visible_keys, insert_at)
        else:
            self._clear_drop_insertion()
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
                bg=self.palette["accent_light"],
                fg=self.palette["text"],
                bd=1,
                relief="solid",
                padx=10,
                pady=5,
                font=("Microsoft YaHei UI", 9),
            )
            self.drag_ghost_label.pack()
        if self.drag_ghost_label is not None:
            target_hint = ""
            if target_group and insert_at is not None:
                if insert_at < len(visible_keys):
                    target_hint = f" → {truncate_text(visible_keys[insert_at], 16)}前"
                elif visible_keys:
                    target_hint = f" → {truncate_text(visible_keys[-1], 16)}后"
                else:
                    target_hint = f" → {target_group}"
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

        menu_options = {
            "bg": self.palette["panel"],
            "fg": self.palette["text"],
            "activebackground": self.palette["accent_light"],
            "activeforeground": self.palette["text"],
        }
        menu = tk.Menu(self.root, tearoff=False, **menu_options)
        item_type = normalize_item_type(self.item_type_by_key.get(key))
        is_resource = item_type in {ITEM_TYPE_LINK, ITEM_TYPE_FILE, ITEM_TYPE_FOLDER}
        resource_path = self._local_resource_path(key, warn=False) if is_resource else None
        if is_resource:
            menu.add_command(label="打开（系统默认方式）", command=lambda: self.open_item_resource(key))
            if resource_path is not None:
                menu.add_command(label="打开文件夹", command=lambda: self.open_resource_folder(key))
                open_with_menu = tk.Menu(menu, tearoff=False, **menu_options)
                handlers = safe_enumerate_open_with_handlers(resource_path)
                if handlers:
                    for label, command_template in handlers:
                        open_with_menu.add_command(
                            label=label,
                            command=lambda template=command_template: self.open_resource_with(key, template),
                        )
                else:
                    open_with_menu.add_command(label="未找到已注册的应用", state="disabled")
                open_with_menu.add_separator()
                open_with_menu.add_command(label="选择其他应用…", command=lambda: self.choose_resource_app(key))
                menu.add_cascade(label="打开方式", menu=open_with_menu)
            menu.add_separator()
        menu.add_command(label="编辑", command=self.edit_selected)
        menu.add_command(label="复制", command=lambda: self.copy_item(key))
        menu.add_command(label="分组", command=self.change_group_selected)
        menu.add_separator()
        menu.add_command(label="删除", command=self.delete_selected)
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _local_resource_path(self, key: str, warn: bool = True) -> Optional[Path]:
        if key not in self.data:
            return None
        value = self.data[key].strip()
        if re.match(r"^(https?|ftp|mailto):", value, re.IGNORECASE):
            return None
        try:
            path = Path(os.path.expandvars(os.path.expanduser(value)))
            if not path.is_absolute():
                path = ROOT / path
            path = path.resolve()
        except (OSError, ValueError) as exc:
            if warn:
                messagebox.showerror("资源路径无效", str(exc), parent=self.root)
            return None
        if not path.exists():
            if warn:
                messagebox.showwarning("资源不存在", f"找不到本地资源：\n{path}", parent=self.root)
            return None
        return path

    def open_resource_folder(self, key: str) -> None:
        resource_path = self._local_resource_path(key)
        if resource_path is None:
            return
        try:
            if resource_path.is_dir():
                os.startfile(str(resource_path), "open")
            else:
                subprocess.Popen(["explorer.exe", f"/select,{resource_path}"])
            self.status_var.set(f"已打开资源所在文件夹：{key}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("打开文件夹失败", str(exc), parent=self.root)

    def open_resource_with(self, key: str, command_template: list[str]) -> None:
        resource_path = self._local_resource_path(key)
        if resource_path is None:
            return
        try:
            command = build_open_with_argv(command_template, resource_path)
            subprocess.Popen(command, cwd=str(resource_path.parent if resource_path.is_file() else resource_path))
            self.status_var.set(f"已使用 {Path(command[0]).stem} 打开：{key}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("指定应用打开失败", str(exc), parent=self.root)

    def choose_resource_app(self, key: str) -> None:
        resource_path = self._local_resource_path(key)
        if resource_path is None:
            return
        try:
            try:
                os.startfile(str(resource_path), "openas")
            except OSError:
                subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", str(resource_path)])
            self.status_var.set(f"请选择用于打开“{key}”的应用。")
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法显示打开方式", str(exc), parent=self.root)

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
        if is_resource and self.explorer_reveal_armed:
            self.explorer_reveal_armed = False
            self.open_item_resource(key, reveal_in_explorer=True)
            return
        if has_ctrl and has_shift:
            self.open_item_resource(key, reveal_in_explorer=False)
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
        self._set_drop_target_item(None)
        self._clear_drop_insertion()
        if target_group:
            current_group = normalize_group_name(self.group_by_key.get(key) or infer_group_name(key))
            visible_keys, insert_at = self._drop_slot(target_group, key, x, y)
            changed = self._move_item_to_slot(key, target_group, visible_keys, insert_at)
            if changed and current_group == target_group:
                self.status_var.set(f"已在分组“{target_group}”内调整：{key}")
            elif changed:
                self.status_var.set(f"已将“{key}”拖动到分组“{target_group}”的指定位置。")
            else:
                self.status_var.set(f"{key} 在分组“{target_group}”内的位置未改变。")
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

            resource_path = self._local_resource_path(key)
            if resource_path is None:
                return
            if reveal_in_explorer:
                self.open_resource_folder(key)
                return
            else:
                try:
                    os.startfile(str(resource_path), "open")
                except OSError as exc:
                    if getattr(exc, "winerror", None) == 1155:
                        self.choose_resource_app(key)
                        return
                    raise
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
    try:
        QuickTextApp(root)
    except Exception as exc:
        messagebox.showerror(
            "程序无法启动",
            f"无法初始化程序数据目录：\n{DATA_ROOT}\n\n{exc}",
            parent=root,
        )
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()

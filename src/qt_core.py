from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable, Optional
import webbrowser

try:
    import winreg
except ImportError:  # pragma: no cover - this application targets Windows
    winreg = None


APP_NAME = "投递文本助手"
DATABASE_DIR = "databases"
SETTINGS_FILE = "app_settings.json"
DEFAULT_DB = "默认投递资料.json"
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

DEFAULT_SHORTCUTS = {
    "terminal_toggle": "ctrl+j",
    "add_item": "ctrl+n",
    "edit_item": "ctrl+e",
    "move_left": "ctrl+left",
    "move_right": "ctrl+right",
    "move_group_up": "ctrl+up",
    "move_group_down": "ctrl+down",
    "explorer_reveal": "ctrl+shift+e",
    "search_items": "ctrl+f",
    "replace_item_names": "ctrl+r",
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
    "search_items": "搜索条目",
    "replace_item_names": "查找并替换条目名称",
}
THEME_LABELS = {
    "light": "明亮蓝",
    "soft_gray": "柔和灰",
    "jetbrains_gray": "JetBrains 灰色",
}
TERMINAL_POSITION_LABELS = {"right": "右侧", "bottom": "底部"}
CODEX_BOOTSTRAP_MARKER = "RS_READY_7C2A"
DEFAULT_TERMINAL_FONT = "Cascadia Mono"
DEFAULT_TERMINAL_FONT_SIZE = 11
TERMINAL_FONT_CANDIDATES = (
    "Cascadia Mono",
    "Cascadia Code",
    "JetBrains Mono",
    "Consolas",
    "Lucida Console",
    "Courier New",
)

THEME_PALETTES = {
    "light": {
        "bg": "#f4f6f9", "panel": "#ffffff", "input": "#ffffff", "control": "#edf1f6",
        "text": "#20242b", "muted": "#68707c", "accent": "#2563eb", "accent_hover": "#1d4ed8",
        "accent_light": "#dbeafe", "border": "#d4dae3", "group_border": "#d7dde6",
        "chip": "#eef3ff", "chip_border": "#c9d6f5", "chip_hover": "#dfe9ff",
        "selected_text": "#ffffff", "danger": "#b42318", "terminal": "#fbfcfe",
        "terminal_text": "#1f2937", "attachment": "#eef4ff",
    },
    "soft_gray": {
        "bg": "#e7e9ec", "panel": "#f4f5f7", "input": "#ffffff", "control": "#dfe3e7",
        "text": "#2f3337", "muted": "#687078", "accent": "#596f84", "accent_hover": "#465c70",
        "accent_light": "#d4dbe2", "border": "#b8c0c8", "group_border": "#c5cbd1",
        "chip": "#e2e6ea", "chip_border": "#bec6ce", "chip_hover": "#d3d9df",
        "selected_text": "#ffffff", "danger": "#9b3a3a", "terminal": "#f7f7f7",
        "terminal_text": "#292d32", "attachment": "#e1e5e9",
    },
    "jetbrains_gray": {
        "bg": "#2b2d30", "panel": "#1e1f22", "input": "#2b2d30", "control": "#393b40",
        "text": "#bcbec4", "muted": "#8b8d92", "accent": "#3574f0", "accent_hover": "#2f65ca",
        "accent_light": "#2f415f", "border": "#43454a", "group_border": "#4e5157",
        "chip": "#393b40", "chip_border": "#4e5157", "chip_hover": "#434b55",
        "selected_text": "#ffffff", "danger": "#ff6b68", "terminal": "#1e1f22",
        "terminal_text": "#d9dce1", "attachment": "#30343b",
    },
}


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    source_dir = Path(__file__).resolve().parent
    # Runtime modules live in project_root/src, while editable databases,
    # settings, documentation and tmp deliberately remain in project_root.
    return source_dir.parent if source_dir.name.lower() == "src" else source_dir


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
        candidate = Path(os.path.expandvars(os.path.expanduser(override))).resolve()
    else:
        candidate = application_dir
    if _directory_is_writable(candidate):
        return candidate
    local = Path(os.environ.get("LOCALAPPDATA", application_dir)) / "ResumeQuickPaste"
    return local if _directory_is_writable(local) else application_dir


ROOT = app_root()
DATA_ROOT = app_data_root(ROOT)
DB_DIR = DATA_ROOT / DATABASE_DIR
SETTINGS_PATH = DATA_ROOT / SETTINGS_FILE
PROJECT_ROOT = ROOT.parent if getattr(sys, "frozen", False) and ROOT.name.lower() == "release" else ROOT


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
        "window_width": 1240,
        "window_height": 720,
        "terminal_width": 520,
        "terminal_height": 300,
    }


def normalize_shortcut(value: object) -> str:
    text = str(value or "").strip().lower().replace("control", "ctrl")
    text = text.replace(" ", "")
    aliases = {"prior": "pageup", "next": "pagedown", "return": "enter"}
    parts = [aliases.get(part, part) for part in text.split("+") if part]
    modifiers = [name for name in ("ctrl", "alt", "shift", "meta") if name in parts]
    keys = [part for part in parts if part not in modifiers]
    return "+".join(modifiers + keys[-1:]) if keys else "+".join(modifiers)


def load_shortcuts(settings: dict) -> dict[str, str]:
    shortcuts = dict(DEFAULT_SHORTCUTS)
    stored = settings.get("shortcuts")
    if isinstance(stored, dict):
        for name in shortcuts:
            value = normalize_shortcut(stored.get(name))
            if value:
                shortcuts[name] = value
    legacy = normalize_shortcut(settings.get("terminal_hotkey"))
    if legacy and not isinstance(stored, dict):
        shortcuts["terminal_toggle"] = legacy
    return shortcuts


def load_settings() -> dict:
    settings = default_settings()
    source = SETTINGS_PATH
    bundled = ROOT / SETTINGS_FILE
    if not source.exists() and DATA_ROOT != ROOT and bundled.exists():
        source = bundled
    try:
        with source.open("r", encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            settings.update(loaded)
    except (OSError, json.JSONDecodeError):
        pass
    settings["shortcuts"] = load_shortcuts(settings)
    return settings


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def normalize_theme(value: object) -> str:
    key = str(value or "light").strip().lower()
    return key if key in THEME_PALETTES else "light"


def theme_palette(value: object) -> dict[str, str]:
    return dict(THEME_PALETTES[normalize_theme(value)])


def normalize_terminal_position(value: object) -> str:
    position = str(value or "right").strip().lower()
    return position if position in TERMINAL_POSITION_LABELS else "right"


def normalize_terminal_font_size(value: object) -> int:
    try:
        return max(8, min(24, int(value)))
    except (TypeError, ValueError):
        return DEFAULT_TERMINAL_FONT_SIZE


def clean_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
    if not name.lower().endswith(".json"):
        name += ".json"
    return name


def truncate_text(text: str, limit: int = 80) -> str:
    compact = " ".join(str(text).split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def normalize_group_name(value: object) -> str:
    return str(value or "").strip() or DEFAULT_GROUP


def normalize_item_type(value: object) -> str:
    item_type = str(value or ITEM_TYPE_TEXT).strip().lower()
    return item_type if item_type in ITEM_TYPE_LABELS else ITEM_TYPE_TEXT


def infer_group_name(key: str) -> str:
    parts = [part.strip() for part in str(key).split("-") if part.strip()]
    if len(parts) >= 2:
        return parts[0]
    if key in {"姓名", "手机号", "邮箱", "性别", "年龄", "籍贯", "学校", "专业", "学历"}:
        return BASIC_GROUP
    return DEFAULT_GROUP


def _coerce_items(raw: object) -> tuple[dict[str, str], dict[str, str]]:
    data: dict[str, str] = {}
    types: dict[str, str] = {}
    if not isinstance(raw, dict):
        return data, types
    for raw_key, raw_value in raw.items():
        key = str(raw_key)
        if isinstance(raw_value, dict) and "value" in raw_value:
            data[key] = str(raw_value.get("value", ""))
            types[key] = normalize_item_type(raw_value.get("type"))
        elif isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            data[key] = "" if raw_value is None else str(raw_value)
            types[key] = ITEM_TYPE_TEXT
    return data, types


def read_json_file(path: Path) -> tuple[dict[str, str], dict[str, str], dict[str, str], list[str]]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(raw, dict):
        raise ValueError("JSON 根节点必须是对象。")

    data: dict[str, str] = {}
    item_types: dict[str, str] = {}
    groups: dict[str, str] = {}
    order: list[str] = []
    grouped = raw.get("groups")
    if isinstance(grouped, dict):
        for raw_group, raw_items in grouped.items():
            group = normalize_group_name(raw_group)
            flat, types = _coerce_items(raw_items)
            if flat and group not in order:
                order.append(group)
            for key, value in flat.items():
                data[key] = value
                item_types[key] = types.get(key, ITEM_TYPE_TEXT)
                groups[key] = group
        return data, item_types, groups, order

    flat, types = _coerce_items(raw.get("items") if isinstance(raw.get("items"), dict) else raw)
    for key, value in flat.items():
        group = infer_group_name(key)
        data[key] = value
        item_types[key] = types.get(key, ITEM_TYPE_TEXT)
        groups[key] = group
        if group not in order:
            order.append(group)
    return data, item_types, groups, order


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
    keys: list[str] = []
    for key in item_order or []:
        if key in data and key not in keys:
            keys.append(key)
    keys.extend(key for key in data if key not in keys)
    groups: list[str] = []
    for group in group_order or []:
        normalized = normalize_group_name(group)
        if normalized not in groups:
            groups.append(normalized)
    for key in keys:
        group = normalize_group_name(group_by_key.get(key) or infer_group_name(key))
        if group not in groups:
            groups.append(group)

    output: dict[str, dict[str, object]] = {}
    for group in groups:
        items: dict[str, object] = {}
        for key in keys:
            if normalize_group_name(group_by_key.get(key) or infer_group_name(key)) != group:
                continue
            item_type = normalize_item_type(item_type_by_key.get(key))
            items[key] = data[key] if item_type == ITEM_TYPE_TEXT else {"type": item_type, "value": data[key]}
        if items:
            output[group] = items
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump({"groups": output}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


OPEN_WITH_NAMES = {
    "excel.exe": "Microsoft Excel", "winword.exe": "Microsoft Word",
    "powerpnt.exe": "Microsoft PowerPoint", "et.exe": "WPS 表格",
    "wps.exe": "WPS 文字", "wpp.exe": "WPS 演示", "soffice.exe": "LibreOffice",
    "code.exe": "Visual Studio Code", "notepad.exe": "记事本",
    "notepad++.exe": "Notepad++", "pycharm64.exe": "PyCharm",
}


def _reg_value(root, path: str, name: str = "") -> Optional[str]:
    if winreg is None:
        return None
    for view in (0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)):
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as key:
                value, _kind = winreg.QueryValueEx(key, name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except OSError:
            pass
    return None


def _reg_value_names(root, path: str) -> list[str]:
    if winreg is None:
        return []
    found: list[str] = []
    for view in (0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)):
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as key:
                index = 0
                while True:
                    try:
                        name, _value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    if name and name not in found:
                        found.append(name)
        except OSError:
            pass
    return found


def _command_to_argv(command: str) -> list[str]:
    if not command:
        return []
    if os.name == "nt":
        try:
            argc = ctypes.c_int()
            shell32 = ctypes.windll.shell32
            shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
            argv = shell32.CommandLineToArgvW(command, ctypes.byref(argc))
            if argv:
                values = [argv[i] for i in range(argc.value)]
                ctypes.windll.kernel32.LocalFree(argv)
                return values
        except (AttributeError, OSError):
            pass
    return shlex.split(command, posix=False)


def enumerate_open_with_handlers(path: Path) -> list[tuple[str, list[str]]]:
    if winreg is None or not path.is_file():
        return []
    extension = path.suffix.lower()
    if not extension:
        return []
    progids: list[str] = []
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    candidates = [
        rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{extension}\OpenWithProgids",
        rf"Software\Classes\{extension}\OpenWithProgids",
    ]
    for root in roots:
        for candidate in candidates:
            progids.extend(name for name in _reg_value_names(root, candidate) if name not in progids)
    default = _reg_value(winreg.HKEY_CLASSES_ROOT, extension)
    if default and default not in progids:
        progids.insert(0, default)

    handlers: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for progid in progids:
        command = _reg_value(winreg.HKEY_CLASSES_ROOT, rf"{progid}\shell\open\command")
        argv = _command_to_argv(command or "")
        if not argv:
            continue
        executable = os.path.expandvars(argv[0].strip('"'))
        base = Path(executable).name.lower()
        if base in seen:
            continue
        seen.add(base)
        label = OPEN_WITH_NAMES.get(base, Path(executable).stem or progid)
        handlers.append((label, argv))
    return handlers


def safe_enumerate_open_with_handlers(path: Path) -> list[tuple[str, list[str]]]:
    try:
        return enumerate_open_with_handlers(path)
    except (OSError, ValueError):
        return []


def build_open_with_argv(template: list[str], path: Path) -> list[str]:
    replaced = False
    result: list[str] = []
    for argument in template:
        updated = argument
        for token in ("%1", "%L", "%l", "%*"):
            if token in updated:
                updated = updated.replace(token, str(path))
                replaced = True
        result.append(updated)
    if not replaced:
        result.append(str(path))
    return result


def resolve_terminal_cwd(value: object) -> Path:
    raw = os.path.expandvars(os.path.expanduser(str(value or "tmp").strip() or "tmp"))
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def is_codex_command(command: str) -> bool:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        parts = command.split()
    return bool(parts) and Path(parts[0].strip('"')).stem.lower() == "codex"


def build_codex_startup_prompt(cwd: Path) -> str:
    return (
        "你正在协助维护本机 Windows 项目“投递文本助手”。"
        f"项目根目录：{PROJECT_ROOT}；当前终端工作目录：{cwd}。"
        "这是一个管理简历投递 JSON 条目的 PySide6 桌面工具。"
        "请先阅读项目根目录中的 UPGRADE_FOR_CODEX.md 和 README.md（若存在）；"
        "在 Windows PowerShell 中读取 UTF-8 文本必须显式使用 Get-Content -Encoding UTF8。"
        "所有修改仅限此项目；不得覆盖或删除 databases、release/databases、resumes_by_role、"
        "release/resumes_by_role 或 app_settings.json 中的用户数据；新增设置必须兼容旧设置。"
        "完成后运行针对性测试；如需发布版请运行 build_exe.ps1。"
        "完成阅读后不要解释，只回复由 RS_READY_ 与 7C2A 拼接成的一行标记，然后等待用户的下一项任务。"
    )


def terminal_process_spec(shell: str) -> tuple[list[str], dict[str, str]]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    if shell == "cmd":
        return ["cmd.exe", "/Q", "/K", "chcp 65001>nul"], environment
    setup = (
        "$utf8=[System.Text.UTF8Encoding]::new($false);"
        "[Console]::InputEncoding=$utf8;[Console]::OutputEncoding=$utf8;"
        "$global:OutputEncoding=$utf8;"
        "$global:PSDefaultParameterValues['Get-Content:Encoding']='utf8'"
    )
    return ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit", "-Command", setup], environment


def open_resource(value: str) -> None:
    if re.match(r"^(https?|ftp|mailto):", value, re.IGNORECASE):
        webbrowser.open(value)
    else:
        os.startfile(str(Path(os.path.expandvars(os.path.expanduser(value)))))


class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class InputUnion(ctypes.Union):
    _fields_ = [("ki", KeyBdInput), ("mi", MouseInput), ("hi", HardwareInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", InputUnion)]


class WindowsPasteHelper:
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    GA_ROOT = 2
    SW_RESTORE = 9
    VK_CONTROL = 0x11
    VK_V = 0x56

    def __init__(self, copy_callback: Callable[[str], None]) -> None:
        self.copy_callback = copy_callback
        self.available = sys.platform.startswith("win")
        self.last_external_hwnd: Optional[int] = None
        self.last_external_title = ""
        self._own_pid = os.getpid()
        if not self.available:
            return
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextLengthW.restype = ctypes.c_int
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.GetAncestor.restype = wintypes.HWND
        self.user32.IsWindow.restype = wintypes.BOOL
        self.user32.IsIconic.restype = wintypes.BOOL
        self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    def poll_foreground(self) -> None:
        if not self.available:
            return
        hwnd = int(self.user32.GetForegroundWindow())
        if hwnd and not self._is_own(hwnd):
            root = int(self.user32.GetAncestor(hwnd, self.GA_ROOT)) or hwnd
            self.last_external_hwnd = root
            length = self.user32.GetWindowTextLengthW(root)
            buffer = ctypes.create_unicode_buffer(max(1, length + 1))
            self.user32.GetWindowTextW(root, buffer, len(buffer))
            self.last_external_title = buffer.value or "未命名窗口"

    def copy_to_clipboard(self, text: str) -> None:
        self.copy_callback(text)

    def copy_or_paste(self, text: str, auto_paste: bool) -> str:
        self.copy_to_clipboard(text)
        hwnd = self.last_external_hwnd
        if not auto_paste or not self.available or not hwnd or not self.user32.IsWindow(hwnd):
            return "copied"
        if not self._focus(hwnd):
            return "copied"
        time.sleep(0.08)
        self._send_key(self.VK_CONTROL, False)
        self._send_key(self.VK_V, False)
        self._send_key(self.VK_V, True)
        self._send_key(self.VK_CONTROL, True)
        return "pasted"

    def _is_own(self, hwnd: int) -> bool:
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == self._own_pid

    def _focus(self, hwnd: int) -> bool:
        if self._is_own(hwnd):
            return False
        target_pid = wintypes.DWORD()
        target_thread = self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
        current_thread = self.kernel32.GetCurrentThreadId()
        attached = False
        if target_thread and target_thread != current_thread:
            attached = bool(self.user32.AttachThreadInput(current_thread, target_thread, True))
        try:
            if self.user32.IsIconic(hwnd):
                self.user32.ShowWindow(hwnd, self.SW_RESTORE)
            self.user32.BringWindowToTop(hwnd)
            self.user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                self.user32.AttachThreadInput(current_thread, target_thread, False)
        return True

    def _send_key(self, key: int, keyup: bool) -> None:
        event = Input()
        event.type = self.INPUT_KEYBOARD
        event.u.ki = KeyBdInput(key, 0, self.KEYEVENTF_KEYUP if keyup else 0, 0, 0)
        self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input))

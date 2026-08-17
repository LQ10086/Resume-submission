# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import tkinter.font as tkfont


APP_NAME = "投递文本助手"
DATABASE_DIR = "databases"
SETTINGS_FILE = "app_settings.json"
DEFAULT_DB = "默认投递资料.json"
MOD_SHIFT = 0x0001
MOD_CONTROL = 0x0004


SAMPLE_DATA = {
    "姓名": "请在这里填写你的姓名",
    "手机号": "请在这里填写你的手机号",
    "邮箱": "your.name@example.com",
    "实习经历-示例-经历名称": "公司/机构名称 | 岗位名称",
    "实习经历-示例-经历角色": "实习生",
    "实习经历-示例-经历详情": "工作内容：用 2-3 句话概括你的核心职责、业务场景和结果。1) 负责... 2) 协助... 3) 输出...",
    "科研经历-示例-经历名称": "课题名称 | 投稿/发表信息",
    "科研经历-示例-经历角色": "学生一作 / 主要参与人",
    "科研经历-示例-经历详情": "论文内容：说明研究问题、方法、你的贡献和阶段性成果。1) ... 2) ... 3) ...",
}


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = app_root()
DB_DIR = ROOT / DATABASE_DIR
SETTINGS_PATH = ROOT / SETTINGS_FILE


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


def read_json_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 格式错误：第 {exc.lineno} 行，第 {exc.colno} 列") from exc

    if isinstance(raw, dict) and isinstance(raw.get("items"), dict):
        raw = raw["items"]
    if not isinstance(raw, dict):
        raise ValueError("资料库必须是 JSON 对象，例如 {\"姓名\": \"张三\"}")

    data: dict[str, str] = {}
    for key, value in raw.items():
        if key is None:
            continue
        text_key = str(key).strip()
        if not text_key:
            continue
        if isinstance(value, str):
            data[text_key] = value
        else:
            data[text_key] = json.dumps(value, ensure_ascii=False, indent=2)
    return data


def write_json_file(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
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
        drag_command,
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
        self.drag_command = drag_command
        self.wheel_command = wheel_command
        self.font = font
        self.selected = False
        self.hover = False
        self.dragging = False
        self.press_xy = (0, 0)
        self.press_state = 0

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self.wheel_command)
        self.bind("<Button-4>", self.wheel_command)
        self.bind("<Button-5>", self.wheel_command)
        self._draw()

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
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
        return "break"

    def _on_motion(self, event: tk.Event) -> str:
        dx = abs(event.x_root - self.press_xy[0])
        dy = abs(event.y_root - self.press_xy[1])
        if dx + dy > 14:
            self.dragging = True
        return "break"

    def _on_release(self, event: tk.Event) -> str:
        state = self.press_state | getattr(event, "state", 0)
        if self.dragging:
            self.drag_command(self.item_key, event.x_root, event.y_root)
        else:
            self.click_command(self.item_key, state)
        return "break"

    def _draw(self) -> None:
        self.delete("all")
        if self.selected:
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
        topmost: bool = False,
    ) -> None:
        self.result: Optional[tuple[str, str]] = None
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("620x360")
        self.window.minsize(500, 320)
        self.window.transient(parent)
        self.window.configure(bg="#f6f7f9")
        if topmost:
            self.window.attributes("-topmost", True)

        self.key_var = tk.StringVar(value=initial_key)
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
        outer.rowconfigure(3, weight=1)

        ttk.Label(outer, text="键名").grid(row=0, column=0, sticky="w")
        self.key_entry = ttk.Entry(outer, textvariable=self.key_var)
        self.key_entry.grid(row=1, column=0, sticky="ew", pady=(4, 12))

        ttk.Label(outer, text="文本内容").grid(row=2, column=0, sticky="w")
        text_shell = ttk.Frame(outer)
        text_shell.grid(row=3, column=0, sticky="nsew", pady=(4, 12))
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
        actions.grid(row=4, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Button(actions, text="取消", command=self._cancel).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="保存", command=self._save, style="Accent.TButton").grid(row=0, column=2)

    def _save(self) -> None:
        key = self.key_var.get().strip()
        value = self.text.get("1.0", "end-1c")
        if not key:
            messagebox.showwarning("缺少键名", "请先填写键名。", parent=self.window)
            return
        self.result = (key, value)
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.destroy()


class QuickTextApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("760x480")
        self.root.minsize(560, 360)

        self.settings = self._load_settings()
        self.current_db = ""
        self.data: dict[str, str] = {}
        self.filtered_keys: list[str] = []
        self.selected_key: Optional[str] = None
        self.selected_keys: set[str] = set()
        self.chips: dict[str, ChipButton] = {}
        self.paste_helper = WindowsPasteHelper(root)

        self.db_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="先点击目标输入框，再点击快捷按钮。Ctrl+点击强制粘贴，Shift+点击多选。")
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

        quick_shell = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        quick_shell.grid(row=1, column=0, sticky="nsew")
        quick_shell.columnconfigure(0, weight=1)
        quick_shell.rowconfigure(0, weight=1)

        self.quick_canvas = tk.Canvas(quick_shell, borderwidth=0, highlightthickness=0, bg="#ffffff")
        self.quick_scroll = ttk.Scrollbar(quick_shell, orient="vertical", command=self.quick_canvas.yview)
        self.quick_frame = tk.Frame(self.quick_canvas, bg="#ffffff")
        self.quick_window = self.quick_canvas.create_window((0, 0), window=self.quick_frame, anchor="nw")
        self.quick_canvas.configure(yscrollcommand=self.quick_scroll.set)
        self.quick_canvas.grid(row=0, column=0, sticky="nsew")
        self.quick_scroll.grid(row=0, column=1, sticky="ns")

        selection = ttk.Frame(self.root, padding=(12, 0, 12, 8))
        selection.grid(row=2, column=0, sticky="ew")
        selection.columnconfigure(1, weight=1)
        ttk.Label(selection, textvariable=self.selected_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(selection, textvariable=self.preview_var, style="Muted.TLabel").grid(row=0, column=1, sticky="w", padx=(12, 8))
        self.edit_button = ttk.Button(selection, text="编辑", command=self.edit_selected)
        self.delete_button = ttk.Button(selection, text="删除", command=self.delete_selected, style="Danger.TButton")
        self.edit_button.grid(row=0, column=2, padx=(8, 4))
        self.delete_button.grid(row=0, column=3, padx=4)
        self.edit_button.grid_remove()
        self.delete_button.grid_remove()

        footer = ttk.Frame(self.root, padding=(12, 0, 12, 10))
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(footer, textvariable=self.target_var, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

    def _wire_events(self) -> None:
        self.db_combo.bind("<<ComboboxSelected>>", self.on_database_selected)
        self.search_var.trace_add("write", lambda *_: self.refresh_items())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.quick_canvas.bind("<Configure>", self._on_quick_canvas_configure)
        self.quick_canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.quick_canvas.bind("<Button-4>", self._on_mouse_wheel)
        self.quick_canvas.bind("<Button-5>", self._on_mouse_wheel)
        self.quick_frame.bind("<MouseWheel>", self._on_mouse_wheel)
        self.quick_frame.bind("<Button-4>", self._on_mouse_wheel)
        self.quick_frame.bind("<Button-5>", self._on_mouse_wheel)

    def _load_settings(self) -> dict:
        if not SETTINGS_PATH.exists():
            return {"auto_paste": False, "topmost": True}
        try:
            with SETTINGS_PATH.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                return loaded
        except (OSError, json.JSONDecodeError):
            pass
        return {"auto_paste": False, "topmost": True}

    def _save_settings(self) -> None:
        self.settings["auto_paste"] = bool(self.auto_paste_var.get())
        self.settings["topmost"] = bool(self.topmost_var.get())
        self.settings["current_db"] = self.current_db
        try:
            with SETTINGS_PATH.open("w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as exc:
            self.status_var.set(f"设置保存失败：{exc}")

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
            self.data = read_json_file(DB_DIR / name)
        except ValueError as exc:
            messagebox.showerror("资料库无法打开", f"{name}\n\n{exc}")
            self.data = {}
        self.current_db = name
        self.selected_key = None
        self.selected_keys.clear()
        self._save_settings()
        self.refresh_items()
        self._update_selection()
        self.status_var.set(f"已打开资料库：{name}")

    def save_database_to_disk(self) -> None:
        if self.current_db:
            write_json_file(DB_DIR / self.current_db, self.data)

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
        write_json_file(path, {})
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
        query = self.search_var.get().strip().lower()
        if query:
            self.filtered_keys = [
                key for key, value in self.data.items() if query in key.lower() or query in value.lower()
            ]
        else:
            self.filtered_keys = list(self.data.keys())

        self.selected_keys = {key for key in self.selected_keys if key in self.data}
        if not self.selected_keys:
            self.selected_key = None
        elif self.selected_key not in self.selected_keys:
            self.selected_key = self._ordered_selected_keys()[0]
        self.root.after_idle(self._layout_quick_buttons)
        self._update_selection()

    def _layout_quick_buttons(self) -> None:
        for child in self.quick_frame.winfo_children():
            child.destroy()
        self.chips = {}

        width = max(self.quick_canvas.winfo_width() - 8, 320)
        x = 8
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

        for key in self.filtered_keys:
            display = truncate_text(key, 24)
            chip_width = min(max(self.chip_font.measure(display) + 28, 58), 260)
            if x + chip_width + 8 > width and x > 8:
                x = 8
                y += row_height + gap_y
            chip = ChipButton(
                self.quick_frame,
                item_key=key,
                display_text=display,
                width=chip_width,
                height=row_height,
                click_command=self.use_item,
                drag_command=self.drag_item,
                wheel_command=self._on_mouse_wheel,
                font=self.chip_font,
            )
            chip.place(x=x, y=y)
            chip.set_selected(key in self.selected_keys)
            self.chips[key] = chip
            x += chip_width + gap_x

        total_height = y + row_height + 10
        self.quick_frame.configure(width=width, height=total_height)
        self.quick_canvas.itemconfigure(self.quick_window, width=width)
        self.quick_canvas.configure(scrollregion=(0, 0, width, total_height))

    def _bind_wheel(self, widget: tk.Widget) -> None:
        widget.bind("<MouseWheel>", self._on_mouse_wheel)
        widget.bind("<Button-4>", self._on_mouse_wheel)
        widget.bind("<Button-5>", self._on_mouse_wheel)

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
        dialog = ItemDialog(self.root, "新增条目", topmost=bool(self.topmost_var.get()))
        if not dialog.result:
            return
        key, value = dialog.result
        self._save_item(None, key, value)

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
            topmost=bool(self.topmost_var.get()),
        )
        if not dialog.result:
            return
        key, value = dialog.result
        self._save_item(old_key, key, value)

    def _save_item(self, old_key: Optional[str], key: str, value: str) -> None:
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
        else:
            self.data[key] = value

        self.save_database_to_disk()
        self.selected_key = key
        self.selected_keys = {key}
        self.refresh_items()
        self.status_var.set(f"已保存：{key}")

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
        if state & MOD_SHIFT:
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
        force_paste = bool(state & MOD_CONTROL)
        should_paste = self.auto_paste_var.get() or force_paste
        result = self.paste_helper.copy_or_paste(self.data[key], should_paste)
        if result == "pasted":
            if force_paste and not self.auto_paste_var.get():
                self.status_var.set(f"已通过 Ctrl+点击粘贴：{key}")
            else:
                self.status_var.set(f"已粘贴：{key}")
        else:
            if force_paste:
                self.status_var.set(f"已复制：{key}。Ctrl+点击未能自动填入，请在目标输入框按 Ctrl+V。")
            else:
                self.status_var.set(f"已复制：{key}。需要直接填入时可 Ctrl+点击。")

    def drag_item(self, key: str, x: int, y: int) -> None:
        if key not in self.data:
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

    def _update_selection(self) -> None:
        selected = self._ordered_selected_keys()
        count = len(selected)
        if count == 1:
            key = selected[0]
            self.selected_key = key
            self.selected_var.set(f"当前条目：{truncate_text(key, 30)}")
            preview = self.data[key].replace("\n", " ")
            self.preview_var.set(truncate_text(preview, 48))
            self.edit_button.grid()
            self.delete_button.grid()
            self.edit_button.configure(state="normal")
            self.delete_button.configure(text="删除", state="normal")
        elif count > 1:
            self.selected_key = selected[-1]
            self.selected_var.set(f"已选择 {count} 个条目")
            self.preview_var.set("多选状态下不能编辑，可批量删除。")
            self.edit_button.grid()
            self.delete_button.grid()
            self.edit_button.configure(state="disabled")
            self.delete_button.configure(text=f"删除 {count} 项", state="normal")
        else:
            self.selected_key = None
            self.selected_var.set("未选择条目")
            self.preview_var.set("")
            self.edit_button.grid_remove()
            self.delete_button.grid_remove()

    def _highlight_selected_chip(self) -> None:
        for key, chip in self.chips.items():
            chip.set_selected(key in self.selected_keys)

    def _ordered_selected_keys(self) -> list[str]:
        return [key for key in self.data if key in self.selected_keys]

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
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    QuickTextApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

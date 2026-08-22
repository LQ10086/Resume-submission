# 给后续 Codex 的升级说明

这是 `Resume Submission` 项目的升级约定。后续如果用户说“升级”或要求增加功能，必须先阅读本文件，再修改代码。

## 不可破坏的内容

1. 不要删除、覆盖或重建 `databases/*.json`。
2. 不要删除、覆盖或重建 `release/databases/*.json`；打包时必须保留用户已经编辑过的发布版资料库。
3. 不要删除 `resumes_by_role`、`release/resumes_by_role` 或其中的简历文件。
4. 不要删除、覆盖或重建 `user_data`、`release/user_data`；新版默认把个人资料库、简历、同步账号、备份和运行时临时文件集中放在这里。
5. `app_settings.json` 是用户设置，新增设置只能合并默认值，不能丢弃已有未知字段。
6. `tmp/` 和 `user_data/tmp` 是终端/同步临时目录，已加入 `.gitignore`，不得把其中的临时文件加入 Git。

## 升级流程

1. 先执行 `git status --short`，确认用户的本地修改和资料库状态。
2. 先备份或读取现有 JSON，再修改程序；不要用示例数据覆盖真实资料。
3. 对设置使用“默认值 + 旧设置覆盖”的迁移方式，保证旧版本仍能启动。
4. 如果新增终端设置，默认使用 `terminal_cwd: "tmp"`；新版会把默认 `tmp` 解析到 `user_data/tmp`，用户自定义的其他相对路径仍按项目目录解析，并自动创建目录。
5. 修改后先运行 `python -m py_compile src/app.py src/qt_core.py src/terminal_qt.py src/sync_service.py` 和针对性测试，再运行 `build_exe.ps1`。
6. 打包脚本必须保留 `release/user_data`、`release/databases` 和 `release/resumes_by_role` 中已有文件；只有目标目录为空时才复制示例数据。
7. 最后启动 `release/ResumeQuickPaste.exe`，确认主界面、设置、终端和原有条目都能正常打开。
8. 应用内终端启动 `codex` 时会通过 CLI 的初始提示参数自动把本文件、项目路径和数据保护约定发送给 Codex；提示内容由程序动态生成，不要硬编码某台电脑的绝对路径。启动引导必须对用户隐藏，界面仅显示准备中、就绪或超时状态。
9. 内置终端使用带历史记录的终端屏幕，滚轮和滚动条必须能够回看输出；主题设置需要同步覆盖主界面、条目卡片、弹窗和终端。
10. 本地资源默认通过 Windows 文件关联打开；右键菜单保留“打开文件夹”和基于注册表枚举的“打开方式”。资源管理器定位快捷键是可再次按下取消的单次模式，不得把状态遗留到后续 `Ctrl+Shift+点击`。
11. 组内及跨组拖拽按界面视觉顺序计算插入槽，必须支持行首、行尾、卡片间隙和跨行位置，并显示插入线。
12. 发布版以 Windows 10/11 x64 为兼容目标，不得硬编码本机软件路径或文件关联。应用目录不可写时，数据目录自动回退到 `%LOCALAPPDATA%\ResumeQuickPaste`；注册表枚举失败时右键菜单仍须保留系统“选择其他应用”。
13. 设置窗口的每个标签页都必须支持鼠标滚轮和滚动条，标签内容滚动时底部保存/取消操作区保持固定。
14. 内置终端使用 PySide6 的原生 `QClipboard` 检查内容。文本走 bracketed paste；图片不得被转成路径或覆盖原剪贴板，必须把用户的粘贴转换为 Codex 能识别的修饰 `V` 键事件，并显示可点击的 `Image #N` 应用内预览附件。
15. 终端支持 `right` 和 `bottom` 两种停靠位置，默认 `right`；更改设置后同步切换 `QSplitter` 方向。渲染光标时必须把终端显示列按字符实际列宽换算成字符串下标，不能直接用 `cursor.x` 索引含中文或 Emoji 的文本。
16. ConPTY 输出必须通过 `pywinpty.PtyProcess.read()` 读取；它会在 UTF-8 字符跨底层管道包时继续补齐字节。不得绕过该方法直接对 `fileobj.recv()` 分块解码，否则 Codex 的框线和中文可能变成 `�`。终端字体和字号属于可迁移设置，字体在其他 Win10/11 主机不存在时必须回退到系统等宽字体。
17. Windows PowerShell 5.1 读取无 BOM 的 UTF-8 中文文件时可能按 ANSI 误解码。Codex 运行 `Get-Content` 必须显式使用 `-Encoding UTF8`；内置 PowerShell 同时设置 UTF-8 输入、输出和 `Get-Content` 默认编码。项目引导文档保留 UTF-8 BOM 以兼容旧版 PowerShell。
18. 终端必须支持鼠标选择后使用 `Ctrl+C`、`Ctrl+Shift+C`、`Ctrl+Insert` 或右键菜单复制文本；没有选区时 `Ctrl+C` 才发送中断。Codex 的文本与图片粘贴是两个不同通道：文本必须发送 bracketed-paste 事件；图片必须保留剪贴板格式。ConPTY 中裸 `0x16` 不等价于修饰键事件，当前实现以 VT `Alt+V` 序列触发 Codex 官方支持的图片粘贴路径。
19. 分组显示顺序必须持久化到当前 JSON；选中同一分组中的任意条目后，默认 `Ctrl+Up`/`Ctrl+Down` 移动整个分组一格。默认 `Ctrl+N` 打开新增条目窗口，三个快捷键都必须进入统一的可配置快捷键和旧设置默认值迁移机制。
20. 主界面已经迁移到 PySide6，当前 Python 运行代码统一位于 `src/`：`src/app.py`、`src/qt_core.py` 和 `src/terminal_qt.py` 是当前实现，`src/legacy_tk_app.py` 仅作回退参考。源码环境使用 `setup_pyside6.ps1` 创建项目内 `.python-runtime`；发布版仍必须把 Qt、Python、pywinpty 和 pyte 打包，确保其他 Win10/11 x64 主机无需安装开发环境。
21. Codex 启动引导只能在收到 `RS_READY_7C2A` 后显示终端内容；此前仅显示准备状态。终端体验测试必须包含真实 ConPTY 中文输出、带中文文本粘贴、实际 Codex 图片粘贴出现 `[Image #1]`、附件点击预览和 U+FFFD 检查。
22. 右侧分隔区域由“终端”和“信息”标签页共用。点击左侧单个条目必须自动打开信息页，并允许直接修改键名、分组、类型和值；保存仍通过现有 JSON 序列化路径，不能另建或覆盖资料库。
23. Codex 只允许在首次显示或用户点击“手动重试”时启动。每次启动必须有独立会话编号，旧会话的输出、退出信号和 30/90 秒计时器不得污染新会话；嵌入模式使用 `--no-alt-screen`，高频 TUI 输出需要合并、去重并保持用户滚动位置。终端刷新不得调用 `setPlainText()` 反复重建整份文档，必须只替换实际变化的文本片段，避免动画输出造成整屏闪烁。
24. 主区域与“终端 / 信息”区域之间的 `QSplitter` 必须使用非实时重排：拖动时显示位置预览，松开后才应用最终尺寸。终端行列数同步必须防抖并只向 pyte/ConPTY 提交最后一次尺寸，避免窗口或分隔条每移动一个像素就重绘和通知子进程。
25. 终端原生文本插入光标必须隐藏，命令光标按 pyte 的实际位置独立绘制，不能随鼠标点击或选择移动。`TerminalView` 必须启用 Qt 输入法事件，把 `QInputMethodEvent.commitString()` 原样发送给 ConPTY，并在真实终端光标处显示预编辑文字。
26. 终端标题中的完整工作路径不得参与右侧面板最小宽度计算；标题标签使用可收缩大小策略，确保水平分隔条可以向右拖动缩窄终端。新增条目窗口的分组框只允许选择已有分组，新名称统一通过“新建分组”按钮加入。
27. 主界面的条目卡片不得使用固定字符数省略键名，也不得用最大宽度裁掉尾部文字；卡片需要使用完整的“类型 + 键名”计算尺寸，超出当前行时由 `FlowLayout` 整体换行。
28. “终端 / 信息”右侧容器必须覆盖 `minimumSizeHint()` 返回 `(0, 0)`，且只允许 `QSplitter` 的右侧子项折叠；不得让标签页、终端标题、按钮或表单产生固定宽度阈值。右侧完全折叠为 0 时不要覆盖此前保存的非零宽度，确保下次显示仍可恢复。
29. 默认 `Ctrl+F` 必须聚焦并全选主界面搜索框；默认 `Ctrl+R` 必须打开条目名称批量查找替换窗口。两个快捷键需要进入统一的快捷键默认值与旧设置迁移机制。批量重命名必须先生成完整映射并检查空名称、目标重名和既有名称冲突，通过后一次性更新数据、顺序、类型、分组与选择状态，最后只写盘一次。

## 从 GitHub 更新其他用户的副本

其他用户可以在仓库根目录直接让 Codex“更新这个项目”。Codex 必须先遵循 `AGENTS.md` 和本文件，再执行以下流程：

1. 使用 `git status --short` 识别本地修改，并记录资料库、简历目录和设置文件的哈希或文件清单。
2. 使用 `git fetch` 检查远程更新；不得使用 `git reset --hard`、`git clean`、`git checkout -- .` 等覆盖式命令。
3. 远程更新若只涉及程序代码、依赖、文档和发布程序，可以采用非破坏性的快进或合并；若触及用户数据或产生冲突，必须停止并请用户决定。
4. 更新后运行 `python -m py_compile src/app.py src/qt_core.py src/terminal_qt.py src/sync_service.py`、针对性测试和 `build_exe.ps1`，并确认受保护文件在构建前后保持一致。
5. 推送贡献时只按白名单暂存代码、依赖、文档和明确要求发布的 exe，绝不提交个人资料、简历、设置、同步账号、`user_data`、`tmp` 或 `build` 中间产物。

## 当前终端设置字段

```json
{
  "terminal_hotkey": "ctrl+j",
  "shortcuts": {
    "terminal_toggle": "ctrl+j",
    "add_item": "ctrl+n",
    "edit_item": "ctrl+e",
    "move_left": "ctrl+left",
    "move_right": "ctrl+right",
    "move_group_up": "ctrl+up",
    "move_group_down": "ctrl+down",
    "explorer_reveal": "ctrl+shift+e"
  },
  "terminal_shell": "powershell",
  "terminal_cwd": "tmp",
  "terminal_command": "codex",
  "terminal_position": "right",
  "terminal_font": "Consolas",
  "terminal_font_size": 11,
  "theme": "light"
}
```

这些字段应当与旧版 `terminal_hotkey`、`auto_paste`、`topmost`、`current_db` 等字段共存，不能重写整个设置文件。旧版只有 `terminal_hotkey` 时，要把它迁移为 `shortcuts.terminal_toggle`，其他快捷键使用默认值。

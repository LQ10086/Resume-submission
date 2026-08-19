# 给后续 Codex 的升级说明

这是 `Resume Submission` 项目的升级约定。后续如果用户说“升级”或要求增加功能，必须先阅读本文件，再修改代码。

## 不可破坏的内容

1. 不要删除、覆盖或重建 `databases/*.json`。
2. 不要删除、覆盖或重建 `release/databases/*.json`；打包时必须保留用户已经编辑过的发布版资料库。
3. 不要删除 `resumes_by_role`、`release/resumes_by_role` 或其中的简历文件。
4. `app_settings.json` 是用户设置，新增设置只能合并默认值，不能丢弃已有未知字段。
5. `tmp/` 是终端工作目录，已加入 `.gitignore`，不得把其中的临时文件加入 Git。

## 升级流程

1. 先执行 `git status --short`，确认用户的本地修改和资料库状态。
2. 先备份或读取现有 JSON，再修改程序；不要用示例数据覆盖真实资料。
3. 对设置使用“默认值 + 旧设置覆盖”的迁移方式，保证旧版本仍能启动。
4. 如果新增终端设置，默认使用 `terminal_cwd: "tmp"`，相对路径要相对于项目目录解析，并自动创建目录。
5. 修改后先运行 `python -m py_compile app.py` 和针对性测试，再运行 `build_exe.ps1`。
6. 打包脚本必须保留 `release/databases` 和 `release/resumes_by_role` 中已有文件；只有目标目录为空时才复制示例数据。
7. 最后启动 `release/ResumeQuickPaste.exe`，确认主界面、设置、终端和原有条目都能正常打开。
8. 应用内终端启动 `codex` 时会自动把本文件、项目路径和数据保护约定发送给 Codex；提示内容由程序动态生成，不要硬编码某台电脑的绝对路径。

## 当前终端设置字段

```json
{
  "terminal_hotkey": "ctrl+j",
  "shortcuts": {
    "terminal_toggle": "ctrl+j",
    "edit_item": "ctrl+e",
    "move_left": "ctrl+left",
    "move_right": "ctrl+right",
    "explorer_reveal": "ctrl+shift+e"
  },
  "terminal_shell": "powershell",
  "terminal_cwd": "tmp",
  "terminal_command": "codex"
}
```

这些字段应当与旧版 `terminal_hotkey`、`auto_paste`、`topmost`、`current_db` 等字段共存，不能重写整个设置文件。旧版只有 `terminal_hotkey` 时，要把它迁移为 `shortcuts.terminal_toggle`，其他快捷键使用默认值。

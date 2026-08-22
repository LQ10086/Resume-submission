# 安全升级约束

当用户说“更新一下这个项目”或要求升级本项目时，先阅读 `UPGRADE_FOR_CODEX.md`，并按其中流程执行。

## 必须保护的本地数据

- 不得删除、覆盖、还原或提交 `databases/`、`release/databases/`、`resumes_by_role/`、`release/resumes_by_role/` 中的用户文件。
- 不得删除、覆盖、还原或提交 `user_data/`、`release/user_data/` 中的个人资料库、同步账号、备份、简历或运行时文件。
- 不得覆盖或提交 `app_settings.json`、`release/app_settings.json`；它们是各用户的个人设置。
- 不得使用会丢弃本地数据的 `git reset --hard`、`git clean -fd`、`git checkout -- .` 或等价操作。
- 更新与打包时使用 `build_exe.ps1`；该脚本会保留发布目录里已有的资料库和简历。

## 提交约束

- 除非用户明确要求，不要提交个人资料库、个人设置、同步账号、`user_data/`、`tmp/` 或 `build/` 的中间产物。
- 只提交实际改动的程序代码、依赖声明、构建脚本、文档，以及需要发布时的 `release/ResumeQuickPaste.exe`。

## 用户通过 Codex 更新

当用户在仓库根目录要求“更新这个项目”时：

1. 先执行 `git status --short` 并阅读 `UPGRADE_FOR_CODEX.md`，区分程序修改与用户数据。
2. 需要同步 GitHub 时先执行 `git fetch`；只允许非破坏性的快进、合并或变基，不得用重置、清理或检出覆盖本地文件。
3. 如果远程提交触及受保护目录或与用户修改冲突，停止自动更新并向用户说明，不得自行选择一方覆盖。
4. 修改后运行语法和针对性测试，再使用 `build_exe.ps1` 打包；打包前后核对受保护文件。
5. Git 提交使用文件白名单，只暂存代码、依赖、文档和明确要求发布的 exe，并在推送前检查 `git diff --cached --name-only`。

在 Windows PowerShell 5.1 中读取本项目的 UTF-8 文本时，始终使用 `Get-Content -Encoding UTF8`；不要依赖系统 ANSI 默认编码，否则中文会在进入 Codex 前变成乱码。

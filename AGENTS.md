# 安全升级约束

当用户说“更新一下这个项目”或要求升级本项目时，先阅读 `UPGRADE_FOR_CODEX.md`，并按其中流程执行。

## 必须保护的本地数据

- 不得删除、覆盖、还原或提交 `databases/`、`release/databases/`、`resumes_by_role/`、`release/resumes_by_role/` 中的用户文件。
- 不得覆盖或提交 `app_settings.json`、`release/app_settings.json`；它们是各用户的个人设置。
- 不得使用会丢弃本地数据的 `git reset --hard`、`git clean -fd`、`git checkout -- .` 或等价操作。
- 更新与打包时使用 `build_exe.ps1`；该脚本会保留发布目录里已有的资料库和简历。

## 提交约束

- 除非用户明确要求，不要提交个人资料库、个人设置、`tmp/` 或 `build/` 的中间产物。
- 只提交实际改动的程序代码、依赖声明、构建脚本、文档，以及需要发布时的 `release/ResumeQuickPaste.exe`。

# codex-integrated-memory-rules

轻量集成两个本地 Codex 辅助组件：

- `prune-mem`：会话级 durable memory 召回与写回
- `codex-rulekit`：项目规则筛选、`AGENTS.md` 注入与 catalog 管理

这个仓库已经按 GitHub 发布面整理过：

- 命令示例改成仓库相对路径
- 增加 `.gitignore`、`.gitattributes`
- 增加 GitHub Actions 校验工作流
- 增加 `scripts/release_check.py` 做发布前自检

## 快速开始

```powershell
git clone <your-repo-url>
cd codex-integrated-memory-rules
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

默认会安装到 `~/.codex`。安装脚本会做三件事：

- 安装 `prune-mem-skill` 到 `<CodexRoot>\skills\prune-mem-skill`
- 生成本地 `codex-rulekit` shim：`.\.bin\codex-rulekit.cmd`
- 检查 `PyYAML`，并自动 bootstrap `<CodexRoot>\rule-library`

指定非默认 `CodexRoot`：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -CodexRoot D:\my-codex-root
```

如果你不想让安装脚本自动装 Python 依赖或 bootstrap：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -SkipPythonDeps -SkipBootstrap
```

## 工作流

进入一个项目：

```powershell
python .\scripts\integrate_project.py --project C:\path\to\repo
```

当前行为：

- 切到新项目时，先自动 finalize 上一个项目段
- 同一线程里重复进入同一个项目时，复用已有 active state，只刷新 `rulekit`
- `--json` 可输出机器可读结果
- `--skip-switch-finalize` 可禁用切项目自动 finalize

示例：

```powershell
python .\scripts\integrate_project.py --project C:\path\to\repo --json
python .\scripts\integrate_project.py --project C:\path\to\repo --skip-switch-finalize
```

结束当前会话并写回记忆：

```powershell
python .\scripts\finalize_session.py
```

带显式 transcript：

```powershell
python .\scripts\finalize_session.py C:\path\to\session-transcript.json
```

## 健康检查

```powershell
python .\scripts\doctor.py
```

检查项：

- Python 可用性
- 仓库关键路径
- 已安装 skill
- rule-library 存在与可写性
- catalog 构建状态
- 集成状态存储可写性

`ok=true` 表示当前环境可运行；`strict_ok=false` 但 `operational_ok=true` 表示部分路径不可直接写入，已使用 `memories_fallback` 降级存储。

## 发布前自检

本地发布前建议跑：

```powershell
python .\scripts\release_check.py
```

这个脚本会在临时目录里验证：

- `install.ps1` 可执行
- `doctor.py` 在干净 `CodexRoot` 下通过
- 同项目重复进入时 active state 复用
- 切项目时自动 finalize 生效

## GitHub Actions

仓库自带 Windows 校验工作流：

- `codex-rulekit` 单测
- `prune-mem` 单测
- `scripts/release_check.py`

文件位置：`.github/workflows/validate.yml`

## 维护经验

历史来源归档放在 `archive/desktop-sources/<date>/`。归档只保存源码、文档、测试和清单，排除 `.git`、缓存、`.tmp`、`.tmp-tests`、`__pycache__` 等临时内容。

`codex-rulekit` 扫描项目画像时会跳过 `archive/`。历史文件不能参与当前项目画像，否则旧的前端、研究或游戏样例会污染当前项目标签和规则选择。

游戏项目检测只应从 UI 或资产扩展名命中，例如 `.html`、`.js`、`.png`。不要把规则模板、文档或归档里的 `browser-game-frontend.md` 当成真实游戏项目线索。

自动生成且未被用户改过的 `.codex/project-profile.yaml` 可以在检测器修复后刷新；用户手改过的 profile 要保留。刷新规则后至少跑一次：

```powershell
.\.bin\codex-rulekit.cmd ensure-project --root C:\Users\admin\.codex --project D:\codex-integrated-memory-rules
```

如果刚把历史文件加入或排除扫描，第一次刷新可能只是在消化扫描差异；再跑一轮稳定扫描，确认 `project_activity_summary` 回到 `No file changes detected since last scan.`。

GitHub push 在这台机器上不一定继承浏览器代理。浏览器走 Windows 用户代理时，Git/curl 仍可能直连失败。先查：

```powershell
git config --global --get http.proxy
git config --global --get https.proxy
netsh winhttp show proxy
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer
```

若 Windows 用户代理是 `127.0.0.1:7890` 且端口可用，优先用临时 Git 代理推送，不要默认写全局配置：

```powershell
git -c http.proxy=http://127.0.0.1:7890 -c https.proxy=http://127.0.0.1:7890 push origin main
```

## 目录

```text
prune-mem/
  src/
  scripts/
  skill/
  tests/
codex-rulekit/
  src/
  tests/
scripts/
  integrate_project.py
  doctor.py
  finalize_session.py
  release_check.py
install.ps1
.env.example
.gitignore
.gitattributes
NOTICE.md
```

## 许可证说明

本仓库使用 MIT License，见 `LICENSE`。

这个仓库包含两个已 vendored 的 MIT 组件：

- `prune-mem`：见 `prune-mem/LICENSE`
- `codex-rulekit`：见 `codex-rulekit/LICENSE`

补充说明见 `NOTICE.md`。

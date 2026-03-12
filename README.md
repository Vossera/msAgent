<h1 align="center">🚀 msAgent</h1>

<p align="center"><strong>面向 Ascend NPU 场景的性能问题定位助手</strong></p>

**msAgent** 聚焦“发现瓶颈 -> 定位根因 -> 给出建议”的分析闭环。  
它结合 LLM 推理能力与可扩展工具链，帮助你把复杂 Profiling 信息快速转化为可执行的优化决策。

<p align="center">
  <img src="https://raw.githubusercontent.com/kali20gakki/images/main/msagent.gif" alt="msAgent">
</p>

📌 文档导航：[最新消息](#最新消息) ｜ [版本说明](#版本说明) ｜ [使用效果展示](#使用效果展示)


## 最新消息

- 2026-03-11：v0.1 PyPi whl包待发布

## 🔍 支持的分析场景与扩展能力

- ⚙️ 单卡性能问题：高耗时算子、计算热点、重叠度不足等
- 🔗 多卡性能问题：快慢卡差异、通信效率瓶颈、同步等待等
- ⏱️ 下发与调度问题：下发延迟、CPU 侧调度阻塞等
- 🧩 集群性能问题：慢节点识别与从全局到单机的逐层定位
- 🔌 MCP 扩展：基于 Model Context Protocol 接入工具（默认启用 [msprof-mcp](https://gitcode.com/kali20gakki1/msprof_mcp)）
- 🧠 Skills 扩展：自动加载 `skills/` 目录技能，复用领域分析流程和知识（仓库：[mindstudio-skills](https://github.com/kali20gakki/mindstudio-skills)）
---

## ⚡ 快速上手

### 1) 🧰 准备环境

- Python 3.11+
- 可用的 LLM API Key（OpenAI / Anthropic / Gemini / 兼容 OpenAI 接口）

说明：
- 下文中 Linux / macOS 默认使用 `bash` / `zsh`
- Windows 示例默认使用 CMD（命令提示符）；若你使用 PowerShell，可将 `set KEY=value` 改为 `$env:KEY = "value"`；若你使用 Git Bash / WSL，可直接复用 Linux / macOS 命令

### 2) 📦 安装（现暂时没上传到PyPi, 请通过源码clone）

```bash
pip install -U mindstudio-agent
```

安装完成后可用以下命令确认：

```bash
msagent --version
```

### 3) 🔐 配置 LLM（必做）

推荐先用 OpenAI：

如果你是源码方式（`git clone` + `uv sync`）运行，请将下列命令中的 `msagent` 替换为 `uv run msagent`。

Linux / macOS：

```bash
export OPENAI_API_KEY="your-key"
msagent config --llm-provider openai --llm-model "gpt-4o-mini"
```

Windows（CMD）：

```cmd
set OPENAI_API_KEY=your-key
msagent config --llm-provider openai --llm-model "gpt-4o-mini"
```

检查配置是否生效：

```bash
msagent config --show
```

### 4) 🖥️ 启动 TUI

```bash
msagent chat --tui
```

### 5) 📊 与msAgent一起性能调优

把 Profiling 目录路径和你的问题一起发给 msAgent，例如：

Linux / macOS：

```text
请分析 /path/to/profiler_output 的性能瓶颈，重点关注通信和高耗时算子。
```

Windows：

```text
请分析 C:\path\to\profiler_output 的性能瓶颈，重点关注通信和高耗时算子。
```

### 6) 🧪 可选：从源码运行（开发场景）

如需调试或二次开发，再使用源码方式：

以下命令在 Linux / macOS / Windows（CMD）一致：

```bash
git clone --recurse-submodules https://github.com/kali20gakki/msAgent.git
cd msAgent
uv sync
uv run msagent chat --tui
```

如果你已经完成普通 `git clone`，请补充执行拉取 [mindstudio-skills](https://github.com/kali20gakki/mindstudio-skills)：

```bash
git submodule sync --recursive
git submodule update --init --recursive --force
```

---

## 📚 常用命令

如果你是源码方式（`git clone` + `uv sync`）运行，请在下列命令前加 `uv run`。以下命令在 Linux / macOS / Windows 一致。

| 命令 | 说明 |
|---|---|
| `msagent chat --tui` | 启动 TUI 交互 |
| `msagent chat` | 启动 CLI 交互 |
| `msagent ask "..."` | 单轮提问 |
| `msagent config --show` | 查看当前配置 |
| `msagent mcp list` | 查看 MCP 服务器 |
| `msagent info` | 查看工具信息 |

---

## 🗂️ 完整命令参考

### 命令行入口

| 命令 | 说明 |
|---|---|
| `msagent --version` | 查看版本 |
| `msagent chat` | 启动 CLI 交互会话 |
| `msagent chat --tui` | 启动 TUI 交互界面 |
| `msagent chat "<message>"` | 直接发送一条消息 |
| `msagent chat --stream` | 以流式方式输出回答（默认开启） |
| `msagent chat --no-stream` | 关闭流式输出 |
| `msagent ask "<question>"` | 单轮提问 |
| `msagent ask --stream` | 单轮提问并流式输出（默认开启） |
| `msagent ask --no-stream` | 单轮提问并一次性输出 |
| `msagent config --show` | 查看当前配置 |
| `msagent config --llm-provider <provider>` | 设置 LLM Provider |
| `msagent config --llm-model <model>` | 设置模型名 |
| `msagent config --llm-base-url <url>` | 设置 OpenAI 兼容接口地址 |
| `msagent config --llm-max-tokens <n>` | 设置最大输出 token，`0` 表示自动 |
| `msagent config --llm-api-key-env <ENV_NAME>` | 设置读取 API Key 的环境变量名 |
| `msagent config --llm-api-key <key>` | 临时写入运行时 API Key（不会落盘保存明文） |
| `msagent mcp list` | 查看 MCP 服务列表 |
| `msagent mcp add --name <name> --command <cmd> --args "<args>"` | 添加 MCP 服务 |
| `msagent mcp remove --name <name>` | 删除 MCP 服务 |
| `msagent info` | 查看项目说明和配置位置 |

说明：
- `chat` 的位置参数 `message` 可省略；省略时进入 CLI 交互模式。
- `ask` 适合脚本化单轮调用，`chat` 更适合连续对话。
- `mcp add` 的 `--args` 使用逗号分隔，例如 `"-y,@modelcontextprotocol/server-filesystem,/tmp"`。

### 会话命令

这些命令在 TUI 输入框和 `msagent chat` 的 CLI 交互模式中都可用，除特别标注外均对当前会话立即生效：

| 命令 | 说明 |
|---|---|
| `/new` | 开启新 Session（清空上下文） |
| `/clear` | 清空当前 Session 的聊天历史 |
| `/backend` | 查看当前 deepagents backend（等价于 `/backend status`） |
| `/backend status` | 查看当前 deepagents backend |
| `/backend filesystem` | 切换到 `FilesystemBackend` |
| `/backend local_shell` | 切换到 `LocalShellBackend` |
| `/shell` | 查看当前 deepagents backend（等价于 `/shell status`） |
| `/shell status` | 查看当前 deepagents backend |
| `/shell on` | 开启 `LocalShellBackend`（快捷命令） |
| `/shell off` | 关闭 `LocalShellBackend`（快捷命令） |
| `/exit` | 退出当前会话 |

仅在 CLI 文本交互模式（`msagent chat`）中可用：

| 命令 | 说明 |
|---|---|
| `/help` | 查看 CLI 交互命令帮助 |

### TUI 快捷键

| 快捷键 | 说明 |
|---|---|
| `Enter` | 欢迎页进入聊天界面 |
| `Ctrl+N` | 开启新会话 |
| `Ctrl+L` | 清空当前对话 |
| `Ctrl+Q` | 退出 TUI |

说明：
- README 只记录当前代码里已确认且用户侧可依赖的快捷键。
- 退出 TUI 可使用 `Ctrl+Q`；也可在会话输入框中使用 `/exit`。
- 输入框存在命令/文件补全交互：当补全列表出现时，可用 `Up` / `Down` 选择，`Tab` 应用补全。

---

## 🧵 会话管理（新对话 Session）

参考 Codex / Claude Code 的交互体验，msAgent 现在支持一键切换到新会话：

- 在 TUI 输入框中输入 `/new`
- 或使用快捷键 `Ctrl+N`（Linux / macOS / Windows 终端默认一致；macOS 不是 `Cmd+N`）
- 切换后会立即清空上下文（历史消息与上下文 token），从全新 Session 开始对话

常用会话命令（TUI 输入框）：

| 命令 | 说明 |
|---|---|
| `/new` | 开启新 Session（清空上下文） |
| `/clear` | 清空当前 Session 的聊天历史 |
| `/backend` | 查看当前 deepagents backend |
| `/backend status` | 查看当前 deepagents backend |
| `/backend filesystem` | 切换到 `FilesystemBackend` |
| `/backend local_shell` | 切换到 `LocalShellBackend` |
| `/shell` | 查看当前 deepagents backend |
| `/shell status` | 查看当前 deepagents backend |
| `/shell on` | 开启 `LocalShellBackend`（快捷命令） |
| `/shell off` | 关闭 `LocalShellBackend`（快捷命令） |
| `/exit` | 退出会话 |

说明：
- 上述 backend 切换命令同时适用于 TUI 输入框和 `msagent chat` 的 CLI 交互模式。
- 切换结果仅对当前会话生效，不会写入全局配置文件。

### ⚠️ LocalShellBackend 使用说明

当你输入 `/backend local_shell` 或 `/shell on` 时，msAgent 会把 deepagents backend 切换为 `LocalShellBackend`。

这会带来更强的本地执行能力，但也有明显风险：

- `execute` 工具会直接在当前机器上执行 shell 命令
- 没有沙箱隔离，命令以当前用户权限运行
- 不适合生产环境、多租户环境或不受信任输入
- 不建议读取或操作敏感文件、密钥、凭证和系统配置

推荐做法：

- 默认使用 `/backend filesystem`
- 只有在确实需要本地 shell 能力时，再临时执行 `/shell on`
- 使用结束后及时执行 `/shell off`
- 涉及安装依赖、修改文件、网络访问等高风险操作时，先确认命令内容

如需在启动前预设 backend，仍可使用环境变量（高级用法）：

```bash
MSAGENT_DEEPAGENTS_BACKEND=local_shell msagent chat --tui
```

---

## 🌱 环境变量参考

### LLM 与模型

| 环境变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | OpenAI Provider 的 API Key |
| `ANTHROPIC_API_KEY` | Anthropic Provider 的 API Key |
| `GEMINI_API_KEY` | Gemini Provider 的 API Key |
| `CUSTOM_API_KEY` | 自定义 OpenAI 兼容 Provider 的 API Key |
| `OPENAI_MODEL` | OpenAI 默认模型名 |
| `ANTHROPIC_MODEL` | Anthropic 默认模型名 |
| `GEMINI_MODEL` | Gemini 默认模型名 |
| `CUSTOM_MODEL` | 自定义 Provider 默认模型名 |
| `CUSTOM_BASE_URL` | 自定义 Provider 的 Base URL |

说明：
- 配置文件不会保存明文 API Key。
- 若未显式传 `--llm-api-key-env`，msAgent 会按当前 Provider 自动读取对应的默认 API Key 环境变量。

### Agent / deepagents 运行时

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MSAGENT_DEEPAGENTS_BACKEND` | `filesystem` | 启动时预设 deepagents backend。可选值：`filesystem` / `local_shell` |
| `MSAGENT_ENABLE_LOCAL_SHELL` | 未设置 | 兼容旧用法；当值为 `1` / `true` / `yes` / `on` 时，启动时启用 `local_shell` |
| `MSAGENT_LLM_TIMEOUT` | `600`（普通 `chat`） / `3600`（流式 `chat_stream`） | Agent 等待 LLM 返回的超时时间，单位秒 |
| `MSAGENT_TOOL_TIMEOUT` | `1200` | MCP 工具调用超时，单位秒 |
| `MSAGENT_LOCAL_SHELL_TIMEOUT` | `120` | `LocalShellBackend` 中 `execute` 工具的默认超时，单位秒 |
| `MSAGENT_LOCAL_SHELL_MAX_OUTPUT_BYTES` | `100000` | `LocalShellBackend` 中 `execute` 输出的最大截断字节数 |
| `MSAGENT_PYTHON_TOOL_TIMEOUT` | `30.0` | 内置 `builtin__execute_python` 工具的默认超时，单位秒 |
| `MSAGENT_PYTHON_TOOL_MAX_TIMEOUT` | `120.0` | 内置 `builtin__execute_python` 工具允许的最大超时，单位秒 |
| `MSAGENT_PYTHON_TOOL_OUTPUT_LIMIT` | `12000` | 内置 `builtin__execute_python` 工具的输出字符截断上限 |

优先级说明：
- 若同时设置了 `MSAGENT_DEEPAGENTS_BACKEND` 和 `MSAGENT_ENABLE_LOCAL_SHELL`，以前者为准。
- 运行时更推荐直接使用会话命令 `/backend ...` 或 `/shell ...` 切换；环境变量更适合启动前预设默认值。

### 配置层环境变量补充

除上面的显式环境变量外，配置系统本身还支持 `MSAGENT_` 前缀的嵌套环境变量覆盖（来自 `AppConfig` 的 `BaseSettings` 配置，嵌套分隔符是 `__`）。

例如：

```bash
MSAGENT__LLM__MODEL=gpt-4o-mini
MSAGENT__LLM__BASE_URL=https://example.com/v1
MSAGENT__THEME=light
```

说明：
- 这是配置层通用能力，不是某个单独模块手写读取的固定变量列表。
- 如果同时存在显式 Provider 环境变量（如 `OPENAI_API_KEY`、`CUSTOM_API_KEY`）和 `MSAGENT__...` 配置覆盖，最终行为仍以实际加载顺序与配置归一化逻辑为准。

### LocalShellBackend 子进程环境

当启用 `LocalShellBackend` 时，`execute` 工具不会继承完整宿主环境，而是只传递最小必要环境：

| 环境变量 | 来源 |
|---|---|
| `PATH` | 透传当前进程的 `PATH`，若不存在则回退为 `/usr/bin:/bin` |
| `HOME` | 若当前进程存在则透传 |
| `LANG` | 若当前进程存在则透传 |
| `LC_ALL` | 若当前进程存在则透传 |
| `SHELL` | 若当前进程存在则透传 |
| `TERM` | 若当前进程存在则透传 |
| `USER` | 若当前进程存在则透传 |
| `PYTHONIOENCODING` | 强制设置为 `utf-8` |

说明：
- `OPENAI_API_KEY` 等敏感变量不会自动传入 `LocalShellBackend` 子进程。
- 这能降低误泄露风险，但不等于安全沙箱；`LocalShellBackend` 仍然是高风险能力。

---

## 🛠️ 参考：配置与扩展

### 🤖 LLM 配置示例

OpenAI:

Linux / macOS：

```bash
export OPENAI_API_KEY="your-key"
msagent config --llm-provider openai --llm-model "gpt-4o-mini"
```

Windows（CMD）：

```cmd
set OPENAI_API_KEY=your-key
msagent config --llm-provider openai --llm-model "gpt-4o-mini"
```

Anthropic:

Linux / macOS：

```bash
export ANTHROPIC_API_KEY="your-key"
msagent config --llm-provider anthropic --llm-model "claude-3-5-sonnet-20241022"
```

Windows（CMD）：

```cmd
set ANTHROPIC_API_KEY=your-key
msagent config --llm-provider anthropic --llm-model "claude-3-5-sonnet-20241022"
```

Gemini:

Linux / macOS：

```bash
export GEMINI_API_KEY="your-key"
msagent config --llm-provider gemini --llm-model "gemini-2.0-flash"
```

Windows（CMD）：

```cmd
set GEMINI_API_KEY=your-key
msagent config --llm-provider gemini --llm-model "gemini-2.0-flash"
```

说明：OpenAI 兼容接口与 OpenAI Provider 共用 `openai`（通过 `--llm-base-url` 指向兼容服务）。

`max_tokens` 默认建议使用自动模式（`0`）：
- 自动模式不会向模型显式传 `max_tokens`，由服务端按模型默认值控制（最省维护）
- 适配新模型时无需更新本地“模型参数表”
- 如需手动覆盖，可用 `--llm-max-tokens <value>`

OpenAI 兼容接口（自定义 Base URL）：

Linux / macOS：

```bash
export OPENAI_API_KEY="your-key"
msagent config --llm-provider openai --llm-base-url "https://api.deepseek.com" --llm-model "deepseek-chat" --llm-max-tokens 0
```

Windows（CMD）：

```cmd
set OPENAI_API_KEY=your-key
msagent config --llm-provider openai --llm-base-url "https://api.deepseek.com" --llm-model "deepseek-chat" --llm-max-tokens 0
```

### 🔌 MCP 服务器管理

默认配置会启用 `msprof-mcp`（仓库：[msprof-mcp](https://gitcode.com/kali20gakki1/msprof_mcp)）。你也可以手动管理 MCP。除路径写法外，命令在 Linux / macOS / Windows 一致：

```bash
# 列表
msagent mcp list

# 添加
msagent mcp add --name filesystem --command npx --args "-y,@modelcontextprotocol/server-filesystem,/path"

# 删除
msagent mcp remove --name filesystem
```

`filesystem` 示例路径：
- Linux / macOS：`msagent mcp add --name filesystem --command npx --args "-y,@modelcontextprotocol/server-filesystem,/path/to/workspace"`
- Windows（CMD）：`msagent mcp add --name filesystem --command npx --args "-y,@modelcontextprotocol/server-filesystem,C:\path\to\workspace"`

### 📁 配置文件位置

- 优先读取当前工作目录：`config.json`
- 若不存在，则读取全局配置：
  - Linux / macOS：`~/.config/msagent/config.json`
  - Windows：`%USERPROFILE%\.config\msagent\config.json`（例如 `C:\Users\<用户名>\.config\msagent\config.json`）
- 安全策略：配置文件不会保存明文 API Key；默认按 Provider 读取对应环境变量（如 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`）

### 🧠 Skills

msAgent 的内置 Skills 已拆分到独立仓库 [mindstudio-skills](https://github.com/kali20gakki/mindstudio-skills)，在本仓通过 Git Submodule 挂载到根目录 `skills/`。

启动时会自动加载项目根目录 `skills/` 下的技能目录；若当前目录没有可用技能，会回退加载安装包内置技能（如 `op-mfu-calculator`）。格式如下：

```text
skills/
  <skill-name>/
    SKILL.md
```

---

## 🏗️ 编译与打包

### 打包 wheel（可直接 pip install）

Linux / macOS：

```bash
bash scripts/build_whl.sh
```

Windows（CMD）：

```cmd
git submodule update --init --recursive --force --depth 1 skills
uv build --wheel --out-dir dist .
```

如果你的 Windows 环境安装了 Git Bash / WSL，也可以直接执行 `bash scripts/build_whl.sh`。

构建脚本会自动执行 `git submodule update --init --recursive --force --depth 1 skills`，确保 `mindstudio-skills` 被打入 wheel 包。

打包完成后会在 `dist/` 目录生成 `mindstudio_agent-*.whl`，可直接安装：

Linux / macOS：

```bash
pip install dist/mindstudio_agent-<version>-py3-none-any.whl
```

Windows（CMD）：

```cmd
pip install .\dist\mindstudio_agent-<version>-py3-none-any.whl
```

请将上面的 `<version>` 替换为实际构建出的 wheel 文件名。

从 TestPyPI 安装时，建议同时添加 PyPI 作为依赖源（部分依赖仅发布在 PyPI）：

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ mindstudio-agent==0.1.0
```

---

## 👨‍💻 开发

以下命令在 Linux / macOS / Windows 一致：

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format .
```

---

## 使用效果展示

| 场景 | 效果展示 |
|---|---|
| MFU 计算 | <img src="https://raw.githubusercontent.com/kali20gakki/images/main/mfu.jpeg" alt="MFU 计算示例" width="800"> |

---

## 版本说明

| 项目 | 说明 |
|---|---|
| 当前版本 | `0.1.0` |
| 包名 | `mindstudio-agent` |
| 命令行入口 | `msagent` |
| Python 要求 | `>=3.11` |
| 版本策略 | 遵循语义化版本（SemVer），补丁版本以兼容性修复为主，次版本新增功能保持向后兼容，主版本包含不兼容变更。 |

可通过以下命令查看本地安装版本：

```bash
msagent --version
```

---

## 📄 许可证

MIT License

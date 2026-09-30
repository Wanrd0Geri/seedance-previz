# seedance-previz

用 Blender 搭 Seedance 2.5 白模预演：交一段能直接传即梦的白模参考视频，和一张给 aigc-video 写提示词用的交接卡。Claude Code 与 Codex 共用同一份文件。

- **依赖**：Blender 5.x、ffmpeg（含 ffprobe）、Python 3、Higgsfield 的 Blender MCP `higgsfield-use-blender`（npm 包 `fnf-blender-mcp`，装在 `~/.higgsfield/blender-mcp/`）。两个宿主都要注册这个 MCP。
- **macOS 与 Windows 通用**：脚本只用 Python 标准库，临时目录用 `tempfile.gettempdir()`，字幕字体按平台找系统中文字体。`scripts/encode.py` 是跨平台的编码入口，`encode.sh` 只是转调它的薄封装。Windows 11 + Blender 5.2 上自测通过；`higgsfield-use-blender` MCP 本身在 Windows 上的表现未验证。
- **找 Blender**：`scripts/selftest.py` 按环境变量 `BLENDER_EXECUTABLE`（或 `BLENDER`）→ PATH → 常见位置查找（macOS `/Applications/Blender*.app`；Windows `C:\Program Files\Blender Foundation\Blender *\blender.exe`，取最新版）。找 ffmpeg 同理，可用 `FFMPEG_DIR` 指定 bin 目录。
- **MCP 注册**（本 skill 不改任何配置文件，需要用户自己注册）：
  - Claude Code：`claude mcp add`，或编辑 `~/.claude.json` 的 `mcpServers`（Windows 是 `C:\Users\<用户名>\.claude.json`），用 `claude mcp list` 确认。
  - Codex：`codex mcp add`，或编辑 `~/.codex/config.toml`（Windows 是 `C:\Users\<用户名>\.codex\config.toml`），用 `codex mcp list` 确认。
  - 两边的命令、参数和环境变量相同。`command` 是 `node` 的路径（macOS 用 `which node`，Windows 用 `where node`），`args` 指向 `fnf-blender-mcp/dist/index.js`，环境变量 `BLENDER_EXECUTABLE` 指向 Blender 可执行文件。Windows 路径在 TOML 里用正斜杠或单引号字符串，避免反斜杠转义。

  ```toml
  [mcp_servers.higgsfield-use-blender]
  command = "/usr/local/bin/node"          # Windows：'C:\Program Files\nodejs\node.exe'
  args = ["/Users/<用户名>/.higgsfield/blender-mcp/node_modules/fnf-blender-mcp/dist/index.js"]
  startup_timeout_sec = 120
  tool_timeout_sec = 300

  [mcp_servers.higgsfield-use-blender.env]
  BLENDER_EXECUTABLE = "/Applications/Blender.app/Contents/MacOS/Blender"   # Windows：'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
  ```

  这个 MCP 的单次调用自己会在 120 秒时超时，超时的任务留着 job_id 继续跑，用 `bl_job_status` 查进度。所以 Codex 这边的 `tool_timeout_sec` 要设得比 120 秒长（Codex 默认只有 60 秒）。
- **自测**：`python3 -X utf8 $HOME/Documents/Codex/seedance-previz/scripts/selftest.py`（Windows 上 `python3` 不可用时用 `py -3`），应输出 `SELFTEST OK`。完整自测见 `references/export-verify.md` 第 6 节。
- 安装、同步与改动规则见 [Wanrd0Geri/skills-setup](https://github.com/Wanrd0Geri/skills-setup)。`notes/` 放施工图，只留在本机，不进仓库。

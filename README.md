# seedance-previz

用 Blender 搭 Seedance 2.5 白模预演：交一段能直接传即梦的白模参考视频，和一张给 aigc-video 写提示词用的交接卡。Claude Code 与 Codex 共用同一份文件。

- **依赖**：Blender 5.x、ffmpeg（含 ffprobe）、Python 3、Blender MCP（宿主里注册名为 `blender` 的 MCP，Blender 里装 `blender_mcp` 插件；插件更新命令 `uvx mcp-for-blender install-addon`）。两个宿主都要注册，用 `claude mcp list` / `codex mcp list` 确认。
- **连接**：MCP 连的是开着窗口的 Blender，插件的连接服务要开着。一键带窗口启动并开服务：
  - Windows（PowerShell）：`& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --python "$HOME\Documents\Codex\seedance-previz\scripts\start_blender_mcp.py"`
  - macOS：`/Applications/Blender.app/Contents/MacOS/Blender --python ~/Documents/Codex/seedance-previz/scripts/start_blender_mcp.py`
  - 也可以手动：Blender 侧边栏 BlenderMCP 页签 → Connect to MCP server。
- **数据收集**：这个插件默认会把提示词、代码和截图发给插件方；要关就让助手调 MCP 的 `disable_telemetry`，重新打开在 Blender 偏好设置 → 插件里改。
- **macOS 与 Windows 通用**：脚本只用 Python 标准库，临时目录用 `tempfile.gettempdir()`，字幕字体按平台找系统中文字体。`scripts/encode.py` 是跨平台的编码入口，`encode.sh` 只是转调它的薄封装。Windows 11 + Blender 5.2 上自测通过；窗口 MCP 路线 2026-10-01 在 Windows 11 + Blender 5.2.1 上实做过一条（蛟龙绕柱），macOS 未验证。
- **找 Blender**：`scripts/selftest.py` 按环境变量 `BLENDER_EXECUTABLE`（或 `BLENDER`）→ PATH → 常见位置查找（macOS `/Applications/Blender*.app`；Windows `C:\Program Files\Blender Foundation\Blender *\blender.exe`，取最新版）。找 ffmpeg 同理，可用 `FFMPEG_DIR` 指定 bin 目录。
- **自测**：`python3 -X utf8 $HOME/Documents/Codex/seedance-previz/scripts/selftest.py`（Windows 上 `python3` 不可用时用 `py -3`），应输出 `SELFTEST OK`。完整自测见 `references/export-verify.md` 第 6 节。
- 安装、同步与改动规则见 [Wanrd0Geri/skills-setup](https://github.com/Wanrd0Geri/skills-setup)。`notes/` 放施工图，只留在本机，不进仓库。

# seedance-previz

用 Blender 搭 Seedance 2.5 白模预演：交一段能直接传即梦的白模参考视频，和一张给 aigc-video 写提示词用的交接卡。Claude Code 与 Codex 共用同一份文件。

- **依赖**：Blender 5.x（`/Applications/Blender.app`）、ffmpeg、Higgsfield 的 Blender MCP `higgsfield-use-blender`（npm 包 `fnf-blender-mcp`，装在 `~/.higgsfield/blender-mcp/`）。两个宿主都要注册这个 MCP。
- **只支持 macOS**：`scripts/encode.sh` 是 bash 脚本，这个 MCP 也没在 Windows 上验证过。
- **Codex 注册**：在 `~/.codex/config.toml` 加下面几行；`node` 的路径用 `which node` 查，改完用 `codex mcp list` 确认。Claude Code 注册在 `~/.claude.json` 的 `mcpServers`，命令、参数和环境变量相同。

  ```toml
  [mcp_servers.higgsfield-use-blender]
  command = "/usr/local/bin/node"
  args = ["/Users/<用户名>/.higgsfield/blender-mcp/node_modules/fnf-blender-mcp/dist/index.js"]
  startup_timeout_sec = 120
  tool_timeout_sec = 300

  [mcp_servers.higgsfield-use-blender.env]
  BLENDER_EXECUTABLE = "/Applications/Blender.app/Contents/MacOS/Blender"
  ```

  这个 MCP 的单次调用自己会在 120 秒时超时，超时的任务留着 job_id 继续跑，用 `bl_job_status` 查进度。所以 Codex 这边的 `tool_timeout_sec` 要设得比 120 秒长（Codex 默认只有 60 秒）。
- **自测**：`/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python ~/Documents/Codex/seedance-previz/scripts/previz_lib.py`，应输出 `SELFTEST OK`。完整自测见 `references/export-verify.md` 第 6 节。
- 安装、同步与改动规则见 [Wanrd0Geri/skills-setup](https://github.com/Wanrd0Geri/skills-setup)。`notes/` 放施工图，只留在本机，不进仓库。

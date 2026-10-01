# -*- coding: utf-8 -*-
"""启动 Blender 时自动打开 Blender MCP 插件的连接服务（插件模块 blender_mcp，侧边栏按钮 "Connect to MCP server"）。

用法（在主机上，Blender 带窗口启动）：
    macOS:   /Applications/Blender.app/Contents/MacOS/Blender --python start_blender_mcp.py
    Windows: "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" --python start_blender_mcp.py

只在本次会话里启用插件（不改偏好设置）；界面起来 4 秒后开服务，端口用插件自己的设置（默认 9876）。
控制台打印 MCP START OK 就能连；打印 MCP START FAIL 就在侧边栏 BlenderMCP 页签手动点连接。
2026-10-01 Windows 11 + Blender 5.2.1 实测可用。
"""
import addon_utils
import bpy

addon_utils.enable("blender_mcp", default_set=False, persistent=False)


def _start():
    try:
        bpy.ops.blendermcp.start_server()
        print("MCP START OK")
    except Exception as e:  # 插件没装或版本不同
        print("MCP START FAIL", e)
    return None


bpy.app.timers.register(_start, first_interval=4.0)

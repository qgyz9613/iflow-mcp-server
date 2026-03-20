"""
Desktop 桌面控制模块 v2.2
Windows 桌面自动化控制

特性：
- 屏幕截图和识别
- 鼠标操作 (移动、点击、拖拽)
- 键盘操作 (按键、输入文本)
- 窗口管理
- 应用程序启动和控制

v2.0 新增:
- 双后端支持: pyautogui (默认) / pywinauto (备用)
- Windows UI Automation 原生控制
- Windows-MCP 风格工具

v2.1 更新:
- 修复命令注入漏洞
- 添加参数安全转义
- 改进资源管理

v2.2 更新:
- [致命修复] desktop_clipboard_set: 使用base64编码避免命令注入
- [高危修复] desktop_keyboard_type: 支持中文输入(剪贴板方式)
- [高危修复] 鼠标函数: 添加坐标边界检查
- [高危修复] 键盘函数: 添加按键名称白名单验证
- [中等修复] 所有裸except改为except Exception
"""

import json
import subprocess
import platform
import os
import time
import re
import uuid
from pathlib import Path
from typing import Any, Optional, List, Dict, Tuple
from datetime import datetime

# 模块配置
IFLOW_DIR = Path(__file__).parent.parent.parent
DESKTOP_DIR = IFLOW_DIR / "desktop_data"
SCREENSHOTS_DIR = DESKTOP_DIR / "screenshots"

# 后端配置
CURRENT_BACKEND = "auto"  # auto/pyautogui/pywinauto


def _ensure_dirs():
    """确保目录存在"""
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _check_pyautogui() -> bool:
    """检查 pyautogui 是否安装"""
    try:
        import pyautogui
        return True
    except ImportError:
        return False


def _check_pywinauto() -> bool:
    """检查 pywinauto 是否安装"""
    try:
        import pywinauto
        return True
    except ImportError:
        return False


def _get_backend() -> str:
    """获取当前使用的后端"""
    global CURRENT_BACKEND
    
    if CURRENT_BACKEND != "auto":
        return CURRENT_BACKEND
    
    # 自动选择
    if _check_pyautogui():
        return "pyautogui"
    elif _check_pywinauto():
        return "pywinauto"
    else:
        return "none"


def _set_backend(backend: str) -> str:
    """设置后端"""
    global CURRENT_BACKEND
    
    if backend == "pyautogui" and not _check_pyautogui():
        return "error: pyautogui 未安装"
    if backend == "pywinauto" and not _check_pywinauto():
        return "error: pywinauto 未安装"
    
    CURRENT_BACKEND = backend
    return f"ok: 后端已切换为 {backend}"


def _escape_powershell_string(s: str) -> str:
    """安全转义字符串用于PowerShell命令"""
    if s is None:
        return ""
    # 转义PowerShell特殊字符
    # 单引号在单引号字符串中需要双写
    escaped = s.replace("'", "''")
    # 转义反引号（PowerShell转义字符）
    escaped = escaped.replace("`", "``")
    # 转义美元符号
    escaped = escaped.replace("$", "`$")
    return escaped


def _escape_cmd_string(s: str) -> str:
    """安全转义字符串用于CMD命令"""
    if s is None:
        return ""
    # CMD中双引号需要转义
    escaped = s.replace('"', '""')
    return escaped


def _escape_regex_pattern(s: str) -> str:
    """安全转义正则表达式模式中的特殊字符"""
    if s is None:
        return ""
    return re.escape(s)


def _run_command(cmd: str, timeout: int = 30000) -> Tuple[int, str, str]:
    """运行命令"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout / 1000
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except Exception as e:
        return -1, "", str(e)


# ============ 工具函数 ============

def desktop_screenshot(region: dict = None, save_path: str = None) -> str:
    """
    截取屏幕截图
    
    Args:
        region: 截取区域 {"x": 0, "y": 0, "width": 1920, "height": 1080}
        save_path: 保存路径
    """
    _ensure_dirs()
    
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装。请运行: pip install pyautogui pillow"
        }, ensure_ascii=False)
    
    import pyautogui
    import base64
    
    try:
        if region:
            screenshot = pyautogui.screenshot(region=(
                region.get("x", 0),
                region.get("y", 0),
                region.get("width", 800),
                region.get("height", 600)
            ))
        else:
            screenshot = pyautogui.screenshot()
        
        # 使用UUID生成唯一文件名
        if not save_path:
            save_path = str(SCREENSHOTS_DIR / f"screenshot_{uuid.uuid4().hex[:8]}.png")
        
        screenshot.save(save_path)
        
        # 转为 base64
        with open(save_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        
        return json.dumps({
            "status": "ok",
            "path": save_path,
            "size": {"width": screenshot.width, "height": screenshot.height},
            "base64_preview": b64[:100] + "..."
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_mouse_move(x: int, y: int, duration: float = 0.5) -> str:
    """
    移动鼠标
    
    Args:
        x: 目标 X 坐标
        y: 目标 Y 坐标
        duration: 移动时间 (秒)
    """
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装"
        }, ensure_ascii=False)
    
    import pyautogui
    
    try:
        # 边界检查：确保坐标在屏幕范围内
        screen_width, screen_height = pyautogui.size()
        if x < 0 or x > screen_width:
            return json.dumps({
                "status": "error",
                "message": f"X坐标超出屏幕范围: {x} (屏幕宽度: {screen_width})"
            }, ensure_ascii=False)
        if y < 0 or y > screen_height:
            return json.dumps({
                "status": "error",
                "message": f"Y坐标超出屏幕范围: {y} (屏幕高度: {screen_height})"
            }, ensure_ascii=False)
        
        pyautogui.moveTo(x, y, duration=duration)
        return json.dumps({
            "status": "ok",
            "position": {"x": x, "y": y}
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_mouse_click(x: int = None, y: int = None, button: str = "left", 
                        clicks: int = 1, interval: float = 0.1) -> str:
    """
    鼠标点击
    
    Args:
        x: 目标 X 坐标 (不指定则当前位置点击)
        y: 目标 Y 坐标
        button: 按键 (left/right/middle)
        clicks: 点击次数
        interval: 点击间隔
    """
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装"
        }, ensure_ascii=False)
    
    import pyautogui
    
    try:
        # 边界检查：如果指定了坐标，验证其在屏幕范围内
        screen_width, screen_height = pyautogui.size()
        if x is not None:
            if x < 0 or x > screen_width:
                return json.dumps({
                    "status": "error",
                    "message": f"X坐标超出屏幕范围: {x} (屏幕宽度: {screen_width})"
                }, ensure_ascii=False)
        if y is not None:
            if y < 0 or y > screen_height:
                return json.dumps({
                    "status": "error",
                    "message": f"Y坐标超出屏幕范围: {y} (屏幕高度: {screen_height})"
                }, ensure_ascii=False)
        
        # 按键名称验证
        valid_buttons = ["left", "right", "middle"]
        if button.lower() not in valid_buttons:
            return json.dumps({
                "status": "error",
                "message": f"无效的按键: {button}，有效值: {valid_buttons}"
            }, ensure_ascii=False)
        
        pyautogui.click(x=x, y=y, button=button, clicks=clicks, interval=interval)
        pos = pyautogui.position()
        return json.dumps({
            "status": "ok",
            "action": "click",
            "button": button,
            "position": {"x": pos[0], "y": pos[1]}
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_mouse_drag(start_x: int, start_y: int, end_x: int, end_y: int,
                       duration: float = 1.0, button: str = "left") -> str:
    """
    鼠标拖拽
    
    Args:
        start_x: 起点 X
        start_y: 起点 Y
        end_x: 终点 X
        end_y: 终点 Y
        duration: 拖拽时间
        button: 按键
    """
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装"
        }, ensure_ascii=False)
    
    import pyautogui
    
    try:
        # 边界检查：确保起点和终点都在屏幕范围内
        screen_width, screen_height = pyautogui.size()
        
        if start_x < 0 or start_x > screen_width:
            return json.dumps({
                "status": "error",
                "message": f"起点X坐标超出屏幕范围: {start_x} (屏幕宽度: {screen_width})"
            }, ensure_ascii=False)
        if start_y < 0 or start_y > screen_height:
            return json.dumps({
                "status": "error",
                "message": f"起点Y坐标超出屏幕范围: {start_y} (屏幕高度: {screen_height})"
            }, ensure_ascii=False)
        if end_x < 0 or end_x > screen_width:
            return json.dumps({
                "status": "error",
                "message": f"终点X坐标超出屏幕范围: {end_x} (屏幕宽度: {screen_width})"
            }, ensure_ascii=False)
        if end_y < 0 or end_y > screen_height:
            return json.dumps({
                "status": "error",
                "message": f"终点Y坐标超出屏幕范围: {end_y} (屏幕高度: {screen_height})"
            }, ensure_ascii=False)
        
        # 按键名称验证
        valid_buttons = ["left", "right", "middle"]
        if button.lower() not in valid_buttons:
            return json.dumps({
                "status": "error",
                "message": f"无效的按键: {button}，有效值: {valid_buttons}"
            }, ensure_ascii=False)
        
        pyautogui.moveTo(start_x, start_y)
        pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration, button=button)
        return json.dumps({
            "status": "ok",
            "action": "drag",
            "from": {"x": start_x, "y": start_y},
            "to": {"x": end_x, "y": end_y}
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_mouse_scroll(clicks: int, x: int = None, y: int = None) -> str:
    """
    鼠标滚轮
    
    Args:
        clicks: 滚动量 (正数向上，负数向下)
        x: X 坐标
        y: Y 坐标
    """
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装"
        }, ensure_ascii=False)
    
    import pyautogui
    
    try:
        pyautogui.scroll(clicks, x=x, y=y)
        return json.dumps({
            "status": "ok",
            "action": "scroll",
            "clicks": clicks
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_mouse_position() -> str:
    """
    获取鼠标当前位置
    """
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装"
        }, ensure_ascii=False)
    
    import pyautogui
    
    try:
        x, y = pyautogui.position()
        return json.dumps({
            "status": "ok",
            "position": {"x": x, "y": y}
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_keyboard_type(text: str, interval: float = 0.05) -> str:
    """
    键盘输入文本 (支持中文)
    
    Args:
        text: 要输入的文本
        interval: 按键间隔
    """
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装"
        }, ensure_ascii=False)
    
    import pyautogui
    
    try:
        # 检测是否包含非ASCII字符（如中文）
        if any(ord(c) > 127 for c in text):
            # 使用剪贴板方式输入中文
            try:
                import pyperclip
                pyperclip.copy(text)
                time.sleep(0.1)  # 等待剪贴板更新
                pyautogui.hotkey('ctrl', 'v')
                return json.dumps({
                    "status": "ok",
                    "action": "type",
                    "method": "clipboard",
                    "length": len(text)
                }, ensure_ascii=False)
            except ImportError:
                # pyperclip未安装，使用PowerShell设置剪贴板
                desktop_clipboard_set(text)
                time.sleep(0.1)
                pyautogui.hotkey('ctrl', 'v')
                return json.dumps({
                    "status": "ok",
                    "action": "type",
                    "method": "powershell_clipboard",
                    "length": len(text)
                }, ensure_ascii=False)
        else:
            # ASCII字符使用typewrite
            pyautogui.typewrite(text, interval=interval)
            return json.dumps({
                "status": "ok",
                "action": "type",
                "method": "typewrite",
                "length": len(text)
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_keyboard_press(key: str, presses: int = 1, interval: float = 0.1) -> str:
    """
    按键
    
    Args:
        key: 按键 (如 'enter', 'tab', 'ctrl', 'alt' 等)
        presses: 按下次数
        interval: 间隔
    """
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装"
        }, ensure_ascii=False)
    
    import pyautogui
    
    # 按键名称白名单
    VALID_KEYS = {
        # 功能键
        'enter', 'return', 'tab', 'esc', 'escape', 'backspace', 'delete', 'insert',
        'space', 'spacebar',
        # 导航键
        'up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown',
        # 修饰键
        'shift', 'ctrl', 'control', 'alt', 'win', 'command', 'option',
        # F键
        'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
        # 数字键
        '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
        # 字母键
        'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
        'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z',
        # 符号键
        'minus', 'equal', 'equals', 'bracketleft', 'bracketright', 
        'backslash', 'semicolon', 'quote', 'comma', 'period', 'slash',
        # 其他
        'capslock', 'numlock', 'scrolllock', 'print', 'printscreen', 'pause',
        'break', 'help', 'menu', 'apps'
    }
    
    # 验证按键名称
    key_lower = key.lower()
    if key_lower not in VALID_KEYS:
        return json.dumps({
            "status": "error",
            "message": f"无效的按键名称: '{key}'。请使用有效按键名称。",
            "valid_keys": sorted(list(VALID_KEYS))
        }, ensure_ascii=False)
    
    try:
        pyautogui.press(key_lower, presses=presses, interval=interval)
        return json.dumps({
            "status": "ok",
            "action": "press",
            "key": key_lower
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_keyboard_hotkey(*keys: str) -> str:
    """
    组合键
    
    Args:
        keys: 按键序列 (如 'ctrl', 'c' 表示 Ctrl+C)
    """
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装"
        }, ensure_ascii=False)
    
    import pyautogui
    
    # 按键名称白名单
    VALID_KEYS = {
        # 功能键
        'enter', 'return', 'tab', 'esc', 'escape', 'backspace', 'delete', 'insert',
        'space', 'spacebar',
        # 导航键
        'up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown',
        # 修饰键
        'shift', 'ctrl', 'control', 'alt', 'win', 'command', 'option',
        # F键
        'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12',
        # 数字键
        '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
        # 字母键
        'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
        'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z',
        # 符号键
        'minus', 'equal', 'equals', 'bracketleft', 'bracketright', 
        'backslash', 'semicolon', 'quote', 'comma', 'period', 'slash',
        # 其他
        'capslock', 'numlock', 'scrolllock', 'print', 'printscreen', 'pause',
        'break', 'help', 'menu', 'apps'
    }
    
    # 验证所有按键名称
    keys_lower = []
    for key in keys:
        key_lower = key.lower()
        if key_lower not in VALID_KEYS:
            return json.dumps({
                "status": "error",
                "message": f"无效的按键名称: '{key}'。请使用有效按键名称。",
                "valid_keys": sorted(list(VALID_KEYS))
            }, ensure_ascii=False)
        keys_lower.append(key_lower)
    
    try:
        pyautogui.hotkey(*keys_lower)
        return json.dumps({
            "status": "ok",
            "action": "hotkey",
            "keys": keys_lower
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_screen_size() -> str:
    """
    获取屏幕尺寸
    """
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装"
        }, ensure_ascii=False)
    
    import pyautogui
    
    try:
        width, height = pyautogui.size()
        return json.dumps({
            "status": "ok",
            "screen": {"width": width, "height": height}
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_locate_on_screen(image_path: str, confidence: float = 0.9) -> str:
    """
    在屏幕上定位图像
    
    Args:
        image_path: 图像文件路径
        confidence: 匹配置信度
    """
    if not _check_pyautogui():
        return json.dumps({
            "status": "error",
            "message": "pyautogui 未安装"
        }, ensure_ascii=False)
    
    import pyautogui
    
    try:
        location = pyautogui.locateOnScreen(image_path, confidence=confidence)
        if location:
            return json.dumps({
                "status": "ok",
                "found": True,
                "location": {
                    "left": location.left,
                    "top": location.top,
                    "width": location.width,
                    "height": location.height
                },
                "center": {
                    "x": location.left + location.width // 2,
                    "y": location.top + location.height // 2
                }
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "status": "ok",
                "found": False,
                "message": "未找到匹配图像"
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_run_app(command: str, wait: bool = False) -> str:
    """
    运行应用程序
    
    Args:
        command: 命令或程序路径
        wait: 是否等待程序结束
    """
    try:
        if wait:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
            return json.dumps({
                "status": "ok",
                "returncode": result.returncode,
                "stdout": result.stdout[:1000],
                "stderr": result.stderr[:500]
            }, ensure_ascii=False)
        else:
            subprocess.Popen(command, shell=True)
            return json.dumps({
                "status": "ok",
                "message": f"已启动"
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_window_list() -> str:
    """
    列出所有窗口
    """
    if not _check_pywinauto():
        # 使用 PowerShell 作为备选
        code, stdout, stderr = _run_command(
            'powershell -Command "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object ProcessName, MainWindowTitle, Id | ConvertTo-Json"'
        )
        
        if code == 0:
            try:
                windows = json.loads(stdout)
                if not isinstance(windows, list):
                    windows = [windows]
                return json.dumps({
                    "status": "ok",
                    "method": "powershell",
                    "windows": [
                        {"process": w.get("ProcessName"), "title": w.get("MainWindowTitle"), "pid": w.get("Id")}
                        for w in windows[:20]
                    ]
                }, ensure_ascii=False)
            except Exception:
                pass
        
        return json.dumps({
            "status": "error",
            "message": "pywinauto 未安装，PowerShell 方法也失败"
        }, ensure_ascii=False)
    
    # 使用 pywinauto
    from pywinauto import Desktop
    
    try:
        desktop = Desktop(backend="uia")
        windows = desktop.windows()
        
        return json.dumps({
            "status": "ok",
            "method": "pywinauto",
            "windows": [
                {
                    "title": w.window_text()[:100],
                    "class_name": w.class_name(),
                    "handle": w.handle
                }
                for w in windows[:20]
                if w.window_text()
            ]
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_window_activate(title_pattern: str = None, handle: int = None) -> str:
    """
    激活窗口
    
    Args:
        title_pattern: 窗口标题模式
        handle: 窗口句柄
    """
    if not _check_pywinauto():
        return json.dumps({
            "status": "error",
            "message": "pywinauto 未安装。请运行: pip install pywinauto"
        }, ensure_ascii=False)
    
    from pywinauto import Desktop
    
    try:
        desktop = Desktop(backend="uia")
        
        if handle:
            window = desktop.window(handle=handle)
        elif title_pattern:
            # 安全转义正则表达式特殊字符
            safe_pattern = _escape_regex_pattern(title_pattern)
            window = desktop.window(title_re=f".*{safe_pattern}.*")
        else:
            return json.dumps({"status": "error", "message": "需要 title_pattern 或 handle"}, ensure_ascii=False)
        
        window.set_focus()
        
        return json.dumps({
            "status": "ok",
            "title": window.window_text()[:100]
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_clipboard_get() -> str:
    """
    获取剪贴板内容
    """
    try:
        import subprocess
        result = subprocess.run(
            ['powershell', '-Command', 'Get-Clipboard'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        return json.dumps({
            "status": "ok",
            "content": result.stdout
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_clipboard_set(text: str) -> str:
    """
    设置剪贴板内容
    
    Args:
        text: 要设置的文本
    """
    import base64
    
    try:
        # 使用base64编码避免命令注入漏洞
        # PowerShell -EncodedCommand 参数需要UTF-16LE编码的base64
        encoded_bytes = text.encode('utf-16le')
        encoded_b64 = base64.b64encode(encoded_bytes).decode('ascii')
        
        # 构建安全的PowerShell命令
        ps_script = f"Set-Clipboard -Value ([System.Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('{encoded_b64}')))"
        ps_script_bytes = ps_script.encode('utf-16le')
        ps_encoded = base64.b64encode(ps_script_bytes).decode('ascii')
        
        result = subprocess.run(
            ['powershell', '-NoProfile', '-EncodedCommand', ps_encoded],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return json.dumps({
                "status": "error",
                "message": f"PowerShell错误: {result.stderr}"
            }, ensure_ascii=False)
        
        return json.dumps({
            "status": "ok",
            "message": "剪贴板已设置",
            "length": len(text)
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


def desktop_check() -> str:
    """
    检查桌面控制环境
    """
    result = {
        "platform": platform.system(),
        "platform_version": platform.version(),
        "pyautogui": _check_pyautogui(),
        "pywinauto": _check_pywinauto(),
        "current_backend": _get_backend()
    }
    
    # 获取屏幕信息
    if _check_pyautogui():
        import pyautogui
        result["screen_size"] = {"width": pyautogui.size()[0], "height": pyautogui.size()[1]}
    
    return json.dumps({
        "status": "ok",
        "environment": result
    }, ensure_ascii=False, indent=2)


# ============ Windows-MCP 备用后端 ============

def desktop_set_backend(backend: str = "auto") -> str:
    """
    设置桌面控制后端
    
    Args:
        backend: 后端类型 (auto/pyautogui/pywinauto)
    """
    result = _set_backend(backend)
    
    if result.startswith("error"):
        return json.dumps({
            "status": "error",
            "message": result,
            "available": {
                "pyautogui": _check_pyautogui(),
                "pywinauto": _check_pywinauto()
            },
            "install_hint": {
                "pyautogui": "pip install pyautogui pillow",
                "pywinauto": "pip install pywinauto"
            }
        }, ensure_ascii=False)
    
    return json.dumps({
        "status": "ok",
        "backend": _get_backend(),
        "message": result
    }, ensure_ascii=False)


def desktop_launch_app(app_name: str, args: str = None, wait: bool = False) -> str:
    """
    启动应用程序 (Windows-MCP 风格)
    
    Args:
        app_name: 应用名称或路径 (如 notepad, winword, chrome)
        args: 启动参数
        wait: 是否等待应用启动
    """
    _ensure_dirs()
    
    # 常用应用路径映射
    app_paths = {
        "notepad": "notepad.exe",
        "word": "winword.exe",
        "excel": "excel.exe",
        "powerpoint": "powerpnt.exe",
        "chrome": "chrome.exe",
        "firefox": "firefox.exe",
        "edge": "msedge.exe",
        "explorer": "explorer.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "paint": "mspaint.exe",
        "calc": "calc.exe",
        "settings": "ms-settings:",
    }
    
    # 获取实际路径（安全处理）
    app_lower = app_name.lower()
    if app_lower in app_paths:
        app_path = app_paths[app_lower]
    else:
        # 对于自定义路径，只使用基本文件名，防止路径遍历
        app_path = os.path.basename(app_name)
    
    # 安全转义参数
    safe_app_path = _escape_cmd_string(app_path)
    safe_args = _escape_cmd_string(args) if args else ""
    
    # 构建命令
    if safe_args:
        cmd = f'start "" "{safe_app_path}" {safe_args}'
    else:
        cmd = f'start "" "{safe_app_path}"'
    
    code, stdout, stderr = _run_command(cmd)
    
    if wait:
        time.sleep(2)
    
    return json.dumps({
        "status": "ok" if code == 0 else "error",
        "app": app_name,
        "message": "应用已启动" if code == 0 else stderr
    }, ensure_ascii=False)


def desktop_shell(command: str, shell_type: str = "powershell") -> str:
    """
    执行 Shell 命令 (Windows-MCP 风格)
    
    Args:
        command: 要执行的命令
        shell_type: Shell 类型 (powershell/cmd)
    """
    _ensure_dirs()
    
    # 安全转义命令
    safe_command = _escape_powershell_string(command) if shell_type == "powershell" else _escape_cmd_string(command)
    
    if shell_type == "powershell":
        cmd = f"powershell -Command '{safe_command}'"
    else:
        cmd = f'cmd /c "{safe_command}"'
    
    code, stdout, stderr = _run_command(cmd, timeout=30000)
    
    return json.dumps({
        "status": "ok" if code == 0 else "error",
        "shell": shell_type,
        "stdout": stdout[:5000] if len(stdout) > 5000 else stdout,
        "stderr": stderr[:1000] if len(stderr) > 1000 else stderr,
        "exit_code": code
    }, ensure_ascii=False, indent=2)


def desktop_get_state(capture_screenshot: bool = True) -> str:
    """
    获取桌面状态 (Windows-MCP 风格)
    
    Args:
        capture_screenshot: 是否截图
    """
    _ensure_dirs()
    
    state = {
        "timestamp": datetime.now().isoformat(),
        "platform": platform.system(),
        "backend": _get_backend()
    }
    
    # 获取鼠标位置
    if _check_pyautogui():
        import pyautogui
        state["mouse_position"] = {"x": pyautogui.position()[0], "y": pyautogui.position()[1]}
        state["screen_size"] = {"width": pyautogui.size()[0], "height": pyautogui.size()[1]}
    
    # 获取活动窗口
    try:
        if _check_pywinauto():
            from pywinauto import Desktop
            desktop = Desktop(backend="uia")
            fg_window = desktop.windows()
            if fg_window:
                active = None
                for w in fg_window:
                    try:
                        if w.is_active():
                            active = {
                                "title": w.window_text(),
                                "class": w.class_name(),
                                "handle": w.handle
                            }
                            break
                    except Exception:
                        continue
                if active:
                    state["active_window"] = active
    except Exception:
        pass
    
    # 获取运行中的应用
    try:
        code, stdout, stderr = _run_command(
            'powershell -Command "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object -First 10 ProcessName, MainWindowTitle | ConvertTo-Json"',
            timeout=10000
        )
        if code == 0 and stdout.strip():
            state["running_apps"] = json.loads(stdout) if stdout.strip().startswith("[") else [json.loads(stdout)]
    except Exception:
        pass
    
    # 截图
    if capture_screenshot:
        screenshot_result = desktop_screenshot()
        try:
            screenshot_data = json.loads(screenshot_result)
            if screenshot_data.get("status") == "ok":
                state["screenshot_path"] = screenshot_data.get("path")
        except Exception:
            pass
    
    return json.dumps({
        "status": "ok",
        "state": state
    }, ensure_ascii=False, indent=2)


def desktop_find_window(title_contains: str = None, class_name: str = None) -> str:
    """
    查找窗口 (pywinauto 备用)
    
    Args:
        title_contains: 窗口标题包含的文本
        class_name: 窗口类名
    """
    _ensure_dirs()
    
    if not _check_pywinauto():
        return json.dumps({
            "status": "error",
            "message": "pywinauto 未安装。请运行: pip install pywinauto",
            "fallback": "使用 desktop_locate_on_screen 进行图像定位"
        }, ensure_ascii=False)
    
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        windows = desktop.windows()
        
        found = []
        for w in windows:
            try:
                w_title = w.window_text()
                w_class = w.class_name()
                
                match = True
                if title_contains:
                    # 安全比较，不使用正则
                    if title_contains.lower() not in w_title.lower():
                        match = False
                if class_name:
                    if class_name.lower() != w_class.lower():
                        match = False
                
                if match and w_title:  # 排除空标题窗口
                    found.append({
                        "title": w_title,
                        "class": w_class,
                        "handle": w.handle,
                        "visible": w.is_visible(),
                        "enabled": w.is_enabled()
                    })
            except Exception:
                continue
        
        return json.dumps({
            "status": "ok",
            "count": len(found),
            "windows": found[:20]  # 最多返回20个
        }, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)


def desktop_click_window(title_contains: str, control_type: str = None,
                         control_name: str = None, action: str = "click") -> str:
    """
    点击窗口控件 (pywinauto 备用)
    
    Args:
        title_contains: 窗口标题
        control_type: 控件类型 (Button/Edit/Text等)
        control_name: 控件名称/文本
        action: 操作类型 (click/set_text/get_text)
    """
    _ensure_dirs()
    
    if not _check_pywinauto():
        return json.dumps({
            "status": "error",
            "message": "pywinauto 未安装。请运行: pip install pywinauto"
        }, ensure_ascii=False)
    
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        
        # 查找窗口（安全比较，不使用正则）
        target_window = None
        for w in desktop.windows():
            if title_contains.lower() in w.window_text().lower():
                target_window = w
                break
        
        if not target_window:
            return json.dumps({
                "status": "error",
                "message": f"未找到包含指定标题的窗口"
            }, ensure_ascii=False)
        
        result = {
            "window_title": target_window.window_text(),
            "action": action
        }
        
        if control_type or control_name:
            # 查找控件
            descendants = target_window.descendants()
            target_control = None
            
            for ctrl in descendants:
                ctrl_type = ctrl.element_info.control_type
                ctrl_name = ctrl.window_text()
                
                type_match = not control_type or control_type.lower() in ctrl_type.lower()
                name_match = not control_name or control_name.lower() in ctrl_name.lower()
                
                if type_match and name_match:
                    target_control = ctrl
                    break
            
            if not target_control:
                return json.dumps({
                    "status": "error",
                    "message": f"未找到控件: type={control_type}, name={control_name}"
                }, ensure_ascii=False)
            
            result["control_type"] = target_control.element_info.control_type
            result["control_name"] = target_control.window_text()
            
            if action == "click":
                target_control.click()
            elif action == "set_text" and control_name:
                target_control.set_text(control_name)
            elif action == "get_text":
                result["text"] = target_control.window_text()
        else:
            # 直接操作窗口
            if action == "click":
                target_window.click()
            elif action == "set_focus":
                target_window.set_focus()
            elif action == "close":
                target_window.close()
        
        result["status"] = "ok"
        return json.dumps(result, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": str(e)
        }, ensure_ascii=False)


def desktop_type_into_window(title_contains: str, text: str, 
                              control_type: str = None) -> str:
    """
    向窗口输入文本 (pywinauto 备用)
    
    Args:
        title_contains: 窗口标题
        text: 要输入的文本
        control_type: 控件类型 (默认 Edit)
    """
    return desktop_click_window(
        title_contains=title_contains,
        control_type=control_type or "Edit",
        action="set_text",
        control_name=text
    )


# ============ 模块定义 ============

MODULE_DEF = {
    "name": "desktop",
    "version": "2.2.0",
    "description": "Windows 桌面控制 v2.2 - 修复命令注入/中文输入/坐标验证/按键验证等安全漏洞",
    "tools": [
        {
            "name": "desktop_screenshot",
            "description": "截取屏幕截图",
            "input_schema": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": "object",
                        "description": "截取区域",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "width": {"type": "integer"},
                            "height": {"type": "integer"}
                        }
                    },
                    "save_path": {"type": "string", "description": "保存路径"}
                }
            },
            "handler": desktop_screenshot
        },
        {
            "name": "desktop_mouse_move",
            "description": "移动鼠标到指定位置",
            "input_schema": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "目标 X 坐标"},
                    "y": {"type": "integer", "description": "目标 Y 坐标"},
                    "duration": {"type": "number", "description": "移动时间(秒)", "default": 0.5}
                },
                "required": ["x", "y"]
            },
            "handler": desktop_mouse_move
        },
        {
            "name": "desktop_mouse_click",
            "description": "鼠标点击",
            "input_schema": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X 坐标"},
                    "y": {"type": "integer", "description": "Y 坐标"},
                    "button": {
                        "type": "string",
                        "description": "按键",
                        "enum": ["left", "right", "middle"],
                        "default": "left"
                    },
                    "clicks": {"type": "integer", "description": "点击次数", "default": 1},
                    "interval": {"type": "number", "description": "点击间隔", "default": 0.1}
                }
            },
            "handler": desktop_mouse_click
        },
        {
            "name": "desktop_mouse_drag",
            "description": "鼠标拖拽",
            "input_schema": {
                "type": "object",
                "properties": {
                    "start_x": {"type": "integer", "description": "起点 X"},
                    "start_y": {"type": "integer", "description": "起点 Y"},
                    "end_x": {"type": "integer", "description": "终点 X"},
                    "end_y": {"type": "integer", "description": "终点 Y"},
                    "duration": {"type": "number", "description": "拖拽时间", "default": 1.0}
                },
                "required": ["start_x", "start_y", "end_x", "end_y"]
            },
            "handler": desktop_mouse_drag
        },
        {
            "name": "desktop_mouse_scroll",
            "description": "鼠标滚轮",
            "input_schema": {
                "type": "object",
                "properties": {
                    "clicks": {"type": "integer", "description": "滚动量 (正数向上)"},
                    "x": {"type": "integer", "description": "X 坐标"},
                    "y": {"type": "integer", "description": "Y 坐标"}
                },
                "required": ["clicks"]
            },
            "handler": desktop_mouse_scroll
        },
        {
            "name": "desktop_mouse_position",
            "description": "获取鼠标当前位置",
            "input_schema": {
                "type": "object",
                "properties": {}
            },
            "handler": desktop_mouse_position
        },
        {
            "name": "desktop_keyboard_type",
            "description": "键盘输入文本",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要输入的文本"},
                    "interval": {"type": "number", "description": "按键间隔", "default": 0.05}
                },
                "required": ["text"]
            },
            "handler": desktop_keyboard_type
        },
        {
            "name": "desktop_keyboard_press",
            "description": "按键",
            "input_schema": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "按键名 (enter/tab/esc等)"},
                    "presses": {"type": "integer", "description": "按下次数", "default": 1}
                },
                "required": ["key"]
            },
            "handler": desktop_keyboard_press
        },
        {
            "name": "desktop_keyboard_hotkey",
            "description": "组合键 (如 Ctrl+C)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "按键序列"
                    }
                },
                "required": ["keys"]
            },
            "handler": lambda keys: desktop_keyboard_hotkey(*keys)
        },
        {
            "name": "desktop_screen_size",
            "description": "获取屏幕尺寸",
            "input_schema": {
                "type": "object",
                "properties": {}
            },
            "handler": desktop_screen_size
        },
        {
            "name": "desktop_locate_on_screen",
            "description": "在屏幕上定位图像",
            "input_schema": {
                "type": "object",
                "properties": {
                    "image_path": {"type": "string", "description": "图像文件路径"},
                    "confidence": {"type": "number", "description": "匹配置信度", "default": 0.9}
                },
                "required": ["image_path"]
            },
            "handler": desktop_locate_on_screen
        },
        {
            "name": "desktop_run_app",
            "description": "运行应用程序",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "命令或程序路径"},
                    "wait": {"type": "boolean", "description": "是否等待程序结束", "default": False}
                },
                "required": ["command"]
            },
            "handler": desktop_run_app
        },
        {
            "name": "desktop_window_list",
            "description": "列出所有窗口",
            "input_schema": {
                "type": "object",
                "properties": {}
            },
            "handler": desktop_window_list
        },
        {
            "name": "desktop_window_activate",
            "description": "激活窗口",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title_pattern": {"type": "string", "description": "窗口标题模式"},
                    "handle": {"type": "integer", "description": "窗口句柄"}
                }
            },
            "handler": desktop_window_activate
        },
        {
            "name": "desktop_clipboard_get",
            "description": "获取剪贴板内容",
            "input_schema": {
                "type": "object",
                "properties": {}
            },
            "handler": desktop_clipboard_get
        },
        {
            "name": "desktop_clipboard_set",
            "description": "设置剪贴板内容",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要设置的文本"}
                },
                "required": ["text"]
            },
            "handler": desktop_clipboard_set
        },
        {
            "name": "desktop_check",
            "description": "检查桌面控制环境和后端状态",
            "input_schema": {
                "type": "object",
                "properties": {}
            },
            "handler": desktop_check
        },
        
        # Windows-MCP 风格工具 (备用后端)
        {
            "name": "desktop_set_backend",
            "description": "设置桌面控制后端 (auto/pyautogui/pywinauto)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "后端类型",
                        "enum": ["auto", "pyautogui", "pywinauto"],
                        "default": "auto"
                    }
                }
            },
            "handler": desktop_set_backend
        },
        {
            "name": "desktop_launch_app",
            "description": "启动应用程序 (Windows-MCP 风格，支持常用应用别名)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "应用名称或路径 (notepad/word/excel/chrome/firefox/edge/explorer/cmd/powershell/paint/calc)"
                    },
                    "args": {"type": "string", "description": "启动参数"},
                    "wait": {"type": "boolean", "description": "是否等待应用启动", "default": False}
                },
                "required": ["app_name"]
            },
            "handler": desktop_launch_app
        },
        {
            "name": "desktop_shell",
            "description": "执行 Shell 命令 (Windows-MCP 风格，支持 PowerShell/CMD)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "shell_type": {
                        "type": "string",
                        "description": "Shell 类型",
                        "enum": ["powershell", "cmd"],
                        "default": "powershell"
                    }
                },
                "required": ["command"]
            },
            "handler": desktop_shell
        },
        {
            "name": "desktop_get_state",
            "description": "获取桌面完整状态 (鼠标位置、活动窗口、运行应用、截图)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "capture_screenshot": {
                        "type": "boolean",
                        "description": "是否截图",
                        "default": True
                    }
                }
            },
            "handler": desktop_get_state
        },
        {
            "name": "desktop_find_window",
            "description": "查找窗口 (pywinauto 备用后端)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title_contains": {"type": "string", "description": "窗口标题包含的文本"},
                    "class_name": {"type": "string", "description": "窗口类名"}
                }
            },
            "handler": desktop_find_window
        },
        {
            "name": "desktop_click_window",
            "description": "点击窗口控件 (pywinauto 备用后端，支持 UI Automation)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title_contains": {"type": "string", "description": "窗口标题"},
                    "control_type": {"type": "string", "description": "控件类型 (Button/Edit/Text等)"},
                    "control_name": {"type": "string", "description": "控件名称/文本"},
                    "action": {
                        "type": "string",
                        "description": "操作类型",
                        "enum": ["click", "set_text", "get_text", "set_focus", "close"],
                        "default": "click"
                    }
                },
                "required": ["title_contains"]
            },
            "handler": desktop_click_window
        },
        {
            "name": "desktop_type_into_window",
            "description": "向窗口输入文本 (pywinauto 备用后端)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title_contains": {"type": "string", "description": "窗口标题"},
                    "text": {"type": "string", "description": "要输入的文本"},
                    "control_type": {"type": "string", "description": "控件类型", "default": "Edit"}
                },
                "required": ["title_contains", "text"]
            },
            "handler": desktop_type_into_window
        }
    ]
}
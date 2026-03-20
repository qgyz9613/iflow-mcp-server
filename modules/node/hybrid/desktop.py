"""
iFlow Desktop Module
Python 桌面自动化 - 零延迟原生调用
安全增强版
"""

import pyautogui
import pyperclip
import time
import os

# ============ 安全配置 ============
# FAILSAFE 安全机制：当鼠标移动到屏幕左上角(0,0)时触发异常，防止失控
# 可通过环境变量 IFLOW_FAILSAFE=false 禁用（仅用于无头服务器）
FAILSAFE_ENABLED = os.environ.get('IFLOW_FAILSAFE', 'true').lower() != 'false'
pyautogui.FAILSAFE = FAILSAFE_ENABLED
pyautogui.PAUSE = 0

# 坐标边界配置
COORDINATE_MARGIN = 100  # 允许超出屏幕边界的像素数

def _get_screen_bounds():
    """获取屏幕边界"""
    try:
        size = pyautogui.size()
        return size.width, size.height
    except:
        return 1920, 1080  # 默认值

def _validate_coordinates(x, y, check_bounds=True):
    """验证坐标是否在合理范围内"""
    if x is None or y is None:
        return False, "Coordinates cannot be None"
    
    try:
        x = float(x)
        y = float(y)
    except (ValueError, TypeError):
        return False, f"Invalid coordinate type: x={type(x)}, y={type(y)}"
    
    if check_bounds:
        screen_w, screen_h = _get_screen_bounds()
        # 允许一定的边界外范围（多屏幕场景）
        if x < -COORDINATE_MARGIN or x > screen_w * 2 + COORDINATE_MARGIN:
            return False, f"X coordinate {x} out of bounds"
        if y < -COORDINATE_MARGIN or y > screen_h * 2 + COORDINATE_MARGIN:
            return False, f"Y coordinate {y} out of bounds"
    
    return True, None

def _safe_call(func):
    """安全调用装饰器"""
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            if isinstance(result, dict):
                result['time'] = (time.time() - start) * 1000
            return result
        except pyautogui.FailSafeException:
            return {
                'status': 'error',
                'message': 'FAILSAFE triggered - mouse moved to corner',
                'time': (time.time() - start) * 1000
            }
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e),
                'time': (time.time() - start) * 1000
            }
    return wrapper

@_safe_call
def get_mouse_position():
    """获取鼠标位置"""
    pos = pyautogui.position()
    return {'status': 'ok', 'x': pos.x, 'y': pos.y}

@_safe_call
def move_mouse(x, y, duration=0):
    """移动鼠标"""
    # 参数验证
    valid, err = _validate_coordinates(x, y)
    if not valid:
        return {'status': 'error', 'message': err}
    
    # 验证duration
    try:
        duration = float(duration)
        if duration < 0 or duration > 60:  # 限制最大移动时间
            return {'status': 'error', 'message': f'Invalid duration: {duration}. Must be between 0 and 60 seconds.'}
    except (ValueError, TypeError):
        return {'status': 'error', 'message': f'Invalid duration type: {type(duration)}'}
    
    pyautogui.moveTo(x, y, duration=duration)
    return {'status': 'ok', 'x': x, 'y': y}

@_safe_call
def click(x, y, button='left', clicks=1):
    """点击"""
    # 参数验证
    valid, err = _validate_coordinates(x, y)
    if not valid:
        return {'status': 'error', 'message': err}
    
    # 验证button
    if button not in ['left', 'right', 'middle']:
        return {'status': 'error', 'message': f'Invalid button: {button}. Must be left, right, or middle.'}
    
    # 验证clicks
    try:
        clicks = int(clicks)
        if clicks < 1 or clicks > 10:
            return {'status': 'error', 'message': f'Invalid clicks: {clicks}. Must be between 1 and 10.'}
    except (ValueError, TypeError):
        return {'status': 'error', 'message': f'Invalid clicks type: {type(clicks)}'}
    
    pyautogui.click(x, y, clicks=clicks, button=button)
    return {'status': 'ok', 'x': x, 'y': y, 'button': button, 'clicks': clicks}

@_safe_call
def double_click(x, y):
    """双击"""
    valid, err = _validate_coordinates(x, y)
    if not valid:
        return {'status': 'error', 'message': err}
    
    pyautogui.doubleClick(x, y)
    return {'status': 'ok', 'x': x, 'y': y}

@_safe_call
def right_click(x, y):
    """右键点击"""
    return click(x, y, button='right')

@_safe_call
def get_screen_size():
    """获取屏幕尺寸"""
    size = pyautogui.size()
    return {'status': 'ok', 'width': size.width, 'height': size.height}

@_safe_call
def get_clipboard():
    """获取剪贴板"""
    content = pyperclip.paste()
    return {'status': 'ok', 'content': content}

@_safe_call
def set_clipboard(text):
    """设置剪贴板"""
    if text is None:
        return {'status': 'error', 'message': 'Text cannot be None'}
    if not isinstance(text, str):
        text = str(text)
    if len(text) > 1000000:  # 限制1MB
        return {'status': 'error', 'message': 'Text too long. Maximum 1MB.'}
    
    pyperclip.copy(text)
    return {'status': 'ok'}

@_safe_call
def screenshot(path=None):
    """截图"""
    if path is not None:
        # 安全检查路径
        if not isinstance(path, str):
            return {'status': 'error', 'message': 'Path must be a string'}
        # 防止路径遍历攻击
        if '..' in path or path.startswith('/') or ':' in path.split(os.sep)[0] if os.sep in path else False:
            # Windows绝对路径检测
            import re
            if not re.match(r'^[a-zA-Z]:\\', path) and '..' in path:
                return {'status': 'error', 'message': 'Invalid path: path traversal not allowed'}
        
        pyautogui.screenshot(path)
    else:
        img = pyautogui.screenshot()
        path = f'screenshot_{int(time.time()*1000)}.png'
        img.save(path)
    return {'status': 'ok', 'path': path}

@_safe_call
def get_windows():
    """获取窗口列表"""
    try:
        import pygetwindow as gw
        windows = [{'title': w.title, 'active': w.isActive} for w in gw.getAllWindows()]
        return {'status': 'ok', 'windows': windows, 'count': len(windows)}
    except ImportError:
        return {'status': 'error', 'message': 'pygetwindow not installed'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

@_safe_call
def type_text(text, interval=0):
    """输入文本 - 支持中文"""
    if text is None:
        return {'status': 'error', 'message': 'Text cannot be None'}
    if not isinstance(text, str):
        text = str(text)
    if len(text) > 10000:
        return {'status': 'error', 'message': 'Text too long. Maximum 10000 characters.'}
    
    # 检测是否包含非ASCII字符（如中文）
    has_non_ascii = any(ord(c) > 127 for c in text)
    
    if has_non_ascii:
        # 使用剪贴板粘贴方式输入中文
        pyperclip.copy(text)
        pyautogui.hotkey('ctrl', 'v')
        # 等待粘贴完成
        time.sleep(0.05)
    else:
        # ASCII字符直接输入
        pyautogui.write(text, interval=interval)
    
    return {'status': 'ok', 'text': text, 'method': 'clipboard' if has_non_ascii else 'direct'}

@_safe_call
def press_key(key):
    """按键"""
    if key is None:
        return {'status': 'error', 'message': 'Key cannot be None'}
    if not isinstance(key, str):
        key = str(key)
    
    # 验证按键名称
    valid_keys = pyautogui.KEYBOARD_KEYS if hasattr(pyautogui, 'KEYBOARD_KEYS') else []
    if valid_keys and key not in valid_keys:
        return {'status': 'error', 'message': f'Invalid key: {key}'}
    
    pyautogui.press(key)
    return {'status': 'ok', 'key': key}

@_safe_call
def hotkey(*keys):
    """热键"""
    if not keys:
        return {'status': 'error', 'message': 'At least one key required'}
    
    # 验证按键
    valid_keys = pyautogui.KEYBOARD_KEYS if hasattr(pyautogui, 'KEYBOARD_KEYS') else []
    for key in keys:
        if not isinstance(key, str):
            return {'status': 'error', 'message': f'Invalid key type: {type(key)}'}
        if valid_keys and key not in valid_keys:
            return {'status': 'error', 'message': f'Invalid key: {key}'}
    
    pyautogui.hotkey(*keys)
    return {'status': 'ok', 'keys': list(keys)}

@_safe_call
def scroll(clicks, x=None, y=None):
    """滚动"""
    if clicks is None:
        return {'status': 'error', 'message': 'Clicks cannot be None'}
    
    try:
        clicks = int(clicks)
        if abs(clicks) > 1000:
            return {'status': 'error', 'message': f'Scroll amount too large: {clicks}. Maximum 1000.'}
    except (ValueError, TypeError):
        return {'status': 'error', 'message': f'Invalid clicks type: {type(clicks)}'}
    
    # 如果提供了坐标，验证它们
    if x is not None and y is not None:
        valid, err = _validate_coordinates(x, y)
        if not valid:
            return {'status': 'error', 'message': err}
    
    pyautogui.scroll(clicks, x=x, y=y)
    return {'status': 'ok', 'clicks': clicks}

@_safe_call
def drag(start_x, start_y, end_x, end_y, duration=0):
    """拖拽"""
    # 验证起始坐标
    valid, err = _validate_coordinates(start_x, start_y)
    if not valid:
        return {'status': 'error', 'message': f'Start coordinates invalid: {err}'}
    
    # 验证结束坐标
    valid, err = _validate_coordinates(end_x, end_y)
    if not valid:
        return {'status': 'error', 'message': f'End coordinates invalid: {err}'}
    
    # 验证duration
    try:
        duration = float(duration)
        if duration < 0 or duration > 60:
            return {'status': 'error', 'message': f'Invalid duration: {duration}. Must be between 0 and 60.'}
    except (ValueError, TypeError):
        return {'status': 'error', 'message': f'Invalid duration type: {type(duration)}'}
    
    pyautogui.moveTo(start_x, start_y)
    pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
    return {'status': 'ok'}

# 导出所有函数
__all__ = [
    'get_mouse_position', 'move_mouse', 'click', 'double_click', 'right_click',
    'get_screen_size', 'get_clipboard', 'set_clipboard', 'screenshot',
    'get_windows', 'type_text', 'press_key', 'hotkey', 'scroll', 'drag'
]

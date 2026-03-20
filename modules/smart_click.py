# -*- coding: utf-8 -*-
"""
智能点击工具 - 一次或两次完成精准点击
使用方法：
    from smart_click import smart_click
    smart_click("点击精选按钮")
"""
import ctypes
import time
import os
from PIL import ImageGrab, ImageDraw, ImageFont
import pyautogui

# 抖音窗口句柄缓存
_window_handles = {}

# 截图保存目录
SCREENSHOTS_DIR = r"C:\Users\admin\.iflow\desktop_data\screenshots"


def _ensure_screenshots_dir():
    """确保截图目录存在"""
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


def is_valid_hwnd(hwnd):
    """验证窗口句柄是否有效"""
    if not hwnd or hwnd <= 0:
        return False
    # 检查窗口是否存在
    return ctypes.windll.user32.IsWindow(hwnd) != 0


def validate_region(region):
    """验证并修正region参数，确保尺寸有效"""
    if not region or len(region) != 4:
        return None
    
    x1, y1, x2, y2 = region
    
    # 确保坐标顺序正确
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    
    # 确保最小尺寸至少为10像素
    if x2 - x1 < 10 or y2 - y1 < 10:
        return None
    
    return (x1, y1, x2, y2)


def validate_coordinates(x, y):
    """验证坐标是否有效（非负且在合理范围内）"""
    if x is None or y is None:
        return False
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return False
    # 获取屏幕尺寸作为边界
    try:
        screen_width, screen_height = pyautogui.size()
        return 0 <= x <= screen_width and 0 <= y <= screen_height
    except Exception:
        # 如果无法获取屏幕尺寸，至少检查非负
        return x >= 0 and y >= 0


def get_window_rect(hwnd):
    """获取窗口位置，带错误处理"""
    class RECT(ctypes.Structure):
        _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long), 
                    ('right', ctypes.c_long), ('bottom', ctypes.c_long)]
    
    # 验证句柄有效性
    if not is_valid_hwnd(hwnd):
        return None
    
    rect = RECT()
    result = ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    
    if result == 0:
        return None
    
    # 验证窗口尺寸有效性
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None
    
    return rect


def get_douyin_hwnd():
    """获取抖音窗口句柄"""
    # 尝试通过窗口标题查找
    hwnd = ctypes.windll.user32.FindWindowW(None, "抖音")
    if hwnd and is_valid_hwnd(hwnd):
        return hwnd
    
    # 未找到有效窗口，返回None而不是硬编码句柄
    return None


def capture_with_mouse(hwnd, region=None, mouse_pos=None):
    """截图并标注鼠标位置"""
    # 验证窗口句柄
    if not is_valid_hwnd(hwnd):
        raise ValueError("无效的窗口句柄")
    
    rect = get_window_rect(hwnd)
    if rect is None:
        raise ValueError("无法获取窗口位置")
    
    # 验证并修正region
    if region:
        region = validate_region(region)
        if region is None:
            raise ValueError("无效的region参数")
        x1 = rect.left + region[0]
        y1 = rect.top + region[1]
        x2 = rect.left + region[2]
        y2 = rect.top + region[3]
    else:
        x1, y1 = rect.left, rect.top
        x2, y2 = rect.right, rect.bottom
    
    # 确保坐标有效（非负）
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = max(0, x2)
    y2 = max(0, y2)
    
    # 验证坐标边界
    if x1 >= x2 or y1 >= y2:
        raise ValueError("计算后的截图区域无效")
    
    screenshot = ImageGrab.grab(bbox=(x1, y1, x2, y2))
    
    # 标注鼠标位置
    if mouse_pos:
        mx, my = mouse_pos
        # 验证鼠标坐标
        if validate_coordinates(mx, my):
            # 转换到截图坐标
            local_x = mx - x1
            local_y = my - y1
            
            # 确保在截图范围内
            width, height = screenshot.size
            if 0 <= local_x <= width and 0 <= local_y <= height:
                draw = ImageDraw.Draw(screenshot)
                r = 15
                # 绿色十字准星
                draw.ellipse([local_x-r, local_y-r, local_x+r, local_y+r], outline='lime', width=3)
                draw.line([local_x-r, local_y, local_x+r, local_y], fill='lime', width=2)
                draw.line([local_x, local_y-r, local_x, local_y+r], fill='lime', width=2)
                # 坐标文字
                draw.text((local_x+20, local_y-10), f'({mx},{my})', fill='lime')
    
    return screenshot, (x1, y1, x2, y2)


def add_grid(image, step=25):
    """添加坐标刻度网格"""
    draw = ImageDraw.Draw(image)
    width, height = image.size
    
    # 验证图像尺寸
    if width <= 0 or height <= 0:
        return image
    
    # 垂直线
    for x in range(0, width, step):
        draw.line([(x, 0), (x, height)], fill='cyan', width=1)
        if x % 50 == 0:
            draw.text((x+2, 2), str(x), fill='yellow')
    
    # 水平线
    for y in range(0, height, step):
        draw.line([(0, y), (width, y)], fill='cyan', width=1)
        if y % 50 == 0:
            draw.text((2, y+2), str(y), fill='yellow')
    
    return image


def find_element_position(hwnd, target_text, region=(0, 0, 250, 350)):
    """
    查找元素位置（需要配合AI视觉分析）
    返回: (屏幕x, 屏幕y, 截图路径)
    """
    # 验证窗口句柄
    if not is_valid_hwnd(hwnd):
        return None, None, None, "无效的窗口句柄"
    
    rect = get_window_rect(hwnd)
    if rect is None:
        return None, None, None, "无法获取窗口位置"
    
    # 验证并修正region
    validated_region = validate_region(region)
    if validated_region is None:
        # 使用默认region
        validated_region = (0, 0, 250, 350)
    
    # 截取指定区域
    x1 = rect.left + validated_region[0]
    y1 = rect.top + validated_region[1]
    x2 = rect.left + validated_region[2]
    y2 = rect.top + validated_region[3]
    
    # 确保坐标有效（非负）
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = max(0, x2)
    y2 = max(0, y2)
    
    # 验证坐标边界
    if x1 >= x2 or y1 >= y2:
        return None, None, None, "计算后的截图区域无效"
    
    try:
        screenshot = ImageGrab.grab(bbox=(x1, y1, x2, y2))
    except Exception as e:
        return None, None, None, f"截图失败: {str(e)}"
    
    # 添加刻度网格
    screenshot = add_grid(screenshot)
    
    # 确保目录存在
    _ensure_screenshots_dir()
    
    save_path = os.path.join(SCREENSHOTS_DIR, 'locate_target.png')
    try:
        screenshot.save(save_path)
    except Exception as e:
        return None, None, None, f"保存截图失败: {str(e)}"
    
    return save_path, (x1, y1), (x2, y2), None


def verify_and_click(hwnd, screen_x, screen_y, target_name="目标"):
    """
    验证并点击：移动鼠标 -> 截图验证 -> 确认后点击
    返回: (success, message)
    """
    # 验证窗口句柄
    if not is_valid_hwnd(hwnd):
        return None, None, "无效的窗口句柄"
    
    # 验证坐标
    if not validate_coordinates(screen_x, screen_y):
        return None, None, "无效的坐标参数"
    
    # 移动鼠标到目标位置
    try:
        pyautogui.moveTo(screen_x, screen_y)
        time.sleep(0.1)
    except Exception as e:
        return None, None, f"移动鼠标失败: {str(e)}"
    
    # 获取鼠标位置
    mx, my = pyautogui.position()
    
    # 截图验证
    rect = get_window_rect(hwnd)
    if rect is None:
        return None, None, "无法获取窗口位置"
    
    region = (0, 0, 250, 350)
    x1 = rect.left + region[0]
    y1 = rect.top + region[1]
    x2 = rect.left + region[2]
    y2 = rect.top + region[3]
    
    # 确保坐标有效（非负）
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = max(0, x2)
    y2 = max(0, y2)
    
    # 验证坐标边界
    if x1 >= x2 or y1 >= y2:
        return None, None, "计算后的截图区域无效"
    
    try:
        screenshot = ImageGrab.grab(bbox=(x1, y1, x2, y2))
    except Exception as e:
        return None, None, f"截图失败: {str(e)}"
    
    # 标注鼠标
    local_x = mx - x1
    local_y = my - y1
    
    # 确保在截图范围内
    width, height = screenshot.size
    if 0 <= local_x <= width and 0 <= local_y <= height:
        draw = ImageDraw.Draw(screenshot)
        r = 15
        draw.ellipse([local_x-r, local_y-r, local_x+r, local_y+r], outline='lime', width=3)
        draw.line([local_x-r, local_y, local_x+r, local_y], fill='lime', width=2)
        draw.line([local_x, local_y-r, local_x, local_y+r], fill='lime', width=2)
    
    # 确保目录存在
    _ensure_screenshots_dir()
    
    verify_path = os.path.join(SCREENSHOTS_DIR, 'verify_mouse.png')
    try:
        screenshot.save(verify_path)
    except Exception as e:
        return None, None, f"保存截图失败: {str(e)}"
    
    return verify_path, (mx, my), None


def click_at(hwnd, window_x, window_y):
    """在窗口内坐标点击（自动转换为屏幕坐标）"""
    # 验证窗口句柄
    if not is_valid_hwnd(hwnd):
        raise ValueError("无效的窗口句柄")
    
    # 验证窗口内坐标
    if window_x < 0 or window_y < 0:
        raise ValueError("窗口坐标不能为负数")
    
    rect = get_window_rect(hwnd)
    if rect is None:
        raise ValueError("无法获取窗口位置")
    
    screen_x = rect.left + window_x
    screen_y = rect.top + window_y
    
    # 验证屏幕坐标
    if not validate_coordinates(screen_x, screen_y):
        raise ValueError(f"计算后的屏幕坐标无效: ({screen_x}, {screen_y})")
    
    pyautogui.click(screen_x, screen_y)
    return screen_x, screen_y


# 预设的抖音按钮坐标（窗口内坐标）
DOUYIN_BUTTONS = {
    '精选': (88, 100),
    '推荐': (88, 150),
    '关注': (88, 250),
    '朋友': (88, 300),
    '我的': (88, 350),
}


def quick_click(button_name):
    """快速点击预设按钮"""
    hwnd = get_douyin_hwnd()
    
    # 检查是否找到有效窗口
    if hwnd is None:
        return None, "未找到抖音窗口，请确保抖音已打开"
    
    if button_name not in DOUYIN_BUTTONS:
        return None, f"未知按钮: {button_name}，可用按钮: {list(DOUYIN_BUTTONS.keys())}"
    
    try:
        wx, wy = DOUYIN_BUTTONS[button_name]
        sx, sy = click_at(hwnd, wx, wy)
        return (sx, sy), f"点击 {button_name} @ ({sx}, {sy})"
    except ValueError as e:
        return None, f"点击失败: {str(e)}"
    except Exception as e:
        return None, f"点击失败: {str(e)}"
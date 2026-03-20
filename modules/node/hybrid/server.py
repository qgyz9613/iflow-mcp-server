"""
iFlow HTTP Server
提供桌面自动化 HTTP 接口
安全增强版
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import time
import os
from functools import wraps
from collections import defaultdict
import threading

# 导入桌面模块
from desktop import *

app = Flask(__name__)
CORS(app)

# ============ 安全配置 ============
MAX_COMMANDS = 100  # 批量操作最大命令数
RATE_LIMIT_REQUESTS = 60  # 每分钟最大请求数
RATE_LIMIT_WINDOW = 60  # 速率限制窗口（秒）

# 简单的速率限制器
rate_limiter = defaultdict(list)
rate_lock = threading.Lock()

def check_rate_limit(client_ip):
    """检查速率限制"""
    with rate_lock:
        now = time.time()
        # 清理过期记录
        rate_limiter[client_ip] = [t for t in rate_limiter[client_ip] if now - t < RATE_LIMIT_WINDOW]
        
        if len(rate_limiter[client_ip]) >= RATE_LIMIT_REQUESTS:
            return False
        
        rate_limiter[client_ip].append(now)
        return True

def rate_limit(f):
    """速率限制装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = request.remote_addr or 'unknown'
        if not check_rate_limit(client_ip):
            return jsonify({
                'status': 'error',
                'message': f'Rate limit exceeded. Max {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW} seconds.'
            }), 429
        return f(*args, **kwargs)
    return decorated_function

def validate_coordinates(x, y, allow_none=False):
    """验证坐标参数"""
    if allow_none and (x is None or y is None):
        return True
    
    if x is None or y is None:
        return False, "Missing coordinates (x, y)"
    
    try:
        x = float(x)
        y = float(y)
    except (ValueError, TypeError):
        return False, "Invalid coordinate values"
    
    # 获取屏幕尺寸进行边界检查
    try:
        screen = pyautogui.size()
        if x < 0 or x > screen.width * 2:  # 允许多屏幕
            return False, f"X coordinate {x} out of reasonable bounds"
        if y < 0 or y > screen.height * 2:
            return False, f"Y coordinate {y} out of reasonable bounds"
    except:
        pass  # 如果无法获取屏幕尺寸，跳过边界检查
    
    return True, None

def validate_params(method, args):
    """验证参数"""
    errors = []
    
    if method in ['moveMouse', 'move_mouse']:
        if 'x' not in args or 'y' not in args:
            errors.append("Missing required parameters: x, y")
        else:
            valid, err = validate_coordinates(args['x'], args['y'])
            if not valid:
                errors.append(err)
    
    elif method in ['click', 'doubleClick', 'double_click', 'rightClick', 'right_click']:
        if 'x' not in args or 'y' not in args:
            errors.append("Missing required parameters: x, y")
        else:
            valid, err = validate_coordinates(args['x'], args['y'])
            if not valid:
                errors.append(err)
        
        # 验证button参数
        if 'button' in args and args['button'] not in ['left', 'right', 'middle']:
            errors.append(f"Invalid button: {args['button']}. Must be 'left', 'right', or 'middle'")
        
        # 验证clicks参数
        if 'clicks' in args:
            try:
                clicks = int(args['clicks'])
                if clicks < 1 or clicks > 10:
                    errors.append(f"Invalid clicks: {clicks}. Must be between 1 and 10")
            except (ValueError, TypeError):
                errors.append("Invalid clicks value")
    
    elif method in ['drag']:
        required = ['startX', 'startY', 'endX', 'endY']
        for param in required:
            if param not in args:
                errors.append(f"Missing required parameter: {param}")
        
        if len(errors) == 0:
            valid1, err1 = validate_coordinates(args['startX'], args['startY'])
            if not valid1:
                errors.append(f"Start coordinates invalid: {err1}")
            valid2, err2 = validate_coordinates(args['endX'], args['endY'])
            if not valid2:
                errors.append(f"End coordinates invalid: {err2}")
    
    elif method in ['scroll']:
        if 'clicks' not in args:
            errors.append("Missing required parameter: clicks")
        else:
            try:
                clicks = int(args['clicks'])
                if abs(clicks) > 1000:  # 合理的滚动量限制
                    errors.append(f"Scroll amount too large: {clicks}")
            except (ValueError, TypeError):
                errors.append("Invalid clicks value")
        
        # 可选坐标验证
        if 'x' in args and 'y' in args:
            valid, err = validate_coordinates(args['x'], args['y'])
            if not valid:
                errors.append(err)
    
    elif method in ['typeText', 'type_text']:
        if 'text' not in args:
            errors.append("Missing required parameter: text")
        elif len(args['text']) > 10000:  # 限制文本长度
            errors.append("Text too long. Maximum 10000 characters.")
    
    elif method in ['pressKey', 'press_key', 'hotkey']:
        if method in ['pressKey', 'press_key'] and 'key' not in args:
            errors.append("Missing required parameter: key")
        if method == 'hotkey' and 'keys' not in args:
            errors.append("Missing required parameter: keys")
    
    return errors

@app.route('/api/ping', methods=['GET'])
@rate_limit
def ping():
    return jsonify({'status': 'ok', 'time': 0})

@app.route('/api/desktop/<method>', methods=['POST'])
@rate_limit
def call_method(method):
    """调用桌面方法"""
    try:
        args = request.get_json() or {}
        
        # 方法映射
        methods = {
            'getMousePosition': get_mouse_position,
            'moveMouse': move_mouse,
            'click': click,
            'doubleClick': double_click,
            'rightClick': right_click,
            'getScreenSize': get_screen_size,
            'getClipboard': get_clipboard,
            'setClipboard': set_clipboard,
            'screenshot': screenshot,
            'getWindows': get_windows,
            'typeText': type_text,
            'pressKey': press_key,
            'hotkey': hotkey,
            'scroll': scroll,
            'drag': drag
        }
        
        if method not in methods:
            return jsonify({'status': 'error', 'message': f'Unknown method: {method}'})
        
        # 参数验证
        validation_errors = validate_params(method, args)
        if validation_errors:
            return jsonify({'status': 'error', 'message': 'Validation failed', 'errors': validation_errors}), 400
        
        # 转换参数名 (camelCase -> snake_case)
        arg_map = {
            'getMousePosition': {},
            'moveMouse': {'duration': 'duration'},
            'click': {'button': 'button', 'clicks': 'clicks'},
            'screenshot': {'path': 'path'},
            'typeText': {'interval': 'interval'},
            'scroll': {'clicks': 'clicks', 'x': 'x', 'y': 'y'},
            'drag': {'startX': 'start_x', 'startY': 'start_y', 'endX': 'end_x', 'endY': 'end_y', 'duration': 'duration'}
        }
        
        if method in arg_map:
            for new_key, old_key in arg_map[method].items():
                if new_key in args:
                    args[old_key] = args.pop(new_key)
        
        result = methods[method](**args)
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/batch', methods=['POST'])
@rate_limit
def batch():
    """批量执行"""
    try:
        data = request.get_json() or {}
        commands = data.get('commands', [])
        
        # 限制批量命令数量
        if len(commands) > MAX_COMMANDS:
            return jsonify({
                'status': 'error',
                'message': f'Too many commands. Maximum is {MAX_COMMANDS}, got {len(commands)}'
            }), 400
        
        if len(commands) == 0:
            return jsonify({'status': 'ok', 'results': [], 'message': 'No commands to execute'})
        
        results = []
        
        for i, cmd in enumerate(commands):
            method = cmd.get('method')
            args = cmd.get('args', {})
            
            # 验证每个命令
            validation_errors = validate_params(method, args)
            if validation_errors:
                results.append({
                    'status': 'error',
                    'message': 'Validation failed',
                    'errors': validation_errors,
                    'command_index': i
                })
                continue
            
            # 递归调用
            with app.test_client() as client:
                resp = client.post(f'/api/desktop/{method}', json=args)
                results.append(resp.get_json())
        
        return jsonify({'status': 'ok', 'results': results, 'count': len(results)})
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

def main():
    """启动服务器"""
    print('iFlow Desktop Server starting...')
    print('Port: 9876')
    print('Endpoints:')
    print('  GET  /api/ping')
    print('  POST /api/desktop/<method>')
    print('  POST /api/batch')
    print(f'Rate limit: {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW} seconds')
    print(f'Batch limit: {MAX_COMMANDS} commands per request')
    
    # 尝试使用生产服务器
    try:
        from waitress import serve
        print('Using Waitress production server')
        serve(app, host='127.0.0.1', port=9876, threads=4)
    except ImportError:
        print('Warning: Waitress not installed, using Flask development server')
        print('Install waitress for production: pip install waitress')
        # 仅在开发模式下使用Flask服务器
        if os.environ.get('IFLOW_DEV_MODE') == '1':
            app.run(host='127.0.0.1', port=9876, threaded=True)
        else:
            print('ERROR: Production server not available. Set IFLOW_DEV_MODE=1 for development.')
            raise RuntimeError('Waitress not installed. Run: pip install waitress')

if __name__ == '__main__':
    main()

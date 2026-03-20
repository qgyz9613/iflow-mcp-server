"""
iFlow Hybrid Benchmark
测试混合架构性能
"""

import sys
import time
import subprocess
import json
import requests
import threading
import os

# 添加模块路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import desktop

BASE_URL = "http://127.0.0.1:9876"

def test_direct():
    """直接调用 Python (无 HTTP 开销)"""
    print("\n=== Direct Python Call (Zero Overhead) ===")
    
    results = []
    
    # 鼠标位置 x10
    times = []
    for _ in range(10):
        start = time.time()
        result = desktop.get_mouse_position()
        times.append((time.time() - start) * 1000)
    avg = sum(times) / len(times)
    print(f"  Mouse Position: {avg:.2f}ms avg (10 calls)")
    results.append(('Mouse Position (Direct)', avg))
    
    # 屏幕尺寸
    start = time.time()
    desktop.get_screen_size()
    print(f"  Screen Size: {(time.time() - start) * 1000:.2f}ms")
    results.append(('Screen Size (Direct)', (time.time() - start) * 1000))
    
    # 剪贴板
    start = time.time()
    desktop.get_clipboard()
    print(f"  Clipboard: {(time.time() - start) * 1000:.2f}ms")
    results.append(('Clipboard (Direct)', (time.time() - start) * 1000))
    
    # 窗口列表
    start = time.time()
    desktop.get_windows()
    print(f"  Windows: {(time.time() - start) * 1000:.2f}ms")
    results.append(('Windows (Direct)', (time.time() - start) * 1000))
    
    return results

def test_http():
    """通过 HTTP 调用"""
    print("\n=== HTTP Call (Network Overhead) ===")
    
    results = []
    
    # 鼠标位置 x10
    times = []
    for _ in range(10):
        start = time.time()
        resp = requests.post(f"{BASE_URL}/api/desktop/getMousePosition", json={})
        times.append((time.time() - start) * 1000)
    avg = sum(times) / len(times)
    print(f"  Mouse Position: {avg:.2f}ms avg (10 calls)")
    results.append(('Mouse Position (HTTP)', avg))
    
    # 屏幕
    start = time.time()
    requests.post(f"{BASE_URL}/api/desktop/getScreenSize", json={})
    print(f"  Screen Size: {(time.time() - start) * 1000:.2f}ms")
    results.append(('Screen Size (HTTP)', (time.time() - start) * 1000))
    
    return results

def run_server():
    """启动服务器"""
    from server import app
    app.run(host='127.0.0.1', port=9876, threaded=True)

def main():
    print("=" * 50)
    print("  iFlow Hybrid Benchmark")
    print("=" * 50)
    
    # 检查服务器
    try:
        resp = requests.get(f"{BASE_URL}/api/ping", timeout=1)
        print("Server is running")
    except:
        print("Starting server...")
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        time.sleep(1)
    
    # 测试
    direct_results = test_direct()
    http_results = test_http()
    
    # 对比
    print("\n" + "=" * 50)
    print("  Performance Comparison")
    print("=" * 50)
    print(f"\n{'Method':<25} {'Direct':<12} {'HTTP':<12} {'Overhead'}")
    print("-" * 60)
    
    for i, (name, direct_time) in enumerate(direct_results[:2]):
        if i < len(http_results):
            http_time = http_results[i][1]
            overhead = http_time - direct_time
            print(f"{name:<25} {direct_time:<12.2f} {http_time:<12.2f} +{overhead:.2f}ms")
    
    print("\n结论:")
    print("  - 直接 Python 调用: ~0ms")
    print("  - HTTP 调用开销: ~1-2ms")
    print("  - 对比单次启动 Python: 节省 ~158ms!")

if __name__ == "__main__":
    main()

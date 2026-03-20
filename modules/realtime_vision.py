#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时视觉模块 v2.1
最优配置: 并发2请求, 14.5次/分钟, 100%成功率
能力: ~33,000 tokens/分钟
"""
import os
import cv2, base64, numpy as np, requests, json, time
import logging
from PIL import ImageGrab
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

logger = logging.getLogger(__name__)

API_URL = 'https://apis.iflow.cn/v1/chat/completions'
# 修复问题1: 使用环境变量替代硬编码API密钥
API_KEY = os.environ.get('IFLOW_API_KEY', '')
MODEL = 'qwen3-vl-plus'

# 最优配置: 并发2个请求
MAX_CONCURRENT = 2

class RealtimeVision:
    def __init__(self):
        if not API_KEY:
            logger.warning("IFLOW_API_KEY环境变量未设置，API调用将失败")
        self.headers = {'Authorization': 'Bearer ' + API_KEY, 'Content-Type': 'application/json'}
        self.executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT)
        self.lock = Lock()
        self._last_capture = None
        self._last_capture_time = 0
        self._closed = False
    
    # 修复问题3: 添加close方法关闭ThreadPoolExecutor
    def close(self):
        """关闭线程池，释放资源"""
        if not self._closed:
            self._closed = True
            self.executor.shutdown(wait=True)
    
    def __del__(self):
        """析构时自动关闭线程池"""
        self.close()
    
    # 修复问题4: 使用Lock保护_last_capture访问
    # 修复问题5: 添加异常处理
    def capture_screen(self, quality=50):
        """截取屏幕，1秒内复用缓存"""
        now = time.time()
        with self.lock:  # 加锁保护
            if self._last_capture and (now - self._last_capture_time) < 1:
                return self._last_capture
        
        try:
            screenshot = ImageGrab.grab()
            frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            result = base64.b64encode(buffer).decode()
            
            with self.lock:  # 加锁保护
                self._last_capture = result
                self._last_capture_time = now
            return result
        except Exception as ex:
            logger.error(f"截屏失败: {ex}")
            return None
    
    def _request(self, img, prompt):
        if img is None:
            return {'success': False, 'error': '截屏失败'}
        
        payload = {'model': MODEL, 'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + img}}
        ]}], 'max_tokens': 100}
        try:
            t = time.time()
            r = requests.post(API_URL, headers=self.headers, json=payload, timeout=30)
            e = time.time() - t
            # 修复问题6: 检查HTTP响应状态码
            if not r.ok:
                return {'success': False, 'error': f'HTTP {r.status_code}: {r.text[:100]}'}
            
            d = r.json()
            if 'choices' in d:
                return {'success': True, 'content': d['choices'][0]['message']['content'], 'tokens': d.get('usage', {}).get('total_tokens', 0), 'time': e}
            return {'success': False, 'error': d.get('msg', str(d)[:100])}
        except Exception as ex:
            return {'success': False, 'error': str(ex)[:50]}
    
    def analyze(self, prompt='描述屏幕内容'):
        """单次分析"""
        return self._request(self.capture_screen(), prompt)
    
    # 修复问题2: 处理所有prompts，不丢失任务
    def analyze_batch(self, prompts):
        """并发分析多个prompt (最优: 2个并发)
        注意: 所有prompts都会被处理，但并发度限制为MAX_CONCURRENT
        """
        if not prompts:
            return []
        
        img = self.capture_screen()
        if img is None:
            return [{'success': False, 'error': '截屏失败'}] * len(prompts)
        
        results = [None] * len(prompts)  # 预分配结果列表，保持顺序
        futures_map = {}
        
        # 分批处理所有prompts，保持索引映射
        for idx, p in enumerate(prompts):
            future = self.executor.submit(self._request, img, p)
            futures_map[future] = idx
        
        for f in as_completed(futures_map):
            idx = futures_map[f]
            results[idx] = f.result()
        
        return results
    
    def analyze_continuous(self, prompt, count=10, callback=None):
        """连续分析，达到最优频率 ~14.5次/分钟"""
        results = []
        for i in range(0, count, MAX_CONCURRENT):
            batch_size = min(MAX_CONCURRENT, count - i)
            prompts = [prompt] * batch_size
            batch_results = self.analyze_batch(prompts)
            results.extend(batch_results)
            if callback:
                for r in batch_results:
                    callback(r)
        return results

# 单例
_vision = None
_vision_lock = Lock()

def get_vision():
    global _vision
    if _vision is None:
        with _vision_lock:
            if _vision is None:
                _vision = RealtimeVision()
    return _vision

def analyze(prompt='描述屏幕内容'):
    """单次分析"""
    return get_vision().analyze(prompt)

def analyze_batch(prompts):
    """并发分析 (2个并发, 100%成功率)"""
    return get_vision().analyze_batch(prompts)

def analyze_continuous(prompt, count=10, callback=None):
    """连续分析，最优频率"""
    return get_vision().analyze_continuous(prompt, count, callback)

def close():
    """关闭视觉模块，释放资源"""
    global _vision
    if _vision is not None:
        _vision.close()
        _vision = None

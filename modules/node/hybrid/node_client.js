/**
 * iFlow Node.js Desktop Client
 * 连接 Python HTTP 服务
 */

const http = require('http');

const PORT = 9876;
const HOST = '127.0.0.1';

// 发送请求
function request(method, args = {}) {
  const start = Date.now();
  
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(args);
    
    const req = http.request({
      hostname: HOST,
      port: PORT,
      path: `/api/desktop/${method}`,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data)
      },
      timeout: 5000
    }, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => {
        try {
          const result = JSON.parse(body);
          result.clientTime = Date.now() - start;
          resolve(result);
        } catch (e) {
          reject(e);
        }
      });
    });
    
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Timeout'));
    });
    
    req.write(data);
    req.end();
  });
}

// 检查服务状态
async function ping() {
  return new Promise((resolve) => {
    http.get(`http://${HOST}:${PORT}/api/ping`, (res) => {
      resolve(true);
    }).on('error', () => resolve(false));
  });
}

// API 方法
const desktop = {
  ping,
  getMousePosition: () => request('getMousePosition'),
  moveMouse: (x, y, duration = 0) => request('moveMouse', { x, y, duration }),
  click: (x, y, button = 'left', clicks = 1) => request('click', { x, y, button, clicks }),
  doubleClick: (x, y) => request('doubleClick', { x, y }),
  rightClick: (x, y) => request('rightClick', { x, y }),
  getScreenSize: () => request('getScreenSize'),
  getClipboard: () => request('getClipboard'),
  setClipboard: (text) => request('setClipboard', { text }),
  screenshot: (path) => request('screenshot', { path }),
  getWindows: () => request('getWindows'),
  typeText: (text, interval = 0) => request('typeText', { text, interval }),
  pressKey: (key) => request('pressKey', { key }),
  hotkey: (...keys) => request('hotkey', { keys }),
  scroll: (clicks, x, y) => request('scroll', { clicks, x, y }),
  drag: (startX, startY, endX, endY, duration = 0) => request('drag', { startX, startY, endX, endY, duration }),
  
  // 批量执行
  batch: async (commands) => {
    const start = Date.now();
    return new Promise((resolve, reject) => {
      const data = JSON.stringify({ commands });
      
      const req = http.request({
        hostname: HOST,
        port: PORT,
        path: '/api/batch',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(data)
        }
      }, (res) => {
        let body = '';
        res.on('data', chunk => body += chunk);
        res.on('end', () => {
          try {
            const result = JSON.parse(body);
            result.clientTime = Date.now() - start;
            resolve(result);
          } catch (e) {
            reject(e);
          }
        });
      });
      
      req.on('error', reject);
      req.write(data);
      req.end();
    });
  }
};

module.exports = desktop;
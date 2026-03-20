/**
 * iFlow Hybrid Architecture
 * Python 桌面服务 + Node.js 数据处理
 */

const { spawn } = require('child_process');
const path = require('path');
const desktop = require('./node_client');
const files = require('../modules/files');
// memory 模块已移除 - 使用 iFlow 内置记忆系统
const session = require('../modules/session');
const cache = require('../modules/cache');
const state = require('../modules/state');
const triage = require('../modules/triage');

let serverProcess = null;

// 启动 Python 服务
async function start() {
  if (serverProcess) return true;
  
  const serverPath = path.join(__dirname, 'server.py');
  
  return new Promise((resolve, reject) => {
    serverProcess = spawn('python', [serverPath], {
      cwd: __dirname,
      stdio: ['ignore', 'pipe', 'pipe']
    });
    
    serverProcess.stdout.on('data', (data) => {
      console.log('[Python]', data.toString().trim());
    });
    
    serverProcess.stderr.on('data', (data) => {
      console.error('[Python Error]', data.toString().trim());
    });
    
    serverProcess.on('close', () => {
      serverProcess = null;
    });
    
    // 等待服务启动
    setTimeout(async () => {
      const ready = await desktop.ping();
      if (ready) {
        resolve(true);
      } else {
        reject(new Error('Server failed to start'));
      }
    }, 1000);
  });
}

// 停止服务
function stop() {
  if (serverProcess) {
    serverProcess.kill();
    serverProcess = null;
  }
}

// 获取状态
async function getStatus() {
  const ready = await desktop.ping();
  return {
    status: ready ? 'running' : 'stopped',
    python: ready,
    node: true
  };
}

// 导出
module.exports = {
  // 生命周期
  start,
  stop,
  getStatus,
  
  // Python 桌面操作 (通过 HTTP)
  desktop,
  
  // Node.js 数据处理 (直接调用)
  files,
  // memory 模块已移除 - 使用 iFlow 内置记忆系统
  session,
  cache,
  state,
  triage,
  
  // 版本
  VERSION: '1.0.0'
};

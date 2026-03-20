/**
 * iFlow Session Write Lock Module
 * 会话写入锁模块（基于OpenClaw session-write-lock设计）
 * 
 * 功能:
 * - 文件锁保护并发写入
 * - 过期锁检测与清理
 * - 进程存活检测
 * - 看门狗定时检查
 */

const fs = require('fs');
const path = require('path');

// ==================== 常量 ====================

const DEFAULT_STALE_MS = 30 * 60 * 1000; // 30分钟过期
const DEFAULT_MAX_HOLD_MS = 5 * 60 * 1000; // 5分钟最大持有
const DEFAULT_WATCHDOG_INTERVAL_MS = 60_000; // 1分钟看门狗间隔
const DEFAULT_TIMEOUT_GRACE_MS = 2 * 60 * 1000; // 2分钟超时宽限

// ==================== 锁状态存储 ====================

const HELD_LOCKS = new Map(); // lockPath -> HeldLock

const cleanupState = {
  registered: false,
  cleanupHandlers: new Map()
};

const watchdogState = {
  started: false,
  intervalMs: DEFAULT_WATCHDOG_INTERVAL_MS,
  timer: null
};

// ==================== 辅助函数 ====================

/**
 * 解析正数毫秒
 */
function resolvePositiveMs(value, fallback, opts = {}) {
  const { allowInfinity = false } = opts;
  
  if (typeof value !== 'number' || isNaN(value) || value <= 0) {
    return fallback;
  }
  
  if (!allowInfinity && !isFinite(value)) {
    return fallback;
  }
  
  return value;
}

/**
 * 检查PID是否存活
 */
function isPidAlive(pid) {
  if (!pid || typeof pid !== 'number') return false;
  
  try {
    // Windows: 使用tasklist
    if (process.platform === 'win32') {
      const result = require('child_process').execSync(
        `tasklist /FI "PID eq ${pid}" /NH`,
        { encoding: 'utf8', timeout: 5000 }
      );
      return result.includes(String(pid));
    }
    
    // Unix: 发送信号0
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return false;
  }
}

/**
 * 获取进程启动时间
 */
function getProcessStartTime(pid) {
  if (process.platform !== 'linux' || !pid) return null;
  
  try {
    const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
    const parts = stat.split(' ');
    // 第22个字段是starttime
    return parseInt(parts[21], 10);
  } catch {
    return null;
  }
}

// ==================== 锁文件操作 ====================

/**
 * 读取锁文件
 */
function readLockFile(lockPath) {
  try {
    const content = fs.readFileSync(lockPath, 'utf8');
    return JSON.parse(content);
  } catch {
    return null;
  }
}

/**
 * 写入锁文件
 */
function writeLockFile(lockPath, payload) {
  const dir = path.dirname(lockPath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  
  fs.writeFileSync(lockPath, JSON.stringify(payload), { mode: 0o600 });
}

/**
 * 删除锁文件
 */
function removeLockFile(lockPath) {
  try {
    fs.unlinkSync(lockPath);
    return true;
  } catch {
    return false;
  }
}

// ==================== 锁检测 ====================

/**
 * 检查锁详情
 */
function inspectLock(lockPath, staleMs = DEFAULT_STALE_MS) {
  const payload = readLockFile(lockPath);
  
  const result = {
    lockPath,
    pid: null,
    pidAlive: false,
    createdAt: null,
    ageMs: null,
    stale: false,
    staleReasons: [],
    removed: false
  };
  
  if (!payload) {
    return result;
  }
  
  result.pid = payload.pid || null;
  result.createdAt = payload.createdAt || null;
  
  // 检查进程存活
  if (result.pid) {
    result.pidAlive = isPidAlive(result.pid);
    
    // Linux: 检查进程启动时间
    if (process.platform === 'linux' && payload.starttime) {
      const currentStarttime = getProcessStartTime(result.pid);
      if (currentStarttime !== null && currentStarttime !== payload.starttime) {
        result.pidAlive = false;
      }
    }
  }
  
  // 计算年龄
  if (result.createdAt) {
    const createdAt = new Date(result.createdAt).getTime();
    if (!isNaN(createdAt)) {
      result.ageMs = Date.now() - createdAt;
    }
  }
  
  // 检查过期
  if (!result.pidAlive) {
    result.stale = true;
    result.staleReasons.push('process_dead');
  }
  
  if (result.ageMs !== null && result.ageMs > staleMs) {
    result.stale = true;
    result.staleReasons.push('age_exceeded');
  }
  
  return result;
}

// ==================== 锁获取与释放 ====================

/**
 * 获取会话锁
 */
async function acquireSessionWriteLock(params) {
  const {
    sessionFile,
    pid = process.pid,
    staleMs = DEFAULT_STALE_MS,
    maxHoldMs = DEFAULT_MAX_HOLD_MS,
    timeoutMs
  } = params;
  
  const lockPath = `${sessionFile}.lock`;
  
  // 检查现有锁
  const existing = inspectLock(lockPath, staleMs);
  
  if (!existing.stale && existing.pidAlive) {
    // 锁被其他进程持有
    if (timeoutMs) {
      // 等待锁释放
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        await sleep(100);
        const recheck = inspectLock(lockPath, staleMs);
        if (recheck.stale || !recheck.pidAlive) {
          break;
        }
      }
    } else {
      throw new Error(`Lock held by process ${existing.pid}`);
    }
  }
  
  // 清理过期锁
  if (existing.stale) {
    removeLockFile(lockPath);
  }
  
  // 创建新锁
  const payload = {
    pid,
    createdAt: new Date().toISOString(),
    starttime: process.platform === 'linux' ? getProcessStartTime(pid) : undefined
  };
  
  writeLockFile(lockPath, payload);
  
  // 记录持有锁
  const heldLock = {
    count: 1,
    lockPath,
    acquiredAt: Date.now(),
    maxHoldMs
  };
  
  HELD_LOCKS.set(lockPath, heldLock);
  
  // 确保看门狗运行
  startWatchdog();
  
  return {
    lockPath,
    release: () => releaseSessionWriteLock(lockPath)
  };
}

/**
 * 释放会话锁
 */
function releaseSessionWriteLock(lockPath) {
  const heldLock = HELD_LOCKS.get(lockPath);
  
  if (!heldLock) {
    return false;
  }
  
  heldLock.count--;
  
  if (heldLock.count <= 0) {
    removeLockFile(lockPath);
    HELD_LOCKS.delete(lockPath);
  }
  
  return true;
}

/**
 * 强制释放锁（即使持有计数>0）
 */
function forceReleaseLock(lockPath) {
  removeLockFile(lockPath);
  HELD_LOCKS.delete(lockPath);
}

// ==================== 看门狗 ====================

/**
 * 启动看门狗
 */
function startWatchdog() {
  if (watchdogState.started) return;
  
  watchdogState.started = true;
  watchdogState.timer = setInterval(() => {
    const now = Date.now();
    
    for (const [lockPath, heldLock] of HELD_LOCKS) {
      // 检查锁持有时间
      if (now - heldLock.acquiredAt > heldLock.maxHoldMs) {
        console.warn(`Lock held too long: ${lockPath}`);
        // 可以选择自动释放
        // forceReleaseLock(lockPath);
      }
    }
  }, watchdogState.intervalMs);
  
  // 防止进程退出时定时器阻止退出
  if (watchdogState.timer.unref) {
    watchdogState.timer.unref();
  }
}

/**
 * 停止看门狗
 */
function stopWatchdog() {
  if (watchdogState.timer) {
    clearInterval(watchdogState.timer);
    watchdogState.timer = null;
  }
  watchdogState.started = false;
}

// ==================== 清理注册 ====================

/**
 * 注册清理处理器
 */
function registerCleanupHandlers() {
  if (cleanupState.registered) return;
  
  const signals = ['SIGINT', 'SIGTERM', 'SIGQUIT'];
  
  for (const signal of signals) {
    const handler = () => {
      releaseAllLocks();
      process.exit(0);
    };
    
    process.on(signal, handler);
    cleanupState.cleanupHandlers.set(signal, handler);
  }
  
  // Windows特殊处理
  if (process.platform === 'win32') {
    process.on('SIGBREAK', () => {
      releaseAllLocks();
      process.exit(0);
    });
  }
  
  cleanupState.registered = true;
}

/**
 * 释放所有锁
 */
function releaseAllLocks() {
  for (const lockPath of HELD_LOCKS.keys()) {
    forceReleaseLock(lockPath);
  }
  
  stopWatchdog();
}

// ==================== 辅助函数 ====================

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ==================== 初始化 ====================

registerCleanupHandlers();

// ==================== 导出 ====================

module.exports = {
  // 锁操作
  acquireSessionWriteLock,
  releaseSessionWriteLock,
  forceReleaseLock,
  releaseAllLocks,
  
  // 锁检测
  inspectLock,
  
  // 看门狗
  startWatchdog,
  stopWatchdog,
  
  // 辅助
  isPidAlive,
  getProcessStartTime,
  
  // 常量
  DEFAULT_STALE_MS,
  DEFAULT_MAX_HOLD_MS,
  DEFAULT_WATCHDOG_INTERVAL_MS
};

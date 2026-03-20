/**
 * iFlow JSON Files Module
 * JSON文件原子操作模块（基于OpenClaw json-files设计）
 * 
 * 功能:
 * - 原子写入JSON/文本文件
 * - 异步锁防止并发冲突
 * - 安全文件操作
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// ==================== JSON文件读取 ====================

/**
 * 读取JSON文件
 */
async function readJsonFile(filePath) {
  try {
    const raw = await fs.promises.readFile(filePath, 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * 同步读取JSON文件
 */
function readJsonFileSync(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

// ==================== 原子写入 ====================

/**
 * 原子写入JSON文件
 */
async function writeJsonAtomic(filePath, value, options = {}) {
  const text = JSON.stringify(value, null, 2);
  await writeTextAtomic(filePath, text, {
    mode: options.mode,
    ensureDirMode: options.ensureDirMode,
    appendTrailingNewline: options.trailingNewline
  });
}

/**
 * 原子写入文本文件
 */
async function writeTextAtomic(filePath, content, options = {}) {
  const mode = options.mode ?? 0o600; // 仅所有者可读写
  const payload = options.appendTrailingNewline && !content.endsWith('\n')
    ? `${content}\n`
    : content;
  
  // 确保目录存在
  const mkdirOptions = { recursive: true };
  if (typeof options.ensureDirMode === 'number') {
    mkdirOptions.mode = options.ensureDirMode;
  }
  
  await fs.promises.mkdir(path.dirname(filePath), mkdirOptions);
  
  // 使用临时文件进行原子写入
  const tmp = `${filePath}.${crypto.randomUUID()}.tmp`;
  
  try {
    // 写入临时文件
    await fs.promises.writeFile(tmp, payload, { encoding: 'utf8', mode });
    
    // 尝试设置权限（某些平台不支持）
    try {
      await fs.promises.chmod(tmp, mode);
    } catch {
      // 忽略不支持chmod的平台
    }
    
    // 原子重命名
    await fs.promises.rename(tmp, filePath);
    
    // 再次确保权限
    try {
      await fs.promises.chmod(filePath, mode);
    } catch {
      // 忽略
    }
  } finally {
    // 清理临时文件
    await fs.promises.rm(tmp, { force: true }).catch(() => undefined);
  }
}

/**
 * 同步原子写入文本文件
 */
function writeTextAtomicSync(filePath, content, options = {}) {
  const mode = options.mode ?? 0o600;
  const payload = options.appendTrailingNewline && !content.endsWith('\n')
    ? `${content}\n`
    : content;
  
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  
  const tmp = `${filePath}.${crypto.randomUUID()}.tmp`;
  
  try {
    fs.writeFileSync(tmp, payload, { encoding: 'utf8', mode });
    
    try {
      fs.chmodSync(tmp, mode);
    } catch {
      // 忽略
    }
    
    fs.renameSync(tmp, filePath);
    
    try {
      fs.chmodSync(filePath, mode);
    } catch {
      // 忽略
    }
  } finally {
    try {
      fs.unlinkSync(tmp);
    } catch {
      // 忽略
    }
  }
}

// ==================== 异步锁 ====================

/**
 * 创建异步锁
 */
function createAsyncLock() {
  let lock = Promise.resolve();
  
  return async function withLock(fn) {
    const prev = lock;
    let release;
    
    lock = new Promise(resolve => {
      release = resolve;
    });
    
    await prev;
    
    try {
      return await fn();
    } finally {
      release?.();
    }
  };
}

/**
 * 创建带超时的异步锁
 */
function createAsyncLockWithTimeout(timeoutMs = 30000) {
  let lock = Promise.resolve();
  
  return async function withLock(fn, timeout = timeoutMs) {
    const prev = lock;
    let release;
    
    lock = new Promise(resolve => {
      release = resolve;
    });
    
    // 等待上一个锁或超时
    const timeoutPromise = new Promise((_, reject) => {
      setTimeout(() => reject(new Error('Lock timeout')), timeout);
    });
    
    await Promise.race([prev, timeoutPromise]);
    
    try {
      return await fn();
    } finally {
      release?.();
    }
  };
}

// ==================== 文件存在检查 ====================

/**
 * 检查文件是否存在
 */
async function fileExists(filePath) {
  try {
    await fs.promises.access(filePath, fs.constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

/**
 * 同步检查文件是否存在
 */
function fileExistsSync(filePath) {
  try {
    fs.accessSync(filePath, fs.constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

// ==================== 安全删除 ====================

/**
 * 安全删除文件
 */
async function safeDeleteFile(filePath) {
  try {
    await fs.promises.unlink(filePath);
    return true;
  } catch {
    return false;
  }
}

/**
 * 安全删除目录（递归）
 */
async function safeDeleteDir(dirPath) {
  try {
    await fs.promises.rm(dirPath, { recursive: true, force: true });
    return true;
  } catch {
    return false;
  }
}

// ==================== 文件复制 ====================

/**
 * 原子复制文件
 */
async function copyFileAtomic(src, dest, options = {}) {
  const content = await fs.promises.readFile(src);
  await writeTextAtomic(dest, content.toString(), options);
}

// ==================== 导出 ====================

module.exports = {
  // JSON操作
  readJsonFile,
  readJsonFileSync,
  writeJsonAtomic,
  
  // 文本操作
  writeTextAtomic,
  writeTextAtomicSync,
  
  // 锁
  createAsyncLock,
  createAsyncLockWithTimeout,
  
  // 文件操作
  fileExists,
  fileExistsSync,
  safeDeleteFile,
  safeDeleteDir,
  copyFileAtomic
};

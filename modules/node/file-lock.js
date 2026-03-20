/**
 * File Lock Module
 * 提供跨进程文件锁功能，防止并发访问冲突
 * 整合自 OpenClaw file-lock.ts
 */

const fs = require("node:fs/promises");
const path = require("node:path");

// ===== Process Scoped Map =====
const processScopedMaps = new Map();

function resolveProcessScopedMap(key) {
  const existing = processScopedMaps.get(key);
  if (existing) {
    return existing;
  }
  const created = new Map();
  processScopedMaps.set(key, created);
  return created;
}

// ===== PID Alive Detection =====
function isValidPid(pid) {
  return Number.isInteger(pid) && pid > 0;
}

function isZombieProcess(pid) {
  if (process.platform !== "linux") {
    return false;
  }
  try {
    const status = require("node:fs").readFileSync(`/proc/${pid}/status`, "utf8");
    const stateMatch = status.match(/^State:\s+(\S)/m);
    return stateMatch?.[1] === "Z";
  } catch {
    return false;
  }
}

function isPidAlive(pid) {
  if (!isValidPid(pid)) {
    return false;
  }
  try {
    process.kill(pid, 0);
  } catch {
    return false;
  }
  if (isZombieProcess(pid)) {
    return false;
  }
  return true;
}

// ===== File Lock Implementation =====
const HELD_LOCKS_KEY = Symbol.for("iflow.fileLockHeldLocks");
const HELD_LOCKS = resolveProcessScopedMap(HELD_LOCKS_KEY);

function computeDelayMs(retries, attempt) {
  const base = Math.min(
    retries.maxTimeout,
    Math.max(retries.minTimeout, retries.minTimeout * Math.pow(retries.factor, attempt))
  );
  const jitter = retries.randomize ? 1 + Math.random() : 1;
  return Math.min(retries.maxTimeout, Math.round(base * jitter));
}

async function readLockPayload(lockPath) {
  try {
    const raw = await fs.readFile(lockPath, "utf8");
    const parsed = JSON.parse(raw);
    if (typeof parsed.pid !== "number" || typeof parsed.createdAt !== "string") {
      return null;
    }
    return { pid: parsed.pid, createdAt: parsed.createdAt };
  } catch {
    return null;
  }
}

async function resolveNormalizedFilePath(filePath) {
  const resolved = path.resolve(filePath);
  const dir = path.dirname(resolved);
  await fs.mkdir(dir, { recursive: true });
  try {
    const realDir = await fs.realpath(dir);
    return path.join(realDir, path.basename(resolved));
  } catch {
    return resolved;
  }
}

async function isStaleLock(lockPath, staleMs) {
  const payload = await readLockPayload(lockPath);
  if (payload?.pid && !isPidAlive(payload.pid)) {
    return true;
  }
  if (payload?.createdAt) {
    const createdAt = Date.parse(payload.createdAt);
    if (!Number.isFinite(createdAt) || Date.now() - createdAt > staleMs) {
      return true;
    }
  }
  try {
    const stat = await fs.stat(lockPath);
    return Date.now() - stat.mtimeMs > staleMs;
  } catch {
    return true;
  }
}

async function releaseHeldLock(normalizedFile) {
  const current = HELD_LOCKS.get(normalizedFile);
  if (!current) {
    return;
  }
  current.count -= 1;
  if (current.count > 0) {
    return;
  }
  HELD_LOCKS.delete(normalizedFile);
  await current.handle.close().catch(() => undefined);
  await fs.rm(current.lockPath, { force: true }).catch(() => undefined);
}

/**
 * 获取文件锁
 * @param {string} filePath - 要锁定的文件路径
 * @param {Object} options - 锁选项
 * @param {Object} options.retries - 重试配置
 * @param {number} options.retries.retries - 重试次数
 * @param {number} options.retries.factor - 退避因子
 * @param {number} options.retries.minTimeout - 最小超时时间
 * @param {number} options.retries.maxTimeout - 最大超时时间
 * @param {boolean} options.retries.randomize - 是否随机化延迟
 * @param {number} options.stale - 锁过期时间
 * @returns {Promise<FileLockHandle>} 文件锁句柄
 */
async function acquireFileLock(filePath, options) {
  const normalizedFile = await resolveNormalizedFilePath(filePath);
  const lockPath = `${normalizedFile}.lock`;
  const held = HELD_LOCKS.get(normalizedFile);
  if (held) {
    held.count += 1;
    return {
      lockPath,
      release: () => releaseHeldLock(normalizedFile),
    };
  }

  const attempts = Math.max(1, options.retries.retries + 1);
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const handle = await fs.open(lockPath, "wx");
      await handle.writeFile(
        JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() }, null, 2),
        "utf8"
      );
      HELD_LOCKS.set(normalizedFile, { count: 1, handle, lockPath });
      return {
        lockPath,
        release: () => releaseHeldLock(normalizedFile),
      };
    } catch (err) {
      const code = err?.code;
      if (code !== "EEXIST") {
        throw err;
      }
      if (await isStaleLock(lockPath, options.stale)) {
        await fs.rm(lockPath, { force: true }).catch(() => undefined);
        continue;
      }
      if (attempt >= attempts - 1) {
        break;
      }
      await new Promise((resolve) =>
        setTimeout(resolve, computeDelayMs(options.retries, attempt))
      );
    }
  }

  throw new Error(`file lock timeout for ${normalizedFile}`);
}

/**
 * 使用文件锁执行函数
 * @param {string} filePath - 要锁定的文件路径
 * @param {Object} options - 锁选项
 * @param {Function} fn - 要执行的函数
 * @returns {Promise<T>} 函数执行结果
 */
async function withFileLock(filePath, options, fn) {
  const lock = await acquireFileLock(filePath, options);
  try {
    return await fn();
  } finally {
    await lock.release();
  }
}

// ===== Default Options =====
const DEFAULT_FILE_LOCK_OPTIONS = {
  retries: {
    retries: 10,
    factor: 2,
    minTimeout: 100,
    maxTimeout: 5000,
    randomize: true,
  },
  stale: 30000, // 30 seconds
};

// ===== CommonJS Export =====
module.exports = {
  acquireFileLock,
  withFileLock,
  isPidAlive,
  DEFAULT_FILE_LOCK_OPTIONS,
};
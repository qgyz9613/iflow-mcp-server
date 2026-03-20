/**
 * iFlow Spawn Utils Module
 * 进程启动和回退工具模块，整合自 OpenClaw 的 spawn-utils.ts
 * 提供进程启动、错误处理和回退机制
 */

const { spawn } = require('child_process');

// ==================== 标准输入输出配置 ====================

/**
 * 解析命令标准输入输出配置
 * @param {Object} params - 参数对象
 * @param {boolean} params.hasInput - 是否有输入
 * @param {boolean} params.preferInherit - 是否优先继承
 * @returns {Array<string>} [stdin, stdout, stderr] 配置数组
 */
function resolveCommandStdio(params) {
  const { hasInput, preferInherit } = params;
  const stdin = hasInput ? 'pipe' : preferInherit ? 'inherit' : 'pipe';
  return [stdin, 'pipe', 'pipe'];
}

// ==================== 错误处理 ====================

/**
 * 格式化进程启动错误
 * @param {unknown} err - 错误对象
 * @returns {string} 格式化后的错误消息
 */
function formatSpawnError(err) {
  if (!(err instanceof Error)) {
    return String(err);
  }
  const details = err;
  const parts = [];
  const message = err.message?.trim();
  if (message) {
    parts.push(message);
  }
  if (details.code && !message?.includes(details.code)) {
    parts.push(details.code);
  }
  if (details.syscall) {
    parts.push(`syscall=${details.syscall}`);
  }
  if (typeof details.errno === 'number') {
    parts.push(`errno=${details.errno}`);
  }
  return parts.join(' ');
}

/**
 * 检查进程是否存活
 * @param {number} pid - 进程 ID
 * @returns {boolean} 进程是否存活
 */
function isProcessAlive(pid) {
  if (!Number.isFinite(pid) || pid <= 0) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

// ==================== 进程启动和回退 ====================

/**
 * 类型定义
 * @typedef {Object} SpawnFallback
 * @property {string} label - 回退方案标签
 * @property {import('child_process').SpawnOptions} options - 启动选项
 */

/**
 * @typedef {Object} SpawnWithFallbackResult
 * @property {import('child_process').ChildProcess} child - 子进程对象
 * @property {boolean} usedFallback - 是否使用了回退方案
 * @property {string} [fallbackLabel] - 回退方案标签
 */

/**
 * @typedef {Object} SpawnWithFallbackParams
 * @property {string[]} argv - 命令行参数
 * @property {import('child_process').SpawnOptions} options - 启动选项
 * @property {SpawnFallback[]} [fallbacks] - 回退方案列表
 * @property {typeof spawn} [spawnImpl] - 自定义 spawn 实现
 * @property {string[]} [retryCodes] - 重试错误代码列表
 * @property {Function} [onFallback] - 回退回调函数
 */

/**
 * 默认重试错误代码
 */
const DEFAULT_RETRY_CODES = ['EBADF'];

/**
 * 检查是否应该重试
 * @param {unknown} err - 错误对象
 * @param {string[]} codes - 重试错误代码列表
 * @returns {boolean} 是否应该重试
 */
function shouldRetry(err, codes) {
  const code = err && typeof err === 'object' && 'code' in err ? String(err.code) : '';
  return code.length > 0 && codes.includes(code);
}

/**
 * 等待进程启动完成
 * @param {typeof spawn} spawnImpl - spawn 函数
 * @param {string[]} argv - 命令行参数
 * @param {import('child_process').SpawnOptions} options - 启动选项
 * @returns {Promise<import('child_process').ChildProcess>} 子进程对象
 */
function spawnAndWaitForSpawn(spawnImpl, argv, options) {
  const child = spawnImpl(argv[0], argv.slice(1), options);

  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => {
      child.removeListener('error', onError);
      child.removeListener('spawn', onSpawn);
    };
    const finishResolve = () => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolve(child);
    };
    const onError = (err) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      reject(err);
    };
    const onSpawn = () => {
      finishResolve();
    };
    child.once('error', onError);
    child.once('spawn', onSpawn);
    // 确保模拟的 spawn 不会永远不触发 "spawn"
    process.nextTick(() => {
      if (typeof child.pid === 'number') {
        finishResolve();
      }
    });
  });
}

/**
 * 带回退机制的进程启动
 * @param {SpawnWithFallbackParams} params - 参数对象
 * @returns {Promise<SpawnWithFallbackResult>} 启动结果
 */
async function spawnWithFallback(params) {
  const spawnImpl = params.spawnImpl || spawn;
  const retryCodes = params.retryCodes || DEFAULT_RETRY_CODES;
  const baseOptions = { ...params.options };
  const fallbacks = params.fallbacks || [];
  const attempts = [
    { options: baseOptions },
    ...fallbacks.map((fallback) => ({
      label: fallback.label,
      options: { ...baseOptions, ...fallback.options },
    })),
  ];

  let lastError;
  for (let index = 0; index < attempts.length; index += 1) {
    const attempt = attempts[index];
    try {
      const child = await spawnAndWaitForSpawn(spawnImpl, params.argv, attempt.options);
      return {
        child,
        usedFallback: index > 0,
        fallbackLabel: attempt.label,
      };
    } catch (err) {
      lastError = err;
      const nextFallback = fallbacks[index];
      if (!nextFallback || !shouldRetry(err, retryCodes)) {
        throw err;
      }
      params.onFallback?.(err, nextFallback);
    }
  }

  throw lastError;
}

/**
 * 带超时的进程启动
 * @param {string[]} argv - 命令行参数
 * @param {import('child_process').SpawnOptions} options - 启动选项
 * @param {number} [timeoutMs] - 超时时间（毫秒）
 * @returns {Promise<{child: import('child_process').ChildProcess, usedFallback: boolean, fallbackLabel?: string}>} 启动结果
 */
async function spawnWithTimeout(argv, options = {}, timeoutMs) {
  const spawnPromise = spawnWithFallback({ argv, options });

  if (!timeoutMs || timeoutMs <= 0) {
    return spawnPromise;
  }

  const timeoutPromise = new Promise((_, reject) => {
    setTimeout(() => {
      reject(new Error(`Process spawn timeout after ${timeoutMs}ms`));
    }, timeoutMs);
  });

  return Promise.race([spawnPromise, timeoutPromise]);
}

module.exports = {
  resolveCommandStdio,
  formatSpawnError,
  isProcessAlive,
  spawnWithFallback,
  spawnWithTimeout,
  DEFAULT_RETRY_CODES
};
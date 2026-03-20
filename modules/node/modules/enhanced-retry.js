/**
 * iFlow Enhanced Retry Module
 * 增强重试模块（基于OpenClaw retry设计）
 * 
 * 功能:
 * - 指数退避重试
 * - 抖动支持
 * - 自定义重试条件
 * - 重试回调
 */

// ==================== 默认配置 ====================

const DEFAULT_RETRY_CONFIG = {
  attempts: 3,
  minDelayMs: 300,
  maxDelayMs: 30_000,
  jitter: 0
};

// ==================== 辅助函数 ====================

/**
 * 解析为有限数
 */
function asFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/**
 * 限制数字范围
 */
function clampNumber(value, fallback, min, max) {
  const next = asFiniteNumber(value);
  if (next === undefined) return fallback;
  
  const floor = typeof min === 'number' ? min : -Infinity;
  const ceiling = typeof max === 'number' ? max : Infinity;
  return Math.min(Math.max(next, floor), ceiling);
}

/**
 * 解析重试配置
 */
function resolveRetryConfig(defaults, overrides) {
  defaults = { ...DEFAULT_RETRY_CONFIG, ...defaults };
  
  const attempts = Math.max(1, Math.round(
    clampNumber(overrides?.attempts, defaults.attempts, 1)
  ));
  
  const minDelayMs = Math.max(0, Math.round(
    clampNumber(overrides?.minDelayMs, defaults.minDelayMs, 0)
  ));
  
  const maxDelayMs = Math.max(minDelayMs, Math.round(
    clampNumber(overrides?.maxDelayMs, defaults.maxDelayMs, 0)
  ));
  
  const jitter = clampNumber(overrides?.jitter, defaults.jitter, 0, 1);
  
  return { attempts, minDelayMs, maxDelayMs, jitter };
}

/**
 * 应用抖动
 */
function applyJitter(delayMs, jitter) {
  if (jitter <= 0) return delayMs;
  
  // 随机偏移 [-jitter, +jitter]
  const offset = (Math.random() * 2 - 1) * jitter;
  return Math.max(0, Math.round(delayMs * (1 + offset)));
}

/**
 * 计算退避延迟
 */
function computeBackoff(attempt, config) {
  const { minDelayMs, maxDelayMs, jitter } = config;
  
  // 指数退避: minDelayMs * 2^attempt
  const baseDelay = minDelayMs * Math.pow(2, attempt);
  const cappedDelay = Math.min(baseDelay, maxDelayMs);
  
  return applyJitter(cappedDelay, jitter);
}

/**
 * 延迟函数
 */
function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * 带中止信号的延迟
 */
function sleepWithAbort(ms, abortSignal) {
  return new Promise((resolve, reject) => {
    if (abortSignal?.aborted) {
      reject(new Error('Aborted'));
      return;
    }
    
    const timer = setTimeout(resolve, ms);
    
    const onAbort = () => {
      clearTimeout(timer);
      reject(new Error('Aborted'));
    };
    
    abortSignal?.addEventListener('abort', onAbort, { once: true });
  });
}

// ==================== 重试函数 ====================

/**
 * 重试信息
 */
class RetryInfo {
  constructor(data) {
    this.attempt = data.attempt;
    this.maxAttempts = data.maxAttempts;
    this.delayMs = data.delayMs;
    this.err = data.err;
    this.label = data.label;
  }
}

/**
 * 异步重试
 */
async function retryAsync(fn, attemptsOrOptions = 3, initialDelayMs = 300) {
  // 简单模式：只传重试次数
  if (typeof attemptsOrOptions === 'number') {
    const attempts = Math.max(1, Math.round(attemptsOrOptions));
    let lastErr;
    
    for (let i = 0; i < attempts; i++) {
      try {
        return await fn();
      } catch (err) {
        lastErr = err;
        
        if (i === attempts - 1) {
          break;
        }
        
        const delay = initialDelayMs * Math.pow(2, i);
        await sleep(delay);
      }
    }
    
    throw lastErr ?? new Error('Retry failed');
  }
  
  // 高级模式：完整配置
  const options = attemptsOrOptions;
  const resolved = resolveRetryConfig(DEFAULT_RETRY_CONFIG, options);
  
  const maxAttempts = resolved.attempts;
  const minDelayMs = resolved.minDelayMs;
  const maxDelayMs = resolved.maxDelayMs;
  const jitter = resolved.jitter;
  
  let lastErr;
  let delayMs = minDelayMs;
  
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      
      // 检查是否应该重试
      if (options.shouldRetry && !options.shouldRetry(err, attempt)) {
        throw err;
      }
      
      if (attempt === maxAttempts - 1) {
        break;
      }
      
      // 计算延迟
      let nextDelay = delayMs;
      
      // 检查 Retry-After 头
      if (options.retryAfterMs) {
        const retryAfter = options.retryAfterMs(err);
        if (retryAfter !== undefined && retryAfter > 0) {
          nextDelay = Math.min(retryAfter, maxDelayMs);
        }
      }
      
      nextDelay = applyJitter(nextDelay, jitter);
      
      // 回调
      if (options.onRetry) {
        options.onRetry(new RetryInfo({
          attempt,
          maxAttempts,
          delayMs: nextDelay,
          err,
          label: options.label
        }));
      }
      
      await sleep(nextDelay);
      
      // 指数增长延迟
      delayMs = Math.min(delayMs * 2, maxDelayMs);
    }
  }
  
  throw lastErr ?? new Error('Retry failed');
}

/**
 * 带超时的重试
 */
async function retryWithTimeout(fn, options = {}) {
  const {
    timeoutMs = 30_000,
    attempts = 3,
    ...retryOptions
  } = options;
  
  const deadline = Date.now() + timeoutMs;
  let lastErr;
  
  for (let attempt = 0; attempt < attempts; attempt++) {
    const remaining = deadline - Date.now();
    
    if (remaining <= 0) {
      throw new Error(`Retry timeout after ${attempt} attempts`);
    }
    
    try {
      // 使用Promise.race实现超时
      const result = await Promise.race([
        fn(),
        new Promise((_, reject) => 
          setTimeout(() => reject(new Error('Timeout')), remaining)
        )
      ]);
      
      return result;
    } catch (err) {
      lastErr = err;
      
      if (err.message === 'Timeout') {
        break;
      }
      
      if (attempt < attempts - 1 && retryOptions.onRetry) {
        retryOptions.onRetry(new RetryInfo({
          attempt,
          maxAttempts: attempts,
          delayMs: 0,
          err,
          label: retryOptions.label
        }));
      }
    }
  }
  
  throw lastErr ?? new Error('Retry timeout');
}

// ==================== 重试装饰器 ====================

/**
 * 创建重试装饰器
 */
function createRetryDecorator(options = {}) {
  return function(target, propertyKey, descriptor) {
    const originalMethod = descriptor.value;
    
    descriptor.value = async function(...args) {
      return retryAsync(
        () => originalMethod.apply(this, args),
        options
      );
    };
    
    return descriptor;
  };
}

/**
 * 函数包装器
 */
function withRetry(fn, options = {}) {
  return async function(...args) {
    return retryAsync(() => fn(...args), options);
  };
}

// ==================== 错误分类 ====================

/**
 * 检查是否为瞬态错误
 */
function isTransientError(err) {
  if (!err) return false;
  
  // 网络错误
  if (err.code) {
    const transientCodes = [
      'ECONNRESET', 'ECONNREFUSED', 'ETIMEDOUT', 'ENOTFOUND',
      'EAI_AGAIN', 'EHOSTUNREACH', 'ENETUNREACH',
      'EPIPE', 'EPROTO', 'CERT_HAS_EXPIRED'
    ];
    
    if (transientCodes.includes(err.code)) {
      return true;
    }
  }
  
  // HTTP状态码
  if (err.status || err.statusCode) {
    const status = err.status || err.statusCode;
    // 5xx 服务器错误通常可以重试
    if (status >= 500 && status < 600 && status !== 501) {
      return true;
    }
    // 429 限流
    if (status === 429) {
      return true;
    }
  }
  
  // 错误消息
  const message = err.message?.toLowerCase() || '';
  if (message.includes('timeout') || 
      message.includes('rate limit') ||
      message.includes('too many requests') ||
      message.includes('service unavailable') ||
      message.includes('temporary')) {
    return true;
  }
  
  return false;
}

// ==================== 导出 ====================

module.exports = {
  // 核心函数
  retryAsync,
  retryWithTimeout,
  
  // 辅助函数
  resolveRetryConfig,
  computeBackoff,
  applyJitter,
  sleep,
  sleepWithAbort,
  
  // 装饰器
  createRetryDecorator,
  withRetry,
  
  // 错误判断
  isTransientError,
  
  // 类
  RetryInfo,
  
  // 常量
  DEFAULT_RETRY_CONFIG
};

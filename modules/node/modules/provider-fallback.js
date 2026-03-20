/**
 * iFlow Provider Fallback Module
 * 模型提供商降级策略（基于OpenClaw model-fallback.ts设计）
 * 
 * 功能:
 * - 自动降级到备用模型
 * - 认证配置冷却机制
 * - 错误分类和处理
 * - 重试策略
 */

const { v4: uuidv4 } = require('uuid');

// ==================== 错误类型定义 ====================

const FAILOVER_ERRORS = {
  // 认证错误
  AUTH_INVALID: 'auth_invalid',
  AUTH_EXPIRED: 'auth_expired',
  AUTH_RATE_LIMITED: 'auth_rate_limited',
  
  // 模型错误
  MODEL_NOT_FOUND: 'model_not_found',
  MODEL_OVERLOADED: 'model_overloaded',
  MODEL_CONTEXT_OVERFLOW: 'model_context_overflow',
  
  // 网络错误
  NETWORK_TIMEOUT: 'network_timeout',
  NETWORK_ERROR: 'network_error',
  
  // 未知错误
  UNKNOWN: 'unknown'
};

// ==================== 降级策略配置 ====================

const FALLBACK_CONFIG = {
  // 最大重试次数
  maxRetries: 3,
  
  // 重试延迟（毫秒）
  retryDelay: 1000,
  
  // 指数退避因子
  backoffFactor: 2,
  
  // 最大退避延迟
  maxBackoffDelay: 30000,
  
  // 冷却时间（毫秒）
  cooldownTime: 60000,  // 1分钟
  
  // 认证配置轮换
  authProfileRotation: true
};

// ==================== 模型候选收集器 ====================

class ModelCandidateCollector {
  constructor(allowlist = null) {
    this.seen = new Set();
    this.candidates = [];
    this.allowlist = allowlist;
  }
  
  addExplicitCandidate(candidate) {
    this._addCandidate(candidate, false);
  }
  
  addAllowlistedCandidate(candidate) {
    this._addCandidate(candidate, true);
  }
  
  _addCandidate(candidate, enforceAllowlist) {
    if (!candidate.provider || !candidate.model) {
      return;
    }
    
    const key = `${candidate.provider}:${candidate.model}`;
    
    if (this.seen.has(key)) {
      return;
    }
    
    if (enforceAllowlist && this.allowlist && !this.allowlist.has(key)) {
      return;
    }
    
    this.seen.add(key);
    this.candidates.push(candidate);
  }
  
  getCandidates() {
    return [...this.candidates];
  }
}

// ==================== 认证配置存储 ====================

class AuthProfileStore {
  constructor() {
    this.profiles = new Map();  // provider -> [{ profile, lastUsed, cooldownExpiry, failures }]
  }
  
  /**
   * 添加认证配置
   */
  addProfile(provider, profile) {
    if (!this.profiles.has(provider)) {
      this.profiles.set(provider, []);
    }
    
    this.profiles.get(provider).push({
      id: profile.id || uuidv4(),
      profile,
      lastUsed: null,
      cooldownExpiry: null,
      failureCount: 0,
      lastFailure: null
    });
  }
  
  /**
   * 获取可用配置（考虑冷却）
   */
  getAvailableProfile(provider) {
    const profiles = this.profiles.get(provider) || [];
    const now = Date.now();
    
    // 过滤掉冷却中的配置
    const available = profiles.filter(p => 
      !p.cooldownExpiry || now > p.cooldownExpiry
    );
    
    if (available.length === 0) {
      return null;
    }
    
    // 按失败次数排序，优先使用失败少的
    available.sort((a, b) => a.failureCount - b.failureCount);
    
    // 轮换：选择最久未使用的
    const leastRecentlyUsed = available.reduce((a, b) => 
      (!a.lastUsed || (b.lastUsed && a.lastUsed < b.lastUsed)) ? a : b
    );
    
    return leastRecentlyUsed;
  }
  
  /**
   * 标记配置使用
   */
  markUsed(provider, profileId) {
    const profiles = this.profiles.get(provider) || [];
    const profile = profiles.find(p => p.id === profileId);
    
    if (profile) {
      profile.lastUsed = Date.now();
      profile.failureCount = 0;  // 成功使用，重置失败计数
    }
  }
  
  /**
   * 标记配置失败
   */
  markFailed(provider, profileId, error) {
    const profiles = this.profiles.get(provider) || [];
    const profile = profiles.find(p => p.id === profileId);
    
    if (profile) {
      profile.failureCount++;
      profile.lastFailure = { error, time: Date.now() };
      
      // 如果连续失败多次，进入冷却
      if (profile.failureCount >= 3) {
        profile.cooldownExpiry = Date.now() + FALLBACK_CONFIG.cooldownTime;
      }
    }
  }
  
  /**
   * 获取最近冷却到期时间
   */
  getSoonestCooldownExpiry(provider) {
    const profiles = this.profiles.get(provider) || [];
    const now = Date.now();
    
    const activeCooldowns = profiles
      .filter(p => p.cooldownExpiry && p.cooldownExpiry > now)
      .map(p => p.cooldownExpiry);
    
    if (activeCooldowns.length === 0) {
      return null;
    }
    
    return Math.min(...activeCooldowns);
  }
  
  /**
   * 检查配置是否在冷却中
   */
  isInCooldown(provider, profileId) {
    const profiles = this.profiles.get(provider) || [];
    const profile = profiles.find(p => p.id === profileId);
    
    if (!profile || !profile.cooldownExpiry) {
      return false;
    }
    
    return Date.now() < profile.cooldownExpiry;
  }
}

// ==================== 降级执行器 ====================

class FallbackExecutor {
  constructor(config = {}) {
    this.config = { ...FALLBACK_CONFIG, ...config };
    this.authStore = new AuthProfileStore();
    this.fallbackLog = [];
  }
  
  /**
   * 执行带降级的调用
   * @param {Array<ModelCandidate>} candidates - 模型候选列表
   * @param {Function} runFn - 执行函数 (provider, model, options) => Promise<T>
   * @param {Object} options - 选项
   * @returns {Promise<T>} - 执行结果
   */
  async executeWithFallback(candidates, runFn, options = {}) {
    const errors = [];
    let lastError = null;
    
    for (const candidate of candidates) {
      const { provider, model } = candidate;
      
      // 获取可用认证配置
      const authProfile = this.authStore.getAvailableProfile(provider);
      
      // 检查是否应该跳过此候选
      if (this._shouldSkipCandidate(candidate, options)) {
        continue;
      }
      
      try {
        // 计算退避延迟
        const delay = this._calculateBackoff(errors.length);
        if (delay > 0) {
          await this._sleep(delay);
        }
        
        // 执行调用
        const result = await runFn(provider, model, {
          ...options,
          authProfile: authProfile?.profile
        });
        
        // 成功：标记配置使用，记录日志
        if (authProfile) {
          this.authStore.markUsed(provider, authProfile.id);
        }
        
        this._logFallback(candidate, null, errors.length);
        
        return result;
        
      } catch (err) {
        lastError = err;
        errors.push({
          provider,
          model,
          error: err.message,
          errorType: this._classifyError(err)
        });
        
        // 标记配置失败
        if (authProfile) {
          this.authStore.markFailed(provider, authProfile.id, err);
        }
        
        // 检查是否应该中断降级
        if (this._shouldAbortFallback(err, errors)) {
          break;
        }
      }
    }
    
    // 所有候选都失败
    const error = new Error(`All model candidates failed: ${errors.map(e => `${e.provider}/${e.model}: ${e.error}`).join('; ')}`);
    error.errors = errors;
    error.lastError = lastError;
    
    throw error;
  }
  
  /**
   * 判断是否应该跳过候选
   */
  _shouldSkipCandidate(candidate, options) {
    // 如果有允许列表且候选不在其中
    if (options.allowlist && !options.allowlist.has(`${candidate.provider}:${candidate.model}`)) {
      return true;
    }
    
    // 如果配置在冷却中且没有其他选择
    if (this.authStore.isInCooldown(candidate.provider)) {
      const expiry = this.authStore.getSoonestCooldownExpiry(candidate.provider);
      if (expiry && Date.now() < expiry) {
        return true;
      }
    }
    
    return false;
  }
  
  /**
   * 判断是否应该中断降级
   */
  _shouldAbortFallback(error, errors) {
    const errorType = this._classifyError(error);
    
    // 上下文溢出不应该降级，需要压缩
    if (errorType === FAILOVER_ERRORS.MODEL_CONTEXT_OVERFLOW) {
      return true;
    }
    
    // 用户中止不降级
    if (error.name === 'AbortError') {
      return true;
    }
    
    return false;
  }
  
  /**
   * 分类错误
   */
  _classifyError(error) {
    const message = error.message?.toLowerCase() || '';
    const status = error.status || error.statusCode;
    
    if (status === 401 || message.includes('invalid api key') || message.includes('authentication')) {
      return FAILOVER_ERRORS.AUTH_INVALID;
    }
    
    if (status === 403 || message.includes('rate limit')) {
      return FAILOVER_ERRORS.AUTH_RATE_LIMITED;
    }
    
    if (status === 404 || message.includes('model not found')) {
      return FAILOVER_ERRORS.MODEL_NOT_FOUND;
    }
    
    if (status === 429 || message.includes('overload')) {
      return FAILOVER_ERRORS.MODEL_OVERLOADED;
    }
    
    if (message.includes('context') || message.includes('token limit')) {
      return FAILOVER_ERRORS.MODEL_CONTEXT_OVERFLOW;
    }
    
    if (error.name === 'TimeoutError' || message.includes('timeout')) {
      return FAILOVER_ERRORS.NETWORK_TIMEOUT;
    }
    
    if (message.includes('network') || message.includes('econnrefused')) {
      return FAILOVER_ERRORS.NETWORK_ERROR;
    }
    
    return FAILOVER_ERRORS.UNKNOWN;
  }
  
  /**
   * 计算退避延迟
   */
  _calculateBackoff(attemptCount) {
    if (attemptCount === 0) return 0;
    
    const delay = this.config.retryDelay * Math.pow(this.config.backoffFactor, attemptCount - 1);
    return Math.min(delay, this.config.maxBackoffDelay);
  }
  
  /**
   * 异步睡眠
   */
  _sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
  
  /**
   * 记录降级日志
   */
  _logFallback(candidate, error, attempts) {
    this.fallbackLog.push({
      timestamp: new Date().toISOString(),
      provider: candidate.provider,
      model: candidate.model,
      error: error?.message,
      attempts,
      success: !error
    });
    
    // 限制日志大小
    if (this.fallbackLog.length > 100) {
      this.fallbackLog = this.fallbackLog.slice(-100);
    }
  }
  
  /**
   * 获取降级日志
   */
  getFallbackLog(options = {}) {
    let log = [...this.fallbackLog];
    
    if (options.since) {
      const since = new Date(options.since).getTime();
      log = log.filter(l => new Date(l.timestamp).getTime() >= since);
    }
    
    if (options.limit) {
      log = log.slice(-options.limit);
    }
    
    return log;
  }
  
  /**
   * 获取认证配置存储
   */
  getAuthStore() {
    return this.authStore;
  }
}

// ==================== 导出 ====================

module.exports = {
  // 错误类型
  FAILOVER_ERRORS,
  
  // 配置
  FALLBACK_CONFIG,
  
  // 类
  ModelCandidateCollector,
  AuthProfileStore,
  FallbackExecutor,
  
  // 便捷函数
  classifyError: (err) => new FallbackExecutor()._classifyError(err)
};

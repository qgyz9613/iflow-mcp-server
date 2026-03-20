/**
 * Session Runtime Model Override
 * 会话运行时模型覆盖（基于OpenClaw设计）
 * 支持会话级别的模型配置、动态覆盖和持久化
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs').promises;

// ==================== 常量定义 ====================

const SESSION_DIR = path.join(__dirname, '..', 'session-runtime-data');
const MODEL_OVERRIDE_FILE = 'model-overrides.json';

// 确保目录存在
async function ensureSessionDir() {
  try {
    await fs.mkdir(SESSION_DIR, { recursive: true });
  } catch (err) {
    console.warn(`[SessionRuntimeModel] Failed to create session directory: ${err.message}`);
  }
}

// ==================== 模型配置类型 ====================

/**
 * 模型配置
 */
class ModelConfig {
  constructor(config = {}) {
    this.provider = config.provider || 'openai';  // openai, anthropic, google, etc.
    this.model = config.model || 'gpt-4';
    this.apiKey = config.apiKey || null;
    this.apiEndpoint = config.apiEndpoint || null;
    this.temperature = config.temperature !== undefined ? config.temperature : 0.7;
    this.maxTokens = config.maxTokens || 4096;
    this.topP = config.topP || 1.0;
    this.frequencyPenalty = config.frequencyPenalty || 0.0;
    this.presencePenalty = config.presencePenalty || 0.0;
    this.timeout = config.timeout || 120000;  // 120秒
    this.retryCount = config.retryCount || 3;
    this.priority = config.priority || 'normal';  // low, normal, high
  }
  
  /**
   * 克隆配置
   */
  clone() {
    return new ModelConfig(JSON.parse(JSON.stringify(this)));
  }
  
  /**
   * 合并配置
   */
  merge(other) {
    const merged = this.clone();
    
    if (other.provider) merged.provider = other.provider;
    if (other.model) merged.model = other.model;
    if (other.apiKey) merged.apiKey = other.apiKey;
    if (other.apiEndpoint) merged.apiEndpoint = other.apiEndpoint;
    if (other.temperature !== undefined) merged.temperature = other.temperature;
    if (other.maxTokens) merged.maxTokens = other.maxTokens;
    if (other.topP !== undefined) merged.topP = other.topP;
    if (other.frequencyPenalty !== undefined) merged.frequencyPenalty = other.frequencyPenalty;
    if (other.presencePenalty !== undefined) merged.presencePenalty = other.presencePenalty;
    if (other.timeout) merged.timeout = other.timeout;
    if (other.retryCount) merged.retryCount = other.retryCount;
    if (other.priority) merged.priority = other.priority;
    
    return merged;
  }
  
  /**
   * 验证配置
   */
  validate() {
    const errors = [];
    
    if (!this.provider) errors.push('provider is required');
    if (!this.model) errors.push('model is required');
    if (this.temperature < 0 || this.temperature > 2) {
      errors.push('temperature must be between 0 and 2');
    }
    if (this.maxTokens <= 0) errors.push('maxTokens must be positive');
    if (this.topP < 0 || this.topP > 1) {
      errors.push('topP must be between 0 and 1');
    }
    if (this.timeout <= 0) errors.push('timeout must be positive');
    if (this.retryCount < 0) errors.push('retryCount must be non-negative');
    
    return {
      valid: errors.length === 0,
      errors
    };
  }
  
  /**
   * 转换为对象
   */
  toObject() {
    return {
      provider: this.provider,
      model: this.model,
      apiKey: this.apiKey,
      apiEndpoint: this.apiEndpoint,
      temperature: this.temperature,
      maxTokens: this.maxTokens,
      topP: this.topP,
      frequencyPenalty: this.frequencyPenalty,
      presencePenalty: this.presencePenalty,
      timeout: this.timeout,
      retryCount: this.retryCount,
      priority: this.priority
    };
  }
  
  /**
   * 从对象创建
   */
  static fromObject(obj) {
    return new ModelConfig(obj);
  }
}

// ==================== 会话模型覆盖 ====================

/**
 * 会话模型覆盖
 */
class SessionModelOverride {
  constructor(sessionId, config = {}) {
    this.sessionId = sessionId;
    this.createdAt = new Date().toISOString();
    this.updatedAt = new Date().toISOString();
    
    // 基础配置（从全局或默认配置继承）
    this.baseConfig = new ModelConfig(config.baseConfig || {});
    
    // 覆盖配置（会话级别的配置）
    this.overrideConfig = new ModelConfig(config.overrideConfig || {});
    
    // 是否启用覆盖
    this.enabled = config.enabled !== false;
    
    // 覆盖优先级
    this.priority = config.priority || 'session';  // session, global, base
    
    // 使用统计
    this.usage = {
      callCount: 0,
      lastUsedAt: null,
      totalTokensUsed: 0,
      errors: 0
    };
    
    // 元数据
    this.metadata = config.metadata || {};
  }
  
  /**
   * 获取有效配置
   */
  getEffectiveConfig() {
    if (!this.enabled) {
      return this.baseConfig;
    }
    
    switch (this.priority) {
      case 'session':
        return this.overrideConfig;
      case 'base':
        return this.baseConfig;
      case 'global':
        // 这里可以集成全局配置
        return this.overrideConfig;
      default:
        return this.overrideConfig;
    }
  }
  
  /**
   * 设置覆盖配置
   */
  setOverrideConfig(config) {
    this.overrideConfig = new ModelConfig(config);
    this.updatedAt = new Date().toISOString();
    this.enabled = true;
  }
  
  /**
   * 清除覆盖配置
   */
  clearOverride() {
    this.overrideConfig = new ModelConfig();
    this.enabled = false;
    this.updatedAt = new Date().toISOString();
  }
  
  /**
   * 更新部分配置
   */
  updateConfig(partialConfig) {
    this.overrideConfig = this.overrideConfig.merge(partialConfig);
    this.updatedAt = new Date().toISOString();
    this.enabled = true;
  }
  
  /**
   * 记录使用
   */
  recordUsage(tokensUsed = 0, error = null) {
    this.usage.callCount++;
    this.usage.lastUsedAt = new Date().toISOString();
    this.usage.totalTokensUsed += tokensUsed;
    
    if (error) {
      this.usage.errors++;
    }
    
    this.updatedAt = new Date().toISOString();
  }
  
  /**
   * 获取使用统计
   */
  getUsageStats() {
    return { ...this.usage };
  }
  
  /**
   * 验证配置
   */
  validate() {
    const baseValidation = this.baseConfig.validate();
    const overrideValidation = this.overrideConfig.validate();
    
    return {
      baseValid: baseValidation.valid,
      baseErrors: baseValidation.errors,
      overrideValid: overrideValidation.valid,
      overrideErrors: overrideValidation.errors,
      overallValid: baseValidation.valid && overrideValidation.valid
    };
  }
  
  /**
   * 转换为对象
   */
  toObject() {
    return {
      sessionId: this.sessionId,
      createdAt: this.createdAt,
      updatedAt: this.updatedAt,
      baseConfig: this.baseConfig.toObject(),
      overrideConfig: this.overrideConfig.toObject(),
      enabled: this.enabled,
      priority: this.priority,
      usage: this.usage,
      metadata: this.metadata
    };
  }
  
  /**
   * 从对象创建
   */
  static fromObject(obj) {
    const override = new SessionModelOverride(obj.sessionId);
    override.createdAt = obj.createdAt;
    override.updatedAt = obj.updatedAt;
    override.baseConfig = ModelConfig.fromObject(obj.baseConfig);
    override.overrideConfig = ModelConfig.fromObject(obj.overrideConfig);
    override.enabled = obj.enabled;
    override.priority = obj.priority;
    override.usage = obj.usage;
    override.metadata = obj.metadata;
    return override;
  }
}

// ==================== 会话运行时模型管理器 ====================

/**
 * 会话运行时模型管理器
 */
class SessionRuntimeModelManager {
  constructor() {
    this.overrides = new Map();
    this.globalConfig = new ModelConfig();
    this.loaded = false;
  }
  
  /**
   * 初始化
   */
  async initialize() {
    await ensureSessionDir();
    await this.loadOverrides();
    this.loaded = true;
  }
  
  /**
   * 加载覆盖配置
   */
  async loadOverrides() {
    try {
      const filePath = path.join(SESSION_DIR, MODEL_OVERRIDE_FILE);
      const content = await fs.readFile(filePath, 'utf8');
      const data = JSON.parse(content);
      
      for (const obj of data.overrides || []) {
        const override = SessionModelOverride.fromObject(obj);
        this.overrides.set(override.sessionId, override);
      }
      
      // 加载全局配置
      if (data.globalConfig) {
        this.globalConfig = ModelConfig.fromObject(data.globalConfig);
      }
      
      console.log(`[SessionRuntimeModel] Loaded ${this.overrides.size} session overrides`);
    } catch (err) {
      console.log(`[SessionRuntimeModel] No existing overrides found: ${err.message}`);
    }
  }
  
  /**
   * 保存覆盖配置
   */
  async saveOverrides() {
    try {
      await ensureSessionDir();
      
      const filePath = path.join(SESSION_DIR, MODEL_OVERRIDE_FILE);
      const data = {
        version: '1.0',
        globalConfig: this.globalConfig.toObject(),
        overrides: Array.from(this.overrides.values()).map(o => o.toObject()),
        savedAt: new Date().toISOString()
      };
      
      await fs.writeFile(filePath, JSON.stringify(data, null, 2));
      
      console.log(`[SessionRuntimeModel] Saved ${this.overrides.size} session overrides`);
    } catch (err) {
      console.error(`[SessionRuntimeModel] Failed to save overrides: ${err.message}`);
      throw err;
    }
  }
  
  /**
   * 创建会话覆盖
   */
  async createOverride(sessionId, config = {}) {
    const override = new SessionModelOverride(sessionId, config);
    this.overrides.set(sessionId, override);
    await this.saveOverrides();
    return override;
  }
  
  /**
   * 获取会话覆盖
   */
  getOverride(sessionId) {
    return this.overrides.get(sessionId) || null;
  }
  
  /**
   * 更新会话覆盖
   */
  async updateOverride(sessionId, config) {
    const override = this.overrides.get(sessionId);
    
    if (!override) {
      throw new Error(`Session override not found: ${sessionId}`);
    }
    
    override.updateConfig(config);
    await this.saveOverrides();
    return override;
  }
  
  /**
   * 删除会话覆盖
   */
  async deleteOverride(sessionId) {
    const deleted = this.overrides.delete(sessionId);
    if (deleted) {
      await this.saveOverrides();
    }
    return deleted;
  }
  
  /**
   * 获取会话的有效模型配置
   */
  getModelConfig(sessionId) {
    const override = this.overrides.get(sessionId);
    
    if (override && override.enabled) {
      return override.getEffectiveConfig();
    }
    
    // 返回全局配置
    return this.globalConfig;
  }
  
  /**
   * 切换会话模型
   */
  async switchModel(sessionId, modelConfig) {
    const config = new ModelConfig(modelConfig);
    const validation = config.validate();
    
    if (!validation.valid) {
      throw new Error(`Invalid model config: ${validation.errors.join(', ')}`);
    }
    
    let override = this.overrides.get(sessionId);
    
    if (!override) {
      override = await this.createOverride(sessionId, {
        baseConfig: this.globalConfig.toObject(),
        overrideConfig: modelConfig
      });
    } else {
      override.setOverrideConfig(modelConfig);
      await this.saveOverrides();
    }
    
    return override;
  }
  
  /**
   * 设置全局配置
   */
  async setGlobalConfig(config) {
    this.globalConfig = new ModelConfig(config);
    await this.saveOverrides();
  }
  
  /**
   * 获取全局配置
   */
  getGlobalConfig() {
    return this.globalConfig;
  }
  
  /**
   * 列出所有会话覆盖
   */
  listOverrides() {
    return Array.from(this.overrides.values()).map(o => ({
      sessionId: o.sessionId,
      enabled: o.enabled,
      model: o.overrideConfig.model,
      provider: o.overrideConfig.provider,
      priority: o.priority,
      createdAt: o.createdAt,
      updatedAt: o.updatedAt,
      usage: o.usage
    }));
  }
  
  /**
   * 记录模型使用
   */
  async recordUsage(sessionId, tokensUsed = 0, error = null) {
    const override = this.overrides.get(sessionId);
    
    if (override) {
      override.recordUsage(tokensUsed, error);
      await this.saveOverrides();
    }
  }
  
  /**
   * 清理过期覆盖
   */
  async cleanupExpiredOverrides(maxAge = 7 * 24 * 60 * 60 * 1000) {  // 默认7天
    const now = Date.now();
    const toDelete = [];
    
    for (const [sessionId, override] of this.overrides.entries()) {
      const elapsed = now - new Date(override.updatedAt).getTime();
      
      // 如果超过最大时间且未被使用，删除
      if (elapsed > maxAge && (!override.usage.lastUsedAt || (now - new Date(override.usage.lastUsedAt).getTime()) > maxAge)) {
        toDelete.push(sessionId);
      }
    }
    
    for (const sessionId of toDelete) {
      this.overrides.delete(sessionId);
      console.log(`[SessionRuntimeModel] Cleaned up expired override: ${sessionId}`);
    }
    
    if (toDelete.length > 0) {
      await this.saveOverrides();
    }
    
    return toDelete.length;
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    const overrides = Array.from(this.overrides.values());
    
    return {
      totalOverrides: overrides.length,
      enabledOverrides: overrides.filter(o => o.enabled).length,
      totalUsage: overrides.reduce((sum, o) => sum + o.usage.callCount, 0),
      totalTokens: overrides.reduce((sum, o) => sum + o.usage.totalTokensUsed, 0),
      totalErrors: overrides.reduce((sum, o) => sum + o.usage.errors, 0),
      byProvider: this._groupBy(overrides, 'overrideConfig.provider'),
      byModel: this._groupBy(overrides, 'overrideConfig.model')
    };
  }
  
  /**
   * 分组统计
   */
  _groupBy(array, keyPath) {
    const result = {};
    
    for (const item of array) {
      const keys = keyPath.split('.');
      let value = item;
      
      for (const k of keys) {
        value = value?.[k];
      }
      
      if (value) {
        result[value] = (result[value] || 0) + 1;
      }
    }
    
    return result;
  }
  
  /**
   * 重置所有覆盖
   */
  async resetAll() {
    this.overrides.clear();
    await this.saveOverrides();
  }
}

// ==================== 全局实例 ====================

let globalManager = null;

/**
 * 获取全局管理器
 */
async function getSessionRuntimeModelManager() {
  if (!globalManager) {
    globalManager = new SessionRuntimeModelManager();
    await globalManager.initialize();
  }
  return globalManager;
}

/**
 * 设置全局管理器
 */
function setSessionRuntimeModelManager(manager) {
  globalManager = manager;
}

// ==================== 导出 ====================

module.exports = {
  // 类定义
  ModelConfig,
  SessionModelOverride,
  SessionRuntimeModelManager,
  
  // 全局实例
  getSessionRuntimeModelManager,
  setSessionRuntimeModelManager
};
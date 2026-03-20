/**
 * iFlow Context Engine Module
 * 上下文引擎模块（基于OpenClaw context-engine设计）
 * 
 * 功能:
 * - 可插拔上下文引擎架构
 * - 消息摄入与组装
 * - 智能压缩
 * - 子代理生命周期
 */

// ==================== 类型定义 ====================

/**
 * 组装结果
 */
class AssembleResult {
  constructor(data = {}) {
    this.messages = data.messages || [];
    this.estimatedTokens = data.estimatedTokens || 0;
    this.systemPromptAddition = data.systemPromptAddition || null;
  }
}

/**
 * 压缩结果
 */
class CompactResult {
  constructor(data = {}) {
    this.ok = data.ok !== false;
    this.compacted = data.compacted || false;
    this.reason = data.reason || null;
    this.result = data.result || null;
  }
}

/**
 * 摄入结果
 */
class IngestResult {
  constructor(ingested = false) {
    this.ingested = ingested;
  }
}

/**
 * 批量摄入结果
 */
class IngestBatchResult {
  constructor(ingestedCount = 0) {
    this.ingestedCount = ingestedCount;
  }
}

/**
 * 引导结果
 */
class BootstrapResult {
  constructor(data = {}) {
    this.bootstrapped = data.bootstrapped || false;
    this.importedMessages = data.importedMessages || 0;
    this.reason = data.reason || null;
  }
}

/**
 * 子代理结束原因
 */
const SubagentEndReason = {
  DELETED: 'deleted',
  COMPLETED: 'completed',
  SWEPT: 'swept',
  RELEASED: 'released'
};

// ==================== 上下文引擎接口 ====================

/**
 * 上下文引擎基类
 */
class ContextEngine {
  constructor(info) {
    this.info = {
      id: info.id || 'default',
      name: info.name || 'Default Context Engine',
      version: info.version || '1.0.0',
      ownsCompaction: info.ownsCompaction || false
    };
  }
  
  /**
   * 初始化引擎
   */
  async bootstrap(params) {
    return new BootstrapResult({ bootstrapped: false, reason: 'Not implemented' });
  }
  
  /**
   * 摄入单条消息
   */
  async ingest(params) {
    return new IngestResult(false);
  }
  
  /**
   * 批量摄入消息
   */
  async ingestBatch(params) {
    return new IngestBatchResult(0);
  }
  
  /**
   * 组装上下文
   */
  async assemble(params) {
    return new AssembleResult();
  }
  
  /**
   * 压缩上下文
   */
  async compact(params) {
    return new CompactResult({ ok: true, compacted: false });
  }
  
  /**
   * 回合后处理
   */
  async afterTurn(params) {
    // 默认无操作
  }
  
  /**
   * 子代理生成前准备
   */
  async prepareSubagentSpawn(params) {
    return {
      rollback: () => {}
    };
  }
  
  /**
   * 子代理结束后清理
   */
  async afterSubagentEnd(params) {
    // 默认无操作
  }
  
  /**
   * 关闭引擎
   */
  async close() {
    // 默认无操作
  }
}

// ==================== 默认上下文引擎 ====================

/**
 * 默认上下文引擎实现
 */
class DefaultContextEngine extends ContextEngine {
  constructor(options = {}) {
    super({
      id: 'default',
      name: 'Default Context Engine',
      version: '1.0.0',
      ownsCompaction: false
    });
    
    this.maxMessages = options.maxMessages || 100;
    this.maxTokens = options.maxTokens || 100000;
    
    // 消息存储
    this.messages = new Map(); // sessionId -> messages[]
    this.tokenCounts = new Map(); // sessionId -> token count
  }
  
  async bootstrap(params) {
    const { sessionId } = params;
    
    if (!this.messages.has(sessionId)) {
      this.messages.set(sessionId, []);
      this.tokenCounts.set(sessionId, 0);
      return new BootstrapResult({ bootstrapped: true });
    }
    
    return new BootstrapResult({ bootstrapped: false, reason: 'Already initialized' });
  }
  
  async ingest(params) {
    const { sessionId, message, isHeartbeat } = params;
    
    let messages = this.messages.get(sessionId);
    if (!messages) {
      messages = [];
      this.messages.set(sessionId, messages);
      this.tokenCounts.set(sessionId, 0);
    }
    
    // 检查重复
    const lastMessage = messages[messages.length - 1];
    if (lastMessage && this._isDuplicate(lastMessage, message)) {
      return new IngestResult(false);
    }
    
    // 添加消息
    messages.push(message);
    
    // 更新Token计数
    const tokens = this._estimateTokens(message);
    this.tokenCounts.set(sessionId, this.tokenCounts.get(sessionId) + tokens);
    
    return new IngestResult(true);
  }
  
  async ingestBatch(params) {
    const { sessionId, messages, isHeartbeat } = params;
    
    let ingestedCount = 0;
    
    for (const message of messages) {
      const result = await this.ingest({ sessionId, message, isHeartbeat });
      if (result.ingested) ingestedCount++;
    }
    
    return new IngestBatchResult(ingestedCount);
  }
  
  async assemble(params) {
    const { sessionId, maxTokens, systemPrompt } = params;
    
    const messages = this.messages.get(sessionId) || [];
    let estimatedTokens = 0;
    
    // 计算总Token
    for (const msg of messages) {
      estimatedTokens += this._estimateTokens(msg);
    }
    
    // 如果超过限制，需要裁剪
    let finalMessages = messages;
    if (maxTokens && estimatedTokens > maxTokens) {
      finalMessages = this._trimMessages(messages, maxTokens);
      estimatedTokens = finalMessages.reduce((sum, msg) => sum + this._estimateTokens(msg), 0);
    }
    
    return new AssembleResult({
      messages: finalMessages,
      estimatedTokens,
      systemPromptAddition: systemPrompt
    });
  }
  
  async compact(params) {
    const { sessionId, maxTokens, strategy } = params;
    
    const messages = this.messages.get(sessionId) || [];
    const currentTokens = this.tokenCounts.get(sessionId) || 0;
    
    if (currentTokens <= maxTokens) {
      return new CompactResult({ ok: true, compacted: false });
    }
    
    // 执行压缩
    const trimmed = this._trimMessages(messages, maxTokens * 0.7); // 目标70%
    const newTokens = trimmed.reduce((sum, msg) => sum + this._estimateTokens(msg), 0);
    
    // 更新存储
    this.messages.set(sessionId, trimmed);
    this.tokenCounts.set(sessionId, newTokens);
    
    return new CompactResult({
      ok: true,
      compacted: true,
      result: {
        tokensBefore: currentTokens,
        tokensAfter: newTokens
      }
    });
  }
  
  async close() {
    this.messages.clear();
    this.tokenCounts.clear();
  }
  
  // ==================== 辅助方法 ====================
  
  _isDuplicate(msg1, msg2) {
    if (msg1.id && msg2.id && msg1.id === msg2.id) return true;
    if (msg1.content === msg2.content && msg1.role === msg2.role) return true;
    return false;
  }
  
  _estimateTokens(message) {
    if (!message) return 0;
    
    let content = '';
    if (typeof message.content === 'string') {
      content = message.content;
    } else if (message.content) {
      content = JSON.stringify(message.content);
    }
    
    // 简化估算：英文4字符/token，中文1.5字符/token
    const chineseChars = (content.match(/[\u4e00-\u9fa5]/g) || []).length;
    const otherChars = content.length - chineseChars;
    return Math.ceil(chineseChars / 1.5 + otherChars / 4);
  }
  
  _trimMessages(messages, maxTokens) {
    const result = [];
    let currentTokens = 0;
    
    // 反向遍历，保留最新消息
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      const tokens = this._estimateTokens(msg);
      
      if (currentTokens + tokens <= maxTokens) {
        result.unshift(msg);
        currentTokens += tokens;
      } else {
        break;
      }
    }
    
    return result;
  }
}

// ==================== 上下文引擎注册表 ====================

/**
 * 上下文引擎注册表
 */
class ContextEngineRegistry {
  constructor() {
    this.engines = new Map(); // id -> { factory, owner, instance }
    this.defaultEngine = null;
  }
  
  /**
   * 注册上下文引擎
   */
  register(id, factory, owner = 'system', options = {}) {
    const { allowSameOwnerRefresh = false } = options;
    
    const existing = this.engines.get(id);
    if (existing) {
      if (!allowSameOwnerRefresh || existing.owner !== owner) {
        return { ok: false, existingOwner: existing.owner };
      }
    }
    
    this.engines.set(id, {
      factory,
      owner,
      instance: null
    });
    
    return { ok: true };
  }
  
  /**
   * 注销上下文引擎
   */
  unregister(id, owner) {
    const entry = this.engines.get(id);
    if (!entry) return false;
    
    if (entry.owner !== owner) return false;
    
    this.engines.delete(id);
    return true;
  }
  
  /**
   * 获取上下文引擎
   */
  async get(id) {
    const entry = this.engines.get(id);
    if (!entry) {
      return this.getDefault();
    }
    
    if (!entry.instance) {
      entry.instance = await entry.factory();
    }
    
    return entry.instance;
  }
  
  /**
   * 设置默认引擎
   */
  setDefault(factory) {
    this.defaultEngine = factory;
  }
  
  /**
   * 获取默认引擎
   */
  async getDefault() {
    if (this.defaultEngine) {
      return await this.defaultEngine();
    }
    return new DefaultContextEngine();
  }
  
  /**
   * 列出所有引擎
   */
  list() {
    return Array.from(this.engines.entries()).map(([id, entry]) => ({
      id,
      owner: entry.owner,
      hasInstance: !!entry.instance
    }));
  }
  
  /**
   * 关闭所有引擎
   */
  async closeAll() {
    for (const [id, entry] of this.engines) {
      if (entry.instance && typeof entry.instance.close === 'function') {
        try {
          await entry.instance.close();
        } catch (err) {
          console.error(`Failed to close engine ${id}:`, err);
        }
      }
    }
    
    this.engines.clear();
  }
}

// ==================== 全局实例 ====================

let globalRegistry = null;

/**
 * 获取全局注册表
 */
function getContextEngineRegistry() {
  if (!globalRegistry) {
    globalRegistry = new ContextEngineRegistry();
    globalRegistry.setDefault(() => new DefaultContextEngine());
  }
  return globalRegistry;
}

/**
 * 重置全局注册表（用于测试）
 */
function resetContextEngineRegistry() {
  if (globalRegistry) {
    globalRegistry.closeAll();
  }
  globalRegistry = null;
}

// ==================== 导出 ====================

module.exports = {
  // 类型
  AssembleResult,
  CompactResult,
  IngestResult,
  IngestBatchResult,
  BootstrapResult,
  SubagentEndReason,
  
  // 引擎
  ContextEngine,
  DefaultContextEngine,
  
  // 注册表
  ContextEngineRegistry,
  getContextEngineRegistry,
  resetContextEngineRegistry
};

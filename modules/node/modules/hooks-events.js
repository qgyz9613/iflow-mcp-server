/**
 * iFlow Event-Driven Hooks Module
 * 事件驱动钩子系统（基于OpenClaw设计）
 * 
 * 功能:
 * - 事件发射器模式
 * - 异步事件处理
 * - 事件过滤和条件触发
 * - 事件历史记录
 */

const { v4: uuidv4 } = require('uuid');
const EventEmitter = require('events');

// ==================== 事件类型定义 ====================

const EVENT_TYPES = {
  // 会话生命周期
  SESSION_START: 'session:start',
  SESSION_END: 'session:end',
  
  // 代理生命周期
  AGENT_START: 'agent:start',
  AGENT_END: 'agent:end',
  
  // 模型调用
  MODEL_BEFORE_CALL: 'model:beforeCall',
  MODEL_AFTER_CALL: 'model:afterCall',
  MODEL_ERROR: 'model:error',
  
  // 工具调用
  TOOL_BEFORE_CALL: 'tool:beforeCall',
  TOOL_AFTER_CALL: 'tool:afterCall',
  TOOL_ERROR: 'tool:error',
  
  // 子代理
  SUBAGENT_SPAWN: 'subagent:spawn',
  SUBAGENT_END: 'subagent:end',
  SUBAGENT_ERROR: 'subagent:error',
  
  // 消息
  MESSAGE_RECEIVED: 'message:received',
  MESSAGE_SENDING: 'message:sending',
  MESSAGE_SENT: 'message:sent',
  
  // 心跳
  HEARTBEAT_BEFORE: 'heartbeat:before',
  HEARTBEAT_AFTER: 'heartbeat:after',
  
  // 技能
  SKILL_BEFORE: 'skill:before',
  SKILL_AFTER: 'skill:after',
  
  // 记忆
  MEMORY_SAVE: 'memory:save',
  MEMORY_SEARCH: 'memory:search',
  
  // 配置
  CONFIG_CHANGE: 'config:change',
  
  // 诊断
  DIAGNOSTIC_EVENT: 'diagnostic:event'
};

// ==================== 事件发射器 ====================

class HookEventEmitter extends EventEmitter {
  constructor(options = {}) {
    super();
    this.maxListeners = options.maxListeners || 100;
    this.eventHistory = [];
    this.maxHistorySize = options.maxHistorySize || 1000;
    this.eventFilters = new Map();
    this.asyncHandlers = new Set();
  }
  
  /**
   * 发射事件（带历史记录）
   */
  emitWithHistory(eventType, data) {
    // 记录事件历史
    const event = {
      id: uuidv4(),
      type: eventType,
      data,
      timestamp: new Date().toISOString()
    };
    
    this.eventHistory.push(event);
    
    // 限制历史大小
    if (this.eventHistory.length > this.maxHistorySize) {
      this.eventHistory = this.eventHistory.slice(-this.maxHistorySize);
    }
    
    // 应用过滤器
    const filters = this.eventFilters.get(eventType) || [];
    let shouldEmit = true;
    
    for (const filter of filters) {
      if (!filter(event)) {
        shouldEmit = false;
        break;
      }
    }
    
    if (shouldEmit) {
      this.emit(eventType, event);
    }
    
    return event;
  }
  
  /**
   * 异步发射事件
   */
  async emitAsync(eventType, data) {
    const event = this.emitWithHistory(eventType, data);
    
    // 等待所有异步处理器完成
    const handlers = this.asyncHandlers.get(eventType) || [];
    await Promise.all(handlers.map(handler => handler(event)));
    
    return event;
  }
  
  /**
   * 添加事件过滤器
   */
  addFilter(eventType, filterFn) {
    if (!this.eventFilters.has(eventType)) {
      this.eventFilters.set(eventType, []);
    }
    this.eventFilters.get(eventType).push(filterFn);
  }
  
  /**
   * 注册异步处理器
   */
  onAsync(eventType, handler) {
    if (!this.asyncHandlers.has(eventType)) {
      this.asyncHandlers.set(eventType, []);
    }
    this.asyncHandlers.get(eventType).push(handler);
  }
  
  /**
   * 获取事件历史
   */
  getHistory(options = {}) {
    let history = [...this.eventHistory];
    
    // 按类型过滤
    if (options.type) {
      history = history.filter(e => e.type === options.type);
    }
    
    // 按时间过滤
    if (options.since) {
      const since = new Date(options.since).getTime();
      history = history.filter(e => new Date(e.timestamp).getTime() >= since);
    }
    
    // 限制数量
    if (options.limit) {
      history = history.slice(-options.limit);
    }
    
    return history;
  }
  
  /**
   * 清除历史
   */
  clearHistory() {
    this.eventHistory = [];
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    const stats = {
      totalEvents: this.eventHistory.length,
      eventTypes: {},
      listeners: this.eventNames().reduce((acc, name) => {
        acc[name] = this.listenerCount(name);
        return acc;
      }, {})
    };
    
    // 统计各类型事件数量
    for (const event of this.eventHistory) {
      stats.eventTypes[event.type] = (stats.eventTypes[event.type] || 0) + 1;
    }
    
    return stats;
  }
}

// ==================== 全局事件发射器 ====================

const globalEmitter = new HookEventEmitter();

// ==================== 便捷函数 ====================

/**
 * 发射事件
 */
function emit(eventType, data) {
  return globalEmitter.emitWithHistory(eventType, data);
}

/**
 * 异步发射事件
 */
async function emitAsync(eventType, data) {
  return globalEmitter.emitAsync(eventType, data);
}

/**
 * 监听事件
 */
function on(eventType, handler) {
  globalEmitter.on(eventType, handler);
  return () => globalEmitter.off(eventType, handler);
}

/**
 * 一次性监听
 */
function once(eventType, handler) {
  globalEmitter.once(eventType, handler);
}

/**
 * 添加过滤器
 */
function addFilter(eventType, filterFn) {
  globalEmitter.addFilter(eventType, filterFn);
}

/**
 * 注册异步处理器
 */
function onAsync(eventType, handler) {
  globalEmitter.onAsync(eventType, handler);
}

/**
 * 获取事件历史
 */
function getHistory(options) {
  return globalEmitter.getHistory(options);
}

/**
 * 获取统计信息
 */
function getStats() {
  return globalEmitter.getStats();
}

// ==================== 生命周期钩子映射 ====================

/**
 * 将事件映射到传统钩子调用
 */
const LIFECYCLE_HOOK_MAP = {
  'agent:start': 'beforeAgentStart',
  'agent:end': 'afterAgentEnd',
  'model:beforeCall': 'beforeModelResolve',
  'tool:beforeCall': 'beforeToolCall',
  'tool:afterCall': 'afterToolCall',
  'subagent:spawn': 'subagentSpawning',
  'subagent:end': 'subagentEnded'
};

/**
 * 从事件触发传统钩子
 */
function bridgeToHooks(eventType, hooksModule) {
  const hookType = LIFECYCLE_HOOK_MAP[eventType];
  if (!hookType || !hooksModule) return;
  
  on(eventType, (event) => {
    hooksModule.trigger(hookType, event.data);
  });
}

// ==================== 导出 ====================

module.exports = {
  // 事件类型
  EVENT_TYPES,
  
  // 类
  HookEventEmitter,
  
  // 全局实例
  globalEmitter,
  
  // 便捷函数
  emit,
  emitAsync,
  on,
  once,
  addFilter,
  onAsync,
  getHistory,
  getStats,
  
  // 桥接
  LIFECYCLE_HOOK_MAP,
  bridgeToHooks
};

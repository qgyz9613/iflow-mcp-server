/**
 * iFlow Diagnostic Events Module
 * 诊断事件模块（基于OpenClaw infra/diagnostic-events设计）
 * 
 * 功能:
 * - 模型使用追踪
 * - Webhook事件记录
 * - 消息队列监控
 * - 会话状态追踪
 * - 心跳监控
 * - 工具循环检测
 */

// ==================== 事件类型 ====================

/**
 * 诊断事件类型
 */
const DiagnosticEventTypes = {
  // 模型使用
  MODEL_USAGE: 'model.usage',
  MODEL_ERROR: 'model.error',
  
  // Webhook
  WEBHOOK_RECEIVED: 'webhook.received',
  WEBHOOK_PROCESSED: 'webhook.processed',
  WEBHOOK_ERROR: 'webhook.error',
  
  // 消息
  MESSAGE_QUEUED: 'message.queued',
  MESSAGE_PROCESSED: 'message.processed',
  
  // 会话
  SESSION_STATE: 'session.state',
  SESSION_STUCK: 'session.stuck',
  
  // 心跳
  HEARTBEAT: 'heartbeat',
  
  // 运行
  RUN_ATTEMPT: 'run.attempt',
  RUN_ERROR: 'run.error',
  
  // 工具
  TOOL_LOOP: 'tool.loop',
  TOOL_CALL: 'tool.call',
  TOOL_ERROR: 'tool.error'
};

/**
 * 会话状态
 */
const SessionStates = {
  IDLE: 'idle',
  PROCESSING: 'processing',
  WAITING: 'waiting',
  STUCK: 'stuck',
  ERROR: 'error'
};

// ==================== 事件结构 ====================

/**
 * 基础事件
 */
class DiagnosticBaseEvent {
  constructor(type, data = {}) {
    this.type = type;
    this.ts = Date.now();
    this.seq = 0; // 由管理器设置
    this.data = data;
  }
}

/**
 * 模型使用事件
 */
class DiagnosticModelUsageEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.MODEL_USAGE, data);
    
    this.sessionKey = data.sessionKey;
    this.sessionId = data.sessionId;
    this.channel = data.channel;
    this.provider = data.provider;
    this.model = data.model;
    
    this.usage = {
      input: data.usage?.input || 0,
      output: data.usage?.output || 0,
      cacheRead: data.usage?.cacheRead || 0,
      cacheWrite: data.usage?.cacheWrite || 0,
      promptTokens: data.usage?.promptTokens || 0,
      total: data.usage?.total || 0
    };
    
    this.lastCallUsage = data.lastCallUsage || null;
    this.context = data.context || null;
    this.costUsd = data.costUsd || null;
    this.durationMs = data.durationMs || null;
  }
}

/**
 * Webhook接收事件
 */
class DiagnosticWebhookReceivedEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.WEBHOOK_RECEIVED, data);
    
    this.channel = data.channel;
    this.updateType = data.updateType;
    this.chatId = data.chatId;
  }
}

/**
 * Webhook处理完成事件
 */
class DiagnosticWebhookProcessedEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.WEBHOOK_PROCESSED, data);
    
    this.channel = data.channel;
    this.updateType = data.updateType;
    this.chatId = data.chatId;
    this.durationMs = data.durationMs;
  }
}

/**
 * Webhook错误事件
 */
class DiagnosticWebhookErrorEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.WEBHOOK_ERROR, data);
    
    this.channel = data.channel;
    this.updateType = data.updateType;
    this.chatId = data.chatId;
    this.error = data.error;
  }
}

/**
 * 消息入队事件
 */
class DiagnosticMessageQueuedEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.MESSAGE_QUEUED, data);
    
    this.sessionKey = data.sessionKey;
    this.sessionId = data.sessionId;
    this.channel = data.channel;
    this.source = data.source;
    this.queueDepth = data.queueDepth;
  }
}

/**
 * 消息处理完成事件
 */
class DiagnosticMessageProcessedEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.MESSAGE_PROCESSED, data);
    
    this.channel = data.channel;
    this.messageId = data.messageId;
    this.chatId = data.chatId;
    this.sessionKey = data.sessionKey;
    this.sessionId = data.sessionId;
    this.durationMs = data.durationMs;
    this.outcome = data.outcome; // 'completed' | 'skipped' | 'error'
    this.reason = data.reason;
    this.error = data.error;
  }
}

/**
 * 会话状态事件
 */
class DiagnosticSessionStateEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.SESSION_STATE, data);
    
    this.sessionKey = data.sessionKey;
    this.sessionId = data.sessionId;
    this.prevState = data.prevState;
    this.state = data.state;
    this.reason = data.reason;
    this.queueDepth = data.queueDepth;
  }
}

/**
 * 会话卡住事件
 */
class DiagnosticSessionStuckEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.SESSION_STUCK, data);
    
    this.sessionKey = data.sessionKey;
    this.sessionId = data.sessionId;
    this.state = data.state;
    this.ageMs = data.ageMs;
    this.queueDepth = data.queueDepth;
    this.waitingSince = data.waitingSince;
    this.lastActivity = data.lastActivity;
  }
}

/**
 * 心跳事件
 */
class DiagnosticHeartbeatEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.HEARTBEAT, data);
    
    this.agentId = data.agentId;
    this.uptime = data.uptime;
    this.sessionsActive = data.sessionsActive;
    this.queuedMessages = data.queuedMessages;
    this.memoryUsage = data.memoryUsage;
    this.cpuUsage = data.cpuUsage;
  }
}

/**
 * 运行尝试事件
 */
class DiagnosticRunAttemptEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.RUN_ATTEMPT, data);
    
    this.runId = data.runId;
    this.sessionKey = data.sessionKey;
    this.agentId = data.agentId;
    this.attempt = data.attempt;
    this.maxAttempts = data.maxAttempts;
    this.delayMs = data.delayMs;
  }
}

/**
 * 工具循环事件
 */
class DiagnosticToolLoopEvent extends DiagnosticBaseEvent {
  constructor(data) {
    super(DiagnosticEventTypes.TOOL_LOOP, data);
    
    this.sessionKey = data.sessionKey;
    this.toolName = data.toolName;
    this.callCount = data.callCount;
    this.threshold = data.threshold;
    this.pattern = data.pattern;
  }
}

// ==================== 诊断管理器 ====================

/**
 * 诊断事件管理器
 */
class DiagnosticEventManager {
  constructor(options = {}) {
    this.enabled = options.enabled !== false;
    this.maxHistorySize = options.maxHistorySize || 1000;
    this.listeners = new Set();
    
    // 事件历史
    this.history = [];
    this.seqCounter = 0;
    
    // 统计
    this.stats = {
      totalEvents: 0,
      byType: {},
      byChannel: {},
      errors: 0,
      modelUsage: {
        totalInput: 0,
        totalOutput: 0,
        totalCost: 0,
        calls: 0
      },
      sessions: {
        active: new Set(),
        stuck: new Set()
      }
    };
    
    // 运行上下文
    this.runContexts = new Map();
  }
  
  // ==================== 事件发射 ====================
  
  /**
   * 发射诊断事件
   */
  emit(event) {
    if (!this.enabled) return;
    
    // 设置序列号
    event.seq = ++this.seqCounter;
    
    // 记录历史
    this._addToHistory(event);
    
    // 更新统计
    this._updateStats(event);
    
    // 通知监听器
    for (const listener of this.listeners) {
      try {
        listener(event);
      } catch (err) {
        console.error('Diagnostic event listener error:', err);
      }
    }
    
    return event;
  }
  
  /**
   * 添加事件监听器
   */
  on(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
  
  // ==================== 便捷方法 ====================
  
  /**
   * 追踪模型使用
   */
  trackModelUsage(data) {
    return this.emit(new DiagnosticModelUsageEvent(data));
  }
  
  /**
   * 追踪Webhook接收
   */
  trackWebhookReceived(data) {
    return this.emit(new DiagnosticWebhookReceivedEvent(data));
  }
  
  /**
   * 追踪Webhook处理完成
   */
  trackWebhookProcessed(data) {
    return this.emit(new DiagnosticWebhookProcessedEvent(data));
  }
  
  /**
   * 追踪Webhook错误
   */
  trackWebhookError(data) {
    return this.emit(new DiagnosticWebhookErrorEvent(data));
  }
  
  /**
   * 追踪消息入队
   */
  trackMessageQueued(data) {
    return this.emit(new DiagnosticMessageQueuedEvent(data));
  }
  
  /**
   * 追踪消息处理完成
   */
  trackMessageProcessed(data) {
    return this.emit(new DiagnosticMessageProcessedEvent(data));
  }
  
  /**
   * 追踪会话状态
   */
  trackSessionState(data) {
    return this.emit(new DiagnosticSessionStateEvent(data));
  }
  
  /**
   * 追踪会话卡住
   */
  trackSessionStuck(data) {
    return this.emit(new DiagnosticSessionStuckEvent(data));
  }
  
  /**
   * 追踪心跳
   */
  trackHeartbeat(data) {
    return this.emit(new DiagnosticHeartbeatEvent(data));
  }
  
  /**
   * 追踪运行尝试
   */
  trackRunAttempt(data) {
    return this.emit(new DiagnosticRunAttemptEvent(data));
  }
  
  /**
   * 追踪工具循环
   */
  trackToolLoop(data) {
    return this.emit(new DiagnosticToolLoopEvent(data));
  }
  
  // ==================== 运行上下文 ====================
  
  /**
   * 注册运行上下文
   */
  registerRunContext(runId, context) {
    if (!runId) return;
    
    const existing = this.runContexts.get(runId);
    if (!existing) {
      this.runContexts.set(runId, { ...context });
      return;
    }
    
    // 合并更新
    if (context.sessionKey) existing.sessionKey = context.sessionKey;
    if (context.verboseLevel) existing.verboseLevel = context.verboseLevel;
    if (context.isControlUiVisible !== undefined) {
      existing.isControlUiVisible = context.isControlUiVisible;
    }
    if (context.isHeartbeat !== undefined) {
      existing.isHeartbeat = context.isHeartbeat;
    }
  }
  
  /**
   * 获取运行上下文
   */
  getRunContext(runId) {
    return this.runContexts.get(runId);
  }
  
  /**
   * 清除运行上下文
   */
  clearRunContext(runId) {
    this.runContexts.delete(runId);
  }
  
  // ==================== 历史管理 ====================
  
  /**
   * 添加到历史
   */
  _addToHistory(event) {
    this.history.push(event);
    
    // 限制历史大小
    if (this.history.length > this.maxHistorySize) {
      this.history.shift();
    }
  }
  
  /**
   * 获取历史
   */
  getHistory(options = {}) {
    const {
      type,
      channel,
      sessionKey,
      since,
      limit = 100
    } = options;
    
    let filtered = this.history;
    
    if (type) {
      filtered = filtered.filter(e => e.type === type);
    }
    
    if (channel) {
      filtered = filtered.filter(e => e.channel === channel);
    }
    
    if (sessionKey) {
      filtered = filtered.filter(e => e.sessionKey === sessionKey);
    }
    
    if (since) {
      filtered = filtered.filter(e => e.ts >= since);
    }
    
    return filtered.slice(-limit);
  }
  
  // ==================== 统计 ====================
  
  /**
   * 更新统计
   */
  _updateStats(event) {
    this.stats.totalEvents++;
    
    // 按类型统计
    if (!this.stats.byType[event.type]) {
      this.stats.byType[event.type] = 0;
    }
    this.stats.byType[event.type]++;
    
    // 按渠道统计
    if (event.channel) {
      if (!this.stats.byChannel[event.channel]) {
        this.stats.byChannel[event.channel] = 0;
      }
      this.stats.byChannel[event.channel]++;
    }
    
    // 模型使用统计
    if (event.type === DiagnosticEventTypes.MODEL_USAGE) {
      this.stats.modelUsage.totalInput += event.usage.input || 0;
      this.stats.modelUsage.totalOutput += event.usage.output || 0;
      this.stats.modelUsage.totalCost += event.costUsd || 0;
      this.stats.modelUsage.calls++;
    }
    
    // 错误统计
    if (event.type.includes('error')) {
      this.stats.errors++;
    }
    
    // 会话状态
    if (event.type === DiagnosticEventTypes.SESSION_STATE) {
      if (event.state === SessionStates.PROCESSING) {
        this.stats.sessions.active.add(event.sessionKey);
      } else if (event.state === SessionStates.IDLE || event.state === SessionStates.ERROR) {
        this.stats.sessions.active.delete(event.sessionKey);
        this.stats.sessions.stuck.delete(event.sessionKey);
      }
    }
    
    if (event.type === DiagnosticEventTypes.SESSION_STUCK) {
      this.stats.sessions.stuck.add(event.sessionKey);
    }
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    return {
      ...this.stats,
      sessions: {
        active: this.stats.sessions.active.size,
        stuck: this.stats.sessions.stuck.size
      }
    };
  }
  
  // ==================== 控制方法 ====================
  
  /**
   * 启用诊断
   */
  enable() {
    this.enabled = true;
  }
  
  /**
   * 禁用诊断
   */
  disable() {
    this.enabled = false;
  }
  
  /**
   * 清除历史和统计
   */
  reset() {
    this.history = [];
    this.seqCounter = 0;
    this.stats = {
      totalEvents: 0,
      byType: {},
      byChannel: {},
      errors: 0,
      modelUsage: {
        totalInput: 0,
        totalOutput: 0,
        totalCost: 0,
        calls: 0
      },
      sessions: {
        active: new Set(),
        stuck: new Set()
      }
    };
    this.runContexts.clear();
  }
}

// ==================== 全局实例 ====================

let globalDiagnostics = null;

/**
 * 获取全局诊断实例
 */
function getDiagnostics(options) {
  if (!globalDiagnostics) {
    globalDiagnostics = new DiagnosticEventManager(options);
  }
  return globalDiagnostics;
}

/**
 * 重置全局诊断实例（用于测试）
 */
function resetDiagnostics() {
  if (globalDiagnostics) {
    globalDiagnostics.reset();
  }
  globalDiagnostics = null;
}

// ==================== 导出 ====================

module.exports = {
  // 类型
  DiagnosticEventTypes,
  SessionStates,
  
  // 事件类
  DiagnosticBaseEvent,
  DiagnosticModelUsageEvent,
  DiagnosticWebhookReceivedEvent,
  DiagnosticWebhookProcessedEvent,
  DiagnosticWebhookErrorEvent,
  DiagnosticMessageQueuedEvent,
  DiagnosticMessageProcessedEvent,
  DiagnosticSessionStateEvent,
  DiagnosticSessionStuckEvent,
  DiagnosticHeartbeatEvent,
  DiagnosticRunAttemptEvent,
  DiagnosticToolLoopEvent,
  
  // 管理器
  DiagnosticEventManager,
  
  // 全局实例
  getDiagnostics,
  resetDiagnostics
};

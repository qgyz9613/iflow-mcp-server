/**
 * Subagent Lifecycle Management
 * 子代理生命周期管理（基于OpenClaw设计）
 * 增强生命周期钩子、完成消息流和清理机制
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');

// ==================== 生命周期事件定义 ====================

/**
 * 生命周期事件类型
 */
const LifecycleEventType = {
  // 代理启动事件
  BEFORE_SPAWN: 'beforeSpawn',
  SPAWNED: 'spawned',
  AFTER_SPAWN: 'afterSpawn',
  
  // 代理执行事件
  BEFORE_EXECUTE: 'beforeExecute',
  EXECUTING: 'executing',
  AFTER_EXECUTE: 'afterExecute',
  
  // 代理结束事件
  BEFORE_END: 'beforeEnd',
  ENDED: 'ended',
  AFTER_END: 'afterEnd',
  
  // 特殊事件
  TIMEOUT: 'timeout',
  CANCELLED: 'cancelled',
  ERROR: 'error',
  KILLED: 'killed'
};

/**
 * 结束原因
 */
const EndReason = {
  COMPLETED: 'completed',
  ERROR: 'error',
  TIMEOUT: 'timeout',
  CANCELLED: 'cancelled',
  KILLED: 'killed',
  FAILED: 'failed'
};

/**
 * 子代理状态
 */
const SubagentStatus = {
  PENDING: 'pending',
  RUNNING: 'running',
  PAUSED: 'paused',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
  TIMEOUT: 'timeout',
  KILLED: 'killed'
};

// ==================== 生命周期事件类 ====================

/**
 * 生命周期事件
 */
class LifecycleEvent {
  constructor(type, data = {}) {
    this.id = uuidv4();
    this.type = type;
    this.timestamp = new Date().toISOString();
    this.data = data;
    this.handled = false;
    this.handlers = [];
  }
  
  /**
   * 添加处理器
   */
  addHandler(handler) {
    this.handlers.push(handler);
  }
  
  /**
   * 触发所有处理器
   */
  async trigger(context) {
    for (const handler of this.handlers) {
      try {
        await handler(this, context);
      } catch (error) {
        console.error(`[LifecycleEvent] Handler error: ${error.message}`);
      }
    }
    this.handled = true;
  }
  
  /**
   * 标记为已处理
   */
  markHandled() {
    this.handled = true;
  }
}

// ==================== 完成消息流类 ====================

/**
 * 完成消息流（基于OpenClaw设计）
 * 支持结构化的完成消息发送和路由
 */
class CompletionMessageFlow {
  constructor(config = {}) {
    this.enabled = config.enabled !== false;
    this.defaultChannel = config.defaultChannel || 'main';
    this.retryAttempts = config.retryAttempts || 3;
    this.messageQueue = [];
    this.handlers = new Map();
  }
  
  /**
   * 发送完成消息
   */
  async sendCompletion(runId, options = {}) {
    const message = {
      id: uuidv4(),
      runId,
      type: 'completion',
      timestamp: new Date().toISOString(),
      
      // 消息内容
      status: options.status || SubagentStatus.COMPLETED,
      result: options.result || null,
      error: options.error || null,
      summary: options.summary || null,
      
      // 路由信息
      channel: options.channel || this.defaultChannel,
      priority: options.priority || 'normal',
      
      // 重试信息
      retryCount: 0,
      lastAttempt: null
    };
    
    // 如果启用了完成消息流，添加到队列
    if (this.enabled) {
      this.messageQueue.push(message);
      
      // 尝试发送
      await this._trySend(message);
    }
    
    return message;
  }
  
  /**
   * 尝试发送消息
   */
  async _trySend(message) {
    const handler = this.handlers.get(message.channel);
    
    if (handler) {
      message.lastAttempt = new Date().toISOString();
      
      try {
        await handler(message);
        
        // 发送成功，从队列移除
        const index = this.messageQueue.indexOf(message);
        if (index > -1) {
          this.messageQueue.splice(index, 1);
        }
        
        return true;
      } catch (error) {
        // 发送失败，重试
        message.retryCount++;
        
        if (message.retryCount < this.retryAttempts) {
          console.warn(`[CompletionMessageFlow] Send failed, retrying (${message.retryCount}/${this.retryAttempts})`);
          await this._delay(1000 * message.retryCount);
          return this._trySend(message);
        } else {
          console.error(`[CompletionMessageFlow] Send failed after ${this.retryAttempts} attempts`);
          
          // 标记为失败
          message.status = 'failed';
          message.error = error.message;
          
          return false;
        }
      }
    } else {
      console.warn(`[CompletionMessageFlow] No handler for channel: ${message.channel}`);
      return false;
    }
  }
  
  /**
   * 注册消息处理器
   */
  registerHandler(channel, handler) {
    this.handlers.set(channel, handler);
  }
  
  /**
   * 获取队列状态
   */
  getQueueStatus() {
    return {
      total: this.messageQueue.length,
      pending: this.messageQueue.filter(m => m.status !== 'failed' && m.status !== 'sent').length,
      failed: this.messageQueue.filter(m => m.status === 'failed').length
    };
  }
  
  /**
   * 清空队列
   */
  clearQueue() {
    this.messageQueue = [];
  }
  
  /**
   * 延迟函数
   */
  _delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

// ==================== 生命周期管理器 ====================

/**
 * 子代理生命周期管理器
 */
class SubagentLifecycleManager {
  constructor(config = {}) {
    this.config = {
      enableHooks: config.enableHooks !== false,
      enableCompletionFlow: config.enableCompletionFlow !== false,
      enableAutoCleanup: config.enableAutoCleanup !== false,
      maxInactiveTime: config.maxInactiveTime || 30 * 60 * 1000, // 30分钟
      ...config
    };
    
    // 生命周期事件处理器
    this.eventHandlers = new Map();
    
    // 完成消息流
    this.completionFlow = new CompletionMessageFlow({
      enabled: this.config.enableCompletionFlow,
      defaultChannel: config.defaultChannel || 'main'
    });
    
    // 活跃子代理追踪
    this.activeSubagents = new Map();
    
    // 清理定时器
    this.cleanupTimer = null;
  }
  
  /**
   * 注册生命周期事件处理器
   */
  on(eventType, handler) {
    if (!this.eventHandlers.has(eventType)) {
      this.eventHandlers.set(eventType, []);
    }
    this.eventHandlers.get(eventType).push(handler);
  }
  
  /**
   * 触发生命周期事件
   */
  async trigger(eventType, context) {
    if (!this.config.enableHooks) {
      return;
    }
    
    const handlers = this.eventHandlers.get(eventType) || [];
    
    for (const handler of handlers) {
      try {
        await handler(context);
      } catch (error) {
        console.error(`[LifecycleManager] Event handler error: ${error.message}`);
      }
    }
  }
  
  /**
   * 启动生命周期
   */
  async startLifecycle(runId, taskInfo) {
    const lifecycleId = uuidv4();
    
    const lifecycle = {
      id: lifecycleId,
      runId,
      status: SubagentStatus.RUNNING,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      
      // 任务信息
      taskInfo,
      
      // 事件历史
      events: [],
      
      // 统计信息
      stats: {
        totalEvents: 0,
        eventsByType: {}
      }
    };
    
    // 触发beforeSpawn事件
    await this.trigger(LifecycleEventType.BEFORE_SPAWN, {
      lifecycleId,
      runId,
      taskInfo
    });
    
    // 记录事件
    this._recordEvent(lifecycle, LifecycleEventType.BEFORE_SPAWN, { taskInfo });
    
    // 存储生命周期
    this.activeSubagents.set(lifecycleId, lifecycle);
    
    // 触发spawned事件
    await this.trigger(LifecycleEventType.SPAWNED, {
      lifecycleId,
      runId,
      taskInfo
    });
    
    this._recordEvent(lifecycle, LifecycleEventType.SPAWNED, {});
    
    // 触发afterSpawn事件
    await this.trigger(LifecycleEventType.AFTER_SPAWN, {
      lifecycleId,
      runId,
      taskInfo
    });
    
    this._recordEvent(lifecycle, LifecycleEventType.AFTER_SPAWN, {});
    
    return lifecycleId;
  }
  
  /**
   * 更新生命周期状态
   */
  async updateStatus(lifecycleId, status, reason = null, data = {}) {
    const lifecycle = this.activeSubagents.get(lifecycleId);
    
    if (!lifecycle) {
      console.warn(`[LifecycleManager] Lifecycle not found: ${lifecycleId}`);
      return;
    }
    
    lifecycle.status = status;
    lifecycle.updatedAt = new Date().toISOString();
    
    if (reason) {
      lifecycle.endReason = reason;
    }
    
    // 记录事件
    this._recordEvent(lifecycle, status === SubagentStatus.COMPLETED ? LifecycleEventType.ENDED : status, {
      reason,
      ...data
    });
    
    // 触发相应事件
    const eventType = this._mapStatusToEvent(status);
    if (eventType) {
      await this.trigger(eventType, {
        lifecycleId,
        runId: lifecycle.runId,
        status,
        reason,
        ...data
      });
    }
    
    // 如果是结束状态，发送完成消息
    if (this._isEndStatus(status)) {
      await this._sendCompletion(lifecycle, status, reason, data);
    }
  }
  
  /**
   * 结束生命周期
   */
  async endLifecycle(lifecycleId, status, reason = null, result = null, error = null) {
    const lifecycle = this.activeSubagents.get(lifecycleId);
    
    if (!lifecycle) {
      console.warn(`[LifecycleManager] Lifecycle not found: ${lifecycleId}`);
      return;
    }
    
    // 触发beforeEnd事件
    await this.trigger(LifecycleEventType.BEFORE_END, {
      lifecycleId,
      runId: lifecycle.runId,
      status,
      reason
    });
    
    this._recordEvent(lifecycle, LifecycleEventType.BEFORE_END, { status, reason });
    
    // 更新状态
    await this.updateStatus(lifecycleId, status, reason, { result, error });
    
    // 触发ended事件
    await this.trigger(LifecycleEventType.ENDED, {
      lifecycleId,
      runId: lifecycle.runId,
      status,
      reason,
      result,
      error
    });
    
    this._recordEvent(lifecycle, LifecycleEventType.ENDED, { status, reason });
    
    // 触发afterEnd事件
    await this.trigger(LifecycleEventType.AFTER_END, {
      lifecycleId,
      runId: lifecycle.runId,
      status,
      reason
    });
    
    this._recordEvent(lifecycle, LifecycleEventType.AFTER_END, { status, reason });
    
    // 标记为非活跃（但保留一段时间用于审计）
    lifecycle.active = false;
    lifecycle.endedAt = new Date().toISOString();
  }
  
  /**
   * 发送完成消息
   */
  async _sendCompletion(lifecycle, status, reason, data) {
    if (!this.config.enableCompletionFlow) {
      return;
    }
    
    await this.completionFlow.sendCompletion(lifecycle.runId, {
      status,
      result: data.result,
      error: data.error,
      summary: data.summary,
      reason
    });
  }
  
  /**
   * 记录事件
   */
  _recordEvent(lifecycle, eventType, data) {
    const event = {
      id: uuidv4(),
      type: eventType,
      timestamp: new Date().toISOString(),
      data
    };
    
    lifecycle.events.push(event);
    lifecycle.stats.totalEvents++;
    lifecycle.stats.eventsByType[eventType] = (lifecycle.stats.eventsByType[eventType] || 0) + 1;
  }
  
  /**
   * 映射状态到事件类型
   */
  _mapStatusToEvent(status) {
    switch (status) {
      case SubagentStatus.RUNNING:
        return LifecycleEventType.EXECUTING;
      case SubagentStatus.COMPLETED:
        return LifecycleEventType.ENDED;
      case SubagentStatus.FAILED:
        return LifecycleEventType.ERROR;
      case SubagentStatus.TIMEOUT:
        return LifecycleEventType.TIMEOUT;
      case SubagentStatus.CANCELLED:
        return LifecycleEventType.CANCELLED;
      case SubagentStatus.KILLED:
        return LifecycleEventType.KILLED;
      default:
        return null;
    }
  }
  
  /**
   * 检查是否是结束状态
   */
  _isEndStatus(status) {
    return [
      SubagentStatus.COMPLETED,
      SubagentStatus.FAILED,
      SubagentStatus.TIMEOUT,
      SubagentStatus.CANCELLED,
      SubagentStatus.KILLED
    ].includes(status);
  }
  
  /**
   * 启动自动清理
   */
  startAutoCleanup() {
    if (!this.config.enableAutoCleanup || this.cleanupTimer) {
      return;
    }
    
    this.cleanupTimer = setInterval(() => {
      this._cleanupInactive();
    }, 60000); // 每分钟检查一次
    
    console.log('[LifecycleManager] Auto cleanup started');
  }
  
  /**
   * 停止自动清理
   */
  stopAutoCleanup() {
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer);
      this.cleanupTimer = null;
      console.log('[LifecycleManager] Auto cleanup stopped');
    }
  }
  
  /**
   * 清理非活跃生命周期
   */
  _cleanupInactive() {
    const now = Date.now();
    const toRemove = [];
    
    for (const [lifecycleId, lifecycle] of this.activeSubagents.entries()) {
      if (!lifecycle.active) {
        const lastUpdate = new Date(lifecycle.updatedAt || lifecycle.endedAt || lifecycle.createdAt).getTime();
        const elapsed = now - lastUpdate;
        
        if (elapsed > this.config.maxInactiveTime) {
          toRemove.push(lifecycleId);
        }
      }
    }
    
    for (const lifecycleId of toRemove) {
      this.activeSubagents.delete(lifecycleId);
      console.log(`[LifecycleManager] Cleaned up lifecycle: ${lifecycleId}`);
    }
    
    return toRemove.length;
  }
  
  /**
   * 获取生命周期信息
   */
  getLifecycle(lifecycleId) {
    return this.activeSubagents.get(lifecycleId) || null;
  }
  
  /**
   * 获取所有活跃生命周期
   */
  getActiveLifecycles() {
    return Array.from(this.activeSubagents.values())
      .filter(l => l.active)
      .map(l => ({
        id: l.id,
        runId: l.runId,
        status: l.status,
        createdAt: l.createdAt,
        updatedAt: l.updatedAt,
        taskInfo: l.taskInfo
      }));
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    const allLifecycles = Array.from(this.activeSubagents.values());
    
    return {
      total: allLifecycles.length,
      active: allLifecycles.filter(l => l.active).length,
      inactive: allLifecycles.filter(l => !l.active).length,
      byStatus: this._groupBy(allLifecycles, 'status'),
      queueStatus: this.completionFlow.getQueueStatus()
    };
  }
  
  /**
   * 分组统计
   */
  _groupBy(array, key) {
    return array.reduce((result, item) => {
      const value = item[key];
      result[value] = (result[value] || 0) + 1;
      return result;
    }, {});
  }
  
  /**
   * 注册完成消息处理器
   */
  registerCompletionHandler(channel, handler) {
    this.completionFlow.registerHandler(channel, handler);
  }
  
  /**
   * 销毁管理器
   */
  destroy() {
    this.stopAutoCleanup();
    this.eventHandlers.clear();
    this.activeSubagents.clear();
    this.completionFlow.clearQueue();
  }
}

// ==================== 全局实例 ====================

let globalLifecycleManager = null;

/**
 * 获取全局生命周期管理器
 */
function getLifecycleManager() {
  if (!globalLifecycleManager) {
    globalLifecycleManager = new SubagentLifecycleManager();
    globalLifecycleManager.startAutoCleanup();
  }
  return globalLifecycleManager;
}

/**
 * 设置全局生命周期管理器
 */
function setLifecycleManager(manager) {
  globalLifecycleManager = manager;
}

// ==================== 导出 ====================

module.exports = {
  // 类型定义
  LifecycleEventType,
  EndReason,
  SubagentStatus,
  
  // 类定义
  LifecycleEvent,
  CompletionMessageFlow,
  SubagentLifecycleManager,
  
  // 全局实例
  getLifecycleManager,
  setLifecycleManager
};
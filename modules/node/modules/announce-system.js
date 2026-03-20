/**
 * Announce System Module
 * 通知系统（基于OpenClaw设计）
 * 支持任务协调、可靠性提升、完成消息路由、多渠道通知
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs').promises;

// ==================== 常量定义 ====================

const ANNOUNCE_DIR = path.join(__dirname, '..', 'announce-data');
const MESSAGES_DIR = path.join(ANNOUNCE_DIR, 'messages');
const QUEUES_DIR = path.join(ANNOUNCE_DIR, 'queues');

// 确保目录存在
async function ensureDirectories() {
  const dirs = [ANNOUNCE_DIR, MESSAGES_DIR, QUEUES_DIR];
  for (const dir of dirs) {
    try {
      await fs.mkdir(dir, { recursive: true });
    } catch (err) {
      console.warn(`[AnnounceSystem] Failed to create directory ${dir}: ${err.message}`);
    }
  }
}

// ==================== 消息类型 ====================

/**
 * 消息类型
 */
const MessageType = {
  TASK_STARTED: 'task_started',
  TASK_COMPLETED: 'task_completed',
  TASK_FAILED: 'task_failed',
  TASK_CANCELLED: 'task_cancelled',
  PROGRESS_UPDATE: 'progress_update',
  SYSTEM_ALERT: 'system_alert',
  USER_NOTIFICATION: 'user_notification',
  ERROR_REPORT: 'error_report',
  COMPLETION_MESSAGE: 'completion_message'
};

/**
 * 消息优先级
 */
const MessagePriority = {
  CRITICAL: 0,
  HIGH: 1,
  NORMAL: 2,
  LOW: 3
};

/**
 * 消息状态
 */
const MessageStatus = {
  PENDING: 'pending',
  QUEUED: 'queued',
  PROCESSING: 'processing',
  SENT: 'sent',
  FAILED: 'failed',
  ACKNOWLEDGED: 'acknowledged'
};

// ==================== 消息类 ====================

/**
 * 通知消息
 */
class AnnouncementMessage {
  constructor(data = {}) {
    this.id = data.id || uuidv4();
    this.type = data.type || MessageType.USER_NOTIFICATION;
    this.priority = data.priority !== undefined ? data.priority : MessagePriority.NORMAL;
    this.status = data.status || MessageStatus.PENDING;
    
    // 消息内容
    this.title = data.title || '';
    this.content = data.content || '';
    this.data = data.data || {};
    
    // 路由信息
    this.channels = data.channels || [];
    this.recipients = data.recipients || [];
    this.tags = data.tags || [];
    
    // 元数据
    this.metadata = data.metadata || {};
    this.taskId = data.taskId || null;
    this.sessionId = data.sessionId || null;
    
    // 时间戳
    this.createdAt = data.createdAt || new Date().toISOString();
    this.scheduledAt = data.scheduledAt || null;
    this.sentAt = data.sentAt || null;
    this.acknowledgedAt = data.acknowledgedAt || null;
    
    // 重试信息
    this.retryCount = data.retryCount || 0;
    this.maxRetries = data.maxRetries || 3;
    this.retryDelay = data.retryDelay || 5000;
    
    // 跟踪信息
    this.attempts = data.attempts || [];
    this.deliveredChannels = data.deliveredChannels || [];
  }
  
  /**
   * 更新状态
   */
  updateStatus(status, metadata = {}) {
    this.status = status;
    
    if (status === MessageStatus.SENT) {
      this.sentAt = new Date().toISOString();
    } else if (status === MessageStatus.ACKNOWLEDGED) {
      this.acknowledgedAt = new Date().toISOString();
    }
    
    if (Object.keys(metadata).length > 0) {
      this.metadata = { ...this.metadata, ...metadata };
    }
  }
  
  /**
   * 添加重试尝试
   */
  addAttempt(success, error = null) {
    this.attempts.push({
      timestamp: new Date().toISOString(),
      success,
      error
    });
    
    if (!success) {
      this.retryCount++;
    }
  }
  
  /**
   * 标记为已送达
   */
  markDelivered(channel) {
    if (!this.deliveredChannels.includes(channel)) {
      this.deliveredChannels.push(channel);
    }
  }
  
  /**
   * 检查是否可以重试
   */
  canRetry() {
    return this.retryCount < this.maxRetries && 
           this.status === MessageStatus.FAILED;
  }
  
  /**
   * 转换为对象
   */
  toObject() {
    return {
      id: this.id,
      type: this.type,
      priority: this.priority,
      status: this.status,
      title: this.title,
      content: this.content,
      data: this.data,
      channels: this.channels,
      recipients: this.recipients,
      tags: this.tags,
      metadata: this.metadata,
      taskId: this.taskId,
      sessionId: this.sessionId,
      createdAt: this.createdAt,
      scheduledAt: this.scheduledAt,
      sentAt: this.sentAt,
      acknowledgedAt: this.acknowledgedAt,
      retryCount: this.retryCount,
      maxRetries: this.maxRetries,
      retryDelay: this.retryDelay,
      attempts: this.attempts,
      deliveredChannels: this.deliveredChannels
    };
  }
  
  /**
   * 从对象创建
   */
  static fromObject(obj) {
    return new AnnouncementMessage(obj);
  }
}

// ==================== 消息队列 ====================

/**
 * 消息队列
 */
class MessageQueue {
  constructor(config = {}) {
    this.id = config.id || uuidv4();
    this.name = config.name || `queue-${this.id}`;
    this.messages = new Map();
    this.config = {
      maxSize: config.maxSize || 1000,
      processingTimeout: config.processingTimeout || 30000,
      maxRetries: config.maxRetries || 3,
      priorityEnabled: config.priorityEnabled !== false
    };
    this.stats = {
      enqueued: 0,
      dequeued: 0,
      processed: 0,
      failed: 0
    };
  }
  
  /**
   * 入队
   */
  async enqueue(message) {
    if (this.messages.size >= this.config.maxSize) {
      throw new Error(`Queue is full (max size: ${this.config.maxSize})`);
    }
    
    if (!(message instanceof AnnouncementMessage)) {
      message = new AnnouncementMessage(message);
    }
    
    message.updateStatus(MessageStatus.QUEUED);
    this.messages.set(message.id, message);
    this.stats.enqueued++;
    
    return message;
  }
  
  /**
   * 出队
   */
  async dequeue() {
    // 按优先级排序
    const messages = Array.from(this.messages.values())
      .filter(m => m.status === MessageStatus.QUEUED)
      .sort((a, b) => a.priority - b.priority);
    
    if (messages.length === 0) {
      return null;
    }
    
    const message = messages[0];
    message.updateStatus(MessageStatus.PROCESSING);
    this.stats.dequeued++;
    
    return message;
  }
  
  /**
   * 完成处理
   */
  async complete(messageId, success, error = null) {
    const message = this.messages.get(messageId);
    
    if (!message) {
      return null;
    }
    
    message.addAttempt(success, error);
    
    if (success) {
      message.updateStatus(MessageStatus.SENT);
      this.stats.processed++;
    } else {
      message.updateStatus(MessageStatus.FAILED);
      this.stats.failed++;
      
      // 检查是否需要重新入队
      if (message.canRetry()) {
        message.updateStatus(MessageStatus.QUEUED);
        message.metadata.nextRetryAt = Date.now() + message.retryDelay;
      }
    }
    
    // 保存到文件
    await this._saveMessage(message);
    
    return message;
  }
  
  /**
   * 确认收到
   */
  async acknowledge(messageId) {
    const message = this.messages.get(messageId);
    
    if (!message) {
      return null;
    }
    
    message.updateStatus(MessageStatus.ACKNOWLEDGED);
    await this._saveMessage(message);
    
    return message;
  }
  
  /**
   * 获取队列状态
   */
  getStatus() {
    const messages = Array.from(this.messages.values());
    
    return {
      id: this.id,
      name: this.name,
      size: this.messages.size,
      pending: messages.filter(m => m.status === MessageStatus.QUEUED).length,
      processing: messages.filter(m => m.status === MessageStatus.PROCESSING).length,
      sent: messages.filter(m => m.status === MessageStatus.SENT).length,
      failed: messages.filter(m => m.status === MessageStatus.FAILED).length,
      stats: this.stats,
      byPriority: this._countByPriority(messages)
    };
  }
  
  /**
   * 按优先级计数
   */
  _countByPriority(messages) {
    return {
      critical: messages.filter(m => m.priority === MessagePriority.CRITICAL).length,
      high: messages.filter(m => m.priority === MessagePriority.HIGH).length,
      normal: messages.filter(m => m.priority === MessagePriority.NORMAL).length,
      low: messages.filter(m => m.priority === MessagePriority.LOW).length
    };
  }
  
  /**
   * 保存消息到文件
   */
  async _saveMessage(message) {
    try {
      const filePath = path.join(MESSAGES_DIR, `${message.id}.json`);
      await fs.writeFile(filePath, JSON.stringify(message.toObject(), null, 2));
    } catch (err) {
      console.warn(`[AnnounceSystem] Failed to save message: ${err.message}`);
    }
  }
  
  /**
   * 清理已完成的消息
   */
  async cleanup(maxAge = 24 * 60 * 60 * 1000) {  // 默认24小时
    const now = Date.now();
    const toDelete = [];
    
    for (const [id, message] of this.messages.entries()) {
      if (message.status === MessageStatus.SENT || message.status === MessageStatus.ACKNOWLEDGED) {
        const createdAt = new Date(message.createdAt).getTime();
        if (now - createdAt > maxAge) {
          toDelete.push(id);
        }
      }
    }
    
    for (const id of toDelete) {
      this.messages.delete(id);
      try {
        await fs.unlink(path.join(MESSAGES_DIR, `${id}.json`));
      } catch (err) {
        console.warn(`[AnnounceSystem] Failed to delete message file: ${err.message}`);
      }
    }
    
    return toDelete.length;
  }
}

// ==================== 通知渠道 ====================

/**
 * 通知渠道
 */
class NotificationChannel {
  constructor(config = {}) {
    this.id = config.id || uuidv4();
    this.name = config.name || `channel-${this.id}`;
    this.type = config.type || 'console';
    this.enabled = config.enabled !== false;
    this.config = config.config || {};
    this.stats = {
      sent: 0,
      failed: 0,
      lastSentAt: null
    };
  }
  
  /**
   * 发送消息
   */
  async send(message) {
    if (!this.enabled) {
      return { success: false, reason: 'Channel disabled' };
    }
    
    try {
      const result = await this._send(message);
      
      if (result.success) {
        this.stats.sent++;
        this.stats.lastSentAt = new Date().toISOString();
      } else {
        this.stats.failed++;
      }
      
      return result;
    } catch (error) {
      this.stats.failed++;
      return { success: false, error: error.message };
    }
  }
  
  /**
   * 内部发送实现
   */
  async _send(message) {
    switch (this.type) {
      case 'console':
        console.log(`[${this.name}] ${message.title}: ${message.content}`);
        return { success: true };
      
      case 'log':
        return await this._sendToLog(message);
      
      default:
        return { success: false, reason: 'Unknown channel type' };
    }
  }
  
  /**
   * 发送到日志
   */
  async _sendToLog(message) {
    try {
      const logPath = path.join(MESSAGES_DIR, `${this.type}-${this.id}.log`);
      const logEntry = `[${new Date().toISOString()}] ${message.type} - ${message.title}: ${message.content}\n`;
      await fs.appendFile(logPath, logEntry);
      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    return {
      id: this.id,
      name: this.name,
      type: this.type,
      enabled: this.enabled,
      stats: this.stats
    };
  }
}

// ==================== 通知系统 ====================

/**
 * 通知系统
 */
class AnnounceSystem {
  constructor(config = {}) {
    this.queues = new Map();
    this.channels = new Map();
    this.router = null;
    this.enabled = config.enabled !== false;
    
    // 默认队列
    this.defaultQueue = new MessageQueue({ name: 'default' });
    this.queues.set(this.defaultQueue.id, this.defaultQueue);
    
    // 默认渠道
    this.defaultChannel = new NotificationChannel({ 
      name: 'console', 
      type: 'console' 
    });
    this.channels.set(this.defaultChannel.id, this.defaultChannel);
  }
  
  /**
   * 初始化
   */
  async initialize() {
    await ensureDirectories();
    await this._loadPersistedData();
    this._startProcessor();
  }
  
  /**
   * 发送通知
   */
  async announce(message, options = {}) {
    if (!this.enabled) {
      return { success: false, reason: 'System disabled' };
    }
    
    // 创建消息
    const announcement = message instanceof AnnouncementMessage 
      ? message 
      : new AnnouncementMessage(message);
    
    // 设置渠道
    if (options.channels && options.channels.length > 0) {
      announcement.channels = options.channels;
    } else if (announcement.channels.length === 0) {
      announcement.channels = [this.defaultChannel.id];
    }
    
    // 入队
    const queue = options.queueId 
      ? this.queues.get(options.queueId)
      : this.defaultQueue;
    
    if (!queue) {
      return { success: false, reason: 'Queue not found' };
    }
    
    await queue.enqueue(announcement);
    
    return { success: true, messageId: announcement.id };
  }
  
  /**
   * 任务完成通知
   */
  async announceTaskCompletion(taskId, result, error = null) {
    const message = new AnnouncementMessage({
      type: error ? MessageType.TASK_FAILED : MessageType.TASK_COMPLETED,
      priority: error ? MessagePriority.HIGH : MessagePriority.NORMAL,
      title: error ? `Task ${taskId} Failed` : `Task ${taskId} Completed`,
      content: error ? error.message : 'Task completed successfully',
      data: { taskId, result, error },
      taskId
    });
    
    return await this.announce(message);
  }
  
  /**
   * 进度更新通知
   */
  async announceProgress(taskId, progress, message) {
    const announcement = new AnnouncementMessage({
      type: MessageType.PROGRESS_UPDATE,
      priority: MessagePriority.LOW,
      title: `Task ${taskId} Progress`,
      content: message || `Progress: ${progress}%`,
      data: { taskId, progress },
      taskId
    });
    
    return await this.announce(announcement);
  }
  
  /**
   * 系统警报
   */
  async announceAlert(title, message, priority = MessagePriority.HIGH) {
    const announcement = new AnnouncementMessage({
      type: MessageType.SYSTEM_ALERT,
      priority,
      title,
      content: message,
      data: { alertType: 'system' }
    });
    
    return await this.announce(announcement);
  }
  
  /**
   * 添加队列
   */
  addQueue(queue) {
    this.queues.set(queue.id, queue);
  }
  
  /**
   * 添加渠道
   */
  addChannel(channel) {
    this.channels.set(channel.id, channel);
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    const queueStats = Array.from(this.queues.values()).map(q => q.getStatus());
    const channelStats = Array.from(this.channels.values()).map(c => c.getStats());
    
    return {
      enabled: this.enabled,
      queues: queueStats,
      channels: channelStats,
      totalQueues: this.queues.size,
      totalChannels: this.channels.size
    };
  }
  
  /**
   * 启动处理器
   */
  _startProcessor() {
    setInterval(async () => {
      if (!this.enabled) return;
      
      for (const queue of this.queues.values()) {
        const message = await queue.dequeue();
        
        if (message) {
          await this._processMessage(queue, message);
        }
      }
    }, 1000);  // 每秒检查一次
  }
  
  /**
   * 处理消息
   */
  async _processMessage(queue, message) {
    const results = [];
    
    for (const channelId of message.channels) {
      const channel = this.channels.get(channelId);
      
      if (channel && channel.enabled) {
        const result = await channel.send(message);
        results.push(result);
        
        if (result.success) {
          message.markDelivered(channelId);
        }
      }
    }
    
    // 完成处理
    const success = results.some(r => r.success);
    const error = results.find(r => !r.success)?.error;
    
    await queue.complete(message.id, success, error);
  }
  
  /**
   * 加载持久化数据
   */
  async _loadPersistedData() {
    try {
      // 加载未完成的消息
      const files = await fs.readdir(MESSAGES_DIR);
      for (const file of files) {
        if (file.endsWith('.json')) {
          const content = await fs.readFile(path.join(MESSAGES_DIR, file), 'utf8');
          const message = AnnouncementMessage.fromObject(JSON.parse(content));
          
          // 如果消息还在队列中，重新入队
          if (message.status === MessageStatus.QUEUED || message.status === MessageStatus.PROCESSING) {
            message.updateStatus(MessageStatus.QUEUED);
            this.defaultQueue.messages.set(message.id, message);
          }
        }
      }
      
      console.log(`[AnnounceSystem] Loaded ${this.defaultQueue.messages.size} persisted messages`);
    } catch (err) {
      console.log(`[AnnounceSystem] No persisted messages found`);
    }
  }
}

// ==================== 全局实例 ====================

let globalAnnounceSystem = null;

/**
 * 获取全局通知系统
 */
async function getAnnounceSystem() {
  if (!globalAnnounceSystem) {
    globalAnnounceSystem = new AnnounceSystem();
    await globalAnnounceSystem.initialize();
  }
  return globalAnnounceSystem;
}

/**
 * 设置全局通知系统
 */
function setAnnounceSystem(system) {
  globalAnnounceSystem = system;
}

// ==================== 导出 ====================

module.exports = {
  // 类型定义
  MessageType,
  MessagePriority,
  MessageStatus,
  
  // 类定义
  AnnouncementMessage,
  MessageQueue,
  NotificationChannel,
  AnnounceSystem,
  
  // 全局实例
  getAnnounceSystem,
  setAnnounceSystem,
  
  // 辅助函数
  ensureDirectories
};
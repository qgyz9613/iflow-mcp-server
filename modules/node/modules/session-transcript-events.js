/**
 * iFlow Session Transcript Events Module
 * 会话转录事件模块（基于OpenClaw transcript-events设计）
 * 
 * 功能:
 * - 会话消息更新事件
 * - 事件订阅与发布
 * - 消息ID追踪
 */

// ==================== 类型定义 ====================

/**
 * 会话转录更新
 */
class SessionTranscriptUpdate {
  constructor(data = {}) {
    this.sessionFile = data.sessionFile || '';
    this.sessionKey = data.sessionKey || null;
    this.message = data.message || undefined;
    this.messageId = data.messageId || null;
  }
}

// ==================== 事件监听器存储 ====================

const SESSION_TRANSCRIPT_LISTENERS = new Set();

// ==================== 事件订阅 ====================

/**
 * 订阅会话转录更新
 * @param {Function} listener - 监听器函数
 * @returns {Function} 取消订阅函数
 */
function onSessionTranscriptUpdate(listener) {
  if (typeof listener !== 'function') {
    throw new Error('Listener must be a function');
  }
  
  SESSION_TRANSCRIPT_LISTENERS.add(listener);
  
  // 返回取消订阅函数
  return () => {
    SESSION_TRANSCRIPT_LISTENERS.delete(listener);
  };
}

/**
 * 取消所有订阅
 */
function clearAllSessionTranscriptListeners() {
  SESSION_TRANSCRIPT_LISTENERS.clear();
}

/**
 * 获取监听器数量
 */
function getSessionTranscriptListenerCount() {
  return SESSION_TRANSCRIPT_LISTENERS.size;
}

// ==================== 事件发布 ====================

/**
 * 发送会话转录更新事件
 * @param {string|SessionTranscriptUpdate} update - 更新对象或会话文件路径
 */
function emitSessionTranscriptUpdate(update) {
  // 规范化参数
  const normalized = typeof update === 'string'
    ? { sessionFile: update }
    : {
        sessionFile: update.sessionFile,
        sessionKey: update.sessionKey,
        message: update.message,
        messageId: update.messageId
      };
  
  // 验证会话文件路径
  const trimmed = (normalized.sessionFile || '').trim();
  if (!trimmed) {
    return; // 忽略无效更新
  }
  
  // 构建更新对象
  const nextUpdate = new SessionTranscriptUpdate({
    sessionFile: trimmed,
    sessionKey: typeof normalized.sessionKey === 'string' && normalized.sessionKey.trim()
      ? normalized.sessionKey.trim()
      : undefined,
    message: normalized.message !== undefined ? normalized.message : undefined,
    messageId: typeof normalized.messageId === 'string' && normalized.messageId.trim()
      ? normalized.messageId.trim()
      : undefined
  });
  
  // 通知所有监听器
  for (const listener of SESSION_TRANSCRIPT_LISTENERS) {
    try {
      listener(nextUpdate);
    } catch (err) {
      // 忽略监听器错误，防止一个监听器失败影响其他监听器
      console.error('Session transcript listener error:', err);
    }
  }
}

// ==================== 批量更新 ====================

/**
 * 批量发送更新
 */
function emitBatchSessionTranscriptUpdates(updates) {
  if (!Array.isArray(updates)) return;
  
  for (const update of updates) {
    emitSessionTranscriptUpdate(update);
  }
}

/**
 * 延迟批量更新（合并短时间内的多次更新）
 */
function createBatchedEmitter(delayMs = 100) {
  let pending = [];
  let timer = null;
  
  const flush = () => {
    if (pending.length > 0) {
      emitBatchSessionTranscriptUpdates(pending);
      pending = [];
    }
    timer = null;
  };
  
  const schedule = () => {
    if (!timer) {
      timer = setTimeout(flush, delayMs);
      // 不阻止进程退出
      if (timer.unref) {
        timer.unref();
      }
    }
  };
  
  return {
    push(update) {
      pending.push(update);
      schedule();
    },
    flush,
    clear() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      pending = [];
    }
  };
}

// ==================== 条件监听 ====================

/**
 * 创建条件监听器
 * @param {Function} predicate - 过滤条件函数
 * @param {Function} listener - 监听器函数
 * @returns {Function} 取消订阅函数
 */
function onSessionTranscriptUpdateWhen(predicate, listener) {
  const wrappedListener = (update) => {
    if (predicate(update)) {
      listener(update);
    }
  };
  
  return onSessionTranscriptUpdate(wrappedListener);
}

/**
 * 监听特定会话文件
 */
function onSessionFileUpdate(sessionFile, listener) {
  return onSessionTranscriptUpdateWhen(
    (update) => update.sessionFile === sessionFile,
    listener
  );
}

/**
 * 监听特定消息ID
 */
function onMessageIdUpdate(messageId, listener) {
  return onSessionTranscriptUpdateWhen(
    (update) => update.messageId === messageId,
    listener
  );
}

// ==================== 异步等待 ====================

/**
 * 等待下一个更新
 * @param {Object} options - 选项
 * @param {number} options.timeoutMs - 超时时间
 * @param {Function} options.predicate - 过滤条件
 * @returns {Promise<SessionTranscriptUpdate>}
 */
function waitForNextUpdate(options = {}) {
  const { timeoutMs = 30000, predicate } = options;
  
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      unsubscribe();
      reject(new Error('Timeout waiting for session transcript update'));
    }, timeoutMs);
    
    const unsubscribe = onSessionTranscriptUpdate((update) => {
      if (predicate && !predicate(update)) {
        return; // 不符合条件的更新，继续等待
      }
      
      clearTimeout(timeout);
      unsubscribe();
      resolve(update);
    });
  });
}

/**
 * 等待特定会话的更新
 */
function waitForSessionUpdate(sessionFile, timeoutMs = 30000) {
  return waitForNextUpdate({
    timeoutMs,
    predicate: (update) => update.sessionFile === sessionFile
  });
}

// ==================== 导出 ====================

module.exports = {
  // 类型
  SessionTranscriptUpdate,
  
  // 基础订阅
  onSessionTranscriptUpdate,
  clearAllSessionTranscriptListeners,
  getSessionTranscriptListenerCount,
  
  // 发布
  emitSessionTranscriptUpdate,
  emitBatchSessionTranscriptUpdates,
  
  // 批量处理
  createBatchedEmitter,
  
  // 条件监听
  onSessionTranscriptUpdateWhen,
  onSessionFileUpdate,
  onMessageIdUpdate,
  
  // 异步等待
  waitForNextUpdate,
  waitForSessionUpdate
};

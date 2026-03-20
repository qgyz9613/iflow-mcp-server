/**
 * Legacy Context Engine
 * 传统上下文引擎实现（基于OpenClaw设计）
 * 保留100%向后兼容性
 */

const fs = require('fs').promises;
const path = require('path');

// ==================== 类型定义 ====================

/**
 * 结果类型
 */
class AssembleResult {
  constructor(messages, estimatedTokens, systemPromptAddition) {
    this.messages = messages;
    this.estimatedTokens = estimatedTokens;
    this.systemPromptAddition = systemPromptAddition;
  }
}

class CompactResult {
  constructor(ok, compacted, reason, result = null) {
    this.ok = ok;
    this.compacted = compacted;
    this.reason = reason;
    this.result = result;
  }
}

class IngestResult {
  constructor(ingested) {
    this.ingested = ingested;
  }
}

class BootstrapResult {
  constructor(bootstrapped, importedMessages = 0, reason = null) {
    this.bootstrapped = bootstrapped;
    this.importedMessages = importedMessages;
    this.reason = reason;
  }
}

// ==================== Legacy Context Engine 类 ====================

/**
 * Legacy Context Engine
 * 实现标准的上下文管理接口，保持向后兼容
 */
class LegacyContextEngine {
  constructor() {
    this.info = {
      id: 'legacy',
      name: 'Legacy Context Engine',
      version: '1.0.0',
      ownsCompaction: false
    };

    this.options = {
      maxMessages: 50,
      maxTokens: 8000,
      autoCompact: true,
      storageDir: path.join(process.env.HOME || process.env.USERPROFILE || '.', '.iflow', 'context')
    };

    this.sessions = new Map();
    this.contextStore = new Map();
  }

  /**
   * 引擎标识
   */
  get id() {
    return this.info.id;
  }

  /**
   * 引擎信息
   */
  get info() {
    return this.info;
  }

  /**
   * 初始化引擎状态
   */
  async initialize() {
    try {
      await fs.mkdir(this.options.storageDir, { recursive: true });
      console.log('[LegacyContextEngine] Initialized');
    } catch (err) {
      console.warn('[LegacyContextEngine] Failed to create storage directory:', err.message);
    }
  }

  /**
   * 摄入消息
   */
  async ingest(params) {
    const { sessionId, message, isHeartbeat = false } = params;

    if (!sessionId) {
      return new IngestResult(false);
    }

    const session = this.sessions.get(sessionId) || {
      id: sessionId,
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now()
    };

    const messageWithMeta = {
      ...message,
      id: this.generateMessageId(),
      timestamp: Date.now(),
      isHeartbeat
    };

    session.messages.push(messageWithMeta);
    session.updatedAt = Date.now();

    // 限制消息数量
    if (session.messages.length > this.options.maxMessages) {
      session.messages = session.messages.slice(-this.options.maxMessages);
    }

    this.sessions.set(sessionId, session);

    return new IngestResult(true);
  }

  /**
   * 组装上下文
   */
  async assemble(params) {
    const { sessionId, messages, tokenBudget } = params;

    const session = this.sessions.get(sessionId);

    if (!session) {
      return new AssembleResult([], 0);
    }

    const effectiveMessages = messages || session.messages;
    const maxMessages = Math.min(
      this.options.maxMessages,
      tokenBudget ? Math.floor(tokenBudget / 200) : this.options.maxMessages
    );

    const selectedMessages = effectiveMessages.slice(-maxMessages);

    // 估算 token 数量
    const estimatedTokens = this.estimateTokens(selectedMessages);

    return new AssembleResult(selectedMessages, estimatedTokens);
  }

  /**
   * 压缩上下文
   */
  async compact(params) {
    const { sessionId, tokenBudget, force = false, currentTokenCount } = params;

    const session = this.sessions.get(sessionId);

    if (!session) {
      return new CompactResult(false, false, 'Session not found');
    }

    const targetTokens = tokenBudget || this.options.maxTokens;
    const effectiveCurrentTokens = currentTokenCount || this.estimateTokens(session.messages);

    if (!force && effectiveCurrentTokens <= targetTokens) {
      return new CompactResult(
        true,
        false,
        'Context already within token budget',
        {
          tokensBefore: effectiveCurrentTokens,
          tokensAfter: effectiveCurrentTokens
        }
      );
    }

    // 压缩策略：保留最近的消息
    const keepRatio = targetTokens / effectiveCurrentTokens;
    const keepCount = Math.max(
      Math.floor(session.messages.length * keepRatio),
      10
    );
    const compactedMessages = session.messages.slice(-keepCount);

    const tokensAfter = this.compactTokens(this.estimateTokens(compactedMessages));

    session.messages = compactedMessages;
    session.updatedAt = Date.now();

    this.sessions.set(sessionId, session);

    return new CompactResult(
      true,
      true,
      'Compacted by keeping recent messages',
      {
        summary: `Kept ${keepCount} of ${session.messages.length + compactedMessages.length} messages`,
        firstKeptEntryId: compactedMessages[0]?.id,
        tokensBefore: effectiveCurrentTokens,
        tokensAfter
      }
    );
  }

  /**
   * 压缩Token计算
   */
  compactTokens(tokens) {
    // 简单的压缩策略：减少20%
    return Math.floor(tokens * 0.8);
  }

  /**
   * 获取会话
   */
  getSession(sessionId) {
    return this.sessions.get(sessionId) || null;
  }

  /**
   * 删除会话
   */
  async deleteSession(sessionId) {
    this.sessions.delete(sessionId);
    this.contextStore.delete(sessionId);
  }

  /**
   * 清理资源
   */
  async dispose() {
    // 清理所有会话
    this.sessions.clear();
    this.contextStore.clear();
    console.log('[LegacyContextEngine] Disposed');
  }

  /**
   * 估算 token 数量
   */
  estimateTokens(messages) {
    if (!Array.isArray(messages)) {
      return 0;
    }

    let totalChars = 0;
    for (const message of messages) {
      if (message.content) {
        totalChars += String(message.content).length;
      }
      if (message.role) {
        totalChars += String(message.role).length;
      }
      if (message.text) {
        totalChars += String(message.text).length;
      }
    }

    // 粗略估算：1 token ≈ 4 字符
    return Math.ceil(totalChars / 4);
  }

  /**
   * 生成消息 ID
   */
  generateMessageId() {
    return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  /**
   * 获取统计信息
   */
  getStats() {
    const sessions = Array.from(this.sessions.values());
    const totalMessages = sessions.reduce((sum, s) => sum + s.messages.length, 0);
    const totalTokens = sessions.reduce((sum, s) => sum + this.estimateTokens(s.messages), 0);

    return {
      sessionCount: sessions.length,
      totalMessages,
      totalTokens,
      avgMessagesPerSession: sessions.length > 0 ? totalMessages / sessions.length : 0
    };
  }
}

// ==================== 导出 ====================

module.exports = {
  LegacyContextEngine,
  AssembleResult,
  CompactResult,
  IngestResult,
  BootstrapResult
};
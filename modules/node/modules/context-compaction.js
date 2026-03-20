/**
 * iFlow Context Compaction Module
 * 上下文压缩模块（基于OpenClaw agents/compaction设计）
 * 
 * 功能:
 * - 智能消息压缩
 * - Token估算
 * - 分段摘要
 * - 标识符保留策略
 */

// ==================== 配置常量 ====================

const BASE_CHUNK_RATIO = 0.4;
const MIN_CHUNK_RATIO = 0.15;
const SAFETY_MARGIN = 1.2; // 20%缓冲
const DEFAULT_PARTS = 2;
const DEFAULT_SUMMARY_FALLBACK = "No prior history.";

// 标识符保留指令
const IDENTIFIER_PRESERVATION_INSTRUCTIONS = [
  "Preserve all opaque identifiers exactly as written (no shortening or reconstruction),",
  "including UUIDs, hashes, IDs, tokens, API keys, hostnames, IPs, ports, URLs, and file names."
].join(" ");

// 合并摘要指令
const MERGE_SUMMARIES_INSTRUCTIONS = [
  "Merge these partial summaries into a single cohesive summary.",
  "",
  "MUST PRESERVE:",
  "- Active tasks and their current status (in-progress, blocked, pending)",
  "- Batch operation progress (e.g., '5/17 items completed')",
  "- The last thing the user requested and what was being done about it",
  "- Decisions made and their rationale",
  "- TODOs, open questions, and constraints",
  "- Any commitments or follow-ups promised",
  "",
  "PRIORITIZE recent context over older history. The agent needs to know",
  "what it was doing, not just what was discussed.",
].join("\n");

// ==================== 消息类型 ====================

/**
 * 消息类型枚举
 */
const MessageTypes = {
  USER: 'user',
  ASSISTANT: 'assistant',
  SYSTEM: 'system',
  TOOL: 'tool',
  TOOL_RESULT: 'tool_result'
};

// ==================== Token估算 ====================

/**
 * 估算单条消息的Token数
 * 简化版：按字符数估算，中文约1.5字符/token，英文约4字符/token
 */
function estimateMessageTokens(message) {
  if (!message) return 0;
  
  let content = '';
  
  if (typeof message === 'string') {
    content = message;
  } else if (message.content) {
    if (typeof message.content === 'string') {
      content = message.content;
    } else if (Array.isArray(message.content)) {
      content = message.content.map(c => {
        if (typeof c === 'string') return c;
        if (c.text) return c.text;
        return '';
      }).join(' ');
    }
  }
  
  // 计算中文字符
  const chineseChars = (content.match(/[\u4e00-\u9fa5]/g) || []).length;
  const otherChars = content.length - chineseChars;
  
  // 中文约1.5字符/token，英文约4字符/token
  return Math.ceil(chineseChars / 1.5 + otherChars / 4);
}

/**
 * 估算消息列表总Token数
 */
function estimateMessagesTokens(messages) {
  if (!messages || !Array.isArray(messages)) return 0;
  
  return messages.reduce((sum, msg) => sum + estimateMessageTokens(msg), 0);
}

/**
 * 估算安全Token数（含缓冲）
 */
function estimateSafeTokens(messages) {
  const estimated = estimateMessagesTokens(messages);
  return Math.ceil(estimated * SAFETY_MARGIN);
}

// ==================== 消息处理 ====================

/**
 * 清理工具结果详情（安全处理）
 */
function stripToolResultDetails(messages) {
  return messages.map(msg => {
    if (msg.type === MessageTypes.TOOL_RESULT && msg.details) {
      const { details, ...rest } = msg;
      return rest;
    }
    return msg;
  });
}

/**
 * 规范化分段数
 */
function normalizeParts(parts, messageCount) {
  if (!Number.isFinite(parts) || parts <= 1) return 1;
  return Math.min(Math.max(1, Math.floor(parts)), Math.max(1, messageCount));
}

/**
 * 按Token份额分割消息
 */
function splitMessagesByTokenShare(messages, parts = DEFAULT_PARTS) {
  if (messages.length === 0) return [];
  
  const normalizedParts = normalizeParts(parts, messages.length);
  if (normalizedParts <= 1) return [messages];
  
  const totalTokens = estimateMessagesTokens(messages);
  const tokensPerPart = Math.ceil(totalTokens / normalizedParts);
  
  const result = [];
  let currentPart = [];
  let currentTokens = 0;
  
  for (const msg of messages) {
    const msgTokens = estimateMessageTokens(msg);
    
    if (currentTokens + msgTokens > tokensPerPart && currentPart.length > 0) {
      result.push(currentPart);
      currentPart = [];
      currentTokens = 0;
    }
    
    currentPart.push(msg);
    currentTokens += msgTokens;
  }
  
  if (currentPart.length > 0) {
    result.push(currentPart);
  }
  
  return result;
}

// ==================== 压缩策略 ====================

/**
 * 压缩策略类型
 */
const CompactionStrategies = {
  SUMMARIZE: 'summarize',     // 摘要压缩
  TRUNCATE: 'truncate',       // 截断
  PRUNE: 'prune',            // 剪枝（移除不重要的）
  HYBRID: 'hybrid'           // 混合策略
};

/**
 * 选择压缩策略
 */
function selectCompactionStrategy(params) {
  const { currentTokens, maxTokens, messageCount } = params;
  
  const ratio = currentTokens / maxTokens;
  
  if (ratio > 2) {
    // 超过限制2倍，使用混合策略
    return CompactionStrategies.HYBRID;
  } else if (ratio > 1.5) {
    // 超过限制1.5倍，使用摘要策略
    return CompactionStrategies.SUMMARIZE;
  } else {
    // 超过限制1-1.5倍，使用剪枝策略
    return CompactionStrategies.PRUNE;
  }
}

/**
 * 计算压缩目标
 */
function calculateCompactionTarget(currentTokens, maxTokens, strategy) {
  // 目标：留出安全边际
  const targetRatio = {
    [CompactionStrategies.SUMMARIZE]: 0.6,
    [CompactionStrategies.TRUNCATE]: 0.7,
    [CompactionStrategies.PRUNE]: 0.75,
    [CompactionStrategies.HYBRID]: 0.5
  };
  
  const ratio = targetRatio[strategy] || 0.6;
  return Math.floor(maxTokens * ratio);
}

// ==================== 摘要生成 ====================

/**
 * 构建压缩摘要指令
 */
function buildCompactionSummarizationInstructions(customInstructions, identifierPolicy = 'strict') {
  const instructions = [];
  
  // 标识符保留
  if (identifierPolicy !== 'off') {
    instructions.push(IDENTIFIER_PRESERVATION_INSTRUCTIONS);
  }
  
  // 自定义指令
  if (customInstructions) {
    instructions.push(`Additional focus:\n${customInstructions}`);
  }
  
  return instructions.length > 0 ? instructions.join('\n\n') : null;
}

/**
 * 生成消息摘要
 * 注：实际摘要生成需要调用LLM，这里提供框架
 */
async function generateMessagesSummary(messages, options = {}) {
  const {
    customInstructions,
    identifierPolicy = 'strict',
    maxOutputTokens = 1000,
    llmClient = null
  } = options;
  
  // 计算消息内容
  const content = messages.map(msg => {
    const role = msg.role || msg.type || 'unknown';
    const text = typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content);
    return `[${role}]: ${text}`;
  }).join('\n\n');
  
  // 构建摘要指令
  const instructions = buildCompactionSummarizationInstructions(customInstructions, identifierPolicy);
  
  // 返回摘要请求结构（需要LLM客户端执行）
  return {
    type: 'summary_request',
    content,
    instructions,
    maxOutputTokens,
    messageCount: messages.length,
    estimatedInputTokens: estimateMessagesTokens(messages)
  };
}

/**
 * 合并部分摘要
 */
function mergePartialSummaries(summaries) {
  if (summaries.length === 0) return DEFAULT_SUMMARY_FALLBACK;
  if (summaries.length === 1) return summaries[0];
  
  return {
    type: 'merge_request',
    summaries,
    instructions: MERGE_SUMMARIES_INSTRUCTIONS
  };
}

// ==================== 消息优先级 ====================

/**
 * 消息优先级
 */
const MessagePriority = {
  CRITICAL: 100,    // 系统消息、用户最新请求
  HIGH: 80,         // 最近的工具调用结果
  MEDIUM: 60,       // 最近的对话
  LOW: 40,          // 历史对话
  MINIMAL: 20       // 可以移除的消息
};

/**
 * 计算消息优先级
 */
function calculateMessagePriority(message, context = {}) {
  const { currentIndex, totalCount, messageTypes = [] } = context;
  
  let priority = MessagePriority.MEDIUM;
  
  // 系统消息最高优先级
  if (message.type === MessageTypes.SYSTEM || message.role === 'system') {
    return MessagePriority.CRITICAL;
  }
  
  // 最新用户消息
  if (message.type === MessageTypes.USER || message.role === 'user') {
    if (currentIndex === totalCount - 1) {
      return MessagePriority.CRITICAL;
    }
    return MessagePriority.HIGH;
  }
  
  // 工具结果
  if (message.type === MessageTypes.TOOL_RESULT) {
    // 最近的工具结果优先级高
    const distanceFromEnd = totalCount - currentIndex;
    if (distanceFromEnd <= 5) {
      return MessagePriority.HIGH;
    }
    return MessagePriority.MEDIUM;
  }
  
  // 根据位置调整
  const positionRatio = currentIndex / totalCount;
  if (positionRatio > 0.8) {
    priority = Math.min(priority + 20, MessagePriority.CRITICAL);
  } else if (positionRatio < 0.2) {
    priority = Math.max(priority - 20, MessagePriority.MINIMAL);
  }
  
  return priority;
}

/**
 * 按优先级排序消息
 */
function sortMessagesByPriority(messages) {
  const totalCount = messages.length;
  
  return messages
    .map((msg, idx) => ({
      message: msg,
      priority: calculateMessagePriority(msg, {
        currentIndex: idx,
        totalCount,
        messageTypes: messages.map(m => m.type || m.role)
      }),
      originalIndex: idx
    }))
    .sort((a, b) => b.priority - a.priority);
}

// ==================== 压缩执行 ====================

/**
 * 执行消息压缩
 */
async function compactMessages(messages, options = {}) {
  const {
    maxTokens,
    strategy = null,
    customInstructions,
    identifierPolicy = 'strict',
    preserveSystem = true
  } = options;
  
  const currentTokens = estimateMessagesTokens(messages);
  
  // 如果未超过限制，不需要压缩
  if (currentTokens <= maxTokens) {
    return {
      compacted: false,
      messages,
      originalTokens: currentTokens,
      finalTokens: currentTokens
    };
  }
  
  // 选择策略
  const selectedStrategy = strategy || selectCompactionStrategy({
    currentTokens,
    maxTokens,
    messageCount: messages.length
  });
  
  // 计算目标
  const targetTokens = calculateCompactionTarget(currentTokens, maxTokens, selectedStrategy);
  
  let result;
  
  switch (selectedStrategy) {
    case CompactionStrategies.PRUNE:
      result = await _pruneMessages(messages, targetTokens, preserveSystem);
      break;
      
    case CompactionStrategies.SUMMARIZE:
      result = await _summarizeMessages(messages, targetTokens, customInstructions, identifierPolicy);
      break;
      
    case CompactionStrategies.HYBRID:
      result = await _hybridCompact(messages, targetTokens, customInstructions, identifierPolicy, preserveSystem);
      break;
      
    default:
      result = await _truncateMessages(messages, targetTokens, preserveSystem);
  }
  
  return {
    compacted: true,
    strategy: selectedStrategy,
    messages: result.messages,
    originalTokens: currentTokens,
    finalTokens: estimateMessagesTokens(result.messages),
    targetTokens,
    removedCount: messages.length - result.messages.length
  };
}

/**
 * 剪枝策略
 */
async function _pruneMessages(messages, targetTokens, preserveSystem) {
  const withPriority = sortMessagesByPriority(messages);
  
  let currentTokens = 0;
  const kept = [];
  
  for (const item of withPriority) {
    const msgTokens = estimateMessageTokens(item.message);
    
    // 保留系统消息
    if (preserveSystem && item.message.type === MessageTypes.SYSTEM) {
      kept.push({ ...item, mustKeep: true });
      currentTokens += msgTokens;
      continue;
    }
    
    if (currentTokens + msgTokens <= targetTokens || item.priority >= MessagePriority.HIGH) {
      kept.push(item);
      currentTokens += msgTokens;
    }
  }
  
  // 恢复原始顺序
  kept.sort((a, b) => a.originalIndex - b.originalIndex);
  
  return {
    messages: kept.map(item => item.message)
  };
}

/**
 * 摘要策略
 */
async function _summarizeMessages(messages, targetTokens, customInstructions, identifierPolicy) {
  // 分段
  const parts = splitMessagesByTokenShare(messages, DEFAULT_PARTS);
  
  // 生成摘要请求
  const summaryRequests = await Promise.all(
    parts.map(part => generateMessagesSummary(part, {
      customInstructions,
      identifierPolicy,
      maxOutputTokens: Math.floor(targetTokens / parts.length)
    }))
  );
  
  // 返回摘要结构（需要LLM执行）
  return {
    messages,
    summaryRequests,
    needsLlmExecution: true
  };
}

/**
 * 混合策略
 */
async function _hybridCompact(messages, targetTokens, customInstructions, identifierPolicy, preserveSystem) {
  // 1. 保留最近的25%消息
  const recentCount = Math.ceil(messages.length * 0.25);
  const recentMessages = messages.slice(-recentCount);
  const oldMessages = messages.slice(0, -recentCount);
  
  // 2. 对旧消息进行摘要
  const summaryRequest = await generateMessagesSummary(oldMessages, {
    customInstructions,
    identifierPolicy,
    maxOutputTokens: targetTokens * 0.5
  });
  
  // 3. 对最近消息进行剪枝
  const prunedRecent = await _pruneMessages(recentMessages, targetTokens * 0.5, preserveSystem);
  
  return {
    messages: [
      { type: MessageTypes.SYSTEM, content: '[Previous context summary]', summaryRequest },
      ...prunedRecent.messages
    ],
    summaryRequest,
    needsLlmExecution: true
  };
}

/**
 * 截断策略
 */
async function _truncateMessages(messages, targetTokens, preserveSystem) {
  const result = [];
  let currentTokens = 0;
  
  // 反向遍历，保留最新的消息
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    const msgTokens = estimateMessageTokens(msg);
    
    // 系统消息总是保留
    if (preserveSystem && msg.type === MessageTypes.SYSTEM) {
      result.unshift(msg);
      currentTokens += msgTokens;
      continue;
    }
    
    if (currentTokens + msgTokens <= targetTokens) {
      result.unshift(msg);
      currentTokens += msgTokens;
    }
  }
  
  return { messages: result };
}

// ==================== 导出 ====================

module.exports = {
  // 常量
  BASE_CHUNK_RATIO,
  MIN_CHUNK_RATIO,
  SAFETY_MARGIN,
  DEFAULT_PARTS,
  DEFAULT_SUMMARY_FALLBACK,
  
  // 类型
  MessageTypes,
  CompactionStrategies,
  MessagePriority,
  
  // Token估算
  estimateMessageTokens,
  estimateMessagesTokens,
  estimateSafeTokens,
  
  // 消息处理
  stripToolResultDetails,
  normalizeParts,
  splitMessagesByTokenShare,
  
  // 压缩策略
  selectCompactionStrategy,
  calculateCompactionTarget,
  compactMessages,
  
  // 摘要
  buildCompactionSummarizationInstructions,
  generateMessagesSummary,
  mergePartialSummaries,
  
  // 优先级
  calculateMessagePriority,
  sortMessagesByPriority
};

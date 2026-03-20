/**
 * Reasoning Tags Processing - Enhanced
 * Strips AI reasoning tags from text (e.g., <thinking>, <final>)
 * 防止内部思考过程泄漏到最终输出中
 */

const codeRegions = require('./code-regions');

function stripRelevantMemoriesTags(text) {
  // This is a simplified version for now
  return text;
}

// 增强的正则表达式 - 更严格的匹配
const QUICK_TAG_RE = /<\s*\/?\s*(?:think(?:ing)?|thought|antthinking|final|reasoning)\b/i;
const FINAL_TAG_RE = /<\s*\/?\s*final\b[^<>]*>/gi;
const THINKING_TAG_RE = /<\s*(\/?)\s*(?:think(?:ing)?|thought|antthinking|reasoning)\b[^<>]*>/gi;
const REASONING_FIELD_RE = /\b["']?(?:thinking|reasoning|thoughts?)["']?\s*:\s*\{[^}]*\}/gi;

// OpenClaw风格的内容清理 - 防止推理字段泄漏
function stripReasoningFields(text) {
  if (!text) {
    return text;
  }
  
  // 移除JSON结构中的reasoning字段
  let cleaned = text.replace(REASONING_FIELD_RE, (match) => {
    // 如果在代码块中，不处理
    if (isInCodeBlock(match, text.indexOf(match), text)) {
      return match;
    }
    return '';
  });
  
  return cleaned;
}

function isInCodeBlock(match, position, text) {
  // 简单检查：看看匹配是否在代码块中
  const before = text.substring(0, position);
  const codeBlockStarts = (before.match(/```/g) || []).length;
  return codeBlockStarts % 2 === 1; // 奇数个```表示在代码块中
}

function applyTrim(value, mode) {
  if (mode === 'none') {
    return value;
  }
  if (mode === 'start') {
    return value.trimStart();
  }
  return value.trim();
}

function stripReasoningTagsFromText(text, options = {}) {
  if (!text) {
    return text;
  }
  
  if (!QUICK_TAG_RE.test(text)) {
    return text;
  }

  const mode = options.mode ?? 'strict';
  const trimMode = options.trim ?? 'both';
  const verbose = options.verbose ?? false;

  let cleaned = text;
  let removedContent = [];
  
  // 先处理final标签
  if (FINAL_TAG_RE.test(cleaned)) {
    FINAL_TAG_RE.lastIndex = 0;
    const finalMatches = [];
    const preCodeRegions = codeRegions.findCodeRegions(cleaned);
    
    for (const match of cleaned.matchAll(FINAL_TAG_RE)) {
      const start = match.index ?? 0;
      const inCode = codeRegions.isInsideCode(start, preCodeRegions);
      finalMatches.push({
        start,
        length: match[0].length,
        inCode,
        content: match[0]
      });
    }

    for (let i = finalMatches.length - 1; i >= 0; i--) {
      const m = finalMatches[i];
      if (!m.inCode) {
        if (verbose) {
          removedContent.push(`[FINAL] ${m.content}`);
        }
        cleaned = cleaned.slice(0, m.start) + cleaned.slice(m.start + m.length);
      }
    }
  } else {
    FINAL_TAG_RE.lastIndex = 0;
  }

  // 处理thinking标签
  const codeRegionsList = codeRegions.findCodeRegions(cleaned);

  THINKING_TAG_RE.lastIndex = 0;
  let result = '';
  let lastIndex = 0;
  let inThinking = false;
  let thinkingContent = '';

  for (const match of cleaned.matchAll(THINKING_TAG_RE)) {
    const idx = match.index ?? 0;
    const isClose = match[1] === '/';

    if (codeRegions.isInsideCode(idx, codeRegionsList)) {
      continue;
    }

    if (!inThinking) {
      result += cleaned.slice(lastIndex, idx);
      if (!isClose) {
        inThinking = true;
        thinkingContent = '';
      }
    } else if (isClose) {
      inThinking = false;
      if (verbose && thinkingContent) {
        removedContent.push(`[THINKING] ${thinkingContent.substring(0, 100)}...`);
      }
    } else {
      thinkingContent += cleaned.slice(lastIndex, idx);
    }

    lastIndex = idx + match[0].length;
  }

  if (!inThinking || mode === 'preserve') {
    result += cleaned.slice(lastIndex);
  }

  const finalResult = applyTrim(result, trimMode);
  
  // 应用OpenClaw风格的reasoning字段清理
  const cleanResult = stripReasoningFields(finalResult);
  
  if (verbose && removedContent.length > 0) {
    console.error(`[ReasoningTags] 移除了 ${removedContent.length} 个推理标签片段`);
  }
  
  return cleanResult;
}

// 导出增强版本
module.exports = {
  stripReasoningTagsFromText,
  stripRelevantMemoriesTags,
  stripReasoningFields,  // 新增：专门处理reasoning字段
  isInCodeBlock,         // 新增：代码块检测辅助函数
  QUICK_TAG_RE,          // 导出正则表达式供外部使用
  FINAL_TAG_RE,
  THINKING_TAG_RE,
  REASONING_FIELD_RE
};
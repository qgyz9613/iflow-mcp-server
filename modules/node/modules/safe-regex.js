/**
 * iFlow Safe Regex Module
 * 安全正则模块（基于OpenClaw safe-regex设计）
 * 
 * 功能:
 * - 防止ReDoS攻击
 * - 嵌套重复检测
 * - 正则复杂度分析
 */

// ==================== 常量 ====================

const SAFE_REGEX_CACHE_MAX = 256;
const SAFE_REGEX_TEST_WINDOW = 2048;

// ==================== 类型 ====================

const SafeRegexRejectReason = {
  EMPTY: 'empty',
  UNSAFE_NESTED_REPETITION: 'unsafe-nested-repetition',
  INVALID_REGEX: 'invalid-regex'
};

// ==================== 缓存 ====================

const safeRegexCache = new Map();

// ==================== 解析器 ====================

/**
 * 量词读取结果
 */
class QuantifierRead {
  constructor(consumed, minRepeat, maxRepeat) {
    this.consumed = consumed;
    this.minRepeat = minRepeat;
    this.maxRepeat = maxRepeat;
  }
}

/**
 * Token状态
 */
class TokenState {
  constructor() {
    this.containsRepetition = false;
    this.hasAmbiguousAlternation = false;
    this.minLength = 0;
    this.maxLength = 0;
  }
}

/**
 * 解析帧
 */
class ParseFrame {
  constructor() {
    this.lastToken = null;
    this.containsRepetition = false;
    this.hasAlternation = false;
    this.branchMinLength = 0;
    this.branchMaxLength = 0;
    this.altMinLength = null;
    this.altMaxLength = null;
  }
}

// ==================== 辅助函数 ====================

function createParseFrame() {
  return new ParseFrame();
}

function addLength(left, right) {
  if (!Number.isFinite(left) || !Number.isFinite(right)) {
    return Infinity;
  }
  return left + right;
}

function multiplyLength(length, factor) {
  if (!Number.isFinite(length)) {
    return factor === 0 ? 0 : Infinity;
  }
  return length * factor;
}

function recordAlternative(frame) {
  if (frame.altMinLength === null || frame.altMaxLength === null) {
    frame.altMinLength = frame.branchMinLength;
    frame.altMaxLength = frame.branchMaxLength;
  } else {
    frame.altMinLength = Math.min(frame.altMinLength, frame.branchMinLength);
    frame.altMaxLength = Math.max(frame.altMaxLength, frame.branchMaxLength);
  }
  
  // 重置分支
  frame.branchMinLength = 0;
  frame.branchMaxLength = 0;
  frame.containsRepetition = false;
  frame.lastToken = null;
}

// ==================== Token解析 ====================

/**
 * 解析量词
 */
function parseQuantifier(pattern, pos) {
  if (pos >= pattern.length) return null;
  
  const char = pattern[pos];
  
  // 单字符量词
  if (char === '*') {
    return new QuantifierRead(1, 0, Infinity);
  }
  if (char === '+') {
    return new QuantifierRead(1, 1, Infinity);
  }
  if (char === '?') {
    return new QuantifierRead(1, 0, 1);
  }
  
  // {n,m} 形式
  if (char === '{') {
    const closePos = pattern.indexOf('}', pos);
    if (closePos === -1) return null;
    
    const content = pattern.slice(pos + 1, closePos);
    const consumed = closePos - pos + 1;
    
    // {n}
    if (/^\d+$/.test(content)) {
      const n = parseInt(content, 10);
      return new QuantifierRead(consumed, n, n);
    }
    
    // {n,}
    if (/^\d+,$/.test(content)) {
      const n = parseInt(content, 10);
      return new QuantifierRead(consumed, n, Infinity);
    }
    
    // {n,m}
    const match = content.match(/^(\d+),(\d+)$/);
    if (match) {
      const n = parseInt(match[1], 10);
      const m = parseInt(match[2], 10);
      return new QuantifierRead(consumed, n, m);
    }
  }
  
  return null;
}

/**
 * 检查是否为简单token
 */
function isSimpleToken(char) {
  return !['\\', '(', ')', '[', ']', '{', '}', '|', '*', '+', '?', '^', '$', '.'].includes(char);
}

// ==================== 安全检查 ====================

/**
 * 检查正则是否安全
 */
function isSafeRegex(pattern, flags = '') {
  // 空模式
  if (!pattern || pattern.length === 0) {
    return { safe: false, reason: SafeRegexRejectReason.EMPTY };
  }
  
  // 检查缓存
  const cacheKey = `${pattern}/${flags}`;
  const cached = safeRegexCache.get(cacheKey);
  if (cached) return cached;
  
  // 尝试编译
  let regex;
  try {
    regex = new RegExp(pattern, flags);
  } catch (e) {
    const result = {
      safe: false,
      reason: SafeRegexRejectReason.INVALID_REGEX,
      error: e.message
    };
    cacheResult(cacheKey, result);
    return result;
  }
  
  // 解析模式检查嵌套重复
  const frame = createParseFrame();
  let pos = 0;
  let groupDepth = 0;
  let charClass = false;
  
  while (pos < pattern.length) {
    const char = pattern[pos];
    
    // 字符类
    if (char === '[' && !charClass) {
      charClass = true;
      pos++;
      continue;
    }
    if (char === ']' && charClass) {
      charClass = false;
      pos++;
      continue;
    }
    if (charClass) {
      pos++;
      continue;
    }
    
    // 转义字符
    if (char === '\\') {
      pos += 2;
      frame.lastToken = { containsRepetition: false, minLength: 1, maxLength: 1 };
      continue;
    }
    
    // 分组
    if (char === '(') {
      groupDepth++;
      pos++;
      continue;
    }
    if (char === ')') {
      groupDepth--;
      pos++;
      continue;
    }
    
    // 选择
    if (char === '|') {
      recordAlternative(frame);
      frame.hasAlternation = true;
      pos++;
      continue;
    }
    
    // 量词
    const quant = parseQuantifier(pattern, pos);
    if (quant) {
      // 检查嵌套重复
      if (frame.lastToken?.containsRepetition && quant.maxRepeat > 1) {
        const result = {
          safe: false,
          reason: SafeRegexRejectReason.UNSAFE_NESTED_REPETITION,
          position: pos
        };
        cacheResult(cacheKey, result);
        return result;
      }
      
      // 检查歧义选择
      if (frame.hasAlternation && frame.lastToken && quant.maxRepeat === Infinity) {
        // 可能有问题，但不是绝对的ReDoS
      }
      
      if (frame.lastToken) {
        frame.lastToken.minLength = multiplyLength(frame.lastToken.minLength, quant.minRepeat);
        frame.lastToken.maxLength = multiplyLength(frame.lastToken.maxLength, quant.maxRepeat);
        frame.lastToken.containsRepetition = quant.maxRepeat > 1;
        
        frame.branchMinLength = addLength(
          frame.branchMinLength - (frame.lastToken.minLength / quant.minRepeat),
          frame.lastToken.minLength
        );
        frame.branchMaxLength = addLength(
          frame.branchMaxLength - (frame.lastToken.maxLength / quant.minRepeat),
          frame.lastToken.maxLength
        );
      }
      
      pos += quant.consumed;
      continue;
    }
    
    // 简单字符
    if (isSimpleToken(char) || char === '.' || char === '^' || char === '$') {
      frame.branchMinLength = addLength(frame.branchMinLength, 1);
      frame.branchMaxLength = addLength(frame.branchMaxLength, 1);
      frame.lastToken = { containsRepetition: false, minLength: 1, maxLength: 1 };
      pos++;
      continue;
    }
    
    pos++;
  }
  
  // 处理最后的分支
  if (frame.hasAlternation && frame.altMinLength !== null) {
    recordAlternative(frame);
    frame.branchMinLength = frame.altMinLength;
    frame.branchMaxLength = frame.altMaxLength;
  }
  
  const result = { safe: true, regex, pattern, flags };
  cacheResult(cacheKey, result);
  return result;
}

/**
 * 缓存结果
 */
function cacheResult(key, result) {
  if (safeRegexCache.size >= SAFE_REGEX_CACHE_MAX) {
    // 删除最旧的条目
    const firstKey = safeRegexCache.keys().next().value;
    safeRegexCache.delete(firstKey);
  }
  safeRegexCache.set(key, result);
}

/**
 * 清除缓存
 */
function clearSafeRegexCache() {
  safeRegexCache.clear();
}

// ==================== 安全编译 ====================

/**
 * 安全编译正则
 */
function compileSafeRegex(pattern, flags = '') {
  const result = isSafeRegex(pattern, flags);
  
  if (result.safe) {
    return {
      regex: result.regex,
      source: pattern,
      flags,
      reason: null
    };
  }
  
  return {
    regex: null,
    source: pattern,
    flags,
    reason: result.reason
  };
}

/**
 * 安全执行正则测试
 */
function safeRegexTest(pattern, text, flags = '') {
  const result = compileSafeRegex(pattern, flags);
  
  if (result.regex) {
    // 限制测试文本长度
    const limitedText = text.slice(0, SAFE_REGEX_TEST_WINDOW);
    try {
      return result.regex.test(limitedText);
    } catch {
      return false;
    }
  }
  
  return false;
}

/**
 * 安全执行正则匹配
 */
function safeRegexMatch(pattern, text, flags = '') {
  const result = compileSafeRegex(pattern, flags);
  
  if (result.regex) {
    const limitedText = text.slice(0, SAFE_REGEX_TEST_WINDOW);
    try {
      return limitedText.match(result.regex);
    } catch {
      return null;
    }
  }
  
  return null;
}

// ==================== 导出 ====================

module.exports = {
  // 核心函数
  isSafeRegex,
  compileSafeRegex,
  
  // 安全执行
  safeRegexTest,
  safeRegexMatch,
  
  // 缓存
  clearSafeRegexCache,
  
  // 常量
  SafeRegexRejectReason,
  SAFE_REGEX_CACHE_MAX,
  SAFE_REGEX_TEST_WINDOW
};

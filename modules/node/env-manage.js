/**
 * Env Manage Module
 * 环境变量管理和布尔值解析
 * 整合自 OpenClaw env.ts 和 boolean.ts
 */

// ===== Boolean Parsing =====

const DEFAULT_TRUTHY = ['true', '1', 'yes', 'on'];
const DEFAULT_FALSY = ['false', '0', 'no', 'off'];
const DEFAULT_TRUTHY_SET = new Set(DEFAULT_TRUTHY);
const DEFAULT_FALSY_SET = new Set(DEFAULT_FALSY);

/**
 * 解析布尔值
 * @param {unknown} value - 要解析的值
 * @param {Object} options - 选项
 * @returns {boolean|undefined} 布尔值或 undefined
 */
function parseBooleanValue(value, options = {}) {
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value !== 'string') {
    return undefined;
  }
  const normalized = value.trim().toLowerCase();
  if (!normalized) {
    return undefined;
  }
  const truthy = options.truthy ?? DEFAULT_TRUTHY;
  const falsy = options.falsy ?? DEFAULT_FALSY;
  const truthySet = truthy === DEFAULT_TRUTHY ? DEFAULT_TRUTHY_SET : new Set(truthy);
  const falsySet = falsy === DEFAULT_FALSY ? DEFAULT_FALSY_SET : new Set(falsy);
  if (truthySet.has(normalized)) {
    return true;
  }
  if (falsySet.has(normalized)) {
    return false;
  }
  return undefined;
}

// ===== Env Management =====

const loggedEnv = new Set();

function formatEnvValue(value, redact) {
  if (redact) {
    return '<redacted>';
  }
  const singleLine = value.replace(/\s+/g, ' ').trim();
  if (singleLine.length <= 160) {
    return singleLine;
  }
  return `${singleLine.slice(0, 160)}…`;
}

/**
 * 记录接受的环境变量选项
 * @param {Object} option - 环境变量选项
 */
function logAcceptedEnvOption(option) {
  if (process.env.VITEST || process.env.NODE_ENV === 'test') {
    return;
  }
  if (loggedEnv.has(option.key)) {
    return;
  }
  const rawValue = option.value ?? process.env[option.key];
  if (!rawValue || !rawValue.trim()) {
    return;
  }
  loggedEnv.add(option.key);
  console.log(`env: ${option.key}=${formatEnvValue(rawValue, option.redact)} (${option.description})`);
}

/**
 * 规范化 ZAI 环境变量
 */
function normalizeZaiEnv() {
  if (!process.env.ZAI_API_KEY?.trim() && process.env.Z_AI_API_KEY?.trim()) {
    process.env.ZAI_API_KEY = process.env.Z_AI_API_KEY;
  }
}

/**
 * 检查环境变量是否为真值
 * @param {string} value - 环境变量值
 * @returns {boolean} 是否为真值
 */
function isTruthyEnvValue(value) {
  return parseBooleanValue(value) === true;
}

/**
 * 规范化环境变量
 */
function normalizeEnv() {
  normalizeZaiEnv();
}

module.exports = {
  parseBooleanValue,
  DEFAULT_TRUTHY,
  DEFAULT_FALSY,
  logAcceptedEnvOption,
  normalizeZaiEnv,
  isTruthyEnvValue,
  normalizeEnv
};
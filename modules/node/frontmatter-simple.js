/**
 * Frontmatter Simple Module
 * Frontmatter 解析简化版，支持字符串列表解析和布尔值解析
 * 整合自 OpenClaw frontminderr.ts（简化版）
 */

/**
 * 规范化字符串列表（支持数组和逗号分隔）
 * @param {unknown} input - 输入
 * @returns {Array} 字符串列表
 */
function normalizeStringList(input) {
  if (!input) {
    return [];
  }
  if (Array.isArray(input)) {
    return input.map(value => String(value).trim()).filter(Boolean);
  }
  if (typeof input === 'string') {
    return input
      .split(',')
      .map(value => value.trim())
      .filter(Boolean);
  }
  return [];
}

/**
 * 获取 frontmatter 字符串值
 * @param {Object} frontmatter - frontmatter 对象
 * @param {string} key - 键名
 * @returns {string|undefined} 字符串值
 */
function getFrontmatterString(frontmatter, key) {
  const raw = frontmatter[key];
  return typeof raw === 'string' ? raw : undefined;
}

/**
 * 解析 frontmatter 布尔值
 * @param {string|undefined} value - 值
 * @param {boolean} fallback - 回退值
 * @returns {boolean} 布尔值
 */
function parseFrontmatterBool(value, fallback) {
  // 使用 env-manage 模块的 parseBooleanValue
  const parseBooleanValue = require('./env-manage').parseBooleanValue;
  const parsed = parseBooleanValue(value);
  return parsed === undefined ? fallback : parsed;
}

module.exports = {
  normalizeStringList,
  getFrontmatterString,
  parseFrontmatterBool
};
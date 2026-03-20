/**
 * String Normalization Module
 * 字符串规范化工具，用于 URL、标识符、slug 等规范化
 * 整合自 OpenClaw string-normalization.ts
 */

/**
 * 规范化字符串列表
 * @param {Array} list - 字符串列表
 * @returns {Array} 规范化后的字符串列表
 */
function normalizeStringEntries(list) {
  return (list ?? []).map(entry => String(entry).trim()).filter(Boolean);
}

/**
 * 规范化字符串列表（小写）
 * @param {Array} list - 字符串列表
 * @returns {Array} 规范化后的字符串列表（小写）
 */
function normalizeStringEntriesLower(list) {
  return normalizeStringEntries(list).map(entry => entry.toLowerCase());
}

/**
 * 规范化连字符 slug（用于 URL/标识符）
 * @param {string} raw - 原始字符串
 * @returns {string} 规范化后的 slug
 */
function normalizeHyphenSlug(raw) {
  const trimmed = raw?.trim().toLowerCase() ?? '';
  if (!trimmed) {
    return '';
  }
  const dashed = trimmed.replace(/\s+/g, '-');
  const cleaned = dashed.replace(/[^a-z0-9#@._+-]+/g, '-');
  return cleaned.replace(/-{2,}/g, '-').replace(/^[-.]+|[-.]+$/g, '');
}

/**
 * 规范化 @# 前缀 slug（用于用户/频道标识）
 * @param {string} raw - 原始字符串
 * @returns {string} 规范化后的 slug
 */
function normalizeAtHashSlug(raw) {
  const trimmed = raw?.trim().toLowerCase() ?? '';
  if (!trimmed) {
    return '';
  }
  const withoutPrefix = trimmed.replace(/^[@#]+/, '');
  const dashed = withoutPrefix.replace(/[\s_]+/g, '-');
  const cleaned = dashed.replace(/[^a-z0-9-]+/g, '-');
  return cleaned.replace(/-{2,}/g, '-').replace(/^-+|-+$/g, '');
}

module.exports = {
  normalizeStringEntries,
  normalizeStringEntriesLower,
  normalizeHyphenSlug,
  normalizeAtHashSlug
};
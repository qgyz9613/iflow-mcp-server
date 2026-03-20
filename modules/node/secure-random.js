/**
 * iFlow Secure Random Module
 * 安全随机数生成模块，整合自 OpenClaw 的 secure-random.ts
 * 使用 Node.js crypto 模块提供加密安全的随机数生成
 */

const crypto = require('crypto');

/**
 * 生成加密安全的 UUID v4
 * @returns {string} UUID v4 格式的字符串
 */
function generateSecureUuid() {
  return crypto.randomUUID();
}

/**
 * 生成加密安全的 Token
 * @param {number} bytes - 字节数（默认 16）
 * @returns {string} Base64URL 编码的安全 Token
 */
function generateSecureToken(bytes = 16) {
  return crypto.randomBytes(bytes).toString('base64url');
}

/**
 * 生成加密安全的十六进制字符串
 * @param {number} bytes - 字节数（默认 16）
 * @returns {string} 十六进制编码的安全随机字符串
 */
function generateSecureHex(bytes = 16) {
  return crypto.randomBytes(bytes).toString('hex');
}

/**
 * 生成指定范围内的安全随机数
 * @param {number} min - 最小值（包含）
 * @param {number} max - 最大值（包含）
 * @returns {number} 安全随机数
 */
function generateSecureRandomInt(min, max) {
  const range = max - min + 1;
  const bytesNeeded = Math.ceil(Math.log2(range) / 8);
  const cutoff = Math.floor((256 ** bytesNeeded) / range) * range;
  let value;
  do {
    value = 0;
    for (let i = 0; i < bytesNeeded; i++) {
      value = (value << 8) + crypto.randomBytes(1)[0];
    }
  } while (value >= cutoff);
  return min + (value % range);
}

/**
 * 生成加密安全的随机字符串
 * @param {number} length - 字符串长度
 * @param {string} charset - 字符集（默认字母数字）
 * @returns {string} 安全随机字符串
 */
function generateSecureRandomString(length, charset = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789') {
  const charsetLength = charset.length;
  const randomBytes = crypto.randomBytes(length);
  let result = '';
  for (let i = 0; i < length; i++) {
    result += charset[randomBytes[i] % charsetLength];
  }
  return result;
}

module.exports = {
  generateSecureUuid,
  generateSecureToken,
  generateSecureHex,
  generateSecureRandomInt,
  generateSecureRandomString
};
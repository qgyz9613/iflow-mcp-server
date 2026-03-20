/**
 * Temp Path Module
 * 临时文件路径管理和自动清理
 * 整合自 OpenClaw temp-path.ts
 */

const crypto = require('crypto');
const fs = require('fs/promises');
const path = require('path');
const os = require('os');

function sanitizePrefix(prefix) {
  const normalized = prefix.replace(/[^a-zA-Z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
  return normalized || 'tmp';
}

function sanitizeExtension(extension) {
  if (!extension) {
    return '';
  }
  const normalized = extension.startsWith('.') ? extension : `.${extension}`;
  const suffix = normalized.match(/[a-zA-Z0-9._-]+$/)?.[0] ?? '';
  const token = suffix.replace(/^[._-]+/, '');
  if (!token) {
    return '';
  }
  return `.${token}`;
}

function sanitizeFileName(fileName) {
  const base = path.basename(fileName).replace(/[^a-zA-Z0-9._-]+/g, '-');
  const normalized = base.replace(/^-+|-+$/g, '');
  return normalized || 'download.bin';
}

function resolveTempRoot(tmpDir) {
  return tmpDir ?? os.tmpdir();
}

function isNodeErrorWithCode(err, code) {
  return (
    typeof err === 'object' &&
    err !== null &&
    'code' in err &&
    err.code === code
  );
}

/**
 * 构建随机临时文件路径
 * @param {Object} params - 参数
 * @returns {string} 临时文件路径
 */
function buildRandomTempFilePath(params) {
  const prefix = sanitizePrefix(params.prefix);
  const extension = sanitizeExtension(params.extension);
  const nowCandidate = params.now;
  const now =
    typeof nowCandidate === 'number' && Number.isFinite(nowCandidate)
      ? Math.trunc(nowCandidate)
      : Date.now();
  const uuid = params.uuid?.trim() || crypto.randomUUID();
  return path.join(resolveTempRoot(params.tmpDir), `${prefix}-${now}-${uuid}${extension}`);
}

/**
 * 使用临时下载路径执行函数
 * @param {Object} params - 参数
 * @param {Function} fn - 执行函数
 * @returns {Promise<any>} 函数执行结果
 */
async function withTempDownloadPath(params, fn) {
  const tempRoot = resolveTempRoot(params.tmpDir);
  const prefix = `${sanitizePrefix(params.prefix)}-`;
  const dir = await fs.mkdtemp(path.join(tempRoot, prefix));
  const tmpPath = path.join(dir, sanitizeFileName(params.fileName ?? 'download.bin'));
  
  try {
    return await fn(tmpPath);
  } finally {
    try {
      await fs.rm(dir, { recursive: true, force: true });
    } catch (err) {
      if (!isNodeErrorWithCode(err, 'ENOENT')) {
        console.warn(`temp-path cleanup failed for ${dir}: ${String(err)}`);
      }
    }
  }
}

module.exports = {
  buildRandomTempFilePath,
  withTempDownloadPath,
  sanitizePrefix,
  sanitizeExtension,
  sanitizeFileName,
  resolveTempRoot
};
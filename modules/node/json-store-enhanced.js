/**
 * JSON Store Enhanced Module
 * JSON 文件读写和存储管理
 * 整合自 OpenClaw json-store.ts
 */

const fs = require('fs');
const fsPromises = require('fs/promises');

/**
 * 安全解析 JSON
 * @param {string} raw - JSON 字符串
 * @returns {any|null} 解析结果
 */
function safeParseJson(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * 读取 JSON 文件（带回退值）
 * @param {string} filePath - 文件路径
 * @param {any} fallback - 回退值
 * @returns {Promise<Object>} 读取结果
 */
async function readJsonFileWithFallback(filePath, fallback) {
  try {
    const raw = await fsPromises.readFile(filePath, 'utf-8');
    const parsed = safeParseJson(raw);
    if (parsed == null) {
      return { value: fallback, exists: true };
    }
    return { value: parsed, exists: true };
  } catch (err) {
    const code = err?.code;
    if (code === 'ENOENT') {
      return { value: fallback, exists: false };
    }
    return { value: fallback, exists: false };
  }
}

/**
 * 读取 JSON 文件（同步，带回退值）
 * @param {string} filePath - 文件路径
 * @param {any} fallback - 回退值
 * @returns {Object} 读取结果
 */
function readJsonFileSyncWithFallback(filePath, fallback) {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    const parsed = safeParseJson(raw);
    if (parsed == null) {
      return { value: fallback, exists: true };
    }
    return { value: parsed, exists: true };
  } catch (err) {
    const code = err?.code;
    if (code === 'ENOENT') {
      return { value: fallback, exists: false };
    }
    return { value: fallback, exists: false };
  }
}

/**
 * 原子写入 JSON 文件
 * @param {string} filePath - 文件路径
 * @param {any} value - 要写入的值
 * @returns {Promise<void>}
 */
async function writeJsonFileAtomically(filePath, value) {
  const content = JSON.stringify(value, null, 2) + '\n';
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  
  try {
    await fsPromises.mkdir(require('path').dirname(filePath), { recursive: true });
    await fsPromises.writeFile(tempPath, content, 'utf-8');
    await fsPromises.rename(tempPath, filePath);
  } catch (err) {
    try {
      await fsPromises.rm(tempPath, { force: true });
    } catch {}
    throw err;
  }
}

/**
 * 原子写入 JSON 文件（同步）
 * @param {string} filePath - 文件路径
 * @param {any} value - 要写入的值
 */
function writeJsonFileSyncAtomically(filePath, value) {
  const content = JSON.stringify(value, null, 2) + '\n';
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  
  try {
    fs.mkdirSync(require('path').dirname(filePath), { recursive: true });
    fs.writeFileSync(tempPath, content, 'utf-8');
    fs.renameSync(tempPath, filePath);
  } catch (err) {
    try {
      fs.rmSync(tempPath, { force: true });
    } catch {}
    throw err;
  }
}

module.exports = {
  safeParseJson,
  readJsonFileWithFallback,
  readJsonFileSyncWithFallback,
  writeJsonFileAtomically,
  writeJsonFileSyncAtomically
};
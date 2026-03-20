/**
 * Config Eval Module
 * 配置评估系统，支持真值判断、路径解析、运行时要求评估
 * 整合自 OpenClaw config-eval.ts
 */

const fs = require('fs');
const path = require('path');

// ===== Truthy Evaluation =====

/**
 * 判断值是否为真
 * @param {unknown} value - 要判断的值
 * @returns {boolean} 是否为真
 */
function isTruthy(value) {
  if (value === undefined || value === null) {
    return false;
  }
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'number') {
    return value !== 0;
  }
  if (typeof value === 'string') {
    return value.trim().length > 0;
  }
  return true;
}

// ===== Config Path Resolution =====

/**
 * 解析配置路径
 * @param {unknown} config - 配置对象
 * @param {string} pathStr - 路径字符串（点分隔）
 * @returns {unknown} 解析后的值
 */
function resolveConfigPath(config, pathStr) {
  const parts = pathStr.split('.').filter(Boolean);
  let current = config;
  for (const part of parts) {
    if (typeof current !== 'object' || current === null) {
      return undefined;
    }
    current = current[part];
  }
  return current;
}

/**
 * 判断配置路径是否为真（支持默认值）
 * @param {unknown} config - 配置对象
 * @param {string} pathStr - 路径字符串
 * @param {Object} defaults - 默认值对象
 * @returns {boolean} 是否为真
 */
function isConfigPathTruthyWithDefaults(config, pathStr, defaults) {
  const value = resolveConfigPath(config, pathStr);
  if (value === undefined) {
    const defaultValue = defaults[pathStr];
    return defaultValue !== undefined ? isTruthy(defaultValue) : false;
  }
  return isTruthy(value);
}

// ===== Binary Detection =====

let cachedHasBinaryPath;
let cachedHasBinaryPathExt;
const hasBinaryCache = new Map();

function windowsPathExtensions() {
  const raw = process.env.PATHEXT;
  const list = raw !== undefined 
    ? raw.split(';').map(v => v.trim()) 
    : ['.EXE', '.CMD', '.BAT', '.COM'];
  return ['', ...list.filter(Boolean)];
}

/**
 * 检查二进制文件是否存在
 * @param {string} bin - 二进制文件名
 * @returns {boolean} 是否存在
 */
function hasBinary(bin) {
  const pathEnv = process.env.PATH ?? '';
  const pathExt = process.platform === 'win32' ? (process.env.PATHEXT ?? '') : '';
  
  if (cachedHasBinaryPath !== pathEnv || cachedHasBinaryPathExt !== pathExt) {
    cachedHasBinaryPath = pathEnv;
    cachedHasBinaryPathExt = pathExt;
    hasBinaryCache.clear();
  }
  
  if (hasBinaryCache.has(bin)) {
    return hasBinaryCache.get(bin);
  }

  const parts = pathEnv.split(path.delimiter).filter(Boolean);
  const extensions = process.platform === 'win32' ? windowsPathExtensions() : [''];
  
  for (const part of parts) {
    for (const ext of extensions) {
      const candidate = path.join(part, bin + ext);
      try {
        fs.accessSync(candidate, fs.constants.X_OK);
        hasBinaryCache.set(bin, true);
        return true;
      } catch {
        // keep scanning
      }
    }
  }
  
  hasBinaryCache.set(bin, false);
  return false;
}

// ===== Runtime Requirements Evaluation =====

/**
 * 评估运行时要求
 * @param {Object} params - 参数
 * @returns {boolean} 是否满足要求
 */
function evaluateRuntimeRequires(params) {
  const requires = params.requires;
  if (!requires) {
    return true;
  }

  const requiredBins = requires.bins ?? [];
  if (requiredBins.length > 0) {
    for (const bin of requiredBins) {
      if (params.hasBin(bin)) {
        continue;
      }
      if (params.hasRemoteBin?.(bin)) {
        continue;
      }
      return false;
    }
  }

  const requiredAnyBins = requires.anyBins ?? [];
  if (requiredAnyBins.length > 0) {
    const anyFound = requiredAnyBins.some(bin => params.hasBin(bin));
    if (!anyFound && !params.hasAnyRemoteBin?.(requiredAnyBins)) {
      return false;
    }
  }

  const requiredEnv = requires.env ?? [];
  if (requiredEnv.length > 0) {
    for (const envName of requiredEnv) {
      if (!params.hasEnv(envName)) {
        return false;
      }
    }
  }

  const requiredConfig = requires.config ?? [];
  if (requiredConfig.length > 0) {
    for (const configPath of requiredConfig) {
      if (!params.isConfigPathTruthy(configPath)) {
        return false;
      }
    }
  }

  return true;
}

/**
 * 评估运行时资格
 * @param {Object} params - 参数
 * @returns {boolean} 是否有资格
 */
function evaluateRuntimeEligibility(params) {
  const osList = params.os ?? [];
  const remotePlatforms = params.remotePlatforms ?? [];
  
  if (
    osList.length > 0 &&
    !osList.includes(resolveRuntimePlatform()) &&
    !remotePlatforms.some(platform => osList.includes(platform))
  ) {
    return false;
  }
  
  if (params.always === true) {
    return true;
  }
  
  return evaluateRuntimeRequires({
    requires: params.requires,
    hasBin: params.hasBin,
    hasRemoteBin: params.hasRemoteBin,
    hasAnyRemoteBin: params.hasAnyRemoteBin,
    hasEnv: params.hasEnv,
    isConfigPathTruthy: params.isConfigPathTruthy
  });
}

/**
 * 解析运行时平台
 * @returns {string} 平台名称
 */
function resolveRuntimePlatform() {
  return process.platform;
}

module.exports = {
  isTruthy,
  resolveConfigPath,
  isConfigPathTruthyWithDefaults,
  hasBinary,
  evaluateRuntimeRequires,
  evaluateRuntimeEligibility,
  resolveRuntimePlatform
};
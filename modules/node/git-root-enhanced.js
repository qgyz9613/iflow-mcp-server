/**
 * Git Root Enhanced Module
 * Git 根目录查找和 HEAD 文件路径解析
 * 整合自 OpenClaw git-root.ts
 */

const fs = require('fs');
const path = require('path');

const DEFAULT_GIT_DISCOVERY_MAX_DEPTH = 12;

function walkUpFrom(startDir, opts, resolveAtDir) {
  let current = path.resolve(startDir);
  const maxDepth = opts.maxDepth ?? DEFAULT_GIT_DISCOVERY_MAX_DEPTH;
  
  for (let i = 0; i < maxDepth; i += 1) {
    const resolved = resolveAtDir(current);
    if (resolved !== null && resolved !== undefined) {
      return resolved;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      break;
    }
    current = parent;
  }
  return null;
}

function hasGitMarker(repoRoot) {
  const gitPath = path.join(repoRoot, '.git');
  try {
    const stat = fs.statSync(gitPath);
    return stat.isDirectory() || stat.isFile();
  } catch {
    return false;
  }
}

/**
 * 查找 Git 根目录
 * @param {string} startDir - 起始目录
 * @param {Object} opts - 选项
 * @returns {string|null} Git 根目录
 */
function findGitRoot(startDir, opts = {}) {
  return walkUpFrom(startDir, opts, (repoRoot) => 
    hasGitMarker(repoRoot) ? repoRoot : null
  );
}

function resolveGitDirFromMarker(repoRoot) {
  const gitPath = path.join(repoRoot, '.git');
  try {
    const stat = fs.statSync(gitPath);
    if (stat.isDirectory()) {
      return gitPath;
    }
    if (!stat.isFile()) {
      return null;
    }
    const raw = fs.readFileSync(gitPath, 'utf-8');
    const match = raw.match(/gitdir:\s*(.+)/i);
    if (!match?.[1]) {
      return null;
    }
    return path.resolve(repoRoot, match[1].trim());
  } catch {
    return null;
  }
}

/**
 * 解析 Git HEAD 文件路径
 * @param {string} startDir - 起始目录
 * @param {Object} opts - 选项
 * @returns {string|null} HEAD 文件路径
 */
function resolveGitHeadPath(startDir, opts = {}) {
  return walkUpFrom(startDir, opts, (repoRoot) => {
    const gitDir = resolveGitDirFromMarker(repoRoot);
    return gitDir ? path.join(gitDir, 'HEAD') : null;
  });
}

module.exports = {
  DEFAULT_GIT_DISCOVERY_MAX_DEPTH,
  findGitRoot,
  resolveGitHeadPath,
  resolveGitDirFromMarker,
  hasGitMarker
};
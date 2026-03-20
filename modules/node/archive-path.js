/**
 * Archive Path Module
 * 归档文件路径验证和规范化，防止路径遍历攻击
 * 整合自 OpenClaw archive-path.ts
 */

const path = require("node:path");

// ===== Path Safety Helpers =====
function resolveSafeBaseDir(rootDir) {
  const resolved = path.resolve(rootDir);
  return resolved.endsWith(path.sep) ? resolved : `${resolved}${path.sep}`;
}

function isPathInside(rootPath, candidatePath) {
  const root = path.resolve(rootPath);
  const candidate = path.resolve(candidatePath);
  const relative = path.relative(root, candidate);
  return (
    relative &&
    !relative.startsWith("..") &&
    !path.isAbsolute(relative) &&
    !relative.startsWith(path.sep)
  );
}

// ===== Archive Path Validation =====

/**
 * 检查路径是否为 Windows 驱动器路径
 * @param {string} value - 要检查的路径
 * @returns {boolean} 是否为驱动器路径
 */
function isWindowsDrivePath(value) {
  return /^[a-zA-Z]:[\\/]/.test(value);
}

/**
 * 规范化归档条目路径（将反斜杠转换为正斜杠）
 * @param {string} raw - 原始路径
 * @returns {string} 规范化后的路径
 */
function normalizeArchiveEntryPath(raw) {
  return raw.replaceAll("\\", "/");
}

/**
 * 验证归档条目路径是否安全
 * @param {string} entryPath - 归档条目路径
 * @param {Object} params - 验证参数
 * @param {string} params.escapeLabel - 边界标签
 * @throws {Error} 如果路径不安全
 */
function validateArchiveEntryPath(entryPath, params = {}) {
  if (!entryPath || entryPath === "." || entryPath === "./") {
    return;
  }
  if (isWindowsDrivePath(entryPath)) {
    throw new Error(`archive entry uses a drive path: ${entryPath}`);
  }
  const normalized = path.posix.normalize(normalizeArchiveEntryPath(entryPath));
  const escapeLabel = params?.escapeLabel ?? "destination";
  if (normalized === ".." || normalized.startsWith("../")) {
    throw new Error(`archive entry escapes ${escapeLabel}: ${entryPath}`);
  }
  if (path.posix.isAbsolute(normalized) || normalized.startsWith("//")) {
    throw new Error(`archive entry is absolute: ${entryPath}`);
  }
}

/**
 * 去除归档路径的前导组件（类似 tar --strip-components）
 * @param {string} entryPath - 归档条目路径
 * @param {number} stripComponents - 要去除的组件数量
 * @returns {string|null} 处理后的路径，如果为空则返回 null
 */
function stripArchivePath(entryPath, stripComponents) {
  const raw = normalizeArchiveEntryPath(entryPath);
  if (!raw || raw === "." || raw === "./") {
    return null;
  }

  // 模拟 tar --strip-components 语义（规范化前的原始片段）
  // 这样可以看到 strip 导致的路径遍历，如 "a/../b"
  const parts = raw.split("/").filter((part) => part.length > 0 && part !== ".");
  const strip = Math.max(0, Math.floor(stripComponents));
  const stripped = strip === 0 ? parts.join("/") : parts.slice(strip).join("/");
  const result = path.posix.normalize(stripped);
  if (!result || result === "." || result === "./") {
    return null;
  }
  return result;
}

/**
 * 解析归档输出路径，确保在安全边界内
 * @param {Object} params - 参数
 * @param {string} params.rootDir - 根目录
 * @param {string} params.relPath - 相对路径
 * @param {string} params.originalPath - 原始路径
 * @param {string} params.escapeLabel - 边界标签
 * @returns {string} 解析后的安全输出路径
 * @throws {Error} 如果路径超出边界
 */
function resolveArchiveOutputPath(params) {
  const safeBase = resolveSafeBaseDir(params.rootDir);
  const outPath = path.resolve(params.rootDir, params.relPath);
  const escapeLabel = params?.escapeLabel ?? "destination";
  if (!isPathInside(safeBase, outPath)) {
    throw new Error(`archive entry escapes ${escapeLabel}: ${params.originalPath}`);
  }
  return outPath;
}

// ===== Archive Type Detection =====

/**
 * 解析归档类型
 * @param {string} filePath - 文件路径
 * @returns {string|null} 归档类型（"tar" | "zip" | null）
 */
function resolveArchiveKind(filePath) {
  const lower = filePath.toLowerCase();
  if (lower.endsWith(".zip")) {
    return "zip";
  }
  const TAR_SUFFIXES = [".tgz", ".tar.gz", ".tar"];
  if (TAR_SUFFIXES.some((suffix) => lower.endsWith(suffix))) {
    return "tar";
  }
  return null;
}

// ===== Security Constants =====
const DEFAULT_MAX_ARCHIVE_BYTES_ZIP = 256 * 1024 * 1024; // 256MB
const DEFAULT_MAX_ENTRIES = 50_000;
const DEFAULT_MAX_EXTRACTED_BYTES = 512 * 1024 * 1024; // 512MB
const DEFAULT_MAX_ENTRY_BYTES = 256 * 1024 * 1024; // 256MB

// ===== CommonJS Export =====
module.exports = {
  isWindowsDrivePath,
  normalizeArchiveEntryPath,
  validateArchiveEntryPath,
  stripArchivePath,
  resolveArchiveOutputPath,
  resolveArchiveKind,
  DEFAULT_MAX_ARCHIVE_BYTES_ZIP,
  DEFAULT_MAX_ENTRIES,
  DEFAULT_MAX_EXTRACTED_BYTES,
  DEFAULT_MAX_ENTRY_BYTES,
};
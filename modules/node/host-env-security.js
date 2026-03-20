/**
 * Host Environment Security Module
 * 主机环境变量安全管理，防止危险环境变量注入
 * 整合自 OpenClaw host-env-security.ts
 */

// ===== Security Policy =====
const PORTABLE_ENV_VAR_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;

const HOST_ENV_SECURITY_POLICY = {
  blockedKeys: [
    "NODE_OPTIONS",
    "NODE_PATH",
    "PYTHONHOME",
    "PYTHONPATH",
    "PERL5LIB",
    "PERL5OPT",
    "RUBYLIB",
    "RUBYOPT",
    "BASH_ENV",
    "ENV",
    "GIT_EXTERNAL_DIFF",
    "GIT_EXEC_PATH",
    "SHELL",
    "SHELLOPTS",
    "PS4",
    "GCONV_PATH",
    "IFS",
    "SSLKEYLOGFILE",
  ],
  blockedOverrideKeys: [
    "HOME",
    "ZDOTDIR",
    "GIT_SSH_COMMAND",
    "GIT_SSH",
    "GIT_PROXY_COMMAND",
    "GIT_ASKPASS",
    "SSH_ASKPASS",
    "LESSOPEN",
    "LESSCLOSE",
    "PAGER",
    "MANPAGER",
    "GIT_PAGER",
    "EDITOR",
    "VISUAL",
    "FCEDIT",
    "SUDO_EDITOR",
    "PROMPT_COMMAND",
    "HISTFILE",
    "PERL5DB",
    "PERL5DBCMD",
    "OPENSSL_CONF",
    "OPENSSL_ENGINES",
    "PYTHONSTARTUP",
    "WGETRC",
    "CURL_HOME",
  ],
  blockedOverridePrefixes: ["GIT_CONFIG_", "NPM_CONFIG_"],
  blockedPrefixes: ["DYLD_", "LD_", "BASH_FUNC_"],
};

// ===== Dangerous Environment Variables =====
const HOST_DANGEROUS_ENV_KEY_VALUES = Object.freeze(
  HOST_ENV_SECURITY_POLICY.blockedKeys.map((key) => key.toUpperCase())
);
const HOST_DANGEROUS_ENV_PREFIXES = Object.freeze(
  HOST_ENV_SECURITY_POLICY.blockedPrefixes.map((prefix) => prefix.toUpperCase())
);
const HOST_DANGEROUS_OVERRIDE_ENV_KEY_VALUES = Object.freeze(
  (HOST_ENV_SECURITY_POLICY.blockedOverrideKeys ?? []).map((key) => key.toUpperCase())
);
const HOST_DANGEROUS_OVERRIDE_ENV_PREFIXES = Object.freeze(
  (HOST_ENV_SECURITY_POLICY.blockedOverridePrefixes ?? []).map((prefix) =>
    prefix.toUpperCase()
  )
);
const HOST_SHELL_WRAPPER_ALLOWED_OVERRIDE_ENV_KEY_VALUES = Object.freeze([
  "TERM",
  "LANG",
  "LC_ALL",
  "LC_CTYPE",
  "LC_MESSAGES",
  "COLORTERM",
  "NO_COLOR",
  "FORCE_COLOR",
]);

const HOST_DANGEROUS_ENV_KEYS = new Set(HOST_DANGEROUS_ENV_KEY_VALUES);
const HOST_DANGEROUS_OVERRIDE_ENV_KEYS = new Set(
  HOST_DANGEROUS_OVERRIDE_ENV_KEY_VALUES
);
const HOST_SHELL_WRAPPER_ALLOWED_OVERRIDE_ENV_KEYS = new Set(
  HOST_SHELL_WRAPPER_ALLOWED_OVERRIDE_ENV_KEY_VALUES
);

// ===== Environment Variable Normalization =====

/**
 * 规范化环境变量键名
 * @param {string} rawKey - 原始键名
 * @param {Object} options - 选项
 * @param {boolean} options.portable - 是否要求可移植的键名
 * @returns {string|null} 规范化后的键名，如果不合法则返回 null
 */
function normalizeEnvVarKey(rawKey, options = {}) {
  const key = rawKey?.trim();
  if (!key) {
    return null;
  }
  if (options?.portable && !PORTABLE_ENV_VAR_KEY.test(key)) {
    return null;
  }
  return key;
}

// ===== Danger Detection =====

/**
 * 检查环境变量键名是否危险
 * @param {string} rawKey - 原始键名
 * @returns {boolean} 是否危险
 */
function isDangerousHostEnvVarName(rawKey) {
  const key = normalizeEnvVarKey(rawKey);
  if (!key) {
    return false;
  }
  const upper = key.toUpperCase();
  if (HOST_DANGEROUS_ENV_KEYS.has(upper)) {
    return true;
  }
  return HOST_DANGEROUS_ENV_PREFIXES.some((prefix) => upper.startsWith(prefix));
}

/**
 * 检查环境变量覆盖键名是否危险
 * @param {string} rawKey - 原始键名
 * @returns {boolean} 是否危险
 */
function isDangerousHostEnvOverrideVarName(rawKey) {
  const key = normalizeEnvVarKey(rawKey);
  if (!key) {
    return false;
  }
  const upper = key.toUpperCase();
  if (HOST_DANGEROUS_OVERRIDE_ENV_KEYS.has(upper)) {
    return true;
  }
  return HOST_DANGEROUS_OVERRIDE_ENV_PREFIXES.some((prefix) => upper.startsWith(prefix));
}

// ===== Environment Sanitization =====

/**
 * 清理主机执行环境
 * @param {Object} params - 参数
 * @param {Object} params.baseEnv - 基础环境变量
 * @param {Object} params.overrides - 覆盖的环境变量
 * @param {boolean} params.blockPathOverrides - 是否阻止 PATH 覆盖
 * @returns {Object} 清理后的环境变量
 */
function sanitizeHostExecEnv(params = {}) {
  const baseEnv = params?.baseEnv ?? process.env;
  const overrides = params?.overrides ?? undefined;
  const blockPathOverrides = params?.blockPathOverrides ?? true;

  const merged = {};
  for (const [rawKey, value] of Object.entries(baseEnv)) {
    if (typeof value !== "string") {
      continue;
    }
    const key = normalizeEnvVarKey(rawKey, { portable: true });
    if (!key || isDangerousHostEnvVarName(key)) {
      continue;
    }
    merged[key] = value;
  }

  if (overrides) {
    for (const [rawKey, value] of Object.entries(overrides)) {
      if (typeof value !== "string") {
        continue;
      }
      const key = normalizeEnvVarKey(rawKey, { portable: true });
      if (!key) {
        continue;
      }
      if (isDangerousHostEnvOverrideVarName(key)) {
        continue;
      }
      if (blockPathOverrides && key.toUpperCase() === "PATH") {
        continue;
      }
      merged[key] = value;
    }
  }

  return merged;
}

/**
 * 创建安全的环境变量对象
 * @param {Object} options - 选项
 * @param {Object} options.baseEnv - 基础环境变量
 * @param {Object} options.allowedKeys - 允许的键名集合
 * @returns {Object} 安全的环境变量
 */
function createSafeEnv(options = {}) {
  const baseEnv = options?.baseEnv ?? process.env;
  const allowedKeys = options?.allowedKeys;

  const result = {};
  for (const [rawKey, value] of Object.entries(baseEnv)) {
    if (typeof value !== "string") {
      continue;
    }
    const key = normalizeEnvVarKey(rawKey, { portable: true });
    if (!key) {
      continue;
    }
    if (isDangerousHostEnvVarName(key)) {
      continue;
    }
    if (allowedKeys && !allowedKeys.has(key.toUpperCase())) {
      continue;
    }
    result[key] = value;
  }

  return result;
}

// ===== CommonJS Export =====
module.exports = {
  HOST_DANGEROUS_ENV_KEY_VALUES,
  HOST_DANGEROUS_ENV_PREFIXES,
  HOST_DANGEROUS_OVERRIDE_ENV_KEY_VALUES,
  HOST_DANGEROUS_OVERRIDE_ENV_PREFIXES,
  HOST_SHELL_WRAPPER_ALLOWED_OVERRIDE_ENV_KEY_VALUES,
  HOST_DANGEROUS_ENV_KEYS,
  HOST_DANGEROUS_OVERRIDE_ENV_KEYS,
  HOST_SHELL_WRAPPER_ALLOWED_OVERRIDE_ENV_KEYS,
  normalizeEnvVarKey,
  isDangerousHostEnvVarName,
  isDangerousHostEnvOverrideVarName,
  sanitizeHostExecEnv,
  createSafeEnv,
  SECURITY_POLICY: Object.freeze(HOST_ENV_SECURITY_POLICY),
};
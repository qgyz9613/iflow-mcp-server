/**
 * Process Respawn Module
 * 进程重启管理，支持监督环境检测和 fresh PID 重启
 * 整合自 OpenClaw process-respawn.ts 和 supervisor-markers.ts
 */

const { spawn } = require('child_process');

// ===== Supervisor Markers =====

const SUPERVISOR_HINTS = {
  launchd: ['LAUNCH_JOB_LABEL', 'LAUNCH_JOB_NAME', 'XPC_SERVICE_NAME', 'OPENCLAW_LAUNCHD_LABEL'],
  systemd: ['OPENCLAW_SYSTEMD_UNIT', 'INVOCATION_ID', 'SYSTEMD_EXEC_PID', 'JOURNAL_STREAM'],
  schtasks: ['OPENCLAW_WINDOWS_TASK_NAME']
};

const SUPERVISOR_HINT_ENV_VARS = [
  ...SUPERVISOR_HINTS.launchd,
  ...SUPERVISOR_HINTS.systemd,
  ...SUPERVISOR_HINTS.schtasks,
  'OPENCLAW_SERVICE_MARKER',
  'OPENCLAW_SERVICE_KIND'
];

function hasAnyHint(env, keys) {
  return keys.some((key) => {
    const value = env[key];
    return typeof value === 'string' && value.trim().length > 0;
  });
}

/**
 * 检测监督环境
 * @param {NodeJS.ProcessEnv} env - 环境变量
 * @param {NodeJS.Platform} platform - 平台
 * @returns {string|null} 监督环境类型
 */
function detectRespawnSupervisor(env = process.env, platform = process.platform) {
  if (platform === 'darwin') {
    return hasAnyHint(env, SUPERVISOR_HINTS.launchd) ? 'launchd' : null;
  }
  if (platform === 'linux') {
    return hasAnyHint(env, SUPERVISOR_HINTS.systemd) ? 'systemd' : null;
  }
  if (platform === 'win32') {
    if (hasAnyHint(env, SUPERVISOR_HINTS.schtasks)) {
      return 'schtasks';
    }
    const marker = env.OPENCLAW_SERVICE_MARKER?.trim();
    const serviceKind = env.OPENCLAW_SERVICE_KIND?.trim();
    return marker && serviceKind === 'gateway' ? 'schtasks' : null;
  }
  return null;
}

// ===== Process Respawn =====

function isTruthy(value) {
  if (!value) {
    return false;
  }
  const normalized = value.trim().toLowerCase();
  return normalized === '1' || normalized === 'true' || normalized === 'yes' || normalized === 'on';
}

/**
 * 尝试使用新 PID 重启进程
 * @returns {Object} 重启结果
 */
function restartGatewayProcessWithFreshPid() {
  if (isTruthy(process.env.OPENCLAW_NO_RESPAWN)) {
    return { mode: 'disabled' };
  }
  
  const supervisor = detectRespawnSupervisor(process.env);
  if (supervisor) {
    // 在监督环境中，调用者应该退出，让监督器重启
    return { mode: 'supervised', supervisor };
  }
  
  if (process.platform === 'win32') {
    // 在 Windows 上，分离重启不安全，除非有识别的计划任务标记
    return {
      mode: 'disabled',
      detail: 'win32: detached respawn unsupported without Scheduled Task markers'
    };
  }

  try {
    const args = [...process.execArgv, ...process.argv.slice(1)];
    const child = spawn(process.execPath, args, {
      env: process.env,
      detached: true,
      stdio: 'inherit'
    });
    child.unref();
    return { mode: 'spawned', pid: child.pid ?? undefined };
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    return { mode: 'failed', detail };
  }
}

module.exports = {
  SUPERVISOR_HINTS,
  SUPERVISOR_HINT_ENV_VARS,
  detectRespawnSupervisor,
  restartGatewayProcessWithFreshPid,
  isTruthy
};
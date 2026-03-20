/**
 * iFlow Sandbox Module v2.0
 * 沙箱执行环境（基于OpenClaw sandbox设计）
 * 
 * 新增功能:
 * - 资源隔离
 * - 执行策略
 * - 安全审计
 * - 超时控制
 * - 多语言支持
 */

const { spawn, exec, fork } = require('child_process');
const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');
const os = require('os');

const SANDBOX_DIR = path.join(__dirname, '..', 'sandbox-data');
const LOGS_DIR = path.join(SANDBOX_DIR, 'logs');

[SANDBOX_DIR, LOGS_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// ============================================================
// 执行策略
// ============================================================

const ExecutionPolicy = {
  ALLOW_ALL: 'allow_all',
  RESTRICTED: 'restricted',
  PARANOID: 'paranoid',
  CUSTOM: 'custom'
};

// ============================================================
// 安全级别
// ============================================================

const SecurityLevel = {
  LOW: 'low',
  MEDIUM: 'medium',
  HIGH: 'high',
  MAXIMUM: 'maximum'
};

// ============================================================
// 语言配置
// ============================================================

const LANGUAGE_CONFIG = {
  javascript: {
    extension: 'js',
    command: 'node',
    timeout: 30000,
    dangerLevel: 'medium'
  },
  typescript: {
    extension: 'ts',
    command: 'npx ts-node',
    timeout: 30000,
    dangerLevel: 'medium'
  },
  python: {
    extension: 'py',
    command: 'python',
    timeout: 60000,
    dangerLevel: 'medium'
  },
  bash: {
    extension: 'sh',
    command: 'bash',
    timeout: 30000,
    dangerLevel: 'high'
  },
  powershell: {
    extension: 'ps1',
    command: 'powershell -File',
    timeout: 30000,
    dangerLevel: 'high'
  },
  go: {
    extension: 'go',
    command: 'go run',
    timeout: 60000,
    dangerLevel: 'low'
  },
  rust: {
    extension: 'rs',
    command: 'rustc',
    timeout: 120000,
    dangerLevel: 'low'
  }
};

// ============================================================
// 沙箱配置
// ============================================================

const DEFAULT_SANDBOX_CONFIG = {
  maxMemoryMB: 512,
  maxCpuPercent: 80,
  maxFileSizeMB: 10,
  maxExecutionTimeMs: 60000,
  maxOutputSize: 1024 * 1024, // 1MB
  allowedCommands: [],
  blockedCommands: ['rm -rf /', 'format', 'del /s'],
  allowedPaths: [],
  blockedPaths: ['/etc', '/root', 'C:\\Windows\\System32'],
  env: {},
  securityLevel: SecurityLevel.MEDIUM,
  executionPolicy: ExecutionPolicy.RESTRICTED
};

// ============================================================
// 沙箱管理器
// ============================================================

class SandboxManager {
  constructor(config = {}) {
    this.config = { ...DEFAULT_SANDBOX_CONFIG, ...config };
    this.activeSandboxes = new Map();
    this.executionHistory = [];
    this.auditLog = [];
    
    this.startCleanupInterval();
  }
  
  /**
   * 创建沙箱
   */
  create(options = {}) {
    const sandboxId = uuidv4();
    const sandboxPath = path.join(SANDBOX_DIR, sandboxId);
    
    fs.mkdirSync(sandboxPath, { recursive: true });
    
    const sandbox = {
      id: sandboxId,
      path: sandboxPath,
      createdAt: Date.now(),
      status: 'created',
      executions: 0,
      config: { ...this.config, ...options },
      files: [],
      processes: []
    };
    
    this.activeSandboxes.set(sandboxId, sandbox);
    
    // 审计日志
    this.audit({
      action: 'create',
      sandboxId,
      config: sandbox.config
    });
    
    return sandbox;
  }
  
  /**
   * 执行代码
   */
  async execute(code, options = {}) {
    const start = Date.now();
    const language = options.language || 'javascript';
    const langConfig = LANGUAGE_CONFIG[language];
    
    if (!langConfig) {
      return { status: 'error', message: `Unsupported language: ${language}` };
    }
    
    // 安全检查
    const securityCheck = this.checkSecurity(code, language, options);
    if (!securityCheck.passed) {
      return { status: 'error', message: securityCheck.reason, violations: securityCheck.violations };
    }
    
    // 创建沙箱
    const sandbox = options.sandboxId 
      ? this.activeSandboxes.get(options.sandboxId)
      : this.create(options);
    
    if (!sandbox) {
      return { status: 'error', message: 'Sandbox not found' };
    }
    
    // 保存代码文件
    const fileName = `main.${langConfig.extension}`;
    const filePath = path.join(sandbox.path, fileName);
    fs.writeFileSync(filePath, code, 'utf8');
    sandbox.files.push(filePath);
    
    // 执行
    const timeout = options.timeout || langConfig.timeout;
    const result = await this.runCommand(langConfig.command, [filePath], {
      cwd: sandbox.path,
      timeout,
      env: { ...process.env, ...sandbox.config.env, ...options.env },
      maxOutput: sandbox.config.maxOutputSize
    });
    
    // 记录执行
    sandbox.executions++;
    sandbox.lastExecution = Date.now();
    
    const executionRecord = {
      sandboxId: sandbox.id,
      language,
      code: code.substring(0, 1000), // 限制记录大小
      result,
      duration: Date.now() - start,
      timestamp: Date.now()
    };
    
    this.executionHistory.push(executionRecord);
    this.limitHistory();
    
    // 审计日志
    this.audit({
      action: 'execute',
      sandboxId: sandbox.id,
      language,
      success: result.status === 'ok',
      duration: result.duration
    });
    
    return {
      status: result.status,
      sandboxId: sandbox.id,
      language,
      stdout: result.stdout,
      stderr: result.stderr,
      exitCode: result.exitCode,
      duration: result.duration,
      time: Date.now() - start
    };
  }
  
  /**
   * 执行Shell命令
   */
  async shell(command, options = {}) {
    const start = Date.now();
    
    // 安全检查
    const securityCheck = this.checkCommandSecurity(command, options);
    if (!securityCheck.passed) {
      return { status: 'error', message: securityCheck.reason };
    }
    
    const timeout = options.timeout || this.config.maxExecutionTimeMs;
    const cwd = options.cwd || SANDBOX_DIR;
    
    const result = await this.runCommand(command, [], {
      cwd,
      timeout,
      shell: true,
      env: { ...process.env, ...options.env }
    });
    
    // 审计日志
    this.audit({
      action: 'shell',
      command: command.substring(0, 200),
      cwd,
      success: result.status === 'ok',
      duration: result.duration
    });
    
    return {
      ...result,
      time: Date.now() - start
    };
  }
  
  /**
   * 运行命令
   */
  runCommand(command, args = [], options = {}) {
    return new Promise((resolve) => {
      const start = Date.now();
      const timeout = options.timeout || 30000;
      
      let stdout = '';
      let stderr = '';
      let killed = false;
      
      const proc = spawn(command, args, {
        cwd: options.cwd,
        env: options.env || process.env,
        shell: options.shell || false,
        timeout
      });
      
      // 超时处理
      const timer = setTimeout(() => {
        killed = true;
        proc.kill('SIGKILL');
      }, timeout);
      
      proc.stdout.on('data', (data) => {
        if (stdout.length < (options.maxOutput || 1024 * 1024)) {
          stdout += data.toString();
        }
      });
      
      proc.stderr.on('data', (data) => {
        if (stderr.length < (options.maxOutput || 1024 * 1024)) {
          stderr += data.toString();
        }
      });
      
      proc.on('close', (code) => {
        clearTimeout(timer);
        
        resolve({
          status: killed ? 'timeout' : (code === 0 ? 'ok' : 'error'),
          stdout: stdout.slice(0, options.maxOutput || 1024 * 1024),
          stderr: stderr.slice(0, options.maxOutput || 1024 * 1024),
          exitCode: code,
          killed,
          duration: Date.now() - start
        });
      });
      
      proc.on('error', (err) => {
        clearTimeout(timer);
        resolve({
          status: 'error',
          message: err.message,
          duration: Date.now() - start
        });
      });
    });
  }
  
  /**
   * 安全检查
   */
  checkSecurity(code, language, options) {
    const violations = [];
    const config = this.config;
    
    // 检查危险模式
    const dangerPatterns = [
      /eval\s*\(/gi,
      /Function\s*\(/gi,
      /require\s*\(\s*['"]child_process['"]\s*\)/gi,
      /process\.exit/gi,
      /fs\.unlinkSync/gi,
      /fs\.rmdirSync/gi
    ];
    
    for (const pattern of dangerPatterns) {
      if (pattern.test(code)) {
        violations.push(`Dangerous pattern detected: ${pattern}`);
      }
    }
    
    // 检查阻止的命令
    for (const blocked of config.blockedCommands) {
      if (code.toLowerCase().includes(blocked.toLowerCase())) {
        violations.push(`Blocked command detected: ${blocked}`);
      }
    }
    
    // 检查代码大小
    if (code.length > config.maxFileSizeMB * 1024 * 1024) {
      violations.push(`Code size exceeds limit: ${config.maxFileSizeMB}MB`);
    }
    
    // 根据安全级别调整
    const passed = config.securityLevel === SecurityLevel.LOW 
      ? violations.filter(v => v.includes('Blocked')).length === 0
      : violations.length === 0;
    
    return {
      passed,
      violations,
      reason: violations[0] || null
    };
  }
  
  /**
   * 命令安全检查
   */
  checkCommandSecurity(command, options) {
    const config = this.config;
    const violations = [];
    
    // 检查阻止的命令
    for (const blocked of config.blockedCommands) {
      if (command.toLowerCase().includes(blocked.toLowerCase())) {
        violations.push(`Blocked command: ${blocked}`);
      }
    }
    
    // 检查阻止的路径
    for (const blocked of config.blockedPaths) {
      if (command.includes(blocked)) {
        violations.push(`Blocked path: ${blocked}`);
      }
    }
    
    // 根据执行策略
    if (config.executionPolicy === ExecutionPolicy.PARANOID) {
      // 只允许白名单命令
      if (config.allowedCommands.length > 0) {
        const allowed = config.allowedCommands.some(cmd => command.startsWith(cmd));
        if (!allowed) {
          violations.push('Command not in allowlist');
        }
      }
    }
    
    return {
      passed: violations.length === 0,
      violations,
      reason: violations[0] || null
    };
  }
  
  /**
   * 销毁沙箱
   */
  destroy(sandboxId) {
    const sandbox = this.activeSandboxes.get(sandboxId);
    if (!sandbox) {
      return { status: 'error', message: 'Sandbox not found' };
    }
    
    // 清理文件
    try {
      fs.rmSync(sandbox.path, { recursive: true, force: true });
    } catch (e) {
      // 忽略清理错误
    }
    
    this.activeSandboxes.delete(sandboxId);
    
    // 审计日志
    this.audit({
      action: 'destroy',
      sandboxId
    });
    
    return { status: 'ok', message: 'Sandbox destroyed' };
  }
  
  /**
   * 审计日志
   */
  audit(entry) {
    this.auditLog.push({
      ...entry,
      timestamp: Date.now()
    });
    
    // 限制日志大小
    if (this.auditLog.length > 1000) {
      this.auditLog = this.auditLog.slice(-1000);
    }
  }
  
  /**
   * 启动清理间隔
   */
  startCleanupInterval() {
    setInterval(() => {
      const now = Date.now();
      const maxAge = 60 * 60 * 1000; // 1小时
      
      for (const [id, sandbox] of this.activeSandboxes) {
        if (now - sandbox.createdAt > maxAge && sandbox.executions === 0) {
          this.destroy(id);
        }
      }
    }, 10 * 60 * 1000); // 每10分钟清理
  }
  
  limitHistory() {
    if (this.executionHistory.length > 100) {
      this.executionHistory = this.executionHistory.slice(-100);
    }
  }
  
  getStats() {
    return {
      activeSandboxes: this.activeSandboxes.size,
      totalExecutions: this.executionHistory.length,
      auditLogSize: this.auditLog.length
    };
  }
}

// ============================================================
// 全局实例
// ============================================================

let globalManager = null;

function getManager(config) {
  if (!globalManager) {
    globalManager = new SandboxManager(config);
  }
  return globalManager;
}

// ============================================================
// 兼容旧API
// ============================================================

function execute(code, options = {}) {
  return getManager().execute(code, options);
}

function shell(command, options = {}) {
  return getManager().shell(command, options);
}

// ============================================================
// 导出
// ============================================================

module.exports = {
  // 核心类
  SandboxManager,
  ExecutionPolicy,
  SecurityLevel,
  LANGUAGE_CONFIG,
  
  // 全局实例
  getManager,
  
  // 兼容旧API
  execute,
  shell,
  
  // 新API
  create: (options) => getManager().create(options),
  destroy: (sandboxId) => getManager().destroy(sandboxId),
  getStats: () => getManager().getStats(),
  getAuditLog: () => getManager().auditLog,
  getExecutionHistory: () => getManager().executionHistory,
  checkSecurity: (code, lang, opts) => getManager().checkSecurity(code, lang, opts)
};
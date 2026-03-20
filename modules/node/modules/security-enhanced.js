/**
 * Security Enhanced Module
 * 基于OpenClaw安全最佳实践的安全增强机制
 */

const securityUtils = require('./security-utils');

// ==================== 零宽度字符规范化 ====================

// 检测并规范化零宽度字符
function normalizeZeroWidthCharacters(text) {
  if (!text || typeof text !== 'string') {
    return text;
  }
  
  // 常见零宽度字符列表
  const zeroWidthChars = [
    '\u200B',  // 零宽度空格
    '\u200C',  // 零宽度非连接符
    '\u200D',  // 零宽度连接符
    '\uFEFF',  // 零宽度无断空格
    '\u00AD',  // 软连字符
    '\u034F',  // 组合连字符
  ];
  
  let normalized = text;
  let detected = false;
  
  for (const char of zeroWidthChars) {
    if (normalized.includes(char)) {
      detected = true;
      // 转义为可见形式
      normalized = normalized.replace(new RegExp(escapeRegExp(char), 'g'), `\\u{${char.codePointAt(0).toString(16).padStart(4, '0')}}`);
    }
  }
  
  return { 
    normalized, 
    detected,
    originalLength: text.length,
    normalizedLength: normalized.length
  };
}

function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ==================== PowerShell 命令安全检测 ====================

// 检测PowerShell命令包装表单
function detectPowerShellCommand(command) {
  if (!command || typeof command !== 'string') {
    return { type: 'unknown', safe: true };
  }
  
  const normalized = normalizeZeroWidthCharacters(command).normalized;
  
  // 检测文件包装表单
  const filePatterns = [
    /-File\s+['"]?([^\s'"`]+)/gi,
    /-f\s+['"]?([^\s'"`]+)/gi
  ];
  
  // 检测命令包装表单
  const commandPatterns = [
    /-Command\s+['"]?([^\s'"`]+)/gi,
    /-c\s+['"]?([^\s'"`]+)/gi
  ];
  
  let fileLaunch = false;
  let commandLaunch = false;
  let detectedScripts = [];
  
  // 检查文件包装
  for (const pattern of filePatterns) {
    const matches = [...normalized.matchAll(pattern)];
    if (matches.length > 0) {
      fileLaunch = true;
      detectedScripts.push(...matches.map(m => m[1]));
    }
  }
  
  // 检查命令包装
  for (const pattern of commandPatterns) {
    const matches = [...normalized.matchAll(pattern)];
    if (matches.length > 0) {
      commandLaunch = true;
      detectedScripts.push(...matches.map(m => m[1]));
    }
  }
  
  let type = 'inline';
  let safe = true;
  
  if (fileLaunch) {
    type = 'file-based-launch';
    safe = false; // 文件启动需要额外审查
  } else if (commandLaunch) {
    type = 'command-based-launch';
  }
  
  return {
    type,
    safe,
    fileLaunch,
    commandLaunch,
    detectedScripts: [...new Set(detectedScripts)],
    normalized
  };
}

// ==================== pnpm/npm 执行检测 ====================

// 检测包管理器执行模式
function detectPackageManagerExecution(command) {
  if (!command || typeof command !== 'string') {
    return { type: 'unknown', safe: true };
  }
  
  const normalized = normalizeZeroWidthCharacters(command).normalized;
  const lower = normalized.toLowerCase();
  
  // 检测各种包管理器执行模式
  const patterns = {
    pnpmExec: /pnpm\s+(?:--reporter\s+[\w-]+\s+)?exec\s+/gi,
    npmExec: /npm\s+(?:--?\w+)*\s+exec\s+/gi,
    npx: /npx\s+/gi,
    yarnExec: /yarn\s+(?:--?\w+)*\s+exec\s+/gi,
    pnpmNode: /pnpm\s+node\s+/gi,
    pnpmScript: /pnpm\s+run\s+/gi,
    npmScript: /npm\s+run\s+/gi
  };
  
  const detected = [];
  let type = 'unknown';
  let safe = true;
  
  for (const [patternName, pattern] of Object.entries(patterns)) {
    if (pattern.test(lower)) {
      detected.push(patternName);
      if (['pnpmExec', 'npmExec', 'npx', 'pnpmNode'].includes(patternName)) {
        safe = false; // 这些模式需要额外审查
      }
    }
  }
  
  if (detected.length > 0) {
    type = detected[0];
  }
  
  return {
    type,
    safe,
    detected,
    normalized
  };
}

// ==================== Shell 命令分析 ====================

// 分析shell命令并提取关键信息
function analyzeShellCommand(command) {
  if (!command || typeof command !== 'string') {
    return { analysis: null, safe: true };
  }
  
  const normalized = normalizeZeroWidthCharacters(command).normalized;
  const analysis = {
    command: normalized,
    segments: [],
    flags: [],
    arguments: [],
    pipes: false,
    chains: false,
    subshell: false
  };
  
  // 简单的分段分析
  const parts = normalized.split(/\s+/);
  analysis.segments = parts;
  
  // 检测管道
  analysis.pipes = normalized.includes('|');
  
  // 检测命令链
  analysis.chains = /&&|\|\||;;/.test(normalized);
  
  // 检测子shell
  analysis.subshell = /\$\(.*\)|`.*`/.test(normalized);
  
  // 提取标志
  analysis.flags = parts.filter(p => p.startsWith('-'));
  
  // 提取参数（非标志）
  analysis.arguments = parts.filter(p => !p.startsWith('-') && p !== parts[0]);
  
  let safe = true;
  const riskFactors = [];
  
  // 风险评估
  if (analysis.pipes) riskFactors.push('pipe');
  if (analysis.chains) riskFactors.push('command-chain');
  if (analysis.subshell) riskFactors.push('subshell');
  
  if (riskFactors.length > 0) {
    safe = false;
  }
  
  return {
    analysis,
    safe,
    riskFactors,
    normalized
  };
}

// ==================== 综合安全检查 ====================

// 执行综合安全检查
function performSecurityCheck(command, options = {}) {
  const strictMode = options.strict ?? true;
  const verbose = options.verbose ?? false;
  
  const results = {
    safe: true,
    warnings: [],
    errors: [],
    normalizedCommand: '',
    checks: {}
  };
  
  if (!command || typeof command !== 'string') {
    results.safe = false;
    results.errors.push('无效的命令');
    return results;
  }
  
  // 1. 零宽度字符检测
  const zeroWidthResult = normalizeZeroWidthCharacters(command);
  results.checks.zeroWidth = zeroWidthResult;
  results.normalizedCommand = zeroWidthResult.normalized;
  
  if (zeroWidthResult.detected) {
    if (strictMode) {
      results.safe = false;
      results.errors.push(`检测到零宽度字符: ${zeroWidthResult.originalLength} -> ${zeroWidthResult.normalizedLength}`);
    } else {
      results.warnings.push('已规范化零宽度字符');
    }
  }
  
  // 2. PowerShell命令检测
  if (command.toLowerCase().includes('powershell') || command.includes('pwsh')) {
    const powerShellResult = detectPowerShellCommand(results.normalizedCommand);
    results.checks.powerShell = powerShellResult;
    
    if (!powerShellResult.safe) {
      if (strictMode) {
        results.safe = false;
        results.errors.push(`PowerShell命令需要审查: ${powerShellResult.type}`);
      } else {
        results.warnings.push(`PowerShell命令: ${powerShellResult.type}`);
      }
    }
  }
  
  // 3. 包管理器执行检测
  const packageManagerResult = detectPackageManagerExecution(results.normalizedCommand);
  results.checks.packageManager = packageManagerResult;
  
  if (!packageManagerResult.safe) {
    if (strictMode) {
      results.safe = false;
      results.errors.push(`包管理器执行需要审查: ${packageManagerResult.type}`);
    } else {
      results.warnings.push(`包管理器执行: ${packageManagerResult.type}`);
    }
  }
  
  // 4. Shell命令分析
  const shellAnalysis = analyzeShellCommand(results.normalizedCommand);
  results.checks.shell = shellAnalysis;
  
  if (!shellAnalysis.safe) {
    if (strictMode) {
      results.safe = false;
      results.errors.push(`Shell命令风险因素: ${shellAnalysis.riskFactors.join(', ')}`);
    } else {
      results.warnings.push(`Shell命令风险: ${shellAnalysis.riskFactors.join(', ')}`);
    }
  }
  
  if (verbose) {
    console.error('[SecurityEnhanced] 安全检查结果:', {
      safe: results.safe,
      warnings: results.warnings.length,
      errors: results.errors.length
    });
  }
  
  return results;
}

// ==================== 安全批准模拟 ====================

// 模拟安全批准流程
function requestSecurityApproval(command, options = {}) {
  const checkResult = performSecurityCheck(command, options);
  
  return {
    approved: checkResult.safe || !options.strict,
    checkResult,
    requiresManualReview: !checkResult.safe && options.strict,
    suggestedAction: checkResult.safe ? '可以直接执行' : '需要人工审查',
    timestamp: Date.now()
  };
}

module.exports = {
  // 零宽度字符处理
  normalizeZeroWidthCharacters,
  
  // PowerShell命令检测
  detectPowerShellCommand,
  
  // 包管理器执行检测
  detectPackageManagerExecution,
  
  // Shell命令分析
  analyzeShellCommand,
  
  // 综合安全检查
  performSecurityCheck,
  
  // 安全批准流程
  requestSecurityApproval,
  
  // 导出工具函数
  escapeRegExp
};

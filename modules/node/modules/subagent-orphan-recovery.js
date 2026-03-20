/**
 * Subagent Orphan Recovery Module
 * 子代理孤儿恢复机制（基于OpenClaw设计）
 * 
 * 功能:
 * - 检测孤儿子代理（父进程终止但子代理仍在运行）
 * - 自动清理和恢复
 * - 定期扫描和清理
 */

const fs = require('fs');
const path = require('path');
const { v4: uuidv4 } = require('uuid');

// ==================== 配置 ====================

const ORPHAN_CONFIG = {
  // 孤儿检测间隔（毫秒）
  scanInterval: 60 * 1000,  // 1分钟
  
  // 超时阈值（毫秒）
  orphanTimeout: 5 * 60 * 1000,  // 5分钟无更新视为孤儿
  
  // 最大清理批处理大小
  maxCleanupBatch: 10,
  
  // 是否启用自动清理
  autoCleanup: true
};

// ==================== 状态 ====================

let scanTimer = null;
const orphanRegistry = new Map();

// ==================== 核心函数 ====================

/**
 * 扫描孤儿子代理
 * @param {Map} subagentRuns - 子代理运行注册表
 * @returns {Array} - 孤儿列表
 */
function scanOrphans(subagentRuns) {
  const now = Date.now();
  const orphans = [];
  
  for (const [runId, run] of subagentRuns.entries()) {
    // 跳过已完成和已取消的
    if (['completed', 'cancelled', 'killed'].includes(run.status)) {
      continue;
    }
    
    // 检查是否超时
    const lastUpdate = new Date(run.updatedAt || run.createdAt).getTime();
    const age = now - lastUpdate;
    
    if (age > ORPHAN_CONFIG.orphanTimeout) {
      orphans.push({
        runId,
        planId: run.planId,
        taskId: run.taskId,
        status: run.status,
        age,
        parentRunId: run.parentRunId,
        depth: run.depth || 0
      });
    }
  }
  
  return orphans;
}

/**
 * 检查父进程是否存活
 * @param {string} parentRunId - 父运行ID
 * @param {Map} subagentRuns - 子代理运行注册表
 * @returns {boolean} - 是否存活
 */
function isParentAlive(parentRunId, subagentRuns) {
  if (!parentRunId) return true;  // 没有父进程，认为是顶层
  
  const parent = subagentRuns.get(parentRunId);
  if (!parent) return false;  // 父进程不在注册表中
  
  // 检查父进程状态
  return ['running', 'pending', 'restored'].includes(parent.status);
}

/**
 * 清理孤儿子代理
 * @param {Array} orphans - 孤儿列表
 * @param {Map} subagentRuns - 子代理运行注册表
 * @param {Function} completeRun - 完成运行回调
 * @returns {Object} - 清理结果
 */
function cleanupOrphans(orphans, subagentRuns, completeRun) {
  const results = {
    cleaned: 0,
    failed: 0,
    details: []
  };
  
  // 限制批处理大小
  const toClean = orphans.slice(0, ORPHAN_CONFIG.maxCleanupBatch);
  
  for (const orphan of toClean) {
    try {
      // 标记为已清理
      const run = subagentRuns.get(orphan.runId);
      if (run) {
        run.status = 'killed';
        run.endReason = 'orphan';
        run.endedAt = new Date().toISOString();
        run.orphanAge = orphan.age;
        
        // 调用完成回调
        if (completeRun) {
          completeRun(orphan.runId, 'killed', 'orphan_cleanup');
        }
        
        results.cleaned++;
        results.details.push({
          runId: orphan.runId,
          action: 'killed',
          reason: 'orphan'
        });
      }
    } catch (err) {
      results.failed++;
      results.details.push({
        runId: orphan.runId,
        action: 'failed',
        error: err.message
      });
    }
  }
  
  return results;
}

/**
 * 恢复子代理状态
 * @param {string} runId - 运行ID
 * @param {Map} subagentRuns - 子代理运行注册表
 * @param {Object} context - 恢复上下文
 * @returns {Object} - 恢复结果
 */
function recoverSubagent(runId, subagentRuns, context = {}) {
  const run = subagentRuns.get(runId);
  if (!run) {
    return { status: 'error', message: 'Run not found' };
  }
  
  // 更新状态
  run.status = 'restored';
  run.restoredAt = new Date().toISOString();
  run.restoreContext = context;
  
  // 记录到孤儿注册表
  orphanRegistry.set(runId, {
    recovered: true,
    recoveredAt: new Date().toISOString(),
    previousStatus: run.status
  });
  
  return {
    status: 'ok',
    runId,
    message: 'Subagent recovered successfully',
    run
  };
}

/**
 * 启动孤儿扫描器
 * @param {Map} subagentRuns - 子代理运行注册表
 * @param {Function} completeRun - 完成运行回调
 * @returns {Object} - 启动结果
 */
function startOrphanScanner(subagentRuns, completeRun) {
  if (scanTimer) {
    return { status: 'ok', message: 'Scanner already running' };
  }
  
  scanTimer = setInterval(() => {
    if (!ORPHAN_CONFIG.autoCleanup) return;
    
    const orphans = scanOrphans(subagentRuns);
    
    if (orphans.length > 0) {
      console.log(`[OrphanRecovery] 发现 ${orphans.length} 个孤儿子代理`);
      
      const result = cleanupOrphans(orphans, subagentRuns, completeRun);
      console.log(`[OrphanRecovery] 清理完成: ${result.cleaned} 成功, ${result.failed} 失败`);
    }
  }, ORPHAN_CONFIG.scanInterval);
  
  return {
    status: 'ok',
    message: 'Orphan scanner started',
    interval: ORPHAN_CONFIG.scanInterval
  };
}

/**
 * 停止孤儿扫描器
 */
function stopOrphanScanner() {
  if (scanTimer) {
    clearInterval(scanTimer);
    scanTimer = null;
  }
  return { status: 'ok', message: 'Orphan scanner stopped' };
}

/**
 * 获取孤儿统计
 * @param {Map} subagentRuns - 子代理运行注册表
 * @returns {Object} - 统计信息
 */
function getOrphanStats(subagentRuns) {
  const orphans = scanOrphans(subagentRuns);
  
  return {
    orphanCount: orphans.length,
    recoveredCount: orphanRegistry.size,
    oldestOrphan: orphans.length > 0 
      ? orphans.reduce((a, b) => a.age > b.age ? a : b)
      : null,
    config: ORPHAN_CONFIG
  };
}

/**
 * 配置孤儿检测
 * @param {Object} config - 配置参数
 */
function configureOrphanDetection(config = {}) {
  Object.assign(ORPHAN_CONFIG, config);
  return { status: 'ok', config: ORPHAN_CONFIG };
}

// ==================== 导出 ====================

module.exports = {
  // 配置
  ORPHAN_CONFIG,
  
  // 核心函数
  scanOrphans,
  isParentAlive,
  cleanupOrphans,
  recoverSubagent,
  
  // 扫描器
  startOrphanScanner,
  stopOrphanScanner,
  
  // 统计和配置
  getOrphanStats,
  configureOrphanDetection
};

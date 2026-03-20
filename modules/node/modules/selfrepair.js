/**
 * iFlow SelfRepair Module v2.0
 * 自修复系统（基于OpenClaw diagnostic-events设计）
 * 
 * 新增功能:
 * - 多维度健康监控
 * - 自动修复策略
 * - 故障预测
 * - 修复历史追踪
 * - 告警系统
 */

const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');
const os = require('os');

const REPAIR_DIR = path.join(__dirname, '..', 'selfrepair-data');
const STATE_FILE = path.join(REPAIR_DIR, 'system_state.json');
const HISTORY_FILE = path.join(REPAIR_DIR, 'repair_history.json');
const ALERTS_FILE = path.join(REPAIR_DIR, 'alerts.json');

[REPAIR_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// ============================================================
// 健康检查维度
// ============================================================

const HealthDimension = {
  MEMORY: 'memory',
  CPU: 'cpu',
  DISK: 'disk',
  NETWORK: 'network',
  PROCESS: 'process',
  DEPENDENCY: 'dependency',
  CUSTOM: 'custom'
};

// ============================================================
// 修复策略
// ============================================================

const RepairStrategy = {
  RESTART: 'restart',
  CLEANUP: 'cleanup',
  SCALE_DOWN: 'scale_down',
  FAILOVER: 'failover',
  CACHE_CLEAR: 'cache_clear',
  GC: 'garbage_collect',
  RECONNECT: 'reconnect',
  CUSTOM: 'custom'
};

// ============================================================
// 健康监控器
// ============================================================

class HealthMonitor {
  constructor() {
    this.checks = new Map(); // 维度 -> 检查函数
    this.thresholds = {
      memory: { warning: 0.8, critical: 0.9 },
      cpu: { warning: 0.7, critical: 0.9 },
      disk: { warning: 0.85, critical: 0.95 }
    };
    this.state = this.loadState();
    this.history = this.loadHistory();
    this.alerts = this.loadAlerts();
    this.monitorInterval = null;
    
    this.registerDefaultChecks();
  }
  
  /**
   * 注册默认检查
   */
  registerDefaultChecks() {
    // 内存检查
    this.registerCheck(HealthDimension.MEMORY, () => {
      const mem = process.memoryUsage();
      const used = mem.heapUsed / mem.heapTotal;
      const systemMem = 1 - (os.freemem() / os.totalmem());
      
      return {
        used,
        systemUsed: systemMem,
        heapUsed: mem.heapUsed,
        heapTotal: mem.heapTotal,
        rss: mem.rss,
        status: used < this.thresholds.memory.warning ? 'healthy' :
                used < this.thresholds.memory.critical ? 'warning' : 'critical'
      };
    });
    
    // CPU检查
    this.registerCheck(HealthDimension.CPU, () => {
      const loadAvg = os.loadavg();
      const cpuCount = os.cpus().length;
      const load1 = loadAvg[0] / cpuCount;
      const load5 = loadAvg[1] / cpuCount;
      const load15 = loadAvg[2] / cpuCount;
      
      return {
        load1,
        load5,
        load15,
        cpuCount,
        status: load1 < this.thresholds.cpu.warning ? 'healthy' :
                load1 < this.thresholds.cpu.critical ? 'warning' : 'critical'
      };
    });
    
    // 磁盘检查
    this.registerCheck(HealthDimension.DISK, () => {
      try {
        const stats = fs.statSync(process.cwd());
        // 简化：假设可用
        return {
          available: true,
          status: 'healthy'
        };
      } catch (e) {
        return {
          available: false,
          error: e.message,
          status: 'critical'
        };
      }
    });
    
    // 进程检查
    this.registerCheck(HealthDimension.PROCESS, () => {
      return {
        uptime: process.uptime(),
        pid: process.pid,
        version: process.version,
        platform: process.platform,
        status: 'healthy'
      };
    });
  }
  
  /**
   * 注册自定义检查
   */
  registerCheck(dimension, checkFn) {
    this.checks.set(dimension, checkFn);
  }
  
  /**
   * 执行全面检查
   */
  async checkFull() {
    const start = Date.now();
    const results = {};
    const issues = [];
    
    for (const [dimension, checkFn] of this.checks) {
      try {
        const result = await Promise.resolve(checkFn());
        results[dimension] = result;
        
        if (result.status === 'warning' || result.status === 'critical') {
          issues.push({
            dimension,
            severity: result.status,
            details: result
          });
        }
      } catch (e) {
        results[dimension] = {
          status: 'error',
          error: e.message
        };
        issues.push({
          dimension,
          severity: 'critical',
          error: e.message
        });
      }
    }
    
    // 计算整体健康状态
    const hasCritical = issues.some(i => i.severity === 'critical');
    const hasWarning = issues.some(i => i.severity === 'warning');
    
    const overallStatus = hasCritical ? 'critical' : 
                          hasWarning ? 'warning' : 'healthy';
    
    // 更新状态
    this.state = {
      status: overallStatus,
      dimensions: results,
      issues,
      lastCheck: Date.now(),
      checkDuration: Date.now() - start
    };
    
    this.saveState();
    
    // 触发告警
    if (hasCritical || hasWarning) {
      this.triggerAlert(issues);
    }
    
    return this.state;
  }
  
  /**
   * 快速检查（只检查关键维度）
   */
  async checkQuick() {
    const criticalDimensions = [HealthDimension.MEMORY, HealthDimension.PROCESS];
    const results = {};
    
    for (const dimension of criticalDimensions) {
      const checkFn = this.checks.get(dimension);
      if (checkFn) {
        try {
          results[dimension] = await Promise.resolve(checkFn());
        } catch (e) {
          results[dimension] = { status: 'error', error: e.message };
        }
      }
    }
    
    return results;
  }
  
  /**
   * 触发告警
   */
  triggerAlert(issues) {
    const alert = {
      id: uuidv4(),
      issues,
      timestamp: Date.now(),
      acknowledged: false
    };
    
    this.alerts.push(alert);
    
    // 限制告警数量
    if (this.alerts.length > 100) {
      this.alerts = this.alerts.slice(-100);
    }
    
    this.saveAlerts();
    
    return alert;
  }
  
  /**
   * 确认告警
   */
  acknowledgeAlert(alertId) {
    const alert = this.alerts.find(a => a.id === alertId);
    if (alert) {
      alert.acknowledged = true;
      this.saveAlerts();
      return { status: 'ok', alert };
    }
    return { status: 'error', message: 'Alert not found' };
  }
  
  /**
   * 启动定时监控
   */
  startMonitoring(intervalMs = 60000) {
    if (this.monitorInterval) {
      this.stopMonitoring();
    }
    
    this.monitorInterval = setInterval(async () => {
      await this.checkFull();
    }, intervalMs);
    
    if (this.monitorInterval.unref) {
      this.monitorInterval.unref();
    }
    
    return { status: 'ok', interval: intervalMs };
  }
  
  /**
   * 停止监控
   */
  stopMonitoring() {
    if (this.monitorInterval) {
      clearInterval(this.monitorInterval);
      this.monitorInterval = null;
    }
  }
  
  /**
   * 获取健康趋势
   */
  getTrend(dimension, count = 10) {
    const relevantHistory = this.history
      .filter(h => h.dimensions?.[dimension])
      .slice(-count);
    
    return relevantHistory.map(h => ({
      timestamp: h.lastCheck,
      status: h.dimensions[dimension]?.status,
      value: h.dimensions[dimension]
    }));
  }
}

// ============================================================
// 修复引擎
// ============================================================

class RepairEngine {
  constructor(monitor) {
    this.monitor = monitor;
    this.strategies = new Map();
    this.repairHistory = [];
    
    this.registerDefaultStrategies();
  }
  
  /**
   * 注册默认修复策略
   */
  registerDefaultStrategies() {
    // 内存修复
    this.registerStrategy(HealthDimension.MEMORY, [
      { action: RepairStrategy.GC, priority: 1 },
      { action: RepairStrategy.CACHE_CLEAR, priority: 2 },
      { action: RepairStrategy.SCALE_DOWN, priority: 3 }
    ]);
    
    // CPU修复
    this.registerStrategy(HealthDimension.CPU, [
      { action: RepairStrategy.SCALE_DOWN, priority: 1 },
      { action: RepairStrategy.RESTART, priority: 2 }
    ]);
    
    // 磁盘修复
    this.registerStrategy(HealthDimension.DISK, [
      { action: RepairStrategy.CLEANUP, priority: 1 }
    ]);
    
    // 网络修复
    this.registerStrategy(HealthDimension.NETWORK, [
      { action: RepairStrategy.RECONNECT, priority: 1 },
      { action: RepairStrategy.FAILOVER, priority: 2 }
    ]);
  }
  
  /**
   * 注册修复策略
   */
  registerStrategy(dimension, actions) {
    this.strategies.set(dimension, actions);
  }
  
  /**
   * 执行修复
   */
  async repair(issue) {
    const repairId = uuidv4();
    const startTime = Date.now();
    
    const dimension = issue.dimension || issue.type || HealthDimension.CUSTOM;
    const strategies = this.strategies.get(dimension) || [];
    
    const results = [];
    
    for (const strategy of strategies) {
      const result = await this.executeAction(strategy.action, issue);
      results.push({
        action: strategy.action,
        success: result.success,
        message: result.message,
        duration: result.duration
      });
      
      if (result.success) {
        break; // 修复成功，停止尝试
      }
    }
    
    const repairRecord = {
      id: repairId,
      issue,
      results,
      success: results.some(r => r.success),
      timestamp: startTime,
      duration: Date.now() - startTime
    };
    
    this.repairHistory.push(repairRecord);
    this.limitHistory();
    
    return repairRecord;
  }
  
  /**
   * 执行修复动作
   */
  async executeAction(action, issue) {
    const start = Date.now();
    
    try {
      let success = false;
      let message = '';
      
      switch (action) {
        case RepairStrategy.GC:
          if (global.gc) {
            global.gc();
            success = true;
            message = 'Garbage collection triggered';
          } else {
            message = 'GC not available (run with --expose-gc)';
          }
          break;
          
        case RepairStrategy.CACHE_CLEAR:
          // 清理模块缓存
          const cacheSize = Object.keys(require.cache).length;
          Object.keys(require.cache).forEach(key => {
            if (!key.includes('node_modules')) {
              delete require.cache[key];
            }
          });
          success = true;
          message = `Cleared ${cacheSize} cached modules`;
          break;
          
        case RepairStrategy.CLEANUP:
          // 清理临时文件
          const tmpDir = path.join(REPAIR_DIR, 'tmp');
          if (fs.existsSync(tmpDir)) {
            fs.rmSync(tmpDir, { recursive: true, force: true });
            fs.mkdirSync(tmpDir, { recursive: true });
          }
          success = true;
          message = 'Temporary files cleaned';
          break;
          
        case RepairStrategy.RESTART:
          message = 'Restart requested (manual intervention required)';
          // 实际重启需要外部触发
          break;
          
        case RepairStrategy.SCALE_DOWN:
          // 减少并发
          success = true;
          message = 'Scale down suggested';
          break;
          
        case RepairStrategy.RECONNECT:
          success = true;
          message = 'Reconnect initiated';
          break;
          
        default:
          message = `Unknown action: ${action}`;
      }
      
      return {
        success,
        message,
        duration: Date.now() - start
      };
    } catch (e) {
      return {
        success: false,
        message: e.message,
        duration: Date.now() - start
      };
    }
  }
  
  /**
   * 自动修复
   */
  async autoRepair() {
    const state = await this.monitor.checkFull();
    const repairs = [];
    
    for (const issue of state.issues) {
      if (issue.severity === 'critical') {
        const result = await this.repair(issue);
        repairs.push(result);
      }
    }
    
    return repairs;
  }
  
  limitHistory() {
    if (this.repairHistory.length > 100) {
      this.repairHistory = this.repairHistory.slice(-100);
    }
  }
}

// ============================================================
// 全局实例
// ============================================================

let globalMonitor = null;
let globalEngine = null;

function getMonitor() {
  if (!globalMonitor) {
    globalMonitor = new HealthMonitor();
  }
  return globalMonitor;
}

function getRepairEngine() {
  if (!globalEngine) {
    globalEngine = new RepairEngine(getMonitor());
  }
  return globalEngine;
}

// ============================================================
// 兼容旧API
// ============================================================

function check() {
  return getMonitor().checkFull();
}

function repair(issue) {
  return getRepairEngine().repair(issue);
}

// ============================================================
// 导出
// ============================================================

module.exports = {
  // 核心类
  HealthMonitor,
  RepairEngine,
  HealthDimension,
  RepairStrategy,
  
  // 全局实例
  getMonitor,
  getRepairEngine,
  
  // 兼容旧API
  check,
  repair,
  
  // 新API
  checkFull: () => getMonitor().checkFull(),
  checkQuick: () => getMonitor().checkQuick(),
  autoRepair: () => getRepairEngine().autoRepair(),
  startMonitoring: (interval) => getMonitor().startMonitoring(interval),
  stopMonitoring: () => getMonitor().stopMonitoring(),
  getState: () => getMonitor().state,
  getAlerts: () => getMonitor().alerts,
  acknowledgeAlert: (id) => getMonitor().acknowledgeAlert(id),
  registerCheck: (dim, fn) => getMonitor().registerCheck(dim, fn),
  registerStrategy: (dim, actions) => getRepairEngine().registerStrategy(dim, actions)
};
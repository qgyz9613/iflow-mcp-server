/**
 * Heartbeat Scheduler Module
 * Heartbeat智能调度（基于OpenClaw设计）
 * 支持资源控制、效率提升、智能调度、并发管理
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs').promises;
const os = require('os');

// ==================== 常量定义 ====================

const SCHEDULER_DIR = path.join(__dirname, '..', 'heartbeat-scheduler-data');
const JOBS_DIR = path.join(SCHEDULER_DIR, 'jobs');
const SCHEDULES_DIR = path.join(SCHEDULER_DIR, 'schedules');

// 确保目录存在
async function ensureDirectories() {
  const dirs = [SCHEDULER_DIR, JOBS_DIR, SCHEDULES_DIR];
  for (const dir of dirs) {
    try {
      await fs.mkdir(dir, { recursive: true });
    } catch (err) {
      console.warn(`[HeartbeatScheduler] Failed to create directory ${dir}: ${err.message}`);
    }
  }
}

// ==================== 任务类型 ====================

/**
 * 任务类型
 */
const JobType = {
  SKILL: 'skill',
  SUBAGENT: 'subagent',
  SYSTEM: 'system',
  CUSTOM: 'custom'
};

/**
 * 任务状态
 */
const JobStatus = {
  PENDING: 'pending',
  SCHEDULED: 'scheduled',
  RUNNING: 'running',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
  TIMEOUT: 'timeout'
};

/**
 * 任务优先级
 */
const JobPriority = {
  CRITICAL: 0,
  HIGH: 1,
  NORMAL: 2,
  LOW: 3
};

// ==================== 资源管理 ====================

/**
 * 资源池
 */
class ResourcePool {
  constructor(config = {}) {
    this.maxCpuUsage = config.maxCpuUsage || 80;  // 80%
    this.maxMemoryUsage = config.maxMemoryUsage || 80;  // 80%
    this.maxConcurrentJobs = config.maxConcurrentJobs || 10;
    this.maxIoOperations = config.maxIoOperations || 5;
    
    this.currentUsage = {
      cpu: 0,
      memory: 0,
      jobs: 0,
      io: 0
    };
    
    this.resourceHistory = [];
    this.historyMaxLength = 100;
  }
  
  /**
   * 检查是否有可用资源
   */
  hasAvailableResources(jobRequirements = {}) {
    const currentCpu = this.getCurrentCpuUsage();
    const currentMemory = this.getCurrentMemoryUsage();
    
    const cpuAvailable = currentCpu < this.maxCpuUsage;
    const memoryAvailable = currentMemory < this.maxMemoryUsage;
    const jobsAvailable = this.currentUsage.jobs < this.maxConcurrentJobs;
    const ioAvailable = this.currentUsage.io < this.maxIoOperations;
    
    return {
      available: cpuAvailable && memoryAvailable && jobsAvailable && ioAvailable,
      cpuAvailable,
      memoryAvailable,
      jobsAvailable,
      ioAvailable,
      currentCpu,
      currentMemory,
      currentJobs: this.currentUsage.jobs,
      currentIo: this.currentUsage.io
    };
  }
  
  /**
   * 获取当前CPU使用率
   */
  getCurrentCpuUsage() {
    const cpus = os.cpus();
    let totalIdle = 0;
    let totalTick = 0;
    
    for (const cpu of cpus) {
      for (const type in cpu.times) {
        totalTick += cpu.times[type];
      }
      totalIdle += cpu.times.idle;
    }
    
    const idle = totalIdle / cpus.length;
    const total = totalTick / cpus.length;
    const usage = 100 - ~~(100 * idle / total);
    
    this.currentUsage.cpu = usage;
    return usage;
  }
  
  /**
   * 获取当前内存使用率
   */
  getCurrentMemoryUsage() {
    const totalMemory = os.totalmem();
    const freeMemory = os.freemem();
    const usedMemory = totalMemory - freeMemory;
    const usage = (usedMemory / totalMemory) * 100;
    
    this.currentUsage.memory = usage;
    return usage;
  }
  
  /**
   * 预留资源
   */
  reserveResources(jobRequirements = {}) {
    this.currentUsage.jobs++;
    this._recordHistory();
  }
  
  /**
   * 释放资源
   */
  releaseResources() {
    if (this.currentUsage.jobs > 0) {
      this.currentUsage.jobs--;
    }
    this._recordHistory();
  }
  
  /**
   * 记录资源历史
   */
  _recordHistory() {
    const snapshot = {
      timestamp: Date.now(),
      cpu: this.currentUsage.cpu,
      memory: this.currentUsage.memory,
      jobs: this.currentUsage.jobs,
      io: this.currentUsage.io
    };
    
    this.resourceHistory.push(snapshot);
    
    if (this.resourceHistory.length > this.historyMaxLength) {
      this.resourceHistory.shift();
    }
  }
  
  /**
   * 获取资源统计
   */
  getResourceStats() {
    return {
      maxCpuUsage: this.maxCpuUsage,
      maxMemoryUsage: this.maxMemoryUsage,
      maxConcurrentJobs: this.maxConcurrentJobs,
      maxIoOperations: this.maxIoOperations,
      currentUsage: this.currentUsage,
      history: this.resourceHistory.slice(-10)  // 最近10条
    };
  }
  
  /**
   * 获取资源预测
   */
  predictResourceAvailability(windowMs = 60000) {  // 默认1分钟
    if (this.resourceHistory.length < 2) {
      return { trend: 'stable', prediction: this.currentUsage };
    }
    
    const now = Date.now();
    const recentHistory = this.resourceHistory.filter(
      h => now - h.timestamp < windowMs
    );
    
    if (recentHistory.length < 2) {
      return { trend: 'stable', prediction: this.currentUsage };
    }
    
    // 计算趋势
    const first = recentHistory[0];
    const last = recentHistory[recentHistory.length - 1];
    
    const cpuTrend = last.cpu - first.cpu;
    const memoryTrend = last.memory - first.memory;
    
    const trend = Math.abs(cpuTrend) > 10 || Math.abs(memoryTrend) > 10 
      ? (cpuTrend > 0 || memoryTrend > 0 ? 'increasing' : 'decreasing')
      : 'stable';
    
    // 预测未来状态
    const prediction = {
      cpu: Math.max(0, Math.min(100, last.cpu + cpuTrend * 0.5)),
      memory: Math.max(0, Math.min(100, last.memory + memoryTrend * 0.5)),
      jobs: last.jobs
    };
    
    return {
      trend,
      prediction,
      confidence: Math.min(recentHistory.length / 10, 1)  // 历史数据越多，置信度越高
    };
  }
}

// ==================== 调度策略 ====================

/**
 * 调度策略
 */
const SchedulingStrategy = {
  PRIORITY_FIRST: 'priority_first',      // 优先级优先
  ROUND_ROBIN: 'round_robin',            // 轮询
  FAIR_SHARE: 'fair_share',              // 公平共享
  RESOURCE_AWARE: 'resource_aware',      // 资源感知
  ADAPTIVE: 'adaptive'                   // 自适应
};

/**
 * 调度器
 */
class JobScheduler {
  constructor(config = {}) {
    this.id = config.id || uuidv4();
    this.strategy = config.strategy || SchedulingStrategy.RESOURCE_AWARE;
    this.resourcePool = new ResourcePool(config.resources || {});
    this.jobs = new Map();
    this.schedules = new Map();
    this.runningJobs = new Map();
    
    this.stats = {
      totalJobs: 0,
      completedJobs: 0,
      failedJobs: 0,
      cancelledJobs: 0,
      averageExecutionTime: 0,
      lastExecutionTime: null
    };
    
    this.enabled = config.enabled !== false;
    this.tickInterval = config.tickInterval || 1000;  // 1秒
    this.tickTimer = null;
  }
  
  /**
   * 启动调度器
   */
  async start() {
    if (this.tickTimer) {
      return;
    }
    
    await ensureDirectories();
    await this._loadSchedules();
    
    this.tickTimer = setInterval(() => {
      this._tick();
    }, this.tickInterval);
    
    console.log(`[HeartbeatScheduler] Scheduler ${this.id} started`);
  }
  
  /**
   * 停止调度器
   */
  stop() {
    if (this.tickTimer) {
      clearInterval(this.tickTimer);
      this.tickTimer = null;
      console.log(`[HeartbeatScheduler] Scheduler ${this.id} stopped`);
    }
  }
  
  /**
   * 添加任务
   */
  async addJob(job) {
    const jobId = job.id || uuidv4();
    
    const jobObj = {
      id: jobId,
      type: job.type || JobType.CUSTOM,
      name: job.name || `Job-${jobId}`,
      handler: job.handler,
      priority: job.priority !== undefined ? job.priority : JobPriority.NORMAL,
      status: JobStatus.PENDING,
      createdAt: new Date().toISOString(),
      scheduledAt: job.scheduledAt || null,
      startedAt: null,
      completedAt: null,
      timeout: job.timeout || 300000,  // 默认5分钟
      retryCount: 0,
      maxRetries: job.maxRetries || 3,
      metadata: job.metadata || {},
      dependencies: job.dependencies || [],
      resources: job.resources || {}
    };
    
    this.jobs.set(jobId, jobObj);
    this.stats.totalJobs++;
    
    // 如果有调度时间，添加到调度表
    if (jobObj.scheduledAt) {
      this.schedules.set(jobId, jobObj);
    }
    
    // 持久化任务
    await this._saveJob(jobObj);
    
    return jobObj;
  }
  
  /**
   * 调度任务
   */
  async scheduleJob(job) {
    return await this.addJob(job);
  }
  
  /**
   * 取消任务
   */
  async cancelJob(jobId) {
    const job = this.jobs.get(jobId);
    
    if (!job) {
      return { success: false, reason: 'Job not found' };
    }
    
    if (job.status === JobStatus.RUNNING) {
      // 如果任务正在运行，需要中断
      return await this._interruptJob(jobId);
    }
    
    job.status = JobStatus.CANCELLED;
    job.completedAt = new Date().toISOString();
    this.stats.cancelledJobs++;
    
    // 从调度表中移除
    this.schedules.delete(jobId);
    
    await this._saveJob(job);
    
    return { success: true, job };
  }
  
  /**
   * 获取任务状态
   */
  getJobStatus(jobId) {
    return this.jobs.get(jobId) || null;
  }
  
  /**
   * 列出所有任务
   */
  listJobs(options = {}) {
    let jobs = Array.from(this.jobs.values());
    
    // 过滤
    if (options.status) {
      jobs = jobs.filter(j => j.status === options.status);
    }
    
    if (options.type) {
      jobs = jobs.filter(j => j.type === options.type);
    }
    
    if (options.priority !== undefined) {
      jobs = jobs.filter(j => j.priority === options.priority);
    }
    
    // 排序
    if (options.sortBy) {
      jobs.sort((a, b) => {
        switch (options.sortBy) {
          case 'priority':
            return a.priority - b.priority;
          case 'createdAt':
            return new Date(a.createdAt) - new Date(b.createdAt);
          case 'scheduledAt':
            return new Date(a.scheduledAt) - new Date(b.scheduledAt);
          default:
            return 0;
        }
      });
    }
    
    // 限制
    if (options.limit) {
      jobs = jobs.slice(0, options.limit);
    }
    
    return jobs;
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    return {
      id: this.id,
      strategy: this.strategy,
      enabled: this.enabled,
      stats: this.stats,
      jobs: {
        total: this.jobs.size,
        pending: this._countJobsByStatus(JobStatus.PENDING),
        scheduled: this._countJobsByStatus(JobStatus.SCHEDULED),
        running: this._countJobsByStatus(JobStatus.RUNNING),
        completed: this._countJobsByStatus(JobStatus.COMPLETED),
        failed: this._countJobsByStatus(JobStatus.FAILED),
        cancelled: this._countJobsByStatus(JobStatus.CANCELLED)
      },
      resources: this.resourcePool.getResourceStats(),
      prediction: this.resourcePool.predictResourceAvailability()
    };
  }
  
  /**
   * 调度器主循环
   */
  async _tick() {
    if (!this.enabled) {
      return;
    }
    
    // 1. 检查调度任务
    await this._checkScheduledJobs();
    
    // 2. 调度待执行任务
    await this._schedulePendingJobs();
    
    // 3. 检查运行任务超时
    await this._checkJobTimeouts();
    
    // 4. 清理已完成任务
    await this._cleanupCompletedJobs();
  }
  
  /**
   * 检查调度任务
   */
  async _checkScheduledJobs() {
    const now = Date.now();
    const toSchedule = [];
    
    for (const [jobId, job] of this.schedules.entries()) {
      if (job.status === JobStatus.SCHEDULED) {
        const scheduledTime = new Date(job.scheduledAt).getTime();
        if (now >= scheduledTime) {
          toSchedule.push(jobId);
        }
      }
    }
    
    for (const jobId of toSchedule) {
      const job = this.schedules.get(jobId);
      if (job) {
        job.status = JobStatus.PENDING;
        this.schedules.delete(jobId);
        await this._saveJob(job);
      }
    }
  }
  
  /**
   * 调度待执行任务
   */
  async _schedulePendingJobs() {
    // 获取待执行任务
    let pendingJobs = Array.from(this.jobs.values())
      .filter(j => j.status === JobStatus.PENDING);
    
    // 检查依赖
    pendingJobs = pendingJobs.filter(job => {
      return this._checkDependencies(job);
    });
    
    // 根据策略排序
    pendingJobs = this._sortJobs(pendingJobs);
    
    // 检查资源可用性
    for (const job of pendingJobs) {
      const resources = this.resourcePool.hasAvailableResources(job.resources);
      
      if (resources.available) {
        await this._executeJob(job);
      }
    }
  }
  
  /**
   * 检查依赖
   */
  _checkDependencies(job) {
    if (job.dependencies.length === 0) {
      return true;
    }
    
    for (const depId of job.dependencies) {
      const depJob = this.jobs.get(depId);
      if (!depJob || depJob.status !== JobStatus.COMPLETED) {
        return false;
      }
    }
    
    return true;
  }
  
  /**
   * 根据策略排序任务
   */
  _sortJobs(jobs) {
    switch (this.strategy) {
      case SchedulingStrategy.PRIORITY_FIRST:
        return jobs.sort((a, b) => a.priority - b.priority);
      
      case SchedulingStrategy.ROUND_ROBIN:
        // 简化实现：按创建时间排序
        return jobs.sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));
      
      case SchedulingStrategy.FAIR_SHARE:
        // 简化实现：优先级 + 创建时间
        return jobs.sort((a, b) => {
          if (a.priority !== b.priority) {
            return a.priority - b.priority;
          }
          return new Date(a.createdAt) - new Date(b.createdAt);
        });
      
      case SchedulingStrategy.RESOURCE_AWARE:
        // 考虑资源需求
        return jobs.sort((a, b) => {
          // 优先考虑资源需求小的
          const aResourceWeight = (a.resources?.cpu || 0) + (a.resources?.memory || 0);
          const bResourceWeight = (b.resources?.cpu || 0) + (b.resources?.memory || 0);
          
          if (aResourceWeight !== bResourceWeight) {
            return aResourceWeight - bResourceWeight;
          }
          
          // 资源需求相同，按优先级
          return a.priority - b.priority;
        });
      
      case SchedulingStrategy.ADAPTIVE:
        // 自适应：根据资源预测调整
        const prediction = this.resourcePool.predictResourceAvailability();
        
        return jobs.sort((a, b) => {
          // 如果资源紧张，优先调度资源需求小的
          if (prediction.trend === 'increasing') {
            const aResourceWeight = (a.resources?.cpu || 0) + (a.resources?.memory || 0);
            const bResourceWeight = (b.resources?.cpu || 0) + (b.resources?.memory || 0);
            return aResourceWeight - bResourceWeight;
          }
          
          // 否则按优先级
          return a.priority - b.priority;
        });
      
      default:
        return jobs;
    }
  }
  
  /**
   * 执行任务
   */
  async _executeJob(job) {
    // 预留资源
    this.resourcePool.reserveResources(job.resources);
    
    // 更新状态
    job.status = JobStatus.RUNNING;
    job.startedAt = new Date().toISOString();
    this.runningJobs.set(job.id, job);
    
    await this._saveJob(job);
    
    // 异步执行
    this._runJob(job).catch(error => {
      console.error(`[HeartbeatScheduler] Job execution error: ${error.message}`);
    });
  }
  
  /**
   * 运行任务
   */
  async _runJob(job) {
    const startTime = Date.now();
    
    try {
      // 执行任务处理器
      if (typeof job.handler === 'function') {
        const result = await job.handler(job);
        
        // 任务完成
        job.status = JobStatus.COMPLETED;
        job.completedAt = new Date().toISOString();
        job.result = result;
        this.stats.completedJobs++;
      } else {
        throw new Error('Job handler is not a function');
      }
    } catch (error) {
      // 任务失败
      job.status = JobStatus.FAILED;
      job.completedAt = new Date().toISOString();
      job.error = error.message;
      job.retryCount++;
      
      // 检查是否需要重试
      if (job.retryCount < job.maxRetries) {
        job.status = JobStatus.PENDING;
        job.metadata.nextRetryAt = Date.now() + (job.retryDelay || 5000) * job.retryCount;
      } else {
        this.stats.failedJobs++;
      }
    } finally {
      // 释放资源
      this.resourcePool.releaseResources();
      this.runningJobs.delete(job.id);
      
      // 更新统计
      const executionTime = Date.now() - startTime;
      this.stats.averageExecutionTime = 
        (this.stats.averageExecutionTime * (this.stats.completedJobs - 1) + executionTime) /
        this.stats.completedJobs;
      this.stats.lastExecutionTime = executionTime;
      
      // 持久化
      await this._saveJob(job);
    }
  }
  
  /**
   * 中断任务
   */
  async _interruptJob(jobId) {
    const job = this.runningJobs.get(jobId);
    
    if (!job) {
      return { success: false, reason: 'Job not running' };
    }
    
    job.status = JobStatus.CANCELLED;
    job.completedAt = new Date().toISOString();
    job.metadata.interrupted = true;
    
    this.resourcePool.releaseResources();
    this.runningJobs.delete(jobId);
    this.stats.cancelledJobs++;
    
    await this._saveJob(job);
    
    return { success: true, job };
  }
  
  /**
   * 检查任务超时
   */
  async _checkJobTimeouts() {
    const now = Date.now();
    
    for (const [jobId, job] of this.runningJobs.entries()) {
      if (job.startedAt) {
        const startedAt = new Date(job.startedAt).getTime();
        const elapsed = now - startedAt;
        
        if (elapsed > job.timeout) {
          console.warn(`[HeartbeatScheduler] Job ${jobId} timeout after ${elapsed}ms`);
          await this._interruptJob(jobId);
        }
      }
    }
  }
  
  /**
   * 清理已完成任务
   */
  async _cleanupCompletedJobs() {
    const maxAge = 24 * 60 * 60 * 1000;  // 24小时
    const now = Date.now();
    const toDelete = [];
    
    for (const [jobId, job] of this.jobs.entries()) {
      if (job.completedAt) {
        const completedAt = new Date(job.completedAt).getTime();
        if (now - completedAt > maxAge) {
          toDelete.push(jobId);
        }
      }
    }
    
    for (const jobId of toDelete) {
      this.jobs.delete(jobId);
      try {
        await fs.unlink(path.join(JOBS_DIR, `${jobId}.json`));
      } catch (err) {
        console.warn(`[HeartbeatScheduler] Failed to delete job file: ${err.message}`);
      }
    }
    
    return toDelete.length;
  }
  
  /**
   * 按状态计数任务
   */
  _countJobsByStatus(status) {
    return Array.from(this.jobs.values()).filter(j => j.status === status).length;
  }
  
  /**
   * 保存任务到文件
   */
  async _saveJob(job) {
    try {
      const filePath = path.join(JOBS_DIR, `${job.id}.json`);
      await fs.writeFile(filePath, JSON.stringify(job, null, 2));
    } catch (err) {
      console.warn(`[HeartbeatScheduler] Failed to save job: ${err.message}`);
    }
  }
  
  /**
   * 加载调度任务
   */
  async _loadSchedules() {
    try {
      const files = await fs.readdir(JOBS_DIR);
      for (const file of files) {
        if (file.endsWith('.json')) {
          const content = await fs.readFile(path.join(JOBS_DIR, file), 'utf8');
          const job = JSON.parse(content);
          this.jobs.set(job.id, job);
          
          if (job.status === JobStatus.SCHEDULED) {
            this.schedules.set(job.id, job);
          }
        }
      }
      
      console.log(`[HeartbeatScheduler] Loaded ${this.jobs.size} jobs`);
    } catch (err) {
      console.log(`[HeartbeatScheduler] No jobs found`);
    }
  }
}

// ==================== 全局实例 ====================

let globalScheduler = null;

/**
 * 获取全局调度器
 */
async function getHeartbeatScheduler() {
  if (!globalScheduler) {
    globalScheduler = new JobScheduler();
    await globalScheduler.start();
  }
  return globalScheduler;
}

/**
 * 设置全局调度器
 */
function setHeartbeatScheduler(scheduler) {
  globalScheduler = scheduler;
}

// ==================== 导出 ====================

module.exports = {
  // 类型定义
  JobType,
  JobStatus,
  JobPriority,
  SchedulingStrategy,
  
  // 类定义
  ResourcePool,
  JobScheduler,
  
  // 全局实例
  getHeartbeatScheduler,
  setHeartbeatScheduler,
  
  // 辅助函数
  ensureDirectories
};
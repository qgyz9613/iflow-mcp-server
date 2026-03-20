/**
 * iFlow Autonomous Module v2.0
 * 自主执行引擎（基于OpenClaw subagent-registry设计）
 * 
 * 新增功能:
 * - 任务调度器
 * - 心跳监控
 * - 错误恢复
 * - 任务优先级
 * - 并发控制
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');

const AUTONOMOUS_DIR = path.join(__dirname, '..', 'autonomous-data');
const TASKS_FILE = path.join(AUTONOMOUS_DIR, 'tasks.json');
const SCHEDULE_FILE = path.join(AUTONOMOUS_DIR, 'schedule.json');

[AUTONOMOUS_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// ============================================================
// 任务调度器
// ============================================================

class TaskScheduler {
  constructor() {
    this.tasks = new Map(); // runId -> TaskRecord
    this.queue = []; // 待执行队列
    this.running = new Map(); // 正在执行的任务
    this.completed = []; // 已完成任务
    this.sweeper = null;
    this.maxConcurrent = 5;
    this.taskTimeout = 30 * 60 * 1000; // 30分钟
    this.orphanTimeout = 5 * 60 * 1000; // 5分钟孤儿检测
    
    this.loadFromDisk();
    this.startSweeper();
  }
  
  /**
   * 创建任务
   */
  createTask(config = {}) {
    const taskId = uuidv4();
    const task = {
      runId: taskId,
      goal: config.goal || 'General autonomous operation',
      priority: config.priority || 5, // 1-10, 10最高
      status: 'pending',
      maxIterations: config.maxIterations || 10,
      currentIteration: 0,
      actions: [],
      errors: [],
      createdAt: Date.now(),
      startedAt: null,
      endedAt: null,
      parentId: config.parentId || null, // 父任务ID（支持嵌套）
      depth: config.depth || 0, // 嵌套深度
      metadata: config.metadata || {}
    };
    
    this.tasks.set(taskId, task);
    this.queue.push(taskId);
    this.sortQueue();
    this.persistToDisk();
    
    return task;
  }
  
  /**
   * 启动任务
   */
  startTask(taskId) {
    const task = this.tasks.get(taskId);
    if (!task) {
      return { status: 'error', message: 'Task not found' };
    }
    
    if (task.status !== 'pending') {
      return { status: 'error', message: `Task already ${task.status}` };
    }
    
    // 检查并发限制
    if (this.running.size >= this.maxConcurrent) {
      return { status: 'error', message: 'Max concurrent tasks reached' };
    }
    
    // 检查嵌套深度
    if (task.depth > 5) {
      return { status: 'error', message: 'Max subagent depth exceeded' };
    }
    
    task.status = 'running';
    task.startedAt = Date.now();
    this.running.set(taskId, task);
    
    // 从队列移除
    const idx = this.queue.indexOf(taskId);
    if (idx !== -1) {
      this.queue.splice(idx, 1);
    }
    
    this.persistToDisk();
    
    return { status: 'ok', task };
  }
  
  /**
   * 完成任务
   */
  completeTask(taskId, result = {}) {
    const task = this.tasks.get(taskId);
    if (!task) {
      return { status: 'error', message: 'Task not found' };
    }
    
    task.status = 'completed';
    task.endedAt = Date.now();
    task.result = result;
    task.duration = task.endedAt - task.startedAt;
    
    this.running.delete(taskId);
    this.completed.push(taskId);
    
    // 限制已完成任务数量
    if (this.completed.length > 100) {
      const oldTaskId = this.completed.shift();
      this.tasks.delete(oldTaskId);
    }
    
    this.persistToDisk();
    
    return { status: 'ok', task };
  }
  
  /**
   * 任务失败
   */
  failTask(taskId, error) {
    const task = this.tasks.get(taskId);
    if (!task) {
      return { status: 'error', message: 'Task not found' };
    }
    
    task.status = 'failed';
    task.endedAt = Date.now();
    task.error = error;
    task.errors.push({
      error,
      timestamp: Date.now()
    });
    
    this.running.delete(taskId);
    this.persistToDisk();
    
    return { status: 'ok', task };
  }
  
  /**
   * 记录行动
   */
  recordAction(taskId, action, result) {
    const task = this.tasks.get(taskId);
    if (!task) {
      return { status: 'error', message: 'Task not found' };
    }
    
    task.actions.push({
      iteration: task.currentIteration,
      action,
      result,
      timestamp: Date.now()
    });
    
    task.currentIteration++;
    this.persistToDisk();
    
    return { status: 'ok', actionCount: task.actions.length };
  }
  
  /**
   * 创建子任务
   */
  spawnChild(parentId, config = {}) {
    const parent = this.tasks.get(parentId);
    if (!parent) {
      return { status: 'error', message: 'Parent task not found' };
    }
    
    const child = this.createTask({
      ...config,
      parentId,
      depth: parent.depth + 1
    });
    
    parent.children = parent.children || [];
    parent.children.push(child.runId);
    
    this.persistToDisk();
    
    return child;
  }
  
  /**
   * 排序队列（按优先级）
   */
  sortQueue() {
    this.queue.sort((a, b) => {
      const taskA = this.tasks.get(a);
      const taskB = this.tasks.get(b);
      return (taskB?.priority || 0) - (taskA?.priority || 0);
    });
  }
  
  /**
   * 启动清扫器（检测孤儿任务）
   */
  startSweeper() {
    if (this.sweeper) return;
    
    this.sweeper = setInterval(() => {
      const now = Date.now();
      
      for (const [taskId, task] of this.running) {
        // 检查超时
        if (task.startedAt && now - task.startedAt > this.taskTimeout) {
          console.warn(`Task timeout: ${taskId}`);
          this.failTask(taskId, 'Task timeout');
        }
        
        // 检查孤儿（长时间无活动）
        const lastActivity = task.actions?.length > 0
          ? task.actions[task.actions.length - 1].timestamp
          : task.startedAt;
        
        if (lastActivity && now - lastActivity > this.orphanTimeout) {
          console.warn(`Orphan task detected: ${taskId}`);
          // 可以选择恢复或终止
        }
      }
    }, 60 * 1000); // 每分钟检查
    
    if (this.sweeper.unref) {
      this.sweeper.unref();
    }
  }
  
  /**
   * 停止清扫器
   */
  stopSweeper() {
    if (this.sweeper) {
      clearInterval(this.sweeper);
      this.sweeper = null;
    }
  }
  
  /**
   * 持久化到磁盘
   */
  persistToDisk() {
    try {
      const data = {
        tasks: Array.from(this.tasks.entries()),
        queue: this.queue,
        running: Array.from(this.running.keys()),
        completed: this.completed.slice(-100),
        savedAt: Date.now()
      };
      fs.writeFileSync(TASKS_FILE, JSON.stringify(data, null, 2));
    } catch (e) {
      console.error('Failed to persist tasks:', e);
    }
  }
  
  /**
   * 从磁盘恢复
   */
  loadFromDisk() {
    try {
      if (fs.existsSync(TASKS_FILE)) {
        const data = JSON.parse(fs.readFileSync(TASKS_FILE, 'utf8'));
        
        if (data.tasks) {
          this.tasks = new Map(data.tasks);
        }
        if (data.queue) {
          this.queue = data.queue;
        }
        if (data.completed) {
          this.completed = data.completed;
        }
        
        // 恢复运行中的任务
        if (data.running) {
          for (const taskId of data.running) {
            const task = this.tasks.get(taskId);
            if (task && task.status === 'running') {
              // 检查是否过期
              if (Date.now() - task.startedAt > this.taskTimeout) {
                task.status = 'failed';
                task.error = 'Task timeout on recovery';
              } else {
                this.running.set(taskId, task);
              }
            }
          }
        }
      }
    } catch (e) {
      console.error('Failed to load tasks:', e);
    }
  }
  
  /**
   * 获取统计
   */
  getStats() {
    return {
      total: this.tasks.size,
      pending: this.queue.length,
      running: this.running.size,
      completed: this.completed.length
    };
  }
}

// ============================================================
// 全局调度器实例
// ============================================================

let globalScheduler = null;

function getScheduler() {
  if (!globalScheduler) {
    globalScheduler = new TaskScheduler();
  }
  return globalScheduler;
}

// ============================================================
// 兼容旧API
// ============================================================

let activeTask = null;
let isRunning = false;

function start(config = {}) {
  const scheduler = getScheduler();
  const task = scheduler.createTask(config);
  const result = scheduler.startTask(task.runId);
  
  if (result.status === 'ok') {
    activeTask = task;
    isRunning = true;
  }
  
  return result;
}

function stop() {
  if (!activeTask) {
    return { status: 'ok', message: 'No active task' };
  }
  
  const scheduler = getScheduler();
  const result = scheduler.completeTask(activeTask.runId);
  
  activeTask = null;
  isRunning = false;
  
  return result;
}

function getStatus() {
  const scheduler = getScheduler();
  const stats = scheduler.getStats();
  
  return {
    status: 'ok',
    isRunning,
    activeTask: activeTask ? {
      id: activeTask.runId,
      goal: activeTask.goal,
      currentIteration: activeTask.currentIteration,
      maxIterations: activeTask.maxIterations,
      status: activeTask.status
    } : null,
    stats,
    time: Date.now()
  };
}

function recordAction(action, result) {
  if (!activeTask) {
    return { status: 'error', message: 'No active task' };
  }
  
  const scheduler = getScheduler();
  return scheduler.recordAction(activeTask.runId, action, result);
}

// ============================================================
// 导出
// ============================================================

module.exports = {
  // 核心类
  TaskScheduler,
  getScheduler,
  
  // 兼容旧API
  start,
  stop,
  getStatus,
  recordAction,
  
  // 新API
  createTask: (config) => getScheduler().createTask(config),
  startTask: (taskId) => getScheduler().startTask(taskId),
  completeTask: (taskId, result) => getScheduler().completeTask(taskId, result),
  failTask: (taskId, error) => getScheduler().failTask(taskId, error),
  spawnChild: (parentId, config) => getScheduler().spawnChild(parentId, config),
  getStats: () => getScheduler().getStats()
};
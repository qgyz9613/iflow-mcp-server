/**
 * iFlow Hooks Advanced Module
 * 参考 OpenClaw 的生命周期钩子和记忆刷新机制
 * 支持：12种钩子类型、条件触发、自动记忆刷新
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');

const DATA_DIR = path.join(__dirname, '..', 'hooks-advanced-data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

// ==================== 钩子类型定义 ====================

const HOOK_TYPES = {
  // Agent 生命周期
  beforeAgentStart: {
    priority: 1,
    async: true,
    description: 'Agent 启动前触发，可用于加载记忆、初始化状态'
  },
  afterAgentEnd: {
    priority: 1,
    async: true,
    description: 'Agent 结束后触发，可用于保存记忆、清理资源'
  },
  
  // 模型调用
  beforeModelResolve: {
    priority: 2,
    async: true,
    description: '模型解析前触发，可用于模型选择、参数调整'
  },
  afterModelResponse: {
    priority: 2,
    async: true,
    description: '模型响应后触发，可用于响应处理、日志记录'
  },
  
  // 工具调用
  beforeToolCall: {
    priority: 3,
    async: true,
    description: '工具调用前触发，可用于参数验证、权限检查'
  },
  afterToolCall: {
    priority: 3,
    async: true,
    description: '工具调用后触发，可用于结果处理、错误处理'
  },
  
  // 压缩
  beforeCompaction: {
    priority: 2,
    async: true,
    description: '上下文压缩前触发，可用于记忆刷新'
  },
  afterCompaction: {
    priority: 2,
    async: true,
    description: '上下文压缩后触发，可用于状态恢复'
  },
  
  // 子代理
  subagentSpawning: {
    priority: 2,
    async: true,
    description: '子代理创建时触发'
  },
  subagentEnded: {
    priority: 2,
    async: true,
    description: '子代理结束时触发'
  },
  
  // 消息
  messageReceived: {
    priority: 1,
    async: false,
    description: '收到消息时触发'
  },
  messageSending: {
    priority: 1,
    async: false,
    description: '发送消息前触发'
  },
  
  // 心跳
  beforeHeartbeat: {
    priority: 1,
    async: false,
    description: '心跳执行前触发'
  },
  afterHeartbeat: {
    priority: 1,
    async: false,
    description: '心跳执行后触发'
  },
  
  // 技能
  beforeSkillExecute: {
    priority: 2,
    async: true,
    description: '技能执行前触发'
  },
  afterSkillExecute: {
    priority: 2,
    async: true,
    description: '技能执行后触发'
  }
};

// ==================== 自动记忆刷新配置 ====================

const DEFAULT_MEMORY_FLUSH_CONFIG = {
  enabled: true,
  softThresholdTokens: 4000,        // 触发刷新的软阈值
  systemPrompt: '会话即将压缩，请立即保存持久化记忆。',
  userPrompt: '将重要决策、偏好和事实写入记忆系统。如果没有需要保存的内容，回复 NO_REPLY。',
  includeCitations: true,
  maxSnippets: 10
};

// ==================== 钩子条件评估器 ====================

class HookConditionEvaluator {
  /**
   * 评估条件
   */
  evaluate(condition, event) {
    if (!condition) return true;
    
    // 简单条件
    if (typeof condition === 'string') {
      return this._evaluateString(condition, event);
    }
    
    // 对象条件
    if (typeof condition === 'object') {
      return this._evaluateObject(condition, event);
    }
    
    // 函数条件
    if (typeof condition === 'function') {
      try {
        return condition(event);
      } catch (e) {
        console.warn('[HookCondition] Evaluation error:', e.message);
        return false;
      }
    }
    
    return true;
  }
  
  /**
   * 字符串条件评估
   */
  _evaluateString(condition, event) {
    // 支持简单的属性路径，如 "tool.name === 'memory_save'"
    try {
      const fn = new Function('event', `return ${condition}`);
      return fn(event);
    } catch (e) {
      return false;
    }
  }
  
  /**
   * 对象条件评估
   */
  _evaluateObject(condition, event) {
    for (const [key, value] of Object.entries(condition)) {
      const eventValue = this._getNestedValue(event, key);
      
      if (Array.isArray(value)) {
        if (!value.includes(eventValue)) return false;
      } else if (value instanceof RegExp) {
        if (!value.test(eventValue)) return false;
      } else if (eventValue !== value) {
        return false;
      }
    }
    return true;
  }
  
  /**
   * 获取嵌套值
   */
  _getNestedValue(obj, path) {
    const parts = path.split('.');
    let current = obj;
    for (const part of parts) {
      if (current == null) return undefined;
      current = current[part];
    }
    return current;
  }
}

// ==================== 钩子执行器 ====================

class HookExecutor {
  constructor(config = {}) {
    this.timeout = config.timeout || 30000;
    this.maxRetries = config.maxRetries || 2;
  }
  
  /**
   * 执行钩子
   */
  async execute(hook, event) {
    const start = Date.now();
    
    try {
      // 检查是否是函数字符串
      if (typeof hook.callback === 'string') {
        const fn = new Function('event', `return (${hook.callback})(event)`);
        const result = await this._executeWithTimeout(fn, event, hook.async);
        return { success: true, result, time: Date.now() - start };
      }
      
      // 直接函数
      if (typeof hook.callback === 'function') {
        const result = await this._executeWithTimeout(hook.callback, event, hook.async);
        return { success: true, result, time: Date.now() - start };
      }
      
      // 脚本路径
      if (hook.script) {
        const result = await this._executeScript(hook.script, event);
        return { success: true, result, time: Date.now() - start };
      }
      
      return { success: false, error: 'No valid callback', time: Date.now() - start };
    } catch (e) {
      return { success: false, error: e.message, time: Date.now() - start };
    }
  }
  
  /**
   * 带超时执行
   */
  async _executeWithTimeout(fn, event, isAsync) {
    if (!isAsync) {
      return fn(event);
    }
    
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error('Hook execution timeout'));
      }, this.timeout);
      
      Promise.resolve(fn(event))
        .then(result => {
          clearTimeout(timer);
          resolve(result);
        })
        .catch(err => {
          clearTimeout(timer);
          reject(err);
        });
    });
  }
  
  /**
   * 执行脚本
   */
  async _executeScript(scriptPath, event) {
    if (!fs.existsSync(scriptPath)) {
      throw new Error(`Script not found: ${scriptPath}`);
    }
    
    const { spawn } = require('child_process');
    const ext = path.extname(scriptPath).toLowerCase();
    
    return new Promise((resolve, reject) => {
      let cmd, args;
      
      switch (ext) {
        case '.py':
          cmd = 'python3';
          args = [scriptPath, JSON.stringify(event)];
          break;
        case '.js':
          cmd = 'node';
          args = [scriptPath, JSON.stringify(event)];
          break;
        case '.sh':
          cmd = 'bash';
          args = [scriptPath, JSON.stringify(event)];
          break;
        default:
          return reject(new Error(`Unsupported script type: ${ext}`));
      }
      
      const proc = spawn(cmd, args, { timeout: this.timeout });
      let stdout = '';
      let stderr = '';
      
      proc.stdout.on('data', data => stdout += data);
      proc.stderr.on('data', data => stderr += data);
      
      proc.on('close', code => {
        if (code === 0) {
          try {
            resolve(JSON.parse(stdout));
          } catch {
            resolve(stdout);
          }
        } else {
          reject(new Error(stderr || `Exit code: ${code}`));
        }
      });
      
      proc.on('error', reject);
    });
  }
}

// ==================== 主钩子管理器 ====================

class HooksAdvancedManager {
  constructor(config = {}) {
    this.config = config;
    this.registry = {};
    this.conditions = new HookConditionEvaluator();
    this.executor = new HookExecutor(config.executor || {});
    this.memoryFlushConfig = { ...DEFAULT_MEMORY_FLUSH_CONFIG, ...config.memoryFlush };
    
    // 钩子到工具映射
    this.toolMappings = [];
    
    // 自动动作
    this.autoActions = {};
    
    // 压缩周期跟踪
    this.compactionCycles = new Map();
    
    this._load();
  }
  
  /**
   * 注册钩子
   */
  register(hookType, callback, options = {}) {
    const start = Date.now();
    
    if (!HOOK_TYPES[hookType]) {
      return { status: 'error', message: `Unknown hook type: ${hookType}` };
    }
    
    const hook = {
      id: options.id || uuidv4(),
      type: hookType,
      callback: callback,
      priority: options.priority || HOOK_TYPES[hookType].priority,
      once: options.once || false,
      condition: options.condition || null,
      enabled: options.enabled !== false,
      createdAt: new Date().toISOString(),
      callCount: 0
    };
    
    if (!this.registry[hookType]) {
      this.registry[hookType] = [];
    }
    
    this.registry[hookType].push(hook);
    this._save();
    
    return { status: 'ok', hookId: hook.id, time: Date.now() - start };
  }
  
  /**
   * 注销钩子
   */
  unregister(hookId) {
    for (const type of Object.keys(this.registry)) {
      const index = this.registry[type].findIndex(h => h.id === hookId);
      if (index >= 0) {
        this.registry[type].splice(index, 1);
        this._save();
        return { status: 'ok', deleted: true };
      }
    }
    return { status: 'ok', deleted: false };
  }
  
  /**
   * 触发钩子
   */
  async trigger(hookType, event = {}) {
    const start = Date.now();
    
    if (!HOOK_TYPES[hookType]) {
      return { status: 'ok', message: 'Unknown hook type, skipped', time: 0 };
    }
    
    const hooks = this.registry[hookType] || [];
    const enabledHooks = hooks.filter(h => h.enabled);
    
    // 按优先级排序
    enabledHooks.sort((a, b) => a.priority - b.priority);
    
    const results = [];
    const toRemove = [];
    
    for (const hook of enabledHooks) {
      // 评估条件
      if (!this.conditions.evaluate(hook.condition, event)) {
        continue;
      }
      
      // 执行钩子
      const result = await this.executor.execute(hook, event);
      hook.callCount++;
      
      results.push({
        hookId: hook.id,
        ...result
      });
      
      // 标记一次性钩子
      if (hook.once) {
        toRemove.push(hook.id);
      }
    }
    
    // 移除一次性钩子
    for (const id of toRemove) {
      this.unregister(id);
    }
    
    // 处理自动动作
    await this._processAutoActions(hookType, event, results);
    
    return {
      status: 'ok',
      type: hookType,
      executed: results.length,
      results,
      time: Date.now() - start
    };
  }
  
  /**
   * 添加自动动作
   */
  addAutoAction(hookType, action) {
    if (!this.autoActions[hookType]) {
      this.autoActions[hookType] = [];
    }
    
    const autoAction = {
      id: action.id || uuidv4(),
      name: action.name,
      trigger: action.trigger,           // 触发条件
      action: action.action,             // 动作类型: notify, execute, save
      script: action.script,             // 脚本路径
      message: action.message,           // 通知消息
      enabled: action.enabled !== false,
      createdAt: new Date().toISOString()
    };
    
    this.autoActions[hookType].push(autoAction);
    this._save();
    
    return { status: 'ok', action: autoAction };
  }
  
  /**
   * 处理自动动作
   */
  async _processAutoActions(hookType, event, results) {
    const actions = this.autoActions[hookType] || [];
    
    for (const action of actions) {
      if (!action.enabled) continue;
      
      // 检查触发条件
      if (action.trigger && !this.conditions.evaluate(action.trigger, event)) {
        continue;
      }
      
      switch (action.action) {
        case 'notify':
          console.log(`[HookAutoAction] ${action.name}: ${action.message}`);
          break;
          
        case 'execute':
          if (action.script) {
            try {
              await this.executor._executeScript(action.script, event);
            } catch (e) {
              console.warn(`[HookAutoAction] Script failed: ${e.message}`);
            }
          }
          break;
          
        case 'save':
          // 保存到记忆系统
          if (event.toolResult && event.tool === 'save_memory') {
            // 记录保存动作
            console.log(`[HookAutoAction] Memory saved: ${event.toolResult.id}`);
          }
          break;
      }
    }
  }
  
  /**
   * 记忆刷新 (压缩前触发)
   * 参考 OpenClaw 的记忆刷新机制
   */
  async triggerMemoryFlush(sessionInfo) {
    const { estimatedTokens, contextWindow, reserveTokensFloor } = sessionInfo;
    
    if (!this.memoryFlushConfig.enabled) {
      return { status: 'ok', triggered: false, reason: 'disabled' };
    }
    
    const threshold = contextWindow - reserveTokensFloor - this.memoryFlushConfig.softThresholdTokens;
    
    if (estimatedTokens <= threshold) {
      return { status: 'ok', triggered: false, reason: 'below_threshold' };
    }
    
    // 检查是否已经为这个压缩周期刷新过
    const sessionId = sessionInfo.sessionId || 'default';
    const lastFlushCycle = this.compactionCycles.get(sessionId) || 0;
    const currentCycle = sessionInfo.compactionCycle || 0;
    
    if (currentCycle === lastFlushCycle) {
      return { status: 'ok', triggered: false, reason: 'already_flushed' };
    }
    
    // 触发记忆刷新
    const flushEvent = {
      type: 'memory_flush',
      sessionInfo,
      prompts: {
        system: this.memoryFlushConfig.systemPrompt,
        user: this.memoryFlushConfig.userPrompt
      },
      config: this.memoryFlushConfig
    };
    
    const result = await this.trigger('beforeCompaction', flushEvent);
    
    // 记录刷新周期
    this.compactionCycles.set(sessionId, currentCycle);
    
    return {
      status: 'ok',
      triggered: true,
      ...result
    };
  }
  
  /**
   * 列出钩子
   */
  list(type = null) {
    if (type) {
      return this.registry[type] || [];
    }
    
    const all = [];
    for (const [t, hooks] of Object.entries(this.registry)) {
      for (const h of hooks) {
        all.push({ type: t, ...h });
      }
    }
    return all;
  }
  
  /**
   * 切换钩子状态
   */
  toggle(hookId, enabled) {
    for (const type of Object.keys(this.registry)) {
      const hook = this.registry[type].find(h => h.id === hookId);
      if (hook) {
        hook.enabled = enabled;
        this._save();
        return { status: 'ok', hookId, enabled };
      }
    }
    return { status: 'error', message: 'Hook not found' };
  }
  
  /**
   * 清除所有钩子
   */
  clear(type = null) {
    if (type) {
      this.registry[type] = [];
    } else {
      this.registry = {};
    }
    this._save();
    return { status: 'ok' };
  }
  
  /**
   * 获取钩子类型定义
   */
  getTypes() {
    return Object.entries(HOOK_TYPES).map(([id, def]) => ({
      id,
      ...def
    }));
  }
  
  /**
   * 保存到磁盘
   */
  _save() {
    const dataPath = path.join(DATA_DIR, 'registry.json');
    fs.writeFileSync(dataPath, JSON.stringify({
      registry: this.registry,
      autoActions: this.autoActions,
      toolMappings: this.toolMappings
    }, null, 2));
  }
  
  /**
   * 从磁盘加载
   */
  _load() {
    const dataPath = path.join(DATA_DIR, 'registry.json');
    if (fs.existsSync(dataPath)) {
      try {
        const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
        this.registry = data.registry || {};
        this.autoActions = data.autoActions || {};
        this.toolMappings = data.toolMappings || [];
        
        // 恢复函数引用
        for (const hooks of Object.values(this.registry)) {
          for (const hook of hooks) {
            if (typeof hook.callback === 'string' && hook.callback.includes('=>')) {
              // 保持字符串形式，执行时再解析
            }
          }
        }
        
        console.log(`[HooksAdvanced] Loaded ${this.list().length} hooks`);
      } catch (e) {
        console.warn('[HooksAdvanced] Load failed:', e.message);
      }
    }
  }
}

// ==================== 导出 ====================

module.exports = {
  HooksAdvancedManager,
  HookConditionEvaluator,
  HookExecutor,
  HOOK_TYPES,
  DEFAULT_MEMORY_FLUSH_CONFIG,
  
  // 快捷方法
  createManager: (config) => new HooksAdvancedManager(config)
};

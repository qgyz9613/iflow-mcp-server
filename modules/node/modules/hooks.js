/**
 * iFlow Hooks Module - 插件钩子系统
 * 参考 OpenClaw 的生命周期钩子设计
 * 增强：钩子到工具自动映射
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');

const HOOKS_DIR = path.join(__dirname, '..', 'hooks-data');
if (!fs.existsSync(HOOKS_DIR)) fs.mkdirSync(HOOKS_DIR, { recursive: true });

// ========== 钩子类型定义 ==========
const HOOK_TYPES = {
  // 代理生命周期
  beforeAgentStart: { priority: 1, async: true },
  afterAgentEnd: { priority: 1, async: true },
  
  // 模型调用
  beforeModelResolve: { priority: 2, async: true },
  beforePromptBuild: { priority: 2, async: true },
  
  // 工具调用
  beforeToolCall: { priority: 3, async: true },
  afterToolCall: { priority: 3, async: true },
  
  // 压缩
  beforeCompaction: { priority: 2, async: true },
  afterCompaction: { priority: 2, async: true },
  
  // 子代理
  subagentSpawning: { priority: 2, async: true },
  subagentEnded: { priority: 2, async: true },
  
  // 消息
  messageReceived: { priority: 1, async: false },
  messageSending: { priority: 1, async: false },
  
  // 心跳
  beforeHeartbeat: { priority: 1, async: false },
  afterHeartbeat: { priority: 1, async: false },
  
  // 技能
  beforeSkillExecute: { priority: 2, async: true },
  afterSkillExecute: { priority: 2, async: true }
};

// ========== 钩子注册表 ==========
let hooksRegistry = {};

// ========== 钩子到工具映射（新增） ==========
let hookToolMappings = [];

// 加载持久化的钩子
function loadHooks() {
  const registryPath = path.join(HOOKS_DIR, 'registry.json');
  if (fs.existsSync(registryPath)) {
    try {
      const data = JSON.parse(fs.readFileSync(registryPath, 'utf8'));
      hooksRegistry = data.hooks || {};
      hookToolMappings = data.mappings || [];
    } catch (e) {
      hooksRegistry = {};
      hookToolMappings = [];
    }
  }
}

// 保存钩子注册表
function saveHooks() {
  const registryPath = path.join(HOOKS_DIR, 'registry.json');
  fs.writeFileSync(registryPath, JSON.stringify({
    hooks: hooksRegistry,
    mappings: hookToolMappings
  }, null, 2));
}

// 初始化加载
loadHooks();

// ========== 核心函数 ==========

/**
 * 注册钩子
 * @param {string} hookType - 钩子类型
 * @param {function} callback - 回调函数
 * @param {object} options - 选项 { priority, once, condition }
 */
function register(hookType, callback, options = {}) {
  const start = Date.now();
  try {
    if (!HOOK_TYPES[hookType]) {
      return { status: 'error', message: `Unknown hook type: ${hookType}`, time: Date.now() - start };
    }
    
    const hookId = uuidv4();
    const hook = {
      id: hookId,
      type: hookType,
      callback: callback.toString(), // 存储函数字符串
      priority: options.priority || HOOK_TYPES[hookType].priority,
      once: options.once || false,
      condition: options.condition || null,
      enabled: true,
      created_at: new Date().toISOString(),
      callCount: 0
    };
    
    if (!hooksRegistry[hookType]) {
      hooksRegistry[hookType] = [];
    }
    hooksRegistry[hookType].push(hook);
    saveHooks();
    
    return { status: 'ok', hookId, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 触发钩子
 * @param {string} hookType - 钩子类型
 * @param {object} event - 事件数据
 * @returns {object} - 处理结果
 */
async function trigger(hookType, event = {}) {
  const start = Date.now();
  try {
    if (!HOOK_TYPES[hookType]) {
      return { status: 'ok', message: 'Unknown hook type, skipped', time: Date.now() - start };
    }
    
    const hooks = hooksRegistry[hookType] || [];
    const enabledHooks = hooks.filter(h => h.enabled);
    
    // 按优先级排序
    enabledHooks.sort((a, b) => a.priority - b.priority);
    
    const results = [];
    const toRemove = [];
    
    for (const hook of enabledHooks) {
      // 检查条件
      if (hook.condition && !evaluateCondition(hook.condition, event)) {
        continue;
      }
      
      try {
        // 执行回调
        const callback = eval(`(${hook.callback})`);
        const hookDef = HOOK_TYPES[hookType];
        
        let result;
        if (hookDef.async) {
          result = await Promise.resolve(callback(event));
        } else {
          result = callback(event);
        }
        
        results.push({ hookId: hook.id, result, status: 'ok' });
        hook.callCount++;
        
        // 一次性钩子标记移除
        if (hook.once) {
          toRemove.push(hook.id);
        }
      } catch (e) {
        results.push({ hookId: hook.id, error: e.message, status: 'error' });
      }
    }
    
    // 移除一次性钩子
    if (toRemove.length > 0) {
      hooksRegistry[hookType] = hooks.filter(h => !toRemove.includes(h.id));
      saveHooks();
    }
    
    return { status: 'ok', results, triggered: results.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 评估条件
 */
function evaluateCondition(condition, event) {
  try {
    // 简单条件评估
    if (typeof condition === 'function') {
      return condition(event);
    }
    if (typeof condition === 'string') {
      // 支持 "event.field === value" 格式
      const fn = new Function('event', `return ${condition}`);
      return fn(event);
    }
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * 取消注册钩子
 */
function unregister(hookId) {
  const start = Date.now();
  try {
    let found = false;
    for (const hookType of Object.keys(hooksRegistry)) {
      const idx = hooksRegistry[hookType].findIndex(h => h.id === hookId);
      if (idx >= 0) {
        hooksRegistry[hookType].splice(idx, 1);
        found = true;
        break;
      }
    }
    
    if (found) {
      saveHooks();
    }
    
    return { status: 'ok', found, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 列出钩子
 */
function list(hookType = null) {
  const start = Date.now();
  try {
    if (hookType) {
      const hooks = hooksRegistry[hookType] || [];
      return { status: 'ok', hooks, total: hooks.length, time: Date.now() - start };
    }
    
    const allHooks = [];
    for (const [type, hooks] of Object.entries(hooksRegistry)) {
      allHooks.push(...hooks.map(h => ({ ...h, type })));
    }
    
    return { status: 'ok', hooks: allHooks, total: allHooks.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 启用/禁用钩子
 */
function toggle(hookId, enabled) {
  const start = Date.now();
  try {
    for (const hookType of Object.keys(hooksRegistry)) {
      const hook = hooksRegistry[hookType].find(h => h.id === hookId);
      if (hook) {
        hook.enabled = enabled;
        saveHooks();
        return { status: 'ok', hook, time: Date.now() - start };
      }
    }
    
    return { status: 'error', message: 'Hook not found', time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 清除所有钩子
 */
function clear(hookType = null) {
  const start = Date.now();
  try {
    if (hookType) {
      hooksRegistry[hookType] = [];
    } else {
      hooksRegistry = {};
    }
    saveHooks();
    
    return { status: 'ok', time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 获取钩子类型定义
 */
function getTypes() {
  return { status: 'ok', types: Object.keys(HOOK_TYPES), definitions: HOOK_TYPES };
}

// ============================================================
// 钩子到工具映射系统（新增）
// ============================================================

/**
 * 添加钩子到工具的映射
 * @param {object} mapping - 映射规则
 * @param {string} mapping.hookType - 钩子类型
 * @param {string} mapping.toolName - 工具名称
 * @param {object} mapping.condition - 触发条件
 * @param {object} mapping.params - 工具参数模板
 * @param {string} mapping.trigger - 触发时机 'before' | 'after'
 * @param {boolean} mapping.async - 是否异步调用
 * @returns {object} - 结果
 */
function addToolMapping(mapping) {
  const start = Date.now();
  
  try {
    // 验证钩子类型
    if (!HOOK_TYPES[mapping.hookType]) {
      return { status: 'error', message: `Unknown hook type: ${mapping.hookType}` };
    }
    
    const mappingId = uuidv4();
    const mappingRecord = {
      id: mappingId,
      hookType: mapping.hookType,
      toolName: mapping.toolName,
      condition: mapping.condition || null,
      params: mapping.params || {},
      trigger: mapping.trigger || 'after',
      async: mapping.async !== false,
      enabled: true,
      priority: mapping.priority || 0,
      callCount: 0,
      lastCallAt: null,
      createdAt: new Date().toISOString()
    };
    
    hookToolMappings.push(mappingRecord);
    saveHooks();
    
    return { status: 'ok', mappingId, mapping: mappingRecord, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 移除钩子到工具的映射
 * @param {string} mappingId - 映射ID
 * @returns {object} - 结果
 */
function removeToolMapping(mappingId) {
  const start = Date.now();
  
  try {
    const idx = hookToolMappings.findIndex(m => m.id === mappingId);
    if (idx >= 0) {
      const removed = hookToolMappings.splice(idx, 1)[0];
      saveHooks();
      return { status: 'ok', mapping: removed, time: Date.now() - start };
    }
    
    return { status: 'error', message: 'Mapping not found', time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 列出钩子到工具的映射
 * @param {object} options - 过滤选项
 * @returns {object} - 映射列表
 */
function listToolMappings(options = {}) {
  const start = Date.now();
  
  try {
    let mappings = hookToolMappings;
    
    // 过滤钩子类型
    if (options.hookType) {
      mappings = mappings.filter(m => m.hookType === options.hookType);
    }
    
    // 过滤工具名称
    if (options.toolName) {
      mappings = mappings.filter(m => m.toolName === options.toolName);
    }
    
    // 过滤启用状态
    if (options.enabled !== undefined) {
      mappings = mappings.filter(m => m.enabled === options.enabled);
    }
    
    return { 
      status: 'ok', 
      mappings, 
      total: mappings.length, 
      time: Date.now() - start 
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 启用/禁用工具映射
 * @param {string} mappingId - 映射ID
 * @param {boolean} enabled - 启用状态
 * @returns {object} - 结果
 */
function toggleToolMapping(mappingId, enabled) {
  const start = Date.now();
  
  try {
    const mapping = hookToolMappings.find(m => m.id === mappingId);
    if (!mapping) {
      return { status: 'error', message: 'Mapping not found', time: Date.now() - start };
    }
    
    mapping.enabled = enabled;
    saveHooks();
    
    return { status: 'ok', mapping, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 执行钩子到工具的映射
 * @param {string} hookType - 钩子类型
 * @param {object} event - 事件数据
 * @returns {object} - 执行结果
 */
async function executeToolMappings(hookType, event) {
  const start = Date.now();
  
  try {
    // 获取相关的映射
    const mappings = hookToolMappings
      .filter(m => m.hookType === hookType && m.enabled)
      .sort((a, b) => b.priority - a.priority);
    
    if (mappings.length === 0) {
      return { status: 'ok', triggered: 0, time: Date.now() - start };
    }
    
    const results = [];
    
    for (const mapping of mappings) {
      // 检查条件
      if (mapping.condition && !evaluateMappingCondition(mapping.condition, event)) {
        continue;
      }
      
      try {
        // 构建工具参数
        const params = buildToolParams(mapping.params, event);
        
        // 调用工具（假设有一个全局工具调用接口）
        const toolResult = await invokeTool(mapping.toolName, params, mapping.async);
        
        // 更新映射统计
        mapping.callCount++;
        mapping.lastCallAt = new Date().toISOString();
        
        results.push({
          mappingId: mapping.id,
          toolName: mapping.toolName,
          params,
          result: toolResult,
          status: toolResult.success ? 'ok' : 'error'
        });
        
      } catch (e) {
        results.push({
          mappingId: mapping.id,
          toolName: mapping.toolName,
          error: e.message,
          status: 'error'
        });
      }
    }
    
    saveHooks();
    
    return {
      status: 'ok',
      triggered: results.length,
      results,
      time: Date.now() - start
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

/**
 * 评估映射条件
 * @param {object|string} condition - 条件
 * @param {object} event - 事件数据
 * @returns {boolean} - 是否满足条件
 */
function evaluateMappingCondition(condition, event) {
  try {
    if (typeof condition === 'function') {
      return condition(event);
    }
    if (typeof condition === 'string') {
      const fn = new Function('event', `return ${condition}`);
      return fn(event);
    }
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * 构建工具参数
 * @param {object} paramsTemplate - 参数模板
 * @param {object} event - 事件数据
 * @returns {object} - 工具参数
 */
function buildToolParams(paramsTemplate, event) {
  const params = {};
  
  for (const [key, value] of Object.entries(paramsTemplate)) {
    if (typeof value === 'string' && value.startsWith('event.')) {
      // 从事件中提取值
      const eventPath = value.substring(6);
      params[key] = getNestedValue(event, eventPath);
    } else if (typeof value === 'string' && value.startsWith('ctx.')) {
      // 从上下文中提取值（需要传入上下文）
      params[key] = value; // 占位符，实际需要从上下文获取
    } else {
      params[key] = value;
    }
  }
  
  return params;
}

/**
 * 获取嵌套值
 * @param {object} obj - 对象
 * @param {string} path - 路径（如 'task.id'）
 * @returns {any} - 值
 */
function getNestedValue(obj, path) {
  const keys = path.split('.');
  let current = obj;
  
  for (const key of keys) {
    if (current && typeof current === 'object' && key in current) {
      current = current[key];
    } else {
      return null;
    }
  }
  
  return current;
}

/**
 * 调用工具（占位符，实际需要根据iFlow的工具调用接口实现）
 * @param {string} toolName - 工具名称
 * @param {object} params - 工具参数
 * @param {boolean} async - 是否异步
 * @returns {object} - 工具结果
 */
async function invokeTool(toolName, params, async = true) {
  // 这里需要根据iFlow的工具调用接口实现
  // 目前返回模拟结果
  return {
    success: true,
    toolName,
    params,
    result: `Tool ${toolName} executed with params: ${JSON.stringify(params)}`,
    timestamp: new Date().toISOString()
  };
}

/**
 * 创建常用映射模板
 * @returns {object} - 映射模板
 */
function getMappingTemplates() {
  return {
    // 子代理完成时记录结果
    subagentCompleted: {
      hookType: 'subagentEnded',
      toolName: 'save_memory',
      condition: 'event.reason === "completed"',
      params: {
        fact: 'event.taskId completed: event.result',
        tags: ['subagent', 'completed']
      },
      priority: 10
    },
    
    // 子代理失败时记录错误
    subagentFailed: {
      hookType: 'subagentEnded',
      toolName: 'save_memory',
      condition: 'event.reason === "error" || event.reason === "failed"',
      params: {
        fact: 'event.taskId failed: event.error || event.notes',
        tags: ['subagent', 'error']
      },
      priority: 10
    },
    
    // 工具调用后记录日志
    toolCallLog: {
      hookType: 'afterToolCall',
      toolName: 'save_memory',
      condition: 'event.toolName === "run_shell_command"',
      params: {
        fact: 'Executed shell command: event.command',
        tags: ['tool', 'shell']
      },
      priority: 5
    },
    
    // 心跳时记录状态
    heartbeatStatus: {
      hookType: 'afterHeartbeat',
      toolName: 'save_memory',
      condition: 'event.error === null',
      params: {
        fact: 'Heartbeat completed successfully',
        tags: ['heartbeat', 'status']
      },
      priority: 3
    }
  };
}

// ============================================================
// 修改 trigger 函数以支持自动工具映射
// ============================================================

/**
 * 触发钩子（增强版）
 * @param {string} hookType - 钩子类型
 * @param {object} event - 事件数据
 * @returns {object} - 处理结果
 */
async function trigger(hookType, event = {}) {
  const start = Date.now();
  try {
    if (!HOOK_TYPES[hookType]) {
      return { status: 'ok', message: 'Unknown hook type, skipped', time: Date.now() - start };
    }
    
    const hooks = hooksRegistry[hookType] || [];
    const enabledHooks = hooks.filter(h => h.enabled);
    
    // 按优先级排序
    enabledHooks.sort((a, b) => a.priority - b.priority);
    
    const results = [];
    const toRemove = [];
    
    // 执行钩子回调
    for (const hook of enabledHooks) {
      // 检查条件
      if (hook.condition && !evaluateCondition(hook.condition, event)) {
        continue;
      }
      
      try {
        // 执行回调
        const callback = eval(`(${hook.callback})`);
        const hookDef = HOOK_TYPES[hookType];
        
        let result;
        if (hookDef.async) {
          result = await Promise.resolve(callback(event));
        } else {
          result = callback(event);
        }
        
        results.push({ hookId: hook.id, result, status: 'ok' });
        hook.callCount++;
        
        // 一次性钩子标记移除
        if (hook.once) {
          toRemove.push(hook.id);
        }
      } catch (e) {
        results.push({ hookId: hook.id, error: e.message, status: 'error' });
      }
    }
    
    // 移除一次性钩子
    if (toRemove.length > 0) {
      hooksRegistry[hookType] = hooks.filter(h => !toRemove.includes(h.id));
      saveHooks();
    }
    
    // 执行钩子到工具的映射（新增）
    const mappingResults = await executeToolMappings(hookType, event);
    
    return {
      status: 'ok',
      hooks: { results, triggered: results.length },
      tools: mappingResults,
      time: Date.now() - start
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ========== 模块导出 ==========
module.exports = {
  register,
  trigger,
  unregister,
  list,
  toggle,
  clear,
  getTypes,
  HOOK_TYPES,
  // 钩子到工具映射（新增）
  addToolMapping,
  removeToolMapping,
  listToolMappings,
  toggleToolMapping,
  executeToolMappings,
  getMappingTemplates,
  invokeTool
};

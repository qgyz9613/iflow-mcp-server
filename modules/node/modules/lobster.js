/**
 * iFlow Lobster Module v3.0
 * 完整工作流引擎 + 管道命令
 * 参考 OpenClaw 工作流设计，增强条件分支、并行执行、错误回滚
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');
const EventEmitter = require('events');

const WORKFLOW_DIR = path.join(__dirname, '..', 'workflow-data');
const CACHE_DIR = path.join(__dirname, '..', 'lobster-cache');
[WORKFLOW_DIR, CACHE_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// ============================================================
// 事件发射器
// ============================================================

const workflowEvents = new EventEmitter();

// ============================================================
// 管道命令
// ============================================================

// 解析谓词表达式
function parsePredicate(expr) {
  const m = expr.match(/^([a-zA-Z0-9_.]+)\s*(==|=|!=|<=|>=|<|>)\s*(.+)$/);
  if (!m) throw new Error(`Invalid where expression: ${expr}`);
  const [, fieldPath, op, rawValue] = m;

  let value = rawValue;
  if (rawValue === 'true') value = true;
  else if (rawValue === 'false') value = false;
  else if (rawValue === 'null') value = null;
  else if (!Number.isNaN(Number(rawValue)) && rawValue.trim() !== '') value = Number(rawValue);

  return { fieldPath, op: op === '=' ? '==' : op, value };
}

// 获取嵌套路径值
function getByPath(obj, fieldPath) {
  if (!fieldPath) return obj;
  const parts = fieldPath.split('.').filter(Boolean);
  let cur = obj;
  for (const p of parts) {
    if (cur === null || typeof cur !== 'object') return undefined;
    cur = cur[p];
  }
  return cur;
}

// 设置嵌套路径值
function setByPath(obj, fieldPath, value) {
  const parts = fieldPath.split('.').filter(Boolean);
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    const p = parts[i];
    if (!(p in cur)) cur[p] = {};
    cur = cur[p];
  }
  cur[parts[parts.length - 1]] = value;
}

// 比较函数
function compare(left, op, right) {
  switch (op) {
    case '==': return left == right;
    case '!=': return left != right;
    case '<': return left < right;
    case '<=': return left <= right;
    case '>': return left > right;
    case '>=': return left >= right;
    default: throw new Error(`Unsupported operator: ${op}`);
  }
}

// where - 过滤
function where(items, expr) {
  const start = Date.now();
  try {
    const pred = parsePredicate(expr);
    const results = items.filter(item => {
      const left = getByPath(item, pred.fieldPath);
      return compare(left, pred.op, pred.value);
    });
    return { status: 'ok', results, count: results.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// pick - 选择字段
function pick(items, fields) {
  const start = Date.now();
  try {
    const fieldList = typeof fields === 'string' ? fields.split(',').map(s => s.trim()).filter(Boolean) : fields;
    const results = items.map(item => {
      if (item === null || typeof item !== 'object') return item;
      const out = {};
      for (const f of fieldList) out[f] = item[f];
      return out;
    });
    return { status: 'ok', results, count: results.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// head - 取前N条
function head(items, n = 10) {
  const start = Date.now();
  try {
    const count = Number(n) || 10;
    const results = items.slice(0, count);
    return { status: 'ok', results, count: results.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// tail - 取后N条
function tail(items, n = 10) {
  const start = Date.now();
  try {
    const count = Number(n) || 10;
    const results = items.slice(-count);
    return { status: 'ok', results, count: results.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// map - 映射转换
function map(items, options = {}) {
  const start = Date.now();
  try {
    const { wrap, unwrap, assignments } = options;
    let results = items;

    if (unwrap) {
      results = items.map(item => getByPath(item, unwrap));
    } else if (wrap) {
      results = items.map(item => ({ [wrap]: item }));
    }

    if (assignments && Object.keys(assignments).length > 0) {
      results = results.map(item => {
        const newItem = { ...item };
        for (const [key, template] of Object.entries(assignments)) {
          // 支持 {{path}} 模板
          newItem[key] = template.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_, expr) => {
            const val = getByPath(item, expr.trim());
            return val !== undefined ? String(val) : '';
          });
        }
        return newItem;
      });
    }

    return { status: 'ok', results, count: results.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// sort - 排序
function sort(items, options = {}) {
  const start = Date.now();
  try {
    const { key, desc = false } = options;
    
    const indexed = items.map((item, idx) => ({ item, idx }));
    
    indexed.sort((a, b) => {
      const av = key ? getByPath(a.item, key) : a.item;
      const bv = key ? getByPath(b.item, key) : b.item;
      
      // null/undefined 排最后
      const aNull = av === undefined || av === null;
      const bNull = bv === undefined || bv === null;
      if (aNull && bNull) return 0;
      if (aNull) return 1;
      if (bNull) return -1;
      
      let c;
      if (typeof av === 'number' && typeof bv === 'number') {
        c = av - bv;
      } else {
        c = String(av).localeCompare(String(bv));
      }
      
      if (c !== 0) return desc ? -c : c;
      return a.idx - b.idx; // 稳定排序
    });

    const results = indexed.map(x => x.item);
    return { status: 'ok', results, count: results.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// dedupe - 去重
function dedupe(items, options = {}) {
  const start = Date.now();
  try {
    const { key } = options;
    const seen = new Set();
    const results = [];

    for (const item of items) {
      const id = key ? getByPath(item, key) : item;
      const k = JSON.stringify(id);
      if (seen.has(k)) continue;
      seen.add(k);
      results.push(item);
    }

    return { status: 'ok', results, count: results.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// groupBy - 分组
function groupBy(items, key) {
  const start = Date.now();
  try {
    const groups = {};
    
    for (const item of items) {
      const groupKey = getByPath(item, key);
      const k = JSON.stringify(groupKey);
      if (!groups[k]) groups[k] = { key: groupKey, items: [] };
      groups[k].items.push(item);
    }

    const results = Object.values(groups);
    return { status: 'ok', results, count: results.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// count - 计数
function count(items) {
  const start = Date.now();
  return { status: 'ok', count: items.length, time: Date.now() - start };
}

// sum - 求和
function sum(items, field) {
  const start = Date.now();
  try {
    const total = items.reduce((acc, item) => {
      const val = field ? getByPath(item, field) : item;
      return acc + (Number(val) || 0);
    }, 0);
    return { status: 'ok', sum: total, count: items.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// avg - 平均值
function avg(items, field) {
  const start = Date.now();
  try {
    if (items.length === 0) return { status: 'ok', avg: 0, count: 0, time: Date.now() - start };
    const total = items.reduce((acc, item) => {
      const val = field ? getByPath(item, field) : item;
      return acc + (Number(val) || 0);
    }, 0);
    return { status: 'ok', avg: total / items.length, sum: total, count: items.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// 工作流执行引擎 v3.0
// ============================================================

// 工作流状态
const WorkflowState = {
  PENDING: 'pending',
  RUNNING: 'running',
  PAUSED: 'paused',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CANCELLED: 'cancelled'
};

// 步骤状态
const StepState = {
  PENDING: 'pending',
  RUNNING: 'running',
  SKIPPED: 'skipped',
  COMPLETED: 'completed',
  FAILED: 'failed',
  ROLLED_BACK: 'rolled_back'
};

// 步骤类型
const StepType = {
  TASK: 'task',
  CONDITION: 'condition',
  PARALLEL: 'parallel',
  LOOP: 'loop',
  APPROVAL: 'approval',
  DELAY: 'delay',
  SUBWORKFLOW: 'subworkflow'
};

// 工作流执行器
class WorkflowExecutor {
  constructor() {
    this.executions = new Map();
    this.stepHandlers = new Map();
    this.rollbackHandlers = new Map();
    this.maxConcurrentSteps = 5;
    
    this._registerDefaultHandlers();
  }
  
  _registerDefaultHandlers() {
    // 任务步骤处理器
    this.stepHandlers.set(StepType.TASK, async (step, context) => {
      const { action, params = {} } = step;
      
      // 解析参数中的模板
      const resolvedParams = this._resolveParams(params, context);
      
      // 执行动作（这里需要根据实际动作类型调用相应工具）
      const result = await this._executeAction(action, resolvedParams);
      
      return { success: result.status === 'ok', result };
    });
    
    // 条件步骤处理器
    this.stepHandlers.set(StepType.CONDITION, async (step, context) => {
      const { branches, defaultBranch } = step;
      
      for (const branch of branches || []) {
        if (this._evaluateCondition(branch.condition, context)) {
          return { success: true, branch: branch.name, steps: branch.steps };
        }
      }
      
      if (defaultBranch) {
        return { success: true, branch: 'default', steps: defaultBranch };
      }
      
      return { success: true, skipped: true };
    });
    
    // 并行步骤处理器
    this.stepHandlers.set(StepType.PARALLEL, async (step, context) => {
      const { steps, failFast = true } = step;
      
      const results = [];
      const errors = [];
      
      // 分批执行
      const batches = this._chunk(steps, this.maxConcurrentSteps);
      
      for (const batch of batches) {
        const batchResults = await Promise.allSettled(
          batch.map(s => this._executeStep(s, context))
        );
        
        for (let i = 0; i < batchResults.length; i++) {
          const result = batchResults[i];
          const stepDef = batch[i];
          
          if (result.status === 'fulfilled') {
            results.push({ step: stepDef.name, result: result.value });
          } else {
            errors.push({ step: stepDef.name, error: result.reason.message });
            if (failFast) {
              return { success: false, errors, completedResults: results };
            }
          }
        }
      }
      
      return { success: errors.length === 0, results, errors };
    });
    
    // 循环步骤处理器
    this.stepHandlers.set(StepType.LOOP, async (step, context) => {
      const { items: itemsPath, itemVar = 'item', steps, maxIterations = 100 } = step;
      
      const items = getByPath(context, itemsPath) || [];
      const results = [];
      
      const limitedItems = items.slice(0, maxIterations);
      
      for (let i = 0; i < limitedItems.length; i++) {
        const loopContext = {
          ...context,
          [itemVar]: limitedItems[i],
          _index: i,
          _total: limitedItems.length
        };
        
        for (const subStep of steps) {
          const result = await this._executeStep(subStep, loopContext);
          results.push({ index: i, step: subStep.name, result });
          
          if (!result.success && step.failFast !== false) {
            return { success: false, results, lastIndex: i };
          }
        }
      }
      
      return { success: true, results, totalIterations: limitedItems.length };
    });
    
    // 审批步骤处理器
    this.stepHandlers.set(StepType.APPROVAL, async (step, context) => {
      const { prompt, approvers, timeout = 3600000 } = step;
      
      // 创建审批请求
      const approvalId = uuidv4();
      const approval = {
        id: approvalId,
        prompt: this._resolveTemplate(prompt, context),
        approvers,
        status: 'pending',
        created_at: new Date().toISOString(),
        expires_at: new Date(Date.now() + timeout).toISOString()
      };
      
      // 保存审批请求
      const approvalPath = path.join(WORKFLOW_DIR, `approval-${approvalId}.json`);
      fs.writeFileSync(approvalPath, JSON.stringify(approval, null, 2));
      
      // 发出事件
      workflowEvents.emit('approval:created', approval);
      
      return { success: true, approvalId, status: 'pending_approval' };
    });
    
    // 延迟步骤处理器
    this.stepHandlers.set(StepType.DELAY, async (step, context) => {
      const { duration, until } = step;
      
      let delayMs = 0;
      if (duration) {
        delayMs = this._parseDuration(duration);
      } else if (until) {
        const targetTime = new Date(until).getTime();
        delayMs = Math.max(0, targetTime - Date.now());
      }
      
      if (delayMs > 0) {
        await new Promise(resolve => setTimeout(resolve, Math.min(delayMs, 3600000)));
      }
      
      return { success: true, delayed: delayMs };
    });
    
    // 子工作流步骤处理器
    this.stepHandlers.set(StepType.SUBWORKFLOW, async (step, context) => {
      const { workflow: subWorkflowName, params = {} } = step;
      
      const resolvedParams = this._resolveParams(params, context);
      
      // 执行子工作流
      const result = await run(subWorkflowName, resolvedParams);
      
      return { success: result.status === 'ok', subExecution: result.execution };
    });
  }
  
  _chunk(array, size) {
    const chunks = [];
    for (let i = 0; i < array.length; i += size) {
      chunks.push(array.slice(i, i + size));
    }
    return chunks;
  }
  
  _parseDuration(duration) {
    if (typeof duration === 'number') return duration;
    
    const match = duration.match(/^(\d+)(ms|s|m|h|d)$/);
    if (!match) return 0;
    
    const [, value, unit] = match;
    const multipliers = { ms: 1, s: 1000, m: 60000, h: 3600000, d: 86400000 };
    return parseInt(value) * multipliers[unit];
  }
  
  _resolveParams(params, context) {
    const resolved = {};
    for (const [key, value] of Object.entries(params)) {
      if (typeof value === 'string') {
        resolved[key] = this._resolveTemplate(value, context);
      } else if (typeof value === 'object' && value !== null) {
        resolved[key] = this._resolveParams(value, context);
      } else {
        resolved[key] = value;
      }
    }
    return resolved;
  }
  
  _resolveTemplate(template, context) {
    return template.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_, expr) => {
      const val = getByPath(context, expr.trim());
      return val !== undefined ? String(val) : '';
    });
  }
  
  _evaluateCondition(condition, context) {
    if (typeof condition === 'function') {
      return condition(context);
    }
    if (typeof condition === 'string') {
      try {
        const fn = new Function('ctx', `return ${condition}`);
        return fn(context);
      } catch {
        return false;
      }
    }
    if (typeof condition === 'object') {
      // 支持 { field: { op: value } } 格式
      for (const [field, rule] of Object.entries(condition)) {
        const actualValue = getByPath(context, field);
        for (const [op, expectedValue] of Object.entries(rule)) {
          if (!compare(actualValue, op, expectedValue)) {
            return false;
          }
        }
      }
      return true;
    }
    return true;
  }
  
  async _executeAction(action, params) {
    // 这里需要根据实际动作类型调用相应工具
    // 目前返回模拟结果
    return {
      status: 'ok',
      action,
      params,
      result: `Action ${action} executed`,
      timestamp: new Date().toISOString()
    };
  }
  
  async _executeStep(step, context) {
    const handler = this.stepHandlers.get(step.type || StepType.TASK);
    if (!handler) {
      return { success: false, error: `Unknown step type: ${step.type}` };
    }
    
    try {
      const result = await handler(step, context);
      return result;
    } catch (e) {
      return { success: false, error: e.message };
    }
  }
  
  // 执行工作流
  async execute(workflowDef, args = {}) {
    const executionId = uuidv4();
    const start = Date.now();
    
    const execution = {
      id: executionId,
      workflow: workflowDef.name || 'anonymous',
      workflowDef,
      args,
      status: WorkflowState.RUNNING,
      currentStep: 0,
      steps: [],
      context: { ...args },
      snapshot: [], // 用于回滚
      started_at: new Date().toISOString(),
      completed_at: null,
      result: null,
      error: null
    };
    
    this.executions.set(executionId, execution);
    
    // 保存初始状态
    this._saveExecution(execution);
    
    try {
      // 发出事件
      workflowEvents.emit('workflow:started', execution);
      
      // 执行步骤
      for (let i = 0; i < (workflowDef.steps || []).length; i++) {
        const step = workflowDef.steps[i];
        execution.currentStep = i;
        
        // 记录快照（用于回滚）
        execution.snapshot.push({
          stepIndex: i,
          stepName: step.name,
          contextSnapshot: JSON.parse(JSON.stringify(execution.context)),
          timestamp: new Date().toISOString()
        });
        
        // 检查条件跳过
        if (step.condition && !this._evaluateCondition(step.condition, execution.context)) {
          execution.steps.push({
            name: step.name,
            status: StepState.SKIPPED,
            reason: 'condition_not_met'
          });
          continue;
        }
        
        // 发出步骤开始事件
        workflowEvents.emit('step:started', { executionId, step });
        
        // 执行步骤
        const stepResult = await this._executeStep(step, execution.context);
        
        const stepRecord = {
          name: step.name,
          type: step.type || StepType.TASK,
          status: stepResult.success ? StepState.COMPLETED : StepState.FAILED,
          result: stepResult,
          started_at: new Date().toISOString(),
          completed_at: new Date().toISOString()
        };
        
        execution.steps.push(stepRecord);
        
        // 更新上下文
        if (stepResult.success && stepResult.result && step.saveTo) {
          setByPath(execution.context, step.saveTo, stepResult.result);
        }
        
        // 保存执行状态
        this._saveExecution(execution);
        
        // 发出步骤完成事件
        workflowEvents.emit('step:completed', { executionId, step, stepResult });
        
        // 处理失败
        if (!stepResult.success && step.continueOnError !== true) {
          execution.status = WorkflowState.FAILED;
          execution.error = stepResult.error || 'Step failed';
          
          // 尝试回滚
          if (workflowDef.rollbackOnError !== false) {
            await this._rollback(execution);
          }
          
          break;
        }
      }
      
      // 设置最终状态
      if (execution.status === WorkflowState.RUNNING) {
        execution.status = WorkflowState.COMPLETED;
      }
      
      execution.completed_at = new Date().toISOString();
      execution.result = execution.context;
      
    } catch (e) {
      execution.status = WorkflowState.FAILED;
      execution.error = e.message;
      execution.completed_at = new Date().toISOString();
      
      // 尝试回滚
      if (workflowDef.rollbackOnError !== false) {
        await this._rollback(execution);
      }
    }
    
    // 保存最终状态
    this._saveExecution(execution);
    
    // 发出事件
    workflowEvents.emit('workflow:completed', execution);
    
    // 清理
    this.executions.delete(executionId);
    
    return {
      status: execution.status === WorkflowState.COMPLETED ? 'ok' : 'error',
      execution,
      time: Date.now() - start
    };
  }
  
  async _rollback(execution) {
    // 按相反顺序执行回滚
    const completedSteps = execution.steps.filter(s => s.status === StepState.COMPLETED);
    
    for (let i = completedSteps.length - 1; i >= 0; i--) {
      const step = completedSteps[i];
      const rollbackHandler = this.rollbackHandlers.get(step.name);
      
      if (rollbackHandler) {
        try {
          await rollbackHandler(execution.context);
          step.status = StepState.ROLLED_BACK;
          workflowEvents.emit('step:rolled_back', { executionId: execution.id, step });
        } catch (e) {
          workflowEvents.emit('rollback:failed', { executionId: execution.id, step, error: e.message });
        }
      }
    }
  }
  
  _saveExecution(execution) {
    const filePath = path.join(WORKFLOW_DIR, `${execution.id}.json`);
    fs.writeFileSync(filePath, JSON.stringify(execution, null, 2));
  }
  
  // 注册自定义步骤处理器
  registerStepHandler(stepType, handler, rollbackHandler = null) {
    this.stepHandlers.set(stepType, handler);
    if (rollbackHandler) {
      this.rollbackHandlers.set(stepType, rollbackHandler);
    }
  }
  
  // 注册回滚处理器
  registerRollbackHandler(stepName, handler) {
    this.rollbackHandlers.set(stepName, handler);
  }
}

// 创建全局执行器实例
const executor = new WorkflowExecutor();

// ============================================================
// 工作流 API
// ============================================================

// 执行工作流
async function run(workflow, args = {}) {
  const start = Date.now();
  try {
    // 支持工作流名称、YAML 定义或步骤数组
    let workflowDef = workflow;
    
    // 如果是字符串，尝试加载工作流文件
    if (typeof workflow === 'string') {
      const workflowPath = path.join(WORKFLOW_DIR, `${workflow}.yaml`);
      if (fs.existsSync(workflowPath)) {
        const yaml = require('js-yaml'); // 可选依赖
        workflowDef = yaml.load(fs.readFileSync(workflowPath, 'utf8'));
      } else {
        // 尝试 JSON
        const jsonPath = path.join(WORKFLOW_DIR, `${workflow}.json`);
        if (fs.existsSync(jsonPath)) {
          workflowDef = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
        } else {
          return { status: 'error', message: 'Workflow not found', time: Date.now() - start };
        }
      }
    }
    
    // 使用执行器执行
    return await executor.execute(workflowDef, args);
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// 恢复工作流
async function resume(token, approved = true) {
  const start = Date.now();
  try {
    const filePath = path.join(WORKFLOW_DIR, `${token}.json`);
    
    if (!fs.existsSync(filePath)) {
      return { status: 'error', message: 'Workflow not found', time: Date.now() - start };
    }
    
    const execution = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    
    // 处理审批
    if (execution.status === 'pending_approval') {
      execution.status = approved ? WorkflowState.RUNNING : WorkflowState.CANCELLED;
      workflowEvents.emit('approval:responded', { executionId: token, approved });
    } else {
      execution.status = approved ? WorkflowState.RUNNING : WorkflowState.CANCELLED;
    }
    
    execution.resumed_at = new Date().toISOString();
    fs.writeFileSync(filePath, JSON.stringify(execution, null, 2));
    
    return { status: 'ok', execution, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// 暂停工作流
async function pause(workflowId) {
  const start = Date.now();
  try {
    const filePath = path.join(WORKFLOW_DIR, `${workflowId}.json`);
    
    if (!fs.existsSync(filePath)) {
      return { status: 'error', message: 'Workflow not found', time: Date.now() - start };
    }
    
    const execution = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    execution.status = WorkflowState.PAUSED;
    execution.paused_at = new Date().toISOString();
    
    fs.writeFileSync(filePath, JSON.stringify(execution, null, 2));
    
    workflowEvents.emit('workflow:paused', execution);
    
    return { status: 'ok', execution, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// 取消工作流
async function cancel(workflowId) {
  const start = Date.now();
  try {
    const filePath = path.join(WORKFLOW_DIR, `${workflowId}.json`);
    
    if (!fs.existsSync(filePath)) {
      return { status: 'error', message: 'Workflow not found', time: Date.now() - start };
    }
    
    const execution = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    execution.status = WorkflowState.CANCELLED;
    execution.cancelled_at = new Date().toISOString();
    
    fs.writeFileSync(filePath, JSON.stringify(execution, null, 2));
    
    workflowEvents.emit('workflow:cancelled', execution);
    
    return { status: 'ok', execution, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// 回滚工作流
async function rollback(workflowId) {
  const start = Date.now();
  try {
    const filePath = path.join(WORKFLOW_DIR, `${workflowId}.json`);
    
    if (!fs.existsSync(filePath)) {
      return { status: 'error', message: 'Workflow not found', time: Date.now() - start };
    }
    
    const execution = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    
    await executor._rollback(execution);
    
    execution.status = WorkflowState.FAILED;
    execution.rolled_back_at = new Date().toISOString();
    
    fs.writeFileSync(filePath, JSON.stringify(execution, null, 2));
    
    return { status: 'ok', execution, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// 列出工作流
function list(options = {}) {
  const start = Date.now();
  try {
    const files = fs.readdirSync(WORKFLOW_DIR).filter(f => f.endsWith('.json') && !f.startsWith('approval-'));
    
    const workflows = files.map(f => {
      try {
        const wf = JSON.parse(fs.readFileSync(path.join(WORKFLOW_DIR, f), 'utf8'));
        return {
          id: wf.id,
          name: wf.workflow,
          status: wf.status,
          started_at: wf.started_at,
          completed_at: wf.completed_at,
          stepCount: wf.steps?.length || 0,
          error: wf.error
        };
      } catch {
        return null;
      }
    }).filter(Boolean);
    
    // 支持过滤
    let results = workflows;
    if (options.status) {
      results = results.filter(w => w.status === options.status);
    }
    if (options.name) {
      results = results.filter(w => w.name.includes(options.name));
    }
    
    return { status: 'ok', workflows: results, total: results.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// 获取状态
function state(workflowName = null) {
  const start = Date.now();
  try {
    const files = fs.readdirSync(WORKFLOW_DIR).filter(f => f.endsWith('.json') && !f.startsWith('approval-'));
    
    if (workflowName) {
      const matching = files.filter(f => {
        try {
          const wf = JSON.parse(fs.readFileSync(path.join(WORKFLOW_DIR, f), 'utf8'));
          return wf.workflow === workflowName;
        } catch {
          return false;
        }
      });
      
      return { status: 'ok', count: matching.length, time: Date.now() - start };
    }
    
    const statuses = files.map(f => {
      try {
        const wf = JSON.parse(fs.readFileSync(path.join(WORKFLOW_DIR, f), 'utf8'));
        return { id: wf.id, workflow: wf.workflow, status: wf.status, error: wf.error };
      } catch {
        return null;
      }
    }).filter(Boolean);
    
    return { status: 'ok', workflows: statuses, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// 添加步骤结果
function addStep(workflowId, step, result) {
  const start = Date.now();
  try {
    const filePath = path.join(WORKFLOW_DIR, `${workflowId}.json`);
    
    if (!fs.existsSync(filePath)) {
      return { status: 'error', message: 'Workflow not found', time: Date.now() - start };
    }
    
    const execution = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    execution.steps.push({
      name: step.name || step,
      type: step.type || StepType.TASK,
      status: result.success ? StepState.COMPLETED : StepState.FAILED,
      result,
      timestamp: new Date().toISOString()
    });
    
    // 更新上下文
    if (result && typeof result === 'object') {
      execution.context = { ...execution.context, ...result };
    }
    
    fs.writeFileSync(filePath, JSON.stringify(execution, null, 2));
    
    return { status: 'ok', execution, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// 审批流程
// ============================================================

// 创建审批请求
function approve(options = {}) {
  const start = Date.now();
  try {
    const { prompt = 'Approve?', items = [], preview = null, timeout = 3600000 } = options;
    
    const approvalId = uuidv4();
    const approval = {
      id: approvalId,
      type: 'approval_request',
      prompt,
      items,
      preview,
      status: 'pending',
      created_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + timeout).toISOString(),
      response: null
    };
    
    const filePath = path.join(WORKFLOW_DIR, `approval-${approvalId}.json`);
    fs.writeFileSync(filePath, JSON.stringify(approval, null, 2));
    
    workflowEvents.emit('approval:created', approval);
    
    return { 
      status: 'ok', 
      approval,
      message: 'Approval request created. Use respond() to answer.',
      time: Date.now() - start 
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// 响应审批
function respond(approvalId, response, notes = '') {
  const start = Date.now();
  try {
    const filePath = path.join(WORKFLOW_DIR, `approval-${approvalId}.json`);
    
    if (!fs.existsSync(filePath)) {
      return { status: 'error', message: 'Approval not found', time: Date.now() - start };
    }
    
    const approval = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    
    if (approval.status !== 'pending') {
      return { status: 'error', message: `Approval already ${approval.status}`, time: Date.now() - start };
    }
    
    if (new Date() > new Date(approval.expires_at)) {
      approval.status = 'expired';
    } else {
      approval.status = response ? 'approved' : 'rejected';
    }
    
    approval.response = response;
    approval.notes = notes;
    approval.responded_at = new Date().toISOString();
    
    fs.writeFileSync(filePath, JSON.stringify(approval, null, 2));
    
    workflowEvents.emit('approval:responded', { approvalId, response });
    
    return { status: 'ok', approval, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// 管道执行器
// ============================================================

// 执行管道
function pipe(items, commands) {
  const start = Date.now();
  try {
    let data = Array.isArray(items) ? items : [items];
    const logs = [];
    
    for (const cmd of commands) {
      const { command, args = {} } = typeof cmd === 'string' ? { command: cmd } : cmd;
      const cmdStart = Date.now();
      
      switch (command) {
        case 'where':
          data = where(data, args.expr || args._?.[0]).results || [];
          break;
        case 'pick':
          data = pick(data, args.fields || args._?.[0]).results || [];
          break;
        case 'head':
          data = head(data, args.n || args._?.[0]).results || [];
          break;
        case 'tail':
          data = tail(data, args.n || args._?.[0]).results || [];
          break;
        case 'map':
          data = map(data, args).results || [];
          break;
        case 'sort':
          data = sort(data, args).results || [];
          break;
        case 'dedupe':
          data = dedupe(data, args).results || [];
          break;
        case 'groupBy':
          data = groupBy(data, args.key).results || [];
          break;
        case 'count':
          data = [count(data)];
          break;
        case 'sum':
          data = [sum(data, args.field)];
          break;
        case 'avg':
          data = [avg(data, args.field)];
          break;
        default:
          throw new Error(`Unknown command: ${command}`);
      }
      
      logs.push({
        command,
        inputCount: data.length,
        time: Date.now() - cmdStart
      });
    }
    
    return { 
      status: 'ok', 
      results: data, 
      count: data.length,
      logs,
      time: Date.now() - start 
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// 事件订阅
// ============================================================

function on(event, handler) {
  workflowEvents.on(event, handler);
  return { status: 'ok', event };
}

function off(event, handler) {
  workflowEvents.off(event, handler);
  return { status: 'ok', event };
}

function once(event, handler) {
  workflowEvents.once(event, handler);
  return { status: 'ok', event };
}

// ============================================================
// 注册自定义步骤处理器
// ============================================================

function registerStepHandler(stepType, handler, rollbackHandler = null) {
  executor.registerStepHandler(stepType, handler, rollbackHandler);
  return { status: 'ok', stepType };
}

function registerRollbackHandler(stepName, handler) {
  executor.registerRollbackHandler(stepName, handler);
  return { status: 'ok', stepName };
}

// ============================================================
// 模块导出
// ============================================================

module.exports = {
  // 管道命令
  where,
  pick,
  head,
  tail,
  map,
  sort,
  dedupe,
  groupBy,
  count,
  sum,
  avg,
  pipe,
  
  // 工作流
  run,
  resume,
  pause,
  cancel,
  rollback,
  list,
  state,
  addStep,
  
  // 审批
  approve,
  respond,
  
  // 事件
  on,
  off,
  once,
  workflowEvents,
  
  // 自定义步骤
  registerStepHandler,
  registerRollbackHandler,
  
  // 常量
  WorkflowState,
  StepState,
  StepType,
  
  // 执行器
  executor
};

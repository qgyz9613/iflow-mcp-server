/**
 * iFlow SubAgent Module - 多代理协同系统
 * 升级：协调者智能委派 + 并行执行 + 努力扩展
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');

const SUBAGENT_DIR = path.join(__dirname, '..', 'subagent-data');
const ARTIFACTS_DIR = path.join(SUBAGENT_DIR, 'artifacts');
[SUBAGENT_DIR, ARTIFACTS_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// ========== 努力扩展规则 ==========
const EFFORT_SCALING = {
  simple: { subagents: 1, toolCalls: '3-10', strategy: 'sequential' },
  moderate: { subagents: '2-4', toolCalls: '10-15', strategy: 'parallel' },
  complex: { subagents: '5-10', toolCalls: '15+', strategy: 'parallel' }
};

// ========== 任务复杂度评估 ==========
function assessComplexity(query) {
  const factors = {
    breadth: (query.match(/所有|全部|每个|列出/g) || []).length,
    depth: (query.match(/详细|深入|分析|对比/g) || []).length,
    multiple: (query.match(/和|以及|同时|分别/g) || []).length,
    parallel: (query.match(/并行|同时|不同/g) || []).length
  };
  
  const score = Object.values(factors).reduce((a, b) => a + b, 0);
  
  if (score <= 1) return 'simple';
  if (score <= 3) return 'moderate';
  return 'complex';
}

// ========== 协调者：创建委派计划 ==========
function plan(tasks, options = {}) {
  const start = Date.now();
  try {
    const planId = uuidv4();
    
    // 评估复杂度并确定策略
    const query = options.query || tasks.map(t => t.name).join(' ');
    const complexity = options.complexity || assessComplexity(query);
    const scaling = EFFORT_SCALING[complexity];
    
    const plan = {
      id: planId,
      query,
      complexity,
      scaling,
      strategy: options.strategy || scaling.strategy,
      reviewEnabled: options.reviewEnabled !== false,
      status: 'pending',
      created_at: new Date().toISOString(),
      expectedSubagents: typeof scaling.subagents === 'string' 
        ? parseInt(scaling.subagents.split('-')[1]) 
        : scaling.subagents,
      tasks: tasks.map((t, i) => ({
        id: `${planId}-${i}`,
        name: t.name,
        // 详细任务描述（关键改进）
        description: t.description || t.name,
        objective: t.objective || `完成 ${t.name}`,
        outputFormat: t.outputFormat || 'summary',
        tools: t.tools || ['default'],
        sources: t.sources || [],
        boundaries: t.boundaries || '专注于指定任务，不重复其他代理的工作',
        priority: t.priority || 'medium',
        status: 'pending',
        agentType: t.agentType || 'general-purpose',
        model: t.model || 'default',  // 支持多模型路由
        result: null,
        artifactPath: null  // 子代理输出文件路径
      }))
    };
    
    const filePath = path.join(SUBAGENT_DIR, `plan-${planId}.json`);
    fs.writeFileSync(filePath, JSON.stringify(plan, null, 2));
    
    // 保存计划到记忆（防止上下文溢出）
    const memoryPath = path.join(SUBAGENT_DIR, `memory-${planId}.json`);
    fs.writeFileSync(memoryPath, JSON.stringify({
      planId,
      query,
      strategy: plan.strategy,
      taskCount: plan.tasks.length,
      createdAt: plan.created_at
    }, null, 2));
    
    return { 
      status: 'ok', 
      plan,
      message: `计划创建成功，复杂度: ${complexity}，策略: ${plan.strategy}，预期子代理: ${plan.expectedSubagents}`,
      time: Date.now() - start 
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ========== 委派任务给子代理 ==========
function delegate(taskId, options = {}) {
  const start = Date.now();
  try {
    const files = fs.readdirSync(SUBAGENT_DIR).filter(f => f.startsWith('plan-'));
    
    for (const f of files) {
      const plan = JSON.parse(fs.readFileSync(path.join(SUBAGENT_DIR, f), 'utf8'));
      const task = plan.tasks.find(t => t.id === taskId);
      
      if (task) {
        task.status = 'in_progress';
        task.agentType = options.agentType || task.agentType;
        task.model = options.model || task.model;
        task.context = options.context;
        task.started_at = new Date().toISOString();
        
        // 创建子代理工件目录
        const artifactDir = path.join(ARTIFACTS_DIR, taskId);
        if (!fs.existsSync(artifactDir)) fs.mkdirSync(artifactDir, { recursive: true });
        task.artifactPath = artifactDir;
        
        fs.writeFileSync(path.join(SUBAGENT_DIR, f), JSON.stringify(plan, null, 2));
        
        // 生成委派指令（详细描述）
        const delegation = {
          taskId,
          instruction: generateDelegationInstruction(task),
          agentType: task.agentType,
          model: task.model,
          artifactPath: task.artifactPath
        };
        
        return { 
          status: 'ok', 
          task, 
          delegation,
          planId: plan.id, 
          time: Date.now() - start 
        };
      }
    }
    
    return { status: 'error', message: 'Task not found', time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ========== 生成委派指令（关键：详细描述） ==========
function generateDelegationInstruction(task) {
  return `
## 任务目标
${task.objective}

## 输出格式
${task.outputFormat}

## 可用工具
${task.tools.join(', ')}

## 信息源
${task.sources.length > 0 ? task.sources.join(', ') : '自动选择'}

## 任务边界
${task.boundaries}

## 注意事项
- 不要重复其他代理已完成的工作
- 使用 ${task.tools.length} 个工具完成任务
- 将输出保存到 ${task.artifactPath}
`;
}

// ========== 报告结果 ==========
function report(taskId, status, result = null, notes = '') {
  const start = Date.now();
  try {
    const files = fs.readdirSync(SUBAGENT_DIR).filter(f => f.startsWith('plan-'));
    
    for (const f of files) {
      const plan = JSON.parse(fs.readFileSync(path.join(SUBAGENT_DIR, f), 'utf8'));
      const task = plan.tasks.find(t => t.id === taskId);
      
      if (task) {
        task.status = status;
        task.result = result;
        task.notes = notes;
        task.completed_at = new Date().toISOString();
        
        // 如果有大型结果，保存到工件文件
        if (result && typeof result === 'string' && result.length > 1000) {
          const resultPath = path.join(task.artifactPath || ARTIFACTS_DIR, `result-${taskId}.json`);
          fs.writeFileSync(resultPath, JSON.stringify({
            taskId,
            status,
            result,
            notes,
            completedAt: task.completed_at
          }, null, 2));
          task.resultPath = resultPath;
          task.result = `[结果已保存到 ${resultPath}]`;
        }
        
        fs.writeFileSync(path.join(SUBAGENT_DIR, f), JSON.stringify(plan, null, 2));
        
        // 更新子代理上下文
        const run = Array.from(subagentRuns.values()).find(r => r.taskId === taskId);
        if (run && run.contextId) {
          addMessage(run.contextId, {
            role: 'system',
            content: `任务${status}: ${notes || ''}`,
            metadata: { status, resultPath: task.resultPath }
          });
          
          if (status === 'completed' && result) {
            addResult(run.contextId, result);
          } else if (status === 'failed' || status === 'error') {
            addError(run.contextId, { status, notes });
          }
          
          persistState();
        }
        
        return { status: 'ok', task, time: Date.now() - start };
      }
    }
    
    return { status: 'error', message: 'Task not found', time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ========== 并行委派多个子代理 ==========
function delegateParallel(planId, taskIds = null) {
  const start = Date.now();
  try {
    const filePath = path.join(SUBAGENT_DIR, `plan-${planId}.json`);
    
    if (!fs.existsSync(filePath)) {
      return { status: 'error', message: 'Plan not found', time: Date.now() - start };
    }
    
    const plan = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    
    // 获取待执行任务
    const pendingTasks = taskIds 
      ? plan.tasks.filter(t => taskIds.includes(t.id) && t.status === 'pending')
      : plan.tasks.filter(t => t.status === 'pending');
    
    if (pendingTasks.length === 0) {
      return { status: 'ok', message: 'No pending tasks', plan, time: Date.now() - start };
    }
    
    // 并行委派
    const delegations = [];
    for (const task of pendingTasks) {
      const result = delegate(task.id);
      if (result.status === 'ok') {
        delegations.push(result.delegation);
      }
    }
    
    return { 
      status: 'ok', 
      delegations,
      count: delegations.length,
      plan,
      time: Date.now() - start 
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ========== 查询状态 ==========
function status(options = {}) {
  const start = Date.now();
  try {
    if (options.taskId) {
      const files = fs.readdirSync(SUBAGENT_DIR).filter(f => f.startsWith('plan-'));
      
      for (const f of files) {
        const plan = JSON.parse(fs.readFileSync(path.join(SUBAGENT_DIR, f), 'utf8'));
        const task = plan.tasks.find(t => t.id === options.taskId);
        if (task) {
          return { status: 'ok', task, planId: plan.id, time: Date.now() - start };
        }
      }
      
      return { status: 'error', message: 'Task not found', time: Date.now() - start };
    }
    
    if (options.planId) {
      const filePath = path.join(SUBAGENT_DIR, `plan-${options.planId}.json`);
      
      if (!fs.existsSync(filePath)) {
        return { status: 'error', message: 'Plan not found', time: Date.now() - start };
      }
      
      const plan = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      
      // 计算进度
      const completed = plan.tasks.filter(t => t.status === 'completed').length;
      const progress = `${completed}/${plan.tasks.length}`;
      
      return { status: 'ok', plan, progress, time: Date.now() - start };
    }
    
    // 列出所有计划
    const files = fs.readdirSync(SUBAGENT_DIR).filter(f => f.startsWith('plan-'));
    const plans = files.map(f => {
      try {
        const plan = JSON.parse(fs.readFileSync(path.join(SUBAGENT_DIR, f), 'utf8'));
        const completed = plan.tasks.filter(t => t.status === 'completed').length;
        return { 
          id: plan.id, 
          query: plan.query,
          complexity: plan.complexity,
          strategy: plan.strategy, 
          status: plan.status, 
          progress: `${completed}/${plan.tasks.length}`,
          taskCount: plan.tasks.length 
        };
      } catch {
        return null;
      }
    }).filter(Boolean);
    
    return { status: 'ok', plans, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ========== 审查任务结果 ==========
function review(taskId, options = {}) {
  const start = Date.now();
  try {
    const files = fs.readdirSync(SUBAGENT_DIR).filter(f => f.startsWith('plan-'));
    
    for (const f of files) {
      const plan = JSON.parse(fs.readFileSync(path.join(SUBAGENT_DIR, f), 'utf8'));
      const task = plan.tasks.find(t => t.id === taskId);
      
      if (task) {
        // 审查标准
        const criteria = options.criteria || ['correctness', 'completeness', 'quality'];
        const scores = {};
        let totalScore = 0;
        
        for (const c of criteria) {
          // 模拟审查评分（实际应该调用 LLM）
          scores[c] = options.scores?.[c] || 0.85;
          totalScore += scores[c];
        }
        
        const avgScore = totalScore / criteria.length;
        const passed = avgScore >= (options.threshold || 0.7);
        
        const reviewResult = {
          taskId,
          criteria,
          scores,
          avgScore,
          passed,
          notes: options.notes || (passed ? '审查通过' : '需要改进'),
          timestamp: new Date().toISOString()
        };
        
        // 保存审查结果
        task.review = reviewResult;
        fs.writeFileSync(path.join(SUBAGENT_DIR, f), JSON.stringify(plan, null, 2));
        
        return { status: 'ok', review: reviewResult, task, time: Date.now() - start };
      }
    }
    
    return { status: 'error', message: 'Task not found', time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ========== 聚合结果 ==========
function aggregate(planId, format = 'summary') {
  const start = Date.now();
  try {
    const filePath = path.join(SUBAGENT_DIR, `plan-${planId}.json`);
    
    if (!fs.existsSync(filePath)) {
      return { status: 'error', message: 'Plan not found', time: Date.now() - start };
    }
    
    const plan = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    
    const completed = plan.tasks.filter(t => t.status === 'completed');
    const failed = plan.tasks.filter(t => t.status === 'failed');
    const pending = plan.tasks.filter(t => t.status === 'pending');
    const inProgress = plan.tasks.filter(t => t.status === 'in_progress');
    
    // 收集所有结果
    const results = [];
    for (const task of completed) {
      let result = task.result;
      
      // 如果结果保存到文件，读取它
      if (task.resultPath && fs.existsSync(task.resultPath)) {
        try {
          result = JSON.parse(fs.readFileSync(task.resultPath, 'utf8'));
        } catch (e) {}
      }
      
      results.push({
        taskId: task.id,
        name: task.name,
        result
      });
    }
    
    const summary = {
      planId,
      query: plan.query,
      complexity: plan.complexity,
      total: plan.tasks.length,
      completed: completed.length,
      failed: failed.length,
      pending: pending.length,
      inProgress: inProgress.length,
      results
    };
    
    if (format === 'detailed') {
      summary.tasks = plan.tasks;
    }
    
    // 保存聚合结果
    const aggregatePath = path.join(SUBAGENT_DIR, `aggregate-${planId}.json`);
    fs.writeFileSync(aggregatePath, JSON.stringify(summary, null, 2));
    summary.aggregatePath = aggregatePath;
    
    return { status: 'ok', summary, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ========== 取消任务/计划 ==========
function cancel(options = {}) {
  const start = Date.now();
  try {
    if (options.taskId) {
      return report(options.taskId, 'cancelled', null, options.reason || 'Cancelled by user');
    }
    
    if (options.planId) {
      const filePath = path.join(SUBAGENT_DIR, `plan-${options.planId}.json`);
      
      if (!fs.existsSync(filePath)) {
        return { status: 'error', message: 'Plan not found', time: Date.now() - start };
      }
      
      const plan = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      plan.status = 'cancelled';
      plan.cancelled_at = new Date().toISOString();
      plan.cancel_reason = options.reason;
      
      plan.tasks.forEach(t => {
        if (t.status === 'pending' || t.status === 'in_progress') {
          t.status = 'cancelled';
        }
      });
      
      fs.writeFileSync(filePath, JSON.stringify(plan, null, 2));
      
      return { status: 'ok', plan, time: Date.now() - start };
    }
    
    return { status: 'error', message: 'No taskId or planId provided', time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ========== 获取任务模板 ==========
function templates() {
  const start = Date.now();
  
  const templates = [
    { 
      name: 'code_review', 
      tasks: [
        { name: 'analyze', description: '分析代码结构和依赖', objective: '识别代码中的模式和潜在问题' },
        { name: 'review', description: '代码质量审查', objective: '检查代码风格、安全和性能' },
        { name: 'report', description: '生成审查报告', objective: '汇总发现并提供建议' }
      ], 
      strategy: 'sequential',
      complexity: 'moderate'
    },
    { 
      name: 'parallel_research', 
      tasks: [
        { name: 'research_a', description: '研究方向A', objective: '探索主题的一个方面' },
        { name: 'research_b', description: '研究方向B', objective: '探索主题的另一个方面' },
        { name: 'aggregate', description: '汇总研究结果', objective: '综合所有发现' }
      ], 
      strategy: 'parallel',
      complexity: 'moderate'
    },
    { 
      name: 'feature_development', 
      tasks: [
        { name: 'design', description: '功能设计', objective: '定义功能和接口' },
        { name: 'implement', description: '代码实现', objective: '编写功能代码' },
        { name: 'test', description: '测试验证', objective: '确保功能正确' },
        { name: 'review', description: '代码审查', objective: '质量把关' }
      ], 
      strategy: 'review',
      complexity: 'complex'
    },
    {
      name: 'trading_analysis',
      tasks: [
        { name: 'market_scan', description: '市场扫描', objective: '识别交易机会', tools: ['panwatch', 'quotes'] },
        { name: 'risk_check', description: '风险检查', objective: '评估止损止盈', tools: ['holding', 'analysis'] },
        { name: 'execute', description: '执行交易', objective: '下单或调整仓位', tools: ['easyths'] }
      ],
      strategy: 'sequential',
      complexity: 'simple'
    }
  ];
  
  return { status: 'ok', templates, effortScaling: EFFORT_SCALING, time: Date.now() - start };
}

// ========== 心跳集成：自动委派 ==========
function autoDelegate(callback) {
  const start = Date.now();
  try {
    // 查找未完成的计划
    const files = fs.readdirSync(SUBAGENT_DIR).filter(f => f.startsWith('plan-'));
    
    for (const f of files) {
      const plan = JSON.parse(fs.readFileSync(path.join(SUBAGENT_DIR, f), 'utf8'));
      
      if (plan.status !== 'pending') continue;
      
      // 自动委派待执行任务
      const pendingTasks = plan.tasks.filter(t => t.status === 'pending');
      
      if (pendingTasks.length > 0 && plan.strategy === 'parallel') {
        // 并行委派
        const result = delegateParallel(plan.id);
        if (callback) callback(result);
        return { status: 'ok', action: 'parallel_delegation', ...result, time: Date.now() - start };
      } else if (pendingTasks.length > 0) {
        // 顺序委派第一个
        const result = delegate(pendingTasks[0].id);
        if (callback) callback(result);
        return { status: 'ok', action: 'sequential_delegation', ...result, time: Date.now() - start };
      }
    }
    
    return { status: 'ok', action: 'no_pending_plans', time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// 新增：生命周期钩子集成
// ============================================================
const hooks = require('./hooks');

// 子代理生命周期事件
const LIFECYCLE_EVENTS = {
  SPAWNED: 'subagentSpawned',
  ENDED: 'subagentEnded',
  COMPLETED: 'completed',
  ERROR: 'error',
  KILLED: 'killed'
};

// 结束原因
const END_REASONS = {
  COMPLETED: 'completed',
  ERROR: 'error',
  KILLED: 'killed',
  TIMEOUT: 'timeout',
  CANCELLED: 'cancelled'
};

// ============================================================
// 新增：生命周期管理器集成
// ============================================================
const lifecycle = require('./subagent-lifecycle');
let lifecycleManager = null;

// ============================================================
// 新增：子代理运行时注册表
// ============================================================
const subagentRuns = new Map();
let sweeper = null;

// 最大子代理深度
const MAX_DEPTH = 5;

// ============================================================
// 新增：子代理上下文隔离系统
// ============================================================
const CONTEXTS_DIR = path.join(SUBAGENT_DIR, 'contexts');
if (!fs.existsSync(CONTEXTS_DIR)) fs.mkdirSync(CONTEXTS_DIR, { recursive: true });

// 子代理上下文存储
const subagentContexts = new Map();

/**
 * 创建子代理独立上下文
 * @param {string} runId - 子代理运行ID
 * @param {object} options - 选项 { parentRunId, initialContext, taskInfo }
 * @returns {object} - 上下文信息
 */
function createContext(runId, options = {}) {
  const contextId = uuidv4();
  const context = {
    contextId,
    runId,
    parentRunId: options.parentRunId || null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    
    // 上下文数据
    data: {
      messages: [],
      variables: options.initialContext?.variables || {},
      results: [],
      errors: [],
      artifacts: [],
      
      // 任务信息
      taskInfo: options.taskInfo || null,
      
      // 继承的父级上下文（只读）
      inherited: {}
    },
    
    // 上下文设置
    settings: {
      maxMessages: options.maxMessages || 100,
      maxTokenBudget: options.maxTokenBudget || 4000,
      inheritFromParent: options.inheritFromParent !== false,
      isolationLevel: options.isolationLevel || 'full' // full | partial | none
    }
  };
  
  // 如果有父级上下文且需要继承
  if (context.settings.inheritFromParent && options.parentRunId) {
    const parentContext = getContextByRunId(options.parentRunId);
    if (parentContext) {
      context.data.inherited = {
        contextId: parentContext.contextId,
        variables: { ...parentContext.data.variables },
        // 不继承消息，避免污染
        summary: parentContext.data.messages.slice(-3).map(m => ({
          role: m.role,
          summary: m.content.substring(0, 100)
        }))
      };
    }
  }
  
  // 保存上下文到文件
  const contextPath = path.join(CONTEXTS_DIR, `${contextId}.json`);
  fs.writeFileSync(contextPath, JSON.stringify(context, null, 2));
  
  // 存储到内存
  subagentContexts.set(contextId, context);
  
  return { status: 'ok', context, contextPath };
}

/**
 * 获取子代理上下文
 * @param {string} contextId - 上下文ID
 * @returns {object|null} - 上下文对象
 */
function getContext(contextId) {
  // 先从内存获取
  if (subagentContexts.has(contextId)) {
    return subagentContexts.get(contextId);
  }
  
  // 从文件加载
  const contextPath = path.join(CONTEXTS_DIR, `${contextId}.json`);
  if (fs.existsSync(contextPath)) {
    try {
      const context = JSON.parse(fs.readFileSync(contextPath, 'utf8'));
      subagentContexts.set(contextId, context);
      return context;
    } catch (e) {
      return null;
    }
  }
  
  return null;
}

/**
 * 根据runId获取上下文
 * @param {string} runId - 子代理运行ID
 * @returns {object|null} - 上下文对象
 */
function getContextByRunId(runId) {
  for (const [contextId, context] of subagentContexts.entries()) {
    if (context.runId === runId) {
      return context;
    }
  }
  
  // 从文件查找
  const files = fs.readdirSync(CONTEXTS_DIR).filter(f => f.endsWith('.json'));
  for (const f of files) {
    try {
      const context = JSON.parse(fs.readFileSync(path.join(CONTEXTS_DIR, f), 'utf8'));
      if (context.runId === runId) {
        subagentContexts.set(context.contextId, context);
        return context;
      }
    } catch (e) {}
  }
  
  return null;
}

/**
 * 添加消息到上下文
 * @param {string} contextId - 上下文ID
 * @param {object} message - 消息 { role, content, metadata }
 * @returns {object} - 结果
 */
function addMessage(contextId, message) {
  const context = getContext(contextId);
  if (!context) {
    return { status: 'error', message: 'Context not found' };
  }
  
  const messageWithMeta = {
    ...message,
    timestamp: new Date().toISOString(),
    id: uuidv4()
  };
  
  context.data.messages.push(messageWithMeta);
  
  // 应用消息数量限制
  if (context.data.messages.length > context.settings.maxMessages) {
    // 保留最新的消息，删除最旧的
    const removed = context.data.messages.splice(0, 
      context.data.messages.length - context.settings.maxMessages);
    context.data.removedMessages = (context.data.removedMessages || []).concat(removed);
  }
  
  context.updatedAt = new Date().toISOString();
  
  // 持久化
  saveContext(context);
  
  return { status: 'ok', message: messageWithMeta };
}

/**
 * 设置上下文变量
 * @param {string} contextId - 上下文ID
 * @param {string} key - 变量名
 * @param {any} value - 变量值
 * @returns {object} - 结果
 */
function setVariable(contextId, key, value) {
  const context = getContext(contextId);
  if (!context) {
    return { status: 'error', message: 'Context not found' };
  }
  
  context.data.variables[key] = value;
  context.updatedAt = new Date().toISOString();
  
  saveContext(context);
  
  return { status: 'ok', key, value };
}

/**
 * 获取上下文变量
 * @param {string} contextId - 上下文ID
 * @param {string} key - 变量名
 * @returns {any} - 变量值
 */
function getVariable(contextId, key) {
  const context = getContext(contextId);
  if (!context) {
    return null;
  }
  
  // 先查找自己的变量
  if (key in context.data.variables) {
    return context.data.variables[key];
  }
  
  // 再查找继承的变量
  if (key in context.data.inherited?.variables) {
    return context.data.inherited.variables[key];
  }
  
  return null;
}

/**
 * 添加结果到上下文
 * @param {string} contextId - 上下文ID
 * @param {object} result - 结果数据
 * @returns {object} - 结果
 */
function addResult(contextId, result) {
  const context = getContext(contextId);
  if (!context) {
    return { status: 'error', message: 'Context not found' };
  }
  
  const resultWithMeta = {
    ...result,
    timestamp: new Date().toISOString(),
    id: uuidv4()
  };
  
  context.data.results.push(resultWithMeta);
  context.updatedAt = new Date().toISOString();
  
  saveContext(context);
  
  return { status: 'ok', result: resultWithMeta };
}

/**
 * 添加错误到上下文
 * @param {string} contextId - 上下文ID
 * @param {object} error - 错误信息
 * @returns {object} - 结果
 */
function addError(contextId, error) {
  const context = getContext(contextId);
  if (!context) {
    return { status: 'error', message: 'Context not found' };
  }
  
  const errorWithMeta = {
    ...error,
    timestamp: new Date().toISOString(),
    id: uuidv4()
  };
  
  context.data.errors.push(errorWithMeta);
  context.updatedAt = new Date().toISOString();
  
  saveContext(context);
  
  return { status: 'ok', error: errorWithMeta };
}

/**
 * 保存上下文到文件
 * @param {object} context - 上下文对象
 */
function saveContext(context) {
  const contextPath = path.join(CONTEXTS_DIR, `${context.contextId}.json`);
  fs.writeFileSync(contextPath, JSON.stringify(context, null, 2));
}

/**
 * 清理子代理上下文
 * @param {string} runId - 子代理运行ID
 * @returns {object} - 结果
 */
function cleanupContext(runId) {
  const context = getContextByRunId(runId);
  if (!context) {
    return { status: 'ok', message: 'Context not found' };
  }
  
  // 从内存移除
  subagentContexts.delete(context.contextId);
  
  // 删除文件（可选，保留用于审计）
  // fs.unlinkSync(path.join(CONTEXTS_DIR, `${context.contextId}.json`));
  
  return { status: 'ok', contextId: context.contextId };
}

/**
 * 获取上下文摘要
 * @param {string} runId - 子代理运行ID
 * @returns {object} - 摘要信息
 */
function getContextSummary(runId) {
  const context = getContextByRunId(runId);
  if (!context) {
    return { status: 'error', message: 'Context not found' };
  }
  
  return {
    status: 'ok',
    contextId: context.contextId,
    runId,
    parentRunId: context.parentRunId,
    messageCount: context.data.messages.length,
    variableCount: Object.keys(context.data.variables).length,
    resultCount: context.data.results.length,
    errorCount: context.data.errors.length,
    createdAt: context.createdAt,
    updatedAt: context.updatedAt,
    settings: context.settings
  };
}

/**
 * 列出所有上下文
 * @returns {object} - 所有上下文列表
 */
function listContexts() {
  const contexts = Array.from(subagentContexts.values()).map(ctx => ({
    contextId: ctx.contextId,
    runId: ctx.runId,
    parentRunId: ctx.parentRunId,
    status: 'active',
    messageCount: ctx.data.messages.length,
    createdAt: ctx.createdAt
  }));
  
  return { status: 'ok', contexts, total: contexts.length };
}

// ============================================================
// 新增：状态持久化和恢复
// ============================================================
function persistState() {
  const statePath = path.join(SUBAGENT_DIR, 'state.json');
  const state = {
    runs: Array.from(subagentRuns.entries()).map(([id, run]) => ({
      id,
      planId: run.planId,
      taskId: run.taskId,
      status: run.status,
      depth: run.depth,
      createdAt: run.createdAt,
      updatedAt: run.updatedAt,
      contextId: run.contextId
    })),
    contexts: Array.from(subagentContexts.keys()),
    persistedAt: new Date().toISOString()
  };
  fs.writeFileSync(statePath, JSON.stringify(state, null, 2));
}

function restoreState() {
  const statePath = path.join(SUBAGENT_DIR, 'state.json');
  if (fs.existsSync(statePath)) {
    try {
      const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
      for (const run of state.runs || []) {
        if (run.status === 'running' || run.status === 'pending') {
          run.status = 'restored';
          run.restoredAt = new Date().toISOString();
        }
        subagentRuns.set(run.id, run);
      }
      console.log(`[SubAgent] 恢复了 ${subagentRuns.size} 个子代理状态`);
    } catch (e) {
      console.log(`[SubAgent] 状态恢复失败: ${e.message}`);
    }
  }
}

// 启动时恢复状态
restoreState();

// ============================================================
// 新增：启动清理器
// ============================================================
function startSweeper() {
  if (sweeper) return;
  
  sweeper = setInterval(() => {
    const now = Date.now();
    const timeout = 30 * 60 * 1000; // 30分钟超时
    
    for (const [id, run] of subagentRuns.entries()) {
      if (run.status === 'running' || run.status === 'restored') {
        const elapsed = now - new Date(run.updatedAt || run.createdAt).getTime();
        if (elapsed > timeout) {
          run.status = 'timeout';
          run.endedAt = new Date().toISOString();
          run.endReason = END_REASONS.TIMEOUT;
          subagentRuns.set(id, run);
          
          // 触发钩子
          hooks.trigger('subagentEnded', {
            runId: id,
            reason: END_REASONS.TIMEOUT,
            elapsed
          });
        }
      }
    }
    
    persistState();
  }, 60000); // 每分钟检查一次
  
  console.log('[SubAgent] 清理器已启动');
}

function stopSweeper() {
  if (sweeper) {
    clearInterval(sweeper);
    sweeper = null;
    console.log('[SubAgent] 清理器已停止');
  }
}

// 注意：清理器不再自动启动，需要调用 startSweeper() 手动启动
// 这是为了避免模块加载时创建定时器导致进程无法退出
// startSweeper();

// ============================================================
// 新增：增强版委派（带钩子、状态管理和上下文隔离）
// ============================================================
async function delegateWithLifecycle(taskId, options = {}) {
  const start = Date.now();
  
  // 初始化生命周期管理器
  if (!lifecycleManager) {
    lifecycleManager = lifecycle.getLifecycleManager();
  }
  
  // 触发 before 钩子
  await hooks.trigger('subagentSpawning', { taskId, options });
  
  try {
    const result = delegate(taskId, options);
    
    if (result.status === 'ok') {
      const runId = uuidv4();
      
      // 启动生命周期（新增：完整生命周期追踪）
      const lifecycleId = await lifecycleManager.startLifecycle(runId, result.task);
      
      // 创建子代理上下文（关键：上下文隔离）
      const contextResult = createContext(runId, {
        parentRunId: options.parentRunId,
        initialContext: options.initialContext,
        taskInfo: result.task,
        maxMessages: options.maxMessages || 100,
        maxTokenBudget: options.maxTokenBudget || 4000,
        inheritFromParent: options.inheritFromParent,
        isolationLevel: options.isolationLevel || 'full'
      });
      
      // 添加任务信息到上下文
      if (contextResult.status === 'ok') {
        addMessage(contextResult.context.contextId, {
          role: 'system',
          content: `任务开始: ${result.task.objective}`,
          metadata: { taskId, taskName: result.task.name, lifecycleId }
        });
      }
      
      const run = {
        id: runId,
        planId: result.planId,
        taskId,
        status: 'running',
        depth: options.depth || 0,
        contextId: contextResult.status === 'ok' ? contextResult.context.contextId : null,
        lifecycleId: lifecycleId,  // 新增：生命周期ID
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };
      
      subagentRuns.set(runId, run);
      persistState();
      
      // 触发 spawned 钩子
      await hooks.trigger('subagentSpawned', { 
        runId, 
        taskId, 
        planId: result.planId,
        contextId: run.contextId,
        lifecycleId: lifecycleId
      });
      
      return { ...result, runId, contextId: run.contextId, lifecycleId: lifecycleId };
    }
    
    return result;
  } catch (e) {
    await hooks.trigger('subagentEnded', { taskId, reason: END_REASONS.ERROR, error: e.message });
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// 新增：完成子代理生命周期
// ============================================================
async function completeSubagentLifecycle(runId, status, reason = null, result = null, error = null) {
  if (!lifecycleManager) {
    lifecycleManager = lifecycle.getLifecycleManager();
  }
  
  const run = subagentRuns.get(runId);
  if (!run || !run.lifecycleId) {
    console.warn(`[SubAgent] Run or lifecycle not found: ${runId}`);
    return { status: 'error', message: 'Run or lifecycle not found' };
  }
  
  // 结束生命周期（新增：自动发送完成消息）
  await lifecycleManager.endLifecycle(run.lifecycleId, status, reason, result, error);
  
  // 更新运行状态
  run.status = status;
  run.updatedAt = new Date().toISOString();
  if (reason) run.endReason = reason;
  
  subagentRuns.set(runId, run);
  persistState();
  
  return { status: 'ok', runId, lifecycleId: run.lifecycleId, status };
}

// ============================================================
// 新增：获取运行时状态
// ============================================================
function getRuntimeStatus() {
  return {
    activeRuns: Array.from(subagentRuns.entries())
      .filter(([_, run]) => run.status === 'running')
      .map(([id, run]) => ({ id, ...run })),
    totalRuns: subagentRuns.size,
    sweeperActive: sweeper !== null
  };
}

// ============================================================
// 新增：深度限制检查
// ============================================================
function checkDepthLimit(depth = 0) {
  return depth < MAX_DEPTH;
}

// ============================================================
// 新增：列出活动子代理
// ============================================================
function listActive() {
  const start = Date.now();
  
  const active = Array.from(subagentRuns.entries())
    .filter(([_, run]) => run.status === 'running' || run.status === 'restored')
    .map(([id, run]) => ({
      id,
      taskId: run.taskId,
      planId: run.planId,
      depth: run.depth,
      status: run.status,
      createdAt: run.createdAt,
      elapsed: Date.now() - new Date(run.createdAt).getTime()
    }));
  
  return { status: 'ok', active, count: active.length, time: Date.now() - start };
}

module.exports = {
  plan,
  delegate,
  delegateParallel,
  report,
  status,
  review,
  aggregate,
  cancel,
  templates,
  autoDelegate,
  assessComplexity,
  // 生命周期
  delegateWithLifecycle,
  completeSubagentLifecycle,
  getRuntimeStatus,
  listActive,
  checkDepthLimit,
  startSweeper,
  stopSweeper,
  persistState,
  restoreState,
  LIFECYCLE_EVENTS,
  END_REASONS,
  MAX_DEPTH,
  // 生命周期管理器
  lifecycleManager,
  getLifecycleManager: () => lifecycle.getLifecycleManager(),
  setLifecycleManager: (manager) => lifecycle.setLifecycleManager(manager),
  // 上下文隔离
  createContext,
  getContext,
  getContextByRunId,
  addMessage,
  setVariable,
  getVariable,
  addResult,
  addError,
  cleanupContext,
  getContextSummary,
  listContexts
};
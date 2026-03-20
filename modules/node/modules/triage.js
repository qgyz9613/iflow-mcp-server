/**
 * iFlow Triage Module v2.0
 * 任务分类系统（基于OpenClaw routing设计）
 * 
 * 新增功能:
 * - 智能路由 (Intelligent Routing)
 * - 依赖分析 (Dependency Analysis)
 * - 容量规划 (Capacity Planning)
 * - 任务分组 (Task Grouping)
 * - 学习反馈 (Learning Feedback)
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');

const TRIAGE_DIR = path.join(__dirname, '..', 'triage-data');
const LEARNING_DIR = path.join(TRIAGE_DIR, 'learning');

[TRIAGE_DIR, LEARNING_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// ============================================================
// 任务分类
// ============================================================

const CATEGORIES = {
  code: {
    subs: ['debug', 'refactor', 'implement', 'review', 'test', 'document'],
    agents: ['general-purpose', 'code-reviewer'],
    avgTime: 300000, // 5分钟
    requiredSkills: ['programming']
  },
  research: {
    subs: ['search', 'analyze', 'summarize', 'compare'],
    agents: ['explore-agent', 'general-purpose'],
    avgTime: 180000, // 3分钟
    requiredSkills: ['analysis']
  },
  file: {
    subs: ['read', 'write', 'organize', 'search', 'backup'],
    agents: ['general-purpose'],
    avgTime: 60000, // 1分钟
    requiredSkills: ['filesystem']
  },
  browser: {
    subs: ['scrape', 'interact', 'automate', 'test'],
    agents: ['frontend-tester', 'general-purpose'],
    avgTime: 240000, // 4分钟
    requiredSkills: ['browser', 'automation']
  },
  system: {
    subs: ['configure', 'monitor', 'deploy', 'backup'],
    agents: ['general-purpose'],
    avgTime: 180000, // 3分钟
    requiredSkills: ['sysadmin']
  },
  communication: {
    subs: ['email', 'message', 'notify', 'report'],
    agents: ['general-purpose'],
    avgTime: 120000, // 2分钟
    requiredSkills: ['communication']
  },
  general: {
    subs: ['other', 'question', 'chat'],
    agents: ['general-purpose'],
    avgTime: 60000,
    requiredSkills: []
  }
};

// ============================================================
// 优先级配置
// ============================================================

const PRIORITY_KEYWORDS = {
  high: ['urgent', 'critical', 'important', 'asap', 'emergency', '紧急', '重要', '立即', '马上'],
  medium: ['soon', 'needed', 'normal', '需要', '正常', '常规'],
  low: ['later', 'someday', 'maybe', 'whenever', '以后', '可能', '有空']
};

// ============================================================
// 分类器类
// ============================================================

class TaskClassifier {
  constructor() {
    this.patterns = this.loadPatterns();
    this.learning = this.loadLearning();
    this.stats = this.loadStats();
  }
  
  loadPatterns() {
    const patternPath = path.join(TRIAGE_DIR, 'patterns.json');
    if (fs.existsSync(patternPath)) {
      try {
        return JSON.parse(fs.readFileSync(patternPath, 'utf8'));
      } catch (e) {}
    }
    
    // 默认模式
    return {
      code: ['function', 'class', 'bug', 'error', 'fix', 'implement', 'refactor', '代码', '函数', '类', '修复', '实现'],
      research: ['research', 'analyze', 'find', 'search', 'what', 'why', 'how', '研究', '分析', '查找', '搜索', '什么', '为什么', '如何'],
      file: ['file', 'read', 'write', 'copy', 'move', 'delete', 'folder', '文件', '读取', '写入', '复制', '移动', '删除', '文件夹'],
      browser: ['browser', 'website', 'scrape', 'click', 'navigate', 'web', '浏览器', '网站', '网页', '点击', '访问'],
      system: ['system', 'config', 'install', 'deploy', 'server', 'process', '系统', '配置', '安装', '部署', '服务器', '进程'],
      communication: ['email', 'send', 'message', 'notify', 'report', '邮件', '发送', '消息', '通知', '报告']
    };
  }
  
  loadLearning() {
    const learningPath = path.join(LEARNING_DIR, 'feedback.json');
    if (fs.existsSync(learningPath)) {
      try {
        return JSON.parse(fs.readFileSync(learningPath, 'utf8'));
      } catch (e) {}
    }
    return { corrections: [], accuracy: {} };
  }
  
  loadStats() {
    const statsPath = path.join(TRIAGE_DIR, 'stats.json');
    if (fs.existsSync(statsPath)) {
      try {
        return JSON.parse(fs.readFileSync(statsPath, 'utf8'));
      } catch (e) {}
    }
    return { total: 0, correct: 0, byCategory: {} };
  }
  
  /**
   * 分类任务
   */
  classify(task, options = {}) {
    const start = Date.now();
    const text = (task || '').toLowerCase();
    
    // 检查学习修正
    const correction = this.findCorrection(task);
    if (correction) {
      return this.createClassification(task, correction.category, correction.subCategory, options, 0.95);
    }
    
    // 基于模式匹配
    let bestCategory = 'general';
    let bestSubCategory = 'other';
    let bestScore = 0;
    
    for (const [category, keywords] of Object.entries(this.patterns)) {
      const matches = keywords.filter(k => text.includes(k.toLowerCase())).length;
      const score = matches / keywords.length;
      
      if (score > bestScore) {
        bestScore = score;
        bestCategory = category;
      }
    }
    
    // 查找子类别
    const catConfig = CATEGORIES[bestCategory];
    if (catConfig && catConfig.subs) {
      for (const sub of catConfig.subs) {
        if (text.includes(sub.toLowerCase())) {
          bestSubCategory = sub;
          break;
        }
      }
    }
    
    // 计算置信度
    const confidence = Math.min(0.5 + bestScore * 0.5, 1.0);
    
    return this.createClassification(task, bestCategory, bestSubCategory, options, confidence);
  }
  
  /**
   * 创建分类结果
   */
  createClassification(task, category, subCategory, options, confidence) {
    const text = (task || '').toLowerCase();
    const catConfig = CATEGORIES[category] || CATEGORIES.general;
    
    // 检测优先级
    let priority = 'medium';
    for (const [p, keywords] of Object.entries(PRIORITY_KEYWORDS)) {
      if (keywords.some(k => text.includes(k.toLowerCase()))) {
        priority = p;
        break;
      }
    }
    
    // 分析复杂度
    const complexity = this.analyzeComplexity(task);
    
    // 估算时间
    const estimatedTime = this.estimateTime(task, category, complexity);
    
    // 推荐代理
    const recommendedAgents = catConfig.agents || ['general-purpose'];
    
    // 检测依赖
    const dependencies = this.detectDependencies(task);
    
    const result = {
      id: options.id || uuidv4(),
      task: options.originalTask || task,
      category,
      subCategory,
      priority,
      complexity,
      confidence,
      estimatedTime,
      recommendedAgents,
      dependencies,
      requiredSkills: catConfig.requiredSkills || [],
      timestamp: new Date().toISOString()
    };
    
    // 保存结果
    this.saveResult(result);
    
    return {
      status: 'ok',
      triage: result,
      time: Date.now() - start
    };
  }
  
  /**
   * 分析复杂度
   */
  analyzeComplexity(task) {
    const text = (task || '').toLowerCase();
    let score = 0;
    
    // 简单任务标志
    if (text.includes('simple') || text.includes('quick') || text.includes('简单') || text.includes('快速')) {
      score -= 1;
    }
    
    // 复杂任务标志
    if (text.includes('complex') || text.includes('complicated') || text.includes('复杂') || text.includes('完整')) {
      score += 2;
    }
    
    // 多任务标志
    if (text.includes('multiple') || text.includes('多个') || text.includes('all') || text.includes('所有')) {
      score += 1;
    }
    
    // 长任务
    if (text.split(/\s+/).length > 20 || text.length > 100) {
      score += 1;
    }
    
    // 并发任务
    if (text.includes('and') || text.includes('然后') || text.includes('同时') || text.includes('parallel')) {
      score += 1;
    }
    
    // 代码相关通常更复杂
    if (text.includes('code') || text.includes('代码') || text.includes('function') || text.includes('函数')) {
      score += 1;
    }
    
    if (score <= 0) return 'low';
    if (score === 1) return 'medium';
    return 'high';
  }
  
  /**
   * 估算时间
   */
  estimateTime(task, category, complexity) {
    const catConfig = CATEGORIES[category] || CATEGORIES.general;
    const baseTime = catConfig.avgTime || 60000;
    
    const multipliers = {
      low: 0.7,
      medium: 1.0,
      high: 1.5
    };
    
    return Math.round(baseTime * (multipliers[complexity] || 1.0));
  }
  
  /**
   * 检测依赖
   */
  detectDependencies(task) {
    const text = (task || '').toLowerCase();
    const dependencies = [];
    
    // 文件依赖
    const filePattern = /([a-zA-Z0-9_\-./]+\.(js|ts|py|json|yaml|md|txt))/gi;
    const fileMatches = text.match(filePattern) || [];
    fileMatches.forEach(f => {
      dependencies.push({ type: 'file', name: f });
    });
    
    // URL 依赖
    const urlPattern = /https?:\/\/[^\s]+/gi;
    const urlMatches = text.match(urlPattern) || [];
    urlMatches.forEach(u => {
      dependencies.push({ type: 'url', name: u });
    });
    
    // 模块依赖
    const modulePattern = /require\s*\(\s*['"]([^'"]+)['"]\s*\)/g;
    let match;
    while ((match = modulePattern.exec(text)) !== null) {
      dependencies.push({ type: 'module', name: match[1] });
    }
    
    return dependencies;
  }
  
  /**
   * 查找修正
   */
  findCorrection(task) {
    const text = (task || '').toLowerCase();
    
    for (const corr of this.learning.corrections) {
      if (text.includes(corr.pattern.toLowerCase())) {
        return corr;
      }
    }
    
    return null;
  }
  
  /**
   * 记录反馈
   */
  feedback(taskId, correct, actualCategory = null) {
    const start = Date.now();
    
    // 更新统计
    this.stats.total++;
    if (correct) {
      this.stats.correct++;
    } else if (actualCategory) {
      // 学习修正
      this.learning.corrections.push({
        pattern: taskId, // 简化：用ID作为模式
        category: actualCategory.category,
        subCategory: actualCategory.subCategory,
        timestamp: new Date().toISOString()
      });
      
      // 限制修正数量
      if (this.learning.corrections.length > 100) {
        this.learning.corrections = this.learning.corrections.slice(-100);
      }
      
      this.saveLearning();
    }
    
    this.saveStats();
    
    return {
      status: 'ok',
      accuracy: this.stats.total > 0 ? this.stats.correct / this.stats.total : 0,
      time: Date.now() - start
    };
  }
  
  /**
   * 保存结果
   */
  saveResult(result) {
    const filePath = path.join(TRIAGE_DIR, `${result.id}.json`);
    fs.writeFileSync(filePath, JSON.stringify(result, null, 2));
    
    // 更新分类统计
    if (!this.stats.byCategory[result.category]) {
      this.stats.byCategory[result.category] = 0;
    }
    this.stats.byCategory[result.category]++;
    this.saveStats();
  }
  
  saveLearning() {
    fs.writeFileSync(
      path.join(LEARNING_DIR, 'feedback.json'),
      JSON.stringify(this.learning, null, 2)
    );
  }
  
  saveStats() {
    fs.writeFileSync(
      path.join(TRIAGE_DIR, 'stats.json'),
      JSON.stringify(this.stats, null, 2)
    );
  }
}

// ============================================================
// 路由器类
// ============================================================

class TaskRouter {
  constructor(classifier) {
    this.classifier = classifier;
    this.agentCapacities = new Map(); // agent -> {current, max}
    this.routingHistory = [];
  }
  
  /**
   * 路由任务
   */
  route(task, options = {}) {
    const start = Date.now();
    
    // 分类任务
    const classification = this.classifier.classify(task, options);
    if (classification.status !== 'ok') {
      return classification;
    }
    
    const triage = classification.triage;
    
    // 选择最佳代理
    const agent = this.selectAgent(triage);
    
    // 创建路由结果
    const routing = {
      triageId: triage.id,
      task: triage.task,
      category: triage.category,
      selectedAgent: agent,
      priority: triage.priority,
      estimatedTime: triage.estimatedTime,
      dependencies: triage.dependencies,
      routedAt: new Date().toISOString()
    };
    
    // 记录路由历史
    this.routingHistory.push(routing);
    if (this.routingHistory.length > 1000) {
      this.routingHistory = this.routingHistory.slice(-1000);
    }
    
    return {
      status: 'ok',
      routing,
      triage,
      time: Date.now() - start
    };
  }
  
  /**
   * 选择代理
   */
  selectAgent(triage) {
    const recommended = triage.recommendedAgents || ['general-purpose'];
    
    // 检查代理容量
    for (const agent of recommended) {
      const capacity = this.agentCapacities.get(agent);
      if (!capacity || capacity.current < capacity.max) {
        return agent;
      }
    }
    
    // 默认代理
    return 'general-purpose';
  }
  
  /**
   * 设置代理容量
   */
  setAgentCapacity(agent, max) {
    this.agentCapacities.set(agent, {
      current: 0,
      max: max || 5
    });
  }
  
  /**
   * 更新代理负载
   */
  updateAgentLoad(agent, delta) {
    const capacity = this.agentCapacities.get(agent);
    if (capacity) {
      capacity.current = Math.max(0, capacity.current + delta);
    }
  }
}

// ============================================================
// 批量处理
// ============================================================

function batchClassify(tasks) {
  const start = Date.now();
  const classifier = new TaskClassifier();
  
  const results = tasks.map(t => {
    const result = classifier.classify(t);
    return result.triage;
  });
  
  return {
    status: 'ok',
    results,
    total: tasks.length,
    time: Date.now() - start
  };
}

function prioritize(tasks) {
  const start = Date.now();
  const classifier = new TaskClassifier();
  
  const priorityOrder = { high: 0, medium: 1, low: 2 };
  const complexityOrder = { low: 0, medium: 1, high: 2 };
  
  const classified = tasks.map(t => {
    const result = classifier.classify(t);
    return result.triage;
  });
  
  // 排序：优先级 > 复杂度（简单优先）
  classified.sort((a, b) => {
    const pDiff = priorityOrder[a.priority] - priorityOrder[b.priority];
    if (pDiff !== 0) return pDiff;
    return complexityOrder[a.complexity] - complexityOrder[b.complexity];
  });
  
  return {
    status: 'ok',
    tasks: classified,
    time: Date.now() - start
  };
}

// ============================================================
// 查询和统计
// ============================================================

function getHistory(limit = 50) {
  const start = Date.now();
  try {
    const files = fs.readdirSync(TRIAGE_DIR)
      .filter(f => f.endsWith('.json') && !f.includes('stats') && !f.includes('patterns'))
      .slice(-limit);
    
    const history = files.map(f => {
      try {
        return JSON.parse(fs.readFileSync(path.join(TRIAGE_DIR, f), 'utf8'));
      } catch {
        return null;
      }
    }).filter(Boolean);
    
    return { status: 'ok', history, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

function getStats() {
  const start = Date.now();
  try {
    const statsPath = path.join(TRIAGE_DIR, 'stats.json');
    const stats = fs.existsSync(statsPath)
      ? JSON.parse(fs.readFileSync(statsPath, 'utf8'))
      : { total: 0, correct: 0, byCategory: {} };
    
    return { status: 'ok', stats, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// 全局实例
// ============================================================

let globalClassifier = null;
let globalRouter = null;

function getClassifier() {
  if (!globalClassifier) {
    globalClassifier = new TaskClassifier();
  }
  return globalClassifier;
}

function getRouter() {
  if (!globalRouter) {
    globalRouter = new TaskRouter(getClassifier());
  }
  return globalRouter;
}

// ============================================================
// 兼容旧API
// ============================================================

function classify(task, options = {}) {
  return getClassifier().classify(task, options);
}

function route(task, options = {}) {
  return getRouter().route(task, options);
}

function feedback(taskId, correct, actualCategory) {
  return getClassifier().feedback(taskId, correct, actualCategory);
}

// ============================================================
// 模块导出
// ============================================================

module.exports = {
  // 核心类
  TaskClassifier,
  TaskRouter,
  
  // 全局实例
  getClassifier,
  getRouter,
  
  // 兼容旧API
  classify,
  prioritize,
  getHistory,
  getStats,
  batchClassify,
  
  // 新API
  route,
  feedback,
  
  // 配置
  CATEGORIES,
  PRIORITY_KEYWORDS
};
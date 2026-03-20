/**
 * iFlow Decision Module v2.0
 * 决策系统（基于OpenClaw multi-strategy设计）
 * 
 * 新增功能:
 * - 多策略决策引擎
 * - 决策树支持
 * - 置信度计算
 * - 历史分析
 * - A/B测试
 */

const path = require('path');
const fs = require('fs');
const { v4: uuidv4 } = require('uuid');

const DECISION_DIR = path.join(__dirname, '..', 'decision-data');
const HISTORY_FILE = path.join(DECISION_DIR, 'history.json');
const PREFS_FILE = path.join(DECISION_DIR, 'preferences.json');
const MODELS_FILE = path.join(DECISION_DIR, 'models.json');

[DECISION_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// ============================================================
// 决策策略
// ============================================================

const DecisionStrategy = {
  RANDOM: 'random',
  WEIGHTED: 'weighted',
  FIRST: 'first',
  CONSENSUS: 'consensus',
  THOMPSON_SAMPLING: 'thompson',
  UCB: 'ucb', // Upper Confidence Bound
  BAYESIAN: 'bayesian',
  DECISION_TREE: 'tree',
  MULTI_CRITERIA: 'mcdm' // 多准则决策
};

// ============================================================
// 决策引擎
// ============================================================

class DecisionEngine {
  constructor() {
    this.history = this.loadHistory();
    this.preferences = this.loadPreferences();
    this.models = this.loadModels();
    this.banditStats = new Map(); // 多臂老虎机统计
  }
  
  /**
   * 做出决策
   */
  decide(options, context = {}) {
    const strategy = context.strategy || DecisionStrategy.WEIGHTED;
    
    if (!options || options.length === 0) {
      return { status: 'error', message: 'No options provided' };
    }
    
    let decision;
    let confidence = 0;
    let reasoning = [];
    
    switch (strategy) {
      case DecisionStrategy.RANDOM:
        decision = this.randomChoice(options);
        confidence = 1 / options.length;
        reasoning.push('Random selection');
        break;
        
      case DecisionStrategy.WEIGHTED:
        const weightedResult = this.weightedChoice(options, context);
        decision = weightedResult.decision;
        confidence = weightedResult.confidence;
        reasoning.push(`Weighted by preferences (weight sum: ${weightedResult.totalWeight})`);
        break;
        
      case DecisionStrategy.THOMPSON_SAMPLING:
        const thompsonResult = this.thompsonSampling(options, context);
        decision = thompsonResult.decision;
        confidence = thompsonResult.confidence;
        reasoning.push('Thompson sampling based on historical performance');
        break;
        
      case DecisionStrategy.UCB:
        const ucbResult = this.ucbChoice(options, context);
        decision = ucbResult.decision;
        confidence = ucbResult.confidence;
        reasoning.push('UCB balancing exploration and exploitation');
        break;
        
      case DecisionStrategy.MULTI_CRITERIA:
        const mcdmResult = this.multiCriteriaChoice(options, context);
        decision = mcdmResult.decision;
        confidence = mcdmResult.confidence;
        reasoning = mcdmResult.reasoning;
        break;
        
      case DecisionStrategy.DECISION_TREE:
        const treeResult = this.decisionTreeChoice(options, context);
        decision = treeResult.decision;
        confidence = treeResult.confidence;
        reasoning = treeResult.reasoning;
        break;
        
      default:
        decision = options[0];
        confidence = 0.5;
        reasoning.push('Default first choice');
    }
    
    // 记录决策
    const record = {
      id: uuidv4(),
      context,
      options,
      strategy,
      decision,
      confidence,
      reasoning,
      timestamp: Date.now()
    };
    
    this.history.push(record);
    this.limitHistory();
    this.saveHistory();
    
    return {
      status: 'ok',
      decision,
      confidence,
      reasoning,
      recordId: record.id
    };
  }
  
  /**
   * 随机选择
   */
  randomChoice(options) {
    return options[Math.floor(Math.random() * options.length)];
  }
  
  /**
   * 加权选择
   */
  weightedChoice(options, context) {
    const weights = options.map(opt => {
      const key = this.getOptionKey(opt);
      const baseWeight = this.preferences[key] || 1;
      const contextBonus = this.getContextBonus(key, context);
      return { opt, weight: baseWeight + contextBonus };
    });
    
    const totalWeight = weights.reduce((sum, w) => sum + w.weight, 0);
    let random = Math.random() * totalWeight;
    
    for (const w of weights) {
      random -= w.weight;
      if (random <= 0) {
        return {
          decision: w.opt,
          confidence: w.weight / totalWeight,
          totalWeight
        };
      }
    }
    
    return {
      decision: options[0],
      confidence: weights[0]?.weight / totalWeight || 0.5,
      totalWeight
    };
  }
  
  /**
   * Thompson采样（多臂老虎机）
   */
  thompsonSampling(options, context) {
    const samples = options.map(opt => {
      const key = this.getOptionKey(opt);
      const stats = this.getBanditStats(key);
      
      // Beta分布采样
      const alpha = stats.successes + 1;
      const beta = stats.failures + 1;
      const sample = this.betaSample(alpha, beta);
      
      return { opt, sample, stats };
    });
    
    samples.sort((a, b) => b.sample - a.sample);
    const best = samples[0];
    
    return {
      decision: best.opt,
      confidence: best.sample,
      samples: samples.slice(0, 3).map(s => ({ key: this.getOptionKey(s.opt), sample: s.sample }))
    };
  }
  
  /**
   * UCB选择
   */
  ucbChoice(options, context) {
    const totalPulls = options.reduce((sum, opt) => {
      const stats = this.getBanditStats(this.getOptionKey(opt));
      return sum + stats.total;
    }, 0);
    
    const ucbScores = options.map(opt => {
      const key = this.getOptionKey(opt);
      const stats = this.getBanditStats(key);
      
      if (stats.total === 0) {
        return { opt, score: Infinity, stats };
      }
      
      const avgReward = stats.successes / stats.total;
      const exploration = Math.sqrt(2 * Math.log(totalPulls) / stats.total);
      const score = avgReward + exploration;
      
      return { opt, score, stats, avgReward, exploration };
    });
    
    ucbScores.sort((a, b) => b.score - a.score);
    const best = ucbScores[0];
    
    return {
      decision: best.opt,
      confidence: best.score,
      avgReward: best.avgReward,
      exploration: best.exploration
    };
  }
  
  /**
   * 多准则决策
   */
  multiCriteriaChoice(options, context) {
    const criteria = context.criteria || [
      { name: 'preference', weight: 0.4 },
      { name: 'recency', weight: 0.3 },
      { name: 'success_rate', weight: 0.3 }
    ];
    
    const scores = options.map(opt => {
      const key = this.getOptionKey(opt);
      const details = this.getOptionDetails(key);
      
      let totalScore = 0;
      const breakdown = {};
      
      for (const criterion of criteria) {
        let score = 0;
        
        switch (criterion.name) {
          case 'preference':
            score = this.preferences[key] || 1;
            break;
          case 'recency':
            score = details.lastUsed ? Math.exp(-((Date.now() - details.lastUsed) / 86400000)) : 0.5;
            break;
          case 'success_rate':
            const stats = this.getBanditStats(key);
            score = stats.total > 0 ? stats.successes / stats.total : 0.5;
            break;
          default:
            score = 0.5;
        }
        
        breakdown[criterion.name] = score;
        totalScore += score * criterion.weight;
      }
      
      return { opt, totalScore, breakdown };
    });
    
    scores.sort((a, b) => b.totalScore - a.totalScore);
    const best = scores[0];
    const maxScore = Math.max(...scores.map(s => s.totalScore));
    
    return {
      decision: best.opt,
      confidence: maxScore > 0 ? best.totalScore / maxScore : 0.5,
      reasoning: Object.entries(best.breakdown).map(([k, v]) => `${k}: ${v.toFixed(2)}`),
      allScores: scores.slice(0, 5).map(s => ({ key: this.getOptionKey(s.opt), score: s.totalScore }))
    };
  }
  
  /**
   * 决策树选择
   */
  decisionTreeChoice(options, context) {
    const tree = context.decisionTree || this.buildDefaultTree(options);
    const reasoning = [];
    
    let node = tree;
    
    while (node.children) {
      const condition = node.condition;
      const result = this.evaluateCondition(condition, context);
      reasoning.push(`${condition} => ${result}`);
      
      node = node.children[result] || node.children.default || Object.values(node.children)[0];
    }
    
    const decision = node.value || options[0];
    const optionIndex = options.findIndex(o => this.getOptionKey(o) === this.getOptionKey(decision));
    
    return {
      decision,
      confidence: node.confidence || 0.7,
      reasoning,
      path: reasoning.join(' -> ')
    };
  }
  
  /**
   * 反馈结果
   */
  feedback(decisionId, outcome, reward = null) {
    const record = this.history.find(h => h.id === decisionId);
    if (!record) {
      return { status: 'error', message: 'Decision not found' };
    }
    
    // 更新多臂老虎机统计
    const key = this.getOptionKey(record.decision);
    const stats = this.getBanditStats(key);
    
    if (outcome === 'success' || reward > 0.5) {
      stats.successes++;
    } else {
      stats.failures++;
    }
    stats.total++;
    
    this.banditStats.set(key, stats);
    
    // 更新偏好
    if (reward !== null) {
      const currentPref = this.preferences[key] || 1;
      this.preferences[key] = currentPref * 0.9 + reward * 0.1; // 指数移动平均
    }
    
    // 记录结果
    record.outcome = outcome;
    record.reward = reward;
    record.feedbackAt = Date.now();
    
    this.saveHistory();
    this.savePreferences();
    
    return { status: 'ok', key, stats };
  }
  
  // ============================================================
  // 辅助方法
  // ============================================================
  
  getOptionKey(opt) {
    return typeof opt === 'string' ? opt : opt.name || opt.id || JSON.stringify(opt);
  }
  
  getContextBonus(key, context) {
    let bonus = 0;
    if (context.context?.includes(key)) bonus += 0.5;
    if (context.boost?.[key]) bonus += context.boost[key];
    return bonus;
  }
  
  getBanditStats(key) {
    if (!this.banditStats.has(key)) {
      this.banditStats.set(key, { successes: 0, failures: 0, total: 0 });
    }
    return this.banditStats.get(key);
  }
  
  getOptionDetails(key) {
    const records = this.history.filter(h => this.getOptionKey(h.decision) === key);
    return {
      count: records.length,
      lastUsed: records.length > 0 ? records[records.length - 1].timestamp : null,
      avgConfidence: records.length > 0 
        ? records.reduce((sum, r) => sum + (r.confidence || 0), 0) / records.length 
        : 0
    };
  }
  
  betaSample(alpha, beta) {
    // 简化的Beta采样
    const u1 = Math.random();
    const u2 = Math.random();
    return Math.pow(u1, 1/alpha) / (Math.pow(u1, 1/alpha) + Math.pow(u2, 1/beta));
  }
  
  evaluateCondition(condition, context) {
    if (!condition) return true;
    
    try {
      const fn = new Function('context', `return ${condition}`);
      return fn(context);
    } catch {
      return false;
    }
  }
  
  buildDefaultTree(options) {
    return {
      condition: 'context.urgent',
      children: {
        true: { value: options[0], confidence: 0.9 },
        false: {
          condition: 'options.length > 3',
          children: {
            true: { value: 'weighted', confidence: 0.8 },
            false: { value: options[0], confidence: 0.7 }
          }
        }
      }
    };
  }
  
  limitHistory() {
    if (this.history.length > 1000) {
      this.history = this.history.slice(-1000);
    }
  }
  
  loadHistory() {
    try {
      return fs.existsSync(HISTORY_FILE) 
        ? JSON.parse(fs.readFileSync(HISTORY_FILE, 'utf8'))
        : [];
    } catch {
      return [];
    }
  }
  
  saveHistory() {
    try {
      fs.writeFileSync(HISTORY_FILE, JSON.stringify(this.history, null, 2));
    } catch (e) {
      console.error('Failed to save history:', e);
    }
  }
  
  loadPreferences() {
    try {
      return fs.existsSync(PREFS_FILE)
        ? JSON.parse(fs.readFileSync(PREFS_FILE, 'utf8'))
        : {};
    } catch {
      return {};
    }
  }
  
  savePreferences() {
    try {
      fs.writeFileSync(PREFS_FILE, JSON.stringify(this.preferences, null, 2));
    } catch (e) {
      console.error('Failed to save preferences:', e);
    }
  }
  
  loadModels() {
    try {
      return fs.existsSync(MODELS_FILE)
        ? JSON.parse(fs.readFileSync(MODELS_FILE, 'utf8'))
        : {};
    } catch {
      return {};
    }
  }
}

// ============================================================
// 全局实例
// ============================================================

let globalEngine = null;

function getEngine() {
  if (!globalEngine) {
    globalEngine = new DecisionEngine();
  }
  return globalEngine;
}

// ============================================================
// 兼容旧API
// ============================================================

function make(args = {}) {
  const engine = getEngine();
  const context = typeof args === 'object' ? args : { options: [] };
  const options = args.options || (Array.isArray(args) ? args : []);
  const strategy = args.strategy || 'weighted';
  
  return engine.decide(options, { ...context, strategy });
}

function updatePreference(key, value) {
  const engine = getEngine();
  engine.preferences[key] = value;
  engine.savePreferences();
  return { status: 'ok', key, value };
}

// ============================================================
// 导出
// ============================================================

module.exports = {
  // 核心类
  DecisionEngine,
  DecisionStrategy,
  getEngine,
  
  // 兼容旧API
  make,
  updatePreference,
  
  // 新API
  decide: (options, context) => getEngine().decide(options, context),
  feedback: (decisionId, outcome, reward) => getEngine().feedback(decisionId, outcome, reward),
  getHistory: () => getEngine().history,
  getPreferences: () => getEngine().preferences
};
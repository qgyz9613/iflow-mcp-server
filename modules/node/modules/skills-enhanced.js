/**
 * Skills Enhanced Module
 * 增强技能系统（基于OpenClaw设计）
 * 支持版本管理、缓存优化、环境隔离、依赖图分析
 */

const path = require('path');
const fs = require('fs').promises;
const crypto = require('crypto');
const { execSync } = require('child_process');
const { v4: uuidv4 } = require('uuid');

// ==================== 常量定义 ====================

const SKILLS_ENHANCED_DIR = path.join(__dirname, '..', 'skills-enhanced-data');
const CACHE_DIR = path.join(SKILLS_ENHANCED_DIR, 'cache');
const VERSIONS_DIR = path.join(SKILLS_ENHANCED_DIR, 'versions');
const ENVIRONMENTS_DIR = path.join(SKILLS_ENHANCED_DIR, 'environments');

// 确保目录存在
async function ensureDirectories() {
  const dirs = [SKILLS_ENHANCED_DIR, CACHE_DIR, VERSIONS_DIR, ENVIRONMENTS_DIR];
  for (const dir of dirs) {
    try {
      await fs.mkdir(dir, { recursive: true });
    } catch (err) {
      console.warn(`[SkillsEnhanced] Failed to create directory ${dir}: ${err.message}`);
    }
  }
}

// ==================== 技能版本管理 ====================

/**
 * 技能版本
 */
class SkillVersion {
  constructor(data = {}) {
    this.version = data.version || '1.0.0';
    this.semver = this._parseSemver(this.version);
    this.createdAt = data.createdAt || new Date().toISOString();
    this.installedAt = data.installedAt || null;
    this.changelog = data.changelog || [];
    this.checksum = data.checksum || null;
    this.size = data.size || 0;
  }
  
  /**
   * 解析语义化版本
   */
  _parseSemver(version) {
    const match = version.match(/^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9.-]+))?$/);
    if (!match) {
      return { major: 0, minor: 0, patch: 0, prerelease: null };
    }
    
    return {
      major: parseInt(match[1]),
      minor: parseInt(match[2]),
      patch: parseInt(match[3]),
      prerelease: match[4] || null
    };
  }
  
  /**
   * 比较版本
   */
  compare(other) {
    if (this.semver.major !== other.semver.major) {
      return this.semver.major - other.semver.major;
    }
    if (this.semver.minor !== other.semver.minor) {
      return this.semver.minor - other.semver.minor;
    }
    if (this.semver.patch !== other.semver.patch) {
      return this.semver.patch - other.semver.patch;
    }
    
    // 处理预发布版本
    if (this.semver.prerelease && !other.semver.prerelease) {
      return -1;
    }
    if (!this.semver.prerelease && other.semver.prerelease) {
      return 1;
    }
    if (this.semver.prerelease && other.semver.prerelease) {
      return this.semver.prerelease.localeCompare(other.semver.prerelease);
    }
    
    return 0;
  }
  
  /**
   * 是否比其他版本新
   */
  isNewerThan(other) {
    return this.compare(other) > 0;
  }
  
  /**
   * 转换为对象
   */
  toObject() {
    return {
      version: this.version,
      semver: this.semver,
      createdAt: this.createdAt,
      installedAt: this.installedAt,
      changelog: this.changelog,
      checksum: this.checksum,
      size: this.size
    };
  }
  
  /**
   * 从对象创建
   */
  static fromObject(obj) {
    return new SkillVersion(obj);
  }
}

// ==================== 技能缓存 ====================

/**
 * 技能缓存条目
 */
class SkillCacheEntry {
  constructor(key, data = {}) {
    this.key = key;
    this.data = data.data || null;
    this.createdAt = data.createdAt || new Date().toISOString();
    this.accessedAt = data.accessedAt || new Date().toISOString();
    this.hits = data.hits || 0;
    this.size = data.size || 0;
    this.ttl = data.ttl || 3600000;  // 默认1小时
    this.maxAge = data.maxAge || 86400000;  // 默认1天
  }
  
  /**
   * 检查是否过期
   */
  isExpired() {
    const now = Date.now();
    const age = now - new Date(this.createdAt).getTime();
    return age > this.maxAge;
  }
  
  /**
   * 检查是否需要刷新
   */
  needsRefresh() {
    const now = Date.now();
    const age = now - new Date(this.accessedAt).getTime();
    return age > this.ttl;
  }
  
  /**
   * 访问缓存
   */
  access() {
    this.accessedAt = new Date().toISOString();
    this.hits++;
  }
  
  /**
   * 转换为对象
   */
  toObject() {
    return {
      key: this.key,
      data: this.data,
      createdAt: this.createdAt,
      accessedAt: this.accessedAt,
      hits: this.hits,
      size: this.size,
      ttl: this.ttl,
      maxAge: this.maxAge
    };
  }
  
  /**
   * 从对象创建
   */
  static fromObject(obj) {
    return new SkillCacheEntry(obj.key, obj);
  }
}

/**
 * 技能缓存管理器
 */
class SkillCacheManager {
  constructor(config = {}) {
    this.maxSize = config.maxSize || 100 * 1024 * 1024;  // 默认100MB
    this.maxEntries = config.maxEntries || 1000;
    this.entries = new Map();
    this.totalSize = 0;
  }
  
  /**
   * 获取缓存
   */
  async get(key) {
    const entry = this.entries.get(key);
    
    if (!entry) {
      return null;
    }
    
    if (entry.isExpired()) {
      await this.delete(key);
      return null;
    }
    
    entry.access();
    await this._saveEntry(entry);
    
    return entry.data;
  }
  
  /**
   * 设置缓存
   */
  async set(key, data, options = {}) {
    const size = this._calculateSize(data);
    
    // 检查是否超过限制
    if (size > this.maxSize) {
      throw new Error('Data size exceeds maximum cache size');
    }
    
    // 如果已存在，先删除
    if (this.entries.has(key)) {
      await this.delete(key);
    }
    
    // 检查是否需要清理空间
    while (this.totalSize + size > this.maxSize || this.entries.size >= this.maxEntries) {
      await this._evict();
    }
    
    const entry = new SkillCacheEntry(key, {
      data,
      size,
      ttl: options.ttl,
      maxAge: options.maxAge
    });
    
    this.entries.set(key, entry);
    this.totalSize += size;
    
    await this._saveEntry(entry);
    
    return entry;
  }
  
  /**
   * 删除缓存
   */
  async delete(key) {
    const entry = this.entries.get(key);
    
    if (entry) {
      this.entries.delete(key);
      this.totalSize -= entry.size;
      
      try {
        await fs.unlink(this._getEntryPath(key));
      } catch (err) {
        console.warn(`[SkillCache] Failed to delete cache file: ${err.message}`);
      }
    }
  }
  
  /**
   * 清空缓存
   */
  async clear() {
    const keys = Array.from(this.entries.keys());
    
    for (const key of keys) {
      await this.delete(key);
    }
  }
  
  /**
   * 清理过期缓存
   */
  async cleanup() {
    const expiredKeys = [];
    
    for (const [key, entry] of this.entries.entries()) {
      if (entry.isExpired()) {
        expiredKeys.push(key);
      }
    }
    
    for (const key of expiredKeys) {
      await this.delete(key);
    }
    
    return expiredKeys.length;
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    return {
      totalEntries: this.entries.size,
      totalSize: this.totalSize,
      maxSize: this.maxSize,
      maxEntries: this.maxEntries,
      usage: this.totalSize / this.maxSize,
      hitRate: this._calculateHitRate()
    };
  }
  
  /**
   * 淘汰最少使用的条目
   */
  async _evict() {
    let lruKey = null;
    let lruEntry = null;
    
    for (const [key, entry] of this.entries.entries()) {
      if (!lruEntry || entry.hits < lruEntry.hits) {
        lruKey = key;
        lruEntry = entry;
      }
    }
    
    if (lruKey) {
      await this.delete(lruKey);
    }
  }
  
  /**
   * 计算数据大小
   */
  _calculateSize(data) {
    try {
      return Buffer.byteLength(JSON.stringify(data), 'utf8');
    } catch {
      return 0;
    }
  }
  
  /**
   * 获取条目文件路径
   */
  _getEntryPath(key) {
    const hash = crypto.createHash('md5').update(key).digest('hex');
    return path.join(CACHE_DIR, `${hash}.json`);
  }
  
  /**
   * 保存条目到文件
   */
  async _saveEntry(entry) {
    try {
      const filePath = this._getEntryPath(entry.key);
      await fs.writeFile(filePath, JSON.stringify(entry.toObject(), null, 2));
    } catch (err) {
      console.warn(`[SkillCache] Failed to save cache entry: ${err.message}`);
    }
  }
  
  /**
   * 计算命中率
   */
  _calculateHitRate() {
    let totalHits = 0;
    let totalAccesses = 0;
    
    for (const entry of this.entries.values()) {
      totalHits += entry.hits;
      totalAccesses += entry.hits + 1;  // +1 for initial set
    }
    
    return totalAccesses > 0 ? totalHits / totalAccesses : 0;
  }
}

// ==================== 技能依赖图 ====================

/**
 * 技能依赖图节点
 */
class SkillDependencyNode {
  constructor(skillName, version) {
    this.id = `${skillName}@${version}`;
    this.skillName = skillName;
    this.version = version;
    this.dependencies = [];
    this.dependents = [];
    this.installed = false;
    this.depth = 0;
  }
}

/**
 * 技能依赖图
 */
class SkillDependencyGraph {
  constructor() {
    this.nodes = new Map();
  }
  
  /**
   * 添加技能节点
   */
  addNode(skillName, version, dependencies = []) {
    const node = new SkillDependencyNode(skillName, version);
    this.nodes.set(node.id, node);
    
    // 添加依赖关系
    for (const dep of dependencies) {
      const depId = `${dep.name}@${dep.version}`;
      
      if (!this.nodes.has(depId)) {
        this.addNode(dep.name, dep.version, dep.dependencies || []);
      }
      
      const depNode = this.nodes.get(depId);
      node.dependencies.push(depId);
      depNode.dependents.push(node.id);
    }
    
    // 计算深度
    this._calculateDepth(node.id);
    
    return node;
  }
  
  /**
   * 获取节点
   */
  getNode(skillName, version) {
    const id = `${skillName}@${version}`;
    return this.nodes.get(id) || null;
  }
  
  /**
   * 获取所有依赖
   */
  getAllDependencies(skillName, version, visited = new Set()) {
    const node = this.getNode(skillName, version);
    
    if (!node || visited.has(node.id)) {
      return [];
    }
    
    visited.add(node.id);
    const deps = [node.id];
    
    for (const depId of node.dependencies) {
      const depNode = this.nodes.get(depId);
      if (depNode) {
        deps.push(...this.getAllDependencies(
          depNode.skillName,
          depNode.version,
          visited
        ));
      }
    }
    
    return [...new Set(deps)];
  }
  
  /**
   * 获取依赖者
   */
  getDependents(skillName, version, visited = new Set()) {
    const node = this.getNode(skillName, version);
    
    if (!node || visited.has(node.id)) {
      return [];
    }
    
    visited.add(node.id);
    const dependents = [node.id];
    
    for (const depId of node.dependents) {
      const depNode = this.nodes.get(depId);
      if (depNode) {
        dependents.push(...this.getDependents(
          depNode.skillName,
          depNode.version,
          visited
        ));
      }
    }
    
    return [...new Set(dependents)];
  }
  
  /**
   * 检查循环依赖
   */
  hasCycle() {
    const visited = new Set();
    const recursionStack = new Set();
    
    for (const nodeId of this.nodes.keys()) {
      if (this._hasCycleDFS(nodeId, visited, recursionStack)) {
        return true;
      }
    }
    
    return false;
  }
  
  /**
   * 深度优先搜索检测循环
   */
  _hasCycleDFS(nodeId, visited, recursionStack) {
    if (recursionStack.has(nodeId)) {
      return true;
    }
    
    if (visited.has(nodeId)) {
      return false;
    }
    
    visited.add(nodeId);
    recursionStack.add(nodeId);
    
    const node = this.nodes.get(nodeId);
    if (node) {
      for (const depId of node.dependencies) {
        if (this._hasCycleDFS(depId, visited, recursionStack)) {
          return true;
        }
      }
    }
    
    recursionStack.delete(nodeId);
    return false;
  }
  
  /**
   * 计算节点深度
   */
  _calculateDepth(nodeId, visited = new Set()) {
    if (visited.has(nodeId)) {
      return 0;
    }
    
    visited.add(nodeId);
    const node = this.nodes.get(nodeId);
    
    if (!node || node.dependencies.length === 0) {
      return 0;
    }
    
    let maxDepDepth = 0;
    for (const depId of node.dependencies) {
      const depDepth = this._calculateDepth(depId, new Set(visited));
      maxDepDepth = Math.max(maxDepDepth, depDepth);
    }
    
    node.depth = maxDepDepth + 1;
    return node.depth;
  }
  
  /**
   * 拓扑排序
   */
  topologicalSort() {
    if (this.hasCycle()) {
      throw new Error('Cannot perform topological sort on graph with cycles');
    }
    
    const sorted = [];
    const visited = new Set();
    
    // 按深度排序
    const nodesByDepth = Array.from(this.nodes.values())
      .sort((a, b) => a.depth - b.depth);
    
    for (const node of nodesByDepth) {
      if (!visited.has(node.id)) {
        this._topologicalSortDFS(node.id, visited, sorted);
      }
    }
    
    return sorted;
  }
  
  /**
   * 深度优先搜索拓扑排序
   */
  _topologicalSortDFS(nodeId, visited, sorted) {
    visited.add(nodeId);
    const node = this.nodes.get(nodeId);
    
    if (node) {
      for (const depId of node.dependencies) {
        if (!visited.has(depId)) {
          this._topologicalSortDFS(depId, visited, sorted);
        }
      }
    }
    
    sorted.push(nodeId);
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    const nodes = Array.from(this.nodes.values());
    
    return {
      totalNodes: nodes.length,
      totalDependencies: nodes.reduce((sum, n) => sum + n.dependencies.length, 0),
      totalDependents: nodes.reduce((sum, n) => sum + n.dependents.length, 0),
      hasCycle: this.hasCycle(),
      maxDepth: Math.max(...nodes.map(n => n.depth)),
      avgDepth: nodes.reduce((sum, n) => sum + n.depth, 0) / nodes.length
    };
  }
}

// ==================== 技能环境管理器 ====================

/**
 * 技能执行环境
 */
class SkillEnvironment {
  constructor(config = {}) {
    this.id = config.id || uuidv4();
    this.name = config.name || `env-${this.id}`;
    this.isolated = config.isolated !== false;
    this.variables = config.variables || {};
    this.paths = config.paths || [];
    this.tools = config.tools || [];
    this.createdAt = config.createdAt || new Date().toISOString();
    this.active = false;
  }
  
  /**
   * 激活环境
   */
  async activate() {
    if (!this.active) {
      this.active = true;
      await this._save();
    }
  }
  
  /**
   * 停用环境
   */
  async deactivate() {
    if (this.active) {
      this.active = false;
      await this._save();
    }
  }
  
  /**
   * 添加变量
   */
  addVariable(key, value) {
    this.variables[key] = value;
  }
  
  /**
   * 移除变量
   */
  removeVariable(key) {
    delete this.variables[key];
  }
  
  /**
   * 添加路径
   */
  addPath(path) {
    if (!this.paths.includes(path)) {
      this.paths.push(path);
    }
  }
  
  /**
   * 添加工具
   */
  addTool(tool) {
    if (!this.tools.includes(tool)) {
      this.tools.push(tool);
    }
  }
  
  /**
   * 转换为对象
   */
  toObject() {
    return {
      id: this.id,
      name: this.name,
      isolated: this.isolated,
      variables: this.variables,
      paths: this.paths,
      tools: this.tools,
      createdAt: this.createdAt,
      active: this.active
    };
  }
  
  /**
   * 保存到文件
   */
  async _save() {
    try {
      const filePath = path.join(ENVIRONMENTS_DIR, `${this.id}.json`);
      await fs.writeFile(filePath, JSON.stringify(this.toObject(), null, 2));
    } catch (err) {
      console.warn(`[SkillEnvironment] Failed to save environment: ${err.message}`);
    }
  }
  
  /**
   * 从对象创建
   */
  static fromObject(obj) {
    return new SkillEnvironment(obj);
  }
}

/**
 * 技能环境管理器
 */
class SkillEnvironmentManager {
  constructor() {
    this.environments = new Map();
  }
  
  /**
   * 创建环境
   */
  async createEnvironment(config = {}) {
    const env = new SkillEnvironment(config);
    this.environments.set(env.id, env);
    await env._save();
    return env;
  }
  
  /**
   * 获取环境
   */
  getEnvironment(envId) {
    return this.environments.get(envId) || null;
  }
  
  /**
   * 删除环境
   */
  async deleteEnvironment(envId) {
    const deleted = this.environments.delete(envId);
    
    if (deleted) {
      try {
        await fs.unlink(path.join(ENVIRONMENTS_DIR, `${envId}.json`));
      } catch (err) {
        console.warn(`[SkillEnvironment] Failed to delete environment file: ${err.message}`);
      }
    }
    
    return deleted;
  }
  
  /**
   * 列出所有环境
   */
  listEnvironments() {
    return Array.from(this.environments.values()).map(env => env.toObject());
  }
}

// ==================== 导出 ====================

module.exports = {
  // 版本管理
  SkillVersion,
  
  // 缓存管理
  SkillCacheEntry,
  SkillCacheManager,
  
  // 依赖图
  SkillDependencyNode,
  SkillDependencyGraph,
  
  // 环境管理
  SkillEnvironment,
  SkillEnvironmentManager,
  
  // 辅助函数
  ensureDirectories
};
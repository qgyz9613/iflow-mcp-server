/**
 * iFlow Session Store Module
 * 会话存储模块（基于OpenClaw sessions/store设计）
 * 
 * 功能:
 * - TTL缓存支持
 * - 原子写入
 * - 磁盘预算管理
 * - 会话维护清理
 */

const fs = require('fs');
const path = require('path');

// ==================== 配置常量 ====================

const DEFAULT_SESSION_STORE_TTL_MS = 45000; // 45秒缓存
const DEFAULT_DISK_BUDGET_MB = 500; // 500MB磁盘预算
const DEFAULT_MAX_SESSIONS = 1000;
const DEFAULT_MAX_ENTRIES_PER_SESSION = 1000;
const MAINTENANCE_INTERVAL_MS = 60000; // 1分钟维护间隔

// ==================== 会话条目类型 ====================

/**
 * 会话条目
 */
class SessionEntry {
  constructor(data = {}) {
    this.sessionId = data.sessionId || generateId();
    this.sessionKey = data.sessionKey || null;
    this.channel = data.channel || null;
    this.createdAt = data.createdAt || Date.now();
    this.updatedAt = data.updatedAt || Date.now();
    this.lastActivity = data.lastActivity || Date.now();
    this.messageCount = data.messageCount || 0;
    this.totalTokens = data.totalTokens || 0;
    this.state = data.state || 'active';
    this.metadata = data.metadata || {};
    this.deliveryContext = data.deliveryContext || null;
    
    // 运行时字段
    this.lastTo = data.lastTo || null;
    this.lastChannel = data.lastChannel || null;
    this.lastAccountId = data.lastAccountId || null;
    this.lastThreadId = data.lastThreadId || null;
  }
  
  toJSON() {
    return {
      sessionId: this.sessionId,
      sessionKey: this.sessionKey,
      channel: this.channel,
      createdAt: this.createdAt,
      updatedAt: this.updatedAt,
      lastActivity: this.lastActivity,
      messageCount: this.messageCount,
      totalTokens: this.totalTokens,
      state: this.state,
      metadata: this.metadata,
      deliveryContext: this.deliveryContext,
      lastTo: this.lastTo,
      lastChannel: this.lastChannel,
      lastAccountId: this.lastAccountId,
      lastThreadId: this.lastThreadId
    };
  }
  
  static fromJSON(data) {
    return new SessionEntry(data);
  }
}

// ==================== 会话存储 ====================

/**
 * 会话存储管理器
 */
class SessionStore {
  constructor(options = {}) {
    this.storePath = options.storePath || './sessions';
    this.ttlMs = options.ttlMs || DEFAULT_SESSION_STORE_TTL_MS;
    this.diskBudgetMb = options.diskBudgetMb || DEFAULT_DISK_BUDGET_MB;
    this.maxSessions = options.maxSessions || DEFAULT_MAX_SESSIONS;
    this.maxEntriesPerSession = options.maxEntriesPerSession || DEFAULT_MAX_ENTRIES_PER_SESSION;
    
    // 内存缓存
    this.cache = new Map();
    this.cacheTimestamps = new Map();
    
    // 脏标记
    this.dirty = new Set();
    this.writePending = null;
    
    // 维护定时器
    this.maintenanceTimer = null;
    
    // 初始化
    this._init();
  }
  
  _init() {
    // 确保目录存在
    if (!fs.existsSync(this.storePath)) {
      fs.mkdirSync(this.storePath, { recursive: true });
    }
    
    // 启动维护定时器
    this._startMaintenance();
  }
  
  // ==================== 缓存操作 ====================
  
  /**
   * 检查缓存是否启用
   */
  isCacheEnabled() {
    return this.ttlMs > 0;
  }
  
  /**
   * 检查缓存是否过期
   */
  isCacheExpired(key) {
    if (!this.isCacheEnabled()) return true;
    
    const timestamp = this.cacheTimestamps.get(key);
    if (!timestamp) return true;
    
    return Date.now() - timestamp > this.ttlMs;
  }
  
  /**
   * 获取缓存
   */
  getFromCache(key) {
    if (!this.isCacheEnabled()) return null;
    if (this.isCacheExpired(key)) {
      this.cache.delete(key);
      this.cacheTimestamps.delete(key);
      return null;
    }
    
    return this.cache.get(key);
  }
  
  /**
   * 设置缓存
   */
  setCache(key, value) {
    if (!this.isCacheEnabled()) return;
    
    this.cache.set(key, value);
    this.cacheTimestamps.set(key, Date.now());
  }
  
  /**
   * 清除缓存
   */
  clearCache(key = null) {
    if (key) {
      this.cache.delete(key);
      this.cacheTimestamps.delete(key);
    } else {
      this.cache.clear();
      this.cacheTimestamps.clear();
    }
  }
  
  // ==================== 会话操作 ====================
  
  /**
   * 获取会话
   */
  getSession(sessionKey) {
    // 先检查缓存
    const cached = this.getFromCache(sessionKey);
    if (cached) return cached;
    
    // 从文件加载
    const filePath = this._getSessionFilePath(sessionKey);
    if (!fs.existsSync(filePath)) return null;
    
    try {
      const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
      const entry = SessionEntry.fromJSON(data);
      this.setCache(sessionKey, entry);
      return entry;
    } catch (err) {
      console.error(`Failed to load session ${sessionKey}:`, err);
      return null;
    }
  }
  
  /**
   * 保存会话
   */
  async saveSession(sessionKey, entry) {
    // 更新时间戳
    entry.updatedAt = Date.now();
    
    // 更新缓存
    this.setCache(sessionKey, entry);
    
    // 标记脏
    this.dirty.add(sessionKey);
    
    // 触发写入
    await this._scheduleWrite();
  }
  
  /**
   * 创建或更新会话
   */
  async upsertSession(sessionKey, data = {}) {
    let entry = this.getSession(sessionKey);
    
    if (entry) {
      // 更新现有条目
      entry = this._mergeEntry(entry, data);
    } else {
      // 创建新条目
      entry = new SessionEntry({
        sessionKey,
        ...data
      });
    }
    
    await this.saveSession(sessionKey, entry);
    return entry;
  }
  
  /**
   * 合并条目
   */
  _mergeEntry(existing, updates) {
    const merged = new SessionEntry(existing.toJSON());
    
    // 更新字段
    for (const [key, value] of Object.entries(updates)) {
      if (value !== undefined && value !== null) {
        if (key === 'metadata' && typeof value === 'object') {
          merged.metadata = { ...merged.metadata, ...value };
        } else if (key === 'deliveryContext' && typeof value === 'object') {
          merged.deliveryContext = { ...merged.deliveryContext, ...value };
        } else {
          merged[key] = value;
        }
      }
    }
    
    return merged;
  }
  
  /**
   * 删除会话
   */
  async deleteSession(sessionKey) {
    // 从缓存删除
    this.cache.delete(sessionKey);
    this.cacheTimestamps.delete(sessionKey);
    
    // 从脏集合删除
    this.dirty.delete(sessionKey);
    
    // 删除文件
    const filePath = this._getSessionFilePath(sessionKey);
    if (fs.existsSync(filePath)) {
      await fs.promises.unlink(filePath);
    }
  }
  
  /**
   * 列出所有会话
   */
  listSessions() {
    const sessions = [];
    
    if (!fs.existsSync(this.storePath)) return sessions;
    
    const files = fs.readdirSync(this.storePath);
    for (const file of files) {
      if (file.endsWith('.json')) {
        const sessionKey = file.replace('.json', '');
        const entry = this.getSession(sessionKey);
        if (entry) {
          sessions.push(entry);
        }
      }
    }
    
    return sessions;
  }
  
  // ==================== 写入操作 ====================
  
  /**
   * 调度写入
   */
  async _scheduleWrite() {
    if (this.writePending) return;
    
    this.writePending = this._flushWrites();
    await this.writePending;
    this.writePending = null;
  }
  
  /**
   * 刷新写入
   */
  async _flushWrites() {
    const toWrite = Array.from(this.dirty);
    this.dirty.clear();
    
    for (const sessionKey of toWrite) {
      const entry = this.getFromCache(sessionKey);
      if (!entry) continue;
      
      await this._writeSessionFile(sessionKey, entry);
    }
  }
  
  /**
   * 原子写入会话文件
   */
  async _writeSessionFile(sessionKey, entry) {
    const filePath = this._getSessionFilePath(sessionKey);
    const tempPath = `${filePath}.tmp`;
    
    try {
      // 写入临时文件
      await fs.promises.writeFile(tempPath, JSON.stringify(entry.toJSON(), null, 2), {
        encoding: 'utf-8',
        mode: 0o600
      });
      
      // 原子重命名
      await fs.promises.rename(tempPath, filePath);
    } catch (err) {
      // 清理临时文件
      if (fs.existsSync(tempPath)) {
        await fs.promises.unlink(tempPath);
      }
      throw err;
    }
  }
  
  /**
   * 获取会话文件路径
   */
  _getSessionFilePath(sessionKey) {
    return path.join(this.storePath, `${sessionKey}.json`);
  }
  
  // ==================== 维护操作 ====================
  
  /**
   * 启动维护
   */
  _startMaintenance() {
    this.maintenanceTimer = setInterval(() => {
      this._runMaintenance();
    }, MAINTENANCE_INTERVAL_MS);
    
    // 不阻止进程退出
    if (this.maintenanceTimer.unref) {
      this.maintenanceTimer.unref();
    }
  }
  
  /**
   * 停止维护
   */
  stopMaintenance() {
    if (this.maintenanceTimer) {
      clearInterval(this.maintenanceTimer);
      this.maintenanceTimer = null;
    }
  }
  
  /**
   * 运行维护
   */
  async _runMaintenance() {
    // 1. 清理过期缓存
    this._cleanupExpiredCache();
    
    // 2. 清理旧会话
    await this._cleanupOldSessions();
    
    // 3. 检查磁盘预算
    await this._checkDiskBudget();
  }
  
  /**
   * 清理过期缓存
   */
  _cleanupExpiredCache() {
    const now = Date.now();
    
    for (const [key, timestamp] of this.cacheTimestamps) {
      if (now - timestamp > this.ttlMs) {
        this.cache.delete(key);
        this.cacheTimestamps.delete(key);
      }
    }
  }
  
  /**
   * 清理旧会话
   */
  async _cleanupOldSessions() {
    const sessions = this.listSessions();
    
    // 按活动时间排序
    sessions.sort((a, b) => b.lastActivity - a.lastActivity);
    
    // 超过最大数量时删除最旧的
    if (sessions.length > this.maxSessions) {
      const toDelete = sessions.slice(this.maxSessions);
      
      for (const session of toDelete) {
        await this.deleteSession(session.sessionKey);
      }
    }
  }
  
  /**
   * 检查磁盘预算
   */
  async _checkDiskBudget() {
    const stats = await this._getDiskUsage();
    
    if (stats.totalMb > this.diskBudgetMb) {
      // 删除最旧的会话直到满足预算
      const sessions = this.listSessions();
      sessions.sort((a, b) => b.lastActivity - a.lastActivity);
      
      for (const session of sessions) {
        if (stats.totalMb <= this.diskBudgetMb) break;
        
        await this.deleteSession(session.sessionKey);
        stats.totalMb -= session.sizeMb || 0;
      }
    }
  }
  
  /**
   * 获取磁盘使用情况
   */
  async _getDiskUsage() {
    let totalBytes = 0;
    let fileCount = 0;
    
    if (fs.existsSync(this.storePath)) {
      const files = fs.readdirSync(this.storePath);
      
      for (const file of files) {
        const filePath = path.join(this.storePath, file);
        const stat = fs.statSync(filePath);
        totalBytes += stat.size;
        fileCount++;
      }
    }
    
    return {
      totalBytes,
      totalMb: totalBytes / (1024 * 1024),
      fileCount
    };
  }
  
  // ==================== 关闭 ====================
  
  /**
   * 关闭存储
   */
  async close() {
    // 停止维护
    this.stopMaintenance();
    
    // 刷新写入
    await this._flushWrites();
    
    // 清理缓存
    this.clearCache();
  }
}

// ==================== 辅助函数 ====================

/**
 * 生成唯一ID
 */
function generateId() {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * 规范化会话键
 */
function normalizeSessionKey(key) {
  if (!key) return null;
  return key.trim().toLowerCase();
}

// ==================== 导出 ====================

module.exports = {
  SessionEntry,
  SessionStore,
  generateId,
  normalizeSessionKey,
  
  // 常量
  DEFAULT_SESSION_STORE_TTL_MS,
  DEFAULT_DISK_BUDGET_MB,
  DEFAULT_MAX_SESSIONS,
  DEFAULT_MAX_ENTRIES_PER_SESSION,
  MAINTENANCE_INTERVAL_MS
};

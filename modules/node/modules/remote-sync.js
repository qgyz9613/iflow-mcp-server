/**
 * iFlow Remote Sync Module
 * 远程数据库同步 - 双重存储（本地+远程）
 * 支持记忆、对话、配置的云端备份和同步
 * 
 * 配置:
 * - 远程API: http://192.168.100.216:18080
 * - 本地存储: SQLite (memory.db)
 * - 失败不影响本地存储
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');
const https = require('https');
const http = require('http');

// 集成 SQLite 记忆后端
const { MemoryDatabase, DATA_DIR: SQLITE_DATA_DIR } = require('./sqlite-memory');

const DATA_DIR = path.join(__dirname, '..', 'remote-sync-data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

// ==================== 默认配置 ====================

const DEFAULT_CONFIG = {
  api: {
    baseUrl: 'http://192.168.100.216:18080',  // 远程API地址
    timeout: 30000,
    retryCount: 3,
    retryDelay: 1000
  },
  memory: {
    enabled: true,
    autoSync: true,
    syncInterval: 60000,  // 1分钟
    useSQLite: true       // 使用SQLite本地存储
  }
};

// ==================== 远程 API 客户端 ====================

class RemoteAPIClient {
  constructor(config = {}) {
    this.baseUrl = config.baseUrl || 'http://localhost:18080';
    this.apiKey = config.apiKey || null;
    this.timeout = config.timeout || 30000;
    this.retryCount = config.retryCount || 3;
    this.retryDelay = config.retryDelay || 1000;
  }
  
  /**
   * 发送请求
   */
  async request(method, endpoint, data = null) {
    const url = new URL(`${this.baseUrl}${endpoint}`);
    const isHttps = url.protocol === 'https:';
    const client = isHttps ? https : http;
    
    return new Promise((resolve, reject) => {
      const options = {
        hostname: url.hostname,
        port: url.port || (isHttps ? 443 : 80),
        path: url.pathname + url.search,
        method: method,
        headers: {
          'Content-Type': 'application/json',
          ...(this.apiKey ? { 'Authorization': `Bearer ${this.apiKey}` } : {})
        }
      };
      
      const req = client.request(options, (res) => {
        let body = '';
        res.on('data', chunk => body += chunk);
        res.on('end', () => {
          if (res.statusCode >= 200 && res.statusCode < 300) {
            try {
              resolve(JSON.parse(body));
            } catch {
              resolve({ raw: body });
            }
          } else {
            reject(new Error(`HTTP ${res.statusCode}: ${body.slice(0, 500)}`));
          }
        });
      });
      
      req.on('error', reject);
      req.setTimeout(this.timeout, () => {
        req.destroy();
        reject(new Error('Request timeout'));
      });
      
      if (data) {
        req.write(JSON.stringify(data));
      }
      req.end();
    });
  }
  
  /**
   * GET 请求
   */
  async get(endpoint) {
    return this.request('GET', endpoint);
  }
  
  /**
   * POST 请求
   */
  async post(endpoint, data) {
    return this.request('POST', endpoint, data);
  }
  
  /**
   * PUT 请求
   */
  async put(endpoint, data) {
    return this.request('PUT', endpoint, data);
  }
  
  /**
   * DELETE 请求
   */
  async delete(endpoint) {
    return this.request('DELETE', endpoint);
  }
}

// ==================== 记忆同步器 ====================

class MemorySync {
  constructor(config = {}) {
    this.client = new RemoteAPIClient(config.api || DEFAULT_CONFIG.api);
    this.enabled = config.enabled !== false;
    this.syncInterval = config.syncInterval || 60000;  // 1分钟
    this.lastSync = null;
    this.pendingWrites = [];
    this.syncTimer = null;
    
    // 本地存储 - 使用 SQLite
    this.useSQLite = config.useSQLite !== false;
    this.sqliteDb = null;
    
    // JSON 降级路径
    this.localPath = config.localPath || path.join(DATA_DIR, 'memories.json');
    
    // 初始化 SQLite
    this._initSQLite();
    
    // 启动定时同步
    if (this.enabled && config.autoSync !== false) {
      this.startAutoSync();
    }
  }
  
  /**
   * 初始化 SQLite 存储
   */
  async _initSQLite() {
    if (this.useSQLite) {
      try {
        this.sqliteDb = new MemoryDatabase();
        await this.sqliteDb.init();
        console.log('[MemorySync] SQLite backend initialized');
      } catch (e) {
        console.warn('[MemorySync] SQLite init failed, using JSON fallback:', e.message);
        this.useSQLite = false;
        this._loadLocal();
      }
    } else {
      this._loadLocal();
    }
  }
  
  /**
   * 双重保存 (本地 + 远程)
   * @param {string} content - 记忆内容
   * @param {string} category - 分类 (general/trading/knowledge/skill/error等)
   * @param {number} importance - 重要性 1-10
   * @returns {Promise<{status, id, local, remote, time}>}
   */
  async saveMemoryDual(content, category = 'general', importance = 5) {
    const start = Date.now();
    const id = uuidv4();
    const now = new Date().toISOString();
    
    const memory = {
      id,
      content,
      category,
      tags: [category],
      importance,
      createdAt: now,
      updatedAt: now,
      source: 'iflow',
      synced: false
    };
    
    // 1. 本地保存 (SQLite 或 JSON)
    try {
      await this._saveLocalMemory(memory);
    } catch (e) {
      console.error('[MemorySync] Local save failed:', e.message);
      return { status: 'error', stage: 'local', message: e.message, time: Date.now() - start };
    }
    
    // 2. 远程保存 (异步，失败不影响本地)
    if (this.enabled) {
      this._syncToRemote(memory, id, start).catch(e => {
        // 远程失败，加入待同步队列
        this.pendingWrites.push({ type: 'save', memory });
        console.warn('[MemorySync] Remote sync failed, queued for retry:', e.message);
      });
    }
    
    return { 
      status: 'ok', 
      id, 
      local: true, 
      remote: this.enabled ? 'pending' : false,
      time: Date.now() - start 
    };
  }
  
  /**
   * 异步同步到远程
   */
  async _syncToRemote(memory, id, startTime) {
    try {
      const remoteResult = await this.client.post('/api/memories', memory);
      memory.synced = true;
      memory.remoteId = remoteResult.id || remoteResult._id;
      
      // 更新本地同步状态
      await this._updateSyncStatus(id, memory.remoteId);
      
      console.log(`[MemorySync] Synced to remote: ${id} -> ${memory.remoteId}`);
    } catch (e) {
      throw e;
    }
  }
  
  /**
   * 保存到本地存储
   */
  async _saveLocalMemory(memory) {
    if (this.useSQLite && this.sqliteDb) {
      // 转换为 SQLite 文档格式
      const doc = {
        id: memory.id,
        path: `/memories/${memory.category}/${memory.id}`,
        startLine: 0,
        endLine: 0,
        text: memory.content,
        source: memory.category,
        model: 'iflow-memory'
      };
      this.sqliteDb.insertDocument(doc);
    } else {
      // JSON 降级
      const localData = this._loadLocal();
      localData.push(memory);
      this._saveLocal(localData);
    }
  }
  
  /**
   * 更新同步状态
   */
  async _updateSyncStatus(id, remoteId) {
    if (this.useSQLite && this.sqliteDb) {
      // SQLite 模式：更新文档 source 字段标记已同步
      const doc = this.sqliteDb.getDocument(id);
      if (doc) {
        doc.source = `${doc.source}:synced:${remoteId}`;
        this.sqliteDb.insertDocument(doc);
      }
    } else {
      // JSON 模式
      const localData = this._loadLocal();
      const idx = localData.findIndex(m => m.id === id);
      if (idx >= 0) {
        localData[idx].synced = true;
        localData[idx].remoteId = remoteId;
        this._saveLocal(localData);
      }
    }
  }
  
  /**
   * 从远程加载记忆
   */
  async loadFromRemote(options = {}) {
    const start = Date.now();
    
    if (!this.enabled) {
      return { status: 'error', message: 'Remote sync disabled', time: Date.now() - start };
    }
    
    try {
      const memories = await this.client.get('/api/memories');
      
      if (options.merge) {
        // 合并本地和远程
        const localData = this._loadLocal();
        const merged = this._mergeMemories(localData, memories);
        this._saveLocal(merged);
        return { status: 'ok', count: merged.length, merged: true, time: Date.now() - start };
      }
      
      // 覆盖本地
      this._saveLocal(memories);
      return { status: 'ok', count: memories.length, time: Date.now() - start };
    } catch (e) {
      return { status: 'error', message: e.message, time: Date.now() - start };
    }
  }
  
  /**
   * 推送本地到远程
   */
  async pushToRemote() {
    const start = Date.now();
    
    if (!this.enabled) {
      return { status: 'error', message: 'Remote sync disabled' };
    }
    
    try {
      const localData = this._loadLocal();
      const unsynced = localData.filter(m => !m.synced);
      
      if (unsynced.length === 0) {
        return { status: 'ok', pushed: 0, message: 'All synced' };
      }
      
      const results = [];
      for (const memory of unsynced) {
        try {
          const result = await this.client.post('/api/memories', memory);
          memory.synced = true;
          memory.remoteId = result.id || result._id;
          results.push({ id: memory.id, success: true });
        } catch (e) {
          results.push({ id: memory.id, success: false, error: e.message });
        }
      }
      
      // 更新本地
      this._saveLocal(localData);
      
      const successCount = results.filter(r => r.success).length;
      this.lastSync = new Date().toISOString();
      
      return { 
        status: successCount === unsynced.length ? 'ok' : 'partial',
        pushed: successCount,
        total: unsynced.length,
        results,
        time: Date.now() - start
      };
    } catch (e) {
      return { status: 'error', message: e.message, time: Date.now() - start };
    }
  }
  
  /**
   * 拉取远程到本地
   */
  async pullFromRemote() {
    const start = Date.now();
    
    if (!this.enabled) {
      return { status: 'error', message: 'Remote sync disabled' };
    }
    
    try {
      const remoteMemories = await this.client.get('/api/memories');
      const localData = this._loadLocal();
      
      // 合并（保留本地未同步的）
      const merged = this._mergeMemories(localData, remoteMemories);
      this._saveLocal(merged);
      
      this.lastSync = new Date().toISOString();
      
      return { 
        status: 'ok', 
        pulled: remoteMemories.length, 
        total: merged.length,
        time: Date.now() - start 
      };
    } catch (e) {
      return { status: 'error', message: e.message, time: Date.now() - start };
    }
  }
  
  /**
   * 完整同步
   */
  async fullSync() {
    const start = Date.now();
    
    // 先推送
    const pushResult = await this.pushToRemote();
    
    // 再拉取
    const pullResult = await this.pullFromRemote();
    
    return {
      status: pushResult.status === 'ok' && pullResult.status === 'ok' ? 'ok' : 'partial',
      push: pushResult,
      pull: pullResult,
      time: Date.now() - start
    };
  }
  
  /**
   * 开始自动同步
   */
  startAutoSync() {
    if (this.syncTimer) return;
    
    this.syncTimer = setInterval(() => {
      if (this.pendingWrites.length > 0) {
        this.fullSync().catch(e => console.warn('[MemorySync] Auto sync failed:', e.message));
      }
    }, this.syncInterval);
    
    console.log(`[MemorySync] Auto sync started (interval: ${this.syncInterval}ms)`);
  }
  
  /**
   * 停止自动同步
   */
  stopAutoSync() {
    if (this.syncTimer) {
      clearInterval(this.syncTimer);
      this.syncTimer = null;
      console.log('[MemorySync] Auto sync stopped');
    }
  }
  
  /**
   * 合并记忆
   */
  _mergeMemories(local, remote) {
    const byId = new Map();
    
    // 添加本地
    for (const m of local) {
      byId.set(m.id, m);
    }
    
    // 合并远程（远程优先，除非本地有未同步的修改）
    for (const rm of remote) {
      const existing = byId.get(rm.id);
      if (!existing || existing.synced) {
        byId.set(rm.id, { ...rm, synced: true });
      }
    }
    
    return Array.from(byId.values());
  }
  
  /**
   * 加载本地数据
   */
  _loadLocal() {
    if (fs.existsSync(this.localPath)) {
      try {
        return JSON.parse(fs.readFileSync(this.localPath, 'utf8'));
      } catch {
        return [];
      }
    }
    return [];
  }
  
  /**
   * 保存本地数据
   */
  _saveLocal(data) {
    fs.writeFileSync(this.localPath, JSON.stringify(data, null, 2));
  }
  
  /**
   * 获取同步状态
   */
  getStatus() {
    const localData = this._loadLocal();
    const synced = localData.filter(m => m.synced).length;
    
    return {
      enabled: this.enabled,
      autoSync: !!this.syncTimer,
      syncInterval: this.syncInterval,
      lastSync: this.lastSync,
      local: {
        total: localData.length,
        synced,
        pending: localData.length - synced
      },
      pendingWrites: this.pendingWrites.length
    };
  }
}

// ==================== 对话同步器 ====================

class ConversationSync {
  constructor(config = {}) {
    this.client = new RemoteAPIClient(config.api || {});
    this.enabled = config.enabled !== false;
    this.localPath = config.localPath || path.join(DATA_DIR, 'conversations');
    
    if (!fs.existsSync(this.localPath)) {
      fs.mkdirSync(this.localPath, { recursive: true });
    }
  }
  
  /**
   * 保存对话
   */
  async saveConversation(sessionId, messages, summary = null) {
    const start = Date.now();
    const now = new Date().toISOString();
    
    const conversation = {
      id: sessionId,
      messages,
      summary,
      messageCount: messages.length,
      createdAt: now,
      updatedAt: now
    };
    
    // 本地保存
    const localFile = path.join(this.localPath, `${sessionId}.json`);
    fs.writeFileSync(localFile, JSON.stringify(conversation, null, 2));
    
    // 远程保存
    if (this.enabled) {
      try {
        await this.client.post('/api/conversations', conversation);
        return { status: 'ok', id: sessionId, dual: true, time: Date.now() - start };
      } catch (e) {
        return { status: 'partial', id: sessionId, local: true, remote: false, message: e.message, time: Date.now() - start };
      }
    }
    
    return { status: 'ok', id: sessionId, dual: false, time: Date.now() - start };
  }
  
  /**
   * 加载对话
   */
  async loadConversation(sessionId) {
    const start = Date.now();
    
    // 优先本地
    const localFile = path.join(this.localPath, `${sessionId}.json`);
    if (fs.existsSync(localFile)) {
      const local = JSON.parse(fs.readFileSync(localFile, 'utf8'));
      return { status: 'ok', conversation: local, source: 'local', time: Date.now() - start };
    }
    
    // 尝试远程
    if (this.enabled) {
      try {
        const remote = await this.client.get(`/api/conversations/${sessionId}`);
        return { status: 'ok', conversation: remote, source: 'remote', time: Date.now() - start };
      } catch (e) {
        return { status: 'error', message: e.message, time: Date.now() - start };
      }
    }
    
    return { status: 'error', message: 'Conversation not found', time: Date.now() - start };
  }
  
  /**
   * 列出对话
   */
  async listConversations(limit = 20) {
    const start = Date.now();
    
    // 本地列表
    const localFiles = fs.readdirSync(this.localPath).filter(f => f.endsWith('.json'));
    const localConversations = localFiles.map(f => {
      try {
        const data = JSON.parse(fs.readFileSync(path.join(this.localPath, f), 'utf8'));
        return {
          id: data.id,
          summary: data.summary?.slice(0, 100),
          messageCount: data.messageCount,
          updatedAt: data.updatedAt
        };
      } catch {
        return null;
      }
    }).filter(Boolean);
    
    return { 
      status: 'ok', 
      conversations: localConversations.slice(0, limit), 
      total: localFiles.length,
      time: Date.now() - start 
    };
  }
}

// ==================== 主同步管理器 ====================

class RemoteSyncManager {
  constructor(config = {}) {
    // 合并默认配置
    this.config = {
      api: { ...DEFAULT_CONFIG.api, ...config.api },
      memory: { ...DEFAULT_CONFIG.memory, ...config.memory },
      conversation: config.conversation || {}
    };
    
    this.memory = new MemorySync({ api: this.config.api, ...this.config.memory });
    this.conversation = new ConversationSync({ api: this.config.api, ...this.config.conversation });
    
    // 连接状态
    this.connected = false;
    this._checkConnection();
  }
  
  /**
   * 检查连接
   */
  async _checkConnection() {
    try {
      const client = new RemoteAPIClient(this.config.api);
      await client.get('/health');
      this.connected = true;
      console.log(`[RemoteSync] Connected to remote server: ${this.config.api.baseUrl}`);
    } catch (e) {
      this.connected = false;
      console.warn(`[RemoteSync] Remote server unavailable (${this.config.api.baseUrl}):`, e.message);
    }
  }
  
  /**
   * 测试连接
   */
  async testConnection() {
    try {
      const client = new RemoteAPIClient(this.config.api || {});
      const result = await client.get('/health');
      this.connected = true;
      return { status: 'ok', connected: true, ...result };
    } catch (e) {
      this.connected = false;
      return { status: 'error', connected: false, message: e.message };
    }
  }
  
  /**
   * 完整同步所有数据
   */
  async syncAll() {
    const start = Date.now();
    
    const memorySync = await this.memory.fullSync();
    
    return {
      status: memorySync.status,
      memory: memorySync,
      time: Date.now() - start
    };
  }
  
  /**
   * 获取完整状态
   */
  getStatus() {
    return {
      connected: this.connected,
      memory: this.memory.getStatus(),
      api: {
        baseUrl: this.config.api?.baseUrl,
        timeout: this.config.api?.timeout || 30000
      }
    };
  }
  
  /**
   * 启动所有自动同步
   */
  startAllAutoSync() {
    this.memory.startAutoSync();
    console.log('[RemoteSync] All auto sync started');
  }
  
  /**
   * 停止所有自动同步
   */
  stopAllAutoSync() {
    this.memory.stopAutoSync();
    console.log('[RemoteSync] All auto sync stopped');
  }
}

// ==================== 便捷函数 ====================

/**
 * 创建默认记忆同步器
 */
function createDefaultMemorySync() {
  return new MemorySync(DEFAULT_CONFIG.memory);
}

/**
 * 快速双重保存记忆
 * @param {string} content - 记忆内容
 * @param {string} category - 分类
 * @param {number} importance - 重要性 1-10
 */
let _defaultSync = null;
async function saveMemoryDual(content, category = 'general', importance = 5) {
  if (!_defaultSync) {
    _defaultSync = createDefaultMemorySync();
  }
  return _defaultSync.saveMemoryDual(content, category, importance);
}

// ==================== 导出 ====================

module.exports = {
  RemoteSyncManager,
  MemorySync,
  ConversationSync,
  RemoteAPIClient,
  
  // 默认配置
  DEFAULT_CONFIG,
  
  // 便捷方法
  createManager: (config) => new RemoteSyncManager({ ...DEFAULT_CONFIG, ...config }),
  createDefaultMemorySync,
  saveMemoryDual
};

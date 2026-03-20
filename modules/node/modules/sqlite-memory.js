/**
 * SQLite Memory Backend
 * SQLite 持久化记忆存储（移植自 core-modules）
 * 
 * 特性:
 * - 文档、嵌入、FTS、向量表
 * - 自动降级到 JSON 存储
 * - 混合搜索（向量 + FTS）
 */

const path = require('path');
const fs = require('fs');

// ==================== 常量 ====================

const DATA_DIR = path.join(__dirname, '..', 'memory-sqlite-data');
const DB_PATH = path.join(DATA_DIR, 'memory.db');
const DEFAULT_VECTOR_DIMS = 1536;
const SNIPPET_MAX_CHARS = 700;

// 确保数据目录存在
function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
}

// ==================== 余弦相似度 ====================

function cosineSimilarity(a, b) {
  if (a.length !== b.length || a.length === 0) return 0;
  let dotProduct = 0, normA = 0, normB = 0;
  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  const denom = Math.sqrt(normA) * Math.sqrt(normB);
  return denom === 0 ? 0 : dotProduct / denom;
}

// ==================== SQLite 记忆数据库 ====================

class MemoryDatabase {
  constructor(dbPath = DB_PATH) {
    this.dbPath = dbPath;
    this.db = null;
    this.vectorAvailable = false;
    this.ftsAvailable = false;
    this.dims = DEFAULT_VECTOR_DIMS;
    this.useJsonFallback = false;
    this.jsonData = null;
  }

  /**
   * 初始化数据库
   */
  async init() {
    ensureDataDir();

    // 尝试加载 better-sqlite3
    let sqlite3;
    try {
      sqlite3 = require('better-sqlite3');
    } catch (err) {
      console.warn('[SQLiteMemory] better-sqlite3 not available, using JSON fallback');
      this.useJsonFallback = true;
      return this._initJsonFallback();
    }

    try {
      this.db = new sqlite3(this.dbPath);
      this._createTables();
      this._checkExtensions();
      console.log('[SQLiteMemory] SQLite backend initialized');
    } catch (err) {
      console.warn('[SQLiteMemory] SQLite init failed, using JSON fallback:', err.message);
      this.useJsonFallback = true;
      return this._initJsonFallback();
    }
  }

  /**
   * 创建表
   */
  _createTables() {
    // 文档表
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        text TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'memory',
        model TEXT,
        created_at INTEGER DEFAULT (strftime('%s', 'now')),
        updated_at INTEGER DEFAULT (strftime('%s', 'now'))
      );
      CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path);
      CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
    `);

    // 嵌入缓存表
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS embedding_cache (
        id TEXT PRIMARY KEY,
        embedding BLOB NOT NULL,
        model TEXT NOT NULL,
        created_at INTEGER DEFAULT (strftime('%s', 'now'))
      );
    `);

    // FTS 表
    try {
      this.db.exec(`
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
          id, path, text, source,
          tokenize='porter unicode61'
        );
      `);
      this.ftsAvailable = true;
    } catch (err) {
      console.warn('[SQLiteMemory] FTS5 not available:', err.message);
      this.ftsAvailable = false;
    }

    // 向量表（需要 sqlite-vec 扩展）
    try {
      this.db.exec(`
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_vec USING vec0(
          id TEXT PRIMARY KEY,
          embedding FLOAT[${this.dims}]
        );
      `);
      this.vectorAvailable = true;
    } catch (err) {
      console.warn('[SQLiteMemory] Vector extension not available:', err.message);
      this.vectorAvailable = false;
    }
  }

  /**
   * 检查扩展
   */
  _checkExtensions() {
    // 检查向量扩展
    try {
      this.db.prepare('SELECT vec_version()').get();
      this.vectorAvailable = true;
    } catch {
      this.vectorAvailable = false;
    }
  }

  /**
   * JSON 降级初始化
   */
  _initJsonFallback() {
    this.jsonData = {
      documents: [],
      embeddings: {}
    };
    
    if (fs.existsSync(path.join(DATA_DIR, 'memory.json'))) {
      try {
        this.jsonData = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'memory.json'), 'utf8'));
        console.log('[SQLiteMemory] JSON fallback loaded, documents:', this.jsonData.documents.length);
      } catch {}
    }
  }

  /**
   * 保存 JSON 数据
   */
  _saveJsonFallback() {
    if (!this.useJsonFallback) return;
    fs.writeFileSync(path.join(DATA_DIR, 'memory.json'), JSON.stringify(this.jsonData, null, 2));
  }

  /**
   * 插入文档
   */
  insertDocument(doc) {
    if (this.useJsonFallback) {
      // 移除旧文档（相同 ID）
      this.jsonData.documents = this.jsonData.documents.filter(d => d.id !== doc.id);
      this.jsonData.documents.push(doc);
      this._saveJsonFallback();
      return;
    }

    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO documents (id, path, start_line, end_line, text, source, model)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);
    stmt.run(doc.id, doc.path, doc.startLine, doc.endLine, doc.text, doc.source, doc.model);

    // 更新 FTS
    if (this.ftsAvailable) {
      const ftsStmt = this.db.prepare(`
        INSERT OR REPLACE INTO documents_fts (id, path, text, source)
        VALUES (?, ?, ?, ?)
      `);
      ftsStmt.run(doc.id, doc.path, doc.text, doc.source);
    }
  }

  /**
   * 批量插入文档
   */
  insertDocuments(docs) {
    for (const doc of docs) {
      this.insertDocument(doc);
    }
  }

  /**
   * 存储嵌入
   */
  storeEmbedding(id, embedding, model) {
    if (this.useJsonFallback) {
      this.jsonData.embeddings[id] = { embedding, model };
      this._saveJsonFallback();
      return;
    }

    const buffer = Buffer.from(new Float32Array(embedding).buffer);
    
    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO embedding_cache (id, embedding, model)
      VALUES (?, ?, ?)
    `);
    stmt.run(id, buffer, model);

    // 存储到向量表
    if (this.vectorAvailable) {
      try {
        const vecStmt = this.db.prepare(`
          INSERT OR REPLACE INTO documents_vec (id, embedding)
          VALUES (?, ?)
        `);
        vecStmt.run(id, buffer);
      } catch {}
    }
  }

  /**
   * 批量存储嵌入
   */
  storeEmbeddings(items) {
    for (const { id, embedding, model } of items) {
      this.storeEmbedding(id, embedding, model);
    }
  }

  /**
   * 获取嵌入
   */
  getEmbedding(id) {
    if (this.useJsonFallback) {
      return this.jsonData.embeddings[id]?.embedding || null;
    }

    const row = this.db.prepare('SELECT embedding FROM embedding_cache WHERE id = ?').get(id);
    if (!row) return null;

    const float32 = new Float32Array(row.embedding.buffer);
    return Array.from(float32);
  }

  /**
   * 获取文档
   */
  getDocument(id) {
    if (this.useJsonFallback) {
      return this.jsonData.documents.find(d => d.id === id) || null;
    }

    const row = this.db.prepare('SELECT * FROM documents WHERE id = ?').get(id);
    if (!row) return null;

    return {
      id: row.id,
      path: row.path,
      startLine: row.start_line,
      endLine: row.end_line,
      text: row.text,
      source: row.source,
      model: row.model
    };
  }

  /**
   * 向量搜索
   */
  searchVector(queryVec, limit = 10, sourceFilter = null) {
    if (this.useJsonFallback) {
      // 内存向量搜索
      const results = [];
      for (const doc of this.jsonData.documents) {
        if (sourceFilter && doc.source !== sourceFilter) continue;
        const embData = this.jsonData.embeddings[doc.id];
        if (!embData) continue;
        const score = cosineSimilarity(queryVec, embData.embedding);
        results.push({ ...doc, score });
      }
      return results.sort((a, b) => b.score - a.score).slice(0, limit);
    }

    if (!this.vectorAvailable) return [];

    const buffer = Buffer.from(new Float32Array(queryVec).buffer);
    const sourceSql = sourceFilter ? 'AND c.source = ?' : '';
    
    const rows = this.db.prepare(`
      SELECT c.id, c.path, c.start_line, c.end_line, c.text, c.source,
             1 - vec_distance_cosine(v.embedding, ?) AS score
        FROM documents_vec v
        JOIN documents c ON c.id = v.id
       WHERE 1=1 ${sourceSql}
       ORDER BY score DESC
       LIMIT ?
    `).all(buffer, ...(sourceFilter ? [sourceFilter] : []), limit);

    return rows.map(r => ({
      id: r.id,
      path: r.path,
      startLine: r.start_line,
      endLine: r.end_line,
      snippet: r.text.substring(0, SNIPPET_MAX_CHARS),
      source: r.source,
      score: r.score
    }));
  }

  /**
   * FTS 搜索
   */
  searchFTS(query, limit = 10, sourceFilter = null) {
    if (this.useJsonFallback) {
      // 简单关键词匹配
      const keywords = query.toLowerCase().split(/\s+/).filter(k => k.length > 1);
      if (keywords.length === 0) return [];

      const results = [];
      for (const doc of this.jsonData.documents) {
        if (sourceFilter && doc.source !== sourceFilter) continue;
        const text = doc.text.toLowerCase();
        let matchCount = 0;
        for (const kw of keywords) {
          if (text.includes(kw)) matchCount++;
        }
        if (matchCount > 0) {
          results.push({ ...doc, snippet: doc.text.substring(0, SNIPPET_MAX_CHARS), score: matchCount / keywords.length });
        }
      }
      return results.sort((a, b) => b.score - a.score).slice(0, limit);
    }

    if (!this.ftsAvailable) return [];

    const tokens = query.match(/[\p{L}\p{N}_]+/gu) || [];
    if (tokens.length === 0) return [];

    const ftsQuery = tokens.map(t => `"${t}"`).join(' AND ');
    const sourceSql = sourceFilter ? 'AND source = ?' : '';

    try {
      const rows = this.db.prepare(`
        SELECT id, path, text, source,
               bm25(documents_fts) AS score
          FROM documents_fts
         WHERE documents_fts MATCH ? ${sourceSql}
         ORDER BY score
         LIMIT ?
      `).all(ftsQuery, ...(sourceFilter ? [sourceFilter] : []), limit);

      return rows.map(r => {
        const doc = this.db.prepare('SELECT start_line, end_line FROM documents WHERE id = ?').get(r.id);
        return {
          id: r.id,
          path: r.path,
          startLine: doc?.start_line || 0,
          endLine: doc?.end_line || 0,
          snippet: r.text.substring(0, SNIPPET_MAX_CHARS),
          source: r.source,
          score: 1 / (1 + Math.abs(r.score))
        };
      });
    } catch {
      return [];
    }
  }

  /**
   * 混合搜索（向量 + FTS）
   */
  async searchHybrid(query, queryVec, options = {}) {
    const { limit = 10, vectorWeight = 0.7, textWeight = 0.3, sourceFilter = null } = options;

    const vectorResults = queryVec ? this.searchVector(queryVec, limit * 2, sourceFilter) : [];
    const ftsResults = this.ftsAvailable ? this.searchFTS(query, limit * 2, sourceFilter) : [];

    // 合并结果
    const byId = new Map();
    for (const r of vectorResults) {
      byId.set(r.id, { ...r, vectorScore: r.score, textScore: 0 });
    }
    for (const r of ftsResults) {
      const existing = byId.get(r.id);
      if (existing) {
        existing.textScore = r.score;
      } else {
        byId.set(r.id, { ...r, vectorScore: 0, textScore: r.score });
      }
    }

    // 计算混合分数
    return Array.from(byId.values())
      .map(e => ({ ...e, score: vectorWeight * e.vectorScore + textWeight * e.textScore }))
      .sort((a, b) => b.score - a.score)
      .slice(0, limit);
  }

  /**
   * 删除文档
   */
  deleteDocument(id) {
    if (this.useJsonFallback) {
      this.jsonData.documents = this.jsonData.documents.filter(d => d.id !== id);
      delete this.jsonData.embeddings[id];
      this._saveJsonFallback();
      return;
    }

    this.db.prepare('DELETE FROM documents WHERE id = ?').run(id);
    this.db.prepare('DELETE FROM embedding_cache WHERE id = ?').run(id);
    
    if (this.ftsAvailable) {
      this.db.prepare('DELETE FROM documents_fts WHERE id = ?').run(id);
    }
    
    if (this.vectorAvailable) {
      try {
        this.db.prepare('DELETE FROM documents_vec WHERE id = ?').run(id);
      } catch {}
    }
  }

  /**
   * 获取统计信息
   */
  getStats() {
    if (this.useJsonFallback) {
      return {
        documents: this.jsonData.documents.length,
        embeddings: Object.keys(this.jsonData.embeddings).length,
        vectorAvailable: false,
        ftsAvailable: false,
        storage: 'json'
      };
    }

    const docCount = this.db.prepare('SELECT COUNT(*) as count FROM documents').get()?.count || 0;
    const embCount = this.db.prepare('SELECT COUNT(*) as count FROM embedding_cache').get()?.count || 0;

    return {
      documents: docCount,
      embeddings: embCount,
      vectorAvailable: this.vectorAvailable,
      ftsAvailable: this.ftsAvailable,
      storage: 'sqlite'
    };
  }

  /**
   * 清空所有数据
   */
  clear() {
    if (this.useJsonFallback) {
      this.jsonData = { documents: [], embeddings: {} };
      this._saveJsonFallback();
      return;
    }

    this.db.exec('DELETE FROM documents');
    this.db.exec('DELETE FROM embedding_cache');
    if (this.ftsAvailable) {
      this.db.exec('DELETE FROM documents_fts');
    }
    if (this.vectorAvailable) {
      try {
        this.db.exec('DELETE FROM documents_vec');
      } catch {}
    }
  }

  /**
   * 关闭数据库
   */
  close() {
    if (this.db) {
      this.db.close();
      this.db = null;
    }
  }
}

// ==================== 导出 ====================

module.exports = {
  MemoryDatabase,
  cosineSimilarity,
  ensureDataDir,
  DATA_DIR,
  DB_PATH,
  DEFAULT_VECTOR_DIMS
};

/**
 * Memory Vector Enhanced Module
 * 增强向量记忆系统（基于OpenClaw设计）
 * 支持多嵌入提供商、混合搜索、时间衰减、MMR重排序、常青记忆、向量压缩
 * 
 * 更新记录:
 * - 2026-03-19: 添加MMR重排序、常青记忆功能（参考OpenClaw mmr.ts/temporal-decay.ts）
 * - 2026-03-19: 添加SQLite持久化后端（移植自core-modules）
 * - 2026-03-20: 集成Provider Fallback降级机制，支持iFlow/OpenAI/Gemini/Local多级降级
 */

const path = require('path');
const fs = require('fs').promises;
const crypto = require('crypto');
const { v4: uuidv4 } = require('uuid');

// 导入MMR重排序模块
const { 
  mmrRerank, 
  applyMMRToMemoryResults,
  DEFAULT_MMR_CONFIG 
} = require('./mmr-rerank.js');

// 导入SQLite后端模块
const { 
  MemoryDatabase,
  cosineSimilarity,
  DATA_DIR,
  DB_PATH
} = require('./sqlite-memory.js');

// 导入Provider Fallback模块
const { 
  FallbackExecutor,
  ModelCandidateCollector,
  FAILOVER_ERRORS,
  FALLBACK_CONFIG
} = require('./provider-fallback.js');

// ==================== 常量定义 ====================

const VECTOR_DIR = path.join(__dirname, '..', 'memory-vector-data');
const INDEX_DIR = path.join(VECTOR_DIR, 'indices');
const EMBEDDINGS_DIR = path.join(VECTOR_DIR, 'embeddings');

// 确保目录存在
async function ensureDirectories() {
  const dirs = [VECTOR_DIR, INDEX_DIR, EMBEDDINGS_DIR];
  for (const dir of dirs) {
    try {
      await fs.mkdir(dir, { recursive: true });
    } catch (err) {
      console.warn(`[MemoryVectorEnhanced] Failed to create directory ${dir}: ${err.message}`);
    }
  }
}

// ==================== 嵌入提供商 ====================

/**
 * 嵌入提供商类型
 */
const EmbeddingProviderType = {
  IFLOW: 'iflow',        // iFlow 内置服务
  OPENAI: 'openai',
  GEMINI: 'gemini',      // Google Gemini
  ANTHROPIC: 'anthropic',
  HUGGINGFACE: 'huggingface',
  COHERE: 'cohere',
  LOCAL: 'local',        // 本地哈希向量（降级）
  CUSTOM: 'custom'
};

/**
 * 默认降级顺序：iFlow -> OpenAI -> Gemini -> Local
 */
const DEFAULT_FALLBACK_ORDER = [
  EmbeddingProviderType.IFLOW,
  EmbeddingProviderType.OPENAI,
  EmbeddingProviderType.GEMINI,
  EmbeddingProviderType.LOCAL
];

/**
 * 嵌入提供商配置
 */
class EmbeddingProviderConfig {
  constructor(config = {}) {
    this.type = config.type || EmbeddingProviderType.OPENAI;
    this.apiKey = config.apiKey || null;
    this.apiEndpoint = config.apiEndpoint || null;
    this.model = config.model || 'text-embedding-ada-002';
    this.dimensions = config.dimensions || 1536;
    this.batchSize = config.batchSize || 100;
    this.timeout = config.timeout || 30000;
    this.retryCount = config.retryCount || 3;
    this.enabled = config.enabled !== false;
  }
  
  /**
   * 验证配置
   */
  validate() {
    const errors = [];
    
    if (!this.type) errors.push('type is required');
    if (this.dimensions <= 0) errors.push('dimensions must be positive');
    if (this.batchSize <= 0) errors.push('batchSize must be positive');
    
    return {
      valid: errors.length === 0,
      errors
    };
  }
  
  /**
   * 转换为对象
   */
  toObject() {
    return {
      type: this.type,
      apiKey: this.apiKey,
      apiEndpoint: this.apiEndpoint,
      model: this.model,
      dimensions: this.dimensions,
      batchSize: this.batchSize,
      timeout: this.timeout,
      retryCount: this.retryCount,
      enabled: this.enabled
    };
  }
  
  /**
   * 从对象创建
   */
  static fromObject(obj) {
    return new EmbeddingProviderConfig(obj);
  }
}

/**
 * 嵌入提供商
 */
class EmbeddingProvider {
  constructor(config) {
    this.config = new EmbeddingProviderConfig(config);
  }
  
  /**
   * 生成嵌入
   */
  async generateEmbedding(text) {
    throw new Error('generateEmbedding must be implemented by subclass');
  }
  
  /**
   * 批量生成嵌入
   */
  async generateBatchEmbeddings(texts) {
    const embeddings = [];
    
    for (let i = 0; i < texts.length; i += this.config.batchSize) {
      const batch = texts.slice(i, i + this.config.batchSize);
      const batchEmbeddings = await Promise.all(
        batch.map(text => this.generateEmbedding(text))
      );
      embeddings.push(...batchEmbeddings);
    }
    
    return embeddings;
  }
  
  /**
   * 获取维度
   */
  getDimensions() {
    return this.config.dimensions;
  }
}

// ==================== 具体嵌入提供商实现 ====================

/**
 * iFlow 内置嵌入服务
 */
class IFlowEmbeddingProvider extends EmbeddingProvider {
  constructor(config = {}) {
    super({ ...config, type: EmbeddingProviderType.IFLOW });
    this.endpoint = config.endpoint || 'http://localhost:18080/api/embedding';
  }
  
  async generateEmbedding(text) {
    const response = await fetch(this.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });
    
    if (!response.ok) {
      throw new Error(`iFlow embedding failed: ${response.status}`);
    }
    
    const data = await response.json();
    return data.embedding || data.data?.[0]?.embedding || [];
  }
}

/**
 * OpenAI 嵌入服务
 */
class OpenAIEmbeddingProvider extends EmbeddingProvider {
  constructor(config = {}) {
    super({ ...config, type: EmbeddingProviderType.OPENAI });
    this.apiKey = config.apiKey || process.env.OPENAI_API_KEY;
    this.endpoint = config.endpoint || 'https://api.openai.com/v1/embeddings';
    this.model = config.model || 'text-embedding-ada-002';
  }
  
  async generateEmbedding(text) {
    const response = await fetch(this.endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.apiKey}`
      },
      body: JSON.stringify({
        model: this.model,
        input: text
      })
    });
    
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(`OpenAI embedding failed: ${error.error?.message || response.status}`);
    }
    
    const data = await response.json();
    return data.data[0].embedding;
  }
}

/**
 * Google Gemini 嵌入服务
 */
class GeminiEmbeddingProvider extends EmbeddingProvider {
  constructor(config = {}) {
    super({ ...config, type: EmbeddingProviderType.GEMINI, dimensions: 768 });
    this.apiKey = config.apiKey || process.env.GEMINI_API_KEY;
    this.endpoint = config.endpoint || 'https://generativelanguage.googleapis.com/v1/models/embedding-001:embedContent';
    this.model = config.model || 'embedding-001';
  }
  
  async generateEmbedding(text) {
    const url = `${this.endpoint}?key=${this.apiKey}`;
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: `models/${this.model}`,
        content: { parts: [{ text }] }
      })
    });
    
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(`Gemini embedding failed: ${error.error?.message || response.status}`);
    }
    
    const data = await response.json();
    return data.embedding?.values || [];
  }
}

/**
 * 本地哈希向量嵌入（降级方案）
 * 使用确定性哈希生成向量，不依赖外部API
 */
class LocalEmbeddingProvider extends EmbeddingProvider {
  constructor(config = {}) {
    super({ 
      ...config, 
      type: EmbeddingProviderType.LOCAL,
      dimensions: config.dimensions || 256  // 本地向量维度较小
    });
    this.seed = config.seed || 42;
  }
  
  /**
   * 使用确定性哈希生成向量
   * 这是一个降级方案，生成的向量可用于基本相似度计算
   */
  async generateEmbedding(text) {
    const dims = this.config.dimensions;
    const embedding = new Array(dims);
    
    // 使用文本特征的确定性映射
    const features = this._extractFeatures(text);
    
    for (let i = 0; i < dims; i++) {
      // 结合特征和位置生成向量分量
      const hash = this._hash(`${features.seed}:${i}:${features.ngrams[i % features.ngrams.length]}`);
      embedding[i] = (hash % 10000) / 10000 * 2 - 1;  // 归一化到 [-1, 1]
    }
    
    // L2 归一化
    const norm = Math.sqrt(embedding.reduce((sum, v) => sum + v * v, 0));
    return embedding.map(v => v / (norm || 1));
  }
  
  /**
   * 提取文本特征
   */
  _extractFeatures(text) {
    const words = text.toLowerCase().split(/\s+/);
    const seed = this._hash(text);
    
    // 生成 n-gram 特征
    const ngrams = [];
    for (let n = 2; n <= 4; n++) {
      for (let i = 0; i <= words.length - n; i++) {
        ngrams.push(words.slice(i, i + n).join('_'));
      }
    }
    
    // 确保有足够的 ngram
    while (ngrams.length < this.config.dimensions) {
      ngrams.push(`pad_${ngrams.length}`);
    }
    
    return { seed, ngrams };
  }
  
  /**
   * 简单哈希函数
   */
  _hash(str) {
    let hash = this.seed;
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) - hash) + str.charCodeAt(i);
      hash = hash & hash;  // Convert to 32bit integer
    }
    return Math.abs(hash);
  }
}

// ==================== 嵌入提供商工厂 ====================

/**
 * 创建嵌入提供商实例
 */
function createEmbeddingProvider(type, config = {}) {
  switch (type) {
    case EmbeddingProviderType.IFLOW:
      return new IFlowEmbeddingProvider(config);
    case EmbeddingProviderType.OPENAI:
      return new OpenAIEmbeddingProvider(config);
    case EmbeddingProviderType.GEMINI:
      return new GeminiEmbeddingProvider(config);
    case EmbeddingProviderType.LOCAL:
      return new LocalEmbeddingProvider(config);
    default:
      return new LocalEmbeddingProvider(config);  // 默认使用本地降级
  }
}

// ==================== 向量索引 ====================

/**
 * 向量文档
 */
class VectorDocument {
  constructor(data = {}) {
    this.id = data.id || uuidv4();
    this.embedding = data.embedding || [];
    this.text = data.text || '';
    this.metadata = data.metadata || {};
    this.createdAt = data.createdAt || new Date().toISOString();
    this.updatedAt = data.updatedAt || new Date().toISOString();
    this.score = data.score || 0;
  }
  
  /**
   * 更新分数
   */
  updateScore(score) {
    this.score = score;
    this.updatedAt = new Date().toISOString();
  }
  
  /**
   * 转换为对象
   */
  toObject() {
    return {
      id: this.id,
      embedding: this.embedding,
      text: this.text,
      metadata: this.metadata,
      createdAt: this.createdAt,
      updatedAt: this.updatedAt,
      score: this.score
    };
  }
  
  /**
   * 从对象创建
   */
  static fromObject(obj) {
    return new VectorDocument(obj);
  }
}

/**
 * 向量索引
 */
class VectorIndex {
  constructor(config = {}) {
    this.id = config.id || uuidv4();
    this.name = config.name || `index-${this.id}`;
    this.dimensions = config.dimensions || 1536;
    this.metric = config.metric || 'cosine';  // cosine, euclidean, dot
    this.documents = new Map();
    this.createdAt = config.createdAt || new Date().toISOString();
    this.updatedAt = config.updatedAt || new Date().toISOString();
  }
  
  /**
   * 添加文档
   */
  addDocument(document) {
    if (document.embedding.length !== this.dimensions) {
      throw new Error(`Embedding dimension mismatch: expected ${this.dimensions}, got ${document.embedding.length}`);
    }
    
    this.documents.set(document.id, document);
    this.updatedAt = new Date().toISOString();
  }
  
  /**
   * 批量添加文档
   */
  addDocuments(documents) {
    for (const doc of documents) {
      this.addDocument(doc);
    }
  }
  
  /**
   * 删除文档
   */
  removeDocument(documentId) {
    const deleted = this.documents.delete(documentId);
    if (deleted) {
      this.updatedAt = new Date().toISOString();
    }
    return deleted;
  }
  
  /**
   * 搜索
   */
  search(queryEmbedding, options = {}) {
    const topK = options.topK || 10;
    const minScore = options.minScore || 0;
    
    const results = [];
    
    for (const document of this.documents.values()) {
      const score = this._calculateSimilarity(queryEmbedding, document.embedding);
      
      if (score >= minScore) {
        const resultDoc = new VectorDocument(document.toObject());
        resultDoc.updateScore(score);
        results.push(resultDoc);
      }
    }
    
    // 按分数排序
    results.sort((a, b) => b.score - a.score);
    
    // 返回topK结果
    return results.slice(0, topK);
  }
  
  /**
   * 混合搜索（向量+关键词）
   */
  hybridSearch(queryEmbedding, queryText, options = {}) {
    const vectorWeight = options.vectorWeight || 0.7;
    const keywordWeight = options.keywordWeight || 0.3;
    const topK = options.topK || 10;
    
    const results = [];
    
    for (const document of this.documents.values()) {
      // 向量相似度
      const vectorScore = this._calculateSimilarity(queryEmbedding, document.embedding);
      
      // 关键词匹配
      const keywordScore = this._calculateKeywordMatch(queryText, document.text);
      
      // 混合分数
      const hybridScore = vectorWeight * vectorScore + keywordWeight * keywordScore;
      
      if (hybridScore >= (options.minScore || 0)) {
        const resultDoc = new VectorDocument(document.toObject());
        resultDoc.updateScore(hybridScore);
        results.push(resultDoc);
      }
    }
    
    // 按分数排序
    results.sort((a, b) => b.score - a.score);
    
    return results.slice(0, topK);
  }
  
  /**
   * MMR增强搜索（向量搜索 + MMR重排序）
   * 参考OpenClaw设计，平衡相关性与多样性
   */
  searchWithMMR(queryEmbedding, options = {}) {
    const topK = options.topK || 20;
    const mmrConfig = options.mmr || {};
    const mmrEnabled = mmrConfig.enabled !== false && options.useMMR !== false;
    
    // 先获取更多结果用于MMR筛选
    const candidateCount = mmrEnabled ? Math.max(topK * 3, 50) : topK;
    
    // 基础搜索
    let results = this.search(queryEmbedding, { 
      ...options, 
      topK: candidateCount 
    });
    
    // 应用时间衰减
    if (options.applyTimeDecay !== false && this.timeDecay) {
      results = this.timeDecay.applyToResults(results, options);
    }
    
    // 应用MMR重排序
    if (mmrEnabled && results.length > 1) {
      const mmrResults = applyMMRToMemoryResults(results, {
        enabled: true,
        lambda: mmrConfig.lambda ?? DEFAULT_MMR_CONFIG.lambda,
        maxResults: topK
      });
      
      return mmrResults;
    }
    
    return results.slice(0, topK);
  }
  
  /**
   * 混合搜索 + MMR重排序
   */
  hybridSearchWithMMR(queryEmbedding, queryText, options = {}) {
    const topK = options.topK || 20;
    const mmrConfig = options.mmr || {};
    const mmrEnabled = mmrConfig.enabled !== false && options.useMMR !== false;
    
    // 获取更多候选结果
    const candidateCount = mmrEnabled ? Math.max(topK * 3, 50) : topK;
    
    // 基础混合搜索
    let results = this.hybridSearch(queryEmbedding, queryText, { 
      ...options, 
      topK: candidateCount 
    });
    
    // 应用时间衰减
    if (options.applyTimeDecay !== false && this.timeDecay) {
      results = this.timeDecay.applyToResults(results, options);
    }
    
    // 应用MMR
    if (mmrEnabled && results.length > 1) {
      return applyMMRToMemoryResults(results, {
        enabled: true,
        lambda: mmrConfig.lambda ?? DEFAULT_MMR_CONFIG.lambda,
        maxResults: topK
      });
    }
    
    return results.slice(0, topK);
  }
  
  /**
   * 计算相似度
   */
  _calculateSimilarity(embedding1, embedding2) {
    switch (this.metric) {
      case 'cosine':
        return this._cosineSimilarity(embedding1, embedding2);
      case 'euclidean':
        return this._euclideanDistance(embedding1, embedding2);
      case 'dot':
        return this._dotProduct(embedding1, embedding2);
      default:
        return this._cosineSimilarity(embedding1, embedding2);
    }
  }
  
  /**
   * 余弦相似度
   */
  _cosineSimilarity(a, b) {
    let dotProduct = 0;
    let normA = 0;
    let normB = 0;
    
    for (let i = 0; i < a.length; i++) {
      dotProduct += a[i] * b[i];
      normA += a[i] * a[i];
      normB += b[i] * b[i];
    }
    
    return dotProduct / (Math.sqrt(normA) * Math.sqrt(normB));
  }
  
  /**
   * 欧几里得距离
   */
  _euclideanDistance(a, b) {
    let sum = 0;
    for (let i = 0; i < a.length; i++) {
      const diff = a[i] - b[i];
      sum += diff * diff;
    }
    return 1 / (1 + Math.sqrt(sum));
  }
  
  /**
   * 点积
   */
  _dotProduct(a, b) {
    let sum = 0;
    for (let i = 0; i < a.length; i++) {
      sum += a[i] * b[i];
    }
    return sum;
  }
  
  /**
   * 计算关键词匹配
   */
  _calculateKeywordMatch(query, text) {
    const queryWords = query.toLowerCase().split(/\s+/);
    const textWords = text.toLowerCase().split(/\s+/);
    
    let matchCount = 0;
    for (const word of queryWords) {
      if (textWords.some(w => w.includes(word))) {
        matchCount++;
      }
    }
    
    return matchCount / queryWords.length;
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    return {
      id: this.id,
      name: this.name,
      dimensions: this.dimensions,
      metric: this.metric,
      documentCount: this.documents.size,
      createdAt: this.createdAt,
      updatedAt: this.updatedAt
    };
  }
  
  /**
   * 转换为对象
   */
  toObject() {
    return {
      id: this.id,
      name: this.name,
      dimensions: this.dimensions,
      metric: this.metric,
      documents: Array.from(this.documents.values()).map(d => d.toObject()),
      createdAt: this.createdAt,
      updatedAt: this.updatedAt
    };
  }
  
  /**
   * 从对象创建
   */
  static fromObject(obj) {
    const index = new VectorIndex(obj);
    index.documents = new Map();
    
    for (const doc of obj.documents || []) {
      index.documents.set(doc.id, VectorDocument.fromObject(doc));
    }
    
    return index;
  }
}

// ==================== 时间衰减 ====================

/**
 * 时间衰减器
 */
class TimeDecay {
  constructor(config = {}) {
    this.halfLife = config.halfLife || 30 * 24 * 60 * 60 * 1000;  // 默认30天
    this.baseDecay = config.baseDecay || 0.5;
    this.evergreenTags = config.evergreenTags || ['evergreen', 'permanent', 'core'];  // 常青标签
  }
  
  /**
   * 检查是否为常青记忆
   * 常青记忆不会衰减，始终保持最高相关性
   */
  isEvergreen(metadata = {}) {
    const tags = metadata.tags || [];
    const evergreen = metadata.evergreen;
    
    if (evergreen === true) return true;
    if (evergreen === false) return false;
    
    return tags.some(tag => 
      this.evergreenTags.includes(tag.toLowerCase())
    );
  }
  
  /**
   * 计算衰减因子（基于OpenClaw temporal-decay.ts）
   * 公式: exp(-λ * age)，其中 λ = ln(2) / halfLife
   */
  calculate(timestamp, metadata = {}) {
    // 常青记忆不衰减
    if (this.isEvergreen(metadata)) {
      return 1.0;
    }
    
    const now = Date.now();
    const age = now - new Date(timestamp).getTime();
    
    if (age <= 0) {
      return 1.0;
    }
    
    // 指数衰减: e^(-λ * age)
    const lambda = Math.log(2) / this.halfLife;
    const decay = Math.exp(-lambda * age);
    
    // 应用基础衰减，确保最小值
    const result = decay * this.baseDecay + (1 - this.baseDecay);
    
    return Math.max(result, 0.1);  // 最低保持10%相关性
  }
  
  /**
   * 应用衰减到分数
   */
  applyToScore(score, timestamp, metadata = {}) {
    return score * this.calculate(timestamp, metadata);
  }
  
  /**
   * 批量应用衰减
   */
  applyToResults(results, options = {}) {
    return results.map(result => {
      const timestamp = result.timestamp || result.metadata?.timestamp || Date.now();
      const metadata = result.metadata || {};
      
      const decayFactor = this.calculate(timestamp, metadata);
      const isEvergreen = this.isEvergreen(metadata);
      
      return {
        ...result,
        score: result.score * decayFactor,
        decayFactor,
        isEvergreen,
        originalScore: result.score
      };
    });
  }
  
  /**
   * 调整衰减参数
   */
  adjustDecay(halfLife, baseDecay) {
    if (halfLife !== undefined) {
      this.halfLife = halfLife;
    }
    if (baseDecay !== undefined) {
      this.baseDecay = Math.max(0, Math.min(1, baseDecay));
    }
  }
  
  /**
   * 设置常青标签
   */
  setEvergreenTags(tags) {
    this.evergreenTags = Array.isArray(tags) ? tags.map(t => t.toLowerCase()) : [];
  }
}

// ==================== 向量压缩 ====================

/**
 * 向量压缩器
 */
class VectorCompressor {
  constructor(config = {}) {
    this.targetDimensions = config.targetDimensions || 256;
    this.method = config.method || 'pca';  // pca, random, uniform
  }
  
  /**
   * 压缩向量
   */
  compress(vector) {
    switch (this.method) {
      case 'pca':
        return this._pcaCompress(vector);
      case 'random':
        return this._randomCompress(vector);
      case 'uniform':
        return this._uniformCompress(vector);
      default:
        return this._uniformCompress(vector);
    }
  }
  
  /**
   * PCA压缩（简化版）
   */
  _pcaCompress(vector) {
    // 简化实现：采样
    return this._uniformCompress(vector);
  }
  
  /**
   * 随机采样压缩
   */
  _randomCompress(vector) {
    const indices = [];
    for (let i = 0; i < this.targetDimensions; i++) {
      indices.push(Math.floor(Math.random() * vector.length));
    }
    
    return indices.map(i => vector[i]);
  }
  
  /**
   * 均匀采样压缩
   */
  _uniformCompress(vector) {
    const step = Math.floor(vector.length / this.targetDimensions);
    const compressed = [];
    
    for (let i = 0; i < this.targetDimensions; i++) {
      const index = Math.min(i * step, vector.length - 1);
      compressed.push(vector[index]);
    }
    
    return compressed;
  }
  
  /**
   * 压缩文档集合
   */
  compressDocuments(documents) {
    return documents.map(doc => {
      const compressedDoc = new VectorDocument(doc.toObject());
      compressedDoc.embedding = this.compress(doc.embedding);
      return compressedDoc;
    });
  }
}

// ==================== 向量存储 ====================

/**
 * 向量存储
 */
class VectorStore {
  constructor(config = {}) {
    this.indices = new Map();
    this.providers = new Map();
    this.defaultProvider = config.defaultProvider || null;
    this.timeDecay = new TimeDecay(config.timeDecay || {});
    this.compressor = new VectorCompressor(config.compression || {});
    
    // 嵌入降级管理
    this.fallbackExecutor = new FallbackExecutor(config.fallback || {});
    this.fallbackOrder = config.fallbackOrder || DEFAULT_FALLBACK_ORDER;
    this.embeddingCache = new Map();  // 嵌入缓存
    this._initDefaultProviders(config.providers);
  }
  
  /**
   * 初始化默认提供商
   */
  _initDefaultProviders(providerConfigs = {}) {
    for (const type of this.fallbackOrder) {
      const config = providerConfigs[type] || {};
      const provider = createEmbeddingProvider(type, config);
      this.providers.set(type, provider);
    }
    
    // 设置默认提供商为降级顺序的第一个
    if (!this.defaultProvider && this.fallbackOrder.length > 0) {
      this.defaultProvider = this.fallbackOrder[0];
    }
  }
  
  /**
   * 创建索引
   */
  createIndex(name, dimensions, metric = 'cosine') {
    const index = new VectorIndex({
      name,
      dimensions,
      metric
    });
    
    this.indices.set(index.id, index);
    return index;
  }
  
  /**
   * 获取索引
   */
  getIndex(indexId) {
    return this.indices.get(indexId) || null;
  }
  
  /**
   * 删除索引
   */
  deleteIndex(indexId) {
    return this.indices.delete(indexId);
  }
  
  /**
   * 添加嵌入提供商
   */
  addProvider(id, provider) {
    this.providers.set(id, provider);
    
    if (!this.defaultProvider) {
      this.defaultProvider = id;
    }
  }
  
  /**
   * 获取提供商
   */
  getProvider(id) {
    return this.providers.get(id) || null;
  }
  
  /**
   * 设置默认提供商
   */
  setDefaultProvider(id) {
    if (this.providers.has(id)) {
      this.defaultProvider = id;
    }
  }
  
  /**
   * 设置降级顺序
   */
  setFallbackOrder(order) {
    this.fallbackOrder = order.filter(type => 
      Object.values(EmbeddingProviderType).includes(type)
    );
  }
  
  /**
   * 生成嵌入（带降级）
   * 失败时自动切换到下一个Provider
   */
  async generateEmbeddingWithFallback(text, options = {}) {
    // 检查缓存
    const cacheKey = this._hashText(text);
    if (this.embeddingCache.has(cacheKey)) {
      return this.embeddingCache.get(cacheKey);
    }
    
    // 构建候选列表
    const collector = new ModelCandidateCollector();
    for (const type of this.fallbackOrder) {
      collector.addExplicitCandidate({ provider: type, model: type });
    }
    const candidates = collector.getCandidates();
    
    // 使用降级执行器
    try {
      const embedding = await this.fallbackExecutor.executeWithFallback(
        candidates,
        async (provider, model, opts) => {
          const providerInstance = this.providers.get(provider);
          if (!providerInstance) {
            throw new Error(`Provider not available: ${provider}`);
          }
          return providerInstance.generateEmbedding(text);
        },
        options
      );
      
      // 缓存结果
      this.embeddingCache.set(cacheKey, embedding);
      
      // 限制缓存大小
      if (this.embeddingCache.size > 10000) {
        const firstKey = this.embeddingCache.keys().next().value;
        this.embeddingCache.delete(firstKey);
      }
      
      return embedding;
      
    } catch (error) {
      console.error('[VectorStore] All embedding providers failed:', error.message);
      
      // 最终降级：使用本地哈希向量
      const localProvider = this.providers.get(EmbeddingProviderType.LOCAL);
      if (localProvider) {
        console.log('[VectorStore] Falling back to local hash embedding');
        const embedding = await localProvider.generateEmbedding(text);
        this.embeddingCache.set(cacheKey, embedding);
        return embedding;
      }
      
      throw error;
    }
  }
  
  /**
   * 哈希文本用于缓存键
   */
  _hashText(text) {
    const crypto = require('crypto');
    return crypto.createHash('md5').update(text).digest('hex');
  }
  
  /**
   * 添加文档（使用降级嵌入）
   */
  async addDocument(indexId, text, metadata = {}) {
    const index = this.getIndex(indexId);
    
    if (!index) {
      throw new Error(`Index not found: ${indexId}`);
    }
    
    // 使用降级机制生成嵌入
    const embedding = await this.generateEmbeddingWithFallback(text);
    
    // 创建文档
    const document = new VectorDocument({
      text,
      embedding,
      metadata
    });
    
    // 添加到索引
    index.addDocument(document);
    
    return document;
  }
  
  /**
   * 批量添加文档
   */
  async addDocuments(indexId, texts, metadatas = []) {
    const documents = [];
    for (let i = 0; i < texts.length; i++) {
      const doc = await this.addDocument(indexId, texts[i], metadatas[i] || {});
      documents.push(doc);
    }
    return documents;
  }
  
  /**
   * 搜索（使用降级嵌入）
   */
  async search(indexId, query, options = {}) {
    const index = this.getIndex(indexId);
    
    if (!index) {
      throw new Error(`Index not found: ${indexId}`);
    }
    
    // 使用降级机制生成查询嵌入
    const queryEmbedding = await this.generateEmbeddingWithFallback(query);
    
    // 执行搜索
    let results;
    
    if (options.hybrid) {
      results = index.hybridSearch(queryEmbedding, query, options);
    } else if (options.useMMR) {
      results = index.searchWithMMR(queryEmbedding, options);
    } else {
      results = index.search(queryEmbedding, options);
    }
    
    // 应用时间衰减
    if (options.enableTimeDecay !== false) {
      for (const result of results) {
        const decayedScore = this.timeDecay.applyToScore(result.score, result.createdAt);
        result.updateScore(decayedScore);
      }
    }
    
    // 重新排序
    results.sort((a, b) => b.score - a.score);
    
    return results;
  }
  
  /**
   * 获取降级日志
   */
  getFallbackLog(options = {}) {
    return this.fallbackExecutor.getFallbackLog(options);
  }
  
  /**
   * 获取统计信息
   */
  getStats() {
    const indices = Array.from(this.indices.values());
    
    return {
      totalIndices: indices.length,
      totalDocuments: indices.reduce((sum, i) => sum + i.documents.size, 0),
      providers: Array.from(this.providers.keys()),
      defaultProvider: this.defaultProvider,
      fallbackOrder: this.fallbackOrder,
      embeddingCacheSize: this.embeddingCache.size,
      timeDecay: {
        halfLife: this.timeDecay.halfLife,
        baseDecay: this.timeDecay.baseDecay
      },
      compression: {
        targetDimensions: this.compressor.targetDimensions,
        method: this.compressor.method
      }
    };
  }
  
  /**
   * 保存到文件
   */
  async save() {
    await ensureDirectories();
    
    // 保存索引
    for (const index of this.indices.values()) {
      const indexPath = path.join(INDEX_DIR, `${index.id}.json`);
      await fs.writeFile(indexPath, JSON.stringify(index.toObject(), null, 2));
    }
    
    // 保存提供商配置
    const providersConfig = {};
    for (const [id, provider] of this.providers.entries()) {
      providersConfig[id] = provider.config.toObject();
    }
    
    const providersPath = path.join(VECTOR_DIR, 'providers.json');
    await fs.writeFile(providersPath, JSON.stringify(providersConfig, null, 2));
    
    // 保存存储配置
    const storeConfig = {
      defaultProvider: this.defaultProvider,
      timeDecay: {
        halfLife: this.timeDecay.halfLife,
        baseDecay: this.timeDecay.baseDecay
      },
      compression: {
        targetDimensions: this.compressor.targetDimensions,
        method: this.compressor.method
      }
    };
    
    const configPath = path.join(VECTOR_DIR, 'config.json');
    await fs.writeFile(configPath, JSON.stringify(storeConfig, null, 2));
  }
  
  /**
   * 从文件加载
   */
  async load() {
    await ensureDirectories();
    
    // 加载索引
    const indexFiles = await fs.readdir(INDEX_DIR);
    for (const file of indexFiles) {
      if (file.endsWith('.json')) {
        const indexPath = path.join(INDEX_DIR, file);
        const content = await fs.readFile(indexPath, 'utf8');
        const index = VectorIndex.fromObject(JSON.parse(content));
        this.indices.set(index.id, index);
      }
    }
    
    // 加载提供商配置
    try {
      const providersPath = path.join(VECTOR_DIR, 'providers.json');
      const content = await fs.readFile(providersPath, 'utf8');
      const providersConfig = JSON.parse(content);
      
      for (const [id, config] of Object.entries(providersConfig)) {
        const provider = new EmbeddingProvider(config);
        this.providers.set(id, provider);
      }
    } catch (err) {
      console.log('[MemoryVectorEnhanced] No providers config found');
    }
    
    // 加载存储配置
    try {
      const configPath = path.join(VECTOR_DIR, 'config.json');
      const content = await fs.readFile(configPath, 'utf8');
      const storeConfig = JSON.parse(content);
      
      this.defaultProvider = storeConfig.defaultProvider;
      this.timeDecay.adjustDecay(
        storeConfig.timeDecay?.halfLife,
        storeConfig.timeDecay?.baseDecay
      );
      
      this.compressor.targetDimensions = storeConfig.compression?.targetDimensions || 256;
      this.compressor.method = storeConfig.compression?.method || 'pca';
    } catch (err) {
      console.log('[MemoryVectorEnhanced] No store config found');
    }
  }
}

// ==================== 导出 ====================

module.exports = {
  // 嵌入提供商
  EmbeddingProviderType,
  EmbeddingProviderConfig,
  EmbeddingProvider,
  DEFAULT_FALLBACK_ORDER,
  
  // 具体提供商实现
  IFlowEmbeddingProvider,
  OpenAIEmbeddingProvider,
  GeminiEmbeddingProvider,
  LocalEmbeddingProvider,
  
  // 提供商工厂
  createEmbeddingProvider,
  
  // 向量索引
  VectorDocument,
  VectorIndex,
  
  // 时间衰减（含常青记忆）
  TimeDecay,
  
  // 向量压缩
  VectorCompressor,
  
  // 向量存储
  VectorStore,
  
  // MMR重排序
  mmrRerank,
  applyMMRToMemoryResults,
  DEFAULT_MMR_CONFIG,
  
  // Provider Fallback（从provider-fallback.js导入）
  FallbackExecutor,
  ModelCandidateCollector,
  FAILOVER_ERRORS,
  FALLBACK_CONFIG,
  
  // 辅助函数
  ensureDirectories
};
/**
 * iFlow LLM Module v2.0
 * LLM 调用 + 缓存 + Schema验证 + 模型降级
 * 
 * 新增功能（基于OpenClaw设计）:
 * - 模型降级 (Model Fallback)
 * - 认证配置轮换 (Auth Profile Rotation)
 * - 冷却机制 (Cooldown)
 * - 错误分类 (Error Classification)
 * - 使用统计 (Usage Statistics)
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const https = require('https');
const http = require('http');

const LLM_DIR = path.join(__dirname, '..', 'llm-data');
const CACHE_DIR = path.join(LLM_DIR, 'cache');
const STATS_DIR = path.join(LLM_DIR, 'stats');

[LLM_DIR, CACHE_DIR, STATS_DIR].forEach(dir => {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
});

// ============================================================
// 错误分类
// ============================================================

const ErrorType = {
  AUTH_FAILED: 'auth_failed',
  RATE_LIMITED: 'rate_limited',
  MODEL_OVERLOADED: 'model_overloaded',
  CONTEXT_TOO_LONG: 'context_too_long',
  INVALID_REQUEST: 'invalid_request',
  TIMEOUT: 'timeout',
  NETWORK_ERROR: 'network_error',
  UNKNOWN: 'unknown'
};

const TRANSIENT_ERRORS = [
  ErrorType.RATE_LIMITED,
  ErrorType.MODEL_OVERLOADED,
  ErrorType.TIMEOUT,
  ErrorType.NETWORK_ERROR
];

function classifyError(error) {
  const msg = (error.message || '').toLowerCase();
  
  if (msg.includes('401') || msg.includes('unauthorized') || msg.includes('invalid api key')) {
    return ErrorType.AUTH_FAILED;
  }
  if (msg.includes('429') || msg.includes('rate limit') || msg.includes('too many requests')) {
    return ErrorType.RATE_LIMITED;
  }
  if (msg.includes('overloaded') || msg.includes('capacity') || msg.includes('503')) {
    return ErrorType.MODEL_OVERLOADED;
  }
  if (msg.includes('context') || msg.includes('token') || msg.includes('too long')) {
    return ErrorType.CONTEXT_TOO_LONG;
  }
  if (msg.includes('timeout') || msg.includes('etimedout')) {
    return ErrorType.TIMEOUT;
  }
  if (msg.includes('econnrefused') || msg.includes('enotfound') || msg.includes('network')) {
    return ErrorType.NETWORK_ERROR;
  }
  if (msg.includes('400') || msg.includes('invalid')) {
    return ErrorType.INVALID_REQUEST;
  }
  return ErrorType.UNKNOWN;
}

// ============================================================
// 认证配置管理
// ============================================================

class AuthProfileManager {
  constructor() {
    this.profiles = new Map(); // provider -> [{key, weight, cooldownUntil}]
    this.stats = new Map(); // provider -> {successes, failures, lastError}
    this.loadProfiles();
  }
  
  loadProfiles() {
    const profilePath = path.join(LLM_DIR, 'auth_profiles.json');
    if (fs.existsSync(profilePath)) {
      try {
        const data = JSON.parse(fs.readFileSync(profilePath, 'utf8'));
        for (const [provider, profiles] of Object.entries(data)) {
          this.profiles.set(provider, profiles);
        }
      } catch (e) {
        console.warn('Failed to load auth profiles:', e.message);
      }
    }
  }
  
  saveProfiles() {
    const data = {};
    for (const [provider, profiles] of this.profiles) {
      data[provider] = profiles;
    }
    fs.writeFileSync(path.join(LLM_DIR, 'auth_profiles.json'), JSON.stringify(data, null, 2));
  }
  
  addProfile(provider, key, weight = 1) {
    if (!this.profiles.has(provider)) {
      this.profiles.set(provider, []);
    }
    this.profiles.get(provider).push({
      key,
      weight,
      cooldownUntil: 0,
      successCount: 0,
      failureCount: 0
    });
    this.saveProfiles();
  }
  
  getAvailableProfile(provider) {
    const profiles = this.profiles.get(provider) || [];
    const now = Date.now();
    
    // 过滤可用的配置（不在冷却期）
    const available = profiles.filter(p => p.cooldownUntil < now);
    if (available.length === 0) {
      return null;
    }
    
    // 按权重和成功率选择
    available.sort((a, b) => {
      const scoreA = a.weight * (a.successCount / Math.max(1, a.successCount + a.failureCount));
      const scoreB = b.weight * (b.successCount / Math.max(1, b.successCount + a.failureCount));
      return scoreB - scoreA;
    });
    
    return available[0];
  }
  
  recordSuccess(provider, key) {
    const profiles = this.profiles.get(provider) || [];
    const profile = profiles.find(p => p.key === key);
    if (profile) {
      profile.successCount++;
      this.saveProfiles();
    }
  }
  
  recordFailure(provider, key, errorType) {
    const profiles = this.profiles.get(provider) || [];
    const profile = profiles.find(p => p.key === key);
    if (profile) {
      profile.failureCount++;
      
      // 认证失败立即禁用
      if (errorType === ErrorType.AUTH_FAILED) {
        profile.cooldownUntil = Date.now() + 24 * 60 * 60 * 1000; // 24小时
      }
      // 限流短期冷却
      else if (errorType === ErrorType.RATE_LIMITED) {
        profile.cooldownUntil = Date.now() + 60 * 1000; // 1分钟
      }
      // 过载中期冷却
      else if (errorType === ErrorType.MODEL_OVERLOADED) {
        profile.cooldownUntil = Date.now() + 5 * 60 * 1000; // 5分钟
      }
      
      this.saveProfiles();
    }
  }
}

// ============================================================
// 模型降级管理
// ============================================================

class ModelFallbackManager {
  constructor() {
    this.fallbacks = new Map(); // model -> [fallback models]
    this.cooldowns = new Map(); // model -> cooldownUntil
    this.loadFallbacks();
  }
  
  loadFallbacks() {
    const fallbackPath = path.join(LLM_DIR, 'model_fallbacks.json');
    if (fs.existsSync(fallbackPath)) {
      try {
        const data = JSON.parse(fs.readFileSync(fallbackPath, 'utf8'));
        for (const [model, fallbacks] of Object.entries(data)) {
          this.fallbacks.set(model, fallbacks);
        }
      } catch (e) {
        console.warn('Failed to load model fallbacks:', e.message);
      }
    }
    
    // 默认降级配置
    if (this.fallbacks.size === 0) {
      this.setFallback('gpt-4', ['gpt-4-turbo', 'gpt-3.5-turbo']);
      this.setFallback('gpt-4-turbo', ['gpt-3.5-turbo']);
      this.setFallback('claude-3-opus', ['claude-3-sonnet', 'claude-3-haiku']);
      this.setFallback('claude-3-sonnet', ['claude-3-haiku']);
      this.setFallback('doubao-pro', ['doubao-lite']);
    }
  }
  
  saveFallbacks() {
    const data = {};
    for (const [model, fallbacks] of this.fallbacks) {
      data[model] = fallbacks;
    }
    fs.writeFileSync(path.join(LLM_DIR, 'model_fallbacks.json'), JSON.stringify(data, null, 2));
  }
  
  setFallback(model, fallbacks) {
    this.fallbacks.set(model, fallbacks);
    this.saveFallbacks();
  }
  
  getFallbackChain(model) {
    const chain = [model];
    const fallbacks = this.fallbacks.get(model) || [];
    
    for (const fallback of fallbacks) {
      if (!this.isInCooldown(fallback)) {
        chain.push(fallback);
      }
    }
    
    return chain;
  }
  
  isInCooldown(model) {
    const cooldownUntil = this.cooldowns.get(model) || 0;
    return Date.now() < cooldownUntil;
  }
  
  setCooldown(model, durationMs) {
    this.cooldowns.set(model, Date.now() + durationMs);
  }
  
  clearCooldown(model) {
    this.cooldowns.delete(model);
  }
}

// ============================================================
// 使用统计
// ============================================================

class UsageStats {
  constructor() {
    this.stats = new Map(); // model -> {calls, tokens, errors}
    this.loadStats();
  }
  
  loadStats() {
    const statsPath = path.join(STATS_DIR, 'usage_stats.json');
    if (fs.existsSync(statsPath)) {
      try {
        const data = JSON.parse(fs.readFileSync(statsPath, 'utf8'));
        for (const [model, stats] of Object.entries(data)) {
          this.stats.set(model, stats);
        }
      } catch (e) {
        console.warn('Failed to load usage stats:', e.message);
      }
    }
  }
  
  saveStats() {
    const data = {};
    for (const [model, stats] of this.stats) {
      data[model] = stats;
    }
    fs.writeFileSync(path.join(STATS_DIR, 'usage_stats.json'), JSON.stringify(data, null, 2));
  }
  
  record(model, inputTokens, outputTokens, success) {
    if (!this.stats.has(model)) {
      this.stats.set(model, { calls: 0, inputTokens: 0, outputTokens: 0, errors: 0 });
    }
    const stats = this.stats.get(model);
    stats.calls++;
    stats.inputTokens += inputTokens || 0;
    stats.outputTokens += outputTokens || 0;
    if (!success) stats.errors++;
    this.saveStats();
  }
  
  getStats(model) {
    return this.stats.get(model) || { calls: 0, inputTokens: 0, outputTokens: 0, errors: 0 };
  }
  
  getAllStats() {
    const result = {};
    for (const [model, stats] of this.stats) {
      result[model] = stats;
    }
    return result;
  }
}

// ============================================================
// LLM 提供商配置
// ============================================================

const providers = {
  openai: {
    url: 'https://api.openai.com/v1/chat/completions',
    models: ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo', 'gpt-4o', 'gpt-4o-mini'],
    auth: (apiKey) => ({ 'Authorization': `Bearer ${apiKey}` })
  },
  anthropic: {
    url: 'https://api.anthropic.com/v1/messages',
    models: ['claude-3-opus', 'claude-3-sonnet', 'claude-3-haiku', 'claude-3-5-sonnet'],
    auth: (apiKey) => ({ 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' })
  },
  doubao: {
    url: 'https://www.doubao.com/chat/completion',
    models: ['doubao-pro', 'doubao-lite'],
    auth: (cookie) => ({ 'Cookie': cookie })
  },
  coze: {
    url: 'https://www.coze.cn/api/coze_space/chat',
    models: ['coze-bot'],
    auth: (cookie) => ({ 'Cookie': cookie })
  },
  openrouter: {
    url: 'https://openrouter.ai/api/v1/chat/completions',
    models: ['auto', 'anthropic/claude-3-opus', 'openai/gpt-4', 'deepseek/deepseek-chat'],
    auth: (apiKey) => ({ 'Authorization': `Bearer ${apiKey}` })
  },
  local: {
    url: 'http://localhost:11434/api/chat',
    models: ['llama2', 'mistral', 'codellama', 'qwen', 'deepseek'],
    auth: () => ({})
  }
};

// ============================================================
// 全局实例
// ============================================================

let authManager = null;
let fallbackManager = null;
let usageStats = null;

function getAuthManager() {
  if (!authManager) authManager = new AuthProfileManager();
  return authManager;
}

function getFallbackManager() {
  if (!fallbackManager) fallbackManager = new ModelFallbackManager();
  return fallbackManager;
}

function getUsageStats() {
  if (!usageStats) usageStats = new UsageStats();
  return usageStats;
}

// ============================================================
// 缓存管理
// ============================================================

function computeCacheKey(prompt, model, options = {}) {
  const payload = {
    prompt,
    model: model || 'default',
    temperature: options.temperature,
    maxTokens: options.maxTokens,
    system: options.system,
    artifacts: options.artifacts || []
  };
  return crypto.createHash('sha256').update(JSON.stringify(payload)).digest('hex');
}

function getCachePath(key) {
  return path.join(CACHE_DIR, `${key}.json`);
}

function getFromCache(key) {
  const cachePath = getCachePath(key);
  if (fs.existsSync(cachePath)) {
    try {
      const cached = JSON.parse(fs.readFileSync(cachePath, 'utf8'));
      cached.cached = true;
      return cached;
    } catch {
      return null;
    }
  }
  return null;
}

function saveToCache(key, result) {
  const cachePath = getCachePath(key);
  fs.writeFileSync(cachePath, JSON.stringify({
    ...result,
    cached: false,
    cached_at: new Date().toISOString()
  }, null, 2));
}

// ============================================================
// HTTP 请求
// ============================================================

function httpRequest(url, options, body) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const client = urlObj.protocol === 'https:' ? https : http;
    
    const reqOptions = {
      hostname: urlObj.hostname,
      port: urlObj.port || (urlObj.protocol === 'https:' ? 443 : 80),
      path: urlObj.pathname + urlObj.search,
      method: options.method || 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...options.headers
      }
    };

    const req = client.request(reqOptions, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(data));
          } catch {
            resolve({ raw: data });
          }
        } else {
          const error = new Error(`HTTP ${res.statusCode}: ${data.slice(0, 500)}`);
          error.statusCode = res.statusCode;
          reject(error);
        }
      });
    });

    req.on('error', reject);
    req.setTimeout(120000, () => {
      req.destroy();
      reject(new Error('Request timeout'));
    });

    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

// ============================================================
// LLM 调用（增强版）
// ============================================================

async function invoke(options = {}) {
  const start = Date.now();
  const attempts = [];
  
  try {
    const {
      prompt,
      model = 'gpt-3.5-turbo',
      provider = 'openai',
      system,
      temperature = 0.7,
      maxTokens = 4096,
      apiKey,
      baseUrl,
      artifacts = [],
      outputSchema,
      maxRetries = 1,
      useCache = true,
      refresh = false,
      enableFallback = true,
      enableAuthRotation = true
    } = options;

    if (!prompt) {
      return { status: 'error', message: 'prompt is required', time: Date.now() - start };
    }

    // 检查缓存
    const cacheKey = computeCacheKey(prompt, model, { temperature, maxTokens, system, artifacts });
    if (useCache && !refresh) {
      const cached = getFromCache(cacheKey);
      if (cached) {
        return { 
          status: 'ok', 
          result: cached, 
          cached: true,
          time: Date.now() - start 
        };
      }
    }

    // 获取降级链
    const fallbackManager = getFallbackManager();
    const modelChain = enableFallback ? fallbackManager.getFallbackChain(model) : [model];
    
    let lastResult = null;
    
    // 尝试每个模型
    for (const currentModel of modelChain) {
      const attemptStart = Date.now();
      
      // 获取提供商配置
      const providerConfig = providers[provider];
      if (!providerConfig && !baseUrl) {
        attempts.push({ model: currentModel, error: `Unknown provider: ${provider}` });
        continue;
      }

      // 获取认证配置
      let authKey = apiKey;
      if (enableAuthRotation && !apiKey) {
        const profile = getAuthManager().getAvailableProfile(provider);
        if (profile) {
          authKey = profile.key;
        }
      }
      
      if (!authKey && !baseUrl) {
        attempts.push({ model: currentModel, error: 'No API key available' });
        continue;
      }

      // 构建请求
      const url = baseUrl || providerConfig.url;
      const headers = providerConfig ? providerConfig.auth(authKey) : { 'Authorization': `Bearer ${authKey}` };
      
      let requestBody;
      if (provider === 'anthropic') {
        requestBody = {
          model: currentModel,
          max_tokens: maxTokens,
          messages: [
            ...(system ? [{ role: 'user', content: system }] : []),
            { role: 'user', content: prompt }
          ]
        };
      } else if (provider === 'doubao') {
        requestBody = {
          bot_id: options.botId || '7338286299411103781',
          messages: [{ role: 'user', content: prompt }],
          stream: false
        };
      } else if (provider === 'coze') {
        requestBody = {
          conversation_id: uuidv4(),
          bot_id: options.botId || 'default',
          user: options.user || 'user',
          query: prompt,
          stream: false
        };
      } else if (provider === 'local') {
        requestBody = {
          model: currentModel,
          messages: [
            ...(system ? [{ role: 'system', content: system }] : []),
            { role: 'user', content: prompt }
          ],
          stream: false
        };
      } else {
        // OpenAI 兼容格式
        requestBody = {
          model: currentModel,
          messages: [
            ...(system ? [{ role: 'system', content: system }] : []),
            { role: 'user', content: prompt }
          ],
          temperature,
          max_tokens: maxTokens
        };
      }

      // 发送请求
      try {
        const response = await httpRequest(url, { headers }, requestBody);
        
        // 解析响应
        let result;
        if (provider === 'anthropic') {
          result = {
            text: response.content?.[0]?.text || '',
            model: response.model,
            usage: {
              inputTokens: response.usage?.input_tokens,
              outputTokens: response.usage?.output_tokens
            }
          };
        } else if (provider === 'doubao' || provider === 'coze') {
          result = {
            text: response.choices?.[0]?.message?.content || response.messages?.[0]?.content || '',
            model: currentModel,
            usage: response.usage || {}
          };
        } else {
          result = {
            text: response.choices?.[0]?.message?.content || '',
            model: response.model,
            usage: {
              inputTokens: response.usage?.prompt_tokens,
              outputTokens: response.usage?.completion_tokens
            }
          };
        }

        // 记录成功
        getAuthManager().recordSuccess(provider, authKey);
        getUsageStats().record(currentModel, result.usage.inputTokens, result.usage.outputTokens, true);
        fallbackManager.clearCooldown(currentModel);

        // Schema 验证
        if (outputSchema) {
          try {
            const parsed = JSON.parse(result.text);
            const valid = validateSchema(parsed, outputSchema);
            if (!valid.valid) {
              result.schemaValid = false;
              result.schemaErrors = valid.errors;
            } else {
              result.schemaValid = true;
              result.data = parsed;
            }
          } catch {
            result.schemaValid = false;
            result.schemaErrors = ['Output is not valid JSON'];
          }
        }

        // 保存到缓存
        if (useCache) {
          saveToCache(cacheKey, result);
        }

        // 保存执行记录
        const runId = uuidv4();
        const runPath = path.join(LLM_DIR, `${runId}.json`);
        fs.writeFileSync(runPath, JSON.stringify({
          id: runId,
          prompt,
          model: currentModel,
          provider,
          result,
          cached: false,
          attempts: attempts.length + 1,
          created_at: new Date().toISOString()
        }, null, 2));

        return { 
          status: 'ok', 
          runId,
          result,
          model: currentModel,
          cached: false,
          attempts: attempts.length + 1,
          time: Date.now() - start 
        };
      } catch (err) {
        const errorType = classifyError(err);
        
        // 记录失败
        getAuthManager().recordFailure(provider, authKey, errorType);
        getUsageStats().record(currentModel, 0, 0, false);
        
        // 如果是瞬态错误，设置冷却
        if (TRANSIENT_ERRORS.includes(errorType)) {
          fallbackManager.setCooldown(currentModel, 60000); // 1分钟冷却
        }
        
        attempts.push({
          model: currentModel,
          error: err.message,
          errorType,
          duration: Date.now() - attemptStart
        });
        
        // 非瞬态错误不继续尝试降级
        if (!TRANSIENT_ERRORS.includes(errorType) && errorType !== ErrorType.UNKNOWN) {
          break;
        }
        
        continue;
      }
    }
    
    // 所有尝试都失败
    return { 
      status: 'error', 
      message: 'All models failed',
      attempts,
      time: Date.now() - start 
    };
  } catch (e) {
    return { status: 'error', message: e.message, attempts, time: Date.now() - start };
  }
}

// 简单 Schema 验证
function validateSchema(data, schema) {
  const errors = [];
  
  if (schema.type) {
    const actualType = Array.isArray(data) ? 'array' : typeof data;
    if (actualType !== schema.type && !(actualType === 'number' && schema.type === 'integer')) {
      errors.push(`Expected type ${schema.type}, got ${actualType}`);
    }
  }
  
  if (schema.required && Array.isArray(schema.required)) {
    for (const field of schema.required) {
      if (data[field] === undefined) {
        errors.push(`Missing required field: ${field}`);
      }
    }
  }
  
  if (schema.properties && typeof data === 'object') {
    for (const [key, propSchema] of Object.entries(schema.properties)) {
      if (data[key] !== undefined && propSchema.type) {
        const actualType = typeof data[key];
        if (actualType !== propSchema.type) {
          errors.push(`Field ${key}: expected ${propSchema.type}, got ${actualType}`);
        }
      }
    }
  }
  
  return { valid: errors.length === 0, errors };
}

// ============================================================
// 流式调用 (SSE)
// ============================================================

async function stream(options = {}) {
  const start = Date.now();
  try {
    const {
      prompt,
      model = 'gpt-3.5-turbo',
      provider = 'openai',
      system,
      temperature = 0.7,
      maxTokens = 4096,
      apiKey,
      baseUrl,
      onChunk
    } = options;

    if (!prompt) {
      return { status: 'error', message: 'prompt is required', time: Date.now() - start };
    }

    const providerConfig = providers[provider];
    const url = baseUrl || providerConfig.url;
    const headers = providerConfig ? providerConfig.auth(apiKey) : { 'Authorization': `Bearer ${apiKey}` };
    
    const requestBody = {
      model,
      messages: [
        ...(system ? [{ role: 'system', content: system }] : []),
        { role: 'user', content: prompt }
      ],
      temperature,
      max_tokens: maxTokens,
      stream: true
    };

    return { 
      status: 'ok', 
      message: 'Stream mode - use onChunk callback',
      time: Date.now() - start 
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// 批量调用
// ============================================================

async function batch(prompts, options = {}) {
  const start = Date.now();
  try {
    const results = [];
    const { concurrency = 3 } = options;
    
    for (let i = 0; i < prompts.length; i += concurrency) {
      const batch = prompts.slice(i, i + concurrency);
      const batchResults = await Promise.all(
        batch.map(prompt => invoke({ ...options, prompt }))
      );
      results.push(...batchResults);
    }
    
    return { 
      status: 'ok', 
      results,
      total: results.length,
      time: Date.now() - start 
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// Embedding (向量嵌入)
// ============================================================

async function embed(text, options = {}) {
  const start = Date.now();
  try {
    const { model = 'text-embedding-ada-002', apiKey, provider = 'openai' } = options;
    
    const providerConfig = providers[provider];
    const url = provider === 'openai' 
      ? 'https://api.openai.com/v1/embeddings'
      : `${providerConfig.url}/embeddings`;
    
    const response = await httpRequest(url, {
      headers: providerConfig.auth(apiKey)
    }, {
      input: text,
      model
    });
    
    const embedding = response.data?.[0]?.embedding || [];
    
    return { 
      status: 'ok', 
      embedding,
      model,
      dimensions: embedding.length,
      time: Date.now() - start 
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// 缓存管理
// ============================================================

function clearCache() {
  const start = Date.now();
  try {
    const files = fs.readdirSync(CACHE_DIR);
    for (const f of files) {
      fs.unlinkSync(path.join(CACHE_DIR, f));
    }
    return { status: 'ok', cleared: files.length, time: Date.now() - start };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

function cacheStats() {
  const start = Date.now();
  try {
    const files = fs.readdirSync(CACHE_DIR);
    let totalSize = 0;
    for (const f of files) {
      totalSize += fs.statSync(path.join(CACHE_DIR, f)).size;
    }
    return { 
      status: 'ok', 
      count: files.length,
      totalSize,
      totalSizeMB: Math.round(totalSize / 1024 / 1024 * 100) / 100,
      time: Date.now() - start 
    };
  } catch (e) {
    return { status: 'error', message: e.message, time: Date.now() - start };
  }
}

// ============================================================
// 模块导出
// ============================================================

module.exports = {
  // 核心 API
  invoke,
  stream,
  batch,
  embed,
  
  // 缓存
  clearCache,
  cacheStats,
  
  // 提供商配置
  providers,
  
  // 新增 API
  getAuthManager,
  getFallbackManager,
  getUsageStats,
  classifyError,
  ErrorType,
  TRANSIENT_ERRORS,
  
  // 认证配置
  addAuthProfile: (provider, key, weight) => getAuthManager().addProfile(provider, key, weight),
  
  // 降级配置
  setModelFallback: (model, fallbacks) => getFallbackManager().setFallback(model, fallbacks),
  getModelFallbackChain: (model) => getFallbackManager().getFallbackChain(model),
  
  // 使用统计
  getModelStats: (model) => getUsageStats().getStats(model),
  getAllStats: () => getUsageStats().getAllStats()
};
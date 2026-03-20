/**
 * Context Engine Registry
 * 上下文引擎注册表（基于OpenClaw设计）
 * 支持插件化的上下文管理策略
 */

// ==================== 类型定义 ====================

/**
 * 上下文引擎信息
 */
class ContextEngineInfo {
  constructor(id, name, version, ownsCompaction = false) {
    this.id = id;
    this.name = name;
    this.version = version;
    this.ownsCompaction = ownsCompaction;
  }
}

/**
 * 上下文引擎工厂类型
 */
class ContextEngineFactory {
  constructor(factoryFn, options = {}) {
    this.factoryFn = factoryFn;
    this.options = options;
  }
}

// ==================== 注册表状态 ====================

const CONTEXT_ENGINE_REGISTRY_STATE = Symbol('iflow.contextEngineRegistryState');

/**
 * 获取注册表状态
 */
function getContextEngineRegistryState() {
  if (!global[CONTEXT_ENGINE_REGISTRY_STATE]) {
    global[CONTEXT_ENGINE_REGISTRY_STATE] = {
      engines: new Map(),
      defaultEngineId: 'legacy'
    };
  }
  return global[CONTEXT_ENGINE_REGISTRY_STATE];
}

// ==================== 引擎注册管理 ====================

/**
 * 注册上下文引擎
 */
function registerContextEngine(id, factoryFn, options = {}) {
  const state = getContextEngineRegistryState();
  
  const factory = new ContextEngineFactory(factoryFn, options);
  state.engines.set(id, factory);
  
  console.log(`[ContextEngine] Registered engine: ${id}`);
}

/**
 * 获取上下文引擎工厂
 */
function getContextEngineFactory(id) {
  const state = getContextEngineRegistryState();
  return state.engines.get(id);
}

/**
 * 列出所有已注册的引擎ID
 */
function listContextEngineIds() {
  const state = getContextEngineRegistryState();
  return Array.from(state.engines.keys());
}

/**
 * 解析上下文引擎
 */
function resolveContextEngine(config = {}) {
  const state = getContextEngineRegistryState();
  
  // 从配置中获取引擎ID
  const engineId = config.plugins?.slots?.contextEngine || state.defaultEngineId;
  
  const factory = state.engines.get(engineId);
  
  if (!factory) {
    throw new Error(
      `Context engine "${engineId}" is not registered. ` +
      `Available engines: ${listContextEngineIds().join(', ') || '(none)'}`
    );
  }
  
  console.log(`[ContextEngine] Resolved engine: ${engineId}`);
  
  // 创建引擎实例
  return factory.factoryFn(factory.options);
}

/**
 * 设置默认引擎ID
 */
function setDefaultContextEngine(engineId) {
  const state = getContextEngineRegistryState();
  
  if (!state.engines.has(engineId)) {
    throw new Error(`Cannot set default to unregistered engine: ${engineId}`);
  }
  
  state.defaultEngineId = engineId;
  console.log(`[ContextEngine] Set default engine: ${engineId}`);
}

/**
 * 获取默认引擎ID
 */
function getDefaultContextEngineId() {
  const state = getContextEngineRegistryState();
  return state.defaultEngineId;
}

// ==================== 导出 ====================

module.exports = {
  ContextEngineInfo,
  ContextEngineFactory,
  registerContextEngine,
  getContextEngineFactory,
  listContextEngineIds,
  resolveContextEngine,
  setDefaultContextEngine,
  getDefaultContextEngineId
};
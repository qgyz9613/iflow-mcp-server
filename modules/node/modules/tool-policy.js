/**
 * iFlow Tool Policy System
 * 参考 OpenClaw 的多层级工具策略管道
 * 支持：Profile、Global、Agent、Group、Sandbox 策略
 */

const { v4: uuidv4 } = require('uuid');
const path = require('path');
const fs = require('fs');

const DATA_DIR = path.join(__dirname, '..', 'tool-policy-data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

// ==================== 工具 Profile 定义 ====================

/**
 * 预定义工具 Profile
 * 参考 OpenClaw 的 tool-catalog.ts
 */
const TOOL_PROFILES = {
  minimal: {
    id: 'minimal',
    name: 'Minimal',
    description: '最小工具集，仅包含基础文件操作',
    tools: ['read', 'write', 'edit']
  },
  
  coding: {
    id: 'coding',
    name: 'Coding',
    description: '编码工具集，包含文件、执行、Web、Memory',
    tools: [
      // 文件系统
      'read', 'write', 'edit', 'files_scan', 'files_tree',
      // 运行时
      'exec', 'process',
      // Web
      'web_search', 'web_fetch', 'web_gateway',
      // Memory
      'memory_save', 'memory_search', 'memory_list',
      // Browser
      'browser_init', 'browser_navigate', 'browser_click', 'browser_fill',
      // Desktop
      'desktop_mouse', 'desktop_keyboard', 'desktop_screenshot',
      // State
      'state_get', 'state_set'
    ]
  },
  
  messaging: {
    id: 'messaging',
    name: 'Messaging',
    description: '消息工具集，用于通信渠道',
    tools: [
      'channel_send', 'channel_notify',
      'session_create', 'session_load',
      'message_send', 'message_receive'
    ]
  },
  
  full: {
    id: 'full',
    name: 'Full',
    description: '完整工具集，无限制',
    tools: ['*']  // 通配符表示所有工具
  }
};

// ==================== 工具分类 ====================

/**
 * 工具分类定义
 */
const TOOL_CATEGORIES = {
  fs: {
    name: 'File System',
    tools: ['read', 'write', 'edit', 'files_scan', 'files_tree', 'files_copy', 'files_remove']
  },
  
  runtime: {
    name: 'Runtime',
    tools: ['exec', 'process', 'process_monitor', 'process_restart']
  },
  
  web: {
    name: 'Web',
    tools: ['web_search', 'web_fetch', 'web_gateway', 'web_guard', 'link_extraction']
  },
  
  memory: {
    name: 'Memory',
    tools: ['memory_save', 'memory_search', 'memory_list', 'memory_remove', 'memory_stats']
  },
  
  browser: {
    name: 'Browser',
    tools: [
      'browser_init', 'browser_navigate', 'browser_click', 'browser_fill',
      'browser_getText', 'browser_screenshot', 'browser_evaluate', 'browser_close'
    ]
  },
  
  desktop: {
    name: 'Desktop',
    tools: [
      'desktop_mouse', 'desktop_keyboard', 'desktop_screenshot',
      'desktop_window', 'desktop_clipboard'
    ]
  },
  
  channel: {
    name: 'Channel',
    tools: ['channel_send', 'channel_notify', 'channel_config']
  },
  
  session: {
    name: 'Session',
    tools: ['session_create', 'session_load', 'session_addMessage', 'session_list', 'session_remove']
  },
  
  state: {
    name: 'State',
    tools: ['state_get', 'state_set', 'state_list', 'state_delete', 'state_clear']
  },
  
  agent: {
    name: 'Agent',
    tools: ['agent_assign', 'agent_dispatch', 'agent_collaborate', 'subagent_plan', 'subagent_delegate']
  },
  
  llm: {
    name: 'LLM',
    tools: ['llm_invoke', 'llm_stream', 'llm_embed']
  },
  
  hooks: {
    name: 'Hooks',
    tools: ['hooks_register', 'hooks_trigger', 'hooks_list']
  },
  
  skills: {
    name: 'Skills',
    tools: ['skills_search', 'skills_install', 'skills_list', 'skills_execute']
  }
};

// ==================== 策略管道 ====================

/**
 * 策略管道处理器
 * 按顺序应用多个策略层
 */
class ToolPolicyPipeline {
  constructor(config = {}) {
    this.steps = config.steps || [
      'profile',      // Profile 策略
      'global',       // 全局策略
      'agent',        // Agent 策略
      'group',        // Group 策略
      'sandbox',      // Sandbox 策略
      'subagent'      // Subagent 策略
    ];
    
    this.policies = {
      profile: { allow: [], deny: [] },
      global: { allow: [], deny: [] },
      agent: { allow: [], deny: [] },
      group: { allow: [], deny: [] },
      sandbox: { allow: [], deny: [] },
      subagent: { allow: [], deny: [] }
    };
    
    this._loadPolicies();
  }
  
  /**
   * 加载策略配置
   */
  _loadPolicies() {
    const policyPath = path.join(DATA_DIR, 'policies.json');
    if (fs.existsSync(policyPath)) {
      try {
        const data = JSON.parse(fs.readFileSync(policyPath, 'utf8'));
        this.policies = { ...this.policies, ...data };
      } catch (e) {
        console.warn('[ToolPolicy] Failed to load policies:', e.message);
      }
    }
  }
  
  /**
   * 保存策略配置
   */
  _savePolicies() {
    const policyPath = path.join(DATA_DIR, 'policies.json');
    fs.writeFileSync(policyPath, JSON.stringify(this.policies, null, 2));
  }
  
  /**
   * 设置策略
   */
  setPolicy(level, config) {
    if (!this.policies[level]) {
      return { status: 'error', message: `Unknown policy level: ${level}` };
    }
    
    this.policies[level] = {
      allow: config.allow || [],
      deny: config.deny || [],
      profile: config.profile || null
    };
    
    this._savePolicies();
    return { status: 'ok', level, config: this.policies[level] };
  }
  
  /**
   * 获取策略
   */
  getPolicy(level) {
    return this.policies[level] || null;
  }
  
  /**
   * 应用 Profile
   */
  applyProfile(profileId) {
    const profile = TOOL_PROFILES[profileId];
    if (!profile) {
      return { status: 'error', message: `Unknown profile: ${profileId}` };
    }
    
    if (profile.tools.includes('*')) {
      this.policies.profile = { allow: ['*'], deny: [] };
    } else {
      this.policies.profile = { allow: profile.tools, deny: [] };
    }
    
    this._savePolicies();
    return { status: 'ok', profile: profileId, tools: profile.tools };
  }
  
  /**
   * 检查工具是否允许
   */
  isToolAllowed(toolName) {
    // 按管道顺序检查
    let allowed = null;  // null = 未决定, true = 允许, false = 拒绝
    
    for (const step of this.steps) {
      const policy = this.policies[step];
      if (!policy) continue;
      
      // 检查拒绝列表
      if (policy.deny && policy.deny.length > 0) {
        if (policy.deny.includes('*') || policy.deny.includes(toolName)) {
          return false;  // 明确拒绝
        }
      }
      
      // 检查允许列表
      if (policy.allow && policy.allow.length > 0) {
        if (policy.allow.includes('*') || policy.allow.includes(toolName)) {
          allowed = true;  // 明确允许
        }
      }
    }
    
    // 如果没有明确决定，默认允许
    return allowed !== false;
  }
  
  /**
   * 过滤工具列表
   */
  filterTools(tools) {
    return tools.filter(tool => {
      const name = typeof tool === 'string' ? tool : tool.name;
      return this.isToolAllowed(name);
    });
  }
  
  /**
   * 应用策略管道到工具列表
   */
  applyPipeline(tools, options = {}) {
    const start = Date.now();
    
    // 1. 应用 Profile
    let filtered = this.filterTools(tools);
    
    // 2. 应用额外允许
    if (options.extraAllow && options.extraAllow.length > 0) {
      const extraTools = options.extraAllow.filter(name => 
        tools.some(t => (typeof t === 'string' ? t : t.name) === name)
      );
      filtered = [...new Set([...filtered.map(t => typeof t === 'string' ? t : t.name), ...extraTools])];
      filtered = tools.filter(t => filtered.includes(typeof t === 'string' ? t : t.name));
    }
    
    // 3. 应用额外拒绝
    if (options.extraDeny && options.extraDeny.length > 0) {
      filtered = filtered.filter(tool => {
        const name = typeof tool === 'string' ? tool : tool.name;
        return !options.extraDeny.includes(name);
      });
    }
    
    return {
      status: 'ok',
      original: tools.length,
      filtered: filtered.length,
      tools: filtered,
      time: Date.now() - start
    };
  }
  
  /**
   * 获取可用 Profile 列表
   */
  getProfiles() {
    return Object.values(TOOL_PROFILES);
  }
  
  /**
   * 获取工具分类
   */
  getCategories() {
    return Object.entries(TOOL_CATEGORIES).map(([id, cat]) => ({
      id,
      name: cat.name,
      toolCount: cat.tools.length
    }));
  }
  
  /**
   * 获取分类下的工具
   */
  getCategoryTools(categoryId) {
    const category = TOOL_CATEGORIES[categoryId];
    return category ? category.tools : [];
  }
}

// ==================== 工具 Schema 标准化 ====================

/**
 * 工具 Schema 标准化器
 * 适配 OpenAI/Gemini/Anthropic 不同的 Schema 要求
 */
class ToolSchemaNormalizer {
  constructor(config = {}) {
    this.targetFormat = config.targetFormat || 'openai';  // openai, gemini, anthropic
  }
  
  /**
   * 标准化工具参数
   */
  normalize(tool, options = {}) {
    const format = options.format || this.targetFormat;
    
    switch (format) {
      case 'openai':
        return this._normalizeOpenAI(tool);
      case 'gemini':
        return this._normalizeGemini(tool);
      case 'anthropic':
        return this._normalizeAnthropic(tool);
      default:
        return tool;
    }
  }
  
  /**
   * OpenAI 格式
   */
  _normalizeOpenAI(tool) {
    return {
      type: 'function',
      function: {
        name: tool.name,
        description: tool.description || '',
        parameters: tool.inputSchema || tool.parameters || { type: 'object', properties: {} }
      }
    };
  }
  
  /**
   * Gemini 格式
   */
  _normalizeGemini(tool) {
    return {
      name: tool.name,
      description: tool.description || '',
      parameters: tool.inputSchema || tool.parameters || { type: 'object', properties: {} }
    };
  }
  
  /**
   * Anthropic 格式
   */
  _normalizeAnthropic(tool) {
    return {
      name: tool.name,
      description: tool.description || '',
      input_schema: tool.inputSchema || tool.parameters || { type: 'object', properties: {} }
    };
  }
  
  /**
   * 批量标准化
   */
  normalizeAll(tools, options = {}) {
    return tools.map(tool => this.normalize(tool, options));
  }
}

// ==================== 工具注册表 ====================

/**
 * 工具注册表
 * 管理所有可用工具的定义
 */
class ToolRegistry {
  constructor() {
    this.tools = new Map();
    this.categories = new Map(Object.entries(TOOL_CATEGORIES));
    this._loadRegistry();
  }
  
  /**
   * 注册工具
   */
  register(tool) {
    const definition = {
      name: tool.name,
      description: tool.description || '',
      category: tool.category || 'general',
      handler: tool.handler,
      inputSchema: tool.inputSchema || tool.parameters || { type: 'object', properties: {} },
      profiles: tool.profiles || ['full'],
      dangerous: tool.dangerous || false,
      requiresConfirmation: tool.requiresConfirmation || false
    };
    
    this.tools.set(tool.name, definition);
    this._saveRegistry();
    
    return { status: 'ok', name: tool.name };
  }
  
  /**
   * 注销工具
   */
  unregister(name) {
    const deleted = this.tools.delete(name);
    if (deleted) this._saveRegistry();
    return { status: 'ok', deleted };
  }
  
  /**
   * 获取工具
   */
  getTool(name) {
    return this.tools.get(name);
  }
  
  /**
   * 获取所有工具
   */
  getAllTools() {
    return Array.from(this.tools.values());
  }
  
  /**
   * 按分类获取工具
   */
  getToolsByCategory(category) {
    return this.getAllTools().filter(t => t.category === category);
  }
  
  /**
   * 搜索工具
   */
  search(query) {
    const q = query.toLowerCase();
    return this.getAllTools().filter(t => 
      t.name.toLowerCase().includes(q) || 
      t.description.toLowerCase().includes(q)
    );
  }
  
  /**
   * 执行工具
   */
  async execute(name, params, context = {}) {
    const tool = this.tools.get(name);
    if (!tool) {
      return { status: 'error', message: `Tool not found: ${name}` };
    }
    
    if (typeof tool.handler !== 'function') {
      return { status: 'error', message: `Tool has no handler: ${name}` };
    }
    
    try {
      const result = await tool.handler(params, context);
      return { status: 'ok', result, tool: name };
    } catch (e) {
      return { status: 'error', message: e.message, tool: name };
    }
  }
  
  /**
   * 保存注册表
   */
  _saveRegistry() {
    const registryPath = path.join(DATA_DIR, 'registry.json');
    const data = this.getAllTools().map(t => ({
      name: t.name,
      description: t.description,
      category: t.category,
      inputSchema: t.inputSchema,
      profiles: t.profiles,
      dangerous: t.dangerous,
      requiresConfirmation: t.requiresConfirmation
    }));
    fs.writeFileSync(registryPath, JSON.stringify(data, null, 2));
  }
  
  /**
   * 加载注册表
   */
  _loadRegistry() {
    const registryPath = path.join(DATA_DIR, 'registry.json');
    if (fs.existsSync(registryPath)) {
      try {
        const data = JSON.parse(fs.readFileSync(registryPath, 'utf8'));
        for (const tool of data) {
          this.tools.set(tool.name, tool);
        }
      } catch (e) {
        console.warn('[ToolRegistry] Failed to load registry:', e.message);
      }
    }
  }
}

// ==================== 导出 ====================

module.exports = {
  // 策略管道
  ToolPolicyPipeline,
  
  // Schema 标准化
  ToolSchemaNormalizer,
  
  // 工具注册表
  ToolRegistry,
  
  // 常量
  TOOL_PROFILES,
  TOOL_CATEGORIES,
  
  // 快捷方法
  createPipeline: (config) => new ToolPolicyPipeline(config),
  createRegistry: () => new ToolRegistry(),
  createNormalizer: (config) => new ToolSchemaNormalizer(config)
};

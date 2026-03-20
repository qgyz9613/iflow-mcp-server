/**
 * iFlow Config Validation Module
 * 配置验证模块（基于OpenClaw zod-schema设计）
 * 
 * 功能:
 * - Zod schema验证
 * - 配置类型定义
 * - 验证错误报告
 * - 配置迁移
 */

// ==================== 简化版Schema系统 ====================
// 注：如果安装了zod，可替换为真正的zod

/**
 * Schema类型定义
 */
const SchemaTypes = {
  STRING: 'string',
  NUMBER: 'number',
  BOOLEAN: 'boolean',
  OBJECT: 'object',
  ARRAY: 'array',
  ENUM: 'enum',
  OPTIONAL: 'optional',
  UNION: 'union'
};

/**
 * 基础Schema类
 */
class Schema {
  constructor(type, options = {}) {
    this.type = type;
    this.options = options;
    this._optional = false;
    this._default = undefined;
    this._transform = null;
  }
  
  optional() {
    this._optional = true;
    return this;
  }
  
  default(value) {
    this._default = value;
    this._optional = true;
    return this;
  }
  
  transform(fn) {
    this._transform = fn;
    return this;
  }
  
  validate(value) {
    if (value === undefined || value === null) {
      if (this._optional) {
        return { success: true, data: this._default };
      }
      return { success: false, error: 'Value is required' };
    }
    
    let data = value;
    
    if (this._transform) {
      try {
        data = this._transform(value);
      } catch (err) {
        return { success: false, error: err.message };
      }
    }
    
    return this._validateType(data);
  }
  
  _validateType(value) {
    throw new Error('Subclass must implement _validateType');
  }
}

/**
 * 字符串Schema
 */
class StringSchema extends Schema {
  constructor(options = {}) {
    super(SchemaTypes.STRING, options);
    this._min = options.min;
    this._max = options.max;
    this._pattern = options.pattern;
  }
  
  min(length) {
    this._min = length;
    return this;
  }
  
  max(length) {
    this._max = length;
    return this;
  }
  
  pattern(regex) {
    this._pattern = regex;
    return this;
  }
  
  _validateType(value) {
    if (typeof value !== 'string') {
      return { success: false, error: `Expected string, got ${typeof value}` };
    }
    
    if (this._min !== undefined && value.length < this._min) {
      return { success: false, error: `String must be at least ${this._min} characters` };
    }
    
    if (this._max !== undefined && value.length > this._max) {
      return { success: false, error: `String must be at most ${this._max} characters` };
    }
    
    if (this._pattern && !this._pattern.test(value)) {
      return { success: false, error: `String does not match pattern ${this._pattern}` };
    }
    
    return { success: true, data: value };
  }
}

/**
 * 数字Schema
 */
class NumberSchema extends Schema {
  constructor(options = {}) {
    super(SchemaTypes.NUMBER, options);
    this._min = options.min;
    this._max = options.max;
    this._int = options.int;
  }
  
  min(value) {
    this._min = value;
    return this;
  }
  
  max(value) {
    this._max = value;
    return this;
  }
  
  int() {
    this._int = true;
    return this;
  }
  
  _validateType(value) {
    if (typeof value !== 'number' || isNaN(value)) {
      return { success: false, error: `Expected number, got ${typeof value}` };
    }
    
    if (this._int && !Number.isInteger(value)) {
      return { success: false, error: 'Expected integer' };
    }
    
    if (this._min !== undefined && value < this._min) {
      return { success: false, error: `Number must be at least ${this._min}` };
    }
    
    if (this._max !== undefined && value > this._max) {
      return { success: false, error: `Number must be at most ${this._max}` };
    }
    
    return { success: true, data: value };
  }
}

/**
 * 布尔Schema
 */
class BooleanSchema extends Schema {
  constructor() {
    super(SchemaTypes.BOOLEAN);
  }
  
  _validateType(value) {
    if (typeof value !== 'boolean') {
      return { success: false, error: `Expected boolean, got ${typeof value}` };
    }
    return { success: true, data: value };
  }
}

/**
 * 对象Schema
 */
class ObjectSchema extends Schema {
  constructor(shape) {
    super(SchemaTypes.OBJECT);
    this.shape = shape;
  }
  
  _validateType(value) {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      return { success: false, error: `Expected object, got ${typeof value}` };
    }
    
    const result = {};
    const errors = {};
    
    for (const [key, schema] of Object.entries(this.shape)) {
      const fieldResult = schema.validate(value[key]);
      
      if (fieldResult.success) {
        if (fieldResult.data !== undefined) {
          result[key] = fieldResult.data;
        }
      } else {
        errors[key] = fieldResult.error;
      }
    }
    
    if (Object.keys(errors).length > 0) {
      return { success: false, error: errors };
    }
    
    return { success: true, data: result };
  }
}

/**
 * 数组Schema
 */
class ArraySchema extends Schema {
  constructor(elementSchema) {
    super(SchemaTypes.ARRAY);
    this.elementSchema = elementSchema;
    this._min = undefined;
    this._max = undefined;
  }
  
  min(length) {
    this._min = length;
    return this;
  }
  
  max(length) {
    this._max = length;
    return this;
  }
  
  _validateType(value) {
    if (!Array.isArray(value)) {
      return { success: false, error: `Expected array, got ${typeof value}` };
    }
    
    if (this._min !== undefined && value.length < this._min) {
      return { success: false, error: `Array must have at least ${this._min} elements` };
    }
    
    if (this._max !== undefined && value.length > this._max) {
      return { success: false, error: `Array must have at most ${this._max} elements` };
    }
    
    const result = [];
    const errors = [];
    
    for (let i = 0; i < value.length; i++) {
      const elementResult = this.elementSchema.validate(value[i]);
      
      if (elementResult.success) {
        result.push(elementResult.data);
      } else {
        errors.push({ index: i, error: elementResult.error });
      }
    }
    
    if (errors.length > 0) {
      return { success: false, error: errors };
    }
    
    return { success: true, data: result };
  }
}

/**
 * 枚举Schema
 */
class EnumSchema extends Schema {
  constructor(values) {
    super(SchemaTypes.ENUM);
    this.values = values;
  }
  
  _validateType(value) {
    if (!this.values.includes(value)) {
      return { success: false, error: `Expected one of [${this.values.join(', ')}], got ${value}` };
    }
    return { success: true, data: value };
  }
}

// ==================== Schema构建函数 ====================

const z = {
  string: () => new StringSchema(),
  number: () => new NumberSchema(),
  boolean: () => new BooleanSchema(),
  object: (shape) => new ObjectSchema(shape),
  array: (elementSchema) => new ArraySchema(elementSchema),
  enum: (values) => new EnumSchema(values),
  optional: (schema) => schema.optional()
};

// ==================== iFlow配置Schema ====================

/**
 * Agent配置Schema
 */
const AgentConfigSchema = z.object({
  id: z.string().min(1),
  name: z.string().optional(),
  default: z.boolean().optional(),
  workspace: z.string().optional(),
  agentDir: z.string().optional(),
  
  model: z.object({
    primary: z.string().optional(),
    fallbacks: z.array(z.string()).optional()
  }).optional(),
  
  skills: z.array(z.string()).optional(),
  
  memory: z.object({
    enabled: z.boolean().optional(),
    maxResults: z.number().optional(),
    decayHalfLife: z.number().optional()
  }).optional(),
  
  humanDelay: z.object({
    enabled: z.boolean().optional(),
    minMs: z.number().optional(),
    maxMs: z.number().optional()
  }).optional(),
  
  subagents: z.object({
    allowAgents: z.array(z.string()).optional(),
    model: z.string().optional()
  }).optional(),
  
  tools: z.object({
    allow: z.array(z.string()).optional(),
    deny: z.array(z.string()).optional()
  }).optional()
});

/**
 * Memory配置Schema
 */
const MemoryConfigSchema = z.object({
  backend: z.enum(['builtin', 'qmd', 'sqlite']).optional(),
  citations: z.enum(['auto', 'on', 'off']).optional(),
  
  timeDecay: z.object({
    halfLife: z.number().optional(),
    baseDecay: z.number().min(0).max(1).optional(),
    evergreenTags: z.array(z.string()).optional()
  }).optional(),
  
  mmr: z.object({
    enabled: z.boolean().optional(),
    lambda: z.number().min(0).max(1).optional()
  }).optional(),
  
  embedding: z.object({
    provider: z.enum(['openai', 'gemini', 'voyage', 'mistral', 'ollama', 'local']).optional(),
    model: z.string().optional(),
    dimensions: z.number().optional()
  }).optional()
});

/**
 * Hooks配置Schema
 */
const HooksConfigSchema = z.object({
  events: z.array(z.string()).optional(),
  handlers: z.object({}).optional(),
  filters: z.array(z.object({
    event: z.string(),
    condition: z.string().optional()
  })).optional()
});

/**
 * 完整配置Schema
 */
const FullConfigSchema = z.object({
  agents: z.object({
    defaults: AgentConfigSchema.optional(),
    list: z.array(AgentConfigSchema).optional()
  }).optional(),
  
  memory: MemoryConfigSchema.optional(),
  
  hooks: HooksConfigSchema.optional(),
  
  providers: z.object({}).optional(),
  
  skills: z.object({
    allowlist: z.array(z.string()).optional(),
    bundled: z.array(z.string()).optional()
  }).optional(),
  
  gateway: z.object({
    port: z.number().optional(),
    host: z.string().optional()
  }).optional(),
  
  logging: z.object({
    level: z.enum(['debug', 'info', 'warn', 'error']).optional(),
    file: z.string().optional()
  }).optional()
});

// ==================== 验证函数 ====================

/**
 * 验证配置
 * @param {Object} config - 配置对象
 * @param {Schema} schema - Schema
 * @returns {Object} - 验证结果
 */
function validateConfig(config, schema = FullConfigSchema) {
  return schema.validate(config);
}

/**
 * 验证并抛出错误
 */
function validateConfigOrThrow(config, schema = FullConfigSchema) {
  const result = schema.validate(config);
  
  if (!result.success) {
    const error = new Error('Config validation failed');
    error.details = result.error;
    throw error;
  }
  
  return result.data;
}

/**
 * 格式化验证错误
 */
function formatValidationError(error) {
  if (typeof error === 'string') {
    return error;
  }
  
  if (Array.isArray(error)) {
    return error.map(e => 
      `Index ${e.index}: ${formatValidationError(e.error)}`
    ).join('\n');
  }
  
  if (typeof error === 'object') {
    return Object.entries(error)
      .map(([key, value]) => `${key}: ${formatValidationError(value)}`)
      .join('\n');
  }
  
  return String(error);
}

// ==================== 导出 ====================

module.exports = {
  // Schema类型
  SchemaTypes,
  
  // Schema类
  Schema,
  StringSchema,
  NumberSchema,
  BooleanSchema,
  ObjectSchema,
  ArraySchema,
  EnumSchema,
  
  // Schema构建器
  z,
  
  // 预定义Schema
  AgentConfigSchema,
  MemoryConfigSchema,
  HooksConfigSchema,
  FullConfigSchema,
  
  // 验证函数
  validateConfig,
  validateConfigOrThrow,
  formatValidationError
};

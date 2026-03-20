/**
 * iFlow Routing Module
 * 路由解析模块（基于OpenClaw routing设计）
 * 
 * 功能:
 * - 多级绑定匹配
 * - 会话键构建
 * - 账户ID规范化
 * - 最后路由策略
 */

// ==================== 常量 ====================

const DEFAULT_ACCOUNT_ID = 'default';
const DEFAULT_AGENT_ID = 'default';

// ==================== 类型定义 ====================

/**
 * 路由节点类型
 */
const RoutePeerKind = {
  USER: 'user',
  CHANNEL: 'channel',
  GROUP: 'group',
  THREAD: 'thread'
};

/**
 * 路由节点
 */
class RoutePeer {
  constructor(kind, id) {
    this.kind = kind;
    this.id = id;
  }
}

/**
 * 解析的路由结果
 */
class ResolvedAgentRoute {
  constructor(data = {}) {
    this.agentId = data.agentId || DEFAULT_AGENT_ID;
    this.channel = data.channel || 'unknown';
    this.accountId = data.accountId || DEFAULT_ACCOUNT_ID;
    this.sessionKey = data.sessionKey || '';
    this.mainSessionKey = data.mainSessionKey || '';
    this.lastRoutePolicy = data.lastRoutePolicy || 'main';
    this.matchedBy = data.matchedBy || 'default';
  }
}

// ==================== ID规范化 ====================

/**
 * 规范化账户ID
 */
function normalizeAccountId(accountId) {
  if (!accountId) return DEFAULT_ACCOUNT_ID;
  
  const trimmed = String(accountId).trim().toLowerCase();
  return trimmed || DEFAULT_ACCOUNT_ID;
}

/**
 * 规范化代理ID
 */
function normalizeAgentId(agentId) {
  if (!agentId) return DEFAULT_AGENT_ID;
  
  const trimmed = String(agentId).trim().toLowerCase();
  return trimmed || DEFAULT_AGENT_ID;
}

/**
 * 净化代理ID（移除特殊字符）
 */
function sanitizeAgentId(agentId) {
  if (!agentId) return DEFAULT_AGENT_ID;
  
  return String(agentId)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '_')
    .substring(0, 64);
}

/**
 * 规范化Token
 */
function normalizeToken(value) {
  return (value || '').trim().toLowerCase();
}

/**
 * 规范化ID
 */
function normalizeId(value) {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'bigint') return String(value).trim();
  return '';
}

// ==================== 会话键构建 ====================

/**
 * 构建代理主会话键
 * 格式: agentId:channel:accountId
 */
function buildAgentMainSessionKey(params) {
  const {
    agentId,
    channel,
    accountId
  } = params;
  
  const parts = [
    sanitizeAgentId(agentId),
    normalizeToken(channel) || 'unknown',
    normalizeAccountId(accountId)
  ];
  
  return parts.join(':');
}

/**
 * 构建代理对等会话键
 * 格式: agentId:channel:accountId:peerKind:peerId
 */
function buildAgentPeerSessionKey(params) {
  const {
    agentId,
    channel,
    accountId,
    peer
  } = params;
  
  const mainKey = buildAgentMainSessionKey({ agentId, channel, accountId });
  
  if (!peer) return mainKey;
  
  return `${mainKey}:${peer.kind}:${normalizeId(peer.id)}`;
}

/**
 * 构建代理会话键
 */
function buildAgentSessionKey(params) {
  const {
    agentId,
    channel,
    accountId,
    peer,
    dmScope = 'main',
    identityLinks = {}
  } = params;
  
  // DM作用域处理
  if (peer && peer.kind === RoutePeerKind.USER) {
    switch (dmScope) {
      case 'per-peer':
        return buildAgentPeerSessionKey({ agentId, channel, accountId, peer });
        
      case 'per-channel-peer':
        return `${buildAgentMainSessionKey({ agentId, channel, accountId })}:user:${normalizeId(peer.id)}`;
        
      case 'per-account-channel-peer':
        return `${buildAgentMainSessionKey({ agentId, channel, accountId })}:${normalizeId(peer.id)}`;
        
      case 'main':
      default:
        return buildAgentMainSessionKey({ agentId, channel, accountId });
    }
  }
  
  // 群组/频道消息
  if (peer && (peer.kind === RoutePeerKind.GROUP || peer.kind === RoutePeerKind.CHANNEL)) {
    return buildAgentPeerSessionKey({ agentId, channel, accountId, peer });
  }
  
  // 线程
  if (peer && peer.kind === RoutePeerKind.THREAD) {
    return buildAgentPeerSessionKey({ agentId, channel, accountId, peer });
  }
  
  return buildAgentMainSessionKey({ agentId, channel, accountId });
}

// ==================== 最后路由策略 ====================

/**
 * 推导最后路由策略
 */
function deriveLastRoutePolicy(params) {
  const { sessionKey, mainSessionKey } = params;
  return sessionKey === mainSessionKey ? 'main' : 'session';
}

/**
 * 解析入站最后路由会话键
 */
function resolveInboundLastRouteSessionKey(params) {
  const { route, sessionKey } = params;
  return route.lastRoutePolicy === 'main' ? route.mainSessionKey : sessionKey;
}

// ==================== 绑定解析 ====================

/**
 * 绑定规则
 */
class BindingRule {
  constructor(data = {}) {
    this.agentId = data.agentId || DEFAULT_AGENT_ID;
    this.channel = data.channel || null;
    this.accountId = data.accountId || null;
    this.peerId = data.peerId || null;
    this.peerKind = data.peerKind || null;
    this.guildId = data.guildId || null;
    this.teamId = data.teamId || null;
    this.roleIds = data.roleIds || [];
    this.priority = data.priority || 0;
  }
  
  matches(params) {
    const { channel, accountId, peer, guildId, teamId, memberRoleIds } = params;
    
    // 渠道匹配
    if (this.channel && this.channel !== normalizeToken(channel)) {
      return false;
    }
    
    // 账户匹配
    if (this.accountId && this.accountId !== normalizeAccountId(accountId)) {
      return false;
    }
    
    // 对等节点匹配
    if (this.peerId || this.peerKind) {
      if (!peer) return false;
      if (this.peerId && this.peerId !== normalizeId(peer.id)) return false;
      if (this.peerKind && this.peerKind !== peer.kind) return false;
    }
    
    // 服务器/团队匹配
    if (this.guildId && this.guildId !== normalizeId(guildId)) return false;
    if (this.teamId && this.teamId !== normalizeId(teamId)) return false;
    
    // 角色匹配
    if (this.roleIds && this.roleIds.length > 0) {
      if (!memberRoleIds || memberRoleIds.length === 0) return false;
      const hasRole = this.roleIds.some(roleId => 
        memberRoleIds.some(id => normalizeId(id) === normalizeId(roleId))
      );
      if (!hasRole) return false;
    }
    
    return true;
  }
}

// ==================== 路由解析 ====================

/**
 * 解析代理路由
 */
function resolveAgentRoute(params) {
  const {
    cfg,
    channel,
    accountId,
    peer,
    parentPeer,
    guildId,
    teamId,
    memberRoleIds
  } = params;
  
  const normalizedChannel = normalizeToken(channel);
  const normalizedAccountId = normalizeAccountId(accountId);
  
  // 获取绑定规则
  const bindings = cfg?.bindings || [];
  
  // 按优先级排序
  const sortedBindings = bindings
    .map(b => new BindingRule(b))
    .sort((a, b) => b.priority - a.priority);
  
  // 尝试匹配
  let matchedBinding = null;
  let matchedBy = 'default';
  
  for (const binding of sortedBindings) {
    if (binding.matches({ channel, accountId, peer, guildId, teamId, memberRoleIds })) {
      matchedBinding = binding;
      
      // 确定匹配类型
      if (binding.peerId && binding.peerKind) {
        matchedBy = 'binding.peer';
      } else if (binding.guildId && binding.roleIds.length > 0) {
        matchedBy = 'binding.guild+roles';
      } else if (binding.guildId) {
        matchedBy = 'binding.guild';
      } else if (binding.teamId) {
        matchedBy = 'binding.team';
      } else if (binding.accountId) {
        matchedBy = 'binding.account';
      } else if (binding.channel) {
        matchedBy = 'binding.channel';
      }
      
      break;
    }
  }
  
  // 尝试匹配父级对等节点（线程继承）
  if (!matchedBinding && parentPeer) {
    for (const binding of sortedBindings) {
      if (binding.matches({ channel, accountId, peer: parentPeer, guildId, teamId, memberRoleIds })) {
        matchedBinding = binding;
        matchedBy = 'binding.peer.parent';
        break;
      }
    }
  }
  
  // 确定代理ID
  const agentId = matchedBinding?.agentId || 
    cfg?.defaultAgentId || 
    DEFAULT_AGENT_ID;
  
  // 构建会话键
  const sessionKey = buildAgentSessionKey({
    agentId,
    channel: normalizedChannel,
    accountId: normalizedAccountId,
    peer,
    dmScope: cfg?.dmScope || 'main'
  });
  
  const mainSessionKey = buildAgentMainSessionKey({
    agentId,
    channel: normalizedChannel,
    accountId: normalizedAccountId
  });
  
  return new ResolvedAgentRoute({
    agentId,
    channel: normalizedChannel,
    accountId: normalizedAccountId,
    sessionKey,
    mainSessionKey,
    lastRoutePolicy: deriveLastRoutePolicy({ sessionKey, mainSessionKey }),
    matchedBy
  });
}

// ==================== 绑定管理 ====================

/**
 * 列出绑定
 */
function listBindings(cfg) {
  return (cfg?.bindings || []).map(b => new BindingRule(b));
}

/**
 * 添加绑定
 */
function addBinding(cfg, binding) {
  if (!cfg.bindings) {
    cfg.bindings = [];
  }
  
  cfg.bindings.push(new BindingRule(binding).toJSON());
}

/**
 * 移除绑定
 */
function removeBinding(cfg, index) {
  if (cfg.bindings && index >= 0 && index < cfg.bindings.length) {
    cfg.bindings.splice(index, 1);
    return true;
  }
  return false;
}

// ==================== 导出 ====================

module.exports = {
  // 常量
  DEFAULT_ACCOUNT_ID,
  DEFAULT_AGENT_ID,
  
  // 类型
  RoutePeerKind,
  RoutePeer,
  ResolvedAgentRoute,
  BindingRule,
  
  // ID规范化
  normalizeAccountId,
  normalizeAgentId,
  sanitizeAgentId,
  normalizeToken,
  normalizeId,
  
  // 会话键构建
  buildAgentMainSessionKey,
  buildAgentPeerSessionKey,
  buildAgentSessionKey,
  
  // 路由策略
  deriveLastRoutePolicy,
  resolveInboundLastRouteSessionKey,
  
  // 路由解析
  resolveAgentRoute,
  
  // 绑定管理
  listBindings,
  addBinding,
  removeBinding
};

# iFlow MCP Server

> iFlow AI Agent 核心模块与技能集合 - 提供完整的桌面自动化、浏览器控制、多代理协同、记忆系统、消息通道等功能

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-18+-green.svg)](https://nodejs.org/)
[![Modules](https://img.shields.io/badge/Modules-186-blue.svg)]()
[![Tools](https://img.shields.io/badge/Tools-950+-orange.svg)]()

## 📖 简介

iFlow MCP Server 是一个基于 Model Context Protocol (MCP) 的定制工具服务器，提供丰富的自动化和数据处理能力。采用 Python + Node.js 混合架构，支持 **950+ 工具函数**。

### 📊 当前版本统计

| 类型 | 数量 | 说明 |
|------|------|------|
| **Python 模块** | 29 | 浏览器自动化、桌面控制、股票分析等 |
| **Node.js 模块** | 157 | 缓存、日志、安全、会话等 |
| **总模块数** | 186 | 所有 .py 和 .js 文件 |
| **工具函数** | 950+ | 所有可调用的工具函数 |

## ✨ 特性

- 🔧 **模块化设计** - 自动发现和加载模块
- 🐍 **Python 模块** - 浏览器自动化、桌面控制、金融查询等
- 📦 **Node.js 模块** - 90+ 工具模块，覆盖缓存、日志、安全等
- 🔒 **安全防护** - 命令注入防护、SSRF 防护、参数验证
- 🌐 **跨平台** - 支持 Windows / macOS / Linux

## 🚀 快速开始

### 安装依赖

```bash
# Python 依赖
pip install mcp pyautogui pyperclip requests akshare pandas

# Node.js 依赖
npm install @modelcontextprotocol/sdk better-sqlite3
```

### 启动服务器

```bash
# Python MCP Server
python mcp-server/server.py

# Node.js MCP Server
node modules/node/mcp-server.js
```

## 📁 项目结构

```
.iflow/
├── mcp-server/               # Python MCP 服务器
│   ├── server.py             # 主服务入口
│   └── requirements.txt      # Python 依赖
│
├── modules/                  # 模块目录
│   ├── browser/              # 浏览器自动化
│   ├── desktop/              # 桌面控制
│   ├── db_client.py          # 数据库客户端
│   ├── finance_query.py      # 金融查询
│   ├── memory_sync.py        # 记忆同步
│   ├── remote_memory.py      # 远程记忆
│   ├── realtime_vision.py    # 实时视觉
│   ├── smart_click.py        # 智能点击
│   ├── stock_*.py            # 股票分析模块
│   │
│   └── node/                 # Node.js 模块
│       ├── index.js          # 主入口
│       ├── mcp-server.js     # MCP 服务器
│       ├── hybrid/           # 混合模块
│       │   ├── desktop.py    # 桌面控制 (Python)
│       │   ├── server.py     # HTTP 服务器
│       │   └── index.js      # Node.js 入口
│       │
│       └── modules/          # 90+ 工具模块
│           ├── heartbeat.js  # 心跳监控
│           ├── hooks.js      # 钩子系统
│           ├── skills.js     # 技能管理
│           ├── session.js    # 会话管理
│           ├── cache.js      # 缓存工具
│           ├── logging.js    # 日志系统
│           ├── security*.js  # 安全工具
│           └── ...
│
└── .gitignore               # Git 忽略配置
```

## 🛠️ 核心模块

### Python 模块

| 模块 | 功能 | 工具数 |
|------|------|--------|
| `browser` | 浏览器自动化 (Playwright) | 40+ |
| `desktop` | 桌面控制 (鼠标/键盘/剪贴板) | 20+ |
| `db_client` | 数据库客户端 | 5 |
| `finance_query` | 金融数据查询 (AKShare) | 8 |
| `memory_sync` | 本地/远程记忆同步 | 6 |
| `remote_memory` | 远程记忆 API | 5 |
| `realtime_vision` | 实时视觉分析 | 4 |
| `smart_click` | 智能点击定位 | 5 |
| `stock_*` | 股票分析 (12个子模块) | 100+ |

### Node.js 模块 (90+)

| 分类 | 模块 | 功能 |
|------|------|------|
| **核心** | heartbeat, hooks, skills, session | 系统核心功能 |
| **缓存** | cache, cache-utils, dedupe-cache | 缓存管理 |
| **日志** | logging, diagnostic-events | 日志记录 |
| **安全** | security-utils, security-enhanced, http-guard | 安全防护 |
| **数据** | json-file, sqlite-memory, data-validation | 数据处理 |
| **工具** | utils-base, string-utils, net-utils | 通用工具 |
| **进程** | process-monitor, process-restart, subagent | 进程管理 |
| **文件** | file-atomic, file-security, path-resolver | 文件操作 |
| **重试** | enhanced-retry, retry-policy, rate-limit | 重试限流 |

## 🔒 安全特性

### v2.2.0 安全修复

| 问题类型 | 修复数量 | 修复方案 |
|----------|----------|----------|
| **命令注入** | 8 | base64 编码 + 参数化 |
| **SSRF** | 4 | URL 白名单验证 |
| **SQL 注入** | 3 | 参数化查询 |
| **硬编码密钥** | 6 | 环境变量配置 |
| **异常处理** | 50+ | try-catch 包裹 |

### 安全函数

```python
# PowerShell 命令转义
_escape_powershell_string(text)

# CMD 命令转义
_escape_cmd_string(text)

# URL 白名单验证
_is_allowed_url(url)

# 参数验证
validate_params(params, schema)
```

```javascript
// Node.js 安全工具
const { validateInput, sanitizeText, rateLimit } = require('./modules/security-utils');
```

## 📊 性能优化

- **HTTP 连接池** - requests.Session 复用
- **SQLite 并发锁** - threading.Lock 保护
- **异步执行** - asyncio + ThreadPoolExecutor
- **输出截断** - 自动限制 50K 字符，防止 token 超限

## 🔧 配置

### 环境变量

```bash
# API 密钥 (可选)
IFLOW_API_KEY=your_api_key
IFLOW_DB_API=http://localhost:18080
IFLOW_MEMORY_API=http://localhost:18080

# FAILSAFE 配置
IFLOW_FAILSAFE=true

# 超时配置
AKSHARE_TIMEOUT=30
REQUEST_TIMEOUT=10
```

### .gitignore

```gitignore
# 敏感信息
secrets.json
*.key
*.pem

# 依赖
node_modules/
__pycache__/

# 数据库
*.db
*.sqlite

# 浏览器数据
browser-data/
browser_data/

# 日志
logs/
*.log
```

## 📈 版本历史

### v2.2.0 (2026-03-20)
- ✅ 修复 338 个 BUG (52 致命 / 78 高危 / 122 中等 / 86 轻微)
- ✅ 新增安全函数：命令转义、URL 验证、参数验证
- ✅ 优化异常处理：所有 requests 调用添加 try-catch
- ✅ 性能优化：HTTP Session 复用、SQLite 并发锁

### v2.1.0 (2026-03-15)
- ✅ 新增 90+ Node.js 模块
- ✅ 实现混合架构 (Python + Node.js)
- ✅ 添加心跳监控、钩子系统

### v2.0.0 (2026-03-10)
- ✅ 重构为模块化架构
- ✅ 自动模块发现和加载
- ✅ 输出长度限制

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

---

**GitHub**: https://github.com/qgyz9613/iflow-mcp-server

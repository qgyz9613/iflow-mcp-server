# iFlow MCP Server

> iFlow AI Agent 核心模块与技能集合 - 提供完整的桌面自动化、浏览器控制、多代理协同、记忆系统、消息通道等功能

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-18+-green.svg)](https://nodejs.org/)
[![Modules](https://img.shields.io/badge/Modules-188-blue.svg)]()
[![Tools](https://img.shields.io/badge/Tools-960+-orange.svg)]()

本项目包含 iFlow AI Agent 的核心模块和技能，提供完整的桌面自动化、浏览器控制、多代理协同、记忆系统、消息通道等功能。当前版本包含 **188个模块**，约 **960个工具**，支持高度可配置的自主代理系统。

**2026-03-20 更新**: 新增统一交易系统模块（unified_trading.py）和ML预测模块（ml_predictor.py），整合fortune和stock-trading-system的所有功能。

## 🚀 快速开始

```bash
# 安装 Node.js 依赖
cd modules/node
npm install
npm run mcp

# 安装 Python 依赖
pip install -r mcp-server/requirements.txt
python mcp-server/server.py
```

## 📦 模块总览

### 🤖 AI 与代理核心

| 模块 | 功能描述 |
|------|----------|
| `subagent` | 多代理协同、并行执行、任务委派、状态持久化 |
| `agents` | 角色定义、多模型路由、协作模式、动态代理 |
| `autonomous` | 自主决策、目标追踪、自主运行引擎 |
| `decision` | 决策支持、偏好学习、决策历史管理 |
| `heartbeat` | 心跳监控、定时任务、自主运行引擎、cron调度 |
| `improve` | 学习进化、错误记录、模式检测、自动推广 |
| `memory` | 长期记忆、向量搜索、SQLite存储、时间衰减 |
| `llm` | 多模型调用、缓存、Schema验证、模型降级容错 |

### 🖥️ 自动化控制

| 模块 | 功能描述 |
|------|----------|
| `browser` | 浏览器自动化、多页面管理、设备模拟、性能追踪 |
| `desktop` | 桌面自动化、双后端支持、UI自动化、窗口管理 |

### 📡 消息与通信

| 模块 | 功能描述 |
|------|----------|
| `channel` | 消息通道（Telegram/Discord/Slack/WeCom） |
| `channels-enhanced` | 增强消息路由、会话管理、权限控制、消息去重 |
| `session` | 会话管理、消息历史、上下文追踪 |
| `web-gateway` | Web服务器、REST API、远程控制接口 |

### 💾 数据与缓存

| 模块 | 功能描述 |
|------|----------|
| `cache` | 缓存系统、TTL过期、LRU缓存 |
| `cache-utils` | 缓存工具、哈希计算、大小估算、清理机制 |
| `lobster` | 数据管道、流式处理、工作流编排 |
| `state` | 状态管理、持久化存储、键值存储 |

### 🛠️ 工具与系统

| 模块 | 功能描述 |
|------|----------|
| `files` | 文件操作、目录管理、批量处理 |
| `clipboard` | 剪贴板操作、跨平台支持、历史记录 |
| `string-utils` | 字符串规范化、大小写转换、转义处理 |
| `utils-base` | 通用工具、分块处理、并发控制、超时管理 |
| `system-utils` | 系统工具、进程管理、文件锁、端口管理 |
| `security-utils` | 安全工具、路径守卫、输入验证、速率限制 |

### 🌐 网络与抓取

| 模块 | 功能描述 |
|------|----------|
| `link-extraction` | 链接提取、自动抓取、SSRF防护、Markdown格式化 |
| `fetch-enhanced` | HTTP请求、重试机制、超时控制 |

### 📊 数据分析

| 模块 | 功能描述 |
|------|----------|
| `summarize` | 内容摘要、批量处理、关键词提取 |
| `context-engine` | 上下文管理、Token估算、自动压缩 |
| `indicators` | 技术指标计算（MACD、KDJ、RSI、Bollinger Bands、MA、VOL等） |
| `sector-rotation` | 板块轮动分析、主力资金流向、热点板块识别 |
| `sentiment` | 情感分析、自动标注记忆情感倾向（看涨/看跌/中性） |
| `data-aggregator` | 多数据源聚合（PostgreSQL、AKShare、东方财富API） |

### 📈 统一交易系统（新增）

**核心Python模块** (`modules/`)

| 模块 | 文件 | 功能描述 |
|------|------|----------|
| **unified_trading** | `unified_trading.py` | 统一交易系统 - 整合所有数据源、技术分析、信号生成、风险评估 |
| **ml_predictor** | `ml_predictor.py` | ML预测模块 - 模型管理、特征工程、股票预测、多代理分析 |

**unified_trading.py 核心类**:

| 类 | 功能 |
|---|---|
| `DataSourceManager` | 多数据源管理（腾讯API、东财API、新浪新闻） |
| `TechnicalAnalyzer` | 技术指标计算（SMA、EMA、MACD、KDJ、RSI、Bollinger） |
| `SignalGenerator` | 交易信号生成（综合多指标判断） |
| `RiskAnalyzer` | 风险分析（VaR计算、仓位建议） |
| `UnifiedTradingSystem` | 统一接口（完整股票分析） |

**MCP工具**:

| 工具 | 功能 |
|------|------|
| `stock_realtime` | 获取股票实时行情（腾讯API） |
| `stock_kline` | 获取股票历史K线（东财API） |
| `stock_news` | 搜索股票新闻（新浪API） |
| `stock_analyze` | 完整股票分析（行情+指标+信号+风险） |
| `calculate_indicators` | 计算技术指标 |
| `calculate_position` | 计算建议仓位 |

**ml_predictor.py 核心类**:

| 类 | 功能 |
|---|---|
| `ModelManager` | 模型管理（加载、查询） |
| `FeatureEngineer` | 特征工程（50+技术特征） |
| `StockPredictor` | 股票预测器 |
| `MultiAgentSystem` | 多代理系统（信号/风险/情感代理） |

**已训练模型**:

| 模型 | 准确率 | 股票数 | 描述 |
|------|--------|--------|------|
| `mainboard_5pct` | 54.38% | 4079 | 主板5%涨幅预测 |
| `a_stock_10pct` | 54% | 250 | A股10%涨幅预测 |

**使用示例**:

```python
# 测试统一交易系统
cd .iflow/modules
python unified_trading.py

# 测试ML预测模块
python ml_predictor.py
```

### 🔗 集群与技能

| 模块 | 功能描述 |
|------|----------|
| `cluster` | 集群管理、节点发现、远程执行 |
| `skills` | 技能系统、依赖管理、自动安装、元数据 |

### 📈 监控与诊断

| 模块 | 功能描述 |
|------|----------|
| `diagnostic-events` | 诊断事件、模型使用追踪、错误监控 |
| `logging` | 结构化日志、分级日志、敏感信息脱敏 |
| `triage` | 任务分类、优先级排序、统计查询 |

### 🔧 容错与重试

| 模块 | 功能描述 |
|------|----------|
| `selfrepair` | 自我修复、错误恢复、历史记录 |
| `enhanced-retry` | 增强重试、指数退避、抖动机制 |
| `error-handler` | 统一错误处理、错误分类、敏感信息脱敏 |
| `retry-policy` | 重试策略、自适应延迟、错误检测 |

### 📝 文本处理

| 模块 | 功能描述 |
|------|----------|
| `text-chunking` | 文本分块、Markdown支持、Token估算 |
| `rate-limit` | 速率限制、多种算法、装饰器支持 |
| `dedupe-cache` | 去重缓存、持久化去重、TTL过期 |

### 🔐 安全

| 模块 | 功能描述 |
|------|----------|
| `secrets` | 密钥存储、环境变量、密钥引用、脱敏显示 |
| `secret-file` | 密钥文件加载、安全验证、环境变量回退 |
| `http-guard` | HTTP防护、请求体限制、超时控制 |
| `file-security` | 文件安全、符号链接防护、身份验证 |

### 📄 内容处理

| 模块 | 功能描述 |
|------|----------|
| `markdown` | Markdown解析渲染、Frontmatter、表格处理 |
| `media` | 媒体文件处理、MIME类型、元数据提取 |
| `data-validation` | 数据验证、随机数生成、范围检查 |
| `json-files-enhanced` | JSON文件增强、原子写入、并发安全 |

### 🖥️ 系统工具

| 模块 | 功能描述 |
|------|----------|
| `path-resolver` | 路径解析、跨平台、主目录处理 |
| `executable-path` | 可执行文件路径、PATH管理、命令查找 |
| `shell-env` | Shell环境、环境变量管理、命令查找 |
| `os-summary` | 系统摘要、CPU/内存信息、网络接口 |
| `node-commands` | Node.js命令、运行时信息、模块管理 |
| `process-monitor` | 进程监控、进程树、资源监控 |

### ⚙️ 配置管理

| 模块 | 功能描述 |
|------|----------|
| `env-config` | 环境配置、.env加载、验证、脱敏 |
| `runtime-env` | 运行时环境、日志支持、错误处理 |
| `config-eval` | 配置评估、二进制检查、运行时验证 |
| `requirements-eval` | 需求评估、缺失检查、验证报告 |

### 📦 Git 工具

| 模块 | 功能描述 |
|------|----------|
| `git-utils` | Git工具、提交信息、分支管理、状态检查 |
| `git-root-enhanced` | 增强Git根目录查找、HEAD路径解析 |

### 🎨 CLI 格式化

| 模块 | 功能描述 |
|------|----------|
| `cli-format` | CLI格式化、ANSI颜色、表格渲染、进度条 |
| `subagents-format` | 子代理格式化、Token统计、性能显示 |

### 🖥️ 平台兼容

| 模块 | 功能描述 |
|------|----------|
| `wsl` | WSL检测、环境变量检查、异步缓存 |
| `stable-node-path` | 稳定Node路径、Homebrew处理 |
| `machine-name` | 机器名称、主机名、唯一标识 |

### 📚 基础设施

| 模块 | 功能描述 |
|------|----------|
| `archive` | 归档系统、压缩解压、格式检测 |
| `plugin-tools` | 插件工具、异步队列、持久化去重 |
| `runtime-system` | 运行时系统、系统事件、命令队列 |
| `sandbox` | 沙箱环境、隔离执行、安全限制 |

### 🐍 Python 模块

| 模块 | 功能描述 |
|------|----------|
| `browser` | 浏览器自动化 v2.0 - 持久化会话、多页面管理 |
| `desktop` | 桌面控制 v2.0 - 双后端支持（pyautogui/pywinauto） |
| `finance_query` | 金融数据查询（AKShare）、实时行情 |
| `memory_sync` | 本地/远程记忆同步、双重存储 |
| `remote_memory` | 远程记忆API、向量搜索 |
| `realtime_vision` | 实时视觉分析、屏幕识别 |
| `smart_click` | 智能点击定位、目标识别 |
| `stock_*` | 股票分析模块（12个子模块） |

## 📁 项目结构

```
iflow-mcp-server/
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
│   ├── stock_*.py            # 股票分析模块（12个）
│   │
│   └── node/                 # Node.js 模块
│       ├── index.js          # 主入口
│       ├── mcp-server.js     # MCP 服务器
│       ├── package.json      # 依赖配置
│       ├── hybrid/           # 混合模块
│       │   ├── desktop.py    # 桌面控制 (Python)
│       │   ├── server.py     # HTTP 服务器
│       │   └── index.js      # Node.js 入口
│       │
│       └── modules/          # 核心模块（157个）
│           ├── subagent.js
│           ├── agents.js
│           ├── heartbeat.js
│           ├── memory.js
│           ├── llm.js
│           ├── browser.js
│           ├── desktop.js
│           ├── channel.js
│           ├── channels-enhanced.js
│           ├── session.js
│           ├── web-gateway.js
│           ├── cache.js
│           ├── secrets.js
│           └── ...
│
└── .gitignore               # Git 忽略配置
```

## ✨ 核心特性

### 🤖 AI 能力
- **多代理协同**: 自动复杂度评估、并行委派、结果聚合、状态持久化
- **自主运行**: 心跳驱动的技能系统、Cron调度、自主决策
- **学习进化**: 错误记录、模式检测、自动推广、置信度管理
- **向量搜索**: 基于 SQLite 的向量相似度搜索、时间衰减、MMR重排序
- **多模型路由**: 支持 OpenAI、Anthropic、豆包、扣子、模型降级容错
- **密钥管理**: 安全存储、环境变量、密钥引用、脱敏显示、审计日志

### 📡 消息系统
- **消息通道**: Telegram/Discord/Slack/WeCom/Feishu/DingTalk
- **增强路由**: 正则匹配、优先级、消息去重
- **权限控制**: 角色/用户权限、发送策略
- **上下文管理**: Token估算、自动压缩、会话历史、智能选择

### 🖥️ 自动化
- **浏览器持久化**: 保持登录状态、多页面管理、设备模拟、性能追踪
- **桌面双后端**: pyautogui + pywinauto 自动切换、窗口管理、UI自动化
- **剪贴板跨平台**: 复制粘贴、历史记录、文件操作
- **Shell环境管理**: 命令查找、环境变量、执行控制

### 🔒 安全与容错
- **全面安全**: 路径守卫、输入验证、SSRF防护、速率限制、内容安全
- **命令注入防护**: PowerShell/CMD 参数转义、base64 编码
- **错误恢复**: 增强重试、指数退避、自我修复、错误分类
- **性能优化**: 缓存系统、文本分块、速率限制、并发控制、超时管理
- **诊断监控**: 诊断事件、模型使用追踪、结构化日志、敏感信息脱敏

### 🛠️ 开发工具
- **配置管理**: 环境配置、需求评估、运行时验证、密钥管理
- **Git集成**: Git工具、版本控制、提交管理
- **集群管理**: 节点发现、远程执行、资源共享
- **技能系统**: 依赖管理、自动安装、元数据、技能目录

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
AGENTS.md
TOOLS_INDEX.md

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
- ✅ 安全加固：移除敏感文件，清理 Git 历史

### v2.1.0 (2026-03-15)
- ✅ 新增 90+ Node.js 模块
- ✅ 实现混合架构 (Python + Node.js)
- ✅ 添加心跳监控、钩子系统

### v2.0.0 (2026-03-10)
- ✅ 重构为模块化架构
- ✅ 自动模块发现和加载
- ✅ 输出长度限制

## 📄 许可证

MIT License

---

**GitHub**: https://github.com/qgyz9613/iflow-mcp-server

欢迎提交 Issue 和 Pull Request！
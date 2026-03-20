"""
iFlow 股票决策系统 v2.1
整合：数据层 + Agent层 + 回测系统 + 风控系统 + 推送 + 调度

使用方式：
    from stock_system import StockDecisionSystem
    
    system = StockDecisionSystem()
    result = await system.analyze("600519")
    decision = await system.make_decision("600519", capital=100000)
    
    # 定时监控
    scheduler = system.create_scheduler(watch_list=["600519", "000001"])
    await scheduler.start()
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

# 导入各层模块（支持相对导入和绝对导入）
try:
    # 作为包导入时
    from .stock_data_hub import StockDataHub
    from .stock_agents import (
        AgentManager, AgentSignal, SignalType, MarketRegime,
        TechnicalAnalyst, FundamentalsAnalyst, SentimentAnalyst,
        ValuationAnalyst, AIModelAnalyst, MacroAnalyst,
        SignalAggregator, RiskManager as AgentRiskManager
    )
    from .stock_decision import (
        ResearcherBullAgent, ResearcherBearAgent, DebateRoomAgent,
        RegimeDetector, RiskManager, PortfolioManager,
        TradeDecision, RiskMetrics, DebateResult
    )
    from .stock_backtest import (
        Backtester, PerformanceMetrics, BaseStrategy,
        BuyHoldStrategy, MomentumStrategy, MeanReversionStrategy,
        MovingAverageStrategy, RSIStrategy, BollingerStrategy,
        MACDStrategy, AIAgentStrategy, RandomWalkStrategy
    )
except ImportError:
    # 独立运行时
    from stock_data_hub import StockDataHub
    from stock_agents import (
        AgentManager, AgentSignal, SignalType, MarketRegime,
        TechnicalAnalyst, FundamentalsAnalyst, SentimentAnalyst,
        ValuationAnalyst, AIModelAnalyst, MacroAnalyst,
        SignalAggregator, RiskManager as AgentRiskManager
    )
    from stock_decision import (
        ResearcherBullAgent, ResearcherBearAgent, DebateRoomAgent,
        RegimeDetector, RiskManager, PortfolioManager,
        TradeDecision, RiskMetrics, DebateResult
    )
    from stock_backtest import (
        Backtester, PerformanceMetrics, BaseStrategy,
        BuyHoldStrategy, MomentumStrategy, MeanReversionStrategy,
        MovingAverageStrategy, RSIStrategy, BollingerStrategy,
        MACDStrategy, AIAgentStrategy, RandomWalkStrategy
    )

# 可选模块导入
try:
    from stock_notifier import WeChatNotifier, NotifierConfig
    NOTIFIER_AVAILABLE = True
except ImportError:
    NOTIFIER_AVAILABLE = False
    logger.debug("stock_notifier 模块未加载")

try:
    from stock_scheduler import StockScheduler, SchedulerConfig, is_trading_time
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    logger.debug("stock_scheduler 模块未加载")


# ==================== 系统配置 ====================

@dataclass
class SystemConfig:
    """系统配置"""
    # 数据配置
    primary_data_source: str = "MX_Skills"  # 优先数据源
    cache_ttl: int = 300  # 缓存时间(秒)
    
    # Agent权重配置
    agent_weights: Dict[str, float] = field(default_factory=lambda: {
        "technical": 1.2,
        "fundamentals": 1.0,
        "sentiment": 0.8,
        "valuation": 1.1,
        "ai_model": 1.3,
        "macro": 0.9
    })
    
    # 风控配置
    max_position_ratio: float = 0.3  # 单只最大仓位
    max_loss_ratio: float = 0.03  # 最大止损比例
    var_confidence: float = 0.95  # VaR置信度
    
    # 回测配置
    initial_capital: float = 100000.0
    trading_cost: float = 0.001  # 交易成本
    slippage: float = 0.001  # 滑点
    
    def __post_init__(self):
        """参数验证"""
        # 仓位比例必须在0-1之间
        if not 0 < self.max_position_ratio <= 1:
            raise ValueError(f"max_position_ratio必须在(0, 1]范围内，当前值: {self.max_position_ratio}")
        # 止损比例必须在0-1之间
        if not 0 < self.max_loss_ratio < 1:
            raise ValueError(f"max_loss_ratio必须在(0, 1)范围内，当前值: {self.max_loss_ratio}")
        # VaR置信度必须在0-1之间
        if not 0 < self.var_confidence < 1:
            raise ValueError(f"var_confidence必须在(0, 1)范围内，当前值: {self.var_confidence}")
        # 交易成本和滑点必须非负
        if self.trading_cost < 0:
            raise ValueError(f"trading_cost不能为负数，当前值: {self.trading_cost}")
        if self.slippage < 0:
            raise ValueError(f"slippage不能为负数，当前值: {self.slippage}")
        # 初始资金必须为正
        if self.initial_capital <= 0:
            raise ValueError(f"initial_capital必须为正数，当前值: {self.initial_capital}")


# ==================== 分析结果 ====================

@dataclass
class AnalysisResult:
    """股票分析结果"""
    ticker: str
    timestamp: str
    
    # 数据层结果
    realtime_quote: Optional[Dict] = None
    financial_data: Optional[Dict] = None
    historical_data_available: bool = False
    
    # Agent层结果
    agent_signals: Dict[str, AgentSignal] = field(default_factory=dict)
    consolidated_signal: Optional[AgentSignal] = None
    
    # 区制检测结果
    market_regime: Optional[str] = None
    regime_confidence: float = 0.0
    
    # 辩论结果
    bull_thesis: Optional[str] = None
    bear_thesis: Optional[str] = None
    debate_result: Optional[DebateResult] = None
    
    # 风险指标
    risk_metrics: Optional[RiskMetrics] = None
    
    # 最终决策
    final_decision: Optional[TradeDecision] = None
    
    # 汇总
    summary: str = ""


# ==================== 决策仪表盘 ====================

@dataclass
class StockDecision:
    """单只股票决策结果"""
    ticker: str
    name: str = ""
    action: str = "hold"  # "buy", "hold", "sell"
    score: float = 0.0  # 综合评分 0-100
    confidence: float = 0.0
    price: float = 0.0
    change_pct: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size: float = 0.0
    reasoning: str = ""
    risk_level: str = "medium"  # "low", "medium", "high"
    signal_type: str = "neutral"  # "bullish", "bearish", "neutral"
    
    # 技术指标摘要
    ma_trend: str = "neutral"  # "up", "down", "neutral"
    volume_status: str = "normal"  # "high", "low", "normal"
    rsi_value: float = 50.0
    macd_signal: str = "neutral"


@dataclass
class DashboardReport:
    """决策仪表盘报告"""
    date: str
    total_stocks: int
    buy_count: int
    hold_count: int
    sell_count: int
    stocks: List[StockDecision] = field(default_factory=list)
    market_summary: str = ""  # 大盘概览
    sector_performance: List[Dict] = field(default_factory=list)  # 板块表现
    north_fund: Dict = field(default_factory=dict)  # 北向资金
    sentiment_summary: str = ""  # 舆情情绪
    risk_alerts: List[str] = field(default_factory=list)  # 风险警报
    positive_catalysts: List[str] = field(default_factory=list)  # 利好催化
    
    def to_display(self) -> str:
        """生成仪表盘显示文本"""
        lines = [
            f"🎯 {self.date} 决策仪表盘",
            f"共分析{self.total_stocks}只股票 | 🟢买入:{self.buy_count} 🟡观望:{self.hold_count} 🔴卖出:{self.sell_count}",
            "",
            "📊 分析结果摘要",
        ]
        
        # 按评分排序
        sorted_stocks = sorted(self.stocks, key=lambda x: x.score, reverse=True)
        
        for stock in sorted_stocks:
            emoji = "🟢" if stock.action == "buy" else ("🔴" if stock.action == "sell" else "🟡")
            action_cn = {"buy": "买入", "hold": "观望", "sell": "卖出"}.get(stock.action, "观望")
            signal_cn = {"bullish": "看多", "bearish": "看空", "neutral": "震荡"}.get(stock.signal_type, "震荡")
            
            lines.append(
                f"{emoji} {stock.name}({stock.ticker}): {action_cn} | 评分 {stock.score:.0f} | {signal_cn}"
            )
            
            if stock.action == "buy":
                lines.append(f"   💰 建议仓位: ¥{stock.position_size:.0f} | 止损: ¥{stock.stop_loss:.2f} | 止盈: ¥{stock.take_profit:.2f}")
        
        # 大盘概览
        if self.market_summary:
            lines.extend(["", "📈 大盘概览", self.market_summary])
        
        # 板块表现
        if self.sector_performance:
            lines.extend(["", "🏭 板块表现"])
            for sector in self.sector_performance[:5]:
                change_emoji = "📈" if sector.get("change", 0) > 0 else "📉"
                lines.append(f"  {change_emoji} {sector.get('name', 'N/A')}: {sector.get('change', 0):+.2f}%")
        
        # 北向资金
        if self.north_fund:
            lines.extend(["", "💰 北向资金"])
            net_inflow = self.north_fund.get("net_inflow", 0)
            trend = "流入" if net_inflow > 0 else "流出"
            lines.append(f"  今日净{trend}: {abs(net_inflow):.2f}亿")
        
        # 重要信息
        lines.extend(["", "📰 重要信息速览"])
        
        if self.sentiment_summary:
            lines.append(f"💭 舆情情绪: {self.sentiment_summary}")
        
        if self.risk_alerts:
            lines.append("🚨 风险警报:")
            for alert in self.risk_alerts[:3]:
                lines.append(f"   ⚠️ {alert}")
        
        if self.positive_catalysts:
            lines.append("✨ 利好催化:")
            for catalyst in self.positive_catalysts[:3]:
                lines.append(f"   ✅ {catalyst}")
        
        return "\n".join(lines)


# ==================== 主系统类 ====================

class StockDecisionSystem:
    """
    股票决策系统主类
    
    整合四个层次：
    1. 数据层 - 统一数据接口
    2. Agent层 - 12个专业Agent分析
    3. 决策层 - 辩论+风险管理
    4. 回测层 - 策略验证
    """
    
    def __init__(self, config: Optional[SystemConfig] = None):
        self.config = config or SystemConfig()
        
        # 初始化各层组件
        self.data_hub = StockDataHub()
        self.agent_manager = AgentManager()
        self.regime_detector = RegimeDetector()
        self.risk_manager = RiskManager()
        self.portfolio_manager = PortfolioManager()
        
        # 辩论Agent
        self.bull_researcher = ResearcherBullAgent()
        self.bear_researcher = ResearcherBearAgent()
        self.debate_room = DebateRoomAgent()
        
        # 回测器
        self.backtester = Backtester(
            initial_capital=self.config.initial_capital
        )
        
        # 状态
        self._initialized = False
    
    async def initialize(self):
        """初始化系统"""
        if self._initialized:
            return
        
        # 注册Agent
        agents = [
            TechnicalAnalyst(weight=self.config.agent_weights.get("technical", 1.0)),
            FundamentalsAnalyst(weight=self.config.agent_weights.get("fundamentals", 1.0)),
            SentimentAnalyst(weight=self.config.agent_weights.get("sentiment", 0.8)),
            ValuationAnalyst(weight=self.config.agent_weights.get("valuation", 1.0)),
            AIModelAnalyst(weight=self.config.agent_weights.get("ai_model", 1.3)),
            MacroAnalyst(weight=self.config.agent_weights.get("macro", 0.9)),
        ]
        
        for agent in agents:
            self.agent_manager.register_agent(agent)
        
        self._initialized = True
        print("[StockSystem] 初始化完成")
    
    async def analyze(self, ticker: str) -> AnalysisResult:
        """
        完整分析单只股票
        
        Args:
            ticker: 股票代码 (如 "600519")
            
        Returns:
            AnalysisResult: 完整分析结果
        """
        await self.initialize()
        
        result = AnalysisResult(
            ticker=ticker,
            timestamp=datetime.now().isoformat()
        )
        
        print(f"[StockSystem] 开始分析 {ticker}")
        
        # ===== 第一层：数据收集 =====
        print(f"  [1/6] 数据收集...")
        
        # 实时行情
        quote = await self.data_hub.get_realtime_quote([ticker])
        result.realtime_quote = quote.get(ticker) if quote else None
        
        # 财务数据
        result.financial_data = await self.data_hub.get_financial_data(f"{ticker}基本面")
        
        # 历史数据（用于技术分析）- 初始化为None防止未定义错误
        historical = None
        try:
            historical = await self.data_hub.get_historical_data(ticker, days=365)
        except Exception as e:
            logger.warning(f"获取历史数据失败: {e}")
        result.historical_data_available = historical is not None and len(historical) > 0
        
        # ===== 第二层：Agent分析 =====
        print(f"  [2/6] Agent分析...")
        
        data = {
            "ticker": ticker,
            "quote": result.realtime_quote,
            "financial": result.financial_data,
            "historical": historical
        }
        
        result.agent_signals = await self.agent_manager.run_parallel(data)
        
        # 综合信号
        result.consolidated_signal = self.agent_manager.aggregate_signals(
            result.agent_signals,
            self.config.agent_weights
        )
        
        # ===== 第三层：区制检测 =====
        print(f"  [3/6] 区制检测...")
        
        if historical is not None and len(historical) > 60:
            regime_info = self.regime_detector.detect(historical)
            # 检查regime_info是否为None，避免NoneType错误
            if regime_info is not None:
                result.market_regime = regime_info.get("regime_name", "unknown")
                result.regime_confidence = regime_info.get("confidence", 0.0)
            else:
                result.market_regime = "unknown"
                result.regime_confidence = 0.0
                logger.warning(f"区制检测返回None，股票: {ticker}")
        
        # ===== 第四层：辩论 =====
        print(f"  [4/6] 多空辩论...")
        
        # 多头观点
        bull_result = self.bull_researcher.analyze(
            result.agent_signals,
            result.realtime_quote,
            result.financial_data
        )
        result.bull_thesis = bull_result.thesis if hasattr(bull_result, 'thesis') else str(bull_result)
        
        # 空头观点
        bear_result = self.bear_researcher.analyze(
            result.agent_signals,
            result.realtime_quote,
            result.financial_data
        )
        result.bear_thesis = bear_result.thesis if hasattr(bear_result, 'thesis') else str(bear_result)
        
        # 辩论综合
        signals_dict = {
            name: {"signal": sig.signal.value if hasattr(sig.signal, 'value') else str(sig.signal),
                   "confidence": sig.confidence}
            for name, sig in result.agent_signals.items()
        }
        
        result.debate_result = self.debate_room.conduct_debate(
            bull_result.__dict__ if hasattr(bull_result, '__dict__') else {},
            bear_result.__dict__ if hasattr(bear_result, '__dict__') else {},
            signals_dict,
            {"regime_name": result.market_regime, "confidence": result.regime_confidence}
        )
        
        # ===== 第五层：风险管理 =====
        print(f"  [5/6] 风险评估...")
        
        if historical is not None and len(historical) > 20:
            returns = historical['close'].pct_change().dropna().values
            result.risk_metrics = self.risk_manager.calculate_metrics(
                returns,
                confidence=self.config.var_confidence
            )
        
        # ===== 第六层：最终决策 =====
        print(f"  [6/6] 生成决策...")
        
        decision_signal = self._map_signal_to_decision(
            result.consolidated_signal.signal if result.consolidated_signal else "neutral"
        )
        
        result.final_decision = TradeDecision(
            action=decision_signal,
            confidence=result.consolidated_signal.confidence if result.consolidated_signal else 0.5,
            position_size=self._calculate_position(result),
            stop_loss=self._calculate_stop_loss(result),
            take_profit=self._calculate_take_profit(result),
            reasoning=self._generate_reasoning(result)
        )
        
        # 生成汇总
        result.summary = self._generate_summary(result)
        
        print(f"[StockSystem] 分析完成: {result.final_decision.action}")
        return result
    
    async def make_decision(self, ticker: str, capital: float = 100000) -> TradeDecision:
        """
        快速决策（简化版）
        
        Args:
            ticker: 股票代码
            capital: 可用资金
            
        Returns:
            TradeDecision: 交易决策
        """
        result = await self.analyze(ticker)
        
        if result.final_decision:
            # 根据资金调整仓位
            result.final_decision.position_size = min(
                result.final_decision.position_size,
                capital * self.config.max_position_ratio
            )
        
        return result.final_decision
    
    async def backtest(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        strategies: Optional[List[str]] = None
    ) -> Dict:
        """
        回测分析
        
        Args:
            ticker: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            strategies: 策略列表，None则使用全部
            
        Returns:
            回测结果
        """
        await self.initialize()
        
        # 获取历史数据
        data = await self.data_hub.get_historical_data(
            ticker,
            start=start_date,
            end=end_date
        )
        
        if data is None or len(data) == 0:
            return {"error": "无法获取历史数据"}
        
        # 选择策略
        strategy_map = {
            "buy_hold": BuyHoldStrategy(),
            "momentum": MomentumStrategy(),
            "mean_reversion": MeanReversionStrategy(),
            "ma": MovingAverageStrategy(),
            "rsi": RSIStrategy(),
            "bollinger": BollingerStrategy(),
            "macd": MACDStrategy(),
            "random": RandomWalkStrategy(),
            "ai": AIAgentStrategy()
        }
        
        if strategies:
            selected = {k: v for k, v in strategy_map.items() if k in strategies}
        else:
            selected = strategy_map
        
        # 运行对比
        results = self.backtester.compare_strategies(data, list(selected.values()))
        
        return results
    
    def _map_signal_to_decision(self, signal: str) -> str:
        """映射信号到决策动作"""
        mapping = {
            "bullish": "buy",
            "strong_bullish": "strong_buy",
            "bearish": "sell",
            "strong_bearish": "strong_sell",
            "neutral": "hold"
        }
        return mapping.get(signal.lower(), "hold")
    
    def _calculate_position(self, result: AnalysisResult) -> float:
        """计算建议仓位"""
        base_position = 10000  # 基础仓位
        
        # 根据信号强度调整
        if result.consolidated_signal:
            confidence = result.consolidated_signal.confidence
            base_position *= confidence
        
        # 根据区制调整
        if result.market_regime == "crisis":
            base_position *= 0.3  # 危机区制减仓
        elif result.market_regime == "high_volatility_mean_reverting":
            base_position *= 0.5  # 高波动区制保守
        
        # 根据风险指标调整
        if result.risk_metrics:
            if result.risk_metrics.var_95 and result.risk_metrics.var_95 < -0.05:
                base_position *= 0.5  # 高风险减仓
        
        return min(base_position, self.config.initial_capital * self.config.max_position_ratio)
    
    def _calculate_stop_loss(self, result: AnalysisResult) -> float:
        """计算止损价"""
        if result.realtime_quote:
            price = result.realtime_quote.get("price", 0)
            return price * (1 - self.config.max_loss_ratio)
        return 0.0
    
    def _calculate_take_profit(self, result: AnalysisResult) -> float:
        """计算止盈价"""
        if result.realtime_quote:
            price = result.realtime_quote.get("price", 0)
            confidence = result.consolidated_signal.confidence if result.consolidated_signal else 0.5
            profit_ratio = 0.03 + confidence * 0.07  # 3%-10%止盈
            return price * (1 + profit_ratio)
        return 0.0
    
    def _generate_reasoning(self, result: AnalysisResult) -> str:
        """生成决策理由"""
        reasons = []
        
        if result.consolidated_signal:
            reasons.append(f"综合信号: {result.consolidated_signal.signal.value}")
            reasons.append(f"置信度: {result.consolidated_signal.confidence:.1%}")
        
        if result.market_regime:
            reasons.append(f"市场状态: {result.market_regime}")
        
        if result.risk_metrics:
            reasons.append(f"风险评分: {result.risk_metrics.risk_score:.1f}")
        
        if result.bull_thesis and len(result.bull_thesis) > 10:
            reasons.append(f"多头观点: {result.bull_thesis[:50]}...")
        
        return " | ".join(reasons)
    
    def _generate_summary(self, result: AnalysisResult) -> str:
        """生成分析摘要"""
        lines = [
            f"【{result.ticker} 分析报告】",
            f"时间: {result.timestamp}",
            "",
            f"▶ 决策: {result.final_decision.action if result.final_decision else 'N/A'}",
            f"▶ 置信度: {result.final_decision.confidence:.1%}" if result.final_decision else "",
            f"▶ 建议仓位: ¥{result.final_decision.position_size:.0f}" if result.final_decision else "",
            f"▶ 止损价: ¥{result.final_decision.stop_loss:.2f}" if result.final_decision else "",
            f"▶ 止盈价: ¥{result.final_decision.take_profit:.2f}" if result.final_decision else "",
            "",
            f"▶ 市场状态: {result.market_regime or '未知'}",
            f"▶ 区制置信: {result.regime_confidence:.1%}",
            "",
            "【Agent信号】",
        ]
        
        for name, signal in result.agent_signals.items():
            signal_str = signal.signal.value if hasattr(signal.signal, 'value') else str(signal.signal)
            lines.append(f"  - {name}: {signal_str} ({signal.confidence:.0%})")
        
        return "\n".join(lines)
    
    # ==================== 决策仪表盘功能 ====================
    
    async def generate_dashboard(self, stock_list: List[str]) -> DashboardReport:
        """
        生成决策仪表盘
        
        输出格式：
        🎯 2026-03-20 决策仪表盘
        共分析N只股票 | 🟢买入:X 🟡观望:Y 🔴卖出:Z
        
        📊 分析结果摘要
        🟢 茅台(600519): 买入 | 评分 75 | 看多
        🟡 平安(000001): 观望 | 评分 55 | 震荡
        🔴 ...
        
        📰 重要信息速览
        💭 舆情情绪: ...
        🚨 风险警报: ...
        ✨ 利好催化: ...
        
        Args:
            stock_list: 股票代码列表
            
        Returns:
            DashboardReport: 仪表盘报告
        """
        await self.initialize()
        
        date_str = datetime.now().strftime("%Y-%m-%d")
        decisions: List[StockDecision] = []
        buy_count = 0
        hold_count = 0
        sell_count = 0
        
        print(f"[StockSystem] 生成决策仪表盘，共{len(stock_list)}只股票")
        
        # 并行分析所有股票
        tasks = [self._quick_analyze_for_dashboard(ticker) for ticker in stock_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"  [WARN] {stock_list[i]} 分析失败: {result}")
                continue
            
            if result:
                decisions.append(result)
                if result.action == "buy":
                    buy_count += 1
                elif result.action == "sell":
                    sell_count += 1
                else:
                    hold_count += 1
        
        # 获取市场概览
        market_summary = await self._get_market_summary()
        sector_performance = await self._get_sector_performance()
        north_fund = await self._get_north_fund()
        sentiment_summary = await self._get_sentiment_summary(stock_list)
        
        # 风险警报和利好催化
        risk_alerts = self._extract_risk_alerts(decisions)
        positive_catalysts = self._extract_positive_catalysts(decisions)
        
        report = DashboardReport(
            date=date_str,
            total_stocks=len(decisions),
            buy_count=buy_count,
            hold_count=hold_count,
            sell_count=sell_count,
            stocks=decisions,
            market_summary=market_summary,
            sector_performance=sector_performance,
            north_fund=north_fund,
            sentiment_summary=sentiment_summary,
            risk_alerts=risk_alerts,
            positive_catalysts=positive_catalysts
        )
        
        return report
    
    async def _quick_analyze_for_dashboard(self, ticker: str) -> Optional[StockDecision]:
        """快速分析单只股票，用于仪表盘"""
        try:
            # 获取实时行情
            quote = await self.data_hub.get_realtime_quote([ticker])
            quote_data = quote.get(ticker, {}) if quote else {}
            
            # 获取历史数据
            historical = await self.data_hub.get_historical_data(ticker, days=60)
            
            if not quote_data:
                return None
            
            price = quote_data.get("price", 0)
            name = quote_data.get("name", ticker)
            change_pct = quote_data.get("change_pct", 0)
            
            # 简化的技术分析
            ma_trend = "neutral"
            volume_status = "normal"
            rsi_value = 50.0
            macd_signal = "neutral"
            
            if historical is not None and len(historical) > 20:
                # MA趋势
                ma5 = historical['close'].rolling(5).mean().iloc[-1]
                ma10 = historical['close'].rolling(10).mean().iloc[-1]
                ma20 = historical['close'].rolling(20).mean().iloc[-1]
                
                if ma5 > ma10 > ma20:
                    ma_trend = "up"
                elif ma5 < ma10 < ma20:
                    ma_trend = "down"
                
                # RSI简化计算
                delta = historical['close'].diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                # 修复：使用where方法正确处理除零，避免replace方法错误
                rs = gain / loss.where(loss != 0, 1e-10)
                rsi_value = (100 - (100 / (1 + rs.iloc[-1]))) if not rs.empty else 50
                
                # MACD简化
                ema12 = historical['close'].ewm(span=12).mean()
                ema26 = historical['close'].ewm(span=26).mean()
                dif = ema12 - ema26
                dea = dif.ewm(span=9).mean()
                macd_signal = "bullish" if dif.iloc[-1] > dea.iloc[-1] else "bearish"
                
                # 成交量状态
                vol_ma = historical['volume'].rolling(20).mean().iloc[-1]
                vol_today = historical['volume'].iloc[-1]
                if vol_today > vol_ma * 1.5:
                    volume_status = "high"
                elif vol_today < vol_ma * 0.5:
                    volume_status = "low"
            
            # 计算评分 (0-100)
            score = self._calculate_score(ma_trend, volume_status, rsi_value, macd_signal, change_pct)
            
            # 决策
            if score >= 65:
                action = "buy"
                signal_type = "bullish"
            elif score <= 35:
                action = "sell"
                signal_type = "bearish"
            else:
                action = "hold"
                signal_type = "neutral"
            
            # 止损止盈
            stop_loss = price * 0.97 if action == "buy" else 0
            take_profit = price * 1.08 if action == "buy" else 0
            
            # 风险等级
            if rsi_value > 80 or change_pct > 9:
                risk_level = "high"
            elif rsi_value < 20 or change_pct < -9:
                risk_level = "high"
            else:
                risk_level = "low" if abs(change_pct) < 3 else "medium"
            
            return StockDecision(
                ticker=ticker,
                name=name,
                action=action,
                score=score,
                confidence=min(score / 100, 0.95),
                price=price,
                change_pct=change_pct,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size=self.config.initial_capital * self.config.max_position_ratio,
                reasoning=self._generate_quick_reasoning(ma_trend, volume_status, rsi_value, macd_signal),
                risk_level=risk_level,
                signal_type=signal_type,
                ma_trend=ma_trend,
                volume_status=volume_status,
                rsi_value=rsi_value,
                macd_signal=macd_signal
            )
            
        except Exception as e:
            logger.error(f"分析 {ticker} 失败: {e}")
            return None
    
    def _calculate_score(self, ma_trend: str, volume_status: str, rsi: float, 
                         macd_signal: str, change_pct: float) -> float:
        """
        计算综合评分
        
        评分逻辑：
        - 基础分50分，根据技术指标加减分
        - 评分范围0-100
        - 65分以上建议买入，35分以下建议卖出
        
        Args:
            ma_trend: 均线趋势 ("up", "down", "neutral")
            volume_status: 成交量状态 ("high", "low", "normal")
            rsi: RSI值 (0-100)
            macd_signal: MACD信号 ("bullish", "bearish", "neutral")
            change_pct: 涨跌幅百分比
        """
        score = 50.0  # 基础分
        
        # MA趋势权重 25%
        if ma_trend == "up":
            score += 12.5  # 均线多头排列，加分
        elif ma_trend == "down":
            score -= 12.5  # 均线空头排列，减分
        
        # MACD权重 20%
        if macd_signal == "bullish":
            score += 10  # MACD金叉，加分
        elif macd_signal == "bearish":
            score -= 10  # MACD死叉，减分
        
        # RSI权重 20%
        if 40 <= rsi <= 60:
            score += 5  # RSI中性区间，稳健
        elif 30 <= rsi < 40:
            score += 3  # RSI偏低，有上涨空间
        elif 60 < rsi <= 70:
            score += 2  # RSI偏高但未超买
        elif rsi < 30:
            score += 5  # RSI超卖，反弹机会
        elif rsi > 80:
            score -= 10  # RSI严重超买，风险大
        elif rsi > 70:
            score -= 5  # RSI超买，注意风险
        
        # 成交量权重 15%
        if volume_status == "high" and ma_trend == "up":
            score += 7.5  # 放量上涨，强势信号
        elif volume_status == "high" and ma_trend == "down":
            score -= 7.5  # 放量下跌，恐慌抛售
        elif volume_status == "low":
            score -= 2  # 缩量，观望情绪
        
        # 涨跌幅权重 20% - 修复逻辑矛盾
        if 0 < change_pct <= 3:
            score += 5  # 温和上涨，稳健
        elif 3 < change_pct <= 5:
            score += 7.5  # 中等上涨，强势
        elif 5 < change_pct <= 7:
            score += 5  # 大涨，强势但注意追高风险
        elif change_pct > 7:
            score += 2  # 暴涨，强势但风险较高，谨慎
        elif -3 <= change_pct < 0:
            score -= 5  # 温和下跌，弱势
        elif -5 <= change_pct < -3:
            score -= 7.5  # 中等下跌，明显弱势
        elif -7 <= change_pct < -5:
            score -= 5  # 大跌，可能有反弹机会
        elif change_pct < -7:
            score -= 3  # 暴跌，超跌反弹机会，但仍需谨慎
        
        return max(0, min(100, score))
    
    def _generate_quick_reasoning(self, ma_trend: str, volume_status: str, 
                                   rsi: float, macd_signal: str) -> str:
        """生成快速理由"""
        reasons = []
        
        if ma_trend == "up":
            reasons.append("均线多头排列")
        elif ma_trend == "down":
            reasons.append("均线空头排列")
        
        if volume_status == "high":
            reasons.append("放量")
        elif volume_status == "low":
            reasons.append("缩量")
        
        if rsi > 70:
            reasons.append("RSI超买")
        elif rsi < 30:
            reasons.append("RSI超卖")
        
        if macd_signal == "bullish":
            reasons.append("MACD金叉")
        elif macd_signal == "bearish":
            reasons.append("MACD死叉")
        
        return " | ".join(reasons) if reasons else "信号中性"
    
    async def _get_market_summary(self) -> str:
        """获取大盘概览"""
        try:
            # 获取上证指数
            sh_quote = await self.data_hub.get_realtime_quote(["000001"])
            if sh_quote and "000001" in sh_quote:
                data = sh_quote["000001"]
                change = data.get("change_pct", 0)
                trend = "上涨" if change > 0 else ("下跌" if change < 0 else "平盘")
                return f"上证指数{trend}{abs(change):.2f}%"
        except:
            pass
        return "大盘数据获取失败"
    
    async def _get_sector_performance(self) -> List[Dict]:
        """获取板块表现"""
        # 简化实现，返回空列表
        return []
    
    async def _get_north_fund(self) -> Dict:
        """获取北向资金"""
        # 简化实现
        return {}
    
    async def _get_sentiment_summary(self, stock_list: List[str]) -> str:
        """获取舆情摘要"""
        # 计算整体情绪
        buy_signals = 0
        total = len(stock_list)
        
        # 简化：基于涨跌幅判断
        try:
            quotes = await self.data_hub.get_realtime_quote(stock_list[:10])
            if quotes:
                for ticker, data in quotes.items():
                    if data.get("change_pct", 0) > 0:
                        buy_signals += 1
                
                ratio = buy_signals / len(quotes) if quotes else 0.5
                if ratio > 0.6:
                    return "偏乐观"
                elif ratio < 0.4:
                    return "偏谨慎"
                else:
                    return "中性"
        except:
            pass
        return "中性"
    
    def _extract_risk_alerts(self, decisions: List[StockDecision]) -> List[str]:
        """提取风险警报"""
        alerts = []
        for d in decisions:
            if d.risk_level == "high":
                alerts.append(f"{d.name}({d.ticker}) 风险较高")
            if d.rsi_value > 80:
                alerts.append(f"{d.name} RSI超买({d.rsi_value:.0f})")
            if d.change_pct < -8:
                alerts.append(f"{d.name} 大跌{d.change_pct:.1f}%")
        return alerts[:5]
    
    def _extract_positive_catalysts(self, decisions: List[StockDecision]) -> List[str]:
        """提取利好催化"""
        catalysts = []
        for d in decisions:
            if d.action == "buy" and d.score >= 70:
                catalysts.append(f"{d.name}({d.ticker}) 评分{d.score:.0f}，建议买入")
            if d.ma_trend == "up" and d.volume_status == "high":
                catalysts.append(f"{d.name} 放量突破均线")
            if d.macd_signal == "bullish" and d.rsi_value < 70:
                catalysts.append(f"{d.name} MACD金叉且未超买")
        return catalysts[:5]
    
    def generate_checklist(self, decision: StockDecision) -> Dict[str, str]:
        """
        生成操作检查清单
        
        返回：
        {
            "趋势": "满足",  # MA5 > MA10 > MA20
            "量能": "注意",  # 成交量是否放大
            "乖离率": "满足",  # < 5%
            "止损设置": "满足",  # 已设置止损价
            ...
        }
        
        Args:
            decision: 股票决策结果
            
        Returns:
            Dict[str, str]: 检查清单
        """
        checklist = {}
        
        # 1. 趋势检查
        if decision.ma_trend == "up":
            checklist["趋势"] = "满足"
        elif decision.ma_trend == "down":
            checklist["趋势"] = "不满足"
        else:
            checklist["趋势"] = "中性"
        
        # 2. 量能检查
        if decision.volume_status == "high":
            checklist["量能"] = "满足"
        elif decision.volume_status == "low":
            checklist["量能"] = "注意"
        else:
            checklist["量能"] = "中性"
        
        # 3. 乖离率检查 (简化：基于涨跌幅)
        if abs(decision.change_pct) < 3:
            checklist["乖离率"] = "满足"
        elif abs(decision.change_pct) < 5:
            checklist["乖离率"] = "注意"
        else:
            checklist["乖离率"] = "不满足"
        
        # 4. 止损设置
        if decision.stop_loss > 0:
            checklist["止损设置"] = "满足"
        else:
            checklist["止损设置"] = "未设置"
        
        # 5. 止盈设置
        if decision.take_profit > 0:
            checklist["止盈设置"] = "满足"
        else:
            checklist["止盈设置"] = "未设置"
        
        # 6. RSI检查
        if 30 <= decision.rsi_value <= 70:
            checklist["RSI状态"] = "满足"
        elif decision.rsi_value < 30:
            checklist["RSI状态"] = "超卖(机会)"
        else:
            checklist["RSI状态"] = "超买(风险)"
        
        # 7. MACD检查
        if decision.macd_signal == "bullish":
            checklist["MACD信号"] = "满足"
        elif decision.macd_signal == "bearish":
            checklist["MACD信号"] = "不满足"
        else:
            checklist["MACD信号"] = "中性"
        
        # 8. 风险等级
        if decision.risk_level == "low":
            checklist["风险等级"] = "满足"
        elif decision.risk_level == "medium":
            checklist["风险等级"] = "注意"
        else:
            checklist["风险等级"] = "高风险"
        
        # 9. 评分检查
        if decision.score >= 65:
            checklist["综合评分"] = "满足"
        elif decision.score >= 35:
            checklist["综合评分"] = "中性"
        else:
            checklist["综合评分"] = "不满足"
        
        # 10. 仓位控制
        if decision.position_size > 0:
            max_pos = self.config.initial_capital * self.config.max_position_ratio
            if decision.position_size <= max_pos:
                checklist["仓位控制"] = "满足"
            else:
                checklist["仓位控制"] = "超限"
        else:
            checklist["仓位控制"] = "未设置"
        
        return checklist
    
    def format_checklist_display(self, decision: StockDecision) -> str:
        """格式化检查清单显示"""
        checklist = self.generate_checklist(decision)
        
        lines = [
            f"📋 {decision.name}({decision.ticker}) 操作检查清单",
            f"决策: {decision.action.upper()} | 评分: {decision.score:.0f}",
            "",
        ]
        
        for item, status in checklist.items():
            if status == "满足":
                emoji = "✅"
            elif status in ["注意", "中性", "超卖(机会)", "未设置"]:
                emoji = "⚠️"
            else:
                emoji = "❌"
            lines.append(f"  {emoji} {item}: {status}")
        
        # 汇总
        satisfied = sum(1 for s in checklist.values() if s == "满足")
        total = len(checklist)
        lines.append("")
        lines.append(f"📊 满足项: {satisfied}/{total}")
        
        if decision.action == "buy":
            if satisfied >= 7:
                lines.append("✨ 建议: 条件充分，可执行买入")
            elif satisfied >= 5:
                lines.append("⚠️ 建议: 条件一般，谨慎操作")
            else:
                lines.append("🚨 建议: 条件不足，暂缓操作")
        
        return "\n".join(lines)


# ==================== 便捷函数 ====================

async def quick_analyze(ticker: str) -> str:
    """快速分析（返回摘要文本）"""
    system = StockDecisionSystem()
    result = await system.analyze(ticker)
    return result.summary


async def quick_decision(ticker: str, capital: float = 10000) -> Dict:
    """快速决策（返回决策字典）"""
    system = StockDecisionSystem()
    decision = await system.make_decision(ticker, capital)
    
    if decision:
        return {
            "action": decision.action,
            "confidence": decision.confidence,
            "position_size": decision.position_size,
            "stop_loss": decision.stop_loss,
            "take_profit": decision.take_profit,
            "reasoning": decision.reasoning
        }
    return {"error": "无法生成决策"}


# ==================== 模块导出 ====================

__all__ = [
    "StockDecisionSystem",
    "SystemConfig",
    "AnalysisResult",
    "quick_analyze",
    "quick_decision",
    
    # 决策仪表盘
    "StockDecision",
    "DashboardReport",
    
    # 数据层
    "StockDataHub",
    
    # Agent层
    "AgentManager",
    "AgentSignal",
    "SignalType",
    
    # 决策层
    "TradeDecision",
    "RiskMetrics",
    "DebateResult",
    
    # 回测层
    "Backtester",
    "PerformanceMetrics",
]

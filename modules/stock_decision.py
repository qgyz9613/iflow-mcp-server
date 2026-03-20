"""
股票决策系统 - 辩论和决策机制
实现多头空头辩论、区制检测、风险管理和组合决策
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import logging

# 配置日志
logger = logging.getLogger(__name__)


# ==================== 数据结构定义 ====================

class SignalStrength(Enum):
    """信号强度枚举"""
    STRONG_BUY = 5
    BUY = 4
    NEUTRAL = 3
    SELL = 2
    STRONG_SELL = 1


class MarketRegime(Enum):
    """市场区制枚举"""
    LOW_VOLATILITY_TRENDING = "low_volatility_trending"
    HIGH_VOLATILITY_MEAN_REVERTING = "high_volatility_mean_reverting"
    CRISIS_REGIME = "crisis_regime"
    TRANSITION = "transition"


@dataclass
class ResearchSignal:
    """研究报告信号"""
    agent_name: str
    signal_type: str  # "bull" or "bear"
    strength: float  # -1 to 1
    confidence: float  # 0 to 1
    reasons: List[str]
    supporting_data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DebateResult:
    """辩论结果"""
    bull_score: float
    bear_score: float
    consensus: float  # -1 to 1, positive = bull, negative = bear
    key_arguments: Dict[str, List[str]]  # {"bull": [...], "bear": [...]}
    uncertainty: float
    regime_context: MarketRegime


@dataclass
class RiskMetrics:
    """风险指标"""
    var_95: float  # 95% VaR
    var_99: float  # 99% VaR
    cvar_95: float  # 95% CVaR (条件风险价值)
    max_drawdown: float
    volatility: float
    sharpe_ratio: float
    kelly_fraction: float
    recommended_position: float  # 建议仓位比例


@dataclass
class TradeDecision:
    """交易决策"""
    action: str  # "buy", "sell", "hold"
    position_size: float  # 仓位大小比例
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: float = 0.0
    reasoning: str = ""
    risk_metrics: Optional[RiskMetrics] = None
    debate_result: Optional[DebateResult] = None
    timestamp: datetime = field(default_factory=datetime.now)


# ==================== 研究员Agent ====================

class ResearcherBullAgent:
    """多头观点研究员 - 负责挖掘看涨理由"""
    
    def __init__(self, name: str = "BullResearcher"):
        self.name = name
        self.signal_type = "bull"
        
    def analyze(self, market_data: Dict[str, Any], technical_indicators: Dict[str, Any],
                fundamental_data: Dict[str, Any] = None) -> ResearchSignal:
        """
        多头分析 - 寻找看涨信号
        
        Args:
            market_data: 市场数据 (price, volume, etc.)
            technical_indicators: 技术指标 (MA, MACD, RSI, etc.)
            fundamental_data: 基本面数据 (可选)
        
        Returns:
            ResearchSignal: 多头研究报告
        """
        reasons = []
        supporting_data = {}
        strength_scores = []
        
        # 1. 技术面分析
        tech_signals = self._analyze_technical(technical_indicators)
        reasons.extend(tech_signals["reasons"])
        strength_scores.append(tech_signals["strength"])
        supporting_data["technical"] = tech_signals
        
        # 2. 资金面分析
        flow_signals = self._analyze_capital_flow(market_data)
        reasons.extend(flow_signals["reasons"])
        strength_scores.append(flow_signals["strength"])
        supporting_data["capital_flow"] = flow_signals
        
        # 3. 趋势分析
        trend_signals = self._analyze_trend(market_data, technical_indicators)
        reasons.extend(trend_signals["reasons"])
        strength_scores.append(trend_signals["strength"])
        supporting_data["trend"] = trend_signals
        
        # 4. 基本面分析 (如果有)
        if fundamental_data:
            fund_signals = self._analyze_fundamental(fundamental_data)
            reasons.extend(fund_signals["reasons"])
            strength_scores.append(fund_signals["strength"])
            supporting_data["fundamental"] = fund_signals
        
        # 综合评分
        avg_strength = np.mean(strength_scores) if strength_scores else 0.0
        confidence = self._calculate_confidence(reasons, strength_scores)
        
        return ResearchSignal(
            agent_name=self.name,
            signal_type=self.signal_type,
            strength=min(1.0, max(0.0, avg_strength)),  # 0 to 1 for bull
            confidence=confidence,
            reasons=reasons,
            supporting_data=supporting_data
        )
    
    def _analyze_technical(self, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """技术面多头信号分析"""
        reasons = []
        strength = 0.0
        
        # MA金叉
        if indicators.get("ma_cross") == "golden":
            reasons.append("MA金叉形成，短期均线上穿长期均线")
            strength += 0.3
        
        # MACD信号
        macd = indicators.get("macd", {})
        if macd.get("signal") == "bullish":
            reasons.append("MACD金叉，DIF上穿DEA")
            strength += 0.25
        if macd.get("histogram_trend") == "increasing":
            reasons.append("MACD红柱放大，动能增强")
            strength += 0.15
        
        # RSI超卖反弹
        rsi = indicators.get("rsi", 50)
        if 30 < rsi < 50:
            reasons.append(f"RSI={rsi:.1f}处于合理区间，有上涨空间")
            strength += 0.2
        elif rsi < 30:
            reasons.append(f"RSI={rsi:.1f}超卖区，反弹概率高")
            strength += 0.15
        
        # 布林带
        boll = indicators.get("bollinger", {})
        if boll.get("price_position") == "lower_band":
            reasons.append("股价触及布林带下轨，技术性反弹")
            strength += 0.2
        
        # KDJ
        kdj = indicators.get("kdj", {})
        if kdj.get("j_value", 50) < 20:
            reasons.append("KDJ的J值低于20，超卖信号")
            strength += 0.15
        if kdj.get("cross") == "golden":
            reasons.append("KDJ金叉形成")
            strength += 0.2
        
        return {"reasons": reasons, "strength": min(1.0, strength)}
    
    def _analyze_capital_flow(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """资金面多头分析"""
        reasons = []
        strength = 0.0
        
        # 主力资金
        main_flow = market_data.get("main_capital_flow", 0)
        if main_flow > 0:
            reasons.append(f"主力资金净流入{main_flow/1e8:.2f}亿元")
            strength += min(0.3, main_flow / 1e9)
        
        # 北向资金
        north_flow = market_data.get("north_capital_flow", 0)
        if north_flow > 0:
            reasons.append(f"北向资金净买入{north_flow/1e8:.2f}亿元")
            strength += min(0.25, north_flow / 1e9)
        
        # 成交量
        volume_ratio = market_data.get("volume_ratio", 1.0)
        if volume_ratio > 1.5:
            reasons.append(f"量比{volume_ratio:.2f}，成交活跃")
            strength += 0.2
        elif volume_ratio > 1.2:
            reasons.append(f"量比{volume_ratio:.2f}，放量明显")
            strength += 0.1
        
        # 大单占比
        big_order_ratio = market_data.get("big_order_ratio", 0.5)
        if big_order_ratio > 0.6:
            reasons.append(f"大单买入占比{big_order_ratio*100:.1f}%，主力吸筹")
            strength += 0.2
        
        return {"reasons": reasons, "strength": min(1.0, strength)}
    
    def _analyze_trend(self, market_data: Dict[str, Any], indicators: Dict[str, Any]) -> Dict[str, Any]:
        """趋势多头分析"""
        reasons = []
        strength = 0.0
        
        # 均线排列
        ma_trend = indicators.get("ma_arrangement", "unknown")
        if ma_trend == "bullish":
            reasons.append("均线多头排列，趋势向上")
            strength += 0.35
        
        # 价格位置
        price_vs_ma20 = indicators.get("price_vs_ma20", 0)
        if price_vs_ma20 > 0:
            reasons.append(f"股价站稳20日均线，涨幅{price_vs_ma20*100:.1f}%")
            strength += 0.2
        
        # 突破信号
        if indicators.get("breakout"):
            reasons.append("突破前高或平台整理，打开上涨空间")
            strength += 0.3
        
        # 口袋支点
        if indicators.get("pocket_pivot"):
            reasons.append("口袋支点形成，强势启动信号")
            strength += 0.25
        
        return {"reasons": reasons, "strength": min(1.0, strength)}
    
    def _analyze_fundamental(self, fundamental: Dict[str, Any]) -> Dict[str, Any]:
        """基本面多头分析"""
        reasons = []
        strength = 0.0
        
        # PE估值
        pe = fundamental.get("pe_ratio", 0)
        industry_pe = fundamental.get("industry_pe", 20)
        if pe > 0 and pe < industry_pe * 0.7:
            reasons.append(f"PE={pe:.1f}低于行业均值{industry_pe:.1f}，低估")
            strength += 0.25
        
        # ROE
        roe = fundamental.get("roe", 0)
        if roe > 15:
            reasons.append(f"ROE={roe:.1f}%，盈利能力强")
            strength += 0.25
        
        # 业绩增长
        growth = fundamental.get("profit_growth", 0)
        if growth > 20:
            reasons.append(f"净利润增长{growth:.1f}%，成长性好")
            strength += 0.2
        
        # 分红
        dividend_yield = fundamental.get("dividend_yield", 0)
        if dividend_yield > 3:
            reasons.append(f"股息率{dividend_yield:.1f}%，分红丰厚")
            strength += 0.1
        
        return {"reasons": reasons, "strength": min(1.0, strength)}
    
    def _calculate_confidence(self, reasons: List[str], scores: List[float]) -> float:
        """计算置信度"""
        if not reasons:
            return 0.0
        # 理由越多、分数越高，置信度越高
        reason_factor = min(1.0, len(reasons) / 5)
        score_factor = np.mean(scores) if scores else 0
        consistency = 1 - np.std(scores) if len(scores) > 1 else 0.5
        
        return (reason_factor * 0.3 + score_factor * 0.5 + consistency * 0.2)


class ResearcherBearAgent:
    """空头观点研究员 - 负责挖掘看跌理由"""
    
    def __init__(self, name: str = "BearResearcher"):
        self.name = name
        self.signal_type = "bear"
    
    def analyze(self, market_data: Dict[str, Any], technical_indicators: Dict[str, Any],
                fundamental_data: Dict[str, Any] = None) -> ResearchSignal:
        """
        空头分析 - 寻找看跌信号
        """
        reasons = []
        supporting_data = {}
        strength_scores = []
        
        # 1. 技术面分析
        tech_signals = self._analyze_technical(technical_indicators)
        reasons.extend(tech_signals["reasons"])
        strength_scores.append(tech_signals["strength"])
        supporting_data["technical"] = tech_signals
        
        # 2. 资金面分析
        flow_signals = self._analyze_capital_flow(market_data)
        reasons.extend(flow_signals["reasons"])
        strength_scores.append(flow_signals["strength"])
        supporting_data["capital_flow"] = flow_signals
        
        # 3. 趋势分析
        trend_signals = self._analyze_trend(market_data, technical_indicators)
        reasons.extend(trend_signals["reasons"])
        strength_scores.append(trend_signals["strength"])
        supporting_data["trend"] = trend_signals
        
        # 4. 风险分析
        risk_signals = self._analyze_risks(market_data, technical_indicators, fundamental_data)
        reasons.extend(risk_signals["reasons"])
        strength_scores.append(risk_signals["strength"])
        supporting_data["risks"] = risk_signals
        
        # 综合评分
        avg_strength = np.mean(strength_scores) if strength_scores else 0.0
        confidence = self._calculate_confidence(reasons, strength_scores)
        
        return ResearchSignal(
            agent_name=self.name,
            signal_type=self.signal_type,
            strength=min(1.0, max(0.0, avg_strength)),  # 0 to 1 for bear strength
            confidence=confidence,
            reasons=reasons,
            supporting_data=supporting_data
        )
    
    def _analyze_technical(self, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """技术面空头信号分析"""
        reasons = []
        strength = 0.0
        
        # MA死叉
        if indicators.get("ma_cross") == "death":
            reasons.append("MA死叉形成，短期均线下穿长期均线")
            strength += 0.3
        
        # MACD信号
        macd = indicators.get("macd", {})
        if macd.get("signal") == "bearish":
            reasons.append("MACD死叉，DIF下穿DEA")
            strength += 0.25
        if macd.get("histogram_trend") == "decreasing":
            reasons.append("MACD绿柱放大，动能衰减")
            strength += 0.15
        
        # RSI超买
        rsi = indicators.get("rsi", 50)
        if rsi > 80:
            reasons.append(f"RSI={rsi:.1f}严重超买，回调风险高")
            strength += 0.25
        elif rsi > 70:
            reasons.append(f"RSI={rsi:.1f}超买区，注意回调")
            strength += 0.15
        
        # 布林带
        boll = indicators.get("bollinger", {})
        if boll.get("price_position") == "upper_band":
            reasons.append("股价触及布林带上轨，压力位")
            strength += 0.2
        
        # KDJ
        kdj = indicators.get("kdj", {})
        if kdj.get("j_value", 50) > 100:
            reasons.append("KDJ的J值超过100，严重超买")
            strength += 0.2
        if kdj.get("cross") == "death":
            reasons.append("KDJ死叉形成")
            strength += 0.2
        
        # 顶背离
        if indicators.get("divergence") == "bearish":
            reasons.append("技术指标顶背离，趋势可能反转")
            strength += 0.3
        
        return {"reasons": reasons, "strength": min(1.0, strength)}
    
    def _analyze_capital_flow(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """资金面空头分析"""
        reasons = []
        strength = 0.0
        
        # 主力资金
        main_flow = market_data.get("main_capital_flow", 0)
        if main_flow < 0:
            reasons.append(f"主力资金净流出{abs(main_flow)/1e8:.2f}亿元")
            strength += min(0.35, abs(main_flow) / 1e9)
        
        # 北向资金
        north_flow = market_data.get("north_capital_flow", 0)
        if north_flow < 0:
            reasons.append(f"北向资金净卖出{abs(north_flow)/1e8:.2f}亿元")
            strength += min(0.25, abs(north_flow) / 1e9)
        
        # 成交量萎缩
        volume_ratio = market_data.get("volume_ratio", 1.0)
        if volume_ratio < 0.7:
            reasons.append(f"量比{volume_ratio:.2f}，成交萎缩，人气不足")
            strength += 0.2
        
        # 大单卖出
        big_order_ratio = market_data.get("big_order_ratio", 0.5)
        if big_order_ratio < 0.4:
            reasons.append(f"大单买入占比仅{big_order_ratio*100:.1f}%，主力出货")
            strength += 0.25
        
        return {"reasons": reasons, "strength": min(1.0, strength)}
    
    def _analyze_trend(self, market_data: Dict[str, Any], indicators: Dict[str, Any]) -> Dict[str, Any]:
        """趋势空头分析"""
        reasons = []
        strength = 0.0
        
        # 均线排列
        ma_trend = indicators.get("ma_arrangement", "unknown")
        if ma_trend == "bearish":
            reasons.append("均线空头排列，趋势向下")
            strength += 0.35
        
        # 价格位置
        price_vs_ma20 = indicators.get("price_vs_ma20", 0)
        if price_vs_ma20 < -0.05:
            reasons.append(f"股价跌破20日均线{abs(price_vs_ma20)*100:.1f}%")
            strength += 0.25
        
        # 支撑破位
        if indicators.get("support_broken"):
            reasons.append("关键支撑位破位，下行空间打开")
            strength += 0.3
        
        # 高位滞涨
        if indicators.get("stagnation"):
            reasons.append("高位滞涨，上攻乏力")
            strength += 0.2
        
        return {"reasons": reasons, "strength": min(1.0, strength)}
    
    def _analyze_risks(self, market_data: Dict[str, Any], indicators: Dict[str, Any],
                       fundamental: Dict[str, Any] = None) -> Dict[str, Any]:
        """风险分析"""
        reasons = []
        strength = 0.0
        
        # 高位放量
        volume_ratio = market_data.get("volume_ratio", 1.0)
        price_position = indicators.get("price_vs_high_52w", 0)
        if volume_ratio > 2 and price_position > 0.9:
            reasons.append("高位巨量，疑似主力出货")
            strength += 0.35
        
        # 市场情绪过热
        sentiment = market_data.get("market_sentiment", 0.5)
        if sentiment > 0.8:
            reasons.append("市场情绪过热，需警惕反转")
            strength += 0.2
        
        # 基本面风险
        if fundamental:
            pe = fundamental.get("pe_ratio", 0)
            if pe > 50:
                reasons.append(f"PE={pe:.1f}估值过高，泡沫风险")
                strength += 0.25
            
            debt_ratio = fundamental.get("debt_ratio", 0)
            if debt_ratio > 0.7:
                reasons.append(f"资产负债率{debt_ratio*100:.1f}%，财务风险高")
                strength += 0.2
        
        return {"reasons": reasons, "strength": min(1.0, strength)}
    
    def _calculate_confidence(self, reasons: List[str], scores: List[float]) -> float:
        """计算置信度"""
        if not reasons:
            return 0.0
        reason_factor = min(1.0, len(reasons) / 5)
        score_factor = np.mean(scores) if scores else 0
        consistency = 1 - np.std(scores) if len(scores) > 1 else 0.5
        
        return (reason_factor * 0.3 + score_factor * 0.5 + consistency * 0.2)


# ==================== 区制检测器 ====================

class RegimeDetector:
    """市场区制检测器 - 使用GMM识别市场状态"""
    
    def __init__(self, n_regimes: int = 4):
        self.n_regimes = n_regimes
        self.regime_models = {}
        self.current_regime = MarketRegime.TRANSITION
        
    def detect(self, market_data: Dict[str, Any], lookback_returns: np.ndarray = None) -> MarketRegime:
        """
        检测当前市场区制
        
        Args:
            market_data: 市场数据
            lookback_returns: 历史收益率序列 (用于GMM)
        
        Returns:
            MarketRegime: 当前市场区制
        """
        # 提取特征
        features = self._extract_features(market_data, lookback_returns)
        
        # 基于规则的区制判断 (简化版，实际应使用GMM)
        regime = self._classify_regime(features)
        
        self.current_regime = regime
        return regime
    
    def _extract_features(self, market_data: Dict[str, Any], returns: np.ndarray = None) -> Dict[str, float]:
        """提取区制识别特征"""
        features = {}
        
        # 波动率
        if returns is not None and len(returns) > 20:
            features["volatility"] = np.std(returns[-20:])
            features["volatility_ratio"] = np.std(returns[-20:]) / (np.std(returns[-60:]) + 1e-8)
        else:
            features["volatility"] = market_data.get("volatility_20d", 0.02)
            features["volatility_ratio"] = market_data.get("volatility_ratio", 1.0)
        
        # 趋势强度
        features["trend_strength"] = market_data.get("adx", 25) / 100.0
        
        # 市场宽度
        features["market_breadth"] = market_data.get("advance_decline_ratio", 1.0)
        
        # VIX或恐慌指数
        features["fear_index"] = market_data.get("vix", 20) / 100.0
        
        # 相关性 (个股与指数)
        features["correlation"] = market_data.get("market_correlation", 0.5)
        
        # 跳跃风险
        if returns is not None and len(returns) > 5:
            features["jump_risk"] = np.sum(np.abs(returns[-5:]) > 2 * np.std(returns)) / 5
        else:
            features["jump_risk"] = market_data.get("jump_risk", 0.1)
        
        return features
    
    def _classify_regime(self, features: Dict[str, float]) -> MarketRegime:
        """基于特征分类市场区制"""
        volatility = features.get("volatility", 0.02)
        volatility_ratio = features.get("volatility_ratio", 1.0)
        trend_strength = features.get("trend_strength", 0.25)
        fear_index = features.get("fear_index", 0.2)
        jump_risk = features.get("jump_risk", 0.1)
        
        # 危机区制: 高波动、高恐慌、高跳跃风险
        if fear_index > 0.4 or volatility_ratio > 2.0 or jump_risk > 0.3:
            return MarketRegime.CRISIS_REGIME
        
        # 低波动趋势区制: 低波动、强趋势
        if volatility < 0.02 and trend_strength > 0.3 and volatility_ratio < 1.2:
            return MarketRegime.LOW_VOLATILITY_TRENDING
        
        # 高波动均值回归区制: 高波动、弱趋势
        if volatility > 0.03 or volatility_ratio > 1.3:
            return MarketRegime.HIGH_VOLATILITY_MEAN_REVERTING
        
        # 默认低波动趋势
        return MarketRegime.LOW_VOLATILITY_TRENDING
    
    def get_regime_characteristics(self, regime: MarketRegime) -> Dict[str, Any]:
        """获取区制特征"""
        characteristics = {
            MarketRegime.LOW_VOLATILITY_TRENDING: {
                "description": "低波动趋势市",
                "suitable_strategies": ["趋势跟踪", "动量策略", "均线策略"],
                "risk_level": "低",
                "recommended_position_scale": 1.0,
                "stop_loss_multiplier": 1.0
            },
            MarketRegime.HIGH_VOLATILITY_MEAN_REVERTING: {
                "description": "高波动震荡市",
                "suitable_strategies": ["均值回归", "区间交易", "反转策略"],
                "risk_level": "中",
                "recommended_position_scale": 0.7,
                "stop_loss_multiplier": 1.5
            },
            MarketRegime.CRISIS_REGIME: {
                "description": "危机市场",
                "suitable_strategies": ["避险", "对冲", "现金为王"],
                "risk_level": "高",
                "recommended_position_scale": 0.3,
                "stop_loss_multiplier": 2.0
            },
            MarketRegime.TRANSITION: {
                "description": "过渡期",
                "suitable_strategies": ["观望", "小仓位试错"],
                "risk_level": "中高",
                "recommended_position_scale": 0.5,
                "stop_loss_multiplier": 1.3
            }
        }
        return characteristics.get(regime, characteristics[MarketRegime.TRANSITION])


# ==================== 辩论室 ====================

class DebateRoomAgent:
    """辩论室Agent - 综合多空观点，形成平衡分析"""
    
    def __init__(self):
        self.bull_agent = ResearcherBullAgent()
        self.bear_agent = ResearcherBearAgent()
        self.regime_detector = RegimeDetector()
        
    def conduct_debate(self, market_data: Dict[str, Any], 
                       technical_indicators: Dict[str, Any],
                       fundamental_data: Dict[str, Any] = None,
                       lookback_returns: np.ndarray = None) -> DebateResult:
        """
        进行多空辩论
        
        Returns:
            DebateResult: 辩论结果
        """
        # 1. 获取多空观点
        bull_signal = self.bull_agent.analyze(market_data, technical_indicators, fundamental_data)
        bear_signal = self.bear_agent.analyze(market_data, technical_indicators, fundamental_data)
        
        # 2. 检测市场区制
        regime = self.regime_detector.detect(market_data, lookback_returns)
        
        # 3. 自适应信号聚合
        consensus = self.adaptive_signal_aggregation(
            [bull_signal, bear_signal], 
            {"regime": regime, "market_data": market_data}
        )
        
        # 4. 提取关键论点
        key_arguments = {
            "bull": bull_signal.reasons[:3],  # 取前3个最重要论点
            "bear": bear_signal.reasons[:3]
        }
        
        # 5. 计算不确定性
        uncertainty = self._calculate_uncertainty(bull_signal, bear_signal, regime)
        
        return DebateResult(
            bull_score=bull_signal.strength * bull_signal.confidence,
            bear_score=bear_signal.strength * bear_signal.confidence,
            consensus=consensus,
            key_arguments=key_arguments,
            uncertainty=uncertainty,
            regime_context=regime
        )
    
    def adaptive_signal_aggregation(self, signals: List[ResearchSignal], 
                                     regime_info: Dict[str, Any]) -> float:
        """
        自适应信号聚合 - 根据市场区制调整权重
        
        Args:
            signals: 信号列表 [bull_signal, bear_signal]
            regime_info: 区制信息
        
        Returns:
            float: 综合信号 (-1 to 1, 正=看多, 负=看空)
        """
        regime = regime_info.get("regime", MarketRegime.TRANSITION)
        
        # 区制权重调整
        regime_weights = {
            MarketRegime.LOW_VOLATILITY_TRENDING: {"bull": 1.2, "bear": 0.8},  # 趋势市偏多
            MarketRegime.HIGH_VOLATILITY_MEAN_REVERTING: {"bull": 0.9, "bear": 1.1},  # 震荡市平衡
            MarketRegime.CRISIS_REGIME: {"bull": 0.6, "bear": 1.5},  # 危机市偏空
            MarketRegime.TRANSITION: {"bull": 1.0, "bear": 1.0}  # 过渡期平衡
        }
        
        weights = regime_weights.get(regime, {"bull": 1.0, "bear": 1.0})
        
        bull_signal = signals[0]
        bear_signal = signals[1]
        
        # 加权评分
        weighted_bull = bull_signal.strength * bull_signal.confidence * weights["bull"]
        weighted_bear = bear_signal.strength * bear_signal.confidence * weights["bear"]
        
        # 综合信号: 正值看多，负值看空
        consensus = weighted_bull - weighted_bear
        
        # 归一化到 [-1, 1]
        return np.clip(consensus, -1.0, 1.0)
    
    def _calculate_uncertainty(self, bull_signal: ResearchSignal, 
                                bear_signal: ResearchSignal,
                                regime: MarketRegime) -> float:
        """计算不确定性"""
        # 基础不确定性: 多空分歧程度
        divergence = abs(bull_signal.strength - bear_signal.strength)
        base_uncertainty = divergence  # 分歧越大，不确定性越高（已修复逻辑）
        
        # 置信度调整
        confidence_factor = 1 - (bull_signal.confidence + bear_signal.confidence) / 2
        
        # 区制调整
        regime_uncertainty = {
            MarketRegime.LOW_VOLATILITY_TRENDING: 0.2,
            MarketRegime.HIGH_VOLATILITY_MEAN_REVERTING: 0.5,
            MarketRegime.CRISIS_REGIME: 0.8,
            MarketRegime.TRANSITION: 0.6
        }
        regime_factor = regime_uncertainty.get(regime, 0.5)
        
        # 综合不确定性
        return min(1.0, base_uncertainty * 0.4 + confidence_factor * 0.3 + regime_factor * 0.3)


# ==================== 风险管理器 ====================

class RiskManager:
    """风险管理器 - 风险评估和仓位控制"""
    
    def __init__(self, max_position: float = 0.2, max_daily_loss: float = 0.02,
                 max_drawdown: float = 0.1):
        self.max_position = max_position  # 单只最大仓位
        self.max_daily_loss = max_daily_loss  # 日最大亏损
        self.max_drawdown = max_drawdown  # 最大回撤
    
    def calculate_risk_metrics(self, returns: np.ndarray, 
                                current_position: float = 0) -> RiskMetrics:
        """
        计算风险指标
        
        Args:
            returns: 历史收益率序列
            current_position: 当前仓位比例
        
        Returns:
            RiskMetrics: 风险指标
        """
        if len(returns) < 20:
            return self._default_risk_metrics()
        
        # VaR计算
        var_95 = self.calculate_var(returns, 0.95)
        var_99 = self.calculate_var(returns, 0.99)
        cvar_95 = self.calculate_cvar(returns, 0.95)
        
        # 最大回撤
        max_drawdown = self._calculate_max_drawdown(returns)
        
        # 波动率
        volatility = np.std(returns) * np.sqrt(252)  # 年化波动率
        
        # 夏普比率 (假设无风险利率3%)
        avg_return = np.mean(returns) * 252
        sharpe_ratio = (avg_return - 0.03) / (volatility + 1e-8)
        
        # 凯利仓位
        kelly_fraction = self.kelly_position_size(returns)
        
        # 建议仓位
        recommended_position = self._calculate_recommended_position(
            var_95, max_drawdown, kelly_fraction, current_position
        )
        
        return RiskMetrics(
            var_95=var_95,
            var_99=var_99,
            cvar_95=cvar_95,
            max_drawdown=max_drawdown,
            volatility=volatility,
            sharpe_ratio=sharpe_ratio,
            kelly_fraction=kelly_fraction,
            recommended_position=recommended_position
        )
    
    def calculate_var(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """
        计算VaR (Value at Risk)
        
        Args:
            returns: 收益率序列
            confidence: 置信水平
        
        Returns:
            float: VaR值 (正数表示可能损失)
        """
        if len(returns) == 0:
            return 0.0
        
        # 历史模拟法
        sorted_returns = np.sort(returns)
        index = int((1 - confidence) * len(sorted_returns))
        # 边界检查防止索引越界
        index = max(0, min(index, len(sorted_returns) - 1))
        var = -sorted_returns[index]
        
        return max(0, var)
    
    def calculate_cvar(self, returns: np.ndarray, confidence: float = 0.95) -> float:
        """
        计算CVaR (Conditional VaR / Expected Shortfall)
        即超出VaR的平均损失
        
        Args:
            returns: 收益率序列
            confidence: 置信水平
        
        Returns:
            float: CVaR值
        """
        if len(returns) == 0:
            return 0.0
        
        var = self.calculate_var(returns, confidence)
        
        # 获取所有低于VaR的收益
        tail_returns = returns[returns <= -var]
        
        if len(tail_returns) == 0:
            return var
        
        return -np.mean(tail_returns)
    
    def kelly_position_size(self, returns: np.ndarray = None, 
                            win_rate: float = None,
                            win_loss_ratio: float = None,
                            regime: MarketRegime = None) -> float:
        """
        凯利公式计算最优仓位
        
        f* = p - (1-p)/b
        其中 p = 胜率, b = 盈亏比
        
        Args:
            returns: 收益率序列 (用于计算胜率和盈亏比)
            win_rate: 直接指定胜率
            win_loss_ratio: 直接指定盈亏比
            regime: 市场区制 (用于调整)
        
        Returns:
            float: 凯利仓位比例
        """
        # 从收益率序列计算
        if returns is not None and len(returns) > 10:
            positive_returns = returns[returns > 0]
            negative_returns = returns[returns < 0]
            
            win_rate = len(positive_returns) / len(returns)
            avg_win = np.mean(positive_returns) if len(positive_returns) > 0 else 0
            avg_loss = abs(np.mean(negative_returns)) if len(negative_returns) > 0 else 1e-8
            win_loss_ratio = avg_win / (avg_loss + 1e-8)
        
        # 默认值
        if win_rate is None:
            win_rate = 0.5
        if win_loss_ratio is None:
            win_loss_ratio = 1.0
        
        # 凯利公式
        kelly = win_rate - (1 - win_rate) / (win_loss_ratio + 1e-8)
        
        # 凯利公式返回负数时发出警告（表示期望收益为负）
        if kelly < 0:
            logger.warning(f"凯利公式返回负值{kelly:.4f}，胜率{win_rate:.2%}，盈亏比{win_loss_ratio:.2f}，建议不交易或减仓")
        
        # 区制调整
        if regime is not None:
            regime_adjustments = {
                MarketRegime.LOW_VOLATILITY_TRENDING: 1.0,
                MarketRegime.HIGH_VOLATILITY_MEAN_REVERTING: 0.7,
                MarketRegime.CRISIS_REGIME: 0.3,
                MarketRegime.TRANSITION: 0.5
            }
            kelly *= regime_adjustments.get(regime, 0.7)
        
        # 限制范围 (使用半凯利更安全)
        return np.clip(kelly * 0.5, 0, self.max_position)
    
    def _calculate_max_drawdown(self, returns: np.ndarray) -> float:
        """计算最大回撤"""
        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - running_max) / running_max
        return abs(np.min(drawdowns))
    
    # 风险指标最小阈值，防止除零导致极大仓位
    MIN_RISK_THRESHOLD = 0.001
    
    def _calculate_recommended_position(self, var: float, max_dd: float,
                                         kelly: float, current: float) -> float:
        """计算建议仓位"""
        # VaR限制 - 使用最小阈值防止除零
        safe_var = max(var, self.MIN_RISK_THRESHOLD)
        var_limit = self.max_daily_loss / safe_var
        
        # 回撤限制 - 使用最小阈值防止除零
        safe_max_dd = max(max_dd, self.MIN_RISK_THRESHOLD)
        dd_limit = self.max_drawdown / safe_max_dd
        
        # 综合限制
        position = min(kelly, var_limit, dd_limit, self.max_position)
        
        # 考虑当前仓位
        available = self.max_position - current
        position = min(position, available)
        
        return max(0, position)
    
    def _default_risk_metrics(self) -> RiskMetrics:
        """默认风险指标"""
        return RiskMetrics(
            var_95=0.02,
            var_99=0.03,
            cvar_95=0.04,
            max_drawdown=0.05,
            volatility=0.20,
            sharpe_ratio=0.5,
            kelly_fraction=0.1,
            recommended_position=0.1
        )
    
    def validate_trade(self, decision: TradeDecision, 
                       current_portfolio: Dict[str, Any]) -> Tuple[bool, str]:
        """
        验证交易是否符合风险约束
        
        Args:
            decision: 交易决策
            current_portfolio: 当前组合状态
        
        Returns:
            Tuple[bool, str]: (是否通过, 原因)
        """
        # 检查单只仓位
        if decision.position_size > self.max_position:
            return False, f"单只仓位{decision.position_size:.1%}超过上限{self.max_position:.1%}"
        
        # 检查总仓位
        current_total = current_portfolio.get("total_position", 0)
        new_total = current_total + decision.position_size
        if new_total > 0.8:  # 总仓位上限80%
            return False, f"总仓位{new_total:.1%}接近上限，需降低风险敞口"
        
        # 检查止损
        if decision.stop_loss is not None and decision.entry_price is not None:
            stop_loss_pct = abs(decision.stop_loss - decision.entry_price) / decision.entry_price
            if stop_loss_pct > 0.1:  # 止损超过10%
                return False, f"止损幅度{stop_loss_pct:.1%}过大，需收紧"
        
        return True, "风险检查通过"


# ==================== 组合经理 ====================

class PortfolioManager:
    """组合经理 - 最终交易决策"""
    
    def __init__(self, risk_manager: RiskManager = None):
        self.debate_room = DebateRoomAgent()
        self.risk_manager = risk_manager or RiskManager()
        self.decision_history: List[TradeDecision] = []
        
    def make_decision(self, market_data: Dict[str, Any],
                      technical_indicators: Dict[str, Any],
                      fundamental_data: Dict[str, Any] = None,
                      portfolio_state: Dict[str, Any] = None,
                      lookback_returns: np.ndarray = None) -> TradeDecision:
        """
        做出交易决策
        
        Args:
            market_data: 市场数据
            technical_indicators: 技术指标
            fundamental_data: 基本面数据
            portfolio_state: 组合状态
            lookback_returns: 历史收益率
        
        Returns:
            TradeDecision: 交易决策
        """
        # 1. 进行多空辩论
        debate_result = self.debate_room.conduct_debate(
            market_data, technical_indicators, fundamental_data, lookback_returns
        )
        
        # 2. 计算风险指标
        risk_metrics = self.risk_manager.calculate_risk_metrics(
            lookback_returns if lookback_returns is not None else np.array([]),
            portfolio_state.get("current_position", 0) if portfolio_state else 0
        )
        
        # 3. 获取区制特征
        regime = debate_result.regime_context
        regime_chars = self.debate_room.regime_detector.get_regime_characteristics(regime)
        
        # 4. 形成决策
        decision = self._formulate_decision(
            debate_result, risk_metrics, regime_chars, market_data
        )
        
        # 5. 风险验证
        if portfolio_state:
            is_valid, reason = self.risk_manager.validate_trade(decision, portfolio_state)
            if not is_valid:
                decision.action = "hold"
                decision.reasoning = f"风险约束: {reason}"
                decision.position_size = 0
        
        # 6. 记录历史
        self.decision_history.append(decision)
        
        return decision
    
    def _formulate_decision(self, debate: DebateResult, risk: RiskMetrics,
                            regime_chars: Dict[str, Any],
                            market_data: Dict[str, Any]) -> TradeDecision:
        """形成交易决策"""
        consensus = debate.consensus
        uncertainty = debate.uncertainty
        
        # 基础决策逻辑
        if consensus > 0.3 and uncertainty < 0.5:
            action = "buy"
            base_position = risk.recommended_position * min(1.0, consensus + 0.5)
        elif consensus < -0.3 and uncertainty < 0.5:
            action = "sell"
            base_position = 0
        elif abs(consensus) < 0.2 or uncertainty > 0.6:
            action = "hold"
            base_position = 0
        else:
            # 弱信号，小仓位试探
            action = "buy" if consensus > 0 else "hold"
            base_position = risk.recommended_position * 0.3
        
        # 区制调整
        position_scale = regime_chars.get("recommended_position_scale", 1.0)
        final_position = base_position * position_scale
        
        # 计算止损止盈
        current_price = market_data.get("current_price", 0)
        if current_price > 0 and action == "buy":
            stop_loss_multiplier = regime_chars.get("stop_loss_multiplier", 1.0)
            stop_loss = current_price * (1 - 0.03 * stop_loss_multiplier)  # 基础3%止损
            take_profit = current_price * (1 + 0.05 + abs(consensus) * 0.05)  # 5-10%止盈
        else:
            stop_loss = None
            take_profit = None
        
        # 决策理由
        reasoning = self._generate_reasoning(debate, risk, regime_chars)
        
        return TradeDecision(
            action=action,
            position_size=min(final_position, risk.kelly_fraction),
            entry_price=current_price if action == "buy" else None,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=max(0, abs(consensus) * (1 - uncertainty)),
            reasoning=reasoning,
            risk_metrics=risk,
            debate_result=debate
        )
    
    def _generate_reasoning(self, debate: DebateResult, risk: RiskMetrics,
                            regime_chars: Dict[str, Any]) -> str:
        """生成决策理由"""
        lines = []
        
        # 区制背景
        lines.append(f"【市场环境】{regime_chars['description']}")
        lines.append(f"适合策略: {', '.join(regime_chars['suitable_strategies'][:2])}")
        
        # 多空观点
        lines.append(f"\n【多头观点】{debate.bull_score:.2f}")
        for arg in debate.key_arguments["bull"][:2]:
            lines.append(f"  • {arg}")
        
        lines.append(f"\n【空头观点】{debate.bear_score:.2f}")
        for arg in debate.key_arguments["bear"][:2]:
            lines.append(f"  • {arg}")
        
        # 综合判断
        direction = "偏多" if debate.consensus > 0 else "偏空"
        lines.append(f"\n【综合判断】{direction}信号{abs(debate.consensus):.2f}，不确定性{debate.uncertainty:.1%}")
        
        # 风险提示
        lines.append(f"\n【风险提示】")
        lines.append(f"  VaR(95%): {risk.var_95:.2%}")
        lines.append(f"  建议仓位: {risk.recommended_position:.1%}")
        
        return "\n".join(lines)
    
    def get_decision_summary(self) -> Dict[str, Any]:
        """获取决策摘要"""
        if not self.decision_history:
            return {"total_decisions": 0}
        
        recent = self.decision_history[-20:]  # 最近20次
        
        buy_count = sum(1 for d in recent if d.action == "buy")
        sell_count = sum(1 for d in recent if d.action == "sell")
        hold_count = sum(1 for d in recent if d.action == "hold")
        
        avg_confidence = np.mean([d.confidence for d in recent])
        avg_position = np.mean([d.position_size for d in recent if d.action == "buy"])
        
        return {
            "total_decisions": len(self.decision_history),
            "recent_actions": {"buy": buy_count, "sell": sell_count, "hold": hold_count},
            "avg_confidence": avg_confidence,
            "avg_position_when_buy": avg_position
        }


# ==================== 便捷函数 ====================

def analyze_stock(market_data: Dict[str, Any],
                  technical_indicators: Dict[str, Any],
                  fundamental_data: Dict[str, Any] = None,
                  lookback_returns: np.ndarray = None) -> TradeDecision:
    """
    一站式股票分析函数
    
    Args:
        market_data: 市场数据
        technical_indicators: 技术指标
        fundamental_data: 基本面数据
        lookback_returns: 历史收益率
    
    Returns:
        TradeDecision: 交易决策
    """
    pm = PortfolioManager()
    return pm.make_decision(
        market_data, technical_indicators, fundamental_data,
        None, lookback_returns
    )


# ==================== 导出 ====================

__all__ = [
    # 数据类
    'SignalStrength', 'MarketRegime', 'ResearchSignal', 'DebateResult',
    'RiskMetrics', 'TradeDecision',
    # Agent类
    'ResearcherBullAgent', 'ResearcherBearAgent', 'DebateRoomAgent',
    'RegimeDetector', 'RiskManager', 'PortfolioManager',
    # 便捷函数
    'analyze_stock'
]

# -*- coding: utf-8 -*-
"""
股票分析Agent系统 - stock_agents.py
包含12个专业Agent：6个分析Agent + 6个决策/风控/执行Agent
整合fortune CatBoost模型预测能力
整合fortune向量化技术指标计算
整合fortune 6维度评分系统
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Callable, Tuple
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import asyncio
import warnings
import os
import sys

warnings.filterwarnings('ignore')

# 添加fortune目录到路径
FORTUNE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'fortune')
if FORTUNE_PATH not in sys.path:
    sys.path.insert(0, FORTUNE_PATH)

# 导入fortune向量化指标模块
# 注意：直接导入具体文件，绕过ml_services/__init__.py的依赖
try:
    import importlib.util
    
    # 直接加载vectorized_indicators.py
    vi_path = os.path.join(FORTUNE_PATH, 'ml_services', 'vectorized_indicators.py')
    sds_path = os.path.join(FORTUNE_PATH, 'ml_services', 'six_dim_scorer.py')
    
    vi_spec = importlib.util.spec_from_file_location("vectorized_indicators", vi_path)
    vi_module = importlib.util.module_from_spec(vi_spec)
    vi_spec.loader.exec_module(vi_module)
    VectorizedIndicators = vi_module.VectorizedIndicators
    
    sds_spec = importlib.util.spec_from_file_location("six_dim_scorer", sds_path)
    sds_module = importlib.util.module_from_spec(sds_spec)
    sds_spec.loader.exec_module(sds_module)
    SixDimensionScorer = sds_module.SixDimensionScorer
    
    VECTORIZED_INDICATORS_AVAILABLE = True
    print("stock_agents: 成功加载向量化指标模块（直接加载）")
except Exception as e:
    VECTORIZED_INDICATORS_AVAILABLE = False
    print(f"stock_agents: 向量化指标模块加载失败，使用内置计算: {e}")


# ==================== 信号枚举 ====================
class SignalType(Enum):
    """信号类型"""
    BULLISH = "bullish"       # 看涨
    BEARISH = "bearish"       # 看跌
    NEUTRAL = "neutral"       # 中性
    STRONG_BUY = "strong_buy" # 强烈买入
    STRONG_SELL = "strong_sell" # 强烈卖出


class MarketRegime(Enum):
    """市场区制"""
    BULL = "bull"             # 牛市
    BEAR = "bear"             # 熊市
    SIDEWAYS = "sideways"     # 震荡
    TRANSITION = "transition" # 转换期


# ==================== 数据结构 ====================
@dataclass
class AgentSignal:
    """Agent信号"""
    agent_name: str
    signal: str               # bullish/bearish/neutral
    confidence: float         # 0-1
    reasoning: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'agent_name': self.agent_name,
            'signal': self.signal,
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'metrics': self.metrics,
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class ConsolidatedSignal:
    """综合信号"""
    final_signal: str
    confidence: float
    weighted_score: float
    agent_signals: List[AgentSignal]
    market_regime: MarketRegime
    risk_level: float
    position_suggestion: float  # 0-1 建议仓位比例
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'final_signal': self.final_signal,
            'confidence': self.confidence,
            'weighted_score': self.weighted_score,
            'agent_signals': [s.to_dict() for s in self.agent_signals],
            'market_regime': self.market_regime.value,
            'risk_level': self.risk_level,
            'position_suggestion': self.position_suggestion
        }


# ==================== 基础Agent类 ====================
class BaseStockAgent(ABC):
    """股票分析Agent基类"""
    
    def __init__(self, name: str, description: str, weight: float = 1.0):
        self.name = name
        self.description = description
        self.weight = weight
        self.enabled = True
    
    @abstractmethod
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """
        分析数据并生成信号
        
        Args:
            data: 包含股票数据的字典，通常包括:
                - 'prices': pd.DataFrame (OHLCV数据)
                - 'fundamentals': dict (基本面数据)
                - 'news': list (新闻列表)
                - 'market': dict (市场环境数据)
                
        Returns:
            AgentSignal对象
        """
        pass
    
    def enable(self):
        """启用Agent"""
        self.enabled = True
    
    def disable(self):
        """禁用Agent"""
        self.enabled = False
    
    def set_weight(self, weight: float):
        """设置权重"""
        self.weight = max(0.0, min(2.0, weight))


# ==================== 6个分析Agent ====================

class TechnicalAnalyst(BaseStockAgent):
    """技术分析Agent - 技术指标+区制感知
    
    整合fortune向量化指标：
    - MA/EMA/SMA移动平均
    - MACD指数平滑
    - KDJ随机指标
    - RSI相对强弱
    - BOLL布林带
    - ATR真实波幅
    - CCI商品通道
    - ADX趋向指数
    """
    
    def __init__(self):
        super().__init__(
            name="TechnicalAnalyst",
            description="技术分析Agent，负责K线形态、趋势指标、市场区制识别",
            weight=1.2
        )
        self.regime_threshold = 0.3
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """技术分析"""
        prices = data.get('prices')
        if prices is None or len(prices) < 30:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="数据不足，无法进行技术分析"
            )
        
        metrics = {}
        signals = []
        
        # 使用向量化指标计算（如果可用）
        if VECTORIZED_INDICATORS_AVAILABLE:
            prices = self._prepare_dataframe(prices)
            indicators_df = VectorizedIndicators.compute_batch_indicators(prices)
            metrics['indicators_computed'] = 'vectorized'
            
            # 1. 趋势分析（MA交叉）- 使用向量化MA
            ma_signal, ma_metrics = self._analyze_moving_averages_vectorized(indicators_df)
            signals.append(ma_signal)
            metrics.update(ma_metrics)
            
            # 2. 动量分析（RSI）- 使用向量化RSI
            rsi_signal, rsi_metrics = self._analyze_rsi_vectorized(indicators_df)
            signals.append(rsi_signal)
            metrics.update(rsi_metrics)
            
            # 3. 波动率分析（布林带）- 使用向量化BOLL
            bb_signal, bb_metrics = self._analyze_bollinger_vectorized(indicators_df)
            signals.append(bb_signal)
            metrics.update(bb_metrics)
            
            # 4. MACD分析 - 使用向量化MACD
            macd_signal, macd_metrics = self._analyze_macd_vectorized(indicators_df)
            signals.append(macd_signal)
            metrics.update(macd_metrics)
            
            # 5. KDJ分析 - 新增
            kdj_signal, kdj_metrics = self._analyze_kdj_vectorized(indicators_df)
            signals.append(kdj_signal)
            metrics.update(kdj_metrics)
            
            # 6. ATR分析 - 新增
            atr_signal, atr_metrics = self._analyze_atr_vectorized(indicators_df)
            signals.append(atr_signal)
            metrics.update(atr_metrics)
            
            # 7. CCI分析 - 新增
            cci_signal, cci_metrics = self._analyze_cci_vectorized(indicators_df)
            signals.append(cci_signal)
            metrics.update(cci_metrics)
            
            # 8. ADX分析 - 新增
            adx_signal, adx_metrics = self._analyze_adx_vectorized(indicators_df)
            signals.append(adx_signal)
            metrics.update(adx_metrics)
            
            # 9. 筹码分布分析 - 新增
            chip_signal, chip_metrics = self._analyze_chip_distribution(prices)
            signals.append(chip_signal)
            metrics.update(chip_metrics)
            
            # 10. 筹码形态识别 - 新增
            chip_pattern = self._identify_chip_pattern(prices)
            metrics['chip_pattern'] = chip_pattern
            
            # 筹码形态调整信号
            if chip_pattern == "低位单峰":
                signals.append(0.5)  # 看涨加成
            elif chip_pattern == "高位单峰":
                signals.append(-0.5)  # 风险加成
        else:
            # 回退到内置计算
            # 1. 趋势分析（MA交叉）
            ma_signal, ma_metrics = self._analyze_moving_averages(prices)
            signals.append(ma_signal)
            metrics.update(ma_metrics)
            
            # 2. 动量分析（RSI）
            rsi_signal, rsi_metrics = self._analyze_rsi(prices)
            signals.append(rsi_signal)
            metrics.update(rsi_metrics)
            
            # 3. 波动率分析（布林带）
            bb_signal, bb_metrics = self._analyze_bollinger(prices)
            signals.append(bb_signal)
            metrics.update(bb_metrics)
            
            # 4. MACD分析
            macd_signal, macd_metrics = self._analyze_macd(prices)
            signals.append(macd_signal)
            metrics.update(macd_metrics)
        
        # 9. 市场区制识别
        regime, regime_metrics = self._detect_regime(prices)
        metrics['regime'] = regime.value
        metrics.update(regime_metrics)
        
        # 综合信号
        avg_signal = np.mean(signals)
        if avg_signal > 0.3:
            final_signal = "bullish"
        elif avg_signal < -0.3:
            final_signal = "bearish"
        else:
            final_signal = "neutral"
        
        confidence = min(1.0, abs(avg_signal) * 1.5)
        
        # 区制调整
        if regime == MarketRegime.BULL and final_signal == "bullish":
            confidence *= 1.2
        elif regime == MarketRegime.BEAR and final_signal == "bearish":
            confidence *= 1.2
        
        return AgentSignal(
            agent_name=self.name,
            signal=final_signal,
            confidence=confidence,
            reasoning=self._generate_reasoning(metrics, regime),
            metrics=metrics
        )
    
    def _prepare_dataframe(self, prices: pd.DataFrame) -> pd.DataFrame:
        """准备数据框格式（向量化指标需要特定列名）"""
        df = prices.copy()
        # 标准化列名
        column_mapping = {
            'open': 'Open', 'high': 'High', 'low': 'Low',
            'close': 'Close', 'volume': 'Volume'
        }
        for old, new in column_mapping.items():
            if old in df.columns and new not in df.columns:
                df[new] = df[old]
        return df
    
    def _analyze_moving_averages_vectorized(self, df: pd.DataFrame) -> tuple:
        """向量化均线分析"""
        current = df['Close'].iloc[-1]
        ma5 = df['MA5'].iloc[-1] if 'MA5' in df else current
        ma10 = df['MA10'].iloc[-1] if 'MA10' in df else current
        ma20 = df['MA20'].iloc[-1] if 'MA20' in df else current
        ma60 = df['MA60'].iloc[-1] if 'MA60' in df else current
        
        signal = 0
        if current > ma5 > ma10 > ma20 > ma60:
            signal = 1.0  # 强势多头排列
        elif current > ma5 > ma10 > ma20:
            signal = 0.7  # 多头排列
        elif current > ma5:
            signal = 0.3
        elif current < ma5 < ma10 < ma20:
            signal = -0.7  # 空头排列
        elif current < ma5:
            signal = -0.3
        
        metrics = {
            'ma5': float(ma5),
            'ma10': float(ma10),
            'ma20': float(ma20),
            'ma60': float(ma60),
            'price_vs_ma5': float((current - ma5) / ma5) if ma5 != 0 else 0,
            'price_vs_ma20': float((current - ma20) / ma20) if ma20 != 0 else 0
        }
        
        return signal, metrics
    
    def _analyze_rsi_vectorized(self, df: pd.DataFrame) -> tuple:
        """向量化RSI分析"""
        rsi = df['RSI'].iloc[-1] if 'RSI' in df else 50
        
        signal = 0
        if rsi < 20:
            signal = 1.0  # 严重超卖
        elif rsi < 30:
            signal = 0.7  # 超卖
        elif rsi > 80:
            signal = -1.0  # 严重超买
        elif rsi > 70:
            signal = -0.7  # 超买
        elif rsi < 40:
            signal = 0.3
        elif rsi > 60:
            signal = -0.3
        
        return signal, {'rsi': float(rsi)}
    
    def _analyze_bollinger_vectorized(self, df: pd.DataFrame) -> tuple:
        """向量化布林带分析"""
        current = df['Close'].iloc[-1]
        upper = df['BOLL_UPPER'].iloc[-1] if 'BOLL_UPPER' in df else current
        lower = df['BOLL_LOWER'].iloc[-1] if 'BOLL_LOWER' in df else current
        middle = df['BOLL_MID'].iloc[-1] if 'BOLL_MID' in df else current
        
        bb_position = (current - lower) / (upper - lower) if upper != lower else 0.5
        
        signal = 0
        if bb_position < 0.05:
            signal = 1.0  # 触及下轨强支撑
        elif bb_position < 0.2:
            signal = 0.7  # 接近下轨
        elif bb_position > 0.95:
            signal = -1.0  # 触及上轨强压力
        elif bb_position > 0.8:
            signal = -0.7  # 接近上轨
        
        return signal, {
            'bb_upper': float(upper),
            'bb_middle': float(middle),
            'bb_lower': float(lower),
            'bb_position': float(bb_position)
        }
    
    def _analyze_macd_vectorized(self, df: pd.DataFrame) -> tuple:
        """向量化MACD分析"""
        macd = df['MACD'].iloc[-1] if 'MACD' in df else 0
        macd_signal_line = df['MACD_DEA'].iloc[-1] if 'MACD_DEA' in df else 0
        macd_dif = df['MACD_DIF'].iloc[-1] if 'MACD_DIF' in df else 0
        
        prev_macd = df['MACD'].iloc[-2] if len(df) > 1 and 'MACD' in df else 0
        
        signal = 0
        # 零轴金叉
        if macd > 0 and prev_macd <= 0:
            signal = 1.0
        # 死叉
        elif macd < 0 and prev_macd >= 0:
            signal = -1.0
        # 金叉区域
        elif macd > 0:
            signal = 0.3
        # 死叉区域
        elif macd < 0:
            signal = -0.3
        
        return signal, {
            'macd': float(macd),
            'macd_signal': float(macd_signal_line),
            'macd_dif': float(macd_dif)
        }
    
    def _analyze_kdj_vectorized(self, df: pd.DataFrame) -> tuple:
        """KDJ分析"""
        k = df['KDJ_K'].iloc[-1] if 'KDJ_K' in df else 50
        d = df['KDJ_D'].iloc[-1] if 'KDJ_D' in df else 50
        j = df['KDJ_J'].iloc[-1] if 'KDJ_J' in df else 50
        
        prev_k = df['KDJ_K'].iloc[-2] if len(df) > 1 and 'KDJ_K' in df else 50
        prev_d = df['KDJ_D'].iloc[-2] if len(df) > 1 and 'KDJ_D' in df else 50
        
        signal = 0
        # 金叉（K上穿D）
        if prev_k <= prev_d and k > d:
            if k < 20:
                signal = 1.0  # 低位金叉
            else:
                signal = 0.7
        # 死叉（K下穿D）
        elif prev_k >= prev_d and k < d:
            if k > 80:
                signal = -1.0  # 高位死叉
            else:
                signal = -0.7
        # 超卖
        elif k < 20 and d < 20:
            signal = 0.5
        # 超买
        elif k > 80 and d > 80:
            signal = -0.5
        
        return signal, {
            'kdj_k': float(k),
            'kdj_d': float(d),
            'kdj_j': float(j)
        }
    
    def _analyze_atr_vectorized(self, df: pd.DataFrame) -> tuple:
        """ATR真实波幅分析"""
        atr = df['ATR'].iloc[-1] if 'ATR' in df else 0
        close = df['Close'].iloc[-1]
        
        # ATR占价格比例
        atr_ratio = atr / close if close > 0 else 0
        
        # 波动率评估
        signal = 0
        if atr_ratio > 0.05:  # 高波动
            signal = -0.3  # 风险增加
        elif atr_ratio < 0.01:  # 低波动
            signal = 0.2  # 可能突破
        
        return signal, {
            'atr': float(atr),
            'atr_ratio': float(atr_ratio)
        }
    
    def _analyze_cci_vectorized(self, df: pd.DataFrame) -> tuple:
        """CCI商品通道指标分析"""
        cci = df['CCI'].iloc[-1] if 'CCI' in df else 0
        
        signal = 0
        if cci < -200:
            signal = 1.0  # 严重超卖
        elif cci < -100:
            signal = 0.5  # 超卖
        elif cci > 200:
            signal = -1.0  # 严重超买
        elif cci > 100:
            signal = -0.5  # 超买
        
        return signal, {'cci': float(cci)}
    
    def _analyze_adx_vectorized(self, df: pd.DataFrame) -> tuple:
        """ADX趋向指数分析"""
        adx = df['ADX'].iloc[-1] if 'ADX' in df else 25
        
        signal = 0
        # ADX > 25 表示趋势明确
        if adx > 40:
            signal = 0.3  # 强趋势
        elif adx > 25:
            signal = 0.1  # 趋势形成
        elif adx < 20:
            signal = -0.1  # 无趋势
        
        return signal, {'adx': float(adx)}
    
    def _analyze_moving_averages(self, prices: pd.DataFrame) -> tuple:
        """均线分析"""
        close = prices['close']
        ma5 = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        current = close.iloc[-1]
        
        # 信号
        signal = 0
        if current > ma5 > ma10 > ma20:
            signal = 1.0  # 多头排列
        elif current < ma5 < ma10 < ma20:
            signal = -1.0  # 空头排列
        elif current > ma5:
            signal = 0.3
        elif current < ma5:
            signal = -0.3
        
        metrics = {
            'ma5': ma5,
            'ma10': ma10,
            'ma20': ma20,
            'price_vs_ma5': (current - ma5) / ma5,
            'price_vs_ma20': (current - ma20) / ma20
        }
        
        return signal, metrics
    
    def _analyze_rsi(self, prices: pd.DataFrame, period: int = 14) -> tuple:
        """RSI分析"""
        close = prices['close']
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        
        signal = 0
        if current_rsi < 30:
            signal = 1.0  # 超卖
        elif current_rsi > 70:
            signal = -1.0  # 超买
        elif current_rsi < 40:
            signal = 0.3
        elif current_rsi > 60:
            signal = -0.3
        
        return signal, {'rsi': current_rsi}
    
    def _analyze_bollinger(self, prices: pd.DataFrame, period: int = 20) -> tuple:
        """布林带分析"""
        close = prices['close']
        middle = close.rolling(period).mean()
        std = close.rolling(period).std()
        upper = middle + 2 * std
        lower = middle - 2 * std
        
        current = close.iloc[-1]
        upper_val = upper.iloc[-1]
        lower_val = lower.iloc[-1]
        middle_val = middle.iloc[-1]
        
        # 布林带位置
        bb_position = (current - lower_val) / (upper_val - lower_val)
        
        signal = 0
        if bb_position < 0.1:
            signal = 1.0  # 接近下轨
        elif bb_position > 0.9:
            signal = -1.0  # 接近上轨
        
        return signal, {
            'bb_upper': upper_val,
            'bb_middle': middle_val,
            'bb_lower': lower_val,
            'bb_position': bb_position
        }
    
    def _analyze_macd(self, prices: pd.DataFrame) -> tuple:
        """MACD分析"""
        close = prices['close']
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd = ema12 - ema26
        signal_line = macd.ewm(span=9).mean()
        histogram = macd - signal_line
        
        current_hist = histogram.iloc[-1]
        prev_hist = histogram.iloc[-2] if len(histogram) > 1 else current_hist
        
        signal = 0
        if current_hist > 0 and prev_hist <= 0:
            signal = 1.0  # 金叉
        elif current_hist < 0 and prev_hist >= 0:
            signal = -1.0  # 死叉
        elif current_hist > 0:
            signal = 0.3
        else:
            signal = -0.3
        
        return signal, {
            'macd': macd.iloc[-1],
            'macd_signal': signal_line.iloc[-1],
            'macd_histogram': current_hist
        }
    
    def _analyze_chip_distribution(self, data: pd.DataFrame) -> tuple:
        """筹码分布分析
        
        分析内容：
        - 筹码集中度（成本分布）
        - 获利盘比例
        - 套牢盘比例
        - 筹码峰位置
        
        算法：
        1. 使用成交量加权计算筹码分布
        2. 识别筹码密集区
        3. 计算当前价格相对于筹码峰的位置
        """
        try:
            close = data['close'] if 'close' in data.columns else data['Close']
            volume = data['volume'] if 'volume' in data.columns else data.get('Volume', data.get('volume', None))
            
            if volume is None:
                return 0, {'chip_error': '无成交量数据'}
            
            current_price = close.iloc[-1]
            
            # 1. 计算筹码分布（成交量加权成本分布）
            # 使用最近60天的数据
            lookback = min(60, len(data) - 1)
            prices_slice = close.iloc[-lookback:].values
            volumes_slice = volume.iloc[-lookback:].values
            
            # 价格区间
            price_min = prices_slice.min()
            price_max = prices_slice.max()
            price_range = price_max - price_min
            
            if price_range == 0:
                return 0, {'chip_concentration': 1.0}
            
            # 将价格分成20个区间
            bins = 20
            bin_width = price_range / bins
            chip_distribution = np.zeros(bins)
            
            for i in range(len(prices_slice)):
                price = prices_slice[i]
                vol = volumes_slice[i]
                bin_idx = int((price - price_min) / bin_width)
                bin_idx = min(bins - 1, max(0, bin_idx))
                chip_distribution[bin_idx] += vol
            
            # 归一化
            total_vol = chip_distribution.sum()
            if total_vol > 0:
                chip_distribution = chip_distribution / total_vol
            
            # 2. 计算筹码集中度（CR指标）
            # 找到筹码峰值区间
            peak_idx = np.argmax(chip_distribution)
            peak_price = price_min + (peak_idx + 0.5) * bin_width
            
            # 计算峰值区间的筹码集中度
            concentration = chip_distribution[peak_idx]
            
            # 3. 计算当前价格对应的筹码位置
            current_bin = int((current_price - price_min) / bin_width)
            current_bin = min(bins - 1, max(0, current_bin))
            
            # 4. 计算获利盘比例（价格低于当前价的筹码）
            profit_chips = chip_distribution[:current_bin + 1].sum()
            
            # 5. 计算套牢盘比例（价格高于当前价的筹码）
            loss_chips = chip_distribution[current_bin:].sum()
            
            # 6. 计算筹码分布离散度（标准差）
            chip_std = np.std(chip_distribution)
            
            # 7. 计算筹码峰偏离度（当前价与筹码峰的距离）
            peak_deviation = (current_price - peak_price) / current_price if current_price > 0 else 0
            
            # 生成信号
            signal = 0
            
            # 获利盘比例分析
            if profit_chips < 0.2:  # 大部分筹码在高位，当前低位
                signal += 0.3  # 可能反弹
            elif profit_chips > 0.8:  # 大部分筹码在低位，当前高位
                signal -= 0.3  # 可能回调
            
            # 筹码集中度分析
            if concentration > 0.3:  # 筹码高度集中
                if peak_deviation < 0:  # 价格在筹码峰下方
                    signal += 0.4  # 支撑强
                elif peak_deviation > 0.1:  # 价格在筹码峰上方较远
                    signal -= 0.3  # 可能回调
            
            # 筹码离散度分析
            if chip_std < 0.05:  # 筹码高度集中
                signal += 0.2
            
            metrics = {
                'chip_concentration': float(concentration),
                'chip_peak_price': float(peak_price),
                'profit_chips_ratio': float(profit_chips),
                'loss_chips_ratio': float(loss_chips),
                'chip_std': float(chip_std),
                'peak_deviation': float(peak_deviation),
                'current_bin': int(current_bin),
                'peak_bin': int(peak_idx)
            }
            
            return signal, metrics
            
        except Exception as e:
            return 0, {'chip_error': str(e)}
    
    def _identify_chip_pattern(self, data: pd.DataFrame) -> str:
        """识别筹码形态
        
        返回：
        - "低位单峰": 底部筹码集中，看涨
        - "高位单峰": 顶部筹码集中，风险
        - "双峰": 多空分歧
        - "发散": 筹码分散
        - "多峰": 复杂形态
        """
        try:
            close = data['close'] if 'close' in data.columns else data['Close']
            volume = data['volume'] if 'volume' in data.columns else data.get('Volume', data.get('volume', None))
            
            if volume is None:
                return "未知"
            
            current_price = close.iloc[-1]
            
            # 使用最近60天数据
            lookback = min(60, len(data) - 1)
            prices_slice = close.iloc[-lookback:].values
            volumes_slice = volume.iloc[-lookback:].values
            
            price_min = prices_slice.min()
            price_max = prices_slice.max()
            price_range = price_max - price_min
            
            if price_range == 0:
                return "未知"
            
            # 分成20个区间
            bins = 20
            bin_width = price_range / bins
            chip_distribution = np.zeros(bins)
            
            for i in range(len(prices_slice)):
                price = prices_slice[i]
                vol = volumes_slice[i]
                bin_idx = int((price - price_min) / bin_width)
                bin_idx = min(bins - 1, max(0, bin_idx))
                chip_distribution[bin_idx] += vol
            
            total_vol = chip_distribution.sum()
            if total_vol > 0:
                chip_distribution = chip_distribution / total_vol
            
            # 寻找峰值（局部最大值）
            peaks = []
            for i in range(1, bins - 1):
                if chip_distribution[i] > chip_distribution[i-1] and chip_distribution[i] > chip_distribution[i+1]:
                    if chip_distribution[i] > 0.05:  # 峰值阈值
                        peaks.append((i, chip_distribution[i]))
            
            # 当前价格位置
            current_bin = int((current_price - price_min) / bin_width)
            current_bin = min(bins - 1, max(0, current_bin))
            
            # 判断形态
            if len(peaks) == 0:
                return "发散"
            
            if len(peaks) == 1:
                peak_bin = peaks[0][0]
                peak_price = price_min + (peak_bin + 0.5) * bin_width
                
                # 判断是低位还是高位
                relative_position = peak_bin / bins
                
                if relative_position < 0.3:  # 低位单峰
                    return "低位单峰"
                elif relative_position > 0.7:  # 高位单峰
                    return "高位单峰"
                else:
                    # 根据当前价与峰价关系判断
                    if current_price > peak_price * 1.1:
                        return "低位单峰"  # 价格已突破，原低位峰形成支撑
                    elif current_price < peak_price * 0.9:
                        return "高位单峰"  # 价格跌破，原高位峰形成压力
                    else:
                        return "单峰整理"
            
            elif len(peaks) == 2:
                # 双峰形态
                peak1_bin, peak1_val = peaks[0]
                peak2_bin, peak2_val = peaks[1]
                
                # 判断双峰距离
                distance = abs(peak2_bin - peak1_bin)
                
                if distance < 3:  # 双峰距离太近，视为单峰
                    avg_bin = (peak1_bin + peak2_bin) / 2
                    if avg_bin / bins < 0.3:
                        return "低位单峰"
                    elif avg_bin / bins > 0.7:
                        return "高位单峰"
                    else:
                        return "单峰整理"
                else:
                    return "双峰"
            
            else:
                # 多峰形态
                return "多峰"
                
        except Exception as e:
            return "未知"
    
    def _detect_regime(self, prices: pd.DataFrame) -> tuple:
        """市场区制识别"""
        close = prices['close']
        returns = close.pct_change()
        
        # 使用20日和60日均线判断趋势
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        
        current_price = close.iloc[-1]
        current_ma20 = ma20.iloc[-1]
        current_ma60 = ma60.iloc[-1] if len(ma60.dropna()) > 0 else current_ma20
        
        # 波动率
        volatility = returns.rolling(20).std().iloc[-1] * np.sqrt(252)
        
        # 判断区制
        if current_price > current_ma20 > current_ma60 and volatility < 0.3:
            regime = MarketRegime.BULL
        elif current_price < current_ma20 < current_ma60:
            regime = MarketRegime.BEAR
        elif volatility > 0.4:
            regime = MarketRegime.TRANSITION
        else:
            regime = MarketRegime.SIDEWAYS
        
        return regime, {
            'volatility': volatility,
            'ma20_slope': (ma20.iloc[-1] - ma20.iloc[-5]) / ma20.iloc[-5] if len(ma20) > 5 else 0
        }
    
    def _generate_reasoning(self, metrics: dict, regime: MarketRegime) -> str:
        """生成分析理由"""
        reasons = []
        
        if 'price_vs_ma5' in metrics:
            if metrics['price_vs_ma5'] > 0:
                reasons.append(f"股价高于MA5 {metrics['price_vs_ma5']*100:.1f}%")
            else:
                reasons.append(f"股价低于MA5 {abs(metrics['price_vs_ma5'])*100:.1f}%")
        
        if 'rsi' in metrics:
            rsi = metrics['rsi']
            if rsi < 30:
                reasons.append(f"RSI={rsi:.1f}超卖")
            elif rsi > 70:
                reasons.append(f"RSI={rsi:.1f}超买")
        
        # 筹码分析理由
        if 'chip_pattern' in metrics:
            chip_pattern = metrics['chip_pattern']
            chip_desc = {
                '低位单峰': '底部筹码集中看涨',
                '高位单峰': '顶部筹码集中风险',
                '双峰': '多空分歧',
                '发散': '筹码分散',
                '单峰整理': '筹码整理中',
                '多峰': '筹码结构复杂'
            }
            reasons.append(f"筹码形态:{chip_desc.get(chip_pattern, chip_pattern)}")
        
        if 'profit_chips_ratio' in metrics:
            profit_ratio = metrics['profit_chips_ratio']
            if profit_ratio > 0.7:
                reasons.append(f"获利盘{profit_ratio:.0%}较高")
            elif profit_ratio < 0.3:
                reasons.append(f"获利盘{profit_ratio:.0%}较低")
        
        if 'chip_concentration' in metrics and metrics['chip_concentration'] > 0.25:
            reasons.append(f"筹码集中度{metrics['chip_concentration']:.0%}")
        
        reasons.append(f"市场区制: {regime.value}")
        
        return "; ".join(reasons)


class FundamentalsAnalyst(BaseStockAgent):
    """基本面分析Agent - 财务评分"""
    
    def __init__(self):
        super().__init__(
            name="FundamentalsAnalyst",
            description="基本面分析Agent，负责财务指标评分、估值判断",
            weight=1.0
        )
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """基本面分析"""
        fundamentals = data.get('fundamentals', {})
        
        if not fundamentals:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="无基本面数据"
            )
        
        metrics = {}
        scores = []
        
        # 1. ROE分析
        roe = fundamentals.get('roe', 0)
        roe_score = self._score_roe(roe)
        scores.append(roe_score)
        metrics['roe'] = roe
        metrics['roe_score'] = roe_score
        
        # 2. 净利润增长率
        profit_growth = fundamentals.get('profit_growth', 0)
        growth_score = self._score_growth(profit_growth)
        scores.append(growth_score)
        metrics['profit_growth'] = profit_growth
        metrics['growth_score'] = growth_score
        
        # 3. 资产负债率
        debt_ratio = fundamentals.get('debt_ratio', 50)
        debt_score = self._score_debt_ratio(debt_ratio)
        scores.append(debt_score)
        metrics['debt_ratio'] = debt_ratio
        metrics['debt_score'] = debt_score
        
        # 4. 毛利率
        gross_margin = fundamentals.get('gross_margin', 0)
        margin_score = self._score_margin(gross_margin)
        scores.append(margin_score)
        metrics['gross_margin'] = gross_margin
        metrics['margin_score'] = margin_score
        
        # 综合评分
        avg_score = np.mean(scores)
        total_score = sum(scores)
        
        if total_score >= 3:
            signal = "bullish"
        elif total_score <= -1:
            signal = "bearish"
        else:
            signal = "neutral"
        
        confidence = min(1.0, abs(total_score) / 4)
        
        return AgentSignal(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            reasoning=self._generate_reasoning(metrics),
            metrics=metrics
        )
    
    def _score_roe(self, roe: float) -> float:
        """ROE评分"""
        if roe >= 20:
            return 1.0
        elif roe >= 15:
            return 0.5
        elif roe >= 10:
            return 0.0
        elif roe >= 5:
            return -0.5
        else:
            return -1.0
    
    def _score_growth(self, growth: float) -> float:
        """增长评分"""
        if growth >= 30:
            return 1.0
        elif growth >= 15:
            return 0.5
        elif growth >= 0:
            return 0.0
        elif growth >= -10:
            return -0.5
        else:
            return -1.0
    
    def _score_debt_ratio(self, ratio: float) -> float:
        """负债率评分"""
        if ratio <= 30:
            return 1.0
        elif ratio <= 50:
            return 0.5
        elif ratio <= 60:
            return 0.0
        elif ratio <= 70:
            return -0.5
        else:
            return -1.0
    
    def _score_margin(self, margin: float) -> float:
        """毛利率评分"""
        if margin >= 40:
            return 1.0
        elif margin >= 30:
            return 0.5
        elif margin >= 20:
            return 0.0
        elif margin >= 10:
            return -0.5
        else:
            return -1.0
    
    def _generate_reasoning(self, metrics: dict) -> str:
        reasons = []
        
        if 'roe' in metrics:
            reasons.append(f"ROE={metrics['roe']:.1f}%")
        if 'profit_growth' in metrics:
            reasons.append(f"利润增长={metrics['profit_growth']:.1f}%")
        if 'debt_ratio' in metrics:
            reasons.append(f"负债率={metrics['debt_ratio']:.1f}%")
        if 'gross_margin' in metrics:
            reasons.append(f"毛利率={metrics['gross_margin']:.1f}%")
        
        return "; ".join(reasons)


class SentimentAnalyst(BaseStockAgent):
    """情感分析Agent - 新闻情感"""
    
    def __init__(self):
        super().__init__(
            name="SentimentAnalyst",
            description="情感分析Agent，负责新闻情感、社交媒体情绪分析",
            weight=0.8
        )
        self.positive_keywords = ['利好', '增长', '突破', '创新高', '盈利', '订单', '合作', '中标']
        self.negative_keywords = ['利空', '亏损', '下滑', '违约', '诉讼', '调查', '处罚', '减持']
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """情感分析"""
        news = data.get('news', [])
        
        if not news:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="无新闻数据"
            )
        
        metrics = {
            'total_news': len(news),
            'positive_count': 0,
            'negative_count': 0,
            'neutral_count': 0
        }
        
        sentiment_scores = []
        
        for item in news:
            title = item.get('title', '') + ' ' + item.get('content', '')
            score = self._analyze_text(title)
            sentiment_scores.append(score)
            
            if score > 0.2:
                metrics['positive_count'] += 1
            elif score < -0.2:
                metrics['negative_count'] += 1
            else:
                metrics['neutral_count'] += 1
        
        avg_sentiment = np.mean(sentiment_scores) if sentiment_scores else 0
        metrics['avg_sentiment'] = avg_sentiment
        
        if avg_sentiment > 0.2:
            signal = "bullish"
        elif avg_sentiment < -0.2:
            signal = "bearish"
        else:
            signal = "neutral"
        
        confidence = min(1.0, abs(avg_sentiment) * 2)
        
        return AgentSignal(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            reasoning=self._generate_reasoning(metrics),
            metrics=metrics
        )
    
    def _analyze_text(self, text: str) -> float:
        """分析文本情感"""
        score = 0
        text = text.lower()
        
        for keyword in self.positive_keywords:
            if keyword in text:
                score += 1
        
        for keyword in self.negative_keywords:
            if keyword in text:
                score -= 1
        
        # 归一化
        if score > 0:
            return min(1.0, score / 3)
        elif score < 0:
            return max(-1.0, score / 3)
        else:
            return 0.0
    
    def _generate_reasoning(self, metrics: dict) -> str:
        return (f"新闻总数:{metrics['total_news']}, "
                f"正面:{metrics['positive_count']}, "
                f"负面:{metrics['negative_count']}, "
                f"平均情感:{metrics['avg_sentiment']:.2f}")


class ValuationAnalyst(BaseStockAgent):
    """估值分析Agent - PE/PB估值"""
    
    def __init__(self):
        super().__init__(
            name="ValuationAnalyst",
            description="估值分析Agent，负责PE/PB/PEG估值分析",
            weight=1.1
        )
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """估值分析"""
        fundamentals = data.get('fundamentals', {})
        prices = data.get('prices')
        
        if not fundamentals:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="无估值数据"
            )
        
        metrics = {}
        scores = []
        
        # PE分析
        pe = fundamentals.get('pe', 0)
        pe_score = self._score_pe(pe)
        scores.append(pe_score)
        metrics['pe'] = pe
        metrics['pe_score'] = pe_score
        
        # PB分析
        pb = fundamentals.get('pb', 0)
        pb_score = self._score_pb(pb)
        scores.append(pb_score)
        metrics['pb'] = pb
        metrics['pb_score'] = pb_score
        
        # PEG分析（如果有增长率）
        growth = fundamentals.get('profit_growth', 10)
        if pe > 0 and growth > 0:
            peg = pe / growth
            peg_score = self._score_peg(peg)
            scores.append(peg_score)
            metrics['peg'] = peg
            metrics['peg_score'] = peg_score
        
        # 综合评分
        total_score = sum(scores)
        
        if total_score >= 2:
            signal = "bullish"
        elif total_score <= -1:
            signal = "bearish"
        else:
            signal = "neutral"
        
        confidence = min(1.0, abs(total_score) / 3)
        
        return AgentSignal(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            reasoning=self._generate_reasoning(metrics),
            metrics=metrics
        )
    
    def _score_pe(self, pe: float) -> float:
        """PE评分"""
        if pe <= 0:
            return -1.0  # 亏损股
        elif pe <= 15:
            return 1.0
        elif pe <= 25:
            return 0.5
        elif pe <= 35:
            return 0.0
        elif pe <= 50:
            return -0.5
        else:
            return -1.0
    
    def _score_pb(self, pb: float) -> float:
        """PB评分"""
        if pb <= 0.8:
            return 1.0  # 破净
        elif pb <= 1.5:
            return 0.5
        elif pb <= 3:
            return 0.0
        elif pb <= 5:
            return -0.5
        else:
            return -1.0
    
    def _score_peg(self, peg: float) -> float:
        """PEG评分"""
        if peg <= 0.5:
            return 1.0
        elif peg <= 1:
            return 0.5
        elif peg <= 1.5:
            return 0.0
        elif peg <= 2:
            return -0.5
        else:
            return -1.0
    
    def _generate_reasoning(self, metrics: dict) -> str:
        reasons = []
        
        if 'pe' in metrics:
            reasons.append(f"PE={metrics['pe']:.1f}")
        if 'pb' in metrics:
            reasons.append(f"PB={metrics['pb']:.2f}")
        if 'peg' in metrics:
            reasons.append(f"PEG={metrics['peg']:.2f}")
        
        return "; ".join(reasons)


class AIModelAnalyst(BaseStockAgent):
    """AI模型分析Agent - CatBoost预测"""
    
    def __init__(self):
        super().__init__(
            name="AIModelAnalyst",
            description="AI模型分析Agent，整合CatBoost模型预测能力",
            weight=1.3
        )
        self.model = None
        self.feature_cols = None
        self._load_model()
    
    def _load_model(self):
        """加载模型"""
        try:
            from catboost import CatBoostClassifier
            
            # 尝试加载多个模型
            model_paths = [
                os.path.join(FORTUNE_PATH, 'models', 'mainboard_5pct_final_model.cbm'),
                os.path.join(FORTUNE_PATH, 'models', 'a_stock_model_latest.cbm'),
                os.path.join(FORTUNE_PATH, 'a_stock_model.cbm'),
            ]
            
            for path in model_paths:
                if os.path.exists(path):
                    self.model = CatBoostClassifier()
                    self.model.load_model(path)
                    print(f"AIModelAnalyst: 成功加载模型 {path}")
                    break
            
            if self.model is None:
                print("AIModelAnalyst: 未找到可用模型，将使用规则模式")
        except Exception as e:
            print(f"AIModelAnalyst: 模型加载失败 {e}")
            self.model = None
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """AI模型预测"""
        prices = data.get('prices')
        
        if prices is None or len(prices) < 60:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="数据不足，无法进行AI预测"
            )
        
        metrics = {}
        
        # 如果有模型，使用模型预测
        if self.model is not None:
            try:
                features = self._calculate_features(prices)
                if features is not None and len(features) > 0:
                    proba = self.model.predict_proba([features])[0]
                    confidence = proba[1]  # 上涨概率
                    prediction = 1 if confidence > 0.5 else 0
                    
                    metrics['model_confidence'] = confidence
                    metrics['model_prediction'] = prediction
                    
                    if confidence > 0.7:
                        signal = "bullish"
                    elif confidence < 0.3:
                        signal = "bearish"
                    else:
                        signal = "neutral"
                    
                    return AgentSignal(
                        agent_name=self.name,
                        signal=signal,
                        confidence=abs(confidence - 0.5) * 2,  # 归一化到0-1
                        reasoning=f"AI模型预测上涨概率:{confidence:.2%}",
                        metrics=metrics
                    )
            except Exception as e:
                print(f"AIModelAnalyst: 预测失败 {e}")
        
        # 如果没有模型或预测失败，使用规则模式
        return self._rule_based_analysis(prices)
    
    def _calculate_features(self, prices: pd.DataFrame) -> Optional[List[float]]:
        """计算模型特征"""
        try:
            close = prices['close']
            features = []
            
            # 波动率
            returns = close.pct_change()
            volatility_10d = returns.rolling(10).std().iloc[-1]
            features.append(volatility_10d)
            
            # 价格相对MA位置
            ma5 = close.rolling(5).mean().iloc[-1]
            ma10 = close.rolling(10).mean().iloc[-1]
            price_vs_ma5 = (close.iloc[-1] - ma5) / ma5
            price_vs_ma10 = (close.iloc[-1] - ma10) / ma10
            features.extend([price_vs_ma5, price_vs_ma10])
            
            # 价格区间位置
            high_20 = prices['high'].rolling(20).max().iloc[-1]
            low_20 = prices['low'].rolling(20).min().iloc[-1]
            price_range = (close.iloc[-1] - low_20) / (high_20 - low_20) if high_20 != low_20 else 0.5
            features.append(price_range)
            
            # 动量
            momentum_5 = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6]
            features.append(momentum_5)
            
            # RSI
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            features.append(rsi.iloc[-1] / 100)  # 归一化
            
            # 成交量比
            vol = prices['volume']
            vol_ma5 = vol.rolling(5).mean().iloc[-1]
            vol_ratio = vol.iloc[-1] / vol_ma5 if vol_ma5 > 0 else 1
            features.append(vol_ratio)
            
            # 填充缺失值
            features = [0 if np.isnan(f) else f for f in features]
            
            return features
        except Exception as e:
            print(f"特征计算失败: {e}")
            return None
    
    def _rule_based_analysis(self, prices: pd.DataFrame) -> AgentSignal:
        """规则分析（备用）"""
        close = prices['close']
        metrics = {}
        
        # 趋势
        ma5 = close.rolling(5).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        trend = 1 if ma5 > ma20 else -1 if ma5 < ma20 else 0
        
        # 动量
        momentum = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5]
        
        # 综合判断
        score = trend * 0.5 + np.sign(momentum) * 0.5
        
        if score > 0.3:
            signal = "bullish"
        elif score < -0.3:
            signal = "bearish"
        else:
            signal = "neutral"
        
        metrics['trend'] = trend
        metrics['momentum'] = momentum
        
        return AgentSignal(
            agent_name=self.name,
            signal=signal,
            confidence=abs(score),
            reasoning="规则模式分析",
            metrics=metrics
        )


class MacroAnalyst(BaseStockAgent):
    """宏观分析Agent - 宏观环境+主力资金+北向资金"""
    
    def __init__(self):
        super().__init__(
            name="MacroAnalyst",
            description="宏观分析Agent，负责宏观经济、政策环境、主力资金、北向资金分析",
            weight=0.9
        )
        # 行业周期映射
        self.sector_cycles = {
            '科技': 'growth',
            '消费': 'stable',
            '金融': 'cyclical',
            '医药': 'defensive',
            '能源': 'cyclical',
            '材料': 'cyclical'
        }
        # 主力资金阈值（亿）
        self.strong_inflow_threshold = 1.0  # 强流入阈值
        self.strong_outflow_threshold = -1.0  # 强流出阈值
        # 北向资金阈值（亿）
        self.north_inflow_threshold = 50.0  # 北向强流入阈值
        self.north_outflow_threshold = -50.0  # 北向强流出阈值
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """宏观分析"""
        market = data.get('market', {})
        fundamentals = data.get('fundamentals', {})
        
        metrics = {}
        scores = []
        
        # 1. 市场整体趋势
        market_trend = market.get('market_trend', 0)  # -1到1
        scores.append(market_trend * 0.8)
        metrics['market_trend'] = market_trend
        
        # 2. 板块热度
        sector = fundamentals.get('sector', '')
        sector_heat = market.get('sector_heat', {}).get(sector, 0.5)
        scores.append((sector_heat - 0.5) * 2)
        metrics['sector_heat'] = sector_heat
        
        # 3. 资金流向
        fund_flow = market.get('fund_flow', 0)  # 北向资金等
        scores.append(np.sign(fund_flow) * min(1, abs(fund_flow) / 100))
        metrics['fund_flow'] = fund_flow
        
        # 4. 主力资金分析（新增）
        fund_analysis = self._analyze_main_fund_flow(data, market)
        if fund_analysis:
            metrics['main_fund_flow'] = fund_analysis.get('net_inflow', 0)
            metrics['main_fund_trend'] = fund_analysis.get('trend', 'neutral')
            
            # 主力资金评分
            main_net = fund_analysis.get('net_inflow', 0) / 100000000  # 转换为亿
            if main_net > self.strong_inflow_threshold:
                scores.append(1.0)  # 强流入
            elif main_net > 0:
                scores.append(0.5)  # 流入
            elif main_net < self.strong_outflow_threshold:
                scores.append(-1.0)  # 强流出
            elif main_net < 0:
                scores.append(-0.5)  # 流出
            else:
                scores.append(0)
        
        # 5. 板块资金流向（新增）
        if sector:
            sector_flow = self._analyze_sector_fund_flow(sector, market)
            if sector_flow:
                metrics['sector_fund_rank'] = sector_flow.get('rank', 0)
                metrics['sector_net_inflow'] = sector_flow.get('net_inflow', 0)
                
                # 板块资金评分
                sector_rank = sector_flow.get('rank', 0)
                if sector_rank > 0 and sector_rank <= 10:
                    scores.append(0.8)  # 热门板块
                elif sector_rank > 10 and sector_rank <= 30:
                    scores.append(0.3)  # 中等板块
                elif sector_rank < 0:
                    scores.append(-0.3)  # 冷门板块
        
        # 6. 北向资金分析（新增）
        north_analysis = self._analyze_north_fund(market)
        if north_analysis:
            metrics['north_fund_flow'] = north_analysis.get('net_inflow', 0)
            metrics['north_fund_trend'] = north_analysis.get('trend', 'neutral')
            metrics['north_continuous_days'] = north_analysis.get('continuous_days', 0)
            
            # 北向资金评分
            north_net = north_analysis.get('net_inflow', 0)
            if north_net > self.north_inflow_threshold:
                scores.append(1.0)  # 强流入
            elif north_net > 0:
                scores.append(0.5)  # 流入
            elif north_net < self.north_outflow_threshold:
                scores.append(-1.0)  # 强流出
            elif north_net < 0:
                scores.append(-0.5)  # 流出
            
            # 连续流入/流出加成
            continuous_days = north_analysis.get('continuous_days', 0)
            if continuous_days >= 3:
                # 连续流入看涨
                if north_analysis.get('trend') == 'inflow':
                    scores.append(0.3)
                # 连续流出看跌
                elif north_analysis.get('trend') == 'outflow':
                    scores.append(-0.3)
        
        # 7. 主力资金追踪（新增）
        tracking_result = self._track_main_fund(data, market)
        if tracking_result:
            metrics['main_fund_signal'] = tracking_result.get('signal', 'neutral')
            metrics['main_fund_accumulation'] = tracking_result.get('accumulation', 0)
            metrics['main_fund_actions'] = tracking_result.get('recent_actions', [])
            
            # 主力追踪评分
            signal_type = tracking_result.get('signal', 'neutral')
            if signal_type == 'strong_buy':
                scores.append(1.0)
            elif signal_type == 'buy':
                scores.append(0.5)
            elif signal_type == 'sell':
                scores.append(-0.5)
            elif signal_type == 'strong_sell':
                scores.append(-1.0)
        
        # 8. 利率环境
        interest_rate = market.get('interest_rate', 3.0)
        rate_score = -0.3 if interest_rate > 5 else 0.3 if interest_rate < 2 else 0
        scores.append(rate_score)
        metrics['interest_rate'] = interest_rate
        
        # 综合评分
        total_score = sum(scores) / len(scores) if scores else 0
        
        if total_score > 0.5:
            signal = "bullish"
        elif total_score < -0.5:
            signal = "bearish"
        else:
            signal = "neutral"
        
        confidence = min(1.0, abs(total_score))
        
        return AgentSignal(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            reasoning=self._generate_reasoning(metrics),
            metrics=metrics
        )
    
    def _analyze_main_fund_flow(self, data: Dict[str, Any], market: Dict) -> Dict[str, Any]:
        """分析主力资金流向"""
        result = {
            'net_inflow': 0,
            'trend': 'neutral',
            'signal': 'neutral'
        }
        
        try:
            # 尝试从stock_data_hub获取
            from .stock_data_hub import StockDataHub
            hub = StockDataHub()
            
            # 获取个股资金流向
            stock_code = data.get('stock_code')
            if stock_code:
                fund_data = hub.get_fund_flow(stock_code)
                if fund_data:
                    result['net_inflow'] = fund_data.get('net_inflow', 0)
                    result['main_inflow'] = fund_data.get('main_inflow', 0)
            
            # 分析趋势
            net = result['net_inflow']
            if net > 0:
                result['trend'] = 'inflow'
                result['signal'] = 'bullish'
            elif net < 0:
                result['trend'] = 'outflow'
                result['signal'] = 'bearish'
                
        except Exception as e:
            # 回退到市场数据中的资金流向
            result['net_inflow'] = market.get('main_fund_flow', 0)
            result['trend'] = 'inflow' if result['net_inflow'] > 0 else 'outflow' if result['net_inflow'] < 0 else 'neutral'
        
        return result
    
    def _analyze_sector_fund_flow(self, sector: str, market: Dict) -> Dict[str, Any]:
        """分析板块资金流向"""
        result = {
            'rank': 0,
            'net_inflow': 0,
            'hot': False
        }
        
        try:
            from .stock_data_hub import StockDataHub
            hub = StockDataHub()
            
            sector_flow = hub.get_sector_fund_flow(sector)
            if sector_flow:
                result.update(sector_flow)
        except:
            # 回退到市场数据
            sector_flows = market.get('sector_flows', {})
            if sector in sector_flows:
                result['net_inflow'] = sector_flows[sector].get('net_inflow', 0)
                result['rank'] = sector_flows[sector].get('rank', 0)
        
        return result
    
    def _analyze_north_fund(self, market: Dict) -> Dict[str, Any]:
        """北向资金分析
        
        分析内容：
        - 北向资金净流入/流出
        - 连续流入/流出天数
        - 历史对比
        """
        result = {
            'net_inflow': 0,
            'trend': 'neutral',
            'continuous_days': 0,
            'signal': 'neutral'
        }
        
        try:
            # 尝试从stock_data_hub获取北向资金数据
            from .stock_data_hub import StockDataHub
            hub = StockDataHub()
            
            north_data = hub.get_north_fund_flow()
            if north_data:
                result['net_inflow'] = north_data.get('net_inflow', 0)
                result['continuous_days'] = north_data.get('continuous_days', 0)
                result['history_avg'] = north_data.get('history_avg', 0)
            
        except Exception as e:
            # 回退到市场数据
            result['net_inflow'] = market.get('north_fund_flow', 0)
            result['continuous_days'] = market.get('north_continuous_days', 0)
        
        # 分析趋势
        net = result['net_inflow']
        if net > 0:
            result['trend'] = 'inflow'
            if net > self.north_inflow_threshold:
                result['signal'] = 'strong_bullish'
            else:
                result['signal'] = 'bullish'
        elif net < 0:
            result['trend'] = 'outflow'
            if net < self.north_outflow_threshold:
                result['signal'] = 'strong_bearish'
            else:
                result['signal'] = 'bearish'
        
        return result
    
    def _track_main_fund(self, data: Dict[str, Any], market: Dict) -> Dict[str, Any]:
        """主力资金追踪
        
        追踪内容：
        - 主力动向信号
        - 近期主力操作
        - 累计建仓/减仓
        """
        result = {
            'signal': 'neutral',
            'accumulation': 0,
            'recent_actions': []
        }
        
        try:
            # 获取个股资金流向
            stock_code = data.get('stock_code')
            
            if not stock_code:
                return result
            
            from .stock_data_hub import StockDataHub
            hub = StockDataHub()
            
            # 获取主力资金历史
            fund_history = hub.get_fund_flow_history(stock_code, days=10)
            
            if fund_history and len(fund_history) > 0:
                total_inflow = 0
                actions = []
                
                for item in fund_history:
                    net = item.get('net_inflow', 0)
                    main_net = item.get('main_inflow', 0) - item.get('main_outflow', 0)
                    total_inflow += main_net
                    
                    # 记录大额操作
                    if abs(main_net) > 50000000:  # 5000万
                        actions.append({
                            'date': item.get('date', ''),
                            'amount': main_net,
                            'type': 'inflow' if main_net > 0 else 'outflow'
                        })
                
                result['accumulation'] = total_inflow
                result['recent_actions'] = actions[-5:]  # 最近5次大额操作
                
                # 生成信号
                if total_inflow > 100000000:  # 累计流入超过1亿
                    result['signal'] = 'strong_buy'
                elif total_inflow > 0:
                    result['signal'] = 'buy'
                elif total_inflow < -100000000:
                    result['signal'] = 'strong_sell'
                elif total_inflow < 0:
                    result['signal'] = 'sell'
            
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    def _generate_reasoning(self, metrics: dict) -> str:
        reasons = []
        
        if 'market_trend' in metrics:
            trend = metrics['market_trend']
            reasons.append(f"市场趋势:{'上涨' if trend > 0 else '下跌'}")
        
        if 'sector_heat' in metrics:
            heat = metrics['sector_heat']
            reasons.append(f"板块热度:{heat:.0%}")
        
        if 'fund_flow' in metrics:
            flow = metrics['fund_flow']
            reasons.append(f"资金流向:{flow:+.0f}亿")
        
        # 主力资金说明
        if 'main_fund_trend' in metrics:
            main_trend = metrics['main_fund_trend']
            main_net = metrics.get('main_fund_flow', 0) / 100000000
            reasons.append(f"主力资金:{main_trend}({main_net:+.2f}亿)")
        
        # 北向资金说明（新增）
        if 'north_fund_trend' in metrics:
            north_trend = metrics['north_fund_trend']
            north_net = metrics.get('north_fund_flow', 0)
            north_days = metrics.get('north_continuous_days', 0)
            if north_days > 0:
                reasons.append(f"北向资金:{north_trend}{north_days}天({north_net:+.0f}亿)")
            else:
                reasons.append(f"北向资金:{north_trend}({north_net:+.0f}亿)")
        
        # 主力追踪说明（新增）
        if 'main_fund_signal' in metrics:
            signal = metrics['main_fund_signal']
            accumulation = metrics.get('main_fund_accumulation', 0) / 100000000
            signal_desc = {
                'strong_buy': '强买入',
                'buy': '买入',
                'sell': '卖出',
                'strong_sell': '强卖出',
                'neutral': '观望'
            }
            reasons.append(f"主力追踪:{signal_desc.get(signal, signal)}(累计{accumulation:+.2f}亿)")
        
        if 'sector_fund_rank' in metrics and metrics['sector_fund_rank'] > 0:
            reasons.append(f"板块资金排名:{metrics['sector_fund_rank']}")
        
        return "; ".join(reasons)


# ==================== 6个决策/风控/执行Agent ====================

class SignalAggregator(BaseStockAgent):
    """信号聚合Agent - 综合各Agent信号"""
    
    def __init__(self):
        super().__init__(
            name="SignalAggregator",
            description="信号聚合Agent，负责综合各分析Agent的信号",
            weight=1.0
        )
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """聚合信号"""
        agent_signals = data.get('agent_signals', [])
        
        if not agent_signals:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="无Agent信号"
            )
        
        metrics = {}
        
        # 加权平均
        total_weight = 0
        weighted_score = 0
        
        for sig in agent_signals:
            if isinstance(sig, AgentSignal):
                weight = data.get('weights', {}).get(sig.agent_name, 1.0)
                signal_value = 1 if sig.signal == "bullish" else -1 if sig.signal == "bearish" else 0
                
                weighted_score += signal_value * sig.confidence * weight
                total_weight += weight
                
                metrics[sig.agent_name] = {
                    'signal': sig.signal,
                    'confidence': sig.confidence,
                    'weight': weight
                }
        
        if total_weight > 0:
            weighted_score /= total_weight
        
        metrics['weighted_score'] = weighted_score
        
        # 确定最终信号
        if weighted_score > 0.3:
            signal = "bullish"
        elif weighted_score < -0.3:
            signal = "bearish"
        else:
            signal = "neutral"
        
        confidence = min(1.0, abs(weighted_score) * 1.5)
        
        return AgentSignal(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            reasoning=f"综合{len(agent_signals)}个Agent信号，加权得分:{weighted_score:.2f}",
            metrics=metrics
        )


class RiskManager(BaseStockAgent):
    """风险管理Agent - VaR/凯利准则"""
    
    def __init__(self):
        super().__init__(
            name="RiskManager",
            description="风险管理Agent，负责风险控制、仓位管理",
            weight=1.2
        )
        self.max_position = 0.1  # 单只股票最大仓位10%
        self.max_loss = 0.03     # 最大止损3%
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """风险评估"""
        prices = data.get('prices')
        account = data.get('account', {})
        
        metrics = {}
        
        if prices is None or len(prices) < 20:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="数据不足"
            )
        
        # 计算VaR
        returns = prices['close'].pct_change().dropna()
        var_95 = np.percentile(returns, 5)
        var_99 = np.percentile(returns, 1)
        
        metrics['var_95'] = var_95
        metrics['var_99'] = var_99
        
        # 计算最大回撤
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative - running_max) / running_max
        max_dd = drawdown.min()
        
        metrics['max_drawdown'] = max_dd
        
        # 凯利准则计算建议仓位
        win_rate = (returns > 0).mean()
        avg_win = returns[returns > 0].mean() if (returns > 0).any() else 0
        avg_loss = abs(returns[returns < 0].mean()) if (returns < 0).any() else 1
        
        # BUG FIX: 添加avg_win > 0检查，避免除零错误
        if avg_loss > 0 and avg_win > 0:
            kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
            kelly = max(0, min(self.max_position, kelly * 0.5))  # 半凯利
        else:
            kelly = 0
        
        metrics['kelly_fraction'] = kelly
        metrics['win_rate'] = win_rate
        
        # 风险评分
        risk_score = 0
        
        if max_dd < -0.2:
            risk_score -= 1
        elif max_dd < -0.1:
            risk_score -= 0.5
        
        if var_95 < -0.05:
            risk_score -= 0.5
        
        if risk_score < -1:
            signal = "bearish"
            confidence = 0.8
        elif risk_score < -0.5:
            signal = "neutral"
            confidence = 0.5
        else:
            signal = "bullish"
            confidence = 0.6
        
        return AgentSignal(
            agent_name=self.name,
            signal=signal,
            confidence=confidence,
            reasoning=f"VaR95={var_95:.2%}, 最大回撤={max_dd:.2%}, 凯利仓位={kelly:.1%}",
            metrics=metrics
        )


class PortfolioOptimizer(BaseStockAgent):
    """组合优化Agent"""
    
    def __init__(self):
        super().__init__(
            name="PortfolioOptimizer",
            description="组合优化Agent，负责多股票组合优化",
            weight=0.8
        )
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """组合优化分析"""
        holdings = data.get('holdings', [])
        
        metrics = {
            'num_holdings': len(holdings),
            'diversification_score': 0
        }
        
        if not holdings:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="无持仓数据"
            )
        
        # 计算分散化程度
        if len(holdings) >= 3:
            metrics['diversification_score'] = 0.7
        elif len(holdings) >= 2:
            metrics['diversification_score'] = 0.4
        else:
            metrics['diversification_score'] = 0.1
        
        # 分散化建议
        if metrics['diversification_score'] < 0.5:
            signal = "neutral"
            reasoning = "建议增加持仓分散风险"
        else:
            signal = "bullish"
            reasoning = "组合分散度良好"
        
        return AgentSignal(
            agent_name=self.name,
            signal=signal,
            confidence=metrics['diversification_score'],
            reasoning=reasoning,
            metrics=metrics
        )


class ExecutionAgent(BaseStockAgent):
    """执行Agent - 信号验证"""
    
    def __init__(self):
        super().__init__(
            name="ExecutionAgent",
            description="执行Agent，负责交易执行决策、滑点控制",
            weight=1.0
        )
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """执行决策"""
        consolidated_signal = data.get('consolidated_signal')
        prices = data.get('prices')
        
        metrics = {}
        
        if consolidated_signal is None:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="无综合信号"
            )
        
        # 流动性检查
        if prices is not None and 'volume' in prices.columns:
            avg_volume = prices['volume'].rolling(5).mean().iloc[-1]
            metrics['avg_volume'] = avg_volume
            metrics['liquidity'] = 'high' if avg_volume > 1e7 else 'medium' if avg_volume > 1e6 else 'low'
        
        # 执行建议
        final_signal = consolidated_signal.signal if isinstance(consolidated_signal, AgentSignal) else consolidated_signal.get('signal', 'neutral')
        confidence = consolidated_signal.confidence if isinstance(consolidated_signal, AgentSignal) else consolidated_signal.get('confidence', 0)
        
        # 高置信度才执行
        if confidence > 0.6:
            execution_signal = final_signal
            execution_confidence = confidence
        else:
            execution_signal = "neutral"
            execution_confidence = 0
            metrics['reason'] = "置信度不足，建议观望"
        
        return AgentSignal(
            agent_name=self.name,
            signal=execution_signal,
            confidence=execution_confidence,
            reasoning=f"执行信号:{execution_signal}, 置信度:{execution_confidence:.0%}",
            metrics=metrics
        )


class BacktestValidator(BaseStockAgent):
    """回测验证Agent"""
    
    def __init__(self):
        super().__init__(
            name="BacktestValidator",
            description="回测验证Agent，负责策略历史表现验证",
            weight=0.7
        )
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """回测验证"""
        backtest_result = data.get('backtest_result', {})
        
        metrics = {}
        
        if not backtest_result:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="无回测数据"
            )
        
        # 提取回测指标
        sharpe = backtest_result.get('sharpe_ratio', 0)
        win_rate = backtest_result.get('win_rate', 0)
        max_dd = backtest_result.get('max_drawdown', 0)
        
        metrics['sharpe_ratio'] = sharpe
        metrics['win_rate'] = win_rate
        metrics['max_drawdown'] = max_dd
        
        # 评分
        score = 0
        
        if sharpe > 1:
            score += 1
        elif sharpe > 0.5:
            score += 0.5
        
        if win_rate > 0.55:
            score += 0.5
        
        if max_dd < 0.1:
            score += 0.5
        elif max_dd > 0.2:
            score -= 0.5
        
        metrics['backtest_score'] = score
        
        if score >= 1.5:
            signal = "bullish"
        elif score >= 0.5:
            signal = "neutral"
        else:
            signal = "bearish"
        
        return AgentSignal(
            agent_name=self.name,
            signal=signal,
            confidence=min(1.0, score / 2),
            reasoning=f"夏普:{sharpe:.2f}, 胜率:{win_rate:.0%}, 回撤:{max_dd:.1%}",
            metrics=metrics
        )


class SentimentAggregator(BaseStockAgent):
    """情感聚合Agent"""
    
    def __init__(self):
        super().__init__(
            name="SentimentAggregator",
            description="情感聚合Agent，负责多源情感信息整合",
            weight=0.9
        )
    
    async def analyze(self, data: Dict[str, Any]) -> AgentSignal:
        """情感聚合"""
        sentiment_sources = data.get('sentiment_sources', [])
        
        metrics = {
            'num_sources': len(sentiment_sources)
        }
        
        if not sentiment_sources:
            return AgentSignal(
                agent_name=self.name,
                signal="neutral",
                confidence=0.0,
                reasoning="无情感数据源"
            )
        
        # 加权平均
        total_sentiment = 0
        total_weight = 0
        
        for source in sentiment_sources:
            sentiment = source.get('sentiment', 0)
            weight = source.get('weight', 1.0)
            
            total_sentiment += sentiment * weight
            total_weight += weight
        
        if total_weight > 0:
            avg_sentiment = total_sentiment / total_weight
        else:
            avg_sentiment = 0
        
        metrics['avg_sentiment'] = avg_sentiment
        
        if avg_sentiment > 0.2:
            signal = "bullish"
        elif avg_sentiment < -0.2:
            signal = "bearish"
        else:
            signal = "neutral"
        
        return AgentSignal(
            agent_name=self.name,
            signal=signal,
            confidence=min(1.0, abs(avg_sentiment)),
            reasoning=f"综合{len(sentiment_sources)}个情感源，平均情感:{avg_sentiment:.2f}",
            metrics=metrics
        )


# ==================== Agent管理器 ====================
class AgentManager:
    """Agent管理器
    
    整合功能：
    - 12个专业Agent分析
    - 6维度评分系统
    - 主力资金分析
    """
    
    def __init__(self):
        # 初始化6维度评分器
        self.six_dim_scorer = None
        if VECTORIZED_INDICATORS_AVAILABLE:
            try:
                self.six_dim_scorer = SixDimensionScorer()
                print("AgentManager: 6维度评分器初始化成功")
            except Exception as e:
                print(f"AgentManager: 6维度评分器初始化失败: {e}")
        
        # 初始化所有Agent
        self.analysis_agents = [
            TechnicalAnalyst(),
            FundamentalsAnalyst(),
            SentimentAnalyst(),
            ValuationAnalyst(),
            AIModelAnalyst(),
            MacroAnalyst()
        ]
        
        self.decision_agents = [
            SignalAggregator(),
            RiskManager(),
            PortfolioOptimizer(),
            ExecutionAgent(),
            BacktestValidator(),
            SentimentAggregator()
        ]
        
        self.all_agents = self.analysis_agents + self.decision_agents
    
    def calculate_six_dim_score(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算6维度评分
        
        评分维度（100分）：
        - 趋势: 35分
        - 乖离率: 25分
        - 量能: 10分
        - 支撑: 10分
        - MACD: 10分
        - RSI: 10分
        
        信号阈值：
        - 买入信号：评分 >= 60分
        - 持有信号：30分 <= 评分 < 60分
        - 卖出信号：评分 < 30分
        
        Args:
            data: 包含prices的字典
            
        Returns:
            dict: 包含total_score, scores, signal的字典
        """
        if self.six_dim_scorer is None:
            return {
                'total_score': 50.0,
                'scores': {
                    'trend': 15.0,
                    'bias': 15.0,
                    'volume': 6.0,
                    'support': 5.0,
                    'macd': 5.0,
                    'rsi': 5.0
                },
                'signal': 'HOLD',
                'error': '6维度评分器未初始化'
            }
        
        prices = data.get('prices')
        if prices is None or len(prices) < 60:
            return {
                'total_score': 50.0,
                'scores': {},
                'signal': 'HOLD',
                'error': '数据不足'
            }
        
        try:
            # 准备数据框
            df = prices.copy()
            
            # 标准化列名
            column_mapping = {
                'open': 'Open', 'high': 'High', 'low': 'Low',
                'close': 'Close', 'volume': 'Volume'
            }
            for old, new in column_mapping.items():
                if old in df.columns and new not in df.columns:
                    df[new] = df[old]
            
            # 计算必要的技术指标
            if VECTORIZED_INDICATORS_AVAILABLE:
                df = VectorizedIndicators.compute_batch_indicators(df)
            
            # 添加成交量均线
            if 'Vol_MA20' not in df.columns and 'Volume' in df.columns:
                df['Vol_MA20'] = df['Volume'].rolling(20).mean()
            
            # 计算评分
            total_score, scores, signal = self.six_dim_scorer.calc_score(df)
            
            return {
                'total_score': total_score,
                'scores': scores,
                'signal': signal,
                'details': self.six_dim_scorer.get_score_details(df).to_dict() if hasattr(self.six_dim_scorer, 'get_score_details') else None
            }
        except Exception as e:
            return {
                'total_score': 50.0,
                'scores': {},
                'signal': 'HOLD',
                'error': str(e)
            }
    
    def analyze_fund_flow(self, stock_code: str = None, days: int = 5) -> Dict[str, Any]:
        """
        分析主力资金流向
        
        使用stock_data_hub获取资金流向数据
        
        Args:
            stock_code: 股票代码（可选，None则分析市场整体）
            days: 分析天数
            
        Returns:
            dict: 主力资金分析结果
        """
        result = {
            'stock_code': stock_code,
            'days': days,
            'net_inflow': 0,
            'main_inflow': 0,
            'retail_inflow': 0,
            'trend': 'neutral',
            'signal': 'neutral',
            'confidence': 0
        }
        
        try:
            # 尝试从stock_data_hub获取资金流向
            from .stock_data_hub import StockDataHub
            
            hub = StockDataHub()
            
            if stock_code:
                # 获取个股资金流向
                fund_data = hub.get_fund_flow(stock_code)
                if fund_data:
                    result['net_inflow'] = fund_data.get('net_inflow', 0)
                    result['main_inflow'] = fund_data.get('main_inflow', 0)
                    result['retail_inflow'] = fund_data.get('retail_inflow', 0)
            else:
                # 获取市场整体资金流向
                market_flow = hub.get_market_fund_flow()
                if market_flow:
                    result['net_inflow'] = market_flow.get('net_inflow', 0)
                    result['main_inflow'] = market_flow.get('main_inflow', 0)
            
            # 分析趋势
            net = result['net_inflow']
            if net > 0:
                result['trend'] = 'inflow'
                if net > 100000000:  # 1亿
                    result['signal'] = 'bullish'
                    result['confidence'] = 0.8
                else:
                    result['signal'] = 'bullish'
                    result['confidence'] = 0.5
            elif net < 0:
                result['trend'] = 'outflow'
                if net < -100000000:  # -1亿
                    result['signal'] = 'bearish'
                    result['confidence'] = 0.8
                else:
                    result['signal'] = 'bearish'
                    result['confidence'] = 0.5
            
        except Exception as e:
            result['error'] = str(e)
            # 回退到规则分析
            result['signal'] = 'neutral'
            result['confidence'] = 0
        
        return result
    
    def get_sector_fund_flow(self, sector: str = None) -> Dict[str, Any]:
        """
        获取板块资金流向
        
        Args:
            sector: 板块名称（可选）
            
        Returns:
            dict: 板块资金流向数据
        """
        result = {
            'sector': sector,
            'net_inflow': 0,
            'rank': 0,
            'hot_sectors': []
        }
        
        try:
            from .stock_data_hub import StockDataHub
            hub = StockDataHub()
            
            # 获取板块资金流向
            sector_flow = hub.get_sector_fund_flow(sector)
            if sector_flow:
                result.update(sector_flow)
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    async def run_analysis(self, data: Dict[str, Any]) -> ConsolidatedSignal:
        """
        运行完整分析流程
        
        Args:
            data: 股票数据
            
        Returns:
            ConsolidatedSignal 综合信号
        """
        # 第一阶段：分析Agent并行运行
        analysis_tasks = [
            agent.analyze(data) 
            for agent in self.analysis_agents 
            if agent.enabled
        ]
        
        # BUG FIX: 添加30秒超时控制，避免无限等待
        try:
            analysis_signals = await asyncio.wait_for(
                asyncio.gather(*analysis_tasks, return_exceptions=True),
                timeout=30.0
            )
            # 过滤掉异常结果
            analysis_signals = [s for s in analysis_signals if not isinstance(s, Exception)]
        except asyncio.TimeoutError:
            analysis_signals = []
            print("Warning: Analysis agents timeout after 30 seconds")
        
        # 更新数据，加入分析结果
        data['agent_signals'] = analysis_signals
        
        # 计算权重
        weights = {agent.name: agent.weight for agent in self.analysis_agents}
        data['weights'] = weights
        
        # 第二阶段：决策Agent运行
        # 先运行信号聚合
        aggregator = self.decision_agents[0]  # SignalAggregator
        consolidated = await aggregator.analyze(data)
        
        data['consolidated_signal'] = consolidated
        
        # 运行其他决策Agent
        decision_tasks = [
            agent.analyze(data) 
            for agent in self.decision_agents[1:] 
            if agent.enabled
        ]
        
        # BUG FIX: 添加30秒超时控制，避免无限等待
        try:
            decision_signals = await asyncio.wait_for(
                asyncio.gather(*decision_tasks, return_exceptions=True),
                timeout=30.0
            )
            # 过滤掉异常结果
            decision_signals = [s for s in decision_signals if not isinstance(s, Exception)]
        except asyncio.TimeoutError:
            decision_signals = []
            print("Warning: Decision agents timeout after 30 seconds")
        
        # 综合决策
        all_signals = list(analysis_signals) + [consolidated] + list(decision_signals)
        
        # 计算最终信号
        final_score = 0
        total_weight = 0
        
        for sig in all_signals:
            if isinstance(sig, AgentSignal):
                signal_value = 1 if sig.signal == "bullish" else -1 if sig.signal == "bearish" else 0
                weight = weights.get(sig.agent_name, 1.0)
                
                final_score += signal_value * sig.confidence * weight
                total_weight += weight
        
        if total_weight > 0:
            final_score /= total_weight
        
        # 确定市场区制
        regime = MarketRegime.SIDEWAYS
        for sig in analysis_signals:
            if isinstance(sig, AgentSignal) and 'regime' in sig.metrics:
                regime = MarketRegime(sig.metrics['regime'])
                break
        
        # 计算风险水平
        risk_level = 0.5
        for sig in decision_signals:
            if isinstance(sig, AgentSignal) and sig.agent_name == "RiskManager":
                risk_level = 1 - sig.confidence
                break
        
        # 建议仓位
        position_suggestion = max(0, min(1, (final_score + 1) / 2)) * (1 - risk_level)
        
        # 最终信号
        if final_score > 0.3:
            final_signal = "bullish"
        elif final_score < -0.3:
            final_signal = "bearish"
        else:
            final_signal = "neutral"
        
        return ConsolidatedSignal(
            final_signal=final_signal,
            confidence=min(1.0, abs(final_score) * 1.5),
            weighted_score=final_score,
            agent_signals=all_signals,
            market_regime=regime,
            risk_level=risk_level,
            position_suggestion=position_suggestion
        )
    
    def get_agent(self, name: str) -> Optional[BaseStockAgent]:
        """获取指定Agent"""
        for agent in self.all_agents:
            if agent.name == name:
                return agent
        return None
    
    def enable_agent(self, name: str):
        """启用Agent"""
        agent = self.get_agent(name)
        if agent:
            agent.enable()
    
    def disable_agent(self, name: str):
        """禁用Agent"""
        agent = self.get_agent(name)
        if agent:
            agent.disable()
    
    def set_weight(self, name: str, weight: float):
        """设置Agent权重"""
        agent = self.get_agent(name)
        if agent:
            agent.set_weight(weight)


# ==================== 便捷函数 ====================
async def analyze_stock(data: Dict[str, Any]) -> ConsolidatedSignal:
    """
    分析股票便捷函数
    
    Args:
        data: 包含以下键的字典:
            - prices: pd.DataFrame (OHLCV数据)
            - fundamentals: dict (基本面数据，可选)
            - news: list (新闻列表，可选)
            - market: dict (市场数据，可选)
            - account: dict (账户数据，可选)
            
    Returns:
        ConsolidatedSignal
    """
    manager = AgentManager()
    return await manager.run_analysis(data)


def create_sample_data() -> Dict[str, Any]:
    """创建示例数据"""
    import pandas as pd
    import numpy as np
    
    # 生成价格数据
    dates = pd.date_range(start='2025-01-01', end='2026-03-20', freq='B')
    n = len(dates)
    
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.02, n)
    prices = 100 * np.cumprod(1 + returns)
    
    prices_df = pd.DataFrame({
        'date': dates,
        'open': prices * (1 + np.random.normal(0, 0.005, n)),
        'high': prices * (1 + np.abs(np.random.normal(0, 0.01, n))),
        'low': prices * (1 - np.abs(np.random.normal(0, 0.01, n))),
        'close': prices,
        'volume': np.random.randint(1000000, 10000000, n)
    })
    
    # 基本面数据
    fundamentals = {
        'roe': 15.5,
        'profit_growth': 20.3,
        'debt_ratio': 45.2,
        'gross_margin': 32.1,
        'pe': 18.5,
        'pb': 2.3,
        'sector': '科技'
    }
    
    # 新闻数据
    news = [
        {'title': '公司发布新产品，市场反应良好', 'content': ''},
        {'title': '业绩增长超预期', 'content': ''}
    ]
    
    # 市场数据
    market = {
        'market_trend': 0.3,
        'sector_heat': {'科技': 0.7},
        'fund_flow': 50,
        'interest_rate': 3.5
    }
    
    return {
        'prices': prices_df,
        'fundamentals': fundamentals,
        'news': news,
        'market': market
    }


# ==================== QjySDK策略集成 ====================
"""
整合QjySDK核心策略：
1. 缠论完整实现 (ChanLun)
2. 傅里叶周期分析 (Fourier)
3. 背离检测 (Divergence)
4. 多因子系统 (MultiFactor)
5. 圣杯策略/多周期共振 (Advanced)
"""

# 尝试导入QjySDK策略模块
CHANLUN_AVAILABLE = False
FOURIER_AVAILABLE = False
DIVERGENCE_AVAILABLE = False
MULTIFACTOR_AVAILABLE = False
ADVANCED_AVAILABLE = False

try:
    from stock_chanlun import ChanLunAnalyzer, analyze_chanlun, get_chanlun_signal
    CHANLUN_AVAILABLE = True
except ImportError:
    pass

try:
    from stock_fourier import FourierAnalyzer, FourierTradingStrategy, analyze_fourier, fourier_trading_signal
    FOURIER_AVAILABLE = True
except ImportError:
    pass

try:
    from stock_divergence import DivergenceDetector, MultiDivergenceStrategy, detect_divergence, multi_divergence_signal
    DIVERGENCE_AVAILABLE = True
except ImportError:
    pass

try:
    from stock_multifactor import MultiFactorScorer, MultiFactorStrategy, analyze_multifactor, multifactor_signal
    MULTIFACTOR_AVAILABLE = True
except ImportError:
    pass

try:
    from stock_advanced import (
        HolyGrailStrategy, MultiPeriodResonance, ThreeFactorResonance, TurtleTrading,
        holy_grail_signal, multi_period_signal, three_factor_signal, turtle_signal
    )
    ADVANCED_AVAILABLE = True
except ImportError:
    pass


class QjySDKAnalyzer:
    """
    QjySDK策略分析器
    
    整合所有QjySDK策略，提供统一的分析接口
    """
    
    def __init__(self):
        self.chanlun = ChanLunAnalyzer() if CHANLUN_AVAILABLE else None
        self.fourier = FourierTradingStrategy() if FOURIER_AVAILABLE else None
        self.divergence = MultiDivergenceStrategy() if DIVERGENCE_AVAILABLE else None
        self.multifactor = MultiFactorStrategy() if MULTIFACTOR_AVAILABLE else None
        self.holy_grail = HolyGrailStrategy() if ADVANCED_AVAILABLE else None
        self.multi_period = MultiPeriodResonance() if ADVANCED_AVAILABLE else None
        self.three_factor = ThreeFactorResonance() if ADVANCED_AVAILABLE else None
        self.turtle = TurtleTrading() if ADVANCED_AVAILABLE else None
    
    async def analyze_all(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        执行所有QjySDK策略分析
        
        Args:
            df: K线数据
            
        Returns:
            综合分析结果
        """
        results = {
            'available_strategies': {
                'chanlun': CHANLUN_AVAILABLE,
                'fourier': FOURIER_AVAILABLE,
                'divergence': DIVERGENCE_AVAILABLE,
                'multifactor': MULTIFACTOR_AVAILABLE,
                'advanced': ADVANCED_AVAILABLE
            },
            'signals': {},
            'final_signal': 'hold',
            'confidence': 0.0,
            'reason': ''
        }
        
        buy_signals = 0
        sell_signals = 0
        total_confidence = 0.0
        reasons = []
        
        # 1. 缠论分析
        if self.chanlun:
            try:
                chanlun_result = self.chanlun.analyze(df)
                signal = chanlun_result.get('current_signal', {})
                results['signals']['chanlun'] = {
                    'signal': signal.get('action', 'hold'),
                    'confidence': signal.get('confidence', 0),
                    'reason': signal.get('reason', ''),
                    'details': {
                        'bi_count': chanlun_result.get('bi_count', 0),
                        'zhongshu_count': chanlun_result.get('zhongshu_count', 0),
                        'beichi_count': chanlun_result.get('beichi_count', 0)
                    }
                }
                if signal.get('action') == 'buy':
                    buy_signals += 1
                    total_confidence += signal.get('confidence', 0)
                elif signal.get('action') == 'sell':
                    sell_signals += 1
                    total_confidence += signal.get('confidence', 0)
                if signal.get('reason'):
                    reasons.append(f"缠论: {signal.get('reason')}")
            except Exception as e:
                results['signals']['chanlun'] = {'error': str(e)}
        
        # 2. 傅里叶周期分析
        if self.fourier:
            try:
                fourier_result = self.fourier.analyze(df)
                results['signals']['fourier'] = {
                    'signal': fourier_result.get('signal', 'hold'),
                    'confidence': fourier_result.get('confidence', 0),
                    'reason': fourier_result.get('reason', ''),
                    'details': fourier_result.get('fourier', {})
                }
                if fourier_result.get('signal') == 'buy':
                    buy_signals += 1
                    total_confidence += fourier_result.get('confidence', 0)
                elif fourier_result.get('signal') == 'sell':
                    sell_signals += 1
                    total_confidence += fourier_result.get('confidence', 0)
                if fourier_result.get('reason'):
                    reasons.append(f"傅里叶: {fourier_result.get('reason')}")
            except Exception as e:
                results['signals']['fourier'] = {'error': str(e)}
        
        # 3. 背离检测
        if self.divergence:
            try:
                div_result = self.divergence.analyze(df)
                signal = div_result.get('final_signal', {})
                results['signals']['divergence'] = {
                    'signal': signal.get('action', 'hold'),
                    'confidence': signal.get('confidence', 0),
                    'reason': signal.get('reason', ''),
                    'details': div_result.get('strongest', {})
                }
                if signal.get('action') == 'buy':
                    buy_signals += 1
                    total_confidence += signal.get('confidence', 0)
                elif signal.get('action') == 'sell':
                    sell_signals += 1
                    total_confidence += signal.get('confidence', 0)
                if signal.get('reason'):
                    reasons.append(f"背离: {signal.get('reason')}")
            except Exception as e:
                results['signals']['divergence'] = {'error': str(e)}
        
        # 4. 多因子分析
        if self.multifactor:
            try:
                mf_result = self.multifactor.analyze(df)
                results['signals']['multifactor'] = {
                    'signal': mf_result.get('action', 'hold'),
                    'confidence': mf_result.get('confidence', 0),
                    'reason': mf_result.get('reason', ''),
                    'details': {
                        'total_score': mf_result.get('total_score', 0),
                        'rank': mf_result.get('rank', 'F'),
                        'factors': mf_result.get('factors', [])
                    }
                }
                if mf_result.get('action') == 'buy':
                    buy_signals += 1
                    total_confidence += mf_result.get('confidence', 0)
                elif mf_result.get('action') == 'sell':
                    sell_signals += 1
                    total_confidence += mf_result.get('confidence', 0)
                if mf_result.get('reason'):
                    reasons.append(f"多因子: {mf_result.get('reason')}")
            except Exception as e:
                results['signals']['multifactor'] = {'error': str(e)}
        
        # 5. 圣杯策略
        if self.holy_grail:
            try:
                hg_result = self.holy_grail.analyze(df)
                results['signals']['holy_grail'] = {
                    'signal': hg_result.action,
                    'confidence': hg_result.confidence,
                    'reason': hg_result.reason,
                    'details': {
                        'strength': hg_result.strength,
                        'entry_price': hg_result.entry_price,
                        'stop_loss': hg_result.stop_loss,
                        'take_profit': hg_result.take_profit
                    }
                }
                if hg_result.action == 'buy':
                    buy_signals += 1
                    total_confidence += hg_result.confidence
                elif hg_result.action == 'sell':
                    sell_signals += 1
                    total_confidence += hg_result.confidence
                if hg_result.reason:
                    reasons.append(f"圣杯: {hg_result.reason}")
            except Exception as e:
                results['signals']['holy_grail'] = {'error': str(e)}
        
        # 6. 多周期共振
        if self.multi_period:
            try:
                mp_result = self.multi_period.analyze(df)
                results['signals']['multi_period'] = {
                    'signal': mp_result.get('signal', 'hold'),
                    'confidence': mp_result.get('confidence', 0),
                    'reason': mp_result.get('reason', ''),
                    'details': mp_result.get('period_trends', {})
                }
                if mp_result.get('signal') == 'buy':
                    buy_signals += 1
                    total_confidence += mp_result.get('confidence', 0)
                elif mp_result.get('signal') == 'sell':
                    sell_signals += 1
                    total_confidence += mp_result.get('confidence', 0)
                if mp_result.get('reason'):
                    reasons.append(f"多周期: {mp_result.get('reason')}")
            except Exception as e:
                results['signals']['multi_period'] = {'error': str(e)}
        
        # 7. 三重因子共振
        if self.three_factor:
            try:
                tf_result = self.three_factor.analyze(df)
                results['signals']['three_factor'] = {
                    'signal': tf_result.get('signal', 'hold'),
                    'confidence': tf_result.get('confidence', 0),
                    'reason': tf_result.get('reason', ''),
                    'details': tf_result.get('factors', {})
                }
                if tf_result.get('signal') == 'buy':
                    buy_signals += 1
                    total_confidence += tf_result.get('confidence', 0)
                elif tf_result.get('signal') == 'sell':
                    sell_signals += 1
                    total_confidence += tf_result.get('confidence', 0)
                if tf_result.get('reason'):
                    reasons.append(f"三因子: {tf_result.get('reason')}")
            except Exception as e:
                results['signals']['three_factor'] = {'error': str(e)}
        
        # 汇总最终信号
        total_strategies = sum(1 for k, v in results['available_strategies'].items() if v)
        if total_strategies > 0:
            avg_confidence = total_confidence / total_strategies
        else:
            avg_confidence = 0
        
        if buy_signals > sell_signals and buy_signals >= total_strategies * 0.5:
            results['final_signal'] = 'buy'
            results['confidence'] = avg_confidence
            results['reason'] = f"多策略共振看涨({buy_signals}/{total_strategies})"
        elif sell_signals > buy_signals and sell_signals >= total_strategies * 0.5:
            results['final_signal'] = 'sell'
            results['confidence'] = avg_confidence
            results['reason'] = f"多策略共振看跌({sell_signals}/{total_strategies})"
        else:
            results['final_signal'] = 'hold'
            results['confidence'] = 0.5
            results['reason'] = f"策略分歧(买{buy_signals}/卖{sell_signals})"
        
        results['all_reasons'] = reasons
        
        return results
    
    def get_strategy_status(self) -> Dict[str, bool]:
        """获取各策略模块状态"""
        return {
            'chanlun': CHANLUN_AVAILABLE,
            'fourier': FOURIER_AVAILABLE,
            'divergence': DIVERGENCE_AVAILABLE,
            'multifactor': MULTIFACTOR_AVAILABLE,
            'holy_grail': ADVANCED_AVAILABLE,
            'multi_period': ADVANCED_AVAILABLE,
            'three_factor': ADVANCED_AVAILABLE,
            'turtle': ADVANCED_AVAILABLE
        }


# 便捷函数
async def qjysdk_analyze(df: pd.DataFrame) -> Dict[str, Any]:
    """QjySDK策略快速分析"""
    analyzer = QjySDKAnalyzer()
    return await analyzer.analyze_all(df)


# ==================== 测试入口 ====================
if __name__ == "__main__":
    async def test():
        print("=== 股票分析Agent系统测试 ===\n")
        
        # 创建示例数据
        data = create_sample_data()
        
        print(f"数据概览:")
        print(f"  价格数据: {len(data['prices'])} 条")
        print(f"  基本面: {list(data['fundamentals'].keys())}")
        print(f"  新闻: {len(data['news'])} 条")
        print()
        
        # 运行分析
        manager = AgentManager()
        
        print("运行分析Agent...")
        result = await manager.run_analysis(data)
        
        print(f"\n=== 分析结果 ===")
        print(f"最终信号: {result.final_signal}")
        print(f"置信度: {result.confidence:.0%}")
        print(f"加权得分: {result.weighted_score:.3f}")
        print(f"市场区制: {result.market_regime.value}")
        print(f"风险水平: {result.risk_level:.0%}")
        print(f"建议仓位: {result.position_suggestion:.0%}")
        
        print(f"\n=== 各Agent信号 ===")
        for sig in result.agent_signals:
            if isinstance(sig, AgentSignal):
                print(f"  {sig.agent_name}: {sig.signal} ({sig.confidence:.0%})")
    
    asyncio.run(test())

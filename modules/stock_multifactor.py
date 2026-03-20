# -*- coding: utf-8 -*-
"""
多因子策略模块
参考 QjySDK MultiFactor.cs

五因子加权打分系统：
- 动量因子 (Momentum)
- 趋势因子 (Trend)
- 波动率因子 (Volatility)
- 成交量因子 (Volume)
- 均值回归因子 (Mean Reversion)

Author: iFlow CLI
Version: 1.0.0
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class FactorScore:
    """因子得分"""
    name: str           # 因子名称
    value: float        # 原始值
    score: float        # 标准化得分 (0-100)
    weight: float       # 权重
    contribution: float # 贡献度 (score * weight)
    signal: str         # 信号 (bullish/bearish/neutral)


@dataclass
class MultiFactorResult:
    """多因子分析结果"""
    total_score: float              # 总分 (0-100)
    factors: List[FactorScore]      # 各因子得分
    signal: str                     # 综合信号
    confidence: float               # 置信度
    rank: str                       # 排名等级
    details: Dict[str, Any]         # 详细信息


class FactorCalculator:
    """因子计算器"""
    
    @staticmethod
    def calculate_momentum(close: np.ndarray, period: int = 20) -> Tuple[float, str]:
        """
        动量因子
        
        计算：ROC (Rate of Change)
        信号：正动量=看涨，负动量=看跌
        """
        if len(close) < period + 1:
            return 0.0, 'neutral'
        
        roc = (close[-1] - close[-period-1]) / close[-period-1] * 100
        
        if roc > 5:
            signal = 'bullish'
        elif roc < -5:
            signal = 'bearish'
        else:
            signal = 'neutral'
        
        return roc, signal
    
    @staticmethod
    def calculate_trend(close: np.ndarray, short: int = 5, long: int = 20) -> Tuple[float, str]:
        """
        趋势因子
        
        计算：短期均线 vs 长期均线的偏离度
        信号：金叉=看涨，死叉=看跌
        """
        if len(close) < long:
            return 0.0, 'neutral'
        
        ma_short = np.mean(close[-short:])
        ma_long = np.mean(close[-long:])
        
        deviation = (ma_short - ma_long) / ma_long * 100
        
        if ma_short > ma_long:
            signal = 'bullish'
        elif ma_short < ma_long:
            signal = 'bearish'
        else:
            signal = 'neutral'
        
        return deviation, signal
    
    @staticmethod
    def calculate_volatility(close: np.ndarray, period: int = 20) -> Tuple[float, str]:
        """
        波动率因子
        
        计算：收益率标准差（年化）
        信号：低波动=稳定看涨/看跌，高波动=不确定
        """
        if len(close) < period + 1:
            return 0.0, 'neutral'
        
        returns = np.diff(close[-period-1:]) / close[-period-1:-1]
        volatility = np.std(returns) * np.sqrt(252) * 100  # 年化波动率
        
        if volatility < 15:
            signal = 'bullish'  # 低波动，趋势稳定
        elif volatility > 30:
            signal = 'bearish'  # 高波动，风险大
        else:
            signal = 'neutral'
        
        return volatility, signal
    
    @staticmethod
    def calculate_volume(volume: np.ndarray, close: np.ndarray, period: int = 20) -> Tuple[float, str]:
        """
        成交量因子
        
        计算：量价关系
        信号：放量上涨=看涨，放量下跌=看跌，缩量=观望
        """
        if len(volume) < period + 1 or len(close) < period + 1:
            return 0.0, 'neutral'
        
        avg_volume = np.mean(volume[-period-1:-1])
        current_volume = volume[-1]
        
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        price_change = (close[-1] - close[-2]) / close[-2] * 100
        
        # 放量上涨
        if volume_ratio > 1.5 and price_change > 0:
            signal = 'bullish'
        # 放量下跌
        elif volume_ratio > 1.5 and price_change < 0:
            signal = 'bearish'
        # 缩量
        elif volume_ratio < 0.7:
            signal = 'neutral'
        else:
            signal = 'neutral'
        
        return volume_ratio, signal
    
    @staticmethod
    def calculate_mean_reversion(close: np.ndarray, period: int = 20) -> Tuple[float, str]:
        """
        均值回归因子
        
        计算：价格与均线的偏离度
        信号：过度偏离=回归信号
        """
        if len(close) < period:
            return 0.0, 'neutral'
        
        ma = np.mean(close[-period:])
        std = np.std(close[-period:])
        
        if std == 0:
            return 0.0, 'neutral'
        
        z_score = (close[-1] - ma) / std
        
        # 低于均值2个标准差=超卖，看涨
        if z_score < -2:
            signal = 'bullish'
        # 高于均值2个标准差=超买，看跌
        elif z_score > 2:
            signal = 'bearish'
        else:
            signal = 'neutral'
        
        return z_score, signal
    
    @staticmethod
    def calculate_rsi_factor(close: np.ndarray, period: int = 14) -> Tuple[float, str]:
        """
        RSI因子
        
        计算：RSI指标
        信号：超卖=看涨，超买=看跌
        """
        if len(close) < period + 1:
            return 50.0, 'neutral'
        
        delta = np.diff(close)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        
        avg_gain = np.mean(gain[-period:])
        avg_loss = np.mean(loss[-period:])
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        if rsi < 30:
            signal = 'bullish'
        elif rsi > 70:
            signal = 'bearish'
        else:
            signal = 'neutral'
        
        return rsi, signal
    
    @staticmethod
    def calculate_macd_factor(close: np.ndarray) -> Tuple[float, str]:
        """
        MACD因子
        
        计算：MACD柱状图
        信号：金叉=看涨，死叉=看跌
        """
        if len(close) < 35:
            return 0.0, 'neutral'
        
        close_series = pd.Series(close)
        ema12 = close_series.ewm(span=12, adjust=False).mean()
        ema26 = close_series.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd = (dif - dea) * 2
        
        histogram = macd.iloc[-1]
        prev_histogram = macd.iloc[-2] if len(macd) > 1 else 0
        
        if histogram > 0 and prev_histogram <= 0:
            signal = 'bullish'
        elif histogram < 0 and prev_histogram >= 0:
            signal = 'bearish'
        elif histogram > 0:
            signal = 'bullish'
        elif histogram < 0:
            signal = 'bearish'
        else:
            signal = 'neutral'
        
        return histogram, signal


class MultiFactorScorer:
    """
    多因子评分器
    
    整合多个因子，计算综合得分
    """
    
    # 默认权重配置
    DEFAULT_WEIGHTS = {
        'momentum': 0.20,
        'trend': 0.25,
        'volatility': 0.15,
        'volume': 0.15,
        'mean_reversion': 0.15,
        'rsi': 0.05,
        'macd': 0.05
    }
    
    def __init__(self, weights: Optional[Dict[str, float]] = None):
        """
        初始化
        
        Args:
            weights: 自定义权重配置
        """
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        self.calculator = FactorCalculator()
        
        # 验证权重
        total_weight = sum(self.weights.values())
        if abs(total_weight - 1.0) > 0.01:
            # 归一化权重
            for key in self.weights:
                self.weights[key] /= total_weight
    
    def analyze(self, df: pd.DataFrame) -> MultiFactorResult:
        """
        执行多因子分析

        Args:
            df: K线数据，需包含 open, high, low, close, volume 列

        Returns:
            MultiFactorResult对象
        """
        # === 数据验证 ===
        # 检查df是否为空
        if df is None or df.empty:
            logger.warning("输入数据为空，返回中性结果")
            return MultiFactorResult(
                total_score=50.0,
                factors=[],
                signal='hold',
                confidence=0.0,
                rank='F',
                details={'error': '输入数据为空'}
            )
        
        # 检查必要列是否存在
        required_columns = ['close']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.warning(f"缺少必要列: {missing_columns}")
            return MultiFactorResult(
                total_score=50.0,
                factors=[],
                signal='hold',
                confidence=0.0,
                rank='F',
                details={'error': f'缺少必要列: {missing_columns}'}
            )
        
        # 检查数据长度是否足够（至少需要35条数据用于MACD）
        min_required_length = 35
        if len(df) < min_required_length:
            logger.warning(f"数据长度不足: {len(df)} < {min_required_length}")
            return MultiFactorResult(
                total_score=50.0,
                factors=[],
                signal='hold',
                confidence=0.0,
                rank='F',
                details={'error': f'数据长度不足: {len(df)} < {min_required_length}'}
            )
        
        # 处理NaN值 - 前向填充后向填充
        df = df.copy()
        df = df.ffill().bfill()
        
        # 最终检查：确保close列没有NaN
        if df['close'].isna().any():
            logger.warning("close列存在无法填充的NaN值")
            return MultiFactorResult(
                total_score=50.0,
                factors=[],
                signal='hold',
                confidence=0.0,
                rank='F',
                details={'error': 'close列存在NaN值'}
            )
        # === 数据验证结束 ===
        
        close = df['close'].values
        volume = df['volume'].values if 'volume' in df.columns else np.ones(len(close))
        
        factors = []
        
        # 1. 动量因子
        momentum_value, momentum_signal = self.calculator.calculate_momentum(close)
        momentum_score = self._normalize_score(momentum_value, -20, 20)
        factors.append(FactorScore(
            name='momentum',
            value=momentum_value,
            score=momentum_score,
            weight=self.weights.get('momentum', 0.2),
            contribution=momentum_score * self.weights.get('momentum', 0.2),
            signal=momentum_signal
        ))
        
        # 2. 趋势因子
        trend_value, trend_signal = self.calculator.calculate_trend(close)
        trend_score = self._normalize_score(trend_value, -10, 10)
        factors.append(FactorScore(
            name='trend',
            value=trend_value,
            score=trend_score,
            weight=self.weights.get('trend', 0.25),
            contribution=trend_score * self.weights.get('trend', 0.25),
            signal=trend_signal
        ))
        
        # 3. 波动率因子
        volatility_value, volatility_signal = self.calculator.calculate_volatility(close)
        volatility_score = 100 - min(100, volatility_value * 2)  # 波动率越低越好
        factors.append(FactorScore(
            name='volatility',
            value=volatility_value,
            score=volatility_score,
            weight=self.weights.get('volatility', 0.15),
            contribution=volatility_score * self.weights.get('volatility', 0.15),
            signal=volatility_signal
        ))
        
        # 4. 成交量因子
        # 修复：结合价格变化方向计算成交量得分
        # 上涨时放量加分，下跌时放量减分
        volume_value, volume_signal = self.calculator.calculate_volume(volume, close)
        
        # 计算价格变化方向
        price_change_pct = 0.0
        if len(close) >= 2 and close[-2] > 0:
            price_change_pct = (close[-1] - close[-2]) / close[-2] * 100
        
        # 成交量得分：量比本身映射到0-100，再根据价格方向调整
        base_volume_score = self._normalize_score(volume_value, 0.5, 2.0)
        
        if price_change_pct > 0:
            # 上涨时，放量加分（量比越高，得分越高）
            volume_score = base_volume_score
        elif price_change_pct < 0:
            # 下跌时，放量减分（量比越高，得分越低）
            volume_score = 100 - base_volume_score
        else:
            # 平盘时中性
            volume_score = 50.0
        
        factors.append(FactorScore(
            name='volume',
            value=volume_value,
            score=volume_score,
            weight=self.weights.get('volume', 0.15),
            contribution=volume_score * self.weights.get('volume', 0.15),
            signal=volume_signal
        ))
        
        # 5. 均值回归因子
        reversion_value, reversion_signal = self.calculator.calculate_mean_reversion(close)
        reversion_score = self._normalize_score(-reversion_value, -3, 3)  # 负偏离得分高
        factors.append(FactorScore(
            name='mean_reversion',
            value=reversion_value,
            score=reversion_score,
            weight=self.weights.get('mean_reversion', 0.15),
            contribution=reversion_score * self.weights.get('mean_reversion', 0.15),
            signal=reversion_signal
        ))
        
        # 6. RSI因子
        # 修复：RSI超卖(<30)应得高分，超买(>70)应得低分
        rsi_value, rsi_signal = self.calculator.calculate_rsi_factor(close)
        rsi_score = 100 - rsi_value  # 反转评分：超卖=高分，超买=低分
        factors.append(FactorScore(
            name='rsi',
            value=rsi_value,
            score=rsi_score,
            weight=self.weights.get('rsi', 0.05),
            contribution=rsi_score * self.weights.get('rsi', 0.05),
            signal=rsi_signal
        ))
        
        # 7. MACD因子
        macd_value, macd_signal = self.calculator.calculate_macd_factor(close)
        macd_score = self._normalize_score(macd_value, -2, 2)
        factors.append(FactorScore(
            name='macd',
            value=macd_value,
            score=macd_score,
            weight=self.weights.get('macd', 0.05),
            contribution=macd_score * self.weights.get('macd', 0.05),
            signal=macd_signal
        ))
        
        # 计算总分
        total_score = sum(f.contribution for f in factors)
        
        # 确定信号和置信度
        signal, confidence = self._determine_signal(factors, total_score)
        
        # 确定排名等级
        rank = self._determine_rank(total_score)
        
        return MultiFactorResult(
            total_score=total_score,
            factors=factors,
            signal=signal,
            confidence=confidence,
            rank=rank,
            details={
                'bullish_count': sum(1 for f in factors if f.signal == 'bullish'),
                'bearish_count': sum(1 for f in factors if f.signal == 'bearish'),
                'neutral_count': sum(1 for f in factors if f.signal == 'neutral'),
                'factor_details': {f.name: {'value': f.value, 'signal': f.signal} for f in factors}
            }
        )
    
    def _normalize_score(self, value: float, min_val: float, max_val: float) -> float:
        """将值归一化到0-100"""
        normalized = (value - min_val) / (max_val - min_val) * 100
        return max(0, min(100, normalized))
    
    def _determine_signal(self, factors: List[FactorScore], total_score: float) -> Tuple[str, float]:
        """确定综合信号"""
        bullish_count = sum(1 for f in factors if f.signal == 'bullish')
        bearish_count = sum(1 for f in factors if f.signal == 'bearish')
        
        if total_score >= 65 and bullish_count >= 4:
            return 'strong_buy', min(1.0, (total_score - 50) / 30)
        elif total_score >= 55 and bullish_count >= 3:
            return 'buy', min(1.0, (total_score - 50) / 30)
        elif total_score <= 35 and bearish_count >= 4:
            return 'strong_sell', min(1.0, (50 - total_score) / 30)
        elif total_score <= 45 and bearish_count >= 3:
            return 'sell', min(1.0, (50 - total_score) / 30)
        else:
            return 'hold', 0.5
    
    def _determine_rank(self, total_score: float) -> str:
        """确定排名等级"""
        if total_score >= 80:
            return 'A+'
        elif total_score >= 70:
            return 'A'
        elif total_score >= 60:
            return 'B+'
        elif total_score >= 50:
            return 'B'
        elif total_score >= 40:
            return 'C'
        elif total_score >= 30:
            return 'D'
        else:
            return 'F'


class MultiFactorStrategy:
    """
    多因子交易策略
    
    参考 QjySDK MultiFactor.cs
    """
    
    def __init__(self, 
                 weights: Optional[Dict[str, float]] = None,
                 buy_threshold: float = 60,
                 sell_threshold: float = 40):
        """
        初始化
        
        Args:
            weights: 因子权重
            buy_threshold: 买入阈值
            sell_threshold: 卖出阈值
        """
        self.scorer = MultiFactorScorer(weights)
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
    
    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        策略分析
        
        Args:
            df: K线数据
            
        Returns:
            分析结果字典
        """
        result = self.scorer.analyze(df)
        
        # 生成交易建议
        action = 'hold'
        reason = ''
        
        if result.total_score >= self.buy_threshold:
            if result.signal == 'strong_buy':
                action = 'buy'
                reason = f"多因子强买入信号，总分{result.total_score:.1f}({result.rank})"
            elif result.signal == 'buy':
                action = 'buy'
                reason = f"多因子买入信号，总分{result.total_score:.1f}({result.rank})"
        elif result.total_score <= self.sell_threshold:
            if result.signal == 'strong_sell':
                action = 'sell'
                reason = f"多因子强卖出信号，总分{result.total_score:.1f}({result.rank})"
            elif result.signal == 'sell':
                action = 'sell'
                reason = f"多因子卖出信号，总分{result.total_score:.1f}({result.rank})"
        else:
            reason = f"多因子中性，总分{result.total_score:.1f}({result.rank})"
        
        return {
            'success': True,
            'action': action,
            'confidence': result.confidence,
            'reason': reason,
            'total_score': result.total_score,
            'rank': result.rank,
            'signal': result.signal,
            'factors': [{
                'name': f.name,
                'score': f.score,
                'weight': f.weight,
                'signal': f.signal
            } for f in result.factors],
            'summary': result.details
        }


# 便捷函数
def analyze_multifactor(df: pd.DataFrame, 
                        weights: Optional[Dict[str, float]] = None) -> MultiFactorResult:
    """快速多因子分析"""
    scorer = MultiFactorScorer(weights)
    return scorer.analyze(df)


def multifactor_signal(df: pd.DataFrame,
                       buy_threshold: float = 60,
                       sell_threshold: float = 40) -> Dict[str, Any]:
    """多因子交易信号"""
    strategy = MultiFactorStrategy(buy_threshold=buy_threshold, sell_threshold=sell_threshold)
    return strategy.analyze(df)


if __name__ == '__main__':
    # 测试代码
    np.random.seed(42)
    
    n = 100
    close = 10 + np.cumsum(np.random.randn(n) * 0.1)
    close = np.abs(close) + 1  # 确保正数
    
    df = pd.DataFrame({
        'close': close,
        'high': close + np.random.rand(n) * 0.5,
        'low': close - np.random.rand(n) * 0.5,
        'volume': np.random.randint(1000, 10000, n)
    })
    
    # 分析
    result = multifactor_signal(df)
    print(f"总分: {result['total_score']:.1f}")
    print(f"等级: {result['rank']}")
    print(f"信号: {result['action']} ({result['confidence']:.2f})")
    print(f"原因: {result['reason']}")

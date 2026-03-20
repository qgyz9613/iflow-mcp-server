# -*- coding: utf-8 -*-
"""
高级策略模块
参考 QjySDK EMA_ADX.cs, MultiPeriodResonance.cs, ThreeFactorResonance.cs

包含：
1. 圣杯策略 (EMA + ADX) - 强趋势回调入场
2. 多周期共振 - 多时间框架确认
3. 三重因子共振 - MA + MACD + OBV
4. 海龟交易策略 - 唐奇安通道 + ATR

Author: iFlow CLI
Version: 1.0.0
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TrendStrength(Enum):
    """趋势强度"""
    STRONG_UP = 3
    UP = 2
    WEAK_UP = 1
    NEUTRAL = 0
    WEAK_DOWN = -1
    DOWN = -2
    STRONG_DOWN = -3


@dataclass
class SignalResult:
    """信号结果"""
    action: str           # buy/sell/hold
    confidence: float     # 置信度
    reason: str           # 原因
    strength: str         # 强度
    entry_price: float    # 建议入场价
    stop_loss: float      # 止损价
    take_profit: float    # 止盈价


class HolyGrailStrategy:
    """
    圣杯策略 (EMA + ADX)
    
    参考 QjySDK EMA_ADX.cs
    
    核心逻辑：
    1. ADX > 25 表示强趋势
    2. 价格回调到EMA附近
    3. EMA方向与趋势一致
    4. 顺势入场
    
    这是最经典的趋势回调策略，被称为"圣杯"
    """
    
    def __init__(self, 
                 ema_period: int = 20,
                 adx_period: int = 14,
                 adx_threshold: float = 25.0,
                 pullback_threshold: float = 0.02):
        """
        初始化
        
        Args:
            ema_period: EMA周期
            adx_period: ADX周期
            adx_threshold: ADX阈值（趋势强度）
            pullback_threshold: 回调阈值（相对于EMA的偏离度）
        """
        self.ema_period = ema_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.pullback_threshold = pullback_threshold
    
    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """执行圣杯策略分析"""
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        # ADX计算需要足够数据点：adx_period*3用于平滑计算，ema_period用于EMA，+5用于安全边际
        min_required = self.adx_period * 3 + self.ema_period + 5
        if len(close) < min_required:
            return {
                'success': False,
                'action': 'hold',
                'confidence': 0.0,
                'reason': f'数据不足(需要{min_required}条,实际{len(close)}条)',
                'strength': 'NEUTRAL',
                'entry_price': 0,
                'stop_loss': 0,
                'take_profit': 0
            }
        
        # 计算EMA
        close_series = pd.Series(close)
        ema = close_series.ewm(span=self.ema_period, adjust=False).mean().values
        
        # 计算ADX
        adx, plus_di, minus_di = self._calculate_adx(high, low, close)
        
        # 当前值
        current_close = close[-1]
        current_ema = ema[-1]
        current_adx = adx[-1]
        current_plus_di = plus_di[-1]
        current_minus_di = minus_di[-1]
        
        # 判断趋势
        ema_trend = 'up' if current_close > current_ema else 'down'
        
        # 计算价格与EMA的偏离度
        deviation = (current_close - current_ema) / current_ema
        
        # 判断回调
        is_pullback_to_ema = abs(deviation) < self.pullback_threshold
        
        # 生成信号
        signal = 'hold'
        confidence = 0.0
        reason = ''
        strength = 'NEUTRAL'
        
        # 强趋势判断
        if current_adx > self.adx_threshold:
            # 向上趋势
            if ema_trend == 'up' and current_plus_di > current_minus_di:
                if is_pullback_to_ema:
                    # 回调到EMA附近，买入信号
                    signal = 'buy'
                    confidence = min(1.0, (current_adx - self.adx_threshold) / 25 + 0.5)
                    reason = f"圣杯买入: ADX={current_adx:.1f}(强趋势), 回调至EMA"
                    strength = self._get_trend_strength(current_adx)
                else:
                    reason = f"向上趋势但未回调, 偏离={deviation*100:.2f}%"
            
            # 向下趋势
            elif ema_trend == 'down' and current_minus_di > current_plus_di:
                if is_pullback_to_ema:
                    signal = 'sell'
                    confidence = min(1.0, (current_adx - self.adx_threshold) / 25 + 0.5)
                    reason = f"圣杯卖出: ADX={current_adx:.1f}(强趋势), 反弹至EMA"
                    strength = self._get_trend_strength(current_adx)
                else:
                    reason = f"向下趋势但未反弹, 偏离={deviation*100:.2f}%"
        else:
            reason = f"趋势不强, ADX={current_adx:.1f}<{self.adx_threshold}"
        
        # 计算止损止盈
        atr = self._calculate_atr(high, low, close, 14)
        stop_loss = current_close - 2 * atr if signal == 'buy' else current_close + 2 * atr
        take_profit = current_close + 3 * atr if signal == 'buy' else current_close - 3 * atr
        
        return {
            'success': True,
            'action': signal,
            'confidence': confidence,
            'reason': reason,
            'strength': strength,
            'entry_price': current_close,
            'stop_loss': stop_loss,
            'take_profit': take_profit
        }
    
    def _calculate_adx(self, high: np.ndarray, low: np.ndarray, 
                       close: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算ADX、+DI、-DI"""
        n = len(close)
        
        # 计算+DM和-DM
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        
        for i in range(1, n):
            up_move = high[i] - high[i-1]
            down_move = low[i-1] - low[i]
            
            if up_move > down_move and up_move > 0:
                plus_dm[i] = up_move
            else:
                plus_dm[i] = 0
            
            if down_move > up_move and down_move > 0:
                minus_dm[i] = down_move
            else:
                minus_dm[i] = 0
        
        # 计算TR
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(high[i] - low[i], 
                       abs(high[i] - close[i-1]), 
                       abs(low[i] - close[i-1]))
        
        # 计算平滑值
        period = self.adx_period
        
        smooth_tr = pd.Series(tr).ewm(span=period, adjust=False).mean().values
        smooth_plus_dm = pd.Series(plus_dm).ewm(span=period, adjust=False).mean().values
        smooth_minus_dm = pd.Series(minus_dm).ewm(span=period, adjust=False).mean().values
        
        # 计算+DI和-DI
        plus_di = 100 * smooth_plus_dm / (smooth_tr + 1e-10)
        minus_di = 100 * smooth_minus_dm / (smooth_tr + 1e-10)
        
        # 计算DX和ADX
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = pd.Series(dx).ewm(span=period, adjust=False).mean().values
        
        return adx, plus_di, minus_di
    
    def _calculate_atr(self, high: np.ndarray, low: np.ndarray, 
                       close: np.ndarray, period: int = 14) -> float:
        """计算ATR"""
        n = len(close)
        tr = np.zeros(n)
        
        for i in range(1, n):
            tr[i] = max(high[i] - low[i],
                       abs(high[i] - close[i-1]),
                       abs(low[i] - close[i-1]))
        
        return np.mean(tr[-period:])
    
    def _get_trend_strength(self, adx: float) -> str:
        """获取趋势强度描述"""
        if adx > 50:
            return 'EXTREMELY_STRONG'
        elif adx > 40:
            return 'VERY_STRONG'
        elif adx > 30:
            return 'STRONG'
        else:
            return 'MODERATE'


class MultiPeriodResonance:
    """
    多周期共振策略
    
    参考 QjySDK MultiPeriodResonance.cs
    
    核心逻辑：
    1. 分析多个时间周期的趋势
    2. 当多个周期趋势一致时信号更强
    3. 共振强度越高，信号可靠性越高
    """
    
    def __init__(self, 
                 periods: List[int] = None,
                 weights: List[float] = None):
        """
        初始化
        
        Args:
            periods: 各周期长度（日线数）
            weights: 各周期权重
        """
        self.periods = periods or [5, 10, 20, 60]  # 5日、10日、20日、60日
        self.weights = weights or [0.1, 0.2, 0.3, 0.4]
        
        if len(self.periods) != len(self.weights):
            raise ValueError("周期数与权重数不匹配")
    
    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """执行多周期共振分析"""
        close = df['close'].values
        
        if len(close) < max(self.periods) + 5:
            return {
                'success': False,
                'signal': 'hold',
                'confidence': 0.0,
                'reason': '数据不足'
            }
        
        # 分析各周期趋势
        period_trends = {}
        
        for period in self.periods:
            if len(close) >= period:
                ma = np.mean(close[-period:])
                ma_prev = np.mean(close[-period-1:-1])
                
                # 计算趋势
                trend_slope = (ma - ma_prev) / ma_prev * 100
                
                if trend_slope > 0.5:
                    trend = 'up'
                elif trend_slope < -0.5:
                    trend = 'down'
                else:
                    trend = 'sideways'
                
                period_trends[period] = {
                    'trend': trend,
                    'slope': trend_slope,
                    'ma': ma
                }
        
        # 计算共振度
        up_count = sum(1 for v in period_trends.values() if v['trend'] == 'up')
        down_count = sum(1 for v in period_trends.values() if v['trend'] == 'down')
        sideways_count = sum(1 for v in period_trends.values() if v['trend'] == 'sideways')
        
        # 加权共振度
        up_weight = sum(self.weights[i] for i, p in enumerate(self.periods) 
                       if p in period_trends and period_trends[p]['trend'] == 'up')
        down_weight = sum(self.weights[i] for i, p in enumerate(self.periods) 
                         if p in period_trends and period_trends[p]['trend'] == 'down')
        
        resonance = max(up_weight, down_weight)
        
        # 生成信号
        if up_weight > 0.7:
            signal = 'buy'
            confidence = up_weight
            reason = f"多周期向上共振({up_count}/{len(self.periods)}), 强度{up_weight:.0%}"
        elif down_weight > 0.7:
            signal = 'sell'
            confidence = down_weight
            reason = f"多周期向下共振({down_count}/{len(self.periods)}), 强度{down_weight:.0%}"
        else:
            signal = 'hold'
            confidence = 0.5
            reason = f"周期分歧: 上{up_count}/下{down_count}/平{sideways_count}"
        
        return {
            'success': True,
            'signal': signal,
            'confidence': confidence,
            'reason': reason,
            'resonance': resonance,
            'period_trends': period_trends,
            'alignment': {
                'up_count': up_count,
                'down_count': down_count,
                'sideways_count': sideways_count
            }
        }


class ThreeFactorResonance:
    """
    三重因子共振策略
    
    参考 QjySDK ThreeFactorResonance.cs
    
    三因子：
    1. MA趋势 - 均线方向
    2. MACD动量 - MACD方向
    3. OBV成交量 - 量能方向
    
    三者同向时信号最强
    """
    
    def __init__(self, 
                 ma_period: int = 20,
                 macd_fast: int = 12,
                 macd_slow: int = 26,
                 macd_signal: int = 9):
        """
        初始化
        """
        self.ma_period = ma_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
    
    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """执行三重因子共振分析"""
        close = df['close'].values
        volume = df['volume'].values if 'volume' in df.columns else np.ones(len(close))
        
        if len(close) < self.macd_slow + 10:
            return {
                'success': False,
                'signal': 'hold',
                'confidence': 0.0,
                'reason': '数据不足'
            }
        
        # 1. MA趋势因子
        ma = pd.Series(close).rolling(self.ma_period).mean().values
        ma_trend = 'up' if ma[-1] > ma[-2] else 'down' if ma[-1] < ma[-2] else 'neutral'
        ma_score = 1 if ma_trend == 'up' else -1 if ma_trend == 'down' else 0
        
        # 2. MACD动量因子
        close_series = pd.Series(close)
        ema_fast = close_series.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = close_series.ewm(span=self.macd_slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=self.macd_signal, adjust=False).mean()
        macd = (dif - dea) * 2
        
        macd_trend = 'up' if macd.iloc[-1] > macd.iloc[-2] else 'down' if macd.iloc[-1] < macd.iloc[-2] else 'neutral'
        macd_score = 1 if macd_trend == 'up' else -1 if macd_trend == 'down' else 0
        
        # 3. OBV成交量因子
        obv = self._calculate_obv(close, volume)
        obv_trend = 'up' if obv[-1] > obv[-5] else 'down' if obv[-1] < obv[-5] else 'neutral'
        obv_score = 1 if obv_trend == 'up' else -1 if obv_trend == 'down' else 0
        
        # 计算共振度
        total_score = ma_score + macd_score + obv_score
        
        # 生成信号
        if total_score == 3:
            signal = 'buy'
            confidence = 1.0
            reason = "三重因子完美共振: MA↑ MACD↑ OBV↑"
        elif total_score == 2:
            signal = 'buy'
            confidence = 0.8
            reason = f"双重因子看涨: MA{'↑' if ma_score>0 else '↓'} MACD{'↑' if macd_score>0 else '↓'} OBV{'↑' if obv_score>0 else '↓'}"
        elif total_score == -3:
            signal = 'sell'
            confidence = 1.0
            reason = "三重因子完美共振: MA↓ MACD↓ OBV↓"
        elif total_score == -2:
            signal = 'sell'
            confidence = 0.8
            reason = f"双重因子看跌: MA{'↑' if ma_score>0 else '↓'} MACD{'↑' if macd_score>0 else '↓'} OBV{'↑' if obv_score>0 else '↓'}"
        else:
            signal = 'hold'
            confidence = 0.5
            reason = f"因子分歧: MA{'↑' if ma_score>0 else '↓' if ma_score<0 else '-'} MACD{'↑' if macd_score>0 else '↓' if macd_score<0 else '-'} OBV{'↑' if obv_score>0 else '↓' if obv_score<0 else '-'}"
        
        return {
            'success': True,
            'signal': signal,
            'confidence': confidence,
            'reason': reason,
            'total_score': total_score,
            'factors': {
                'ma': {'trend': ma_trend, 'score': ma_score, 'value': ma[-1]},
                'macd': {'trend': macd_trend, 'score': macd_score, 'value': macd.iloc[-1]},
                'obv': {'trend': obv_trend, 'score': obv_score, 'value': obv[-1]}
            },
            'resonance_strength': abs(total_score) / 3
        }
    
    def _calculate_obv(self, close: np.ndarray, volume: np.ndarray) -> np.ndarray:
        """计算OBV"""
        obv = np.zeros(len(close))
        obv[0] = volume[0]
        
        for i in range(1, len(close)):
            if close[i] > close[i-1]:
                obv[i] = obv[i-1] + volume[i]
            elif close[i] < close[i-1]:
                obv[i] = obv[i-1] - volume[i]
            else:
                obv[i] = obv[i-1]
        
        return obv


class TurtleTrading:
    """
    海龟交易策略
    
    参考 QjySDK TurtleTrading.cs
    
    核心要素：
    1. 唐奇安通道突破
    2. ATR仓位管理
    3. 金字塔加仓
    4. 止损止盈
    """
    
    def __init__(self,
                 entry_period: int = 20,
                 exit_period: int = 10,
                 atr_period: int = 20,
                 unit_risk: float = 0.01,
                 max_units: int = 4):
        """
        初始化
        
        Args:
            entry_period: 入场通道周期
            exit_period: 出场通道周期
            atr_period: ATR周期
            unit_risk: 单位风险（占总资金比例）
            max_units: 最大持仓单位数
        """
        self.entry_period = entry_period
        self.exit_period = exit_period
        self.atr_period = atr_period
        self.unit_risk = unit_risk
        self.max_units = max_units
    
    def analyze(self, df: pd.DataFrame, 
                position: float = 0,
                entry_price: float = 0,
                units: int = 0,
                capital: float = 100000) -> Dict[str, Any]:
        """
        执行海龟策略分析
        
        Args:
            df: K线数据
            position: 当前持仓数量
            entry_price: 入场价格
            units: 当前持仓单位数
            capital: 总资金
        """
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        
        if len(close) < self.entry_period + 1:
            return {'success': False, 'signal': 'hold', 'reason': '数据不足'}
        
        # 计算唐奇安通道
        upper_channel = np.max(high[-self.entry_period-1:-1])
        lower_channel = np.min(low[-self.entry_period-1:-1])
        
        exit_upper = np.max(high[-self.exit_period-1:-1])
        exit_lower = np.min(low[-self.exit_period-1:-1])
        
        # 计算ATR
        atr = self._calculate_atr(high, low, close)
        
        current_price = close[-1]
        
        # 计算单位仓位
        unit_size = int(capital * self.unit_risk / atr)
        
        # 生成信号
        signal = 'hold'
        confidence = 0.0
        reason = ''
        stop_loss = 0
        add_position = False
        
        if position == 0:
            # 无持仓，检查突破入场
            if current_price > upper_channel:
                signal = 'buy'
                confidence = 0.8
                reason = f"突破{self.entry_period}日高点{upper_channel:.2f}"
                stop_loss = current_price - 2 * atr
            elif current_price < lower_channel:
                signal = 'sell'
                confidence = 0.8
                reason = f"跌破{self.entry_period}日低点{lower_channel:.2f}"
                stop_loss = current_price + 2 * atr
        elif position > 0:
            # 多头持仓，检查止损、出场、加仓
            stop_loss = entry_price - 2 * atr
            
            # 优先检查止损
            if current_price < stop_loss:
                signal = 'sell'
                confidence = 1.0
                reason = f"触发止损{stop_loss:.2f}"
            # 检查出场通道
            elif current_price < exit_lower:
                signal = 'sell'
                confidence = 0.9
                reason = f"跌破{self.exit_period}日低点{exit_lower:.2f}"
            # 检查加仓条件
            elif units < self.max_units and current_price >= entry_price + 0.5 * atr:
                add_position = True
                signal = 'buy'
                confidence = 0.7
                reason = f"金字塔加仓(第{units+1}单位)"
        else:
            # 空头持仓 (position < 0)
            stop_loss = entry_price + 2 * atr
            
            # 优先检查止损
            if current_price > stop_loss:
                signal = 'buy'
                confidence = 1.0
                reason = f"触发止损{stop_loss:.2f}"
            # 检查出场通道
            elif current_price > exit_upper:
                signal = 'buy'
                confidence = 0.9
                reason = f"突破{self.exit_period}日高点{exit_upper:.2f}"
            # 检查加仓条件（空头加仓）
            elif units < self.max_units and current_price <= entry_price - 0.5 * atr:
                add_position = True
                signal = 'sell'
                confidence = 0.7
                reason = f"空头金字塔加仓(第{units+1}单位)"
        
        return {
            'success': True,
            'signal': signal,
            'confidence': confidence,
            'reason': reason,
            'position': position,
            'units': units,
            'add_position': add_position,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'unit_size': unit_size,
            'atr': atr,
            'channels': {
                'entry_upper': upper_channel,
                'entry_lower': lower_channel,
                'exit_upper': exit_upper,
                'exit_lower': exit_lower
            }
        }
    
    def _calculate_atr(self, high: np.ndarray, low: np.ndarray, 
                       close: np.ndarray) -> float:
        """计算ATR"""
        n = len(close)
        tr = np.zeros(n)
        
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(high[i] - low[i],
                       abs(high[i] - close[i-1]),
                       abs(low[i] - close[i-1]))
        
        return np.mean(tr[-self.atr_period:])


# 便捷函数
def holy_grail_signal(df: pd.DataFrame) -> Dict[str, Any]:
    """圣杯策略信号"""
    strategy = HolyGrailStrategy()
    return strategy.analyze(df)


def multi_period_signal(df: pd.DataFrame) -> Dict[str, Any]:
    """多周期共振信号"""
    strategy = MultiPeriodResonance()
    return strategy.analyze(df)


def three_factor_signal(df: pd.DataFrame) -> Dict[str, Any]:
    """三重因子共振信号"""
    strategy = ThreeFactorResonance()
    return strategy.analyze(df)


def turtle_signal(df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
    """海龟交易信号"""
    strategy = TurtleTrading()
    return strategy.analyze(df, **kwargs)


if __name__ == '__main__':
    # 测试代码
    np.random.seed(42)
    
    n = 100
    close = 10 + np.cumsum(np.random.randn(n) * 0.1)
    close = np.abs(close) + 1
    
    df = pd.DataFrame({
        'close': close,
        'high': close + np.random.rand(n) * 0.5,
        'low': close - np.random.rand(n) * 0.5,
        'volume': np.random.randint(1000, 10000, n)
    })
    
    # 测试圣杯策略
    result = holy_grail_signal(df)
    print(f"圣杯策略: {result['action']} ({result['confidence']:.2f})")
    print(f"原因: {result['reason']}")
    
    # 测试多周期共振
    result = multi_period_signal(df)
    print(f"\n多周期共振: {result['signal']} ({result['confidence']:.2f})")
    print(f"原因: {result['reason']}")

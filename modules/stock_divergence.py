# -*- coding: utf-8 -*-
"""
背离检测模块
参考 QjySDK MACD_Deviate.cs, RSI_Deviate.cs

检测顶底背离：
- MACD顶背离：价格创新高，MACD不创新高
- MACD底背离：价格创新低，MACD不创新低
- RSI顶背离：价格创新高，RSI不创新高
- RSI底背离：价格创新低，RSI不创新低

Author: iFlow CLI
Version: 1.0.0
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Optional, Any
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DivergenceType(Enum):
    """背离类型"""
    TOP_DIVERGENCE = 1      # 顶背离
    BOTTOM_DIVERGENCE = -1  # 底背离
    NONE = 0               # 无背离


class DivergenceStrength(Enum):
    """背离强度"""
    STRONG = 3       # 强背离（多次确认）
    MODERATE = 2     # 中等背离
    WEAK = 1         # 弱背离


@dataclass
class Divergence:
    """背离信号"""
    index: int                      # 背离点索引
    divergence_type: DivergenceType # 背离类型
    indicator: str                  # 指标名称（MACD/RSI/KDJ）
    price1: float                   # 第一个极值点价格
    price2: float                   # 第二个极值点价格
    indicator1: float               # 第一个极值点指标值
    indicator2: float               # 第二个极值点指标值
    strength: DivergenceStrength    # 强度
    confidence: float               # 置信度
    confirmed: bool                 # 是否已确认


class DivergenceDetector:
    """
    背离检测器
    
    检测多种类型的背离：
    1. MACD背离（柱状图和DIF线）
    2. RSI背离
    3. KDJ背离
    4. 成交量背离
    """
    
    def __init__(self, 
                 lookback: int = 60,
                 min_peak_distance: int = 5):
        """
        初始化
        
        Args:
            lookback: 回看周期
            min_peak_distance: 极值点最小距离
        """
        self.lookback = lookback
        self.min_peak_distance = min_peak_distance
    
    def detect_all(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        检测所有类型的背离
        
        Args:
            df: K线数据，需包含 high, low, close, volume 列
            
        Returns:
            检测结果字典
        """
        # 数据长度检查
        required_length = max(self.lookback, 50)  # 至少需要50条数据
        if len(df) < required_length:
            logger.warning(f"数据长度不足: {len(df)} < {required_length}")
            return {
                'success': False,
                'error': f'数据长度不足，需要至少{required_length}条数据',
                'divergence_count': 0,
                'strongest': {'type': 'NONE', 'indicator': None, 'confidence': 0.0, 'strength': 'WEAK'},
                'macd_divergences': [],
                'rsi_divergences': [],
                'signal': {'action': 'hold', 'confidence': 0.0, 'reason': '数据不足'}
            }
        
        # 列检查
        required_cols = ['close', 'high', 'low']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.error(f"缺少必要列: {missing_cols}")
            return {
                'success': False,
                'error': f'缺少必要列: {missing_cols}',
                'divergence_count': 0,
                'strongest': {'type': 'NONE', 'indicator': None, 'confidence': 0.0, 'strength': 'WEAK'},
                'macd_divergences': [],
                'rsi_divergences': [],
                'signal': {'action': 'hold', 'confidence': 0.0, 'reason': '数据列缺失'}
            }
        
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        volume = df['volume'].values if 'volume' in df.columns else None
        
        # 确保lookback不超过数据长度（存储为实例变量供检测方法使用）
        self._actual_lookback = min(self.lookback, len(close) - 10)
        if self._actual_lookback < 20:
            logger.warning(f"有效回看周期过短: {self._actual_lookback}")
            self._actual_lookback = min(20, len(close) - 5)  # 最小保证20条
        
        # 计算各指标
        macd, signal, histogram = self._calculate_macd(close)
        rsi = self._calculate_rsi(close)
        k, d, j = self._calculate_kdj(high, low, close)
        
        # 检测各类型背离
        macd_divergences = self._detect_macd_divergence(close, histogram, macd)
        rsi_divergences = self._detect_rsi_divergence(close, rsi)
        kdj_divergences = self._detect_kdj_divergence(close, j)
        volume_divergences = self._detect_volume_divergence(close, volume) if volume is not None else []
        
        # 汇总结果
        all_divergences = macd_divergences + rsi_divergences + kdj_divergences + volume_divergences
        
        # 获取最强信号
        strongest = self._get_strongest_divergence(all_divergences)
        
        return {
            'success': True,
            'divergence_count': len(all_divergences),
            'strongest': {
                'type': strongest.divergence_type.name if strongest else 'NONE',
                'indicator': strongest.indicator if strongest else None,
                'confidence': strongest.confidence if strongest else 0.0,
                'strength': strongest.strength.name if strongest else 'WEAK'
            },
            'macd_divergences': [{
                'index': d.index,
                'type': d.divergence_type.name,
                'confidence': d.confidence,
                'confirmed': d.confirmed
            } for d in macd_divergences[-3:]],
            'rsi_divergences': [{
                'index': d.index,
                'type': d.divergence_type.name,
                'confidence': d.confidence
            } for d in rsi_divergences[-3:]],
            'signal': self._generate_signal(all_divergences)
        }
    
    def _calculate_macd(self, close: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算MACD"""
        close_series = pd.Series(close)
        ema12 = close_series.ewm(span=12, adjust=False).mean()
        ema26 = close_series.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd = (dif - dea) * 2
        return dif.values, dea.values, macd.values
    
    def _calculate_rsi(self, close: np.ndarray, period: int = 14) -> np.ndarray:
        """
        计算RSI（使用EMA算法）
        
        修正：原代码使用SMA算法，应使用EMA算法以符合标准RSI计算方式
        
        Args:
            close: 收盘价序列
            period: RSI周期，默认14
            
        Returns:
            RSI值序列（0-100）
        """
        if len(close) < period + 1:
            return np.full(len(close), 50.0)
        
        close_series = pd.Series(close)
        delta = close_series.diff()
        
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        # 使用EMA而非SMA（关键修正）
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        # 第一个值设为50（无历史数据时的中性值）
        rsi.iloc[0] = 50.0
        
        return rsi.values
    
    def _calculate_kdj(self, high: np.ndarray, low: np.ndarray, 
                       close: np.ndarray, n: int = 9) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算KDJ"""
        k_values = []
        d_values = []
        j_values = []
        
        prev_k = 50.0
        prev_d = 50.0
        
        for i in range(len(close)):
            if i < n - 1:
                k_values.append(50.0)
                d_values.append(50.0)
                j_values.append(50.0)
                continue
            
            # 计算RSV
            high_n = np.max(high[i-n+1:i+1])
            low_n = np.min(low[i-n+1:i+1])
            
            if high_n == low_n:
                rsv = 50.0
            else:
                rsv = (close[i] - low_n) / (high_n - low_n) * 100
            
            # 计算K, D, J
            k = 2/3 * prev_k + 1/3 * rsv
            d = 2/3 * prev_d + 1/3 * k
            j = 3 * k - 2 * d
            
            k_values.append(k)
            d_values.append(d)
            j_values.append(j)
            
            prev_k = k
            prev_d = d
        
        return np.array(k_values), np.array(d_values), np.array(j_values)
    
    def _find_peaks(self, data: np.ndarray, is_high: bool = True) -> List[Tuple[int, float]]:
        """
        寻找极值点（带距离过滤）
        
        Args:
            data: 数据序列
            is_high: True寻找高点，False寻找低点
            
        Returns:
            极值点列表 [(索引, 值), ...]
        """
        peaks = []
        n = len(data)
        
        for i in range(1, n - 1):
            if is_high:
                # 寻找峰值（高点）
                if data[i] > data[i-1] and data[i] > data[i+1]:
                    peaks.append((i, data[i]))
            else:
                # 寻找谷值（低点）
                if data[i] < data[i-1] and data[i] < data[i+1]:
                    peaks.append((i, data[i]))
        
        # 应用min_peak_distance距离过滤（关键修正：原代码未使用此参数）
        if self.min_peak_distance > 1 and len(peaks) > 1:
            filtered_peaks = []
            last_idx = -self.min_peak_distance - 1  # 初始化为足够小的值
            
            for idx, val in peaks:
                if idx - last_idx >= self.min_peak_distance:
                    filtered_peaks.append((idx, val))
                    last_idx = idx
                elif is_high and val > (filtered_peaks[-1][1] if filtered_peaks else 0):
                    # 对于高点，如果距离不够但值更高，替换前一个点
                    if filtered_peaks:
                        filtered_peaks[-1] = (idx, val)
                        last_idx = idx
                elif not is_high and val < (filtered_peaks[-1][1] if filtered_peaks else float('inf')):
                    # 对于低点，如果距离不够但值更低，替换前一个点
                    if filtered_peaks:
                        filtered_peaks[-1] = (idx, val)
                        last_idx = idx
            
            return filtered_peaks
        
        return peaks
    
    def _detect_macd_divergence(self, close: np.ndarray, histogram: np.ndarray, 
                                 macd: np.ndarray) -> List[Divergence]:
        """检测MACD背离"""
        divergences = []
        
        # 使用安全的lookback值
        lookback = getattr(self, '_actual_lookback', self.lookback)
        data_len = len(close)
        
        # 边界检查：确保lookback不超过数据长度
        if lookback >= data_len:
            logger.warning(f"lookback({lookback}) >= 数据长度({data_len})，跳过MACD背离检测")
            return divergences
        
        # 寻找价格高点
        price_highs = self._find_peaks(close[-lookback:], is_high=True)
        # 寻找价格低点
        price_lows = self._find_peaks(close[-lookback:], is_high=False)
        
        # 寻找MACD柱状图高点
        macd_highs = self._find_peaks(histogram[-lookback:], is_high=True)
        # 寻找MACD柱状图低点
        macd_lows = self._find_peaks(histogram[-lookback:], is_high=False)
        
        # 检测顶背离：价格创新高，MACD不创新高
        if len(price_highs) >= 2 and len(macd_highs) >= 2:
            for i in range(len(price_highs) - 1):
                p1_idx, p1_price = price_highs[i]
                p2_idx, p2_price = price_highs[i + 1]
                
                if p2_price > p1_price:  # 价格创新高
                    # 安全的索引计算
                    idx1 = -lookback + p1_idx
                    idx2 = -lookback + p2_idx
                    
                    # 边界检查
                    if abs(idx1) > len(histogram) or abs(idx2) > len(histogram):
                        continue
                    
                    m1_val = histogram[idx1] if -idx1 <= len(histogram) else 0
                    m2_val = histogram[idx2] if -idx2 <= len(histogram) else 0
                    
                    if m2_val < m1_val:  # MACD不创新高
                        strength = self._calculate_strength(m1_val - m2_val, abs(m1_val))
                        confidence = min(1.0, (p2_price - p1_price) / (p1_price + 1e-10) + (m1_val - m2_val) / (abs(m1_val) + 1e-10))
                        
                        div = Divergence(
                            index=data_len - lookback + p2_idx,
                            divergence_type=DivergenceType.TOP_DIVERGENCE,
                            indicator='MACD',
                            price1=p1_price,
                            price2=p2_price,
                            indicator1=m1_val,
                            indicator2=m2_val,
                            strength=strength,
                            confidence=confidence,
                            confirmed=True
                        )
                        divergences.append(div)
        
        # 检测底背离：价格创新低，MACD不创新低
        if len(price_lows) >= 2 and len(macd_lows) >= 2:
            for i in range(len(price_lows) - 1):
                p1_idx, p1_price = price_lows[i]
                p2_idx, p2_price = price_lows[i + 1]
                
                if p2_price < p1_price:  # 价格创新低
                    # 安全的索引计算
                    idx1 = -lookback + p1_idx
                    idx2 = -lookback + p2_idx
                    
                    # 边界检查
                    if abs(idx1) > len(histogram) or abs(idx2) > len(histogram):
                        continue
                    
                    m1_val = histogram[idx1] if -idx1 <= len(histogram) else 0
                    m2_val = histogram[idx2] if -idx2 <= len(histogram) else 0
                    
                    if m2_val > m1_val:  # MACD不创新低（更高）
                        strength = self._calculate_strength(m2_val - m1_val, abs(m1_val) + 1e-10)
                        confidence = min(1.0, (p1_price - p2_price) / (p1_price + 1e-10) + (m2_val - m1_val) / (abs(m1_val) + 1e-10))
                        
                        div = Divergence(
                            index=data_len - lookback + p2_idx,
                            divergence_type=DivergenceType.BOTTOM_DIVERGENCE,
                            indicator='MACD',
                            price1=p1_price,
                            price2=p2_price,
                            indicator1=m1_val,
                            indicator2=m2_val,
                            strength=strength,
                            confidence=confidence,
                            confirmed=True
                        )
                        divergences.append(div)
        
        return divergences
    
    def _detect_rsi_divergence(self, close: np.ndarray, rsi: np.ndarray) -> List[Divergence]:
        """检测RSI背离"""
        divergences = []
        
        # 寻找价格高点
        price_highs = self._find_peaks(close[-self.lookback:], is_high=True)
        # 寻找价格低点
        price_lows = self._find_peaks(close[-self.lookback:], is_high=False)
        
        # 检测顶背离
        if len(price_highs) >= 2:
            for i in range(len(price_highs) - 1):
                p1_idx, p1_price = price_highs[i]
                p2_idx, p2_price = price_highs[i + 1]
                
                if p2_price > p1_price:  # 价格创新高
                    r1_val = rsi[-self.lookback + p1_idx] if p1_idx < len(rsi[-self.lookback:]) else 50
                    r2_val = rsi[-self.lookback + p2_idx] if p2_idx < len(rsi[-self.lookback:]) else 50
                    
                    if r2_val < r1_val:  # RSI不创新高
                        strength = self._calculate_strength(r1_val - r2_val, r1_val)
                        confidence = min(1.0, (p2_price - p1_price) / p1_price + (r1_val - r2_val) / r1_val)
                        
                        div = Divergence(
                            index=len(close) - self.lookback + p2_idx,
                            divergence_type=DivergenceType.TOP_DIVERGENCE,
                            indicator='RSI',
                            price1=p1_price,
                            price2=p2_price,
                            indicator1=r1_val,
                            indicator2=r2_val,
                            strength=strength,
                            confidence=confidence,
                            confirmed=r2_val < 70  # RSI在高位的顶背离更可靠
                        )
                        divergences.append(div)
        
        # 检测底背离
        if len(price_lows) >= 2:
            for i in range(len(price_lows) - 1):
                p1_idx, p1_price = price_lows[i]
                p2_idx, p2_price = price_lows[i + 1]
                
                if p2_price < p1_price:  # 价格创新低
                    r1_val = rsi[-self.lookback + p1_idx] if p1_idx < len(rsi[-self.lookback:]) else 50
                    r2_val = rsi[-self.lookback + p2_idx] if p2_idx < len(rsi[-self.lookback:]) else 50
                    
                    if r2_val > r1_val:  # RSI不创新低
                        strength = self._calculate_strength(r2_val - r1_val, r1_val)
                        confidence = min(1.0, (p1_price - p2_price) / p1_price + (r2_val - r1_val) / r1_val)
                        
                        div = Divergence(
                            index=len(close) - self.lookback + p2_idx,
                            divergence_type=DivergenceType.BOTTOM_DIVERGENCE,
                            indicator='RSI',
                            price1=p1_price,
                            price2=p2_price,
                            indicator1=r1_val,
                            indicator2=r2_val,
                            strength=strength,
                            confidence=confidence,
                            confirmed=r2_val > 30  # RSI在低位的底背离更可靠
                        )
                        divergences.append(div)
        
        return divergences
    
    def _detect_kdj_divergence(self, close: np.ndarray, j: np.ndarray) -> List[Divergence]:
        """检测KDJ背离（使用J值）"""
        divergences = []
        
        price_highs = self._find_peaks(close[-self.lookback:], is_high=True)
        price_lows = self._find_peaks(close[-self.lookback:], is_high=False)
        
        # 顶背离
        if len(price_highs) >= 2:
            for i in range(len(price_highs) - 1):
                p1_idx, p1_price = price_highs[i]
                p2_idx, p2_price = price_highs[i + 1]
                
                if p2_price > p1_price:
                    j1_val = j[-self.lookback + p1_idx] if p1_idx < len(j[-self.lookback:]) else 50
                    j2_val = j[-self.lookback + p2_idx] if p2_idx < len(j[-self.lookback:]) else 50
                    
                    if j2_val < j1_val:
                        strength = self._calculate_strength(j1_val - j2_val, abs(j1_val))
                        confidence = min(1.0, (p2_price - p1_price) / p1_price * 0.5 + (j1_val - j2_val) / (abs(j1_val) + 1) * 0.5)
                        
                        div = Divergence(
                            index=len(close) - self.lookback + p2_idx,
                            divergence_type=DivergenceType.TOP_DIVERGENCE,
                            indicator='KDJ',
                            price1=p1_price,
                            price2=p2_price,
                            indicator1=j1_val,
                            indicator2=j2_val,
                            strength=strength,
                            confidence=confidence,
                            confirmed=j2_val > 100  # J值超买的顶背离更可靠
                        )
                        divergences.append(div)
        
        # 底背离
        if len(price_lows) >= 2:
            for i in range(len(price_lows) - 1):
                p1_idx, p1_price = price_lows[i]
                p2_idx, p2_price = price_lows[i + 1]
                
                if p2_price < p1_price:
                    j1_val = j[-self.lookback + p1_idx] if p1_idx < len(j[-self.lookback:]) else 50
                    j2_val = j[-self.lookback + p2_idx] if p2_idx < len(j[-self.lookback:]) else 50
                    
                    if j2_val > j1_val:
                        strength = self._calculate_strength(j2_val - j1_val, abs(j1_val))
                        confidence = min(1.0, (p1_price - p2_price) / p1_price * 0.5 + (j2_val - j1_val) / (abs(j1_val) + 1) * 0.5)
                        
                        div = Divergence(
                            index=len(close) - self.lookback + p2_idx,
                            divergence_type=DivergenceType.BOTTOM_DIVERGENCE,
                            indicator='KDJ',
                            price1=p1_price,
                            price2=p2_price,
                            indicator1=j1_val,
                            indicator2=j2_val,
                            strength=strength,
                            confidence=confidence,
                            confirmed=j2_val < 0  # J值超卖的底背离更可靠
                        )
                        divergences.append(div)
        
        return divergences
    
    def _detect_volume_divergence(self, close: np.ndarray, volume: np.ndarray) -> List[Divergence]:
        """检测成交量背离"""
        divergences = []
        
        price_highs = self._find_peaks(close[-self.lookback:], is_high=True)
        price_lows = self._find_peaks(close[-self.lookback:], is_high=False)
        
        # 放量不涨（顶背离）
        if len(price_highs) >= 2:
            for i in range(len(price_highs) - 1):
                p1_idx, p1_price = price_highs[i]
                p2_idx, p2_price = price_highs[i + 1]
                
                if p2_price > p1_price:  # 价格创新高
                    v1 = volume[-self.lookback + p1_idx] if p1_idx < len(volume[-self.lookback:]) else 0
                    v2 = volume[-self.lookback + p2_idx] if p2_idx < len(volume[-self.lookback:]) else 0
                    
                    if v2 < v1:  # 成交量不创新高（缩量上涨）
                        div = Divergence(
                            index=len(close) - self.lookback + p2_idx,
                            divergence_type=DivergenceType.TOP_DIVERGENCE,
                            indicator='VOLUME',
                            price1=p1_price,
                            price2=p2_price,
                            indicator1=v1,
                            indicator2=v2,
                            strength=DivergenceStrength.WEAK,
                            confidence=0.5,
                            confirmed=False
                        )
                        divergences.append(div)
        
        return divergences
    
    def _calculate_strength(self, diff: float, base: float) -> DivergenceStrength:
        """计算背离强度"""
        if base == 0:
            return DivergenceStrength.WEAK
        
        ratio = abs(diff / base)
        
        if ratio > 0.5:
            return DivergenceStrength.STRONG
        elif ratio > 0.25:
            return DivergenceStrength.MODERATE
        else:
            return DivergenceStrength.WEAK
    
    def _get_strongest_divergence(self, divergences: List[Divergence]) -> Optional[Divergence]:
        """获取最强背离"""
        if not divergences:
            return None
        
        # 按置信度和强度排序
        strength_map = {
            DivergenceStrength.STRONG: 3,
            DivergenceStrength.MODERATE: 2,
            DivergenceStrength.WEAK: 1
        }
        
        sorted_divs = sorted(
            divergences,
            key=lambda d: (d.confidence * strength_map[d.strength]),
            reverse=True
        )
        
        return sorted_divs[0]
    
    def _generate_signal(self, divergences: List[Divergence]) -> Dict[str, Any]:
        """生成交易信号"""
        if not divergences:
            return {
                'action': 'hold',
                'confidence': 0.0,
                'reason': '无背离信号'
            }
        
        # 统计各类型背离
        top_count = sum(1 for d in divergences if d.divergence_type == DivergenceType.TOP_DIVERGENCE)
        bottom_count = sum(1 for d in divergences if d.divergence_type == DivergenceType.BOTTOM_DIVERGENCE)
        
        # 获取最近的背离
        recent = divergences[-1] if divergences else None
        
        if recent:
            if recent.divergence_type == DivergenceType.BOTTOM_DIVERGENCE:
                return {
                    'action': 'buy',
                    'confidence': recent.confidence,
                    'reason': f'{recent.indicator}底背离(强度:{recent.strength.name})'
                }
            elif recent.divergence_type == DivergenceType.TOP_DIVERGENCE:
                return {
                    'action': 'sell',
                    'confidence': recent.confidence,
                    'reason': f'{recent.indicator}顶背离(强度:{recent.strength.name})'
                }
        
        return {
            'action': 'hold',
            'confidence': 0.5,
            'reason': f'顶背离:{top_count}次, 底背离:{bottom_count}次'
        }


class MultiDivergenceStrategy:
    """
    多重背离策略
    
    参考 QjySDK MACD_Deviate_Boll.cs, RSI_Deviate_Boll.cs
    
    结合多个指标的背离信号，提高胜率
    """
    
    def __init__(self):
        self.detector = DivergenceDetector()
    
    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """综合分析"""
        result = self.detector.detect_all(df)
        
        # 获取各指标背离
        macd_divs = result['macd_divergences']
        rsi_divs = result['rsi_divergences']
        
        # 多重背离确认
        multi_confirmation = self._check_multi_confirmation(macd_divs, rsi_divs)
        
        # 布林带过滤（可选）
        boll_filter = self._bollinger_filter(df)
        
        # 生成最终信号
        signal = result['signal']
        
        if multi_confirmation:
            signal['confidence'] = min(1.0, signal['confidence'] * 1.5)
            signal['reason'] += ' [多重背离确认]'
        
        if boll_filter and signal['action'] != 'hold':
            signal['confidence'] *= 1.2
            signal['reason'] += f' [布林带{boll_filter}]'
        
        return {
            **result,
            'multi_confirmation': multi_confirmation,
            'bollinger_filter': boll_filter,
            'final_signal': signal
        }
    
    def _check_multi_confirmation(self, macd_divs: List, rsi_divs: List) -> bool:
        """检查多重背离确认"""
        if not macd_divs or not rsi_divs:
            return False
        
        # 检查是否有同类型背离在相近位置
        for m in macd_divs[-3:]:
            for r in rsi_divs[-3:]:
                if m['type'] == r['type'] and abs(m['index'] - r['index']) <= 5:
                    return True
        
        return False
    
    def _bollinger_filter(self, df: pd.DataFrame) -> Optional[str]:
        """布林带过滤"""
        close = df['close'].values
        
        # 计算布林带
        close_series = pd.Series(close)
        ma20 = close_series.rolling(20).mean()
        std20 = close_series.rolling(20).std()
        
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        
        current_close = close[-1]
        current_upper = upper.iloc[-1]
        current_lower = lower.iloc[-1]
        
        if current_close >= current_upper:
            return '上轨突破'
        elif current_close <= current_lower:
            return '下轨支撑'
        
        return None


# 便捷函数
def detect_divergence(df: pd.DataFrame) -> Dict[str, Any]:
    """快速背离检测"""
    detector = DivergenceDetector()
    return detector.detect_all(df)


def multi_divergence_signal(df: pd.DataFrame) -> Dict[str, Any]:
    """多重背离交易信号"""
    strategy = MultiDivergenceStrategy()
    return strategy.analyze(df)


if __name__ == '__main__':
    # 测试代码
    np.random.seed(42)
    
    # 生成测试数据（带有背离）
    n = 200
    # 先上涨后下跌，制造顶背离
    t = np.arange(n)
    prices = 10 + 3 * np.sin(2 * np.pi * t / 50) + 0.5 * t / n + np.random.randn(n) * 0.3
    
    # 人为制造顶背离
    prices[150:] = prices[150:] - np.linspace(0, 2, 50)
    
    df = pd.DataFrame({
        'close': prices,
        'high': prices + np.random.rand(n) * 0.5,
        'low': prices - np.random.rand(n) * 0.5,
        'volume': np.random.randint(1000, 10000, n)
    })
    
    # 检测背离
    result = detect_divergence(df)
    print(f"背离检测: {result['strongest']}")
    print(f"交易信号: {result['signal']}")

# -*- coding: utf-8 -*-
"""
傅里叶周期分析模块
参考 QjySDK FourierTransform.cs, RSI_Fourier.cs, MACD_Fourier.cs

使用FFT（快速傅里叶变换）进行：
- 周期识别
- 趋势预测
- 噪音过滤
- 频谱分析

Author: iFlow CLI
Version: 1.0.0
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Optional, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# 检查scipy是否可用
try:
    from scipy import signal as scipy_signal
    from scipy.fft import fft, ifft, fftfreq
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logger.warning("scipy未安装，傅里叶分析功能受限")


@dataclass
class CycleInfo:
    """周期信息"""
    period: int           # 周期长度（天数）
    amplitude: float      # 振幅
    phase: float          # 相位（弧度）
    power: float          # 功率（强度）
    confidence: float     # 置信度


@dataclass
class FourierResult:
    """傅里叶分析结果"""
    dominant_cycles: List[CycleInfo]  # 主导周期
    predicted_trend: str              # 预测趋势（up/down/sideways）
    trend_strength: float             # 趋势强度
    noise_ratio: float                # 噪音比例
    cycle_alignment: float            # 周期共振度
    next_turn_date: Optional[int]     # 预计下次转折点（距离今天的天数）
    filtered_signal: np.ndarray       # 过滤后的信号


class FourierAnalyzer:
    """
    傅里叶周期分析器
    
    核心功能：
    1. 周期识别 - 识别价格周期
    2. 噪音过滤 - FFT低通滤波
    3. 趋势预测 - 基于周期外推
    4. 多周期共振 - 检测多周期同向信号
    """
    
    def __init__(self, 
                 min_period: int = 5,
                 max_period: int = 60,
                 noise_threshold: float = 0.1):
        """
        初始化
        
        Args:
            min_period: 最小周期（天数）
            max_period: 最大周期（天数）
            noise_threshold: 噪音阈值
        """
        self.min_period = min_period
        self.max_period = max_period
        self.noise_threshold = noise_threshold
        
        if not SCIPY_AVAILABLE:
            raise ImportError("需要安装scipy: pip install scipy")
    
    def analyze(self, prices: np.ndarray) -> FourierResult:
        """
        完整傅里叶分析
        
        Args:
            prices: 价格序列
            
        Returns:
            FourierResult对象
        """
        # 1. 数据预处理
        prices = self._preprocess(prices)
        
        # 2. FFT变换
        fft_result, frequencies = self._compute_fft(prices)
        
        # 3. 识别主导周期
        dominant_cycles = self._identify_cycles(fft_result, frequencies, len(prices))
        
        # 4. 噪音过滤
        filtered_signal, noise_ratio = self._filter_noise(prices, fft_result, frequencies)
        
        # 5. 趋势预测
        predicted_trend, trend_strength = self._predict_trend(filtered_signal)
        
        # 6. 周期共振分析
        cycle_alignment = self._check_cycle_alignment(dominant_cycles)
        
        # 7. 预测转折点
        next_turn = self._predict_turning_point(filtered_signal, dominant_cycles)
        
        return FourierResult(
            dominant_cycles=dominant_cycles[:5],  # 取前5个主导周期
            predicted_trend=predicted_trend,
            trend_strength=trend_strength,
            noise_ratio=noise_ratio,
            cycle_alignment=cycle_alignment,
            next_turn_date=next_turn,
            filtered_signal=filtered_signal
        )
    
    def _preprocess(self, prices: np.ndarray) -> np.ndarray:
        """数据预处理：去趋势、归一化"""
        # 去除NaN
        prices = prices[~np.isnan(prices)]
        
        if len(prices) < self.min_period * 2:
            raise ValueError(f"数据长度不足，至少需要{self.min_period * 2}个数据点")
        
        # 去趋势（线性趋势）
        x = np.arange(len(prices))
        coeffs = np.polyfit(x, prices, 1)
        trend = np.polyval(coeffs, x)
        detrended = prices - trend
        
        # 归一化
        normalized = (detrended - np.mean(detrended)) / (np.std(detrended) + 1e-10)
        
        return normalized
    
    def _compute_fft(self, prices: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """计算FFT"""
        n = len(prices)
        
        # FFT变换
        fft_result = fft(prices)
        
        # 计算频率
        frequencies = fftfreq(n, d=1.0)  # d=1表示每天一个采样
        
        return fft_result, frequencies
    
    def _identify_cycles(self, fft_result: np.ndarray, frequencies: np.ndarray, 
                         n: int) -> List[CycleInfo]:
        """识别主导周期"""
        # 只看正频率部分
        positive_mask = frequencies > 0
        positive_freq = frequencies[positive_mask]
        positive_fft = fft_result[positive_mask]
        
        # 计算功率谱
        power = np.abs(positive_fft) ** 2
        
        # 找到主导周期
        cycles = []
        total_power = np.sum(power)
        
        # 按功率排序
        sorted_indices = np.argsort(power)[::-1]
        
        for idx in sorted_indices:
            # 安全检查：确保索引在有效范围内
            if idx >= len(power):
                continue
            freq = positive_freq[idx]
            period = int(1.0 / freq)  # 周期=1/频率
            
            # 过滤周期范围
            if period < self.min_period or period > self.max_period:
                continue
            
            # 过滤已识别周期的谐波
            is_harmonic = False
            for c in cycles:
                if period % c.period == 0 or c.period % period == 0:
                    is_harmonic = True
                    break
            
            if is_harmonic:
                continue
            
            # 计算相位
            phase = np.angle(positive_fft[idx])
            
            # 计算置信度（基于功率占比）- 防止除零
            if total_power > 0:
                confidence = power[idx] / total_power
            else:
                confidence = 0.0
            # 确保置信度在[0, 1]范围内
            confidence = max(0.0, min(1.0, confidence))
            
            cycle = CycleInfo(
                period=period,
                amplitude=np.abs(positive_fft[idx]) / n,
                phase=phase,
                power=power[idx],
                confidence=confidence
            )
            
            cycles.append(cycle)
            
            # 最多识别10个周期
            if len(cycles) >= 10:
                break
        
        return cycles
    
    def _filter_noise(self, prices: np.ndarray, fft_result: np.ndarray,
                      frequencies: np.ndarray) -> Tuple[np.ndarray, float]:
        """噪音过滤（低通滤波）"""
        # 计算功率
        power = np.abs(fft_result) ** 2
        total_power = np.sum(power)
        
        # 防止除零：如果总功率为0，返回原信号
        if total_power <= 0:
            return prices.copy(), 0.0
        
        # 找到主频率阈值
        sorted_power = np.sort(power)[::-1]
        cumulative_power = np.cumsum(sorted_power)
        threshold_idx = np.searchsorted(cumulative_power / total_power, 1 - self.noise_threshold)
        # 防止数组越界
        power_threshold = sorted_power[threshold_idx] if threshold_idx < len(sorted_power) else sorted_power[-1] if len(sorted_power) > 0 else 0
        
        # 创建滤波掩码
        mask = power >= power_threshold
        
        # 应用滤波
        filtered_fft = fft_result * mask
        filtered_signal = np.real(ifft(filtered_fft))
        
        # 计算噪音比例 - 防止除零
        noise_power = total_power - np.sum(power[mask])
        noise_ratio = noise_power / total_power if total_power > 0 else 0.0
        # 确保噪音比例在[0, 1]范围内
        noise_ratio = max(0.0, min(1.0, noise_ratio))
        
        return filtered_signal, noise_ratio
    
    def _predict_trend(self, filtered_signal: np.ndarray) -> Tuple[str, float]:
        """预测趋势"""
        if len(filtered_signal) < 3:
            return 'sideways', 0.0
        
        # 计算最近几点的斜率
        recent = filtered_signal[-5:]
        x = np.arange(len(recent))
        slope = np.polyfit(x, recent, 1)[0]
        
        # 计算斜率的显著性
        std = np.std(recent)
        strength = min(1.0, abs(slope) / (std + 1e-10))
        
        if slope > 0.1:
            return 'up', strength
        elif slope < -0.1:
            return 'down', strength
        else:
            return 'sideways', strength
    
    def _check_cycle_alignment(self, cycles: List[CycleInfo]) -> float:
        """检查周期共振"""
        if len(cycles) < 2:
            return 0.0
        
        # 检查多个周期是否在同一阶段
        alignments = []
        for i, c1 in enumerate(cycles):
            for c2 in cycles[i+1:]:
                # 计算相位差
                phase_diff = abs(c1.phase - c2.phase)
                # 归一化到[0, pi]
                phase_diff = min(phase_diff, 2 * np.pi - phase_diff)
                # 相位越接近，共振度越高
                alignment = 1.0 - phase_diff / np.pi
                # 加权平均
                weighted_alignment = alignment * (c1.confidence + c2.confidence) / 2
                alignments.append(weighted_alignment)
        
        return np.mean(alignments) if alignments else 0.0
    
    def _predict_turning_point(self, filtered_signal: np.ndarray, 
                                cycles: List[CycleInfo]) -> Optional[int]:
        """预测转折点"""
        if not cycles:
            return None
        
        # 使用最强周期预测
        main_cycle = cycles[0]
        period = main_cycle.period
        phase = main_cycle.phase
        
        # 计算当前在周期中的位置
        current_position = (len(filtered_signal) - 1) % period
        
        # 计算到下一个极值点的距离
        # 正弦波的极值点在pi/2和3pi/2
        # 转换到周期位置
        peak_position = int(period * 0.25)  # 四分之一周期
        trough_position = int(period * 0.75)  # 四分之三周期
        
        # 根据当前趋势判断下一个转折点
        recent_trend = np.mean(filtered_signal[-3:]) - np.mean(filtered_signal[-6:-3])
        
        if recent_trend > 0:  # 上升趋势，预测顶部
            # 找最近的峰值位置
            next_peak = peak_position if peak_position > current_position else peak_position + period
            return next_peak - current_position
        else:  # 下降趋势，预测底部
            next_trough = trough_position if trough_position > current_position else trough_position + period
            return next_trough - current_position


class FourierTradingStrategy:
    """
    傅里叶交易策略
    
    结合RSI/MACD + 傅里叶周期分析
    参考 QjySDK 的 RSI_Fourier.cs 和 MACD_Fourier.cs
    """
    
    def __init__(self):
        self.analyzer = FourierAnalyzer()
    
    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        综合分析
        
        Args:
            df: K线数据，需包含 close, high, low 列
            
        Returns:
            分析结果字典
        """
        close = df['close'].values
        
        # 傅里叶周期分析
        try:
            fourier_result = self.analyzer.analyze(close)
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'signal': 'hold',
                'confidence': 0.0
            }
        
        # 计算RSI
        rsi = self._calculate_rsi(close)
        
        # 计算MACD
        macd, signal_line, histogram = self._calculate_macd(close)
        
        # 综合判断
        signal = self._generate_signal(fourier_result, rsi, macd, histogram)
        
        return {
            'success': True,
            'signal': signal['action'],
            'confidence': signal['confidence'],
            'reason': signal['reason'],
            'fourier': {
                'dominant_period': fourier_result.dominant_cycles[0].period if fourier_result.dominant_cycles else None,
                'predicted_trend': fourier_result.predicted_trend,
                'trend_strength': fourier_result.trend_strength,
                'cycle_alignment': fourier_result.cycle_alignment,
                'next_turn_days': fourier_result.next_turn_date
            },
            'rsi': {
                'current': rsi[-1] if len(rsi) > 0 else None,
                'oversold': rsi[-1] < 30 if len(rsi) > 0 else False,
                'overbought': rsi[-1] > 70 if len(rsi) > 0 else False
            },
            'macd': {
                'histogram': histogram[-1] if len(histogram) > 0 else None,
                'bullish_cross': macd[-1] > signal_line[-1] if len(macd) > 1 and len(signal_line) > 1 else False
            }
        }
    
    def _calculate_rsi(self, close: np.ndarray, period: int = 14) -> np.ndarray:
        """计算RSI"""
        delta = np.diff(close)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        
        avg_gain = np.convolve(gain, np.ones(period)/period, mode='valid')
        avg_loss = np.convolve(loss, np.ones(period)/period, mode='valid')
        
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_macd(self, close: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """计算MACD"""
        close_series = pd.Series(close)
        ema12 = close_series.ewm(span=12, adjust=False).mean()
        ema26 = close_series.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd = (dif - dea) * 2
        
        return dif.values, dea.values, macd.values
    
    def _generate_signal(self, fourier: FourierResult, rsi: np.ndarray, 
                         macd: np.ndarray, histogram: np.ndarray) -> Dict[str, Any]:
        """生成交易信号"""
        score = 0.0
        reasons = []
        
        # 傅里叶周期信号
        if fourier.cycle_alignment > 0.7:
            if fourier.predicted_trend == 'up':
                score += 2.0
                reasons.append(f"多周期共振向上(强度{fourier.trend_strength:.2f})")
            elif fourier.predicted_trend == 'down':
                score -= 2.0
                reasons.append(f"多周期共振向下(强度{fourier.trend_strength:.2f})")
        
        # RSI信号 + 周期确认
        if len(rsi) > 0:
            current_rsi = rsi[-1]
            if current_rsi < 30:
                # RSI超卖 + 周期底部确认
                if fourier.next_turn_date and fourier.next_turn_date <= 3:
                    score += 1.5
                    reasons.append(f"RSI超卖({current_rsi:.1f})+周期底部确认")
                else:
                    score += 0.5
                    reasons.append(f"RSI超卖({current_rsi:.1f})")
            elif current_rsi > 70:
                if fourier.next_turn_date and fourier.next_turn_date <= 3:
                    score -= 1.5
                    reasons.append(f"RSI超买({current_rsi:.1f})+周期顶部确认")
                else:
                    score -= 0.5
                    reasons.append(f"RSI超买({current_rsi:.1f})")
        
        # MACD信号
        if len(histogram) > 1:
            if histogram[-1] > 0 and histogram[-2] <= 0:
                score += 1.0
                reasons.append("MACD金叉")
            elif histogram[-1] < 0 and histogram[-2] >= 0:
                score -= 1.0
                reasons.append("MACD死叉")
        
        # 生成最终信号
        if score >= 2.0:
            return {
                'action': 'buy',
                'confidence': min(1.0, score / 4.0),
                'reason': '; '.join(reasons)
            }
        elif score <= -2.0:
            return {
                'action': 'sell',
                'confidence': min(1.0, abs(score) / 4.0),
                'reason': '; '.join(reasons)
            }
        else:
            return {
                'action': 'hold',
                'confidence': 0.5,
                'reason': '信号不明确: ' + '; '.join(reasons) if reasons else '无明显信号'
            }


# 便捷函数
def analyze_fourier(prices: np.ndarray) -> FourierResult:
    """快速傅里叶分析"""
    analyzer = FourierAnalyzer()
    return analyzer.analyze(prices)


def fourier_trading_signal(df: pd.DataFrame) -> Dict[str, Any]:
    """傅里叶交易信号"""
    strategy = FourierTradingStrategy()
    return strategy.analyze(df)


if __name__ == '__main__':
    # 测试代码
    np.random.seed(42)
    
    # 生成带有周期性的测试数据
    n = 200
    t = np.arange(n)
    # 20天周期 + 40天周期 + 噪音
    prices = 10 + 2 * np.sin(2 * np.pi * t / 20) + 1 * np.sin(2 * np.pi * t / 40) + np.random.randn(n) * 0.5
    
    # 分析
    result = analyze_fourier(prices)
    print(f"主导周期: {[c.period for c in result.dominant_cycles[:3]]}")
    print(f"预测趋势: {result.predicted_trend}")
    print(f"周期共振: {result.cycle_alignment:.2f}")

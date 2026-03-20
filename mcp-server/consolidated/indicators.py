"""
技术指标模块 - 合并版
整合以下模块:
- technical_analysis.py (技术分析)
- vectorized_indicators.py (向量化指标)
- technical_indicators.py (stock-trading-system)
- indicators.js (Node.js版本) 的Python实现
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Union
from dataclasses import dataclass
from enum import Enum


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class IndicatorResult:
    """指标结果"""
    name: str
    value: float
    signal: SignalType
    details: Dict = None


class TechnicalIndicators:
    """技术指标计算器"""
    
    # ==================== 均线类 ====================
    
    @staticmethod
    def ma(prices: Union[List, np.ndarray], period: int) -> np.ndarray:
        """简单移动平均 MA"""
        prices = np.array(prices)
        if len(prices) < period:
            return np.array([])
        
        result = np.convolve(prices, np.ones(period)/period, mode='valid')
        return result
    
    @staticmethod
    def ema(prices: Union[List, np.ndarray], period: int) -> np.ndarray:
        """指数移动平均 EMA"""
        prices = np.array(prices)
        if len(prices) < period:
            return np.array([])
        
        k = 2 / (period + 1)
        ema = np.zeros(len(prices))
        ema[period-1] = np.mean(prices[:period])
        
        for i in range(period, len(prices)):
            ema[i] = prices[i] * k + ema[i-1] * (1 - k)
        
        return ema[period-1:]
    
    @staticmethod
    def sma(prices: Union[List, np.ndarray], period: int) -> np.ndarray:
        """简单移动平均 (别名)"""
        return TechnicalIndicators.ma(prices, period)
    
    # ==================== 趋势类 ====================
    
    @staticmethod
    def macd(prices: Union[List, np.ndarray], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """MACD指标"""
        prices = np.array(prices)
        if len(prices) < slow + signal:
            return {"dif": [], "dea": [], "macd": []}
        
        # 计算EMA
        def calc_ema(data, period):
            k = 2 / (period + 1)
            ema = np.zeros(len(data))
            ema[period-1] = np.mean(data[:period])
            for i in range(period, len(data)):
                ema[i] = data[i] * k + ema[i-1] * (1 - k)
            return ema
        
        ema_fast = calc_ema(prices, fast)
        ema_slow = calc_ema(prices, slow)
        
        # DIF
        dif = ema_fast - ema_slow
        
        # DEA (DIF的EMA)
        dea_full = calc_ema(dif[slow-1:], signal)
        # 使用列表而非数组避免广播错误
        dea = list(dea_full)
        
        # MACD - 取有效部分
        valid_len = len(dea)
        dif_valid = dif[-(valid_len + signal -1):][-valid_len:]
        
        macd_line = [(d - dea[i]) * 2 for i, d in enumerate(dif_valid[-valid_len:])]
        
        return {
            "dif": list(dif_valid[-valid_len:]),
            "dea": dea[-valid_len:],
            "macd": macd_line,
        }
    
    @staticmethod
    def kdj(highs: Union[List, np.ndarray], lows: Union[List, np.ndarray], 
            closes: Union[List, np.ndarray], n: int = 9, m1: int = 3, m2: int = 3) -> Dict:
        """KDJ指标"""
        highs, lows, closes = np.array(highs), np.array(lows), np.array(closes)
        if len(closes) < n:
            return {"k": [], "d": [], "j": []}
        
        k, d = 50.0, 50.0
        k_list, d_list, j_list = [], [], []
        
        for i in range(n-1, len(closes)):
            hn = np.max(highs[i-n+1:i+1])
            ln = np.min(lows[i-n+1:i+1])
            
            if hn == ln:
                rsv = 50
            else:
                rsv = (closes[i] - ln) / (hn - ln) * 100
            
            k = (m1 - 1) / m1 * k + 1 / m1 * rsv
            d = (m2 - 1) / m2 * d + 1 / m2 * k
            j = 3 * k - 2 * d
            
            k_list.append(k)
            d_list.append(d)
            j_list.append(j)
        
        
        return {"k": k_list, "d": d_list, "j": j_list}
    
    # ==================== 震荡类 ====================
    
    @staticmethod
    def rsi(prices: Union[List, np.ndarray], period: int = 14) -> np.ndarray:
        """RSI相对强弱指标"""
        prices = np.array(prices)
        if len(prices) < period + 1:
            return np.array([])
        
        changes = np.diff(prices)
        gains = np.where(changes > 0, changes, 0)
        losses = np.where(changes < 0, -changes, 0)
        
        avg_gains = np.convolve(gains, np.ones(period)/period, mode='valid')
        avg_losses = np.convolve(losses, np.ones(period)/period, mode='valid')
        
        rs = np.where(avg_losses == 0, 100, avg_gains / avg_losses)
        rsi = 100 - 100 / (1 + rs)
        
        return rsi
    
    @staticmethod
    def willr(highs: Union[List, np.ndarray], lows: Union[List, np.ndarray],
              closes: Union[List, np.ndarray], period: int = 14) -> np.ndarray:
        """威廉指标 Williams %R"""
        highs, lows, closes = np.array(highs), np.array(lows), np.array(closes)
        if len(closes) < period:
            return np.array([])
        
        willr = []
        for i in range(period-1, len(closes)):
            hn = np.max(highs[i-period+1:i+1])
            ln = np.min(lows[i-period+1:i+1])
            if hn == ln:
                w = -50
            else:
                w = (hn - closes[i]) / (hn - ln) * -100
            willr.append(w)
        
        return np.array(willr)
    
    @staticmethod
    def cci(highs: Union[List, np.ndarray], lows: Union[List, np.ndarray],
            closes: Union[List, np.ndarray], period: int = 20) -> np.ndarray:
        """CCI顺势指标"""
        highs, lows, closes = np.array(highs), np.array(lows), np.array(closes)
        if len(closes) < period:
            return np.array([])
        
        tp = (highs + lows + closes) / 3
        cci = []
        
        for i in range(period-1, len(closes)):
            tp_window = tp[i-period+1:i+1]
            ma = np.mean(tp_window)
            md = np.mean(np.abs(tp_window - ma))
            if md == 0:
                cci.append(0)
            else:
                cci.append((tp[i] - ma) / (0.015 * md))
        
        return np.array(cci)
    
    # ==================== 波动类 ====================
    
    @staticmethod
    def bollinger(prices: Union[List, np.ndarray], period: int = 20, 
                  std_dev: float = 2.0) -> Dict:
        """布林带 Bollinger Bands"""
        prices = np.array(prices)
        if len(prices) < period:
            return {"mid": [], "upper": [], "lower": []}
        
        mid, upper, lower = [], [], []
        
        for i in range(period-1, len(prices)):
            window = prices[i-period+1:i+1]
            m = np.mean(window)
            s = np.std(window)
            mid.append(m)
            upper.append(m + std_dev * s)
            lower.append(m - std_dev * s)
        
        return {"mid": mid, "upper": upper, "lower": lower}
    
    @staticmethod
    def atr(highs: Union[List, np.ndarray], lows: Union[List, np.ndarray],
            closes: Union[List, np.ndarray], period: int = 14) -> np.ndarray:
        """ATR平均真实波幅"""
        highs, lows, closes = np.array(highs), np.array(lows), np.array(closes)
        if len(closes) < period + 1:
            return np.array([])
        
        tr = []
        for i in range(1, len(closes)):
            tr_val = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            tr.append(tr_val)
        
        atr = np.convolve(tr, np.ones(period)/period, mode='valid')
        return atr
    
    # ==================== 成交量类 ====================
    
    @staticmethod
    def obv(prices: Union[List, np.ndarray], volumes: Union[List, np.ndarray]) -> np.ndarray:
        """OBV能量潮"""
        prices, volumes = np.array(prices), np.array(volumes)
        if len(prices) < 2:
            return np.array([])
        
        obv = [0]
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                obv.append(obv[-1] + volumes[i])
            elif prices[i] < prices[i-1]:
                obv.append(obv[-1] - volumes[i])
            else:
                obv.append(obv[-1])
        
        return np.array(obv)
    
    @staticmethod
    def vol_ma(volumes: Union[List, np.ndarray], period: int = 20) -> Dict:
        """成交量均线"""
        volumes = np.array(volumes)
        if len(volumes) < period:
            return {"current": volumes[-1] if len(volumes) > 0 else 0, "avg": 0, "ratio": 1}
        
        avg = np.mean(volumes[-period:])
        current = volumes[-1]
        return {
            "current": current,
            "avg": avg,
            "ratio": current / avg if avg > 0 else 1,
        }
    
    # ==================== 综合信号 ====================
    
    @staticmethod
    def generate_signal(df: pd.DataFrame) -> Dict:
        """
        生成综合交易信号
        
        Args:
            df: DataFrame with columns [open, high, low, close, volume]
        
        Returns:
            Dict with signals and final recommendation
        """
        signals = []
        
        close = df['close'].values
        high = df['high'].values if 'high' in df.columns else close
        low = df['low'].values if 'low' in df.columns else close
        volume = df['volume'].values if 'volume' in df.columns else np.ones(len(close))
        
        # MACD信号
        macd = TechnicalIndicators.macd(close)
        if macd.get('dif') and len(macd['dif']) >= 2:
            if macd['dif'][-1] > macd['dea'][-1] and macd['dif'][-2] <= macd['dea'][-2]:
                signals.append({"indicator": "MACD", "signal": "BUY", "reason": "金叉"})
            elif macd['dif'][-1] < macd['dea'][-1] and macd['dif'][-2] >= macd['dea'][-2]:
                signals.append({"indicator": "MACD", "signal": "SELL", "reason": "死叉"})
        
        # KDJ信号
        kdj = TechnicalIndicators.kdj(high, low, close)
        if kdj['k']:
            k = kdj['k'][-1]
            if k < 20:
                signals.append({"indicator": "KDJ", "signal": "BUY", "reason": f"超卖(K={k:.1f})"})
            elif k > 80:
                signals.append({"indicator": "KDJ", "signal": "SELL", "reason": f"超买(K={k:.1f})"})
        
        # RSI信号
        rsi = TechnicalIndicators.rsi(close)
        if len(rsi) > 0:
            r = rsi[-1]
            if r < 30:
                signals.append({"indicator": "RSI", "signal": "BUY", "reason": f"超卖({r:.1f})"})
            elif r > 70:
                signals.append({"indicator": "RSI", "signal": "SELL", "reason": f"超买({r:.1f})"})
        
        # 布林带信号
        boll = TechnicalIndicators.bollinger(close)
        if boll.get('upper'):
            price = close[-1]
            if price < boll['lower'][-1]:
                signals.append({"indicator": "BOLL", "signal": "BUY", "reason": "跌破下轨"})
            elif price > boll['upper'][-1]:
                signals.append({"indicator": "BOLL", "signal": "SELL", "reason": "突破上轨"})
        
        # 均线信号
        if len(close) >= 20:
            ma5 = TechnicalIndicators.ma(close, 5)[-1]
            ma20 = TechnicalIndicators.ma(close, 20)[-1]
            if ma5 > ma20 and close[-1] > ma5:
                signals.append({"indicator": "MA", "signal": "BUY", "reason": "多头排列"})
            elif ma5 < ma20 and close[-1] < ma5:
                signals.append({"indicator": "MA", "signal": "SELL", "reason": "空头排列"})
        
        # 综合判断
        buy_count = sum(1 for s in signals if s['signal'] == 'BUY')
        sell_count = sum(1 for s in signals if s['signal'] == 'SELL')
        
        if buy_count > sell_count:
            final = "BUY"
        elif sell_count > buy_count:
            final = "SELL"
        else:
            final = "HOLD"
        
        return {
            "signals": signals,
            "final_signal": final,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "confidence": max(buy_count, sell_count) / len(signals) if signals else 0.5,
        }


# ============================================================
# 向量化版本 (高性能)
# ============================================================

class VectorizedIndicators:
    """向量化指标计算 - 高性能版本"""
    
    @staticmethod
    def all_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        一次性计算所有常用指标
        
        Args:
            df: DataFrame with [open, high, low, close, volume]
        
        Returns:
            DataFrame with all indicators added
        """
        result = df.copy()
        
        # 均线
        for period in [5, 10, 20, 60]:
            result[f'ma{period}'] = result['close'].rolling(period).mean()
        
        # MACD
        ema12 = result['close'].ewm(span=12).mean()
        ema26 = result['close'].ewm(span=26).mean()
        result['dif'] = ema12 - ema26
        result['dea'] = result['dif'].ewm(span=9).mean()
        result['macd'] = (result['dif'] - result['dea']) * 2
        
        # RSI
        delta = result['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        result['rsi'] = 100 - 100 / (1 + rs)
        
        # 布林带
        result['boll_mid'] = result['close'].rolling(20).mean()
        result['boll_std'] = result['close'].rolling(20).std()
        result['boll_upper'] = result['boll_mid'] + 2 * result['boll_std']
        result['boll_lower'] = result['boll_mid'] - 2 * result['boll_std']
        
        # ATR
        tr1 = result['high'] - result['low']
        tr2 = abs(result['high'] - result['close'].shift(1))
        tr3 = abs(result['low'] - result['close'].shift(1))
        result['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        result['atr'] = result['tr'].rolling(14).mean()
        
        return result


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    import random
    
    print("=" * 60)
    print("技术指标模块测试 - 合并版")
    print("=" * 60)
    
    # 生成测试数据
    np.random.seed(42)
    n = 100
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    high = close + np.abs(np.random.randn(n) * 1.5)
    low = close - np.abs(np.random.randn(n) * 1.5)
    volume = np.random.randint(1000000, 10000000, n)
    
    print("\n1. MA均线:")
    ma5 = TechnicalIndicators.ma(close, 5)
    ma20 = TechnicalIndicators.ma(close, 20)
    print(f"   MA5最后值: {ma5[-1]:.2f}")
    print(f"   MA20最后值: {ma20[-1]:.2f}")
    
    print("\n2. MACD:")
    macd = TechnicalIndicators.macd(close)
    print(f"   DIF: {macd['dif'][-1]:.4f}")
    print(f"   DEA: {macd['dea'][-1]:.4f}")
    print(f"   MACD: {macd['macd'][-1]:.4f}")
    
    print("\n3. KDJ:")
    kdj = TechnicalIndicators.kdj(high, low, close)
    print(f"   K: {kdj['k'][-1]:.2f}")
    print(f"   D: {kdj['d'][-1]:.2f}")
    print(f"   J: {kdj['j'][-1]:.2f}")
    
    print("\n4. RSI:")
    rsi = TechnicalIndicators.rsi(close)
    print(f"   RSI(14): {rsi[-1]:.2f}")
    
    print("\n5. 布林带:")
    boll = TechnicalIndicators.bollinger(close)
    print(f"   中轨: {boll['mid'][-1]:.2f}")
    print(f"   上轨: {boll['upper'][-1]:.2f}")
    print(f"   下轨: {boll['lower'][-1]:.2f}")
    
    # 测试综合信号
    print("\n6. 综合信号:")
    df = pd.DataFrame({
        'open': close + np.random.randn(n),
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })
    signal = TechnicalIndicators.generate_signal(df)
    print(f"   最终信号: {signal['final_signal']}")
    print(f"   买入信号: {signal['buy_count']}个")
    print(f"   卖出信号: {signal['sell_count']}个")
    
    print("\n" + "=" * 60)
    print("测试完成!")

# -*- coding: utf-8 -*-
"""
股票回测框架 - stock_backtest.py
包含9种策略对比、性能指标计算、统计显著性检验
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple, Callable
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from scipy import stats
import warnings
warnings.filterwarnings('ignore')


# ==================== 信号枚举 ====================
class Signal(Enum):
    """交易信号"""
    BUY = 1
    SELL = -1
    HOLD = 0


class Position(Enum):
    """持仓状态"""
    LONG = 1
    SHORT = -1
    FLAT = 0


# ==================== 数据结构 ====================
@dataclass
class Trade:
    """单笔交易记录"""
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    quantity: int
    signal: Signal
    pnl: float = 0.0
    pnl_pct: float = 0.0
    
    def __post_init__(self):
        if self.signal == Signal.BUY:
            self.pnl = (self.exit_price - self.entry_price) * self.quantity
            self.pnl_pct = (self.exit_price - self.entry_price) / self.entry_price
        else:
            self.pnl = (self.entry_price - self.exit_price) * self.quantity
            self.pnl_pct = (self.entry_price - self.exit_price) / self.entry_price


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    ticker: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    trades: List[Trade] = field(default_factory=list)
    daily_returns: np.ndarray = field(default_factory=lambda: np.array([]))
    equity_curve: np.ndarray = field(default_factory=lambda: np.array([]))
    metrics: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'strategy': self.strategy_name,
            'ticker': self.ticker,
            'period': f"{self.start_date.date()} ~ {self.end_date.date()}",
            'initial_capital': self.initial_capital,
            'final_capital': self.final_capital,
            'total_return': f"{self.total_return:.2%}",
            'annual_return': f"{self.annual_return:.2%}",
            'num_trades': len(self.trades),
            **self.metrics
        }


@dataclass
class ComparisonReport:
    """策略对比报告"""
    ticker: str
    period: Tuple[datetime, datetime]
    results: List[BacktestResult]
    rankings: List[Tuple[str, float]]  # (strategy_name, metric_value)
    statistical_tests: Dict[str, Dict] = field(default_factory=dict)
    
    def get_best_strategy(self, metric: str = 'sharpe_ratio') -> BacktestResult:
        """获取最佳策略"""
        sorted_results = sorted(
            self.results,
            key=lambda x: x.metrics.get(metric, -np.inf),
            reverse=True
        )
        return sorted_results[0]
    
    def to_dataframe(self) -> pd.DataFrame:
        """转换为DataFrame"""
        data = [r.to_dict() for r in self.results]
        df = pd.DataFrame(data)
        return df.sort_values('sharpe_ratio', ascending=False)


# ==================== 策略基类 ====================
class BaseStrategy(ABC):
    """策略基类"""
    
    def __init__(self, name: str = "BaseStrategy"):
        self.name = name
        self.position = Position.FLAT
        self.entry_price = 0.0
    
    @abstractmethod
    def generate_signal(self, data: pd.DataFrame, current_idx: int) -> Signal:
        """
        生成交易信号
        
        Args:
            data: 包含OHLCV的DataFrame
            current_idx: 当前数据索引位置
            
        Returns:
            Signal枚举值
        """
        pass
    
    def reset(self):
        """重置策略状态"""
        self.position = Position.FLAT
        self.entry_price = 0.0


# ==================== 9种策略实现 ====================

class BuyHoldStrategy(BaseStrategy):
    """买入持有策略"""
    
    def __init__(self):
        super().__init__("Buy & Hold")
        self.has_bought = False
    
    def generate_signal(self, data: pd.DataFrame, current_idx: int) -> Signal:
        if not self.has_bought:
            self.has_bought = True
            return Signal.BUY
        return Signal.HOLD
    
    def reset(self):
        super().reset()
        self.has_bought = False


class MomentumStrategy(BaseStrategy):
    """动量策略 - 价格突破N日高点买入，跌破N日低点卖出"""
    
    def __init__(self, lookback: int = 20):
        super().__init__(f"Momentum({lookback})")
        self.lookback = lookback
    
    def generate_signal(self, data: pd.DataFrame, current_idx: int) -> Signal:
        if current_idx < self.lookback:
            return Signal.HOLD
        
        window = data.iloc[current_idx - self.lookback:current_idx + 1]
        current_close = data.iloc[current_idx]['close']
        high = window['high'].max()
        low = window['low'].min()
        
        if self.position == Position.FLAT:
            if current_close >= high:
                return Signal.BUY
        elif self.position == Position.LONG:
            if current_close <= low:
                return Signal.SELL
        
        return Signal.HOLD


class MeanReversionStrategy(BaseStrategy):
    """均值回归策略 - 价格偏离均值超过阈值时反向操作"""
    
    def __init__(self, window: int = 20, threshold: float = 2.0):
        super().__init__(f"MeanReversion({window},{threshold})")
        self.window = window
        self.threshold = threshold  # Z-score阈值
    
    def generate_signal(self, data: pd.DataFrame, current_idx: int) -> Signal:
        if current_idx < self.window:
            return Signal.HOLD
        
        window_data = data.iloc[current_idx - self.window:current_idx + 1]['close']
        current_close = data.iloc[current_idx]['close']
        
        mean = window_data.mean()
        std = window_data.std()
        
        if std == 0:
            return Signal.HOLD
        
        z_score = (current_close - mean) / std
        
        if self.position == Position.FLAT:
            if z_score < -self.threshold:
                return Signal.BUY  # 价格过低，买入
        elif self.position == Position.LONG:
            if z_score > self.threshold:
                return Signal.SELL  # 价格过高，卖出
        
        return Signal.HOLD


class MovingAverageStrategy(BaseStrategy):
    """移动均线策略 - 快均线上穿慢均线买入，下穿卖出"""
    
    def __init__(self, fast: int = 5, slow: int = 20):
        super().__init__(f"MA({fast},{slow})")
        self.fast = fast
        self.slow = slow
    
    def generate_signal(self, data: pd.DataFrame, current_idx: int) -> Signal:
        if current_idx < self.slow:
            return Signal.HOLD
        
        closes = data['close'].iloc[:current_idx + 1]
        fast_ma = closes.rolling(self.fast).mean().iloc[-1]
        slow_ma = closes.rolling(self.slow).mean().iloc[-1]
        prev_fast_ma = closes.rolling(self.fast).mean().iloc[-2]
        prev_slow_ma = closes.rolling(self.slow).mean().iloc[-2]
        
        # 金叉
        if prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma:
            if self.position != Position.LONG:
                return Signal.BUY
        # 死叉
        elif prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma:
            if self.position == Position.LONG:
                return Signal.SELL
        
        return Signal.HOLD


class RSIStrategy(BaseStrategy):
    """RSI策略 - 超卖买入，超买卖出"""
    
    def __init__(self, period: int = 14, oversold: float = 30, overbought: float = 70):
        super().__init__(f"RSI({period})")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
    
    def _calculate_rsi(self, closes: pd.Series) -> float:
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.period).mean()
        
        # 防止除零产生NaN，用NaN替换0值
        loss_safe = loss.replace(0, np.nan)
        rs = gain / loss_safe
        rsi = 100 - (100 / (1 + rs))
        rsi_value = rsi.iloc[-1]
        # 如果RSI为NaN，返回中性值50
        return rsi_value if not np.isnan(rsi_value) else 50.0
    
    def generate_signal(self, data: pd.DataFrame, current_idx: int) -> Signal:
        if current_idx < self.period + 1:
            return Signal.HOLD
        
        closes = data['close'].iloc[:current_idx + 1]
        rsi = self._calculate_rsi(closes)
        
        if self.position == Position.FLAT:
            if rsi < self.oversold:
                return Signal.BUY
        elif self.position == Position.LONG:
            if rsi > self.overbought:
                return Signal.SELL
        
        return Signal.HOLD


class BollingerStrategy(BaseStrategy):
    """布林带策略 - 价格触及下轨买入，触及上轨卖出"""
    
    def __init__(self, period: int = 20, std_dev: float = 2.0):
        super().__init__(f"Bollinger({period})")
        self.period = period
        self.std_dev = std_dev
    
    def generate_signal(self, data: pd.DataFrame, current_idx: int) -> Signal:
        if current_idx < self.period:
            return Signal.HOLD
        
        closes = data['close'].iloc[current_idx - self.period:current_idx + 1]
        current_close = data.iloc[current_idx]['close']
        
        middle = closes.mean()
        std = closes.std()
        upper = middle + self.std_dev * std
        lower = middle - self.std_dev * std
        
        if self.position == Position.FLAT:
            if current_close <= lower:
                return Signal.BUY
        elif self.position == Position.LONG:
            if current_close >= upper:
                return Signal.SELL
        
        return Signal.HOLD


class MACDStrategy(BaseStrategy):
    """MACD策略 - MACD金叉买入，死叉卖出"""
    
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        super().__init__(f"MACD({fast},{slow},{signal})")
        self.fast = fast
        self.slow = slow
        self.signal = signal
    
    def _calculate_macd(self, closes: pd.Series) -> Tuple[float, float]:
        ema_fast = closes.ewm(span=self.fast).mean()
        ema_slow = closes.ewm(span=self.slow).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=self.signal).mean()
        return macd.iloc[-1], signal_line.iloc[-1]
    
    def generate_signal(self, data: pd.DataFrame, current_idx: int) -> Signal:
        if current_idx < self.slow + self.signal:
            return Signal.HOLD
        
        closes = data['close'].iloc[:current_idx + 1]
        macd, signal = self._calculate_macd(closes)
        
        prev_closes = data['close'].iloc[:current_idx]
        prev_macd, prev_signal = self._calculate_macd(prev_closes)
        
        # 金叉
        if prev_macd <= prev_signal and macd > signal:
            if self.position != Position.LONG:
                return Signal.BUY
        # 死叉
        elif prev_macd >= prev_signal and macd < signal:
            if self.position == Position.LONG:
                return Signal.SELL
        
        return Signal.HOLD


class RandomWalkStrategy(BaseStrategy):
    """随机游走策略 - 随机生成信号（作为基准）"""
    
    def __init__(self, seed: int = None):
        super().__init__("RandomWalk")
        self.rng = np.random.default_rng(seed)
        self.trade_count = 0
        self.max_trades = 50
    
    def generate_signal(self, data: pd.DataFrame, current_idx: int) -> Signal:
        # 限制交易次数
        if self.trade_count >= self.max_trades:
            return Signal.HOLD
        
        # 随机决定是否交易
        if self.rng.random() < 0.05:  # 5%概率交易
            self.trade_count += 1
            if self.position == Position.FLAT:
                return Signal.BUY if self.rng.random() > 0.5 else Signal.HOLD
            else:
                return Signal.SELL if self.rng.random() > 0.3 else Signal.HOLD
        
        return Signal.HOLD
    
    def reset(self):
        super().reset()
        self.trade_count = 0


class AIAgentStrategy(BaseStrategy):
    """AI Agent策略 - 基于机器学习预测的信号"""
    
    def __init__(self, model=None, feature_func=None):
        super().__init__("AI Agent")
        self.model = model
        self.feature_func = feature_func
        self.confidence_threshold = 0.6
    
    def set_model(self, model, feature_func: Callable):
        """设置模型和特征函数"""
        self.model = model
        self.feature_func = feature_func
    
    def generate_signal(self, data: pd.DataFrame, current_idx: int) -> Signal:
        if self.model is None or self.feature_func is None:
            return Signal.HOLD
        
        try:
            features = self.feature_func(data.iloc[:current_idx + 1])
            if features is None or len(features) == 0:
                return Signal.HOLD
            
            # 假设模型返回概率
            if hasattr(self.model, 'predict_proba'):
                proba = self.model.predict_proba([features])[0]
                confidence = max(proba)
                prediction = np.argmax(proba)
            else:
                prediction = self.model.predict([features])[0]
                confidence = 1.0
            
            if confidence < self.confidence_threshold:
                return Signal.HOLD
            
            # prediction: 1=涨, 0=跌
            if self.position == Position.FLAT:
                if prediction == 1:
                    return Signal.BUY
            elif self.position == Position.LONG:
                if prediction == 0:
                    return Signal.SELL
        
        except Exception as e:
            pass
        
        return Signal.HOLD


# ==================== 性能指标计算 ====================
class PerformanceMetrics:
    """性能指标计算类"""
    
    @staticmethod
    def sharpe_ratio(returns: np.ndarray, risk_free_rate: float = 0.03) -> float:
        """
        计算夏普比率
        
        Args:
            returns: 日收益率数组
            risk_free_rate: 年化无风险利率
            
        Returns:
            夏普比率
        """
        if len(returns) == 0 or np.std(returns) == 0:
            return 0.0
        
        daily_rf = risk_free_rate / 252
        excess_returns = returns - daily_rf
        
        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)
    
    @staticmethod
    def sortino_ratio(returns: np.ndarray, risk_free_rate: float = 0.03) -> float:
        """
        计算索提诺比率（只考虑下行风险）
        
        Args:
            returns: 日收益率数组
            risk_free_rate: 年化无风险利率
            
        Returns:
            索提诺比率
        """
        if len(returns) == 0:
            return 0.0
        
        daily_rf = risk_free_rate / 252
        excess_returns = returns - daily_rf
        
        # 只计算负收益的标准差
        negative_returns = returns[returns < 0]
        if len(negative_returns) == 0:
            return np.inf
        
        downside_std = np.std(negative_returns)
        if downside_std == 0:
            return np.inf
        
        return np.mean(excess_returns) / downside_std * np.sqrt(252)
    
    @staticmethod
    def max_drawdown(returns: np.ndarray) -> float:
        """
        计算最大回撤
        
        Args:
            returns: 日收益率数组
            
        Returns:
            最大回撤（正数）
        """
        if len(returns) == 0:
            return 0.0
        
        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (running_max - cumulative) / running_max
        
        return np.max(drawdowns)
    
    @staticmethod
    def calmar_ratio(returns: np.ndarray, risk_free_rate: float = 0.03) -> float:
        """
        计算卡玛比率
        
        Args:
            returns: 日收益率数组
            risk_free_rate: 年化无风险利率
            
        Returns:
            卡玛比率
        """
        max_dd = PerformanceMetrics.max_drawdown(returns)
        if max_dd == 0:
            return np.inf
        
        annual_return = np.mean(returns) * 252
        return (annual_return - risk_free_rate) / max_dd
    
    @staticmethod
    def win_rate(trades: List[Trade]) -> float:
        """
        计算胜率
        
        Args:
            trades: 交易列表
            
        Returns:
            胜率
        """
        if len(trades) == 0:
            return 0.0
        
        wins = sum(1 for t in trades if t.pnl > 0)
        return wins / len(trades)
    
    @staticmethod
    def profit_loss_ratio(trades: List[Trade]) -> float:
        """
        计算盈亏比
        
        Args:
            trades: 交易列表
            
        Returns:
            盈亏比
        """
        profits = [t.pnl for t in trades if t.pnl > 0]
        losses = [abs(t.pnl) for t in trades if t.pnl < 0]
        
        if len(losses) == 0:
            return np.inf if len(profits) > 0 else 0.0
        
        avg_profit = np.mean(profits) if profits else 0
        avg_loss = np.mean(losses)
        
        return avg_profit / avg_loss if avg_loss > 0 else 0.0
    
    @staticmethod
    def calculate_all(returns: np.ndarray, trades: List[Trade], 
                      risk_free_rate: float = 0.03) -> Dict[str, float]:
        """
        计算所有指标
        
        Returns:
            指标字典
        """
        return {
            'sharpe_ratio': PerformanceMetrics.sharpe_ratio(returns, risk_free_rate),
            'sortino_ratio': PerformanceMetrics.sortino_ratio(returns, risk_free_rate),
            'max_drawdown': PerformanceMetrics.max_drawdown(returns),
            'calmar_ratio': PerformanceMetrics.calmar_ratio(returns, risk_free_rate),
            'win_rate': PerformanceMetrics.win_rate(trades),
            'profit_loss_ratio': PerformanceMetrics.profit_loss_ratio(trades),
            'total_trades': len(trades),
            'volatility': np.std(returns) * np.sqrt(252) if len(returns) > 0 else 0,
            'avg_return': np.mean(returns) * 252 if len(returns) > 0 else 0
        }


# ==================== 回测引擎 ====================
class Backtester:
    """回测引擎"""
    
    def __init__(self, initial_capital: float = 100000, 
                 commission: float = 0.0003,
                 slippage: float = 0.0001):
        """
        初始化回测引擎
        
        Args:
            initial_capital: 初始资金
            commission: 佣金率
            slippage: 滑点率
        """
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        
        # 内置策略列表
        self.built_in_strategies = [
            BuyHoldStrategy(),
            MomentumStrategy(lookback=20),
            MeanReversionStrategy(window=20, threshold=2.0),
            MovingAverageStrategy(fast=5, slow=20),
            RSIStrategy(period=14),
            BollingerStrategy(period=20),
            MACDStrategy(),
            RandomWalkStrategy(seed=42),
            AIAgentStrategy()
        ]
    
    def run_backtest(self, strategy: BaseStrategy, data: pd.DataFrame,
                     start_date: Optional[datetime] = None,
                     end_date: Optional[datetime] = None) -> BacktestResult:
        """
        运行单策略回测
        
        Args:
            strategy: 策略实例
            data: OHLCV数据，必须包含 'date', 'open', 'high', 'low', 'close', 'volume' 列
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            BacktestResult对象
        """
        # 数据准备
        if start_date:
            data = data[data['date'] >= start_date]
        if end_date:
            data = data[data['date'] <= end_date]
        
        if len(data) < 50:
            raise ValueError("数据不足，至少需要50条记录")
        
        # 重置策略
        strategy.reset()
        
        # 初始化
        capital = self.initial_capital
        position_size = 0
        trades: List[Trade] = []
        equity_curve = []  # 不预置初始值，在循环内append
        daily_returns = []
        entry_price = 0.0
        entry_date = None
        
        # 遍历数据
        for i in range(len(data)):
            current_date = data.iloc[i]['date']
            current_close = data.iloc[i]['close']
            
            # 生成信号
            signal = strategy.generate_signal(data, i)
            
            # 执行交易
            if signal == Signal.BUY and position_size == 0:
                # 买入
                entry_price = current_close * (1 + self.slippage)
                position_size = int(capital / entry_price)
                cost = position_size * entry_price * (1 + self.commission)
                capital -= cost
                entry_date = current_date
                strategy.position = Position.LONG
                strategy.entry_price = entry_price
                
            elif signal == Signal.SELL and position_size > 0:
                # 卖出
                exit_price = current_close * (1 - self.slippage)
                revenue = position_size * exit_price * (1 - self.commission)
                capital += revenue
                
                # 记录交易
                trade = Trade(
                    entry_date=entry_date,
                    exit_date=current_date,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    quantity=position_size,
                    signal=Signal.BUY
                )
                trades.append(trade)
                
                position_size = 0
                strategy.position = Position.FLAT
            
            # 计算当日净值
            current_equity = capital + position_size * current_close
            equity_curve.append(current_equity)
            
            # 计算日收益率
            if len(equity_curve) > 1:
                daily_return = (equity_curve[-1] - equity_curve[-2]) / equity_curve[-2]
                daily_returns.append(daily_return)
        
        # 强制平仓（需要扣除滑点和佣金）
        if position_size > 0:
            last_close = data.iloc[-1]['close'] * (1 - self.slippage)
            capital += position_size * last_close * (1 - self.commission)
        
        # 计算结果
        final_capital = capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital
        
        # 计算年化收益（少于30天不计算年化）
        days = (data.iloc[-1]['date'] - data.iloc[0]['date']).days
        if days >= 30:
            annual_return = (1 + total_return) ** (365 / days) - 1
        else:
            annual_return = total_return  # 少于30天直接返回总收益
        
        # 计算性能指标
        returns_array = np.array(daily_returns)
        metrics = PerformanceMetrics.calculate_all(returns_array, trades)
        
        return BacktestResult(
            strategy_name=strategy.name,
            ticker=data.get('ticker', ['UNKNOWN'])[0] if 'ticker' in data.columns else 'UNKNOWN',
            start_date=data.iloc[0]['date'],
            end_date=data.iloc[-1]['date'],
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            annual_return=annual_return,
            trades=trades,
            daily_returns=returns_array,
            equity_curve=np.array(equity_curve),
            metrics=metrics
        )
    
    def compare_strategies(self, data: pd.DataFrame,
                           strategies: Optional[List[BaseStrategy]] = None,
                           start_date: Optional[datetime] = None,
                           end_date: Optional[datetime] = None) -> ComparisonReport:
        """
        对比多个策略
        
        Args:
            data: OHLCV数据
            strategies: 策略列表，如果为None则使用内置策略
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            ComparisonReport对象
        """
        if strategies is None:
            strategies = self.built_in_strategies
        
        results = []
        for strategy in strategies:
            try:
                # 每次使用新实例
                if hasattr(strategy, '__class__'):
                    new_strategy = strategy.__class__()
                    if hasattr(strategy, 'lookback'):
                        new_strategy.lookback = strategy.lookback
                    if hasattr(strategy, 'window'):
                        new_strategy.window = strategy.window
                    if hasattr(strategy, 'threshold'):
                        new_strategy.threshold = strategy.threshold
                    if hasattr(strategy, 'fast'):
                        new_strategy.fast = strategy.fast
                    if hasattr(strategy, 'slow'):
                        new_strategy.slow = strategy.slow
                    if hasattr(strategy, 'period'):
                        new_strategy.period = strategy.period
                    if hasattr(strategy, 'oversold'):
                        new_strategy.oversold = strategy.oversold
                    if hasattr(strategy, 'overbought'):
                        new_strategy.overbought = strategy.overbought
                    if hasattr(strategy, 'std_dev'):
                        new_strategy.std_dev = strategy.std_dev
                    if hasattr(strategy, 'signal'):
                        new_strategy.signal = strategy.signal
                    
                    result = self.run_backtest(new_strategy, data, start_date, end_date)
                else:
                    result = self.run_backtest(strategy, data, start_date, end_date)
                
                results.append(result)
            except Exception as e:
                print(f"策略 {strategy.name} 回测失败: {e}")
        
        # 排名（按夏普比率）
        rankings = sorted(
            [(r.strategy_name, r.metrics['sharpe_ratio']) for r in results],
            key=lambda x: x[1],
            reverse=True
        )
        
        # 统计检验
        statistical_tests = {}
        if len(results) >= 2:
            for i in range(len(results)):
                for j in range(i + 1, len(results)):
                    key = f"{results[i].strategy_name} vs {results[j].strategy_name}"
                    statistical_tests[key] = diebold_mariano_test(
                        results[i].daily_returns,
                        results[j].daily_returns
                    )
        
        return ComparisonReport(
            ticker=data.get('ticker', ['UNKNOWN'])[0] if 'ticker' in data.columns else 'UNKNOWN',
            period=(results[0].start_date, results[0].end_date) if results else (None, None),
            results=results,
            rankings=rankings,
            statistical_tests=statistical_tests
        )


# ==================== 统计显著性检验 ====================
def diebold_mariano_test(returns1: np.ndarray, returns2: np.ndarray, 
                         h: int = 1, alternative: str = 'two-sided') -> dict:
    """
    Diebold-Mariano检验 - 比较两个预测模型的预测能力
    
    Args:
        returns1: 策略1的收益率序列
        returns2: 策略2的收益率序列
        h: 预测步长
        alternative: 备择假设类型
        
    Returns:
        检验结果字典
    """
    if len(returns1) != len(returns2) or len(returns1) < 10:
        return {'statistic': np.nan, 'p_value': np.nan, 'significant': False}
    
    # 计算损失差值（使用平方损失）
    loss1 = returns1 ** 2
    loss2 = returns2 ** 2
    d = loss1 - loss2
    
    # 计算DM统计量
    mean_d = np.mean(d)
    
    # 计算长期方差（Newey-West）
    n = len(d)
    acov = np.zeros(h)
    for lag in range(h):
        if lag == 0:
            acov[lag] = np.var(d)
        else:
            acov[lag] = np.cov(d[:-lag], d[lag:])[0, 1]
    
    var_d = acov[0] + 2 * sum(acov[1:])
    
    if var_d == 0:
        return {'statistic': 0.0, 'p_value': 1.0, 'significant': False}
    
    dm_stat = mean_d / np.sqrt(var_d / n)
    
    # 计算p值
    if alternative == 'two-sided':
        p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    elif alternative == 'greater':
        p_value = 1 - stats.norm.cdf(dm_stat)
    else:
        p_value = stats.norm.cdf(dm_stat)
    
    return {
        'statistic': float(dm_stat),
        'p_value': float(p_value),
        'significant': p_value < 0.05
    }


def sharpe_ratio_test(sharpe1: float, sharpe2: float, n: int,
                      correlation: float = 0.0) -> dict:
    """
    比较两个夏普比率的显著性
    
    使用Jobson-Korkie检验
    
    Args:
        sharpe1: 策略1的夏普比率
        sharpe2: 策略2的夏普比率
        n: 样本数量
        correlation: 两个策略收益的相关系数
        
    Returns:
        检验结果字典
    """
    if n < 30:
        return {'statistic': np.nan, 'p_value': np.nan, 'significant': False}
    
    # 计算检验统计量
    diff = sharpe1 - sharpe2
    
    # 标准误
    se = np.sqrt(
        (1 / n) * (2 * (1 - correlation) + 
                   0.5 * (sharpe1 ** 2 + sharpe2 ** 2 - 
                          2 * correlation * sharpe1 * sharpe2))
    )
    
    if se == 0:
        return {'statistic': 0.0, 'p_value': 1.0, 'significant': False}
    
    z_stat = diff / se
    p_value = 2 * (1 - stats.norm.cdf(abs(z_stat)))
    
    return {
        'statistic': float(z_stat),
        'p_value': float(p_value),
        'significant': p_value < 0.05,
        'better': 'strategy1' if sharpe1 > sharpe2 else 'strategy2'
    }


# ==================== 辅助函数 ====================
def generate_sample_data(ticker: str = 'DEMO', 
                        start_date: str = '2020-01-01',
                        end_date: str = '2024-12-31',
                        initial_price: float = 100.0) -> pd.DataFrame:
    """
    生成样本数据用于测试
    
    Args:
        ticker: 股票代码
        start_date: 开始日期
        end_date: 结束日期
        initial_price: 初始价格
        
    Returns:
        OHLCV DataFrame
    """
    dates = pd.date_range(start=start_date, end=end_date, freq='B')
    n = len(dates)
    
    # 生成价格序列（几何布朗运动）
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.02, n)
    prices = initial_price * np.cumprod(1 + returns)
    
    # 生成OHLCV
    high_factor = 1 + np.abs(np.random.normal(0, 0.01, n))
    low_factor = 1 - np.abs(np.random.normal(0, 0.01, n))
    
    data = pd.DataFrame({
        'date': dates,
        'ticker': ticker,
        'open': prices * (1 + np.random.normal(0, 0.005, n)),
        'high': prices * high_factor,
        'low': prices * low_factor,
        'close': prices,
        'volume': np.random.randint(1000000, 10000000, n)
    })
    
    return data


def quick_backtest(ticker_data: pd.DataFrame, 
                   initial_capital: float = 100000) -> ComparisonReport:
    """
    快速回测入口函数
    
    Args:
        ticker_data: 股票OHLCV数据
        initial_capital: 初始资金
        
    Returns:
        策略对比报告
    """
    backtester = Backtester(initial_capital=initial_capital)
    return backtester.compare_strategies(ticker_data)


# ==================== 主程序示例 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("股票回测框架测试")
    print("=" * 60)
    
    # 生成测试数据
    data = generate_sample_data('DEMO', '2020-01-01', '2024-12-31')
    print(f"\n生成测试数据: {len(data)} 条记录")
    print(f"日期范围: {data['date'].min()} ~ {data['date'].max()}")
    
    # 创建回测引擎
    backtester = Backtester(initial_capital=100000)
    
    # 运行策略对比
    print("\n运行策略对比...")
    report = backtester.compare_strategies(data)
    
    # 输出结果
    print("\n" + "=" * 60)
    print("策略排名 (按夏普比率)")
    print("=" * 60)
    
    df = report.to_dataframe()
    for i, row in df.iterrows():
        print(f"\n{i+1}. {row['strategy']}")
        print(f"   总收益: {row['total_return']}")
        print(f"   年化收益: {row['annual_return']}")
        print(f"   夏普比率: {row['sharpe_ratio']:.3f}")
        print(f"   最大回撤: {row['max_drawdown']:.2%}")
        print(f"   胜率: {row['win_rate']:.1%}")
        print(f"   交易次数: {row['total_trades']}")
    
    # 最佳策略
    best = report.get_best_strategy('sharpe_ratio')
    print(f"\n最佳策略: {best.strategy_name}")
    print(f"夏普比率: {best.metrics['sharpe_ratio']:.3f}")

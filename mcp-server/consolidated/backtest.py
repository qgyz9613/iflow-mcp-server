"""
回测模块 - 合并版
整合以下模块:
- backtest_engine.py (stock-trading-system)
- backtest_20d_horizon.py
- backtest_evaluator.py
- backtest_analysis_2025.py
- backtest_comprehensive_2024_2026.py
- event_backtester.py
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json


class TradeAction(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Trade:
    """交易记录"""
    date: str
    code: str
    action: TradeAction
    price: float
    shares: int
    amount: float
    reason: str = ""
    profit: float = 0.0
    profit_pct: float = 0.0


@dataclass
class Position:
    """持仓"""
    code: str
    shares: int
    cost_price: float
    current_price: float = 0.0
    
    @property
    def market_value(self) -> float:
        return self.current_price * self.shares
    
    @property
    def profit(self) -> float:
        return (self.current_price - self.cost_price) * self.shares
    
    @property
    def profit_pct(self) -> float:
        return (self.current_price - self.cost_price) / self.cost_price * 100 if self.cost_price > 0 else 0


@dataclass
class BacktestResult:
    """回测结果"""
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    profit_trades: int
    loss_trades: int
    trades: List[Trade] = field(default_factory=list)
    daily_values: List[Dict] = field(default_factory=list)


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, initial_capital: float = 100000.0, 
                 commission_rate: float = 0.0003,
                 stamp_duty: float = 0.001,
                 slippage: float = 0.0):
        """
        初始化回测引擎
        
        Args:
            initial_capital: 初始资金
            commission_rate: 佣金费率 (默认0.03%)
            stamp_duty: 印花税率 (默认0.1%, 仅卖出)
            slippage: 滑点
        """
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.stamp_duty = stamp_duty
        self.slippage = slippage
        
        # 运行时状态
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.daily_values: List[Dict] = []
    
    def reset(self):
        """重置状态"""
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []
        self.daily_values = []
    
    def buy(self, code: str, price: float, shares: int, date: str, reason: str = "") -> bool:
        """买入"""
        # 计算成本
        amount = price * shares
        commission = amount * self.commission_rate
        total_cost = amount + commission
        
        # 实际成交价 (滑点)
        actual_price = price * (1 + self.slippage)
        
        if total_cost > self.cash:
            return False
        
        # 执行买入
        self.cash -= total_cost
        
        if code in self.positions:
            pos = self.positions[code]
            total_shares = pos.shares + shares
            total_cost_basis = pos.cost_price * pos.shares + actual_price * shares
            pos.cost_price = total_cost_basis / total_shares
            pos.shares = total_shares
        else:
            self.positions[code] = Position(code, shares, actual_price)
        
        self.trades.append(Trade(
            date=date, code=code, action=TradeAction.BUY,
            price=actual_price, shares=shares, amount=amount,
            reason=reason
        ))
        return True
    
    def sell(self, code: str, price: float, shares: int, date: str, reason: str = "") -> bool:
        """卖出"""
        if code not in self.positions or self.positions[code].shares < shares:
            return False
        
        pos = self.positions[code]
        
        # 实际成交价 (滑点)
        actual_price = price * (1 - self.slippage)
        
        # 计算收入
        amount = actual_price * shares
        commission = amount * self.commission_rate
        stamp = amount * self.stamp_duty  # 印花税
        total_income = amount - commission - stamp
        
        # 计算盈亏
        cost = pos.cost_price * shares
        profit = amount - cost
        profit_pct = profit / cost * 100 if cost > 0 else 0
        
        # 执行卖出
        self.cash += total_income
        pos.shares -= shares
        
        if pos.shares == 0:
            del self.positions[code]
        
        self.trades.append(Trade(
            date=date, code=code, action=TradeAction.SELL,
            price=actual_price, shares=shares, amount=amount,
            reason=reason, profit=profit, profit_pct=profit_pct
        ))
        return True
    
    def get_total_value(self, prices: Dict[str, float]) -> float:
        """计算总资产"""
        total = self.cash
        for code, pos in self.positions.items():
            if code in prices:
                pos.current_price = prices[code]
                total += pos.market_value
        return total
    
    def record_daily(self, date: str, prices: Dict[str, float]):
        """记录每日资产"""
        total = self.get_total_value(prices)
        self.daily_values.append({
            "date": date,
            "total_value": total,
            "cash": self.cash,
            "position_value": total - self.cash,
        })
    
    def calculate_metrics(self) -> BacktestResult:
        """计算回测指标"""
        if not self.daily_values:
            return None
        
        # 基础数据
        start_date = self.daily_values[0]["date"]
        end_date = self.daily_values[-1]["date"]
        final_capital = self.daily_values[-1]["total_value"]
        
        # 总收益率
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100
        
        # 年化收益率
        days = len(self.daily_values)
        annual_return = (pow(final_capital / self.initial_capital, 252 / days) - 1) * 100 if days > 0 else 0
        
        # 最大回撤
        max_value = self.initial_capital
        max_drawdown = 0
        for dv in self.daily_values:
            if dv["total_value"] > max_value:
                max_value = dv["total_value"]
            drawdown = (max_value - dv["total_value"]) / max_value * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # 胜率
        sell_trades = [t for t in self.trades if t.action == TradeAction.SELL]
        profit_trades = [t for t in sell_trades if t.profit > 0]
        loss_trades = [t for t in sell_trades if t.profit <= 0]
        win_rate = len(profit_trades) / len(sell_trades) * 100 if sell_trades else 0
        
        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            total_trades=len(self.trades),
            profit_trades=len(profit_trades),
            loss_trades=len(loss_trades),
            trades=self.trades,
            daily_values=self.daily_values,
        )


class StrategyBacktest:
    """策略回测"""
    
    def __init__(self, data: pd.DataFrame, engine: BacktestEngine = None):
        """
        Args:
            data: 股票数据, 需包含 date, open, high, low, close, volume
            engine: 回测引擎
        """
        self.data = data
        self.engine = engine or BacktestEngine()
    
    def run_ma_strategy(self, fast: int = 5, slow: int = 20) -> BacktestResult:
        """双均线策略"""
        self.engine.reset()
        
        # 计算均线
        data = self.data.copy()
        data['ma_fast'] = data['close'].rolling(fast).mean()
        data['ma_slow'] = data['close'].rolling(slow).mean()
        
        # 交易逻辑
        position = 0
        for i in range(slow, len(data)):
            row = data.iloc[i]
            prev = data.iloc[i-1]
            
            # 金叉买入
            if prev['ma_fast'] <= prev['ma_slow'] and row['ma_fast'] > row['ma_slow']:
                if position == 0:
                    shares = int(self.engine.cash * 0.95 / row['close'] / 100) * 100
                    if shares > 0:
                        self.engine.buy("stock", row['close'], shares, row['date'], "金叉")
                        position = shares
            
            # 死叉卖出
            elif prev['ma_fast'] >= prev['ma_slow'] and row['ma_fast'] < row['ma_slow']:
                if position > 0:
                    self.engine.sell("stock", row['close'], position, row['date'], "死叉")
                    position = 0
            
            # 记录每日资产
            self.engine.record_daily(row['date'], {"stock": row['close']})
        
        return self.engine.calculate_metrics()
    
    def run_macd_strategy(self) -> BacktestResult:
        """MACD策略"""
        self.engine.reset()
        
        data = self.data.copy()
        
        # 计算MACD
        ema12 = data['close'].ewm(span=12).mean()
        ema26 = data['close'].ewm(span=26).mean()
        data['dif'] = ema12 - ema26
        data['dea'] = data['dif'].ewm(span=9).mean()
        
        position = 0
        for i in range(35, len(data)):  # MACD需要较长时间稳定
            row = data.iloc[i]
            prev = data.iloc[i-1]
            
            # MACD金叉
            if prev['dif'] <= prev['dea'] and row['dif'] > row['dea']:
                if position == 0:
                    shares = int(self.engine.cash * 0.95 / row['close'] / 100) * 100
                    if shares > 0:
                        self.engine.buy("stock", row['close'], shares, row['date'], "MACD金叉")
                        position = shares
            
            # MACD死叉
            elif prev['dif'] >= prev['dea'] and row['dif'] < row['dea']:
                if position > 0:
                    self.engine.sell("stock", row['close'], position, row['date'], "MACD死叉")
                    position = 0
            
            self.engine.record_daily(row['date'], {"stock": row['close']})
        
        return self.engine.calculate_metrics()
    
    def run_rsi_strategy(self, period: int = 14, oversold: float = 30, overbought: float = 70) -> BacktestResult:
        """RSI策略"""
        self.engine.reset()
        
        data = self.data.copy()
        
        # 计算RSI
        delta = data['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        rs = avg_gain / avg_loss
        data['rsi'] = 100 - 100 / (1 + rs)
        
        position = 0
        for i in range(period, len(data)):
            row = data.iloc[i]
            prev = data.iloc[i-1]
            
            # RSI超卖买入
            if prev['rsi'] < oversold and row['rsi'] >= oversold:
                if position == 0:
                    shares = int(self.engine.cash * 0.95 / row['close'] / 100) * 100
                    if shares > 0:
                        self.engine.buy("stock", row['close'], shares, row['date'], "RSI超卖")
                        position = shares
            
            # RSI超买卖出
            elif prev['rsi'] > overbought and row['rsi'] <= overbought:
                if position > 0:
                    self.engine.sell("stock", row['close'], position, row['date'], "RSI超买")
                    position = 0
            
            self.engine.record_daily(row['date'], {"stock": row['close']})
        
        return self.engine.calculate_metrics()


def compare_strategies(data: pd.DataFrame) -> pd.DataFrame:
    """比较不同策略"""
    results = []
    
    # 双均线策略
    engine = BacktestEngine()
    bt = StrategyBacktest(data, engine)
    
    for fast, slow in [(5, 20), (10, 30), (5, 10)]:
        result = bt.run_ma_strategy(fast, slow)
        if result:
            results.append({
                "strategy": f"MA({fast},{slow})",
                "total_return": result.total_return,
                "annual_return": result.annual_return,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "trades": result.total_trades,
            })
    
    # MACD策略
    result = bt.run_macd_strategy()
    if result:
        results.append({
            "strategy": "MACD",
            "total_return": result.total_return,
            "annual_return": result.annual_return,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "trades": result.total_trades,
        })
    
    # RSI策略
    result = bt.run_rsi_strategy()
    if result:
        results.append({
            "strategy": "RSI",
            "total_return": result.total_return,
            "annual_return": result.annual_return,
            "max_drawdown": result.max_drawdown,
            "win_rate": result.win_rate,
            "trades": result.total_trades,
        })
    
    return pd.DataFrame(results)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("回测模块测试 - 合并版")
    print("=" * 60)
    
    # 生成模拟数据
    np.random.seed(42)
    n = 252  # 一年交易日
    
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    base_price = 100
    returns = np.random.randn(n) * 0.02
    close = base_price * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(np.random.randn(n) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n) * 0.01))
    open_price = close * (1 + np.random.randn(n) * 0.01)
    volume = np.random.randint(1000000, 10000000, n)
    
    data = pd.DataFrame({
        'date': dates.strftime('%Y-%m-%d'),
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })
    
    # 测试双均线策略
    print("\n1. 双均线策略 MA(5,20):")
    engine = BacktestEngine(initial_capital=100000)
    bt = StrategyBacktest(data, engine)
    result = bt.run_ma_strategy(5, 20)
    print(f"   总收益率: {result.total_return:.2f}%")
    print(f"   年化收益: {result.annual_return:.2f}%")
    print(f"   最大回撤: {result.max_drawdown:.2f}%")
    print(f"   胜率: {result.win_rate:.1f}%")
    print(f"   交易次数: {result.total_trades}")
    
    # 测试策略比较
    print("\n2. 策略比较:")
    comparison = compare_strategies(data)
    print(comparison.to_string(index=False))
    
    print("\n" + "=" * 60)
    print("测试完成!")

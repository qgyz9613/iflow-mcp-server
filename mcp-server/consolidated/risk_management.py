"""
风险管理模块 - 合并版
整合以下模块:
- dynamic_risk_control.py (动态风控)
- risk_model_var_cvar.py (VaR/CVaR)
- realtime_risk_monitor.py (实时监控)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger('risk_management')


class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class RiskAssessment:
    """风险评估结果"""
    level: RiskLevel
    score: float  # 0-100
    var_pct: float  # VaR百分比
    cvar_pct: float  # CVaR百分比
    position_limit: float  # 仓位限制
    description: str
    warnings: List[str]


class VaRCalculator:
    """VaR/CVaR计算器"""
    
    @staticmethod
    def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
        """
        历史模拟法计算VaR
        
        Args:
            returns: 收益率序列
            confidence: 置信度 (默认95%)
        
        Returns:
            VaR百分比 (正数表示损失)
        """
        if len(returns) < 10:
            return 0.0
        return -np.percentile(returns, (1 - confidence) * 100)
    
    @staticmethod
    def parametric_var(returns: np.ndarray, confidence: float = 0.95) -> float:
        """
        参数法计算VaR (假设正态分布)
        """
        if len(returns) < 10:
            return 0.0
        mean = np.mean(returns)
        std = np.std(returns)
        z = {0.90: 1.28, 0.95: 1.645, 0.99: 2.33}.get(confidence, 1.645)
        return -(mean - z * std)
    
    @staticmethod
    def cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
        """
        条件VaR (Expected Shortfall)
        平均最坏情况的损失
        """
        if len(returns) < 10:
            return 0.0
        var = VaRCalculator.historical_var(returns, confidence)
        # 取所有超过VaR的损失的平均
        tail_losses = returns[returns <= -var]
        if len(tail_losses) == 0:
            return var
        return -np.mean(tail_losses)
    
    @staticmethod
    def max_drawdown(prices: np.ndarray) -> Tuple[float, int, int]:
        """
        最大回撤
        
        Returns:
            (最大回撤百分比, 开始位置, 结束位置)
        """
        if len(prices) < 2:
            return 0.0, 0, 0
        
        peak = prices[0]
        max_dd = 0.0
        start_idx, end_idx = 0, 0
        peak_idx = 0
        
        for i, price in enumerate(prices):
            if price > peak:
                peak = price
                peak_idx = i
            dd = (peak - price) / peak
            if dd > max_dd:
                max_dd = dd
                start_idx = peak_idx
                end_idx = i
        
        return max_dd * 100, start_idx, end_idx


class PositionSizer:
    """仓位计算器"""
    
    @staticmethod
    def kelly_criterion(win_rate: float, win_loss_ratio: float) -> float:
        """
        凯利公式计算最优仓位
        
        Args:
            win_rate: 胜率 (0-1)
            win_loss_ratio: 盈亏比 (平均盈利/平均亏损)
        
        Returns:
            最优仓位比例 (0-1)
        """
        kelly = win_rate - (1 - win_rate) / win_loss_ratio
        return max(0, min(kelly, 1))  # 限制在0-1之间
    
    @staticmethod
    def fixed_fractional(capital: float, risk_pct: float, 
                         entry_price: float, stop_loss: float) -> int:
        """
        固定比例仓位法
        
        Args:
            capital: 总资金
            risk_pct: 单笔风险比例 (如2%)
            entry_price: 入场价
            stop_loss: 止损价
        
        Returns:
            可买股数
        """
        max_loss = capital * risk_pct / 100
        loss_per_share = abs(entry_price - stop_loss)
        if loss_per_share <= 0:
            return 0
        shares = int(max_loss / loss_per_share)
        # 凑整到100股
        return shares // 100 * 100
    
    @staticmethod
    def volatility_adjusted(capital: float, atr: float, 
                           target_risk: float = 0.02) -> int:
        """
        波动率调整仓位法
        
        Args:
            capital: 总资金
            atr: ATR值
            target_risk: 目标风险比例
        
        Returns:
            可买股数
        """
        if atr <= 0:
            return 0
        max_loss = capital * target_risk
        shares = int(max_loss / atr)
        return shares // 100 * 100


class DynamicRiskControl:
    """
    动态风险控制系统
    基于市场环境动态调整仓位限制
    """
    
    def __init__(self):
        # 风险等级配置
        self.risk_levels = {
            RiskLevel.LOW: {
                'position_multiplier': 1.0,
                'description': '低风险，满仓操作',
                'max_drawdown_limit': 0.20,
            },
            RiskLevel.MEDIUM: {
                'position_multiplier': 0.6,
                'description': '中等风险，适度降低仓位',
                'max_drawdown_limit': 0.15,
            },
            RiskLevel.HIGH: {
                'position_multiplier': 0.3,
                'description': '高风险市场，降低仓位',
                'max_drawdown_limit': 0.10,
            },
            RiskLevel.CRITICAL: {
                'position_multiplier': 0.0,
                'description': '极端市场，停止交易',
                'max_drawdown_limit': 0.05,
            },
        }
        
        # 极端市场阈值
        self.thresholds = {
            'crash_5d': -0.10,      # 5日跌幅 > 10%
            'crash_20d': -0.15,     # 20日跌幅 > 15%
            'vix_extreme': 30,      # VIX > 30
            'vol_spike': 2.0,       # 波动率 > 平均2倍
        }
    
    def assess_market(self, index_data: pd.DataFrame = None, 
                      vix: float = None) -> RiskLevel:
        """
        评估市场风险等级
        
        Args:
            index_data: 指数数据 (需有close列)
            vix: VIX指数值
        
        Returns:
            风险等级
        """
        warnings = []
        risk_score = 0  # 越高越危险
        
        # 检查指数跌幅
        if index_data is not None and 'close' in index_data.columns:
            close = index_data['close'].values
            
            # 5日跌幅
            if len(close) >= 5:
                change_5d = (close[-1] - close[-5]) / close[-5]
                if change_5d < self.thresholds['crash_5d']:
                    risk_score += 40
                    warnings.append(f"5日跌幅{change_5d*100:.1f}%超过阈值")
                elif change_5d < self.thresholds['crash_5d'] / 2:
                    risk_score += 20
                    warnings.append(f"5日跌幅{change_5d*100:.1f}%偏大")
            
            # 20日跌幅
            if len(close) >= 20:
                change_20d = (close[-1] - close[-20]) / close[-20]
                if change_20d < self.thresholds['crash_20d']:
                    risk_score += 50
                    warnings.append(f"20日跌幅{change_20d*100:.1f}%严重超跌")
            
            # 波动率
            if len(close) >= 20:
                returns = np.diff(np.log(close[-20:]))
                vol = np.std(returns) * np.sqrt(252)
                avg_vol = np.std(np.diff(np.log(close[-60:]))) * np.sqrt(252) if len(close) >= 60 else vol
                if vol > avg_vol * self.thresholds['vol_spike']:
                    risk_score += 20
                    warnings.append(f"波动率激增{vol/avg_vol:.1f}倍")
        
        # VIX检查
        if vix is not None:
            if vix > self.thresholds['vix_extreme']:
                risk_score += 30
                warnings.append(f"VIX恐慌指数{vix:.1f}极度恐慌")
            elif vix > 20:
                risk_score += 10
                warnings.append(f"VIX恐慌指数{vix:.1f}偏高")
        
        # 确定风险等级
        if risk_score >= 70:
            level = RiskLevel.CRITICAL
        elif risk_score >= 40:
            level = RiskLevel.HIGH
        elif risk_score >= 20:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW
        
        return level, warnings
    
    def get_position_limit(self, risk_level: RiskLevel) -> float:
        """获取仓位限制"""
        return self.risk_levels[risk_level]['position_multiplier']
    
    def assess_position(self, position: Dict, portfolio_value: float,
                        var_pct: float) -> RiskAssessment:
        """
        评估持仓风险
        
        Args:
            position: 持仓信息 {code, shares, cost_price, current_price}
            portfolio_value: 组合总价值
            var_pct: VaR百分比
        
        Returns:
            风险评估结果
        """
        warnings = []
        
        # 计算仓位占比
        position_value = position.get('shares', 0) * position.get('current_price', 0)
        position_pct = position_value / portfolio_value * 100 if portfolio_value > 0 else 0
        
        # 单只股票仓位过高
        if position_pct > 30:
            warnings.append(f"单只股票仓位{position_pct:.1f}%过高")
        
        # VaR过大
        if var_pct > 5:
            warnings.append(f"VaR {var_pct:.1f}%风险敞口过大")
        
        # 计算风险分数
        risk_score = 0
        risk_score += min(position_pct / 2, 30)  # 仓位贡献最多30分
        risk_score += min(var_pct * 2, 40)  # VaR贡献最多40分
        risk_score += len(warnings) * 10
        
        # 确定风险等级
        if risk_score >= 60:
            level = RiskLevel.HIGH
        elif risk_score >= 30:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW
        
        # 计算建议仓位限制
        position_limit = self.get_position_limit(level)
        
        return RiskAssessment(
            level=level,
            score=risk_score,
            var_pct=var_pct,
            cvar_pct=var_pct * 1.2,  # 简化估算
            position_limit=position_limit,
            description=self.risk_levels[level]['description'],
            warnings=warnings,
        )


class RealtimeRiskMonitor:
    """实时风险监控器"""
    
    def __init__(self, max_drawdown_pct: float = 20.0,
                 daily_loss_limit: float = 5.0):
        """
        Args:
            max_drawdown_pct: 最大回撤限制 (%)
            daily_loss_limit: 单日亏损限制 (%)
        """
        self.max_drawdown_pct = max_drawdown_pct
        self.daily_loss_limit = daily_loss_limit
        
        self.peak_value = 0
        self.daily_start_value = 0
        self.current_date = None
    
    def update(self, portfolio_value: float, date: str = None) -> Dict:
        """
        更新监控状态
        
        Returns:
            Dict with risk status
        """
        if date and date != self.current_date:
            self.current_date = date
            self.daily_start_value = portfolio_value
        
        # 更新峰值
        if portfolio_value > self.peak_value:
            self.peak_value = portfolio_value
        
        # 计算回撤
        drawdown = (self.peak_value - portfolio_value) / self.peak_value * 100 if self.peak_value > 0 else 0
        
        # 计算单日亏损
        daily_pnl = (portfolio_value - self.daily_start_value) / self.daily_start_value * 100 if self.daily_start_value > 0 else 0
        
        # 检查风险触发
        alerts = []
        if drawdown > self.max_drawdown_pct * 0.8:
            alerts.append(f"⚠️ 回撤{drawdown:.1f}%接近限制{self.max_drawdown_pct}%")
        if daily_pnl < -self.daily_loss_limit * 0.8:
            alerts.append(f"⚠️ 单日亏损{daily_pnl:.1f}%接近限制{self.daily_loss_limit}%")
        
        # 是否应该停止交易
        should_stop = drawdown > self.max_drawdown_pct or daily_pnl < -self.daily_loss_limit
        
        return {
            'portfolio_value': portfolio_value,
            'peak_value': self.peak_value,
            'drawdown_pct': drawdown,
            'daily_pnl_pct': daily_pnl,
            'alerts': alerts,
            'should_stop_trading': should_stop,
        }


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("风险管理模块测试 - 合并版")
    print("=" * 60)
    
    # 1. VaR计算
    print("\n1. VaR计算:")
    np.random.seed(42)
    returns = np.random.randn(252) * 0.02  # 模拟一年收益率
    
    var = VaRCalculator.historical_var(returns, 0.95)
    cvar = VaRCalculator.cvar(returns, 0.95)
    print(f"   VaR(95%): {var*100:.2f}%")
    print(f"   CVaR(95%): {cvar*100:.2f}%")
    
    # 2. 仓位计算
    print("\n2. 仓位计算:")
    shares = PositionSizer.fixed_fractional(100000, 2.0, 100, 95)
    print(f"   固定比例法 (资金10万, 风险2%, 入场100, 止损95): {shares}股")
    
    kelly = PositionSizer.kelly_criterion(0.55, 1.5)
    print(f"   凯利公式 (胜率55%, 盈亏比1.5): {kelly*100:.1f}%")
    
    # 3. 动态风控
    print("\n3. 动态风控评估:")
    risk_ctrl = DynamicRiskControl()
    
    # 模拟正常市场
    normal_data = pd.DataFrame({'close': 100 * np.exp(np.cumsum(np.random.randn(30) * 0.01))})
    level, warnings = risk_ctrl.assess_market(normal_data)
    print(f"   正常市场风险等级: {level.value}")
    
    # 4. 实时监控
    print("\n4. 实时风险监控:")
    monitor = RealtimeRiskMonitor(max_drawdown_pct=20, daily_loss_limit=5)
    
    # 模拟账户价值变化
    for i, value in enumerate([100000, 98000, 95000, 92000, 85000]):
        status = monitor.update(value, f"2025-01-{i+1:02d}")
        alerts = status['alerts']
        print(f"   Day {i+1}: 价值{value}, 回撤{status['drawdown_pct']:.1f}%, " +
              (f"⚠️ {alerts[0]}" if alerts else "正常"))
    
    print("\n" + "=" * 60)
    print("测试完成!")

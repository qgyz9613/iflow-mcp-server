"""
统一交易系统模块 v1.0
整合 fortune + stock-trading-system + iFlow 所有交易相关功能

模块分类:
1. 数据源 - 多源数据获取
2. 技术分析 - 指标计算
3. AI预测 - 模型推理
4. 交易执行 - 下单操作
5. 风险监控 - 实时监控
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import httpx

# 添加项目路径
FORTUNE_PATH = Path(__file__).parent.parent.parent / "fortune"
STOCK_TRADING_PATH = Path(__file__).parent.parent.parent / "stock-trading-system"

if FORTUNE_PATH.exists():
    sys.path.insert(0, str(FORTUNE_PATH))
if STOCK_TRADING_PATH.exists():
    sys.path.insert(0, str(STOCK_TRADING_PATH))


# ==================== 数据源模块 ====================

class DataSourceManager:
    """多数据源管理器"""
    
    # 数据源优先级
    SOURCES = {
        "tencent": {"name": "腾讯股票", "free": True, "realtime": True},
        "eastmoney": {"name": "东方财富", "free": True, "realtime": True},
        "akshare": {"name": "AKShare", "free": True, "realtime": False},
        "sina": {"name": "新浪财经", "free": True, "realtime": True},
    }
    
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.http_client = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=self.timeout)
        return self.http_client
    
    async def tencent_realtime(self, stock_codes: List[str]) -> Dict:
        """
        腾讯API获取实时行情 - 免费、无需Key
        
        Args:
            stock_codes: 股票代码列表 ["600519", "000001"]
        """
        # 转换代码格式: 600519 -> sh600519, 000001 -> sz000001
        symbols = []
        for code in stock_codes:
            code = code.replace("sh", "").replace("sz", "").replace("bj", "")
            if code.startswith("6"):
                symbols.append(f"sh{code}")
            elif code.startswith(("0", "3")):
                symbols.append(f"sz{code}")
            else:
                symbols.append(f"bj{code}")
        
        url = f"https://qt.gtimg.cn/q={','.join(symbols)}"
        
        try:
            client = await self._get_client()
            resp = await client.get(url)
            return self._parse_tencent_data(resp.text)
        except Exception as e:
            return {"error": str(e), "source": "tencent"}
    
    def _parse_tencent_data(self, text: str) -> Dict:
        """解析腾讯数据格式"""
        results = []
        
        for line in text.strip().split(";"):
            if not line:
                continue
            
            idx = line.find('="')
            if idx == -1:
                continue
            
            data_str = line[idx + 3:-1]
            parts = data_str.split("~")
            
            if len(parts) < 35:
                continue
            
            results.append({
                "name": parts[1],
                "code": parts[2],
                "price": float(parts[3]) if parts[3] else None,
                "yesterday": float(parts[4]) if parts[4] else None,
                "open": float(parts[5]) if parts[5] else None,
                "volume": int(float(parts[6])) if parts[6] else 0,
                "amount": float(parts[37]) if len(parts) > 37 and parts[37] else 0,
                "change": float(parts[31]) if parts[31] else 0,
                "change_pct": float(parts[32]) if parts[32] else 0,
                "high": float(parts[33]) if parts[33] else None,
                "low": float(parts[34]) if parts[34] else None,
                "pe": float(parts[39]) if len(parts) > 39 and parts[39] else None,
                "market_cap": float(parts[45]) if len(parts) > 45 and parts[45] else None,
                "time": parts[30] if len(parts) > 30 else "",
                "source": "tencent"
            })
        
        return {
            "source": "tencent",
            "count": len(results),
            "data": results,
            "timestamp": datetime.now().isoformat()
        }
    
    async def eastmoney_kline(self, stock_code: str, period_days: int = 365) -> Dict:
        """
        东财API获取历史K线
        
        Args:
            stock_code: 股票代码
            period_days: 获取天数
        """
        # 判断市场
        if stock_code.startswith("6"):
            secid = f"1.{stock_code}"
        else:
            secid = f"0.{stock_code}"
        
        url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "klt": 101,  # 日K
            "fqt": 1,    # 前复权
            "end": "20500000",
            "lmt": period_days,
        }
        
        try:
            client = await self._get_client()
            resp = await client.get(url, params=params)
            data = resp.json()
            
            if not data.get("data") or not data["data"].get("klines"):
                return {"error": "无数据", "source": "eastmoney"}
            
            klines = data["data"]["klines"]
            parsed = []
            
            for line in klines:
                parts = line.split(",")
                parsed.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": int(float(parts[5])),
                })
            
            return {
                "source": "eastmoney",
                "code": stock_code,
                "count": len(parsed),
                "data": parsed,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": str(e), "source": "eastmoney"}
    
    async def sina_news(self, keyword: str, limit: int = 5) -> Dict:
        """
        新浪财经搜索新闻
        
        Args:
            keyword: 搜索关键词
            limit: 返回数量
        """
        url = f"https://search.api.sina.com.cn/?c=news&q={keyword}&page=1&num={limit}"
        
        try:
            client = await self._get_client()
            resp = await client.get(url)
            data = resp.json()
            
            news_list = []
            if "result" in data and "list" in data["result"]:
                for item in data["result"]["list"]:
                    news_list.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "time": item.get("time", ""),
                        "source": item.get("media", ""),
                    })
            
            return {
                "source": "sina",
                "keyword": keyword,
                "count": len(news_list),
                "data": news_list,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": str(e), "source": "sina"}


# ==================== 技术分析模块 ====================

class TechnicalAnalyzer:
    """技术指标计算器"""
    
    @staticmethod
    def sma(prices: List[float], period: int) -> List[float]:
        """简单移动平均线"""
        if len(prices) < period:
            return []
        
        result = []
        for i in range(period - 1, len(prices)):
            avg = sum(prices[i - period + 1 : i + 1]) / period
            result.append(round(avg, 2))
        return result
    
    @staticmethod
    def ema(prices: List[float], period: int) -> List[float]:
        """指数移动平均线"""
        if len(prices) < period:
            return []
        
        multiplier = 2 / (period + 1)
        result = []
        
        # 第一个EMA用SMA
        sma_first = sum(prices[:period]) / period
        result.append(round(sma_first, 2))
        
        # 后续用EMA公式
        for i in range(period, len(prices)):
            ema = (prices[i] - result[-1]) * multiplier + result[-1]
            result.append(round(ema, 2))
        
        return result
    
    @staticmethod
    def macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """MACD指标"""
        if len(prices) < slow + signal:
            return {"error": "数据不足"}
        
        ema_fast = TechnicalAnalyzer.ema(prices, fast)
        ema_slow = TechnicalAnalyzer.ema(prices, slow)
        
        # DIF
        dif = [f - s for f, s in zip(ema_fast[-(len(ema_slow)):], ema_slow)]
        
        # DEA (DIF的EMA)
        dea = TechnicalAnalyzer.ema(dif, signal)
        
        # MACD柱
        macd_values = [(d - dea[i]) * 2 for i, d in enumerate(dif[-len(dea):])]
        
        return {
            "dif": dif[-len(dea):],
            "dea": dea,
            "macd": macd_values,
        }
    
    @staticmethod
    def kdj(highs: List[float], lows: List[float], closes: List[float], n: int = 9) -> Dict:
        """KDJ指标"""
        if len(closes) < n:
            return {"error": "数据不足"}
        
        k_values = []
        d_values = []
        j_values = []
        
        for i in range(n - 1, len(closes)):
            high_n = max(highs[i - n + 1 : i + 1])
            low_n = min(lows[i - n + 1 : i + 1])
            
            if high_n == low_n:
                rsv = 50
            else:
                rsv = (closes[i] - low_n) / (high_n - low_n) * 100
            
            if not k_values:
                k = 50
                d = 50
            else:
                k = 2 / 3 * k_values[-1] + 1 / 3 * rsv
                d = 2 / 3 * d_values[-1] + 1 / 3 * k
            
            k_values.append(round(k, 2))
            d_values.append(round(d, 2))
            j_values.append(round(3 * k - 2 * d, 2))
        
        return {"k": k_values, "d": d_values, "j": j_values}
    
    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> List[float]:
        """RSI指标"""
        if len(prices) < period + 1:
            return []
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        rsi_values = []
        
        for i in range(period, len(gains)):
            avg_gain = sum(gains[i - period : i]) / period
            avg_loss = sum(losses[i - period : i]) / period
            
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            rsi_values.append(round(rsi, 2))
        
        return rsi_values
    
    @staticmethod
    def bollinger(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Dict:
        """布林带"""
        if len(prices) < period:
            return {"error": "数据不足"}
        
        import statistics
        
        mid = []
        upper = []
        lower = []
        
        for i in range(period - 1, len(prices)):
            window = prices[i - period + 1 : i + 1]
            ma = sum(window) / period
            std = statistics.stdev(window)
            
            mid.append(round(ma, 2))
            upper.append(round(ma + std_dev * std, 2))
            lower.append(round(ma - std_dev * std, 2))
        
        return {"mid": mid, "upper": upper, "lower": lower}


# ==================== 交易信号模块 ====================

class SignalGenerator:
    """交易信号生成器"""
    
    @staticmethod
    def generate_signals(
        prices: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[int] = None,
    ) -> Dict:
        """
        生成综合交易信号
        
        Returns:
            signal: buy/sell/hold
            confidence: 0-1
            reasons: 信号原因列表
        """
        signals = []
        reasons = []
        
        # 1. MACD信号
        macd_data = TechnicalAnalyzer.macd(prices)
        if "dif" in macd_data and len(macd_data["dif"]) >= 2:
            # 金叉
            if macd_data["dif"][-1] > macd_data["dea"][-1] and macd_data["dif"][-2] <= macd_data["dea"][-2]:
                signals.append(1)
                reasons.append("MACD金叉")
            # 死叉
            elif macd_data["dif"][-1] < macd_data["dea"][-1] and macd_data["dif"][-2] >= macd_data["dea"][-2]:
                signals.append(-1)
                reasons.append("MACD死叉")
        
        # 2. KDJ信号
        kdj_data = TechnicalAnalyzer.kdj(highs, lows, prices)
        if "k" in kdj_data and len(kdj_data["k"]) >= 1:
            k, d, j = kdj_data["k"][-1], kdj_data["d"][-1], kdj_data["j"][-1]
            # 超卖
            if k < 20 and d < 20:
                signals.append(1)
                reasons.append(f"KDJ超卖(K={k}, D={d})")
            # 超买
            elif k > 80 and d > 80:
                signals.append(-1)
                reasons.append(f"KDJ超买(K={k}, D={d})")
        
        # 3. RSI信号
        rsi_values = TechnicalAnalyzer.rsi(prices)
        if rsi_values:
            rsi = rsi_values[-1]
            if rsi < 30:
                signals.append(1)
                reasons.append(f"RSI超卖({rsi})")
            elif rsi > 70:
                signals.append(-1)
                reasons.append(f"RSI超买({rsi})")
        
        # 4. 布林带信号
        boll_data = TechnicalAnalyzer.bollinger(prices)
        if "upper" in boll_data and boll_data["upper"]:
            price = prices[-1]
            lower = boll_data["lower"][-1]
            upper = boll_data["upper"][-1]
            
            if price < lower:
                signals.append(1)
                reasons.append(f"价格跌破布林下轨({price:.2f} < {lower:.2f})")
            elif price > upper:
                signals.append(-1)
                reasons.append(f"价格突破布林上轨({price:.2f} > {upper:.2f})")
        
        # 5. 均线信号
        if len(prices) >= 20:
            ma5 = sum(prices[-5:]) / 5
            ma20 = sum(prices[-20:]) / 20
            price = prices[-1]
            
            if ma5 > ma20 and price > ma5:
                signals.append(1)
                reasons.append("多头排列(MA5>MA20, 价格>MA5)")
            elif ma5 < ma20 and price < ma5:
                signals.append(-1)
                reasons.append("空头排列(MA5<MA20, 价格<MA5)")
        
        # 综合判断
        if not signals:
            return {
                "signal": "hold",
                "confidence": 0.5,
                "reasons": ["无明显信号"],
                "timestamp": datetime.now().isoformat()
            }
        
        avg_signal = sum(signals) / len(signals)
        
        if avg_signal > 0.3:
            final_signal = "buy"
        elif avg_signal < -0.3:
            final_signal = "sell"
        else:
            final_signal = "hold"
        
        confidence = min(1.0, abs(avg_signal) / len(signals) + 0.5)
        
        return {
            "signal": final_signal,
            "confidence": round(confidence, 2),
            "reasons": reasons,
            "raw_score": round(avg_signal, 2),
            "signal_count": len(signals),
            "timestamp": datetime.now().isoformat()
        }


# ==================== 风险评估模块 ====================

class RiskAnalyzer:
    """风险分析器"""
    
    @staticmethod
    def calculate_var(prices: List[float], confidence: float = 0.95) -> Dict:
        """计算VaR (Value at Risk)"""
        if len(prices) < 20:
            return {"error": "数据不足"}
        
        import statistics
        
        # 计算日收益率
        returns = []
        for i in range(1, len(prices)):
            ret = (prices[i] - prices[i - 1]) / prices[i - 1]
            returns.append(ret)
        
        # 计算统计量
        mean_ret = statistics.mean(returns)
        std_ret = statistics.stdev(returns)
        
        # VaR (假设正态分布)
        import math
        z_score = 1.645 if confidence == 0.95 else 2.326  # 95% or 99%
        var = -(mean_ret - z_score * std_ret)
        
        return {
            "var_pct": round(var * 100, 2),
            "std_dev": round(std_ret * 100, 2),
            "mean_return": round(mean_ret * 100, 4),
            "confidence": confidence,
        }
    
    @staticmethod
    def calculate_position_size(
        capital: float,
        entry_price: float,
        stop_loss_price: float,
        max_risk_pct: float = 2.0,
    ) -> Dict:
        """
        计算建议仓位
        
        Args:
            capital: 总资金
            entry_price: 入场价
            stop_loss_price: 止损价
            max_risk_pct: 最大风险百分比
        """
        # 单笔最大亏损金额
        max_loss = capital * max_risk_pct / 100
        
        # 单股最大亏损
        loss_per_share = abs(entry_price - stop_loss_price)
        
        if loss_per_share == 0:
            return {"error": "止损价不能等于入场价"}
        
        # 计算最大股数
        max_shares = int(max_loss / loss_per_share)
        
        # 建议资金
        suggested_capital = max_shares * entry_price
        
        return {
            "max_shares": max_shares,
            "suggested_capital": round(suggested_capital, 2),
            "position_pct": round(suggested_capital / capital * 100, 2),
            "risk_per_share": round(loss_per_share, 2),
            "max_loss_amount": round(max_loss, 2),
        }


# ==================== 统一API ====================

class UnifiedTradingSystem:
    """统一交易系统"""
    
    def __init__(self):
        self.data_source = DataSourceManager()
        self.technicals = TechnicalAnalyzer()
        self.signals = SignalGenerator()
        self.risk = RiskAnalyzer()
    
    async def analyze_stock(self, stock_code: str) -> Dict:
        """
        完整股票分析
        
        Args:
            stock_code: 股票代码
        """
        # 1. 获取历史数据
        kline_data = await self.data_source.eastmoney_kline(stock_code, 365)
        
        if "error" in kline_data:
            return {"error": kline_data["error"]}
        
        # 2. 提取价格数据
        data = kline_data["data"]
        closes = [d["close"] for d in data]
        highs = [d["high"] for d in data]
        lows = [d["low"] for d in data]
        volumes = [d["volume"] for d in data]
        
        # 3. 计算技术指标
        ma5 = self.technicals.sma(closes, 5)
        ma10 = self.technicals.sma(closes, 10)
        ma20 = self.technicals.sma(closes, 20)
        macd = self.technicals.macd(closes)
        kdj = self.technicals.kdj(highs, lows, closes)
        rsi = self.technicals.rsi(closes)
        boll = self.technicals.bollinger(closes)
        
        # 4. 生成交易信号
        signal = self.signals.generate_signals(closes, highs, lows, volumes)
        
        # 5. 风险评估
        var = self.risk.calculate_var(closes)
        
        # 6. 获取实时价格
        realtime = await self.data_source.tencent_realtime([stock_code])
        
        return {
            "code": stock_code,
            "name": realtime.get("data", [{}])[0].get("name", "") if realtime.get("data") else "",
            "current_price": closes[-1],
            "technicals": {
                "ma5": ma5[-1] if ma5 else None,
                "ma10": ma10[-1] if ma10 else None,
                "ma20": ma20[-1] if ma20 else None,
                "macd": macd,
                "kdj": kdj,
                "rsi": rsi[-1] if rsi else None,
                "bollinger": boll,
            },
            "signal": signal,
            "risk": var,
            "realtime": realtime.get("data", [{}])[0] if realtime.get("data") else {},
            "timestamp": datetime.now().isoformat()
        }


# ==================== MCP工具注册 ====================

def register_tools(mcp):
    """注册MCP工具"""
    
    system = UnifiedTradingSystem()
    
    @mcp.tool()
    async def stock_realtime(stock_codes: str) -> dict:
        """
        获取股票实时行情
        
        Args:
            stock_codes: 股票代码，多个用逗号分隔，如 "600519,000001"
        """
        codes = [c.strip() for c in stock_codes.split(",")]
        return await system.data_source.tencent_realtime(codes)
    
    @mcp.tool()
    async def stock_kline(stock_code: str, days: int = 365) -> dict:
        """
        获取股票历史K线
        
        Args:
            stock_code: 股票代码
            days: 获取天数，默认365
        """
        return await system.data_source.eastmoney_kline(stock_code, days)
    
    @mcp.tool()
    async def stock_news(keyword: str, limit: int = 5) -> dict:
        """
        搜索股票新闻
        
        Args:
            keyword: 搜索关键词
            limit: 返回数量，默认5
        """
        return await system.data_source.sina_news(keyword, limit)
    
    @mcp.tool()
    async def stock_analyze(stock_code: str) -> dict:
        """
        完整股票分析：实时行情+技术指标+交易信号+风险评估
        
        Args:
            stock_code: 股票代码
        """
        return await system.analyze_stock(stock_code)
    
    @mcp.tool()
    def calculate_indicators(
        prices: str,
        indicator: str = "all"
    ) -> dict:
        """
        计算技术指标
        
        Args:
            prices: 价格序列，逗号分隔
            indicator: 指标类型 (ma/macd/kdj/rsi/boll/all)
        """
        price_list = [float(p.strip()) for p in prices.split(",")]
        
        result = {"prices_count": len(price_list)}
        
        if indicator in ["ma", "all"]:
            result["ma5"] = TechnicalAnalyzer.sma(price_list, 5)
            result["ma10"] = TechnicalAnalyzer.sma(price_list, 10)
            result["ma20"] = TechnicalAnalyzer.sma(price_list, 20)
        
        if indicator in ["macd", "all"]:
            result["macd"] = TechnicalAnalyzer.macd(price_list)
        
        if indicator in ["rsi", "all"]:
            result["rsi"] = TechnicalAnalyzer.rsi(price_list)
        
        if indicator in ["boll", "all"]:
            result["bollinger"] = TechnicalAnalyzer.bollinger(price_list)
        
        return result
    
    @mcp.tool()
    def calculate_position(
        capital: float,
        entry_price: float,
        stop_loss_price: float,
        max_risk_pct: float = 2.0
    ) -> dict:
        """
        计算建议仓位
        
        Args:
            capital: 总资金
            entry_price: 入场价
            stop_loss_price: 止损价
            max_risk_pct: 最大风险百分比，默认2%
        """
        return RiskAnalyzer.calculate_position_size(
            capital, entry_price, stop_loss_price, max_risk_pct
        )


# ==================== 测试 ====================

if __name__ == "__main__":
    async def test():
        print("=" * 60)
        print("统一交易系统测试")
        print("=" * 60)
        
        system = UnifiedTradingSystem()
        
        # 测试实时行情
        print("\n1. 实时行情测试 (600519 茅台)")
        result = await system.data_source.tencent_realtime(["600519"])
        if result.get("data"):
            stock = result["data"][0]
            print(f"  {stock['name']}({stock['code']})")
            print(f"  价格: {stock['price']}  涨跌: {stock['change_pct']}%")
        
        # 测试K线
        print("\n2. K线数据测试 (600519)")
        result = await system.data_source.eastmoney_kline("600519", 30)
        if result.get("data"):
            print(f"  获取到 {result['count']} 条K线数据")
            latest = result["data"][-1]
            print(f"  最新: {latest['date']} 收盘: {latest['close']}")
        
        # 测试技术指标
        print("\n3. 技术指标测试")
        prices = [100, 102, 101, 103, 105, 104, 106, 108, 107, 109,
                  111, 110, 112, 114, 113, 115, 117, 116, 118, 120]
        
        ma5 = TechnicalAnalyzer.sma(prices, 5)
        print(f"  MA5: {ma5[-3:]}")
        
        rsi = TechnicalAnalyzer.rsi(prices)
        print(f"  RSI: {rsi[-3:]}")
        
        # 测试信号生成
        print("\n4. 交易信号测试")
        highs = [p + 2 for p in prices]
        lows = [p - 2 for p in prices]
        signal = SignalGenerator.generate_signals(prices, highs, lows)
        print(f"  信号: {signal['signal']}")
        print(f"  置信度: {signal['confidence']}")
        print(f"  原因: {signal['reasons']}")
        
        # 测试风险评估
        print("\n5. 风险评估测试")
        var = RiskAnalyzer.calculate_var(prices)
        print(f"  VaR(95%): {var.get('var_pct', 'N/A')}%")
        
        # 测试仓位计算
        print("\n6. 仓位计算测试")
        position = RiskAnalyzer.calculate_position_size(
            capital=100000,
            entry_price=100,
            stop_loss_price=97,
            max_risk_pct=2
        )
        print(f"  建议股数: {position.get('max_shares', 'N/A')}")
        print(f"  建议资金: {position.get('suggested_capital', 'N/A')}")
        
        print("\n" + "=" * 60)
        print("测试完成!")
    
    asyncio.run(test())

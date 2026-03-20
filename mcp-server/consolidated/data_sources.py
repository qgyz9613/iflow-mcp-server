"""
A股主板数据源模块 - 合并版
整合以下模块:
- a_stock_data.py (A股数据)
- fundamental_data.py (基本面)
- batch_stock_news_fetcher.py (新闻)
- Ashare (新浪/腾讯双核心)

数据源优先级: 新浪(主力) -> 腾讯(备用)

说明:
- 只支持A股主板 (60/00/002开头)
- 不包括: 创业板(300)、科创板(688)、北交所(8开头)、ST股票
"""

import asyncio
import httpx
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union
import re


class AStockDataSource:
    """A股主板数据源 - 新浪/腾讯双核心"""
    
    # 主板代码规则
    MAINBOARD_PREFIX = ['60', '00', '002']  # 沪市主板、深市主板、中小板
    
    def __init__(self, timeout: float = 10.0):
        self.client = httpx.AsyncClient(timeout=timeout)
    
    async def close(self):
        await self.client.aclose()
    
    def is_mainboard(self, code: str) -> bool:
        """判断是否主板股票"""
        code = str(code).replace("sh", "").replace("sz", "").replace("bj", "").zfill(6).upper()
        # 排除ST (代码中包含ST或*ST)
        if 'ST' in code or code.startswith('*'):
            return False
        # 检查主板前缀
        for prefix in self.MAINBOARD_PREFIX:
            if code.startswith(prefix):
                return True
        return False
    
    def filter_mainboard(self, codes: List[str]) -> List[str]:
        """过滤出主板股票"""
        return [c for c in codes if self.is_mainboard(c)]
    
    def _normalize_code(self, code: str) -> str:
        """标准化股票代码为 sh/sz 格式"""
        code = str(code).replace("sh", "").replace("sz", "").replace("bj", "").zfill(6)
        if code.startswith('6'):
            return f"sh{code}"
        else:
            return f"sz{code}"
    
    # ==================== 实时行情 ====================
    
    async def realtime(self, codes: List[str]) -> Dict:
        """
        获取实时行情 - 腾讯API
        
        Args:
            codes: 股票代码列表 (自动过滤非主板)
        
        Returns:
            Dict with data and count
        """
        # 过滤主板股票
        mainboard_codes = self.filter_mainboard(codes)
        if not mainboard_codes:
            return {"data": [], "count": 0, "filtered": len(codes)}
        
        # 转换为腾讯格式
        symbols = []
        for code in mainboard_codes:
            code = str(code).replace("sh", "").replace("sz", "").zfill(6)
            if code.startswith('6'):
                symbols.append(f"sh{code}")
            else:
                symbols.append(f"sz{code}")
        
        url = f"https://qt.gtimg.cn/q={','.join(symbols)}"
        
        try:
            resp = await self.client.get(url)
            return self._parse_tencent(resp.text)
        except Exception as e:
            return {"data": [], "count": 0, "error": str(e)}
    
    def _parse_tencent(self, text: str) -> Dict:
        """解析腾讯数据格式"""
        results = []
        for line in text.strip().split(";"):
            if not line or '="' not in line:
                continue
            try:
                parts = line.split('="')[1].rstrip('"').split("~")
                if len(parts) >= 35:
                    code = parts[2]
                    # 再次过滤确保是主板
                    if not self.is_mainboard(code):
                        continue
                    results.append({
                        "name": parts[1],
                        "code": code,
                        "price": float(parts[3]) if parts[3] else None,
                        "change": float(parts[31]) if parts[31] else 0,
                        "change_pct": float(parts[32]) if parts[32] else 0,
                        "volume": int(float(parts[6])) if parts[6] else 0,
                        "amount": float(parts[37]) if len(parts) > 37 and parts[37] else 0,
                        "high": float(parts[33]) if parts[33] else None,
                        "low": float(parts[34]) if parts[34] else None,
                        "open": float(parts[5]) if parts[5] else None,
                        "prev_close": float(parts[4]) if parts[4] else None,
                    })
            except:
                continue
        return {"data": results, "count": len(results)}
    
    # ==================== K线数据 (双核心: 新浪主力, 腾讯备用) ====================
    
    async def _kline_sina(self, code: str, count: int = 365, frequency: str = "1d") -> pd.DataFrame:
        """
        新浪K线API - 主力
        
        支持: 1d日线, 1w周线, 1M月线, 5m/15m/30m/60m分钟线
        """
        # 频率转换: 1d->240m, 1w->1200m, 1M->7200m
        freq_map = {"1d": "240", "1w": "1200", "1M": "7200"}
        scale = freq_map.get(frequency, frequency.replace("m", ""))
        
        code = self._normalize_code(code)
        
        url = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        params = {"symbol": code, "scale": scale, "ma": "5", "datalen": count}
        
        resp = await self.client.get(url, params=params)
        data = json.loads(resp.text)
        
        if not data:
            raise Exception("新浪返回空数据")
        
        # 新浪格式: [{day, open, high, low, close, volume}, ...]
        df = pd.DataFrame(data)
        df = df.rename(columns={"day": "date"})
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
        
        return df[["date", "open", "high", "low", "close", "volume"]]
    
    async def _kline_tencent(self, code: str, count: int = 365, frequency: str = "1d") -> pd.DataFrame:
        """
        腾讯K线API - 备用
        
        支持: 1d日线, 1w周线, 1M月线
        """
        code = self._normalize_code(code)
        
        unit_map = {"1d": "day", "1w": "week", "1M": "month"}
        unit = unit_map.get(frequency, "day")
        
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},{unit},,{count},qfq"
        
        resp = await self.client.get(url)
        text = resp.text
        
        # 去掉JSONP前缀
        if "=" in text:
            text = text.split("=", 1)[1]
        
        data = json.loads(text)
        stock_data = data.get("data", {}).get(code, {})
        kline_list = stock_data.get("qfqday", []) or stock_data.get("day", [])
        
        if not kline_list:
            raise Exception("腾讯返回空数据")
        
        # 腾讯格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
        df = pd.DataFrame([{
            "date": d[0],
            "open": float(d[1]),
            "close": float(d[2]),
            "high": float(d[3]),
            "low": float(d[4]),
            "volume": int(float(d[5])),
        } for d in kline_list if len(d) >= 6])
        
        df["date"] = pd.to_datetime(df["date"])
        return df
    
    async def _kline_min_tencent(self, code: str, count: int = 100, frequency: str = "5m") -> pd.DataFrame:
        """
        腾讯分钟线API
        
        支持: 1m, 5m, 15m, 30m, 60m
        """
        code = self._normalize_code(code)
        ts = int(frequency.replace("m", ""))
        
        url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={code},m{ts},,{count}"
        
        resp = await self.client.get(url)
        data = json.loads(resp.text)
        
        buf = data.get("data", {}).get(code, {}).get(f"m{ts}", [])
        
        if not buf:
            raise Exception("腾讯分钟线返回空数据")
        
        # 分钟线格式: [时间, 开盘, 收盘, 最高, 最低, 成交量, n1, n2]
        df = pd.DataFrame(buf, columns=["time", "open", "close", "high", "low", "volume", "n1", "n2"])
        df = df[["time", "open", "close", "high", "low", "volume"]]
        for col in ["open", "close", "high", "low", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.rename(columns={"time": "date"})
        df["date"] = pd.to_datetime(df["date"])
        
        return df
    
    async def kline(self, code: str, count: int = 365, frequency: str = "1d") -> pd.DataFrame:
        """
        获取K线数据 - 双核心自动切换
        
        Args:
            code: 股票代码
            count: 数据条数
            frequency: 周期 (1d日线/1w周线/1M月线/1m~60m分钟线)
        
        Returns:
            DataFrame with [date, open, high, low, close, volume]
        """
        # 检查主板
        if not self.is_mainboard(code):
            print(f"非主板股票: {code}")
            return pd.DataFrame()
        
        code = self._normalize_code(code)
        
        # 日线/周线/月线: 新浪主力 -> 腾讯备用
        if frequency in ["1d", "1w", "1M"]:
            try:
                return await self._kline_sina(code, count, frequency)
            except Exception as e:
                print(f"新浪失败，切换腾讯: {e}")
                try:
                    return await self._kline_tencent(code, count, frequency)
                except Exception as e2:
                    print(f"腾讯也失败: {e2}")
                    return pd.DataFrame()
        
        # 分钟线: 新浪(5m/15m/30m/60m) -> 腾讯备用; 1m只有腾讯
        elif frequency.endswith("m"):
            if frequency == "1m":
                # 1分钟线只有腾讯支持
                try:
                    return await self._kline_min_tencent(code, count, frequency)
                except Exception as e:
                    print(f"腾讯分钟线失败: {e}")
                    return pd.DataFrame()
            else:
                # 5m/15m/30m/60m: 新浪主力 -> 腾讯备用
                try:
                    return await self._kline_sina(code, count, frequency)
                except Exception as e:
                    print(f"新浪分钟线失败，切换腾讯: {e}")
                    try:
                        return await self._kline_min_tencent(code, count, frequency)
                    except Exception as e2:
                        print(f"腾讯分钟线也失败: {e2}")
                        return pd.DataFrame()
        
        return pd.DataFrame()
    
    # ==================== 基本面数据 ====================
    
    async def fundamental(self, code: str) -> Dict:
        """
        获取基本面数据 - 腾讯API (从实时数据解析)
        
        Args:
            code: 股票代码
        
        Returns:
            Dict with PE, PB, 市值等
        """
        if not self.is_mainboard(code):
            return {}
        
        code = str(code).replace("sh", "").replace("sz", "").zfill(6)
        market = "sh" if code.startswith("6") else "sz"
        
        url = f"https://qt.gtimg.cn/q={market}{code}"
        
        try:
            resp = await self.client.get(url)
            text = resp.text
            
            # 解析腾讯数据
            parts = text.split('~')
            if len(parts) < 50:
                return {}
            
            return {
                "code": code,
                "name": parts[1] if len(parts) > 1 else "",
                "price": float(parts[3]) if parts[3] else 0,
                "pe": float(parts[39]) if len(parts) > 39 and parts[39] else None,
                "pb": float(parts[46]) if len(parts) > 46 and parts[46] else None,
                "total_mv": float(parts[45]) if len(parts) > 45 and parts[45] else None,  # 亿
                "turnover_rate": float(parts[38]) if len(parts) > 38 and parts[38] else None,
            }
        except Exception as e:
            print(f"获取基本面失败 {code}: {e}")
            return {}
    
    # ==================== 新闻数据 ====================
    
    async def news(self, keyword: str, limit: int = 10) -> List[Dict]:
        """
        获取股票新闻 - 新浪API
        
        Args:
            keyword: 搜索关键词 (股票代码或名称)
            limit: 数量限制
        
        Returns:
            List of news dict
        """
        url = f"https://search.api.sina.com.cn/?c=news&q={keyword}&page=1&num={limit}"
        
        try:
            resp = await self.client.get(url)
            data = resp.json()
            
            news = []
            for item in data.get("result", {}).get("list", [])[:limit]:
                news.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "time": item.get("time", ""),
                    "source": item.get("media", ""),
                })
            return news
        except Exception as e:
            print(f"获取新闻失败 {keyword}: {e}")
            return []
    
    # ==================== 涨幅榜 ====================
    
    async def top_gainers(self, top_n: int = 50, min_price: float = 3.0, 
                          max_price: float = 100.0, min_volume: float = 5000,
                          min_change: float = 2.0, max_change: float = 9.5) -> List[Dict]:
        """
        获取涨幅榜 - 新浪A股涨幅排名
        
        Args:
            top_n: 返回数量
            min_price: 最低价格
            max_price: 最高价格
            min_volume: 最小成交额(万)
            min_change: 最小涨幅%
            max_change: 最大涨幅% (排除涨停, 留买入空间)
        
        Returns:
            List of stock dict sorted by change_pct desc
        """
        # 新浪沪深A股涨幅榜
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {
            "page": 1,
            "num": top_n * 3,  # 多取一些用于过滤
            "sort": "changepercent",
            "asc": "0",
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "page"
        }
        
        try:
            resp = await self.client.get(url, params=params)
            data = json.loads(resp.text)
            
            if not isinstance(data, list):
                print(f"新浪返回格式异常: {type(data)}")
                return []
            
            # 解析数据
            all_stocks = []
            for item in data:
                try:
                    code = item.get("code", "")
                    
                    # 主板过滤
                    if not self.is_mainboard(code):
                        continue
                    
                    price = float(item.get("trade", 0) or 0)
                    change_pct = float(item.get("changepercent", 0) or 0)
                    amount = float(item.get("amount", 0) or 0)  # 万
                    
                    # 条件过滤
                    if price <= 0:
                        continue
                    if price < min_price or price > max_price:
                        continue
                    if amount < min_volume:
                        continue
                    if change_pct < min_change or change_pct > max_change:
                        continue
                    
                    all_stocks.append({
                        "name": item.get("name", ""),
                        "code": code,
                        "price": price,
                        "change_pct": change_pct,
                        "change": float(item.get("change", 0) or 0),
                        "high": float(item.get("high", 0) or 0),
                        "low": float(item.get("low", 0) or 0),
                        "open": float(item.get("open", 0) or 0),
                        "volume": int(float(item.get("volume", 0) or 0)),
                        "amount": amount,  # 新浪返回的是元
                        "turnover": float(item.get("turnoverratio", 0) or 0),
                    })
                except:
                    continue
            
            # 按涨幅排序
            all_stocks.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
            
            return all_stocks[:top_n]
            
        except Exception as e:
            print(f"新浪涨幅榜失败: {e}")
            # 备用: 返回热门股票
            return await self.top_gainers_simple(top_n)
    
    async def top_gainers_simple(self, top_n: int = 20) -> List[Dict]:
        """
        简单涨幅榜 - 腾讯API快速获取热门主板股票
        
        Args:
            top_n: 返回数量
        
        Returns:
            List of stock dict
        """
        # 腾讯热门股票代码
        hot_codes = [
            # 沪市主板热门
            "sh600519", "sh600036", "sh600276", "sh600887", "sh600030",
            "sh600016", "sh601318", "sh601166", "sh601398", "sh601288",
            "sh600028", "sh600019", "sh600050", "sh601857", "sh600900",
            # 深市主板热门
            "sz000001", "sz000002", "sz000333", "sz000651", "sz000858",
            "sz000063", "sz000725", "sz000069", "sz000568",
            # 中小板热门
            "sz002415", "sz002594", "sz002304", "sz002352", "sz002475",
            "sz002236", "sz002410", "sz002230", "sz002008", "sz002142",
        ]
        
        url = f"https://qt.gtimg.cn/q={','.join(hot_codes)}"
        
        try:
            resp = await self.client.get(url)
            data = self._parse_tencent(resp.text)
            stocks = data.get("data", [])
            stocks.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
            return stocks[:top_n]
        except Exception as e:
            print(f"获取涨幅榜失败: {e}")
            return []


# ============================================================
# 同步接口
# ============================================================

class AStockDataSourceSync:
    """同步接口包装"""
    
    def __init__(self):
        self._async = AStockDataSource()
    
    def realtime(self, codes: List[str]) -> Dict:
        return asyncio.run(self._async.realtime(codes))
    
    def kline(self, code: str, days: int = 365) -> pd.DataFrame:
        return asyncio.run(self._async.kline(code, days))
    
    def fundamental(self, code: str) -> Dict:
        return asyncio.run(self._async.fundamental(code))
    
    def news(self, keyword: str, limit: int = 10) -> List[Dict]:
        return asyncio.run(self._async.news(keyword, limit))
    
    def top_gainers(self, top_n: int = 50, **kwargs) -> List[Dict]:
        return asyncio.run(self._async.top_gainers(top_n, **kwargs))
    
    def is_mainboard(self, code: str) -> bool:
        return self._async.is_mainboard(code)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    async def test():
        ds = AStockDataSource()
        
        print("=" * 60)
        print("A股主板数据源测试")
        print("=" * 60)
        
        # 1. 测试主板判断
        print("\n1. 主板判断测试:")
        test_codes = ["600519", "000001", "300001", "688001", "002415", "ST某某"]
        for code in test_codes:
            result = "✓主板" if ds.is_mainboard(code) else "✗非主板"
            print(f"   {code}: {result}")
        
        # 2. 测试实时行情
        print("\n2. 实时行情 (600519茅台, 000001平安):")
        data = await ds.realtime(["600519", "000001", "300001"])  # 故意加入创业板测试过滤
        for s in data.get("data", []):
            print(f"   {s['name']}({s['code']}): {s['price']}元, {s['change_pct']:+.2f}%")
        print(f"   过滤掉非主板: {data.get('filtered', 0)}只")
        
        # 3. 测试K线
        print("\n3. K线数据 (600519, 30天):")
        df = await ds.kline("600519", 30)
        if not df.empty:
            print(f"   获取 {len(df)} 条记录")
            print(f"   最新: {df.iloc[-1]['date']} 收盘:{df.iloc[-1]['close']}")
        else:
            print("   获取失败")
        
        # 4. 测试基本面
        print("\n4. 基本面数据 (600519):")
        fund = await ds.fundamental("600519")
        if fund:
            print(f"   PE: {fund.get('pe')}, PB: {fund.get('pb')}")
            print(f"   总市值: {fund.get('total_mv')}亿")
        else:
            print("   获取失败")
        
        # 5. 测试涨幅榜
        print("\n5. 涨幅榜Top10 (主板, 涨幅0-10%, 成交>1000万):")
        gainers = await ds.top_gainers(10, min_price=3, max_price=100, min_volume=1000, min_change=0, max_change=10)
        for i, s in enumerate(gainers, 1):
            print(f"   {i}. {s['name']}({s['code']}): {s['price']}元, {s['change_pct']:+.2f}%, 成交{s['amount']/100000000:.2f}亿, 换手{s['turnover']:.1f}%")
        
        await ds.close()
        print("\n" + "=" * 60)
        print("测试完成!")
    
    asyncio.run(test())
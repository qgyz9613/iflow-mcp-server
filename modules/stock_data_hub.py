# -*- coding: utf-8 -*-
"""
股票数据统一入口 - StockDataHub

整合数据源：
1. MX_Skills (东财API) - 优先，需EM_API_KEY
2. AKShare - 回退，永久免费
3. Tushare - 历史数据，需Token
4. PostgreSQL - 本地存储缓存
5. efinance - 备用数据源

统一接口：
- get_realtime_quote() - 实时行情
- get_stock_pick() - 选股
- get_financial_data() - 财务数据
- get_historical_data() - 历史K线
- get_macro_data() - 宏观数据

特性：
- 自动降级：优先级失败自动切换
- 智能缓存：减少API调用
- 统一格式：标准化输出
"""

import asyncio
import json
import os
import re
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import httpx
import pandas as pd

# ============== 配置 ==============

SECRETS_PATH = Path(__file__).parent.parent / "secrets.json"
_secrets = {}
if SECRETS_PATH.exists():
    try:
        _secrets = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    except:
        pass

# API密钥配置
EM_API_KEY = _secrets.get("eastmoney_em", os.environ.get("EM_API_KEY", ""))
TUSHARE_TOKEN = _secrets.get("tushare_token", os.environ.get("TUSHARE_TOKEN", ""))

# PostgreSQL配置
PG_CONFIG = {
    "host": "38.165.21.21",
    "port": 5432,
    "database": "postgres",
    "user": "admin",
    "password": "SX7YRCwXszkdtd4B"
}

# API端点
EM_SELECT_URL = "https://ai-saas.eastmoney.com/proxy/b/mcp/tool/selectSecurity"
EM_SEARCH_URL = "https://ai-saas.eastmoney.com/proxy/b/mcp/tool/searchData"
EM_MACRO_URL = "https://ai-saas.eastmoney.com/proxy/b/mcp/tool/searchMacroData"

# 缓存配置
CACHE_DIR = Path(__file__).parent.parent / "cache" / "stock_data"
CACHE_TTL = {
    "realtime": 30,      # 实时行情30秒
    "quote": 60,         # 行情1分钟
    "financial": 3600,   # 财务数据1小时
    "macro": 3600,       # 宏观数据1小时
    "historical": 86400, # 历史数据1天
    "news": 300,         # 新闻数据5分钟
}


# ============== 数据源优先级 ==============

class DataSource(Enum):
    MX_SKILLS = "MX_Skills"      # 东财MCP
    AKSHARE = "AKShare"          # AKShare
    TUSHARE = "Tushare"          # Tushare
    EFINANCE = "efinance"        # efinance
    POSTGRES = "PostgreSQL"      # 本地数据库
    CACHE = "Cache"              # 缓存


# ============== 缓存管理 ==============

class DataCache:
    """智能数据缓存"""
    
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: Dict[str, Any] = {}
        self._cache_time: Dict[str, float] = {}
    
    def _get_cache_key(self, prefix: str, *args, **kwargs) -> str:
        """生成缓存键"""
        key_parts = [prefix]
        key_parts.extend(str(a) for a in args)
        key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return "_".join(key_parts)
    
    def get(self, key: str, ttl: int = 60) -> Optional[Any]:
        """获取缓存"""
        # 先检查内存缓存
        if key in self._memory_cache:
            if time.time() - self._cache_time.get(key, 0) < ttl:
                return self._memory_cache[key]
        
        # 检查文件缓存
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if time.time() - data.get("timestamp", 0) < ttl:
                    self._memory_cache[key] = data.get("data")
                    self._cache_time[key] = data["timestamp"]
                    return data.get("data")
            except:
                pass
        return None
    
    def set(self, key: str, data: Any) -> None:
        """设置缓存"""
        timestamp = time.time()
        self._memory_cache[key] = data
        self._cache_time[key] = timestamp
        
        # 写入文件缓存
        cache_file = self.cache_dir / f"{key}.json"
        try:
            # 确保缓存目录存在
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps({"timestamp": timestamp, "data": data}, ensure_ascii=False, default=str),
                encoding="utf-8"
            )
        except (OSError, IOError, json.JSONEncodeError, PermissionError) as e:
            # 文件写入失败时记录警告但不中断程序
            import logging
            logging.warning(f"缓存文件写入失败 [{key}]: {e}")
        except Exception as e:
            # 其他未知错误
            import logging
            logging.error(f"缓存写入未知错误 [{key}]: {e}")
    
    def clear(self, prefix: str = None) -> None:
        """清除缓存"""
        if prefix:
            keys_to_remove = [k for k in self._memory_cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._memory_cache[k]
                cache_file = self.cache_dir / f"{k}.json"
                if cache_file.exists():
                    cache_file.unlink()
        else:
            self._memory_cache.clear()
            for f in self.cache_dir.glob("*.json"):
                f.unlink()


# 全局缓存实例
_cache = DataCache()


# ============== 数据源适配器 ==============

class DataSourceAdapter(ABC):
    """数据源适配器基类"""
    
    @abstractmethod
    async def get_realtime_quote(self, stock_codes: List[str]) -> Dict[str, Any]:
        """获取实时行情"""
        pass
    
    @abstractmethod
    async def get_stock_pick(self, query: str, select_type: str) -> Dict[str, Any]:
        """选股"""
        pass
    
    @abstractmethod
    async def get_financial_data(self, query: str) -> Dict[str, Any]:
        """获取财务数据"""
        pass
    
    @abstractmethod
    async def get_historical_data(
        self, ticker: str, start: str, end: str
    ) -> pd.DataFrame:
        """获取历史K线"""
        pass
    
    @abstractmethod
    async def get_macro_data(self, query: str) -> Dict[str, Any]:
        """获取宏观数据"""
        pass


class MXSkillsAdapter(DataSourceAdapter):
    """东财MX_Skills适配器"""
    
    def __init__(self, api_key: str = EM_API_KEY):
        self.api_key = api_key
        self.timeout = 30.0
    
    async def _call_api(self, url: str, body: dict) -> dict:
        """调用东财API"""
        if not self.api_key:
            return {"error": "EM_API_KEY未配置", "fallback": True}
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(
                    url,
                    json=body,
                    headers={
                        "Content-Type": "application/json",
                        "em_api_key": self.api_key,
                    }
                )
                data = r.json()
                if data.get("code") in (200, 0) and data.get("data"):
                    return {"success": True, "data": data["data"]}
                else:
                    return {"error": data.get("message", "接口错误"), "fallback": True}
        except Exception as e:
            return {"error": str(e), "fallback": True}
    
    async def get_realtime_quote(self, stock_codes: List[str]) -> Dict[str, Any]:
        """实时行情 - MX_Skills暂不支持直接行情查询，使用AKShare"""
        return {"error": "MX_Skills不支持实时行情", "fallback": True}
    
    async def get_stock_pick(self, query: str, select_type: str = "A股") -> Dict[str, Any]:
        """选股"""
        body = {
            "query": query,
            "selectType": select_type,
            "toolContext": {
                "callId": str(uuid.uuid4()),
                "userInfo": {"userId": self.api_key}
            }
        }
        
        result = await self._call_api(EM_SELECT_URL, body)
        
        if result.get("success"):
            data = result["data"]
            all_results = data.get("allResults", {}).get("result", {})
            data_list = all_results.get("dataList", [])
            columns = all_results.get("columns", [])
            
            if data_list:
                return {
                    "source": DataSource.MX_SKILLS.value,
                    "success": True,
                    "count": len(data_list),
                    "data": data_list,
                    "columns": columns,
                    "query": query
                }
        
        return {"error": result.get("error"), "fallback": True}
    
    async def get_financial_data(self, query: str) -> Dict[str, Any]:
        """财务数据"""
        body = {
            "query": query,
            "toolContext": {
                "callId": str(uuid.uuid4()),
                "userInfo": {"userId": self.api_key}
            }
        }
        
        result = await self._call_api(EM_SEARCH_URL, body)
        
        if result.get("success"):
            data = result["data"]
            dto_list = data.get("dataTableDTOList", [])
            
            if dto_list:
                return {
                    "source": DataSource.MX_SKILLS.value,
                    "success": True,
                    "data": dto_list,
                    "query": query
                }
        
        return {"error": result.get("error"), "fallback": True}
    
    async def get_historical_data(
        self, ticker: str, start: str, end: str
    ) -> pd.DataFrame:
        """历史K线 - MX_Skills不支持，使用其他数据源"""
        return pd.DataFrame()
    
    async def get_macro_data(self, query: str) -> Dict[str, Any]:
        """宏观数据"""
        body = {
            "query": query,
            "toolContext": {
                "callId": str(uuid.uuid4()),
                "userInfo": {"userId": self.api_key}
            }
        }
        
        result = await self._call_api(EM_MACRO_URL, body)
        
        if result.get("success"):
            return {
                "source": DataSource.MX_SKILLS.value,
                "success": True,
                "data": result["data"],
                "query": query
            }
        
        return {"error": result.get("error"), "fallback": True}


class AKShareAdapter(DataSourceAdapter):
    """AKShare适配器"""
    
    def __init__(self):
        self._akshare = None
    
    @property
    def akshare(self):
        if self._akshare is None:
            import akshare as ak
            self._akshare = ak
        return self._akshare
    
    async def get_realtime_quote(self, stock_codes: List[str]) -> Dict[str, Any]:
        """实时行情 - 多数据源备用"""
        
        # 清理代码格式
        codes_clean = []
        for code in stock_codes:
            clean = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
            codes_clean.append(clean)
        
        # 方法1: stock_zh_a_spot_em (可能不稳定)
        try:
            df = self.akshare.stock_zh_a_spot_em()
            result = df[df["代码"].isin(codes_clean)]
            if len(result) > 0:
                return {
                    "source": "AKShare_spot_em",
                    "success": True,
                    "count": len(result),
                    "data": result.to_dict("records"),
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            pass  # 继续尝试备用方案
        
        # 方法2: stock_bid_ask_em (五档数据，更稳定)
        try:
            import requests
            results = []
            
            for code in codes_clean:
                try:
                    df2 = self.akshare.stock_bid_ask_em(symbol=code)
                    if df2 is not None and len(df2) > 0:
                        # 从五档数据提取信息
                        row_dict = dict(zip(df2['item'], df2['value']))
                        
                        results.append({
                            "代码": code,
                            "最新价": row_dict.get("最新", 0),
                            "今开": row_dict.get("今开", 0),
                            "昨收": row_dict.get("昨收", 0),
                            "最高": row_dict.get("最高", 0),
                            "最低": row_dict.get("最低", 0),
                            "涨跌幅": row_dict.get("涨幅", 0),
                            "涨跌额": row_dict.get("涨跌", 0),
                            "成交量": row_dict.get("总手", 0),
                            "成交额": row_dict.get("金额", 0),
                            "换手率": row_dict.get("换手", 0),
                            "涨停": row_dict.get("涨停", 0),
                            "跌停": row_dict.get("跌停", 0),
                        })
                except Exception:
                    continue
            
            if results:
                return {
                    "source": "AKShare_bid_ask",
                    "success": True,
                    "count": len(results),
                    "data": results,
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            pass  # 继续尝试新浪API
        
        # 方法3: 新浪API (最稳定)
        try:
            import requests
            
            # 构建请求
            symbols = []
            for code in codes_clean:
                if code.startswith("6"):
                    symbols.append(f"sh{code}")
                elif code.startswith("0") or code.startswith("3"):
                    symbols.append(f"sz{code}")
                else:
                    symbols.append(f"sh{code}")
            
            url = f"https://hq.sinajs.cn/list={','.join(symbols)}"
            headers = {"Referer": "https://finance.sina.com.cn"}
            resp = requests.get(url, headers=headers, timeout=5)
            resp.encoding = "gbk"
            
            results = []
            lines = resp.text.strip().split("\n")
            
            for line in lines:
                if "hq_str_" not in line:
                    continue
                    
                try:
                    code = line.split("_")[2].split("=")[0]
                    data_str = line.split('"')[1]
                    
                    if not data_str:
                        continue
                    
                    parts = data_str.split(",")
                    if len(parts) >= 32:
                        name = parts[0]
                        open_price = float(parts[1]) if parts[1] else 0
                        last_close = float(parts[2]) if parts[2] else 0
                        current = float(parts[3]) if parts[3] else 0
                        high = float(parts[4]) if parts[4] else 0
                        low = float(parts[5]) if parts[5] else 0
                        volume = float(parts[8]) if parts[8] else 0
                        amount = float(parts[9]) if parts[9] else 0
                        
                        change = current - last_close if current and last_close else 0
                        change_pct = (change / last_close * 100) if last_close else 0
                        
                        results.append({
                            "代码": code.replace("sh", "").replace("sz", ""),
                            "名称": name,
                            "最新价": current,
                            "今开": open_price,
                            "昨收": last_close,
                            "最高": high,
                            "最低": low,
                            "涨跌幅": round(change_pct, 2),
                            "涨跌额": round(change, 2),
                            "成交量": volume,
                            "成交额": amount,
                        })
                except Exception:
                    continue
            
            if results:
                return {
                    "source": "Sina_API",
                    "success": True,
                    "count": len(results),
                    "data": results,
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            pass
        
        # 方法4: 东方财富API
        try:
            import requests
            
            results = []
            for code in codes_clean:
                try:
                    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
                    url = "https://push2.eastmoney.com/api/qt/stock/get"
                    params = {
                        "secid": secid,
                        "fields": "f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f55,f57,f58,f60"
                    }
                    resp = requests.get(url, params=params, timeout=5)
                    data = resp.json()
                    
                    if data and "data" in data and data["data"]:
                        d = data["data"]
                        
                        results.append({
                            "代码": code,
                            "名称": d.get("f58", ""),
                            "最新价": d.get("f43", 0) / 100 if d.get("f43") else 0,
                            "最高": d.get("f44", 0) / 100 if d.get("f44") else 0,
                            "最低": d.get("f45", 0) / 100 if d.get("f45") else 0,
                            "今开": d.get("f46", 0) / 100 if d.get("f46") else 0,
                            "昨收": d.get("f60", 0) / 100 if d.get("f60") else 0,
                            "涨跌幅": d.get("f52", 0) / 100 if d.get("f52") else 0,
                            "涨跌额": d.get("f51", 0) / 100 if d.get("f51") else 0,
                            "成交量": d.get("f47", 0),
                        })
                except Exception:
                    continue
            
            if results:
                return {
                    "source": "EastMoney_API",
                    "success": True,
                    "count": len(results),
                    "data": results,
                    "timestamp": datetime.now().isoformat()
                }
        except Exception:
            pass
        
        return {
            "source": DataSource.AKSHARE.value,
            "success": False,
            "error": "所有数据源均获取失败",
            "count": 0,
            "data": []
        }
    
    async def get_stock_pick(self, query: str, select_type: str) -> Dict[str, Any]:
        """选股 - 解析自然语言条件"""
        try:
            df = self.akshare.stock_zh_a_spot_em()
            result_df = df.copy()
            
            # 解析查询条件
            # 股价大于X元
            price_match = re.search(r"股价[大>]于?(\d+)元?", query)
            if price_match:
                price = float(price_match.group(1))
                result_df = result_df[result_df["最新价"] > price]
            
            # 涨幅大于X%
            up_match = re.search(r"涨幅[大>]于?(\d+)[%％]", query)
            if up_match:
                up_pct = float(up_match.group(1))
                result_df = result_df[result_df["涨跌幅"] > up_pct]
            
            # 市值小于X亿
            cap_match = re.search(r"市值[小<]于?(\d+)亿", query)
            if cap_match:
                cap = float(cap_match.group(1)) * 1e8
                result_df = result_df[result_df["总市值"] < cap]
            
            # 成交额大于X亿
            amount_match = re.search(r"成交额[大>]于?(\d+)亿", query)
            if amount_match:
                amount = float(amount_match.group(1)) * 1e8
                result_df = result_df[result_df["成交额"] > amount]
            
            # 换手率X%-Y%
            turnover_match = re.search(r"换手率(\d+)[%％]?[~-](\d+)[%％]?", query)
            if turnover_match:
                low = float(turnover_match.group(1))
                high = float(turnover_match.group(2))
                result_df = result_df[(result_df["换手率"] >= low) & (result_df["换手率"] <= high)]
            
            result_df = result_df.head(50)
            
            return {
                "source": DataSource.AKSHARE.value,
                "success": True,
                "count": len(result_df),
                "data": result_df.to_dict("records"),
                "columns": list(result_df.columns),
                "query": query
            }
        except Exception as e:
            return {"error": str(e), "success": False}
    
    async def get_financial_data(self, query: str) -> Dict[str, Any]:
        """财务数据"""
        try:
            # 解析股票代码
            code_match = re.search(r"(\d{6})", query)
            if not code_match:
                return {"error": "无法识别股票代码", "success": False}
            
            code = code_match.group(1)
            df = self.akshare.stock_financial_abstract_em(symbol=code)
            
            return {
                "source": DataSource.AKSHARE.value,
                "success": True,
                "code": code,
                "data": df.to_dict("records")[:10],
                "columns": list(df.columns),
                "query": query
            }
        except Exception as e:
            return {"error": str(e), "success": False}
    
    async def get_historical_data(
        self, ticker: str, start: str, end: str
    ) -> pd.DataFrame:
        """历史K线"""
        try:
            df = self.akshare.stock_zh_a_hist(
                symbol=ticker,
                period="daily",
                start_date=start.replace("-", ""),
                end_date=end.replace("-", ""),
                adjust="qfq"  # 前复权
            )
            
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "Date",
                    "开盘": "Open",
                    "收盘": "Close",
                    "最高": "High",
                    "最低": "Low",
                    "成交量": "Volume",
                    "成交额": "Amount",
                    "涨跌幅": "ChangePct",
                    "涨跌额": "Change",
                    "换手率": "Turnover"
                })
                df["Date"] = pd.to_datetime(df["Date"])
                df.set_index("Date", inplace=True)
            
            return df
        except Exception as e:
            return pd.DataFrame()
    
    async def get_macro_data(self, query: str) -> Dict[str, Any]:
        """宏观数据"""
        try:
            result = {"source": DataSource.AKSHARE.value, "success": True, "query": query, "data": {}}
            
            if "GDP" in query or "gdp" in query:
                df = self.akshare.macro_china_gdp()
                result["data"]["GDP"] = df.to_dict("records")[-20:]
            
            if "CPI" in query or "cpi" in query or "通胀" in query:
                df = self.akshare.macro_china_cpi_yearly()
                result["data"]["CPI"] = df.to_dict("records")[-20:]
            
            if "M2" in query or "货币" in query:
                df = self.akshare.macro_china_m2_yearly()
                result["data"]["M2"] = df.to_dict("records")[-20:]
            
            return result
        except Exception as e:
            return {"error": str(e), "success": False}


class TushareAdapter(DataSourceAdapter):
    """Tushare适配器"""
    
    def __init__(self, token: str = TUSHARE_TOKEN):
        self.token = token
        self._pro = None
    
    @property
    def pro(self):
        if self._pro is None and self.token:
            import tushare as ts
            ts.set_token(self.token)
            self._pro = ts.pro_api()
        return self._pro
    
    async def get_realtime_quote(self, stock_codes: List[str]) -> Dict[str, Any]:
        """实时行情 - Tushare Pro需要积分"""
        return {"error": "Tushare需要积分支持实时行情", "fallback": True}
    
    async def get_stock_pick(self, query: str, select_type: str) -> Dict[str, Any]:
        """选股"""
        return {"error": "Tushare不支持自然语言选股", "fallback": True}
    
    async def get_financial_data(self, query: str) -> Dict[str, Any]:
        """财务数据"""
        if not self.pro:
            return {"error": "Tushare Token未配置", "fallback": True}
        
        try:
            code_match = re.search(r"(\d{6})", query)
            if not code_match:
                return {"error": "无法识别股票代码", "success": False}
            
            code = code_match.group(1)
            ts_code = f"{code}.SH" if code.startswith("6") else f"{code}.SZ"
            
            df = self.pro.daily_basic(ts_code=ts_code, fields=[
                "pe", "pb", "ps", "dv_ratio", "total_mv", "circ_mv"
            ])
            
            return {
                "source": DataSource.TUSHARE.value,
                "success": True,
                "code": code,
                "data": df.to_dict("records"),
                "query": query
            }
        except Exception as e:
            return {"error": str(e), "success": False}
    
    async def get_historical_data(
        self, ticker: str, start: str, end: str
    ) -> pd.DataFrame:
        """历史K线"""
        if not self.pro:
            return pd.DataFrame()
        
        try:
            ts_code = f"{ticker}.SH" if ticker.startswith("6") else f"{ticker}.SZ"
            df = self.pro.daily(
                ts_code=ts_code,
                start_date=start.replace("-", ""),
                end_date=end.replace("-", "")
            )
            
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "trade_date": "Date",
                    "open": "Open",
                    "close": "Close",
                    "high": "High",
                    "low": "Low",
                    "vol": "Volume",
                    "amount": "Amount"
                })
                df["Date"] = pd.to_datetime(df["Date"])
                df.set_index("Date", inplace=True)
                df.sort_index(inplace=True)
            
            return df
        except:
            return pd.DataFrame()
    
    async def get_macro_data(self, query: str) -> Dict[str, Any]:
        """宏观数据"""
        if not self.pro:
            return {"error": "Tushare Token未配置", "fallback": True}
        
        try:
            result = {"source": DataSource.TUSHARE.value, "success": True, "query": query, "data": {}}
            
            if "GDP" in query or "gdp" in query:
                df = self.pro.cn_gdp()
                result["data"]["GDP"] = df.to_dict("records")[-20:]
            
            if "CPI" in query or "cpi" in query:
                df = self.pro.cn_cpi()
                result["data"]["CPI"] = df.to_dict("records")[-20:]
            
            return result
        except Exception as e:
            return {"error": str(e), "success": False}


class PostgresAdapter(DataSourceAdapter):
    """PostgreSQL本地数据库适配器
    
    注意：psycopg2是同步库，这里通过asyncio.to_thread包装为异步方法
    """
    
    def __init__(self, config: dict = PG_CONFIG):
        self.config = config
        self._conn = None
        self._lock = asyncio.Lock()
    
    def _sync_connect(self):
        """同步连接方法（内部使用）"""
        try:
            import psycopg2
            return psycopg2.connect(**self.config)
        except Exception:
            return None
    
    async def _get_connection(self):
        """获取数据库连接 - 异步包装"""
        async with self._lock:
            if self._conn is None:
                self._conn = await asyncio.to_thread(self._sync_connect)
        return self._conn
    
    def _sync_query_quote(self, stock_codes: List[str]) -> Dict[str, Any]:
        """同步查询行情（内部使用）"""
        import psycopg2.extras
        conn = self._conn
        if not conn:
            return {"error": "数据库连接失败", "fallback": True}
        
        try:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            placeholders = ",".join(["%s"] * len(stock_codes))
            sql = f"""
                SELECT * FROM stocks 
                WHERE code IN ({placeholders})
                ORDER BY code
            """
            cursor.execute(sql, stock_codes)
            rows = cursor.fetchall()
            
            return {
                "source": DataSource.POSTGRES.value,
                "success": True,
                "count": len(rows),
                "data": [dict(r) for r in rows],
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": str(e), "success": False}
    
    async def get_realtime_quote(self, stock_codes: List[str]) -> Dict[str, Any]:
        """实时行情 - 从本地数据库查询（异步）"""
        conn = await self._get_connection()
        if not conn:
            return {"error": "数据库连接失败", "fallback": True}
        return await asyncio.to_thread(self._sync_query_quote, stock_codes)
    
    async def get_stock_pick(self, query: str, select_type: str) -> Dict[str, Any]:
        """选股 - 本地数据库不支持"""
        return {"error": "本地数据库不支持选股", "fallback": True}
    
    async def get_financial_data(self, query: str) -> Dict[str, Any]:
        """财务数据"""
        return {"error": "本地数据库暂无财务数据", "fallback": True}
    
    def _sync_query_historical(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """同步查询历史K线（内部使用）"""
        import psycopg2.extras
        conn = self._conn
        if not conn:
            return pd.DataFrame()
        
        try:
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            sql = """
                SELECT trade_date as date, open, high, low, close, volume
                FROM stock_prices
                WHERE code = %s 
                AND trade_date BETWEEN %s AND %s
                ORDER BY trade_date
            """
            cursor.execute(sql, (ticker, start, end))
            rows = cursor.fetchall()
            
            if rows:
                df = pd.DataFrame([dict(r) for r in rows])
                df["date"] = pd.to_datetime(df["date"])
                df.set_index("date", inplace=True)
                return df
        except Exception:
            pass
        
        return pd.DataFrame()
    
    async def get_historical_data(
        self, ticker: str, start: str, end: str
    ) -> pd.DataFrame:
        """历史K线（异步）"""
        conn = await self._get_connection()
        if not conn:
            return pd.DataFrame()
        return await asyncio.to_thread(self._sync_query_historical, ticker, start, end)
    
    async def get_macro_data(self, query: str) -> Dict[str, Any]:
        """宏观数据"""
        return {"error": "本地数据库暂无宏观数据", "fallback": True}


# ============== 统一数据入口 ==============

class StockDataHub:
    """
    股票数据统一入口
    
    数据源优先级：
    1. 缓存 - 优先检查缓存
    2. MX_Skills - 东财API（需EM_API_KEY）
    3. AKShare - 免费数据源
    4. Tushare - 历史数据（需Token）
    5. PostgreSQL - 本地存储
    """
    
    def __init__(
        self,
        use_cache: bool = True,
        cache_ttl: Optional[Dict[str, int]] = None
    ):
        self.use_cache = use_cache
        self.cache_ttl = cache_ttl or CACHE_TTL
        
        # 初始化数据源适配器
        self.adapters = {
            DataSource.MX_SKILLS: MXSkillsAdapter(),
            DataSource.AKSHARE: AKShareAdapter(),
            DataSource.TUSHARE: TushareAdapter(),
            DataSource.POSTGRES: PostgresAdapter(),
        }
        
        # 数据源优先级
        self.priority = [
            DataSource.MX_SKILLS,
            DataSource.AKSHARE,
            DataSource.TUSHARE,
            DataSource.POSTGRES,
        ]
    
    async def get_realtime_quote(
        self,
        stock_codes: Union[str, List[str]]
    ) -> Dict[str, Any]:
        """
        获取实时行情
        
        Args:
            stock_codes: 股票代码或代码列表
                         支持 "600519" 或 "sh600519" 格式
        
        Returns:
            {
                "source": 数据源名称,
                "success": 是否成功,
                "count": 数量,
                "data": 行情数据列表,
                "timestamp": 时间戳
            }
        """
        if isinstance(stock_codes, str):
            stock_codes = [stock_codes]
        
        # 检查缓存
        cache_key = _cache._get_cache_key("realtime", stock_codes)
        if self.use_cache:
            cached = _cache.get(cache_key, self.cache_ttl["realtime"])
            if cached:
                cached["source"] = DataSource.CACHE.value
                return cached
        
        # 按优先级尝试
        for source in [DataSource.AKSHARE, DataSource.POSTGRES]:  # 实时行情MX_Skills不支持
            adapter = self.adapters.get(source)
            if adapter:
                result = await adapter.get_realtime_quote(stock_codes)
                if result.get("success"):
                    if self.use_cache:
                        _cache.set(cache_key, result)
                    return result
                if not result.get("fallback"):
                    return result
        
        return {"error": "所有数据源均获取失败", "success": False}
    
    async def get_stock_pick(
        self,
        query: str,
        select_type: str = "A股"
    ) -> Dict[str, Any]:
        """
        智能选股
        
        Args:
            query: 自然语言查询
                   如 "股价大于100元的股票"
                   如 "涨幅大于5%成交额大于1亿的股票"
            select_type: A股/港股/美股/基金/ETF/可转债/板块
        
        Returns:
            {
                "source": 数据源名称,
                "success": 是否成功,
                "count": 数量,
                "data": 股票列表,
                "columns": 列名,
                "query": 查询语句
            }
        """
        # 检查缓存
        cache_key = _cache._get_cache_key("stock_pick", query, select_type)
        if self.use_cache:
            cached = _cache.get(cache_key, self.cache_ttl["quote"])
            if cached:
                cached["source"] = DataSource.CACHE.value
                return cached
        
        # 按优先级尝试
        for source in self.priority:
            adapter = self.adapters.get(source)
            if adapter:
                result = await adapter.get_stock_pick(query, select_type)
                if result.get("success"):
                    if self.use_cache:
                        _cache.set(cache_key, result)
                    return result
                if not result.get("fallback"):
                    return result
        
        return {"error": "所有数据源均选股失败", "success": False}
    
    async def get_financial_data(self, query: str) -> Dict[str, Any]:
        """
        获取财务数据
        
        Args:
            query: 自然语言查询
                   如 "600519贵州茅台营收"
                   如 "000001平安银行利润"
        
        Returns:
            {
                "source": 数据源名称,
                "success": 是否成功,
                "data": 财务数据,
                "query": 查询语句
            }
        """
        # 检查缓存
        cache_key = _cache._get_cache_key("financial", query)
        if self.use_cache:
            cached = _cache.get(cache_key, self.cache_ttl["financial"])
            if cached:
                cached["source"] = DataSource.CACHE.value
                return cached
        
        # 按优先级尝试
        for source in self.priority:
            adapter = self.adapters.get(source)
            if adapter:
                result = await adapter.get_financial_data(query)
                if result.get("success"):
                    if self.use_cache:
                        _cache.set(cache_key, result)
                    return result
                if not result.get("fallback"):
                    return result
        
        return {"error": "所有数据源均获取失败", "success": False}
    
    async def get_historical_data(
        self,
        ticker: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        period_days: int = 365
    ) -> pd.DataFrame:
        """
        获取历史K线数据
        
        Args:
            ticker: 股票代码 (如 "600519")
            start: 开始日期 (如 "2024-01-01")
            end: 结束日期 (如 "2024-12-31")
            period_days: 如果未指定日期，获取最近N天
        
        Returns:
            DataFrame: Date, Open, High, Low, Close, Volume
        """
        if not end:
            end = datetime.now().strftime("%Y-%m-%d")
        if not start:
            start = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")
        
        # 检查缓存
        cache_key = _cache._get_cache_key("historical", ticker, start, end)
        if self.use_cache:
            cached = _cache.get(cache_key, self.cache_ttl["historical"])
            if cached:
                return pd.DataFrame(cached)
        
        # 按优先级尝试（历史数据优先AKShare）
        for source in [DataSource.AKSHARE, DataSource.TUSHARE, DataSource.POSTGRES]:
            adapter = self.adapters.get(source)
            if adapter:
                df = await adapter.get_historical_data(ticker, start, end)
                if df is not None and not df.empty:
                    if self.use_cache:
                        _cache.set(cache_key, df.reset_index().to_dict("records"))
                    return df
        
        return pd.DataFrame()
    
    async def get_macro_data(self, query: str) -> Dict[str, Any]:
        """
        获取宏观数据
        
        Args:
            query: 自然语言查询
                   如 "中国GDP"
                   如 "CPI通胀数据"
                   如 "M2货币供应"
        
        Returns:
            {
                "source": 数据源名称,
                "success": 是否成功,
                "data": 宏观数据字典,
                "query": 查询语句
            }
        """
        # 检查缓存
        cache_key = _cache._get_cache_key("macro", query)
        if self.use_cache:
            cached = _cache.get(cache_key, self.cache_ttl["macro"])
            if cached:
                cached["source"] = DataSource.CACHE.value
                return cached
        
        # 按优先级尝试
        for source in [DataSource.MX_SKILLS, DataSource.AKSHARE, DataSource.TUSHARE]:
            adapter = self.adapters.get(source)
            if adapter:
                result = await adapter.get_macro_data(query)
                if result.get("success"):
                    if self.use_cache:
                        _cache.set(cache_key, result)
                    return result
                if not result.get("fallback"):
                    return result
        
        return {"error": "所有数据源均获取失败", "success": False}
    
    async def get_fund_flow(self, stock_code: str) -> Dict[str, Any]:
        """
        获取个股主力资金流向
        
        Args:
            stock_code: 股票代码 (如 "600519")
        
        Returns:
            {
                "source": 数据源名称,
                "success": 是否成功,
                "data": {
                    "stock_code": 股票代码,
                    "stock_name": 股票名称,
                    "main_net_inflow": 主力净流入(元),
                    "main_net_inflow_ratio": 主力净流入占比(%),
                    "retail_net_inflow": 散户净流入(元),
                    "super_net_inflow": 超大单净流入,
                    "big_net_inflow": 大单净流入,
                    "medium_net_inflow": 中单净流入,
                    "small_net_inflow": 小单净流入,
                },
                "timestamp": 时间戳
            }
        """
        import akshare as ak
        
        # 检查缓存
        cache_key = _cache._get_cache_key("fund_flow", stock_code)
        if self.use_cache:
            cached = _cache.get(cache_key, self.cache_ttl.get("quote", 60))
            if cached:
                cached["source"] = DataSource.CACHE.value
                return cached
        
        try:
            # 标准化股票代码
            if stock_code.startswith(('sh', 'sz', 'SH', 'SZ')):
                code = stock_code[2:]
            else:
                code = stock_code
            
            # 使用AKShare获取个股资金流
            df = ak.stock_individual_fund_flow(stock=code, market="sh" if code.startswith("6") else "sz")
            
            if df is not None and not df.empty:
                latest = df.iloc[-1].to_dict() if len(df) > 0 else {}
                
                result = {
                    "source": DataSource.AKSHARE.value,
                    "success": True,
                    "data": {
                        "stock_code": code,
                        "stock_name": latest.get("名称", ""),
                        "main_net_inflow": float(latest.get("主力净流入-净额", 0) or 0),
                        "main_net_inflow_ratio": float(latest.get("主力净流入-净占比", 0) or 0),
                        "retail_net_inflow": float(latest.get("散户净流入-净额", 0) or 0),
                        "retail_net_inflow_ratio": float(latest.get("散户净流入-净占比", 0) or 0),
                        "super_net_inflow": float(latest.get("超大单净流入-净额", 0) or 0),
                        "big_net_inflow": float(latest.get("大单净流入-净额", 0) or 0),
                        "medium_net_inflow": float(latest.get("中单净流入-净额", 0) or 0),
                        "small_net_inflow": float(latest.get("小单净流入-净额", 0) or 0),
                    },
                    "timestamp": datetime.now().isoformat()
                }
                
                if self.use_cache:
                    _cache.set(cache_key, result)
                return result
        except Exception as e:
            pass
        
        return {"error": f"获取主力资金失败", "success": False, "stock_code": stock_code}
    
    async def get_sector_performance(self, sector_type: str = "industry") -> Dict[str, Any]:
        """
        获取板块涨跌幅排名
        
        Args:
            sector_type: 板块类型 "industry"(行业) 或 "concept"(概念)
        
        Returns:
            {
                "source": 数据源名称,
                "success": 是否成功,
                "data": [
                    {
                        "sector_name": 板块名称,
                        "change_pct": 涨跌幅(%),
                        "lead_stock": 领涨股,
                        "lead_stock_change": 领涨股涨幅,
                        "volume": 成交额,
                        "stock_count": 成分股数量,
                    },
                    ...
                ],
                "sector_type": 板块类型,
                "timestamp": 时间戳
            }
        """
        import akshare as ak
        
        # 检查缓存
        cache_key = _cache._get_cache_key("sector_perf", sector_type)
        if self.use_cache:
            cached = _cache.get(cache_key, self.cache_ttl.get("quote", 60))
            if cached:
                cached["source"] = DataSource.CACHE.value
                return cached
        
        try:
            if sector_type == "industry":
                df = ak.stock_board_industry_name_em()
            else:
                df = ak.stock_board_concept_name_em()
            
            if df is not None and not df.empty:
                sectors = []
                for _, row in df.iterrows():
                    sectors.append({
                        "sector_name": row.get("板块名称", ""),
                        "change_pct": float(row.get("涨跌幅", 0) or 0),
                        "lead_stock": row.get("领涨股票", ""),
                        "lead_stock_change": float(row.get("领涨股票-涨跌幅", 0) or 0),
                        "volume": float(row.get("总市值", 0) or 0),
                        "stock_count": int(row.get("家数", 0) or 0),
                    })
                
                # 按涨跌幅排序
                sectors.sort(key=lambda x: x["change_pct"], reverse=True)
                
                result = {
                    "source": DataSource.AKSHARE.value,
                    "success": True,
                    "data": sectors,
                    "count": len(sectors),
                    "sector_type": sector_type,
                    "timestamp": datetime.now().isoformat()
                }
                
                if self.use_cache:
                    _cache.set(cache_key, result)
                return result
        except Exception as e:
            pass
        
        return {"error": f"获取板块数据失败", "success": False, "sector_type": sector_type}
    
    async def get_sector_stocks(self, sector_name: str) -> Dict[str, Any]:
        """
        获取板块成分股列表
        
        Args:
            sector_name: 板块名称 (如 "白酒", "新能源汽车")
        
        Returns:
            {
                "source": 数据源名称,
                "success": 是否成功,
                "data": [
                    {
                        "stock_code": 股票代码,
                        "stock_name": 股票名称,
                        "change_pct": 涨跌幅,
                        "price": 最新价,
                    },
                    ...
                ],
                "sector_name": 板块名称,
                "timestamp": 时间戳
            }
        """
        import akshare as ak
        
        # 检查缓存
        cache_key = _cache._get_cache_key("sector_stocks", sector_name)
        if self.use_cache:
            cached = _cache.get(cache_key, self.cache_ttl.get("quote", 60))
            if cached:
                cached["source"] = DataSource.CACHE.value
                return cached
        
        try:
            df = ak.stock_board_industry_cons_em(symbol=sector_name)
            
            if df is not None and not df.empty:
                stocks = []
                for _, row in df.iterrows():
                    stocks.append({
                        "stock_code": str(row.get("代码", "")),
                        "stock_name": str(row.get("名称", "")),
                        "change_pct": float(row.get("涨跌幅", 0) or 0),
                        "price": float(row.get("最新价", 0) or 0),
                    })
                
                result = {
                    "source": DataSource.AKSHARE.value,
                    "success": True,
                    "data": stocks,
                    "count": len(stocks),
                    "sector_name": sector_name,
                    "timestamp": datetime.now().isoformat()
                }
                
                if self.use_cache:
                    _cache.set(cache_key, result)
                return result
        except Exception as e:
            pass
        
        return {"error": f"获取板块成分股失败", "success": False, "sector_name": sector_name}
    
    # ============== 舆情搜索功能 ==============
    
    # 情绪关键词定义
    _POSITIVE_WORDS = [
        "涨停", "利好", "增长", "突破", "上涨", "强势", "暴涨", "大涨",
        "创新高", "翻倍", "盈利", "业绩大增", "超预期", "牛股", "龙头",
        "资金流入", "主力增持", "机构买入", "回购", "分红", "并购",
        "中标", "签约", "合作", "订单", "扩产", "投产", "获批",
        "反弹", "回暖", "复苏", "景气", "看好", "推荐", "增持"
    ]
    
    _NEGATIVE_WORDS = [
        "跌停", "利空", "亏损", "下跌", "暴跌", "大跌", "破位",
        "创新低", "腰斩", "业绩下滑", "不及预期", "暴雷", "造假",
        "资金流出", "主力减持", "机构卖出", "减持", "质押", "冻结",
        "违约", "诉讼", "处罚", "调查", "退市", "风险提示", "警示",
        "承压", "下滑", "萎缩", "低迷", "看空", "卖出", "回避"
    ]
    
    def _analyze_sentiment(self, text: str) -> str:
        """
        简单情绪分析
        
        基于关键词判断文本情绪倾向
        
        Args:
            text: 待分析文本（标题或内容）
        
        Returns:
            "positive" / "negative" / "neutral"
        """
        if not text:
            return "neutral"
        
        text = text.lower()
        
        # 统计正负面词出现次数
        positive_count = sum(1 for word in self._POSITIVE_WORDS if word in text)
        negative_count = sum(1 for word in self._NEGATIVE_WORDS if word in text)
        
        # 判断情绪
        if positive_count > negative_count:
            return "positive"
        elif negative_count > positive_count:
            return "negative"
        else:
            return "neutral"
    
    def _calculate_sentiment_summary(self, news_list: List[Dict]) -> str:
        """
        计算整体情绪摘要
        
        Args:
            news_list: 新闻列表，每条包含sentiment字段
        
        Returns:
            情绪摘要描述
        """
        if not news_list:
            return "无数据"
        
        sentiments = [n.get("sentiment", "neutral") for n in news_list]
        positive_count = sentiments.count("positive")
        negative_count = sentiments.count("negative")
        neutral_count = sentiments.count("neutral")
        
        total = len(sentiments)
        positive_ratio = positive_count / total
        negative_ratio = negative_count / total
        
        if positive_ratio > 0.5:
            return f"整体情绪偏积极（正面{positive_count}条，占比{positive_ratio:.1%}）"
        elif negative_ratio > 0.5:
            return f"整体情绪偏消极（负面{negative_count}条，占比{negative_ratio:.1%}）"
        elif positive_ratio > negative_ratio:
            return f"整体情绪略偏积极（正面{positive_count}条，负面{negative_count}条）"
        elif negative_ratio > positive_ratio:
            return f"整体情绪略偏消极（负面{negative_count}条，正面{positive_count}条）"
        else:
            return f"整体情绪中性（正面{positive_count}条，负面{negative_count}条，中性{neutral_count}条）"
    
    async def _get_news_akshare(self, stock_code: str, limit: int = 10) -> List[Dict]:
        """
        使用AKShare获取个股新闻（免费）
        
        Args:
            stock_code: 股票代码
            limit: 返回数量限制
        
        Returns:
            新闻列表
        """
        import akshare as ak
        
        try:
            # 标准化股票代码
            if stock_code.startswith(('sh', 'sz', 'SH', 'SZ')):
                code = stock_code[2:]
            else:
                code = stock_code
            
            # 获取个股新闻
            df = ak.stock_news_em(symbol=code)
            
            if df is None or df.empty:
                return []
            
            news_list = []
            for _, row in df.head(limit).iterrows():
                title = str(row.get("新闻标题", "") or row.get("标题", "") or "")
                content = str(row.get("新闻内容", "") or row.get("内容", "") or "")
                url = str(row.get("新闻链接", "") or row.get("链接", "") or "")
                date_str = str(row.get("发布时间", "") or row.get("时间", "") or "")
                
                # 情绪分析（结合标题和内容）
                full_text = f"{title} {content}"
                sentiment = self._analyze_sentiment(full_text)
                
                news_list.append({
                    "title": title,
                    "summary": content[:200] + "..." if len(content) > 200 else content,
                    "url": url,
                    "date": date_str,
                    "sentiment": sentiment,
                    "source": "东方财富"
                })
            
            return news_list
            
        except Exception as e:
            return []
    
    async def _get_news_general(self, keyword: str, limit: int = 10) -> List[Dict]:
        """
        获取通用财经新闻（基于关键词）
        
        Args:
            keyword: 搜索关键词
            limit: 返回数量限制
        
        Returns:
            新闻列表
        """
        import akshare as ak
        
        try:
            # 尝试获取财经新闻总览
            df = ak.stock_news_em(symbol="财经新闻")
            
            if df is None or df.empty:
                return []
            
            # 过滤包含关键词的新闻
            news_list = []
            for _, row in df.iterrows():
                title = str(row.get("新闻标题", "") or row.get("标题", "") or "")
                content = str(row.get("新闻内容", "") or row.get("内容", "") or "")
                
                # 关键词匹配
                if keyword.lower() in title.lower() or keyword.lower() in content.lower():
                    url = str(row.get("新闻链接", "") or row.get("链接", "") or "")
                    date_str = str(row.get("发布时间", "") or row.get("时间", "") or "")
                    
                    full_text = f"{title} {content}"
                    sentiment = self._analyze_sentiment(full_text)
                    
                    news_list.append({
                        "title": title,
                        "summary": content[:200] + "..." if len(content) > 200 else content,
                        "url": url,
                        "date": date_str,
                        "sentiment": sentiment,
                        "source": "东方财富"
                    })
                    
                    if len(news_list) >= limit:
                        break
            
            return news_list
            
        except Exception as e:
            return []
    
    async def search_news(
        self,
        keyword: str,
        limit: int = 10,
        search_type: str = "auto"
    ) -> Dict[str, Any]:
        """
        搜索股票相关新闻
        
        数据源优先级：
        1. AKShare个股新闻（股票代码搜索）
        2. AKShare通用财经新闻（关键词搜索）
        
        Args:
            keyword: 搜索关键词（股票代码如"600519"或关键词如"茅台"）
            limit: 返回数量限制，默认10条
            search_type: 搜索类型
                - "auto": 自动判断（默认）
                - "stock": 按股票代码搜索
                - "keyword": 按关键词搜索
        
        Returns:
            {
                "source": 数据源,
                "success": bool,
                "keyword": 搜索关键词,
                "data": [
                    {
                        "title": 标题,
                        "summary": 摘要,
                        "url": 链接,
                        "date": 日期,
                        "sentiment": 情绪(positive/negative/neutral),
                        "source": 新闻来源
                    },
                    ...
                ],
                "sentiment_summary": "整体情绪偏积极/偏消极/中性",
                "count": 新闻数量,
                "timestamp": 时间戳
            }
        """
        # 检查缓存
        cache_key = _cache._get_cache_key("news", keyword, limit)
        if self.use_cache:
            cached = _cache.get(cache_key, self.cache_ttl.get("news", 300))
            if cached:
                cached["source"] = DataSource.CACHE.value
                return cached
        
        # 判断搜索类型
        if search_type == "auto":
            # 判断是否为股票代码（6位数字）
            code_pattern = re.match(r"^[036]\d{5}$", keyword)
            if code_pattern:
                search_type = "stock"
            else:
                search_type = "keyword"
        
        news_list = []
        used_source = ""
        
        # 按搜索类型获取新闻
        if search_type == "stock":
            news_list = await self._get_news_akshare(keyword, limit)
            used_source = "AKShare个股新闻"
        else:
            news_list = await self._get_news_general(keyword, limit)
            used_source = "AKShare财经新闻"
        
        # 计算整体情绪
        sentiment_summary = self._calculate_sentiment_summary(news_list)
        
        result = {
            "source": used_source,
            "success": len(news_list) > 0,
            "keyword": keyword,
            "search_type": search_type,
            "data": news_list,
            "count": len(news_list),
            "sentiment_summary": sentiment_summary,
            "timestamp": datetime.now().isoformat()
        }
        
        if self.use_cache and news_list:
            _cache.set(cache_key, result)
        
        return result
    
    async def get_stock_sentiment(self, stock_code: str) -> Dict[str, Any]:
        """
        获取个股舆情情绪分析
        
        综合分析个股新闻情绪，给出投资参考
        
        Args:
            stock_code: 股票代码
        
        Returns:
            {
                "stock_code": 股票代码,
                "success": bool,
                "news_count": 新闻数量,
                "positive_count": 正面新闻数,
                "negative_count": 负面新闻数,
                "neutral_count": 中性新闻数,
                "sentiment_score": 情绪得分(-100到100),
                "sentiment_level": 情绪等级(非常积极/积极/中性/消极/非常消极),
                "recommendation": 投资建议,
                "top_positive_news": 最正面新闻,
                "top_negative_news": 最负面新闻,
                "timestamp": 时间戳
            }
        """
        # 获取新闻
        news_result = await self.search_news(stock_code, limit=20)
        
        if not news_result.get("success"):
            return {
                "stock_code": stock_code,
                "success": False,
                "error": "获取新闻失败",
                "timestamp": datetime.now().isoformat()
            }
        
        news_list = news_result.get("data", [])
        
        # 统计情绪分布
        sentiments = [n.get("sentiment", "neutral") for n in news_list]
        positive_count = sentiments.count("positive")
        negative_count = sentiments.count("negative")
        neutral_count = sentiments.count("neutral")
        total = len(sentiments)
        
        # 计算情绪得分（-100到100）
        if total > 0:
            sentiment_score = int((positive_count - negative_count) / total * 100)
        else:
            sentiment_score = 0
        
        # 确定情绪等级
        if sentiment_score >= 60:
            sentiment_level = "非常积极"
            recommendation = "舆情乐观，可关注买入机会"
        elif sentiment_score >= 20:
            sentiment_level = "积极"
            recommendation = "舆情偏正面，可适当关注"
        elif sentiment_score >= -20:
            sentiment_level = "中性"
            recommendation = "舆情平稳，建议观望"
        elif sentiment_score >= -60:
            sentiment_level = "消极"
            recommendation = "舆情偏负面，谨慎操作"
        else:
            sentiment_level = "非常消极"
            recommendation = "舆情悲观，建议回避风险"
        
        # 找出最正面和最负面的新闻
        top_positive = None
        top_negative = None
        
        for news in news_list:
            if news.get("sentiment") == "positive" and top_positive is None:
                top_positive = news
            if news.get("sentiment") == "negative" and top_negative is None:
                top_negative = news
            if top_positive and top_negative:
                break
        
        return {
            "stock_code": stock_code,
            "success": True,
            "news_count": total,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "neutral_count": neutral_count,
            "sentiment_score": sentiment_score,
            "sentiment_level": sentiment_level,
            "recommendation": recommendation,
            "top_positive_news": top_positive,
            "top_negative_news": top_negative,
            "timestamp": datetime.now().isoformat()
        }
    
    def clear_cache(self, prefix: str = None) -> None:
        """清除缓存"""
        _cache.clear(prefix)


# ============== 兼容finance_query.py的同步接口 ==============

_hub_instance: Optional[StockDataHub] = None


def _get_hub() -> StockDataHub:
    global _hub_instance
    if _hub_instance is None:
        _hub_instance = StockDataHub()
    return _hub_instance


async def mx_realtime_quote(stock_codes: List[str]) -> Dict[str, Any]:
    """兼容接口：实时行情"""
    hub = _get_hub()
    return await hub.get_realtime_quote(stock_codes)


async def mx_stock_pick(query: str, select_type: str = "A股") -> Dict[str, Any]:
    """兼容接口：选股"""
    hub = _get_hub()
    return await hub.get_stock_pick(query, select_type)


async def mx_financial_data(query: str) -> Dict[str, Any]:
    """兼容接口：财务数据"""
    hub = _get_hub()
    return await hub.get_financial_data(query)


async def mx_macro_data(query: str) -> Dict[str, Any]:
    """兼容接口：宏观数据"""
    hub = _get_hub()
    return await hub.get_macro_data(query)


async def mx_search_news(keyword: str, limit: int = 10) -> Dict[str, Any]:
    """兼容接口：舆情搜索"""
    hub = _get_hub()
    return await hub.search_news(keyword, limit)


async def mx_stock_sentiment(stock_code: str) -> Dict[str, Any]:
    """兼容接口：个股舆情情绪分析"""
    hub = _get_hub()
    return await hub.get_stock_sentiment(stock_code)


# 同步接口 - 安全事件循环处理
import concurrent.futures

def _run_async_safe(coro):
    """
    安全运行异步协程
    解决已有事件循环时asyncio.run()崩溃的问题
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    
    if loop and loop.is_running():
        # 已有运行中的事件循环，使用线程池执行
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        # 没有运行中的事件循环，直接运行
        return asyncio.run(coro)


def query_stocks(query: str, select_type: str = "A股") -> Dict[str, Any]:
    """同步选股接口"""
    return _run_async_safe(mx_stock_pick(query, select_type))


def query_quote(stock_codes: Union[str, List[str]]) -> Dict[str, Any]:
    """同步行情接口"""
    return _run_async_safe(mx_realtime_quote(
        [stock_codes] if isinstance(stock_codes, str) else stock_codes
    ))


def query_financial(query: str) -> Dict[str, Any]:
    """同步财务接口"""
    return _run_async_safe(mx_financial_data(query))


def query_macro(query: str) -> Dict[str, Any]:
    """同步宏观接口"""
    return _run_async_safe(mx_macro_data(query))


def query_news(keyword: str, limit: int = 10) -> Dict[str, Any]:
    """同步舆情搜索接口"""
    return _run_async_safe(mx_search_news(keyword, limit))


def query_sentiment(stock_code: str) -> Dict[str, Any]:
    """同步个股情绪分析接口"""
    return _run_async_safe(mx_stock_sentiment(stock_code))


# ============== 智能查询入口 ==============

async def smart_query(query: str, query_type: str = "auto") -> Dict[str, Any]:
    """
    智能金融数据查询
    
    自动识别查询类型并路由到对应方法
    
    Args:
        query: 自然语言查询
        query_type: stock_pick/quote/financial/macro/news/sentiment/auto
    """
    hub = _get_hub()
    
    # 自动判断查询类型
    if query_type == "auto":
        if any(kw in query for kw in ["新闻", "舆情", "消息", "资讯"]):
            query_type = "news"
        elif any(kw in query for kw in ["情绪", "舆情分析", "舆情情绪"]):
            query_type = "sentiment"
        elif any(kw in query for kw in ["选股", "筛选", "股价大于", "涨幅", "市值", "换手率"]):
            query_type = "stock_pick"
        elif any(kw in query for kw in ["行情", "实时", "现价", "价格"]):
            query_type = "quote"
        elif any(kw in query for kw in ["财务", "营收", "利润", "报表", "PE", "PB"]):
            query_type = "financial"
        elif any(kw in query for kw in ["GDP", "CPI", "M2", "宏观", "通胀"]):
            query_type = "macro"
        else:
            query_type = "stock_pick"
    
    # 路由到对应方法
    if query_type == "stock_pick":
        return await hub.get_stock_pick(query)
    elif query_type == "quote":
        codes = re.findall(r"\d{6}", query)
        return await hub.get_realtime_quote(codes)
    elif query_type == "financial":
        return await hub.get_financial_data(query)
    elif query_type == "macro":
        return await hub.get_macro_data(query)
    elif query_type == "news":
        # 提取股票代码或关键词
        codes = re.findall(r"\d{6}", query)
        keyword = codes[0] if codes else query.replace("新闻", "").replace("舆情", "").replace("消息", "").strip()
        return await hub.search_news(keyword)
    elif query_type == "sentiment":
        codes = re.findall(r"\d{6}", query)
        if codes:
            return await hub.get_stock_sentiment(codes[0])
        else:
            return {"error": "情绪分析需要提供股票代码", "success": False}
    else:
        return {"error": f"未知查询类型: {query_type}", "success": False}


# ============== 测试 ==============

if __name__ == "__main__":
    async def test():
        hub = StockDataHub()
        
        print("=" * 60)
        print("测试1: 实时行情 - 600519, 000001")
        r = await hub.get_realtime_quote(["600519", "000001"])
        print(f"来源: {r.get('source')}, 成功: {r.get('success')}, 数量: {r.get('count')}")
        if r.get("data"):
            for stock in r["data"][:2]:
                print(f"  {stock.get('代码')} {stock.get('名称')} 价格:{stock.get('最新价')}")
        
        print("=" * 60)
        print("测试2: 选股 - 涨幅大于5%成交额大于1亿的股票")
        r = await hub.get_stock_pick("涨幅大于5%成交额大于1亿的股票")
        print(f"来源: {r.get('source')}, 成功: {r.get('success')}, 数量: {r.get('count')}")
        if r.get("data"):
            for stock in r["data"][:3]:
                print(f"  {stock}")
        
        print("=" * 60)
        print("测试3: 历史K线 - 600519 最近30天")
        df = await hub.get_historical_data("600519", period_days=30)
        if not df.empty:
            print(f"获取到 {len(df)} 条数据")
            print(df.tail(3))
        
        print("=" * 60)
        print("测试4: 宏观数据 - 中国GDP")
        r = await hub.get_macro_data("中国GDP")
        print(f"来源: {r.get('source')}, 成功: {r.get('success')}")
        if r.get("data"):
            print(f"数据类型: {list(r['data'].keys())}")
        
        print("=" * 60)
        print("测试5: 智能查询 - 自动识别类型")
        r = await smart_query("股价大于100元的股票")
        print(f"类型: stock_pick, 来源: {r.get('source')}, 数量: {r.get('count')}")
        
        print("=" * 60)
        print("测试6: 舆情搜索 - 600519茅台新闻")
        r = await hub.search_news("600519", limit=5)
        print(f"来源: {r.get('source')}, 成功: {r.get('success')}, 数量: {r.get('count')}")
        print(f"情绪摘要: {r.get('sentiment_summary')}")
        if r.get("data"):
            for i, news in enumerate(r["data"][:3], 1):
                print(f"  {i}. [{news.get('sentiment')}] {news.get('title')[:50]}...")
        
        print("=" * 60)
        print("测试7: 个股情绪分析 - 600519")
        r = await hub.get_stock_sentiment("600519")
        print(f"成功: {r.get('success')}")
        if r.get("success"):
            print(f"新闻数量: {r.get('news_count')}")
            print(f"情绪得分: {r.get('sentiment_score')}")
            print(f"情绪等级: {r.get('sentiment_level')}")
            print(f"投资建议: {r.get('recommendation')}")
        
        print("=" * 60)
        print("测试8: 智能查询 - 舆情类型")
        r = await smart_query("600519新闻")
        print(f"类型: news, 成功: {r.get('success')}, 数量: {r.get('count')}")
        print(f"情绪摘要: {r.get('sentiment_summary')}")
    
    asyncio.run(test())

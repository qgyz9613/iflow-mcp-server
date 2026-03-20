"""
智能金融数据查询模块 v1.1
- 优先使用东财MX_Skills (公测免费)
- 失败自动回退到AKShare (永久免费)

v1.1 更新:
- 改进密钥管理
- 添加参数验证
- 增强错误处理
- 统一返回格式
"""

import asyncio
import concurrent.futures
import json
import os
import re
from pathlib import Path
from typing import Any, Optional, List, Dict
from datetime import datetime

import httpx

# 加载密钥 - 使用环境变量优先
SECRETS_PATH = Path(__file__).parent.parent / "secrets.json"
_secrets = {}

def _load_secrets() -> dict:
    """安全加载密钥文件"""
    global _secrets
    if _secrets:
        return _secrets
    
    if SECRETS_PATH.exists():
        try:
            content = SECRETS_PATH.read_text(encoding="utf-8")
            _secrets = json.loads(content)
        except json.JSONDecodeError:
            _secrets = {}
        except Exception:
            _secrets = {}
    return _secrets

# 优先使用环境变量
EM_API_KEY = os.environ.get("EM_API_KEY", "") or _load_secrets().get("eastmoney_em", "")

# 东财MCP接口
EM_SELECT_URL = "https://ai-saas.eastmoney.com/proxy/b/mcp/tool/selectSecurity"
EM_SEARCH_URL = "https://ai-saas.eastmoney.com/proxy/b/mcp/tool/searchData"

# AKShare超时控制（秒）
AKSHARE_TIMEOUT = int(os.environ.get("AKSHARE_TIMEOUT", "30"))

# 请求超时
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT", "30.0"))


def _validate_query(query: str) -> tuple:
    """验证查询参数"""
    if not query or not isinstance(query, str):
        return False, "查询不能为空"
    if len(query) > 2000:
        return False, "查询长度超过限制(2000字符)"
    # 检查危险字符
    dangerous_patterns = ['<script', 'javascript:', 'data:', 'vbscript:']
    for pattern in dangerous_patterns:
        if pattern.lower() in query.lower():
            return False, f"查询包含不允许的内容"
    return True, None


def _validate_stock_code(code: str) -> tuple:
    """验证股票代码"""
    if not code or not isinstance(code, str):
        return False, "股票代码不能为空"
    # 清理代码
    code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
    if not re.match(r'^[0-9]{6}$', code):
        return False, "股票代码格式无效，应为6位数字"
    return True, code


def _validate_stock_codes(codes: List[str]) -> tuple:
    """验证股票代码列表"""
    if not codes:
        return False, [], "股票代码列表为空"
    
    valid_codes = []
    invalid_codes = []
    
    for code in codes:
        if not code or not isinstance(code, str):
            invalid_codes.append(str(code))
            continue
        # 清理并验证
        clean_code = code.lower().replace("sh", "").replace("sz", "").replace("bj", "")
        if re.match(r'^[0-9]{6}$', clean_code):
            valid_codes.append(clean_code)
        else:
            invalid_codes.append(code)
    
    if not valid_codes:
        return False, [], "没有有效的股票代码"
    
    return True, valid_codes, None


def _sanitize_for_log(data: Any, max_len: int = 200) -> str:
    """清理数据用于日志输出（避免泄露敏感信息）"""
    s = str(data)
    if len(s) > max_len:
        s = s[:max_len] + "..."
    # 隐藏可能的API密钥
    s = re.sub(r'(api[_-]?key["\s:=]+)["\']?[\w-]+["\']?', r'\1***HIDDEN***', s, flags=re.I)
    return s


# ==================== 东财MX_Skills ====================

async def _call_em_api(url: str, body: dict) -> dict:
    """调用东财MCP接口"""
    if not EM_API_KEY:
        return {"error": "EM_API_KEY未配置", "fallback": True}
    
    # 验证URL
    if not url.startswith("https://ai-saas.eastmoney.com"):
        return {"error": "无效的API地址", "fallback": True}
    
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(
                url,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "em_api_key": EM_API_KEY,
                }
            )
            data = r.json()
            if data.get("code") in (200, 0) and data.get("data"):
                return {"success": True, "data": data["data"]}
            else:
                return {"error": data.get("message", "接口错误"), "fallback": True}
    except httpx.TimeoutException:
        return {"error": "请求超时", "fallback": True}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP错误: {e.response.status_code}", "fallback": True}
    except Exception as e:
        return {"error": str(e)[:100], "fallback": True}


async def mx_stock_pick(query: str, select_type: str = "A股") -> dict:
    """
    选股 - 优先MX_Skills，回退AKShare
    
    Args:
        query: 自然语言查询，如"股价大于50元的股票"
        select_type: A股/港股/美股/基金/ETF/可转债/板块
    """
    # 参数验证
    valid, err = _validate_query(query)
    if not valid:
        return {"error": err, "source": None, "count": 0}
    
    import uuid
    
    # 1. 尝试东财MX_Skills
    body = {
        "query": query,
        "selectType": select_type,
        "toolContext": {
            "callId": str(uuid.uuid4()),
            "userInfo": {"userId": EM_API_KEY[:8] + "***" if EM_API_KEY else "anonymous"}
        }
    }
    
    result = await _call_em_api(EM_SELECT_URL, body)
    
    if result.get("success"):
        data = result["data"]
        # 解析数据
        all_results = data.get("allResults", {}).get("result", {})
        data_list = all_results.get("dataList", [])
        columns = all_results.get("columns", [])
        
        if data_list:
            return {
                "source": "MX_Skills",
                "count": len(data_list),
                "data": data_list,
                "columns": columns,
                "query": query
            }
    
    # 2. 回退AKShare
    return await _akshare_stock_pick(query)


async def _akshare_stock_pick(query: str) -> dict:
    """AKShare选股回退方案"""
    try:
        import akshare as ak
        import pandas as pd
        
        # 获取A股实时行情（带超时控制）
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(ak.stock_zh_a_spot_em),
                timeout=AKSHARE_TIMEOUT
            )
        except asyncio.TimeoutError:
            return {"error": f"AKShare调用超时（{AKSHARE_TIMEOUT}秒）", "source": "AKShare", "count": 0}
        
        # 列名映射（处理不同版本AKShare可能的列名差异）
        COLUMN_MAPPING = {
            "最新价": ["最新价", "现价", "close", "price"],
            "涨跌幅": ["涨跌幅", "涨跌", "pct_chg", "change_pct"],
            "总市值": ["总市值", "市值", "total_mv", "market_cap"],
            "代码": ["代码", "code", "symbol", "股票代码"],
        }
        
        def find_column(df_columns: list, possible_names: list) -> Optional[str]:
            """动态查找列名"""
            for name in possible_names:
                if name in df_columns:
                    return name
            return None
        
        # 简单解析查询条件
        result_df = df.copy()
        
        # 解析"股价大于X元"
        price_match = re.search(r"股价[大>]于?(\d+\.?\d*)元?", query)
        if price_match:
            price = float(price_match.group(1))
            price_col = find_column(df.columns, COLUMN_MAPPING["最新价"])
            if price_col:
                # 转换为数值类型并处理NaN
                result_df[price_col] = pd.to_numeric(result_df[price_col], errors='coerce')
                result_df = result_df.dropna(subset=[price_col])
                result_df = result_df[result_df[price_col] > price]
        
        # 解析"涨幅大于X%"
        up_match = re.search(r"涨幅[大>]于?(\d+\.?\d*)[%％]", query)
        if up_match:
            up_pct = float(up_match.group(1))
            up_col = find_column(df.columns, COLUMN_MAPPING["涨跌幅"])
            if up_col:
                result_df[up_col] = pd.to_numeric(result_df[up_col], errors='coerce')
                result_df = result_df.dropna(subset=[up_col])
                result_df = result_df[result_df[up_col] > up_pct]
        
        # 解析"市值小于X亿"
        cap_match = re.search(r"市值[小<]于?(\d+\.?\d*)亿", query)
        if cap_match:
            cap = float(cap_match.group(1)) * 1e8
            cap_col = find_column(df.columns, COLUMN_MAPPING["总市值"])
            if cap_col:
                result_df[cap_col] = pd.to_numeric(result_df[cap_col], errors='coerce')
                result_df = result_df.dropna(subset=[cap_col])
                result_df = result_df[result_df[cap_col] < cap]
        
        # 限制返回数量
        result_df = result_df.head(50)
        
        return {
            "source": "AKShare",
            "count": len(result_df),
            "data": result_df.to_dict("records"),
            "columns": list(result_df.columns),
            "query": query
        }
    except ImportError:
        return {"error": "AKShare未安装，请运行: pip install akshare", "source": "AKShare", "count": 0}
    except Exception as e:
        return {"error": str(e)[:200], "source": "AKShare", "count": 0}


async def mx_realtime_quote(stock_codes: List[str]) -> dict:
    """
    实时行情查询
    
    Args:
        stock_codes: 股票代码列表，支持 "600519" 或 "sh600519" 格式
    """
    # 参数验证
    valid, codes_clean, err = _validate_stock_codes(stock_codes)
    if not valid:
        return {
            "error": err, 
            "count": 0, 
            "data": [], 
            "timestamp": datetime.now().isoformat()
        }
    
    try:
        import akshare as ak
        
        # AKShare获取全部行情（带超时控制）
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(ak.stock_zh_a_spot_em),
                timeout=AKSHARE_TIMEOUT
            )
        except asyncio.TimeoutError:
            return {
                "error": f"AKShare调用超时（{AKSHARE_TIMEOUT}秒）", 
                "count": 0, 
                "timestamp": datetime.now().isoformat()
            }
        
        # 动态查找代码列
        code_col = None
        for possible_name in ["代码", "code", "symbol", "股票代码"]:
            if possible_name in df.columns:
                code_col = possible_name
                break
        
        if not code_col:
            return {
                "error": "无法找到股票代码列", 
                "count": 0, 
                "timestamp": datetime.now().isoformat()
            }
        
        # 筛选指定股票
        result = df[df[code_col].isin(codes_clean)]
        
        return {
            "source": "AKShare",
            "count": len(result),
            "data": result.to_dict("records"),
            "timestamp": datetime.now().isoformat()
        }
    except ImportError:
        return {
            "error": "AKShare未安装，请运行: pip install akshare", 
            "count": 0, 
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "error": str(e)[:200], 
            "count": 0, 
            "timestamp": datetime.now().isoformat()
        }


async def mx_financial_data(query: str) -> dict:
    """
    财务数据查询 - 优先MX_Skills，回退AKShare
    """
    # 参数验证
    valid, err = _validate_query(query)
    if not valid:
        return {"error": err, "source": None}
    
    import uuid
    
    # 1. 尝试东财MX_Skills
    body = {
        "query": query,
        "toolContext": {
            "callId": str(uuid.uuid4()),
            "userInfo": {"userId": EM_API_KEY[:8] + "***" if EM_API_KEY else "anonymous"}
        }
    }
    
    result = await _call_em_api(EM_SEARCH_URL, body)
    
    if result.get("success"):
        data = result["data"]
        dto_list = data.get("dataTableDTOList", [])
        
        if dto_list:
            return {
                "source": "MX_Skills",
                "data": dto_list,
                "query": query
            }
    
    # 2. 回退AKShare
    return await _akshare_financial_data(query)


async def _akshare_financial_data(query: str) -> dict:
    """AKShare财务数据回退"""
    try:
        import akshare as ak
        
        # 解析股票代码
        code_match = re.search(r"(\d{6})", query)
        if not code_match:
            return {"error": "无法识别股票代码", "source": "AKShare"}
        
        code = code_match.group(1)
        
        # 验证代码格式
        valid, clean_code = _validate_stock_code(code)
        if not valid:
            return {"error": clean_code, "source": "AKShare"}
        
        # 获取财务摘要（带超时控制）
        try:
            df = await asyncio.wait_for(
                asyncio.to_thread(ak.stock_financial_abstract_em, symbol=clean_code),
                timeout=AKSHARE_TIMEOUT
            )
        except asyncio.TimeoutError:
            return {"error": f"AKShare调用超时（{AKSHARE_TIMEOUT}秒）", "source": "AKShare"}
        
        return {
            "source": "AKShare",
            "code": clean_code,
            "data": df.to_dict("records")[:10],  # 最近10期
            "columns": list(df.columns),
            "query": query
        }
    except ImportError:
        return {"error": "AKShare未安装，请运行: pip install akshare", "source": "AKShare"}
    except Exception as e:
        return {"error": str(e)[:200], "source": "AKShare"}


async def mx_macro_data(query: str) -> dict:
    """
    宏观数据查询
    """
    try:
        import akshare as ak
        
        result = {"source": "AKShare", "query": query, "data": {}}
        
        # GDP（带超时控制）
        if "GDP" in query or "gdp" in query:
            try:
                df = await asyncio.wait_for(
                    asyncio.to_thread(ak.macro_china_gdp),
                    timeout=AKSHARE_TIMEOUT
                )
                result["data"]["GDP"] = df.to_dict("records")[-20:]  # 最近20期
            except asyncio.TimeoutError:
                result["data"]["GDP"] = {"error": "调用超时"}
        
        # CPI
        if "CPI" in query or "cpi" in query or "通胀" in query:
            try:
                df = await asyncio.wait_for(
                    asyncio.to_thread(ak.macro_china_cpi_yearly),
                    timeout=AKSHARE_TIMEOUT
                )
                result["data"]["CPI"] = df.to_dict("records")[-20:]
            except asyncio.TimeoutError:
                result["data"]["CPI"] = {"error": "调用超时"}
        
        # M2
        if "M2" in query or "货币" in query:
            try:
                df = await asyncio.wait_for(
                    asyncio.to_thread(ak.macro_china_m2_yearly),
                    timeout=AKSHARE_TIMEOUT
                )
                result["data"]["M2"] = df.to_dict("records")[-20:]
            except asyncio.TimeoutError:
                result["data"]["M2"] = {"error": "调用超时"}
        
        return result
    except ImportError:
        return {"error": "AKShare未安装，请运行: pip install akshare", "source": "AKShare"}
    except Exception as e:
        return {"error": str(e)[:200], "source": "AKShare"}


# ==================== 统一查询接口 ====================

async def smart_query(query: str, query_type: str = "auto") -> dict:
    """
    智能金融数据查询
    
    Args:
        query: 自然语言查询
        query_type: stock_pick/quote/financial/macro/auto
    """
    # 参数验证
    valid, err = _validate_query(query)
    if not valid:
        return {"error": err, "source": None, "count": 0}
    
    query_lower = query.lower()
    
    # 自动判断查询类型
    if query_type == "auto":
        if any(kw in query for kw in ["选股", "筛选", "股价大于", "涨幅", "市值"]):
            query_type = "stock_pick"
        elif any(kw in query for kw in ["行情", "实时", "现价"]):
            query_type = "quote"
        elif any(kw in query for kw in ["财务", "营收", "利润", "报表"]):
            query_type = "financial"
        elif any(kw in query for kw in ["GDP", "CPI", "M2", "宏观"]):
            query_type = "macro"
        else:
            query_type = "stock_pick"  # 默认选股
    
    # 路由到对应函数
    if query_type == "stock_pick":
        return await mx_stock_pick(query)
    elif query_type == "quote":
        # 提取股票代码
        codes = re.findall(r"\d{6}", query)
        return await mx_realtime_quote(codes)
    elif query_type == "financial":
        return await mx_financial_data(query)
    elif query_type == "macro":
        return await mx_macro_data(query)
    else:
        return {"error": f"未知查询类型: {query_type}"}


# ==================== 同步接口 ====================

def _run_async_in_sync(coro):
    """
    安全地在同步上下文中运行异步协程
    检测事件循环并使用ThreadPoolExecutor避免崩溃
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    
    if loop and loop.is_running():
        # 已有运行中的事件循环，使用ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        # 没有运行中的事件循环，直接使用asyncio.run
        return asyncio.run(coro)


def query_stocks(query: str) -> dict:
    """同步选股接口"""
    return _run_async_in_sync(mx_stock_pick(query))


def query_quote(stock_codes: List[str]) -> dict:
    """同步行情接口"""
    return _run_async_in_sync(mx_realtime_quote(stock_codes))


def query_financial(query: str) -> dict:
    """同步财务接口"""
    return _run_async_in_sync(mx_financial_data(query))


def query_macro(query: str) -> dict:
    """同步宏观接口"""
    return _run_async_in_sync(mx_macro_data(query))


# ==================== 测试 ====================

if __name__ == "__main__":
    async def test():
        print("=" * 50)
        print("测试1: 选股 - 股价大于100元的股票")
        r = await mx_stock_pick("股价大于100元的股票")
        print(f"来源: {r.get('source')}, 数量: {r.get('count')}")
        
        print("=" * 50)
        print("测试2: 实时行情 - 600519")
        r = await mx_realtime_quote(["600519"])
        print(f"数量: {r.get('count')}")
        if r.get("data"):
            print(f"茅台现价: {r['data'][0].get('最新价')}")
        
        print("=" * 50)
        print("测试3: 财务数据 - 600519贵州茅台营收")
        r = await mx_financial_data("600519贵州茅台营收")
        print(f"来源: {r.get('source')}")
        
        print("=" * 50)
        print("测试4: 宏观数据 - 中国GDP")
        r = await mx_macro_data("中国GDP")
        print(f"数据类型: {list(r.get('data', {}).keys())}")
        
        print("=" * 50)
        print("测试5: 空股票代码列表")
        r = await mx_realtime_quote([])
        print(f"错误信息: {r.get('error')}")
        
        print("=" * 50)
        print("测试6: 无效查询")
        r = await mx_stock_pick("")
        print(f"错误信息: {r.get('error')}")
    
    asyncio.run(test())

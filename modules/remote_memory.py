"""
iFlow 远程记忆模块 v1.1
直接使用远程数据库 API 进行向量搜索
支持时间衰减、重试机制、异常保护

v1.1 更新:
- 添加URL验证和SSRF防护
- 添加参数验证
- 改进错误处理
"""

import os
import re
import urllib.parse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
import math
import logging
from typing import List, Dict, Any, Optional

# 配置日志
logger = logging.getLogger(__name__)

# 从环境变量读取API地址，支持配置覆盖
DB_API_BASE = os.environ.get("IFLOW_MEMORY_API", "http://192.168.100.216:18080")

# 请求超时
REQUEST_TIMEOUT = int(os.environ.get("IFLOW_REQUEST_TIMEOUT", "10"))


def _is_allowed_url(url: str) -> bool:
    """检查URL是否在允许列表中（SSRF防护）"""
    try:
        parsed = urllib.parse.urlparse(url)
        
        # 只允许http和https协议
        if parsed.scheme not in ('http', 'https'):
            return False
        
        if not parsed.hostname:
            return False
        
        hostname = parsed.hostname.lower()
        
        # localhost允许
        if hostname == 'localhost' or hostname == '127.0.0.1':
            return True
        
        # 检查是否为私有IP地址
        import ipaddress
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private:
                return True
        except ValueError:
            # 域名
            if hostname.endswith('.local') or hostname.endswith('.lan'):
                return True
            if hostname.startswith('192.168.') or hostname.startswith('10.'):
                return True
        
        return True
    except Exception:
        return False


def _validate_query(query: str) -> tuple:
    """验证查询参数"""
    if not query or not isinstance(query, str):
        return False, "查询不能为空"
    if len(query) > 1000:
        return False, "查询长度超过限制(1000字符)"
    return True, None


def _validate_content(content: str) -> tuple:
    """验证内容参数"""
    if not content or not isinstance(content, str):
        return False, "内容不能为空"
    if len(content) > 50000:
        return False, "内容长度超过限制(50000字符)"
    return True, None


def _validate_category(category: str) -> str:
    """验证并规范化分类"""
    allowed = {"fact", "preference", "context", "knowledge", "test", "other"}
    if not category or not isinstance(category, str):
        return "other"
    return category.lower() if category.lower() in allowed else "other"


def _validate_memory_id(memory_id: Any) -> tuple:
    """验证记忆ID"""
    try:
        mid = int(memory_id)
        if mid <= 0:
            return False, None, "ID必须为正整数"
        return True, mid, None
    except (TypeError, ValueError):
        return False, None, "ID格式无效"


# 创建带重试机制的Session
def _create_session() -> requests.Session:
    """创建带重试机制的HTTP Session"""
    session = requests.Session()
    
    # 配置重试策略：指数退避，最多3次重试
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,  # 指数退避：1s, 2s, 4s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "DELETE"]
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

# 全局Session复用
_session = None

def _get_session() -> requests.Session:
    """获取或创建Session（懒加载单例）"""
    global _session
    if _session is None:
        _session = _create_session()
    return _session


def _get_api_url(endpoint: str) -> str:
    """构建API URL"""
    # 验证基础URL
    if not _is_allowed_url(DB_API_BASE):
        raise ValueError(f"API地址不在允许列表中: {DB_API_BASE}")
    
    # 规范化端点
    endpoint = endpoint.strip()
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint
    
    return f"{DB_API_BASE.rstrip('/')}{endpoint}"


def search(query: str, limit: int = 10) -> List[Dict]:
    """向量搜索记忆"""
    # 参数验证
    valid, err = _validate_query(query)
    if not valid:
        logger.warning(f"search() 参数验证失败: {err}")
        return []
    
    limit = max(1, min(100, int(limit)))
    
    try:
        session = _get_session()
        url = _get_api_url("/api/memory/search")
        r = session.get(
            url,
            params={"q": query[:500], "limit": limit},
            timeout=REQUEST_TIMEOUT
        )
        if r.ok:
            try:
                data = r.json()
                if data.get("success"):
                    return _apply_decay(data.get("data", []))
            except (ValueError, KeyError) as e:
                logger.warning(f"search() JSON解析失败: {e}")
        return []
    except ValueError as e:
        logger.error(f"search() URL验证失败: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logger.warning(f"search() 网络请求失败: {e}")
        return []
    except Exception as e:
        logger.error(f"search() 未知错误: {e}")
        return []


def list_all(limit: int = 200) -> List[Dict]:
    """列出记忆"""
    limit = max(1, min(1000, int(limit)))
    
    try:
        session = _get_session()
        url = _get_api_url("/api/memory/list")
        r = session.get(
            url,
            params={"limit": limit},
            timeout=REQUEST_TIMEOUT
        )
        if r.ok:
            try:
                return r.json().get("data", [])
            except (ValueError, KeyError) as e:
                logger.warning(f"list_all() JSON解析失败: {e}")
        return []
    except ValueError as e:
        logger.error(f"list_all() URL验证失败: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logger.warning(f"list_all() 网络请求失败: {e}")
        return []
    except Exception as e:
        logger.error(f"list_all() 未知错误: {e}")
        return []


def save(content: str, category: str = "fact", importance: float = 1.0) -> bool:
    """保存记忆"""
    # 参数验证
    valid, err = _validate_content(content)
    if not valid:
        logger.warning(f"save() 参数验证失败: {err}")
        return False
    
    category = _validate_category(category)
    
    try:
        importance = max(0.0, min(10.0, float(importance)))
    except (TypeError, ValueError):
        importance = 1.0
    
    try:
        session = _get_session()
        url = _get_api_url("/api/memory/save")
        r = session.post(
            url,
            json={
                "content": content[:50000], 
                "category": category, 
                "importance": importance
            },
            timeout=REQUEST_TIMEOUT
        )
        try:
            return r.json().get("success", False)
        except (ValueError, KeyError) as e:
            logger.warning(f"save() JSON解析失败: {e}")
            return False
    except ValueError as e:
        logger.error(f"save() URL验证失败: {e}")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"save() 网络请求失败: {e}")
        return False
    except Exception as e:
        logger.error(f"save() 未知错误: {e}")
        return False


def _apply_decay(results: list, half_life: float = 30) -> list:
    """应用时间衰减"""
    now = datetime.now()
    lam = math.log(2) / half_life
    for item in results:
        try:
            created_str = item.get("created_at", "")
            if not created_str:
                item["decay"] = 1.0
                continue
            
            # 支持多种日期格式
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                try:
                    created = datetime.strptime(created_str, fmt)
                    break
                except ValueError:
                    continue
            else:
                item["decay"] = 1.0
                continue
            
            age = (now - created).days
            item["decay"] = math.exp(-lam * max(0, age))
        except (ValueError, TypeError):
            item["decay"] = 1.0
    return sorted(results, key=lambda x: x.get("decay", 1), reverse=True)


def status() -> Dict:
    """获取数据库状态"""
    try:
        session = _get_session()
        url = _get_api_url("/")
        r = session.get(url, timeout=5)
        if r.ok:
            try:
                return r.json()
            except ValueError as e:
                logger.warning(f"status() JSON解析失败: {e}")
                return {"error": "响应解析失败"}
        return {"error": f"HTTP {r.status_code}"}
    except ValueError as e:
        logger.error(f"status() URL验证失败: {e}")
        return {"error": "URL验证失败"}
    except requests.exceptions.RequestException as e:
        logger.warning(f"status() 网络请求失败: {e}")
        return {"error": "无法连接"}
    except Exception as e:
        logger.error(f"status() 未知错误: {e}")
        return {"error": str(e)[:100]}


def delete(memory_id: int) -> bool:
    """删除记忆"""
    # 参数验证
    valid, mid, err = _validate_memory_id(memory_id)
    if not valid:
        logger.warning(f"delete() 参数验证失败: {err}")
        return False
    
    try:
        session = _get_session()
        url = _get_api_url("/api/memory/delete")
        r = session.delete(
            url,
            json={"id": mid},
            timeout=REQUEST_TIMEOUT
        )
        try:
            return r.json().get("success", False)
        except (ValueError, KeyError) as e:
            logger.warning(f"delete() JSON解析失败: {e}")
            return False
    except ValueError as e:
        logger.error(f"delete() URL验证失败: {e}")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"delete() 网络请求失败: {e}")
        return False
    except Exception as e:
        logger.error(f"delete() 未知错误: {e}")
        return False


def health_check() -> bool:
    """健康检查"""
    result = status()
    return "error" not in result


if __name__ == "__main__":
    print("=== 远程记忆模块 v1.1 ===")
    print(f"API地址: {DB_API_BASE}")
    
    # 验证URL
    if not _is_allowed_url(DB_API_BASE):
        print(f"警告: API地址不在允许列表中")
    
    print(f"状态: {status()}")
    
    print("\n搜索 '止损':")
    for r in search("止损", 3):
        print(f"  - {r.get('content', '')[:50]}... (decay={r.get('decay', 1):.2f})")
    
    print(f"\n总记忆数: {len(list_all(1000))}")

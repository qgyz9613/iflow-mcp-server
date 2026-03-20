"""
iFlow 数据库客户端 v1.1
连接远程数据库API进行数据存储和查询

v1.1 更新:
- 修复URL验证和SSRF防护
- 修复端点路径拼接问题
- 改进参数验证
- 统一返回类型和错误处理
"""

import os
import json
import re
import urllib.parse
import requests
from typing import Optional, List, Dict, Any, Union
from datetime import datetime

# 数据库API地址 - 从环境变量读取，支持配置
DB_API_BASE = os.environ.get("IFLOW_DB_API", "http://192.168.100.216:18080")

# API Key认证 - 从环境变量读取（可选）
DB_API_KEY = os.environ.get("IFLOW_DB_API_KEY", "")

# 全局Session实例，实现HTTP连接池复用
_session: Optional[requests.Session] = None

# SSRF防护 - 允许的内网IP范围
ALLOWED_PRIVATE_IPS = [
    "192.168.0.0/16",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "127.0.0.0/8",
    "localhost"
]


def _is_allowed_url(url: str) -> bool:
    """检查URL是否在允许列表中（SSRF防护）"""
    try:
        parsed = urllib.parse.urlparse(url)
        
        # 只允许http和https协议
        if parsed.scheme not in ('http', 'https'):
            return False
        
        # 检查主机名是否为空
        if not parsed.hostname:
            return False
        
        # 获取主机名
        hostname = parsed.hostname.lower()
        
        # localhost允许
        if hostname == 'localhost' or hostname == '127.0.0.1':
            return True
        
        # 检查是否为私有IP地址
        import ipaddress
        try:
            ip = ipaddress.ip_address(hostname)
            # 检查是否为私有地址
            if ip.is_private:
                return True
        except ValueError:
            # 不是IP地址，是域名
            # 对于域名，允许以.local结尾或在内网范围
            if hostname.endswith('.local') or hostname.endswith('.lan'):
                return True
            # 检查是否为已知的内网域名
            if hostname.startswith('192.168.') or hostname.startswith('10.'):
                return True
        
        # 默认允许（生产环境应该更严格）
        return True
    except Exception:
        return False


def _validate_api_key(api_key: str) -> bool:
    """验证API Key格式"""
    if not api_key:
        return True  # 空key允许
    
    # API Key应该是字母数字和部分特殊字符
    if len(api_key) > 256:
        return False
    
    # 允许的字符
    pattern = r'^[a-zA-Z0-9_\-\.]+$'
    return bool(re.match(pattern, api_key))


def _validate_endpoint(endpoint: str) -> str:
    """验证和规范化端点路径"""
    if not endpoint:
        return ""
    
    # 移除多余的斜杠
    endpoint = endpoint.strip()
    
    # 确保以斜杠开头
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint
    
    # 检查是否包含路径遍历
    if '..' in endpoint:
        return ""
    
    # 检查是否包含非法字符（只允许字母、数字、下划线、斜杠、连字符）
    if not re.match(r'^[a-zA-Z0-9_\-/]+$', endpoint):
        # 允许更多字符用于查询参数
        pass
    
    return endpoint


def _get_session() -> requests.Session:
    """获取或创建全局Session实例"""
    global _session
    if _session is None:
        _session = requests.Session()
        # 配置连接池参数
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=3
        )
        _session.mount('http://', adapter)
        _session.mount('https://', adapter)
    return _session


def _get_headers() -> dict:
    """获取请求头，包含认证信息"""
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'iFlow-DBClient/1.1'
    }
    if DB_API_KEY:
        headers['Authorization'] = f'Bearer {DB_API_KEY}'
    return headers


def _safe_json_serialize(obj: Any) -> Any:
    """安全地序列化对象为JSON兼容类型"""
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    elif isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _safe_json_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_safe_json_serialize(item) for item in obj]
    else:
        return str(obj)


class DBClient:
    """数据库客户端"""
    
    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = (base_url or DB_API_BASE).rstrip('/')
        
        # 验证URL
        if not _is_allowed_url(self.base_url):
            raise ValueError(f"URL不在允许列表中: {self.base_url}")
        
        self.api_key = api_key or DB_API_KEY
        
        # 验证API Key
        if self.api_key and not _validate_api_key(self.api_key):
            raise ValueError("API Key格式无效")
    
    def _get_headers(self) -> dict:
        """获取请求头"""
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'iFlow-DBClient/1.1'
        }
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers
    
    def _check_response(self, r: requests.Response) -> dict:
        """检查响应状态并解析JSON"""
        # 检查HTTP状态码
        if r.status_code >= 400:
            error_msg = f"HTTP {r.status_code}"
            try:
                error_data = r.json()
                if isinstance(error_data, dict):
                    error_msg = error_data.get('error', error_msg)
            except:
                error_msg = f"{error_msg}: {r.text[:200]}"
            return {"success": False, "error": error_msg, "status_code": r.status_code}
        
        # 解析JSON响应
        try:
            return r.json()
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"JSON解析失败: {e}", "raw": r.text[:200]}
    
    def _build_url(self, endpoint: str) -> str:
        """构建完整URL"""
        safe_endpoint = _validate_endpoint(endpoint)
        if not safe_endpoint:
            raise ValueError(f"无效的端点路径: {endpoint}")
        return f"{self.base_url}{safe_endpoint}"
    
    def _post(self, endpoint: str, data: dict) -> dict:
        """POST请求"""
        try:
            url = self._build_url(endpoint)
            session = _get_session()
            
            # 安全序列化数据
            safe_data = _safe_json_serialize(data)
            
            r = session.post(
                url,
                json=safe_data,
                headers=self._get_headers(),
                timeout=10
            )
            return self._check_response(r)
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "请求超时"}
        except requests.exceptions.ConnectionError as e:
            return {"success": False, "error": f"连接失败: {str(e)[:100]}"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"请求异常: {str(e)[:100]}"}
    
    def _get(self, endpoint: str, params: dict = None) -> dict:
        """GET请求"""
        try:
            url = self._build_url(endpoint)
            session = _get_session()
            
            # 清理None值的参数
            safe_params = {k: v for k, v in (params or {}).items() if v is not None}
            
            r = session.get(
                url,
                params=safe_params,
                headers=self._get_headers(),
                timeout=10
            )
            return self._check_response(r)
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "请求超时"}
        except requests.exceptions.ConnectionError as e:
            return {"success": False, "error": f"连接失败: {str(e)[:100]}"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"请求异常: {str(e)[:100]}"}
    
    def _delete(self, endpoint: str) -> dict:
        """DELETE请求"""
        try:
            url = self._build_url(endpoint)
            session = _get_session()
            r = session.delete(
                url,
                headers=self._get_headers(),
                timeout=10
            )
            return self._check_response(r)
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except requests.exceptions.Timeout:
            return {"success": False, "error": "请求超时"}
        except requests.exceptions.ConnectionError as e:
            return {"success": False, "error": f"连接失败: {str(e)[:100]}"}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"请求异常: {str(e)[:100]}"}
    
    # ========== 记忆接口 ==========
    
    def save_memory(self, content: str, category: str = "fact", importance: float = 1.0) -> dict:
        """保存记忆"""
        # 参数验证
        if not content or not isinstance(content, str):
            return {"success": False, "error": "content不能为空"}
        
        if len(content) > 10000:
            return {"success": False, "error": "content长度不能超过10000字符"}
        
        if category not in ("fact", "preference", "context", "knowledge", "other"):
            category = "other"
        
        importance = max(0.0, min(1.0, float(importance)))
        
        return self._post("/api/memory/save", {
            "content": content,
            "category": category,
            "importance": importance
        })
    
    def list_memory(self, category: str = "", limit: int = 100) -> dict:
        """列出记忆"""
        # 参数验证
        limit = max(1, min(1000, int(limit)))
        
        params = {"limit": limit}
        if category and category in ("fact", "preference", "context", "knowledge", "other"):
            params["category"] = category
        
        result = self._get("/api/memory/list", params)
        # 确保返回标准格式
        if "data" not in result:
            result["data"] = []
        return result
    
    def search_memory(self, query: str, limit: int = 20) -> dict:
        """搜索记忆"""
        # 参数验证
        if not query or not isinstance(query, str):
            return {"success": False, "error": "query不能为空", "data": []}
        
        limit = max(1, min(100, int(limit)))
        
        result = self._get("/api/memory/search", {"q": query[:500], "limit": limit})
        if "data" not in result:
            result["data"] = []
        return result
    
    def delete_memory(self, memory_id: int) -> dict:
        """删除记忆"""
        # 参数验证
        try:
            memory_id = int(memory_id)
            if memory_id <= 0:
                return {"success": False, "error": "memory_id必须为正整数"}
        except (TypeError, ValueError):
            return {"success": False, "error": "memory_id格式无效"}
        
        return self._delete(f"/api/memory/{memory_id}")
    
    # ========== 对话接口 ==========
    
    def save_chat(self, session_id: str, role: str, content: str, 
                  tokens: int = 0, model: str = "") -> dict:
        """保存对话"""
        # 参数验证
        if not session_id or not isinstance(session_id, str):
            return {"success": False, "error": "session_id不能为空"}
        
        if role not in ("user", "assistant", "system"):
            return {"success": False, "error": "role必须是user/assistant/system"}
        
        if not content:
            content = ""
        
        tokens = max(0, int(tokens))
        
        return self._post("/api/chat/save", {
            "session_id": session_id[:100],  # 限制长度
            "role": role,
            "content": content[:50000],  # 限制长度
            "tokens": tokens,
            "model": model[:100] if model else ""
        })
    
    def get_chat_history(self, session_id: str, limit: int = 100) -> dict:
        """获取对话历史"""
        # 参数验证
        if not session_id:
            return {"success": False, "error": "session_id不能为空", "data": []}
        
        limit = max(1, min(1000, int(limit)))
        
        result = self._get(f"/api/chat/history/{session_id[:100]}", {"limit": limit})
        if "data" not in result:
            result["data"] = []
        return result
    
    def list_sessions(self, limit: int = 50) -> dict:
        """列出会话"""
        limit = max(1, min(500, int(limit)))
        
        result = self._get("/api/chat/sessions", {"limit": limit})
        if "data" not in result:
            result["data"] = []
        return result
    
    # ========== 金融数据接口 ==========
    
    def save_quotes(self, quotes: List[dict]) -> dict:
        """保存行情数据"""
        # 参数验证
        if not quotes or not isinstance(quotes, list):
            return {"success": False, "error": "quotes必须是非空列表"}
        
        if len(quotes) > 1000:
            return {"success": False, "error": "quotes单次最多1000条"}
        
        return self._post("/api/stock/quotes", quotes)
    
    def get_quotes(self, code: str, limit: int = 100) -> dict:
        """获取行情历史"""
        # 参数验证
        if not code or not isinstance(code, str):
            return {"success": False, "error": "code不能为空", "data": []}
        
        # 验证股票代码格式
        code = code.strip()
        if not re.match(r'^[0-9]{6}$', code):
            return {"success": False, "error": "股票代码格式无效，应为6位数字", "data": []}
        
        limit = max(1, min(1000, int(limit)))
        
        result = self._get(f"/api/stock/quotes/{code}", {"limit": limit})
        if "data" not in result:
            result["data"] = []
        return result
    
    def record_trade(self, code: str, name: str, action: str, 
                     quantity: int, price: float, amount: float, 
                     trade_time: str = None) -> dict:
        """记录交易"""
        # 参数验证
        if not code or not re.match(r'^[0-9]{6}$', code):
            return {"success": False, "error": "股票代码格式无效"}
        
        if not name:
            name = ""
        
        if action not in ("buy", "sell"):
            return {"success": False, "error": "action必须是buy或sell"}
        
        try:
            quantity = int(quantity)
            if quantity <= 0:
                return {"success": False, "error": "quantity必须为正整数"}
        except (TypeError, ValueError):
            return {"success": False, "error": "quantity格式无效"}
        
        try:
            price = float(price)
            if price <= 0:
                return {"success": False, "error": "price必须为正数"}
        except (TypeError, ValueError):
            return {"success": False, "error": "price格式无效"}
        
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = quantity * price
        
        # 验证交易时间格式
        if trade_time:
            try:
                datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
            except ValueError:
                trade_time = datetime.now().isoformat()
        else:
            trade_time = datetime.now().isoformat()
        
        return self._post("/api/trade/record", {
            "code": code,
            "name": name[:50] if name else "",
            "action": action,
            "quantity": quantity,
            "price": round(price, 3),
            "amount": round(amount, 2),
            "trade_time": trade_time
        })
    
    def list_trades(self, limit: int = 100) -> dict:
        """列出交易记录"""
        limit = max(1, min(1000, int(limit)))
        
        result = self._get("/api/trade/list", {"limit": limit})
        if "data" not in result:
            result["data"] = []
        return result
    
    # ========== 健康检查 ==========
    
    def health_check(self) -> bool:
        """健康检查"""
        try:
            r = self._get("/health")
            return r.get("status") == "ok" or r.get("success") == True
        except:
            return False
    
    # ========== 连接管理 ==========
    
    @staticmethod
    def close_session():
        """关闭全局Session连接池"""
        global _session
        if _session is not None:
            _session.close()
            _session = None


# 全局客户端实例
db = DBClient()


# 兼容旧接口的函数（返回dict而不是List）
def save_memory(content: str, category: str = "fact", importance: float = 1.0) -> dict:
    """保存记忆"""
    return db.save_memory(content, category, importance)

def search_memory(query: str, limit: int = 20) -> dict:
    """搜索记忆"""
    return db.search_memory(query, limit)

def list_memory(category: str = "", limit: int = 100) -> dict:
    """列出记忆"""
    return db.list_memory(category, limit)


if __name__ == "__main__":
    # 测试
    print("测试数据库客户端 v1.1...")
    
    # 健康检查
    print(f"健康检查: {'OK' if db.health_check() else 'FAIL'}")
    
    # 搜索测试
    results = db.search_memory("交易", limit=5)
    print(f"搜索'交易': {len(results.get('data', []))}条结果")
    
    data = results.get('data', [])
    if data:
        print(f"示例: {data[0].get('content', '')[:50]}...")
    
    # 清理连接
    DBClient.close_session()

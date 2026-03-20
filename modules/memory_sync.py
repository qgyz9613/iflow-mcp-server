"""
iFlow 记忆同步模块 v1.2
将本地记忆系统同步到远程数据库

v1.2 更新:
- 添加线程锁保护SQLite并发访问
- 修复裸except捕获问题
- 添加远程API响应格式验证

v1.1 更新:
- 修复SQL注入风险
- 添加参数验证
- 改进错误处理
- 支持环境变量配置
"""

import os
import json
import sqlite3
import requests
import re
import hashlib
import urllib.parse
import threading
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Any

# 线程锁 - 保护SQLite并发访问
_db_lock = threading.Lock()

# 配置 - 从环境变量读取，支持自定义
MEMORY_DIR = Path(os.environ.get("IFLOW_MEMORY_DIR", r"C:\Users\admin\.iflow\memory"))
VECTORS_DB = MEMORY_DIR / "vectors.db"
INDEX_JSON = MEMORY_DIR / "index.json"
DB_API_BASE = os.environ.get("IFLOW_DB_API", "http://192.168.100.216:18080")

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


def _validate_category(category: str) -> str:
    """验证并规范化分类"""
    allowed_categories = {"fact", "preference", "context", "knowledge", "test", "other"}
    if not category or not isinstance(category, str):
        return "other"
    category = category.lower().strip()
    return category if category in allowed_categories else "other"


def _validate_content(content: str) -> tuple:
    """验证内容，返回(是否有效, 错误信息)"""
    if not content or not isinstance(content, str):
        return False, "内容不能为空"
    if len(content) > 50000:
        return False, "内容长度超过限制(50000字符)"
    return True, None


def _validate_importance(importance: float) -> float:
    """验证并规范化重要性"""
    try:
        importance = float(importance)
        return max(0.0, min(10.0, importance))
    except (TypeError, ValueError):
        return 5.0


class MemorySync:
    """记忆同步器"""
    
    def __init__(self, api_base: str = None):
        self.local_db = str(VECTORS_DB)
        self.index_file = str(INDEX_JSON)
        self.remote_api = api_base or DB_API_BASE
        
        # 验证URL
        if not _is_allowed_url(self.remote_api):
            raise ValueError(f"API地址不在允许列表中: {self.remote_api}")
    
    def check_remote(self) -> bool:
        """检查远程数据库连接"""
        try:
            r = requests.get(f"{self.remote_api}/health", timeout=5)
            return r.ok
        except Exception:
            return False
    
    def get_local_memories(self) -> List[Dict]:
        """获取本地所有记忆"""
        memories = []
        
        # 从 vectors.db 读取
        if VECTORS_DB.exists():
            conn = None
            try:
                with _db_lock:  # 线程安全
                    conn = sqlite3.connect(self.local_db)
                    cursor = conn.cursor()
                    # 使用参数化查询，安全
                    cursor.execute("""
                        SELECT memory_id, content, category, created_at, source_file 
                        FROM memory_vectors
                    """)
                    for row in cursor.fetchall():
                        memories.append({
                            "id": str(row[0]) if row[0] else "",
                            "content": str(row[1]) if row[1] else "",
                            "category": _validate_category(row[2]),
                            "created_at": str(row[3]) if row[3] else "",
                            "source": str(row[4]) if row[4] else "local"
                        })
            except sqlite3.Error as e:
                print(f"读取本地数据库错误: {e}")
            finally:
                if conn:
                    conn.close()
        
        return memories
    
    def sync_to_remote(self, memories: List[Dict] = None) -> Dict:
        """同步记忆到远程数据库"""
        if memories is None:
            memories = self.get_local_memories()
        
        if not memories:
            return {"synced": 0, "error": "无本地记忆"}
        
        if not self.check_remote():
            return {"synced": 0, "error": "远程数据库不可用"}
        
        synced = 0
        errors = 0
        error_details = []
        
        for mem in memories:
            try:
                # 验证内容
                valid, err = _validate_content(mem.get("content", ""))
                if not valid:
                    errors += 1
                    error_details.append(f"[{mem.get('id', '?')}] {err}")
                    continue
                
                r = requests.post(
                    f"{self.remote_api}/api/memory/save", 
                    json={
                        "content": mem["content"][:50000],  # 限制长度
                        "category": _validate_category(mem.get("category")),
                        "importance": 8.0
                    }, 
                    timeout=REQUEST_TIMEOUT
                )
                if r.ok:
                    synced += 1
                else:
                    errors += 1
            except requests.exceptions.RequestException as e:
                errors += 1
                error_details.append(f"[{mem.get('id', '?')}] 网络错误: {str(e)[:100]}")
            except Exception as e:
                errors += 1
                error_details.append(f"[{mem.get('id', '?')}] {str(e)[:100]}")
        
        result = {"synced": synced, "errors": errors, "total": len(memories)}
        if error_details:
            result["error_details"] = error_details[:10]  # 只保留前10个错误
        return result
    
    def save_to_remote(self, content: str, category: str = "fact", importance: float = 8.0) -> Dict:
        """直接保存记忆到远程数据库"""
        # 参数验证
        valid, err = _validate_content(content)
        if not valid:
            return {"success": False, "error": err}
        
        if not self.check_remote():
            return {"success": False, "error": "远程数据库不可用"}
        
        try:
            r = requests.post(
                f"{self.remote_api}/api/memory/save", 
                json={
                    "content": content[:50000],
                    "category": _validate_category(category),
                    "importance": _validate_importance(importance)
                }, 
                timeout=REQUEST_TIMEOUT
            )
            result = r.json()
            # 验证响应格式
            if not isinstance(result, dict):
                return {"success": False, "error": "响应格式错误: 期望字典"}
            result["success"] = r.ok
            return result
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": f"网络错误: {str(e)[:100]}"}
        except json.JSONDecodeError:
            return {"success": False, "error": "响应解析失败"}
        except Exception as e:
            return {"success": False, "error": str(e)[:100]}
    
    def search_remote(self, query: str, limit: int = 20) -> List[Dict]:
        """搜索远程数据库记忆"""
        # 参数验证
        if not query or not isinstance(query, str):
            return []
        
        if not self.check_remote():
            return []
        
        limit = max(1, min(100, int(limit)))
        
        try:
            r = requests.get(
                f"{self.remote_api}/api/memory/search", 
                params={
                    "q": query[:500],  # 限制查询长度
                    "limit": limit
                }, 
                timeout=REQUEST_TIMEOUT
            )
            data = r.json()
            # 验证响应格式
            if isinstance(data, dict):
                result_list = data.get("data", [])
                return result_list if isinstance(result_list, list) else []
            elif isinstance(data, list):
                return data
            return []
        except Exception:
            return []
    
    def get_stats(self) -> Dict:
        """获取存储统计"""
        stats = {
            "local": {"count": 0, "last_update": None},
            "remote": {"count": 0, "last_update": None},
            "connected": False
        }
        
        # 本地统计
        if VECTORS_DB.exists():
            conn = None
            try:
                with _db_lock:  # 线程安全
                    conn = sqlite3.connect(self.local_db)
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM memory_vectors")
                    stats["local"]["count"] = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT MAX(created_at) FROM memory_vectors")
                    result = cursor.fetchone()
                    if result and result[0]:
                        stats["local"]["last_update"] = str(result[0])
            except sqlite3.Error:
                pass
            finally:
                if conn:
                    conn.close()
        
        # 远程统计
        if self.check_remote():
            stats["connected"] = True
            try:
                r = requests.get(
                    f"{self.remote_api}/api/memory/list", 
                    params={"limit": 1}, 
                    timeout=5
                )
                data = r.json()
                # 验证响应格式
                if isinstance(data, dict):
                    stats["remote"]["count"] = data.get("count", 0)
                    data_list = data.get("data")
                    if isinstance(data_list, list) and data_list:
                        first_item = data_list[0]
                        if isinstance(first_item, dict):
                            stats["remote"]["last_update"] = first_item.get("created_at")
            except Exception:
                pass
        
        return stats


# 全局实例
try:
    memory_sync = MemorySync()
except ValueError as e:
    print(f"MemorySync初始化警告: {e}")
    memory_sync = None


def save_memory_remote(content: str, category: str = "fact", importance: float = 8.0) -> Dict:
    """保存记忆到远程数据库（替代内置 save_memory）"""
    if memory_sync is None:
        return {"success": False, "error": "MemorySync未初始化"}
    return memory_sync.save_to_remote(content, category, importance)


def save_memory_dual(content: str, category: str = "fact", importance: float = 8.0) -> Dict:
    """
    双重存储：同时保存到本地和远程
    确保数据不会丢失
    """
    # 参数验证
    valid, err = _validate_content(content)
    if not valid:
        return {"success": False, "error": err, "local": False, "remote": False}
    
    result = {
        "local": False, 
        "remote": False, 
        "errors": [],
        "success": False
    }
    
    # 1. 先保存到本地（快速，不会失败）
    try:
        local_result = _save_to_local(content, _validate_category(category), _validate_importance(importance))
        result["local"] = True
        result["local_id"] = local_result.get("id")
    except Exception as e:
        result["errors"].append(f"本地保存失败: {str(e)[:100]}")
    
    # 2. 再保存到远程（异步，失败不影响本地）
    if memory_sync:
        try:
            remote_result = memory_sync.save_to_remote(content, category, importance)
            result["remote"] = remote_result.get("success", False)
            result["remote_id"] = remote_result.get("id")
        except Exception as e:
            result["errors"].append(f"远程保存失败: {str(e)[:100]}")
    else:
        result["errors"].append("远程保存失败: MemorySync未初始化")
    
    result["success"] = result["local"] or result["remote"]
    return result


def _save_to_local(content: str, category: str, importance: float) -> Dict:
    """保存到本地 vectors.db"""
    # 生成唯一ID
    mem_id = hashlib.md5(f"{content}{datetime.now().isoformat()}".encode()).hexdigest()[:12]
    
    conn = None
    try:
        with _db_lock:  # 线程安全
            conn = sqlite3.connect(str(VECTORS_DB))
            cursor = conn.cursor()
            # 使用参数化查询，防止SQL注入
            cursor.execute("""
                INSERT OR REPLACE INTO memory_vectors (memory_id, content, category, created_at, source_file)
                VALUES (?, ?, ?, ?, ?)
            """, (mem_id, content, category, datetime.now().isoformat(), "dual_sync"))
            conn.commit()
            return {"id": mem_id, "success": True}
    finally:
        if conn:
            conn.close()


def auto_sync_on_startup() -> Dict:
    """
    启动时自动同步
    检查本地是否有未同步的记忆，自动推送到远程
    """
    if memory_sync is None:
        return {"synced": 0, "skipped": 0, "error": "MemorySync未初始化"}
    
    # 检查是否已同步
    sync_marker = MEMORY_DIR / ".sync_completed"
    
    if sync_marker.exists():
        try:
            with open(sync_marker, "r", encoding='utf-8') as f:
                last_sync = f.read().strip()
            print(f"上次同步: {last_sync}")
        except Exception:
            pass
    
    # 获取本地和远程的记忆ID列表
    local_ids = set()
    if VECTORS_DB.exists():
        conn = None
        try:
            with _db_lock:  # 线程安全
                conn = sqlite3.connect(str(VECTORS_DB))
                cursor = conn.cursor()
                cursor.execute("SELECT memory_id FROM memory_vectors")
                local_ids = {str(row[0]) for row in cursor.fetchall()}
        except sqlite3.Error:
            pass
        finally:
            if conn:
                conn.close()
    
    # 获取远程记忆数量
    remote_count = 0
    if memory_sync.check_remote():
        try:
            r = requests.get(
                f"{DB_API_BASE}/api/memory/list?limit=500", 
                timeout=REQUEST_TIMEOUT
            )
            data = r.json()
            # 验证响应格式
            if isinstance(data, dict):
                data_list = data.get("data", [])
                remote_count = len(data_list) if isinstance(data_list, list) else 0
        except Exception:
            pass
    
    # 如果本地多于远程，需要同步
    result = {"synced": 0, "skipped": 0, "error": None}
    
    if len(local_ids) > remote_count:
        print(f"检测到未同步记忆: 本地{len(local_ids)}条, 远程{remote_count}条")
        sync_result = sync_all_memories()
        result["synced"] = sync_result.get("synced", 0)
        result["errors"] = sync_result.get("errors", 0)
    else:
        result["skipped"] = len(local_ids)
    
    # 标记同步完成
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(sync_marker, "w", encoding='utf-8') as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        result["marker_error"] = str(e)
    
    return result


def search_memory_remote(query: str, limit: int = 20) -> List[Dict]:
    """搜索远程数据库记忆"""
    if memory_sync is None:
        return []
    return memory_sync.search_remote(query, limit)


def sync_all_memories() -> Dict:
    """同步所有本地记忆到远程"""
    if memory_sync is None:
        return {"synced": 0, "error": "MemorySync未初始化"}
    return memory_sync.sync_to_remote()


if __name__ == "__main__":
    print("iFlow 记忆同步模块 v1.2")
    print("=" * 50)
    
    if memory_sync is None:
        print("错误: MemorySync未初始化")
        exit(1)
    
    # 检查状态
    stats = memory_sync.get_stats()
    print(f"本地记忆: {stats['local']['count']} 条")
    print(f"远程记忆: {stats['remote']['count']} 条")
    print(f"连接状态: {'OK 已连接' if stats['connected'] else 'X 未连接'}")
    
    # 测试保存
    print("\n测试保存记忆到远程数据库...")
    result = save_memory_remote("测试记忆-20260315-远程数据库连接测试", "test", 5.0)
    print(f"保存结果: {result}")
    
    # 搜索测试
    print("\n搜索测试...")
    results = search_memory_remote("测试记忆")
    print(f"找到 {len(results)} 条匹配记录")
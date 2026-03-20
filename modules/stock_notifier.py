# -*- coding: utf-8 -*-
"""
股票消息推送模块 - stock_notifier.py
支持多渠道推送：微信、飞书、Telegram、钉钉、邮件
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime, time
import asyncio
import logging
import os
import sys
import base64

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ==================== 配置管理 ====================
@dataclass
class NotifierConfig:
    """推送配置"""
    enabled: bool = True
    wechat_contact: str = "文件传输助手"  # 默认发送给文件传输助手
    push_times: List[str] = field(default_factory=lambda: ["09:00", "11:30", "15:30"])
    retry_count: int = 3
    retry_delay: float = 1.0  # 重试延迟秒数
    
    def should_push_now(self) -> bool:
        """检查当前时间是否应该推送"""
        now = datetime.now().strftime("%H:%M")
        return now in self.push_times


# ==================== 消息格式化 ====================
def format_trade_signal(signal: Dict) -> str:
    """
    格式化交易信号为可读文本
    
    Args:
        signal: 交易信号字典，包含:
            - stock_code: 股票代码
            - stock_name: 股票名称
            - action: 操作 (buy/sell/hold)
            - price: 价格
            - quantity: 数量
            - reason: 原因
            - confidence: 置信度
            - timestamp: 时间戳
    
    Returns:
        格式化后的消息文本
    """
    action_emoji = {
        "buy": "🟢买入",
        "sell": "🔴卖出",
        "hold": "🟡持有",
        "strong_buy": "🟢强烈买入",
        "strong_sell": "🔴强烈卖出"
    }
    
    action = signal.get("action", "hold")
    action_text = action_emoji.get(action, action)
    
    # 使用 or 0 避免 None 值导致格式化错误
    price = signal.get('price') or 0
    quantity = signal.get('quantity') or 0
    confidence = signal.get('confidence') or 0
    
    msg = f"""【交易信号】
股票：{signal.get('stock_name', '未知')}({signal.get('stock_code', '未知')})
操作：{action_text}
价格：{price:.2f}元
数量：{quantity}股
原因：{signal.get('reason', '无')}
置信度：{confidence:.1%}
时间：{signal.get('timestamp', datetime.now().strftime('%H:%M:%S'))}
"""
    return msg


def format_daily_summary(stocks: List[Dict]) -> str:
    """
    格式化每日摘要
    
    Args:
        stocks: 股票列表，每个元素包含:
            - stock_code: 股票代码
            - stock_name: 股票名称
            - current_price: 当前价格
            - change_pct: 涨跌幅
            - volume: 成交量
            - turnover: 成交额
    
    Returns:
        格式化后的摘要文本
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    lines = [f"【每日摘要】{now}", "=" * 30]
    
    up_count = 0
    down_count = 0
    total_value = 0
    
    for stock in stocks:
        change_pct = stock.get('change_pct') or 0
        if change_pct > 0:
            up_count += 1
            emoji = "📈"
        elif change_pct < 0:
            down_count += 1
            emoji = "📉"
        else:
            emoji = "➖"
        
        # 使用 or 0 避免 None 值导致格式化错误
        current_price = stock.get('current_price') or 0
        turnover = stock.get('turnover') or 0
        
        lines.append(
            f"{emoji} {stock.get('stock_name', '未知')}({stock.get('stock_code', '未知')})\n"
            f"   价格: {current_price:.2f}元 "
            f"涨跌: {change_pct:+.2f}%\n"
            f"   成交额: {turnover/1e8:.2f}亿"
        )
        total_value += stock.get('market_value') or 0
    
    lines.append("=" * 30)
    lines.append(f"统计: 上涨{up_count}只, 下跌{down_count}只, 平盘{len(stocks)-up_count-down_count}只")
    
    return "\n".join(lines)


def format_alert(alert: Dict) -> str:
    """
    格式化预警消息
    
    Args:
        alert: 预警信息字典
    
    Returns:
        格式化后的预警文本
    """
    alert_type = alert.get('type', 'unknown')
    level = alert.get('level', 'info')
    
    level_emoji = {
        'critical': '🚨',
        'warning': '⚠️',
        'info': 'ℹ️'
    }
    
    emoji = level_emoji.get(level, 'ℹ️')
    
    msg = f"""【{emoji}预警】
类型：{alert_type}
股票：{alert.get('stock_name', '未知')}({alert.get('stock_code', '未知')})
内容：{alert.get('message', '无详细信息')}
时间：{alert.get('timestamp', datetime.now().strftime('%H:%M:%S'))}
"""
    return msg


def format_portfolio_report(portfolio: Dict) -> str:
    """
    格式化持仓报告
    
    Args:
        portfolio: 持仓信息字典
    
    Returns:
        格式化后的持仓报告
    """
    lines = [
        f"【持仓报告】{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "=" * 35
    ]
    
    total_profit = 0
    positions = portfolio.get('positions', [])
    
    for pos in positions:
        profit = pos.get('profit') or 0
        profit_pct = pos.get('profit_pct') or 0
        total_profit += profit
        
        # 使用 or 0 避免 None 值导致格式化错误
        quantity = pos.get('quantity') or 0
        cost = pos.get('cost') or 0
        current_price = pos.get('current_price') or 0
        
        profit_emoji = "📈" if profit >= 0 else "📉"
        lines.append(
            f"{profit_emoji} {pos.get('stock_name', '未知')}({pos.get('stock_code', '未知')})\n"
            f"   持仓: {quantity}股 成本: {cost:.2f}\n"
            f"   现价: {current_price:.2f} 盈亏: {profit:+.2f}({profit_pct:+.2f}%)"
        )
    
    lines.append("=" * 35)
    lines.append(f"总盈亏: {total_profit:+.2f}元")
    available_cash = portfolio.get('available_cash') or 0
    total_asset = portfolio.get('total_asset') or 0
    lines.append(f"可用资金: {available_cash:.2f}元")
    lines.append(f"总资产: {total_asset:.2f}元")
    
    return "\n".join(lines)


# ==================== 微信推送类 ====================
class WeChatNotifier:
    """微信消息推送器 - 使用Windows RPA方式"""
    
    def __init__(self, config: Optional[NotifierConfig] = None):
        """
        初始化微信推送器
        
        Args:
            config: 推送配置，为None时使用默认配置
        """
        self.config = config or NotifierConfig()
        self._initialized = False
        self._hwnd = None
        
        # 尝试导入必要的库
        try:
            import win32gui
            import pyautogui
            import pyperclip
            self._win32gui = win32gui
            self._pyautogui = pyautogui
            self._pyperclip = pyperclip
            self._available = True
        except ImportError as e:
            logger.warning(f"微信RPA依赖库未安装: {e}")
            self._available = False
    
    def _find_wechat_window(self) -> Optional[int]:
        """
        查找微信窗口句柄
        
        Returns:
            窗口句柄，未找到返回None
        """
        if not self._available:
            return None
        
        try:
            hwnd = self._win32gui.FindWindow(None, '微信')
            if hwnd == 0:
                # 尝试查找包含"微信"的窗口
                hwnd = self._win32gui.FindWindow('WeChatMainWndForPC', None)
            return hwnd if hwnd != 0 else None
        except Exception as e:
            logger.error(f"查找微信窗口失败: {e}")
            return None
    
    def _activate_window(self, hwnd: int) -> bool:
        """
        激活微信窗口
        
        Args:
            hwnd: 窗口句柄
        
        Returns:
            是否成功激活
        """
        try:
            # 先尝试直接设置前台窗口
            self._win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            try:
                # 备用方案：使用PowerShell激活
                import subprocess
                subprocess.run(
                    ['powershell', '-Command', 
                     "$wshell = New-Object -ComObject WScript.Shell; $wshell.AppActivate('微信')"],
                    capture_output=True, timeout=5
                )
                import time
                time.sleep(0.5)
                return True
            except Exception as e:
                logger.error(f"激活微信窗口失败: {e}")
                return False
    
    def _get_window_rect(self, hwnd: int) -> Optional[tuple]:
        """
        获取窗口矩形坐标
        
        Args:
            hwnd: 窗口句柄
        
        Returns:
            (left, top, right, bottom) 或 None
        """
        try:
            return self._win32gui.GetWindowRect(hwnd)
        except Exception as e:
            logger.error(f"获取窗口坐标失败: {e}")
            return None
    
    async def _search_contact(self, contact_name: str) -> bool:
        """
        搜索并选中联系人（异步版本）
        
        Args:
            contact_name: 联系人名称
        
        Returns:
            是否成功选中
        """
        try:
            hwnd = self._find_wechat_window()
            if not hwnd:
                logger.error("未找到微信窗口")
                return False
            
            rect = self._get_window_rect(hwnd)
            if not rect:
                return False
            
            left, top, right, bottom = rect
            width = right - left
            
            # 激活窗口
            if not self._activate_window(hwnd):
                return False
            
            await asyncio.sleep(0.3)
            
            # 使用点击搜索框方式（Ctrl+F在微信打开Web搜索，不是联系人搜索）
            # 搜索框位置：窗口左上角，大约 (left + 150, top + 35)
            search_x = left + 150
            search_y = top + 35
            self._pyautogui.click(search_x, search_y)
            await asyncio.sleep(0.5)
            
            # 输入联系人名称（使用剪贴板处理中文）
            self._pyperclip.copy(contact_name)
            self._pyautogui.hotkey('ctrl', 'v')
            await asyncio.sleep(0.5)
            
            # 按回车选中搜索结果
            self._pyautogui.press('enter')
            await asyncio.sleep(0.3)
            
            return True
            
        except Exception as e:
            logger.error(f"搜索联系人失败: {e}")
            return False
    
    async def send_message(self, contact_name: str, message: str) -> bool:
        """
        发送消息给微信联系人
        
        Args:
            contact_name: 联系人名称
            message: 消息内容
        
        Returns:
            是否发送成功
        """
        if not self._available:
            logger.warning("微信RPA功能不可用，请安装依赖库")
            return False
        
        if not self.config.enabled:
            logger.info("消息推送已禁用")
            return False
        
        for attempt in range(self.config.retry_count):
            try:
                # 搜索联系人（现在是异步方法）
                if not await self._search_contact(contact_name):
                    logger.warning(f"搜索联系人失败，重试 {attempt + 1}/{self.config.retry_count}")
                    await asyncio.sleep(self.config.retry_delay)
                    continue
                
                await asyncio.sleep(0.3)
                
                # 输入消息（使用剪贴板处理中文）
                self._pyperclip.copy(message)
                self._pyautogui.hotkey('ctrl', 'v')
                await asyncio.sleep(0.2)
                
                # 发送消息
                self._pyautogui.press('enter')
                
                logger.info(f"消息已发送给 {contact_name}")
                return True
                
            except Exception as e:
                logger.error(f"发送消息失败 (尝试 {attempt + 1}): {e}")
                await asyncio.sleep(self.config.retry_delay)
        
        logger.error(f"发送消息失败，已重试 {self.config.retry_count} 次")
        return False
    
    async def send_analysis_report(self, contact_name: str, stock_code: str, report: str) -> bool:
        """
        发送股票分析报告
        
        Args:
            contact_name: 联系人名称
            stock_code: 股票代码
            report: 分析报告内容
        
        Returns:
            是否发送成功
        """
        header = f"【股票分析报告】{stock_code}\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'='*30}\n"
        full_message = header + report
        return await self.send_message(contact_name, full_message)
    
    async def send_trade_signal(self, signal: Dict) -> bool:
        """
        发送交易信号
        
        Args:
            signal: 交易信号字典
        
        Returns:
            是否发送成功
        """
        message = format_trade_signal(signal)
        return await self.send_message(self.config.wechat_contact, message)
    
    async def send_daily_summary(self, stocks: List[Dict]) -> bool:
        """
        发送每日摘要
        
        Args:
            stocks: 股票列表
        
        Returns:
            是否发送成功
        """
        message = format_daily_summary(stocks)
        return await self.send_message(self.config.wechat_contact, message)
    
    async def send_alert(self, alert: Dict) -> bool:
        """
        发送预警消息
        
        Args:
            alert: 预警信息
        
        Returns:
            是否发送成功
        """
        message = format_alert(alert)
        return await self.send_message(self.config.wechat_contact, message)
    
    async def send_portfolio_report(self, portfolio: Dict) -> bool:
        """
        发送持仓报告
        
        Args:
            portfolio: 持仓信息
        
        Returns:
            是否发送成功
        """
        message = format_portfolio_report(portfolio)
        return await self.send_message(self.config.wechat_contact, message)


# ==================== 飞书推送类 ====================
class FeishuNotifier:
    """飞书消息推送器 - 使用Webhook"""
    
    def __init__(self, webhook_url: str):
        """
        初始化飞书推送器
        
        Args:
            webhook_url: 飞书机器人Webhook地址
        """
        self.webhook_url = webhook_url
        self._session = None
    
    async def _get_session(self):
        """获取aiohttp session"""
        if self._session is None:
            try:
                import aiohttp
                self._session = aiohttp.ClientSession()
            except ImportError:
                logger.warning("aiohttp未安装，飞书推送不可用")
                return None
        return self._session
    
    async def send_message(self, message: str) -> bool:
        """
        发送飞书文本消息
        
        Args:
            message: 消息内容
        
        Returns:
            是否发送成功
        """
        session = await self._get_session()
        if not session:
            return False
        
        payload = {
            "msg_type": "text",
            "content": {
                "text": message
            }
        }
        
        try:
            async with session.post(self.webhook_url, json=payload) as resp:
                result = await resp.json()
                if result.get("StatusCode") == 0 or result.get("code") == 0:
                    logger.info("飞书消息发送成功")
                    return True
                else:
                    logger.error(f"飞书消息发送失败: {result}")
                    return False
        except Exception as e:
            logger.error(f"飞书消息发送异常: {e}")
            return False
    
    async def send_card(self, title: str, content: Dict) -> bool:
        """
        发送飞书卡片消息
        
        Args:
            title: 卡片标题
            content: 卡片内容
        
        Returns:
            是否发送成功
        """
        session = await self._get_session()
        if not session:
            return False
        
        # 构建卡片消息
        elements = []
        for key, value in content.items():
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{key}**: {value}"
                }
            })
        
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue"
                },
                "elements": elements
            }
        }
        
        try:
            async with session.post(self.webhook_url, json=payload) as resp:
                result = await resp.json()
                if result.get("StatusCode") == 0 or result.get("code") == 0:
                    logger.info("飞书卡片消息发送成功")
                    return True
                else:
                    logger.error(f"飞书卡片消息发送失败: {result}")
                    return False
        except Exception as e:
            logger.error(f"飞书卡片消息发送异常: {e}")
            return False
    
    async def send_trade_signal(self, signal: Dict) -> bool:
        """发送交易信号卡片"""
        action_emoji = {"buy": "🟢", "sell": "🔴", "hold": "🟡"}
        action = signal.get("action", "hold")
        title = f"{action_emoji.get(action, '')} 交易信号 - {signal.get('stock_name', '未知')}"
        
        content = {
            "股票": f"{signal.get('stock_name', '未知')}({signal.get('stock_code', '未知')})",
            "操作": action.upper(),
            "价格": f"{signal.get('price', 0):.2f}元",
            "数量": f"{signal.get('quantity', 0)}股",
            "原因": signal.get('reason', '无'),
            "置信度": f"{signal.get('confidence', 0):.1%}"
        }
        return await self.send_card(title, content)
    
    async def close(self):
        """关闭session"""
        if self._session:
            await self._session.close()
            self._session = None


# ==================== Telegram推送类 ====================
class TelegramNotifier:
    """Telegram消息推送器"""
    
    def __init__(self, bot_token: str, chat_id: str):
        """
        初始化Telegram推送器
        
        Args:
            bot_token: Telegram Bot Token
            chat_id: 聊天ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._session = None
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
    
    async def _get_session(self):
        """获取aiohttp session"""
        if self._session is None:
            try:
                import aiohttp
                self._session = aiohttp.ClientSession()
            except ImportError:
                logger.warning("aiohttp未安装，Telegram推送不可用")
                return None
        return self._session
    
    async def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """
        发送Telegram消息
        
        Args:
            message: 消息内容
            parse_mode: 解析模式 (HTML/Markdown)
        
        Returns:
            是否发送成功
        """
        session = await self._get_session()
        if not session:
            return False
        
        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        
        try:
            async with session.post(url, json=payload) as resp:
                result = await resp.json()
                if result.get("ok"):
                    logger.info("Telegram消息发送成功")
                    return True
                else:
                    logger.error(f"Telegram消息发送失败: {result.get('description')}")
                    return False
        except Exception as e:
            logger.error(f"Telegram消息发送异常: {e}")
            return False
    
    async def send_trade_signal(self, signal: Dict) -> bool:
        """发送交易信号"""
        action_emoji = {"buy": "🟢", "sell": "🔴", "hold": "🟡"}
        action = signal.get("action", "hold")
        
        message = f"""<b>{action_emoji.get(action, '')} 交易信号</b>

<b>股票:</b> {signal.get('stock_name', '未知')}({signal.get('stock_code', '未知')})
<b>操作:</b> {action.upper()}
<b>价格:</b> {signal.get('price', 0):.2f}元
<b>数量:</b> {signal.get('quantity', 0)}股
<b>原因:</b> {signal.get('reason', '无')}
<b>置信度:</b> {signal.get('confidence', 0):.1%}
<b>时间:</b> {signal.get('timestamp', datetime.now().strftime('%H:%M:%S'))}
"""
        return await self.send_message(message)
    
    async def send_alert(self, alert: Dict) -> bool:
        """发送预警消息"""
        level_emoji = {'critical': '🚨', 'warning': '⚠️', 'info': 'ℹ️'}
        emoji = level_emoji.get(alert.get('level', 'info'), 'ℹ️')
        
        message = f"""<b>{emoji} 预警</b>

<b>类型:</b> {alert.get('type', 'unknown')}
<b>股票:</b> {alert.get('stock_name', '未知')}({alert.get('stock_code', '未知')})
<b>内容:</b> {alert.get('message', '无详细信息')}
<b>时间:</b> {alert.get('timestamp', datetime.now().strftime('%H:%M:%S'))}
"""
        return await self.send_message(message)
    
    async def close(self):
        """关闭session"""
        if self._session:
            await self._session.close()
            self._session = None


# ==================== 钉钉推送类 ====================
class DingTalkNotifier:
    """钉钉消息推送器 - 使用Webhook"""
    
    def __init__(self, webhook_url: str, secret: str = None):
        """
        初始化钉钉推送器
        
        Args:
            webhook_url: 钉钉机器人Webhook地址
            secret: 加签密钥（可选，用于安全设置）
        """
        self.webhook_url = webhook_url
        self.secret = secret
        self._session = None
    
    async def _get_session(self):
        """获取aiohttp session"""
        if self._session is None:
            try:
                import aiohttp
                self._session = aiohttp.ClientSession()
            except ImportError:
                logger.warning("aiohttp未安装，钉钉推送不可用")
                return None
        return self._session
    
    def _sign_url(self) -> str:
        """生成签名URL"""
        if not self.secret:
            return self.webhook_url
        
        import time
        import hmac
        import hashlib
        import urllib.parse
        
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        
        return f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"
    
    async def send_message(self, message: str, at_all: bool = False) -> bool:
        """
        发送钉钉文本消息
        
        Args:
            message: 消息内容
            at_all: 是否@所有人
        
        Returns:
            是否发送成功
        """
        import base64
        
        session = await self._get_session()
        if not session:
            return False
        
        url = self._sign_url() if self.secret else self.webhook_url
        
        payload = {
            "msgtype": "text",
            "text": {
                "content": message
            },
            "at": {
                "isAtAll": at_all
            }
        }
        
        try:
            async with session.post(url, json=payload) as resp:
                result = await resp.json()
                if result.get("errcode") == 0:
                    logger.info("钉钉消息发送成功")
                    return True
                else:
                    logger.error(f"钉钉消息发送失败: {result.get('errmsg')}")
                    return False
        except Exception as e:
            logger.error(f"钉钉消息发送异常: {e}")
            return False
    
    async def send_markdown(self, title: str, message: str) -> bool:
        """
        发送钉钉Markdown消息
        
        Args:
            title: 消息标题
            message: Markdown格式消息内容
        
        Returns:
            是否发送成功
        """
        session = await self._get_session()
        if not session:
            return False
        
        url = self._sign_url() if self.secret else self.webhook_url
        
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": message
            }
        }
        
        try:
            async with session.post(url, json=payload) as resp:
                result = await resp.json()
                if result.get("errcode") == 0:
                    logger.info("钉钉Markdown消息发送成功")
                    return True
                else:
                    logger.error(f"钉钉Markdown消息发送失败: {result.get('errmsg')}")
                    return False
        except Exception as e:
            logger.error(f"钉钉Markdown消息发送异常: {e}")
            return False
    
    async def send_trade_signal(self, signal: Dict) -> bool:
        """发送交易信号"""
        action_emoji = {"buy": "🟢", "sell": "🔴", "hold": "🟡"}
        action = signal.get("action", "hold")
        
        title = f"交易信号 - {signal.get('stock_name', '未知')}"
        message = f"""## {action_emoji.get(action, '')} 交易信号

**股票**: {signal.get('stock_name', '未知')}({signal.get('stock_code', '未知')})  
**操作**: {action.upper()}  
**价格**: {signal.get('price', 0):.2f}元  
**数量**: {signal.get('quantity', 0)}股  
**原因**: {signal.get('reason', '无')}  
**置信度**: {signal.get('confidence', 0):.1%}  
**时间**: {signal.get('timestamp', datetime.now().strftime('%H:%M:%S'))}
"""
        return await self.send_markdown(title, message)
    
    async def close(self):
        """关闭session"""
        if self._session:
            await self._session.close()
            self._session = None


# ==================== 邮件推送类 ====================
class EmailNotifier:
    """邮件消息推送器"""
    
    def __init__(self, sender: str, password: str, smtp_server: str = "smtp.qq.com", 
                 smtp_port: int = 465, use_ssl: bool = True):
        """
        初始化邮件推送器
        
        Args:
            sender: 发件人邮箱
            password: 邮箱授权码/密码
            smtp_server: SMTP服务器地址
            smtp_port: SMTP端口
            use_ssl: 是否使用SSL
        """
        self.sender = sender
        self.password = password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.use_ssl = use_ssl
        self._receivers = []
    
    def add_receiver(self, email: str):
        """添加收件人"""
        if email not in self._receivers:
            self._receivers.append(email)
    
    def set_receivers(self, emails: List[str]):
        """设置收件人列表"""
        self._receivers = emails
    
    async def send_email(self, to: str, subject: str, body: str, 
                         html: bool = False) -> bool:
        """
        发送邮件
        
        Args:
            to: 收件人邮箱
            subject: 邮件主题
            body: 邮件内容
            html: 是否为HTML格式
        
        Returns:
            是否发送成功
        """
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.utils import formataddr
        
        try:
            msg = MIMEMultipart()
            msg['From'] = formataddr(["股票助手", self.sender])
            msg['To'] = to
            msg['Subject'] = subject
            
            content_type = 'html' if html else 'plain'
            msg.attach(MIMEText(body, content_type, 'utf-8'))
            
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            else:
                server = smtplib.SMTP(self.smtp_server, self.smtp_port)
                server.starttls()
            
            server.login(self.sender, self.password)
            server.sendmail(self.sender, [to], msg.as_string())
            server.quit()
            
            logger.info(f"邮件发送成功: {to}")
            return True
            
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            return False
    
    async def broadcast(self, subject: str, body: str, html: bool = False) -> Dict[str, bool]:
        """
        群发邮件给所有收件人
        
        Args:
            subject: 邮件主题
            body: 邮件内容
            html: 是否为HTML格式
        
        Returns:
            每个收件人的发送结果
        """
        results = {}
        for receiver in self._receivers:
            results[receiver] = await self.send_email(receiver, subject, body, html)
        return results
    
    async def send_trade_signal(self, signal: Dict) -> bool:
        """发送交易信号邮件"""
        action_emoji = {"buy": "🟢", "sell": "🔴", "hold": "🟡"}
        action = signal.get("action", "hold")
        
        subject = f"{action_emoji.get(action, '')} 交易信号 - {signal.get('stock_name', '未知')}"
        
        body = f"""
<h2>{action_emoji.get(action, '')} 交易信号</h2>
<table border="1" cellpadding="8">
<tr><td><b>股票</b></td><td>{signal.get('stock_name', '未知')}({signal.get('stock_code', '未知')})</td></tr>
<tr><td><b>操作</b></td><td>{action.upper()}</td></tr>
<tr><td><b>价格</b></td><td>{signal.get('price', 0):.2f}元</td></tr>
<tr><td><b>数量</b></td><td>{signal.get('quantity', 0)}股</td></tr>
<tr><td><b>原因</b></td><td>{signal.get('reason', '无')}</td></tr>
<tr><td><b>置信度</b></td><td>{signal.get('confidence', 0):.1%}</td></tr>
<tr><td><b>时间</b></td><td>{signal.get('timestamp', datetime.now().strftime('%H:%M:%S'))}</td></tr>
</table>
"""
        return await self.send_email(self._receivers[0] if self._receivers else "", 
                                    subject, body, html=True)


# ==================== 统一推送管理器 ====================
class NotificationManager:
    """统一推送管理器 - 支持多渠道同时推送"""
    
    def __init__(self):
        """初始化推送管理器"""
        self.notifiers: Dict[str, Any] = {}
        self._enabled = True
    
    # ==================== 添加推送渠道 ====================
    def add_wechat(self, contact: str = "文件传输助手", 
                   config: Optional[NotifierConfig] = None) -> WeChatNotifier:
        """添加微信推送渠道"""
        if config is None:
            config = NotifierConfig(wechat_contact=contact)
        notifier = WeChatNotifier(config)
        self.notifiers['wechat'] = notifier
        return notifier
    
    def add_feishu(self, webhook_url: str) -> FeishuNotifier:
        """添加飞书推送渠道"""
        notifier = FeishuNotifier(webhook_url)
        self.notifiers['feishu'] = notifier
        return notifier
    
    def add_telegram(self, bot_token: str, chat_id: str) -> TelegramNotifier:
        """添加Telegram推送渠道"""
        notifier = TelegramNotifier(bot_token, chat_id)
        self.notifiers['telegram'] = notifier
        return notifier
    
    def add_dingtalk(self, webhook_url: str, secret: str = None) -> DingTalkNotifier:
        """添加钉钉推送渠道"""
        notifier = DingTalkNotifier(webhook_url, secret)
        self.notifiers['dingtalk'] = notifier
        return notifier
    
    def add_email(self, sender: str, password: str, 
                  smtp_server: str = "smtp.qq.com",
                  receivers: List[str] = None) -> EmailNotifier:
        """添加邮件推送渠道"""
        notifier = EmailNotifier(sender, password, smtp_server)
        if receivers:
            notifier.set_receivers(receivers)
        self.notifiers['email'] = notifier
        return notifier
    
    # ==================== 移除推送渠道 ====================
    def remove(self, channel: str) -> bool:
        """移除指定渠道"""
        if channel in self.notifiers:
            del self.notifiers[channel]
            return True
        return False
    
    def clear(self):
        """清空所有渠道"""
        self.notifiers.clear()
    
    # ==================== 渠道管理 ====================
    def get_channels(self) -> List[str]:
        """获取所有已配置的渠道"""
        return list(self.notifiers.keys())
    
    def enable(self, enabled: bool = True):
        """启用/禁用推送"""
        self._enabled = enabled
    
    def is_enabled(self) -> bool:
        """检查是否启用"""
        return self._enabled
    
    # ==================== 统一推送方法 ====================
    async def broadcast(self, message: str, channels: List[str] = None) -> Dict[str, bool]:
        """
        向所有已配置渠道广播消息
        
        Args:
            message: 消息内容
            channels: 指定渠道列表，为None时发送到所有渠道
        
        Returns:
            每个渠道的发送结果
        """
        if not self._enabled:
            logger.info("推送功能已禁用")
            return {}
        
        target_channels = channels or list(self.notifiers.keys())
        results = {}
        
        # 并行发送
        tasks = []
        for channel in target_channels:
            if channel in self.notifiers:
                notifier = self.notifiers[channel]
                if hasattr(notifier, 'send_message'):
                    # 处理微信的特殊情况：需要两个参数 (contact_name, message)
                    if channel == 'wechat':
                        config = self.notifiers[channel].config
                        tasks.append((channel, notifier.send_message(config.wechat_contact, message)))
                    else:
                        tasks.append((channel, notifier.send_message(message)))
        
        for channel, task in tasks:
            try:
                results[channel] = await task
            except Exception as e:
                logger.error(f"渠道 {channel} 发送失败: {e}")
                results[channel] = False
        
        return results
    
    async def broadcast_trade_signal(self, signal: Dict, 
                                     channels: List[str] = None) -> Dict[str, bool]:
        """
        向所有渠道广播交易信号
        
        Args:
            signal: 交易信号
            channels: 指定渠道列表
        
        Returns:
            每个渠道的发送结果
        """
        if not self._enabled:
            return {}
        
        target_channels = channels or list(self.notifiers.keys())
        results = {}
        
        for channel in target_channels:
            if channel in self.notifiers:
                notifier = self.notifiers[channel]
                try:
                    if hasattr(notifier, 'send_trade_signal'):
                        results[channel] = await notifier.send_trade_signal(signal)
                    elif hasattr(notifier, 'send_message'):
                        # 回退到普通消息
                        message = format_trade_signal(signal)
                        results[channel] = await notifier.send_message(message)
                except Exception as e:
                    logger.error(f"渠道 {channel} 发送交易信号失败: {e}")
                    results[channel] = False
        
        return results
    
    async def broadcast_alert(self, alert: Dict, 
                              channels: List[str] = None) -> Dict[str, bool]:
        """
        向所有渠道广播预警消息
        
        Args:
            alert: 预警信息
            channels: 指定渠道列表
        
        Returns:
            每个渠道的发送结果
        """
        if not self._enabled:
            return {}
        
        target_channels = channels or list(self.notifiers.keys())
        results = {}
        
        for channel in target_channels:
            if channel in self.notifiers:
                notifier = self.notifiers[channel]
                try:
                    if hasattr(notifier, 'send_alert'):
                        results[channel] = await notifier.send_alert(alert)
                    elif hasattr(notifier, 'send_message'):
                        message = format_alert(alert)
                        results[channel] = await notifier.send_message(message)
                except Exception as e:
                    logger.error(f"渠道 {channel} 发送预警失败: {e}")
                    results[channel] = False
        
        return results
    
    async def broadcast_daily_summary(self, stocks: List[Dict], 
                                      channels: List[str] = None) -> Dict[str, bool]:
        """
        向所有渠道广播每日摘要
        
        Args:
            stocks: 股票列表
            channels: 指定渠道列表
        
        Returns:
            每个渠道的发送结果
        """
        message = format_daily_summary(stocks)
        return await self.broadcast(message, channels)
    
    async def broadcast_portfolio_report(self, portfolio: Dict, 
                                         channels: List[str] = None) -> Dict[str, bool]:
        """
        向所有渠道广播持仓报告
        
        Args:
            portfolio: 持仓信息
            channels: 指定渠道列表
        
        Returns:
            每个渠道的发送结果
        """
        message = format_portfolio_report(portfolio)
        return await self.broadcast(message, channels)
    
    # ==================== 资源清理 ====================
    async def close(self):
        """关闭所有资源"""
        for name, notifier in self.notifiers.items():
            if hasattr(notifier, 'close'):
                try:
                    await notifier.close()
                except Exception as e:
                    logger.error(f"关闭 {name} 资源失败: {e}")


# ==================== 便捷函数 ====================
def create_notifier(wechat_contact: str = "文件传输助手", 
                    push_times: List[str] = None) -> WeChatNotifier:
    """
    创建微信推送器实例
    
    Args:
        wechat_contact: 微信联系人名称
        push_times: 推送时间列表
    
    Returns:
        WeChatNotifier实例
    """
    config = NotifierConfig(
        wechat_contact=wechat_contact,
        push_times=push_times or ["09:00", "11:30", "15:30"]
    )
    return WeChatNotifier(config)


def create_notification_manager() -> NotificationManager:
    """
    创建统一推送管理器实例
    
    Returns:
        NotificationManager实例
    """
    return NotificationManager()


async def quick_send(message: str, contact: str = "文件传输助手") -> bool:
    """
    快速发送消息
    
    Args:
        message: 消息内容
        contact: 联系人名称
    
    Returns:
        是否发送成功
    """
    notifier = create_notifier(contact)
    return await notifier.send_message(contact, message)


# ==================== 模块测试 ====================
if __name__ == "__main__":
    async def test():
        """测试推送模块功能"""
        print("=" * 50)
        print("测试股票消息推送模块")
        print("=" * 50)
        
        # 测试消息格式化
        signal = {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "action": "buy",
            "price": 10.50,
            "quantity": 1000,
            "reason": "MACD金叉，成交量放大",
            "confidence": 0.75,
            "timestamp": "09:35:00"
        }
        print("\n【交易信号格式化】")
        print(format_trade_signal(signal))
        
        # 测试每日摘要
        stocks = [
            {"stock_code": "600000", "stock_name": "浦发银行", "current_price": 10.50, 
             "change_pct": 2.5, "turnover": 150000000},
            {"stock_code": "000001", "stock_name": "平安银行", "current_price": 12.30, 
             "change_pct": -1.2, "turnover": 200000000},
        ]
        print("\n【每日摘要格式化】")
        print(format_daily_summary(stocks))
        
        # 测试预警格式化
        alert = {
            "type": "价格预警",
            "level": "warning",
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "message": "股价突破20日均线",
            "timestamp": "10:15:00"
        }
        print("\n【预警消息格式化】")
        print(format_alert(alert))
        
        # 测试推送类实例化
        print("\n【测试推送类实例化】")
        
        # 微信推送器
        wechat = WeChatNotifier()
        print(f"微信推送器: 可用={wechat._available}")
        
        # 飞书推送器
        feishu = FeishuNotifier("https://open.feishu.cn/open-apis/bot/v2/hook/xxx")
        print(f"飞书推送器: 已创建")
        
        # Telegram推送器
        telegram = TelegramNotifier("123456:ABC-DEF", "123456789")
        print(f"Telegram推送器: 已创建")
        
        # 钉钉推送器
        dingtalk = DingTalkNotifier("https://oapi.dingtalk.com/robot/send?access_token=xxx")
        print(f"钉钉推送器: 已创建")
        
        # 邮件推送器
        email = EmailNotifier("sender@qq.com", "password")
        print(f"邮件推送器: 已创建")
        
        # 测试统一推送管理器
        print("\n【测试统一推送管理器】")
        manager = NotificationManager()
        manager.add_feishu("https://open.feishu.cn/open-apis/bot/v2/hook/xxx")
        manager.add_telegram("123456:ABC-DEF", "123456789")
        manager.add_dingtalk("https://oapi.dingtalk.com/robot/send?access_token=xxx")
        manager.add_email("sender@qq.com", "password", receivers=["receiver@qq.com"])
        
        print(f"已配置渠道: {manager.get_channels()}")
        print(f"推送功能启用: {manager.is_enabled()}")
        
        # 如果需要实际测试发送，取消下面的注释
        # results = await manager.broadcast("测试消息")
        # print(f"广播结果: {results}")
        
        print("\n" + "=" * 50)
        print("测试完成！")
        print("=" * 50)
    
    asyncio.run(test())

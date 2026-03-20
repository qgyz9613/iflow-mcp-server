# -*- coding: utf-8 -*-
"""
股票定时监控调度模块 - StockScheduler

功能：
1. 定时任务调度（盘前总结、早盘跟踪、尾盘观察等）
2. 交易时间判断
3. 监控股票列表管理
4. 与微信推送联动

使用：
    from stock_scheduler import StockScheduler
    
    scheduler = StockScheduler(system)
    scheduler.add_watch("600519")
    scheduler.start()
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from stock_system import StockDecisionSystem

logger = logging.getLogger(__name__)


# ============== 配置 ==============

@dataclass
class SchedulerConfig:
    """调度器配置"""
    enabled: bool = True
    watch_list: List[str] = field(default_factory=list)
    push_enabled: bool = True
    push_contact: str = "文件传输助手"
    
    # 定时任务时间
    pre_market_time: str = "09:00"      # 盘前总结
    morning_track_time: str = "10:00"   # 早盘跟踪
    morning_summary_time: str = "11:30" # 上午总结
    afternoon_open_time: str = "13:30"  # 下午开盘
    late_afternoon_time: str = "14:45"  # 尾盘观察
    daily_close_time: str = "15:30"     # 收盘记录


# ============== 交易时间判断 ==============

def is_trading_time(dt: Optional[datetime] = None) -> bool:
    """
    判断是否为交易时间
    
    交易时间：
    - 上午：9:30 - 11:30
    - 下午：13:00 - 15:00
    - 周末休市
    """
    if dt is None:
        dt = datetime.now()
    
    # 周末休市
    if dt.weekday() >= 5:
        return False
    
    current_time = dt.time()
    
    # 上午交易时间
    morning_start = time(9, 30)
    morning_end = time(11, 30)
    
    # 下午交易时间
    afternoon_start = time(13, 0)
    afternoon_end = time(15, 0)
    
    # 使用 < 而非 <=，收盘时那一秒不算交易时间
    # 注意：结束时间用 < 排除，确保11:30:00和15:00:00不算交易时间
    return (morning_start <= current_time < morning_end or
            afternoon_start <= current_time < afternoon_end)


def is_pre_market(dt: Optional[datetime] = None) -> bool:
    """判断是否为盘前时间（9:00-9:30）"""
    if dt is None:
        dt = datetime.now()
    if dt.weekday() >= 5:
        return False
    return time(9, 0) <= dt.time() < time(9, 30)


def is_after_hours(dt: Optional[datetime] = None) -> bool:
    """判断是否为盘后时间（15:00之后）"""
    if dt is None:
        dt = datetime.now()
    if dt.weekday() >= 5:
        return True
    return dt.time() >= time(15, 0)


def get_next_trading_day(dt: Optional[datetime] = None) -> datetime:
    """获取下一个交易日"""
    if dt is None:
        dt = datetime.now()
    
    next_day = dt + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.replace(hour=9, minute=30, second=0, microsecond=0)


# ============== 定时任务 ==============

class StockScheduler:
    """
    股票定时监控调度器
    
    功能：
    - 定时执行分析任务
    - 管理监控股票列表
    - 与微信推送联动
    """
    
    def __init__(
        self,
        system: Optional['StockDecisionSystem'] = None,
        config: Optional[SchedulerConfig] = None
    ):
        self.system = system
        self.config = config or SchedulerConfig()
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
        # 尝试导入微信推送
        try:
            from stock_notifier import WeChatNotifier
            self.notifier = WeChatNotifier()
        except ImportError:
            self.notifier = None
            logger.warning("微信推送模块未加载")
    
    def add_watch(self, stock_code: str) -> None:
        """添加监控股票"""
        if stock_code not in self.config.watch_list:
            self.config.watch_list.append(stock_code)
            logger.info(f"添加监控: {stock_code}")
    
    def remove_watch(self, stock_code: str) -> None:
        """移除监控股票"""
        if stock_code in self.config.watch_list:
            self.config.watch_list.remove(stock_code)
            logger.info(f"移除监控: {stock_code}")
    
    def set_watch_list(self, stocks: List[str]) -> None:
        """设置监控列表"""
        self.config.watch_list = stocks
        logger.info(f"设置监控列表: {stocks}")
    
    # ============== 定时任务定义 ==============
    
    async def pre_market_summary(self) -> Dict[str, Any]:
        """
        盘前总结 (09:00)
        
        内容：
        - 昨日回顾
        - 新闻收集
        - 今日预测
        """
        # 检查是否为交易日
        now = datetime.now()
        if now.weekday() >= 5:
            logger.info("周末休市，跳过盘前总结")
            return {"task": "pre_market_summary", "skipped": "周末休市"}
        
        logger.info("执行盘前总结...")
        
        results = {
            "task": "pre_market_summary",
            "time": datetime.now().isoformat(),
            "watch_list": self.config.watch_list,
            "analysis": {}
        }
        
        if self.system and self.config.watch_list:
            for stock in self.config.watch_list:
                try:
                    # 获取分析结果
                    analysis = await self.system.analyze(stock)
                    results["analysis"][stock] = {
                        "decision": str(analysis.final_decision.action) if analysis.final_decision else "N/A",
                        "confidence": analysis.final_decision.confidence if analysis.final_decision else 0,
                    }
                except Exception as e:
                    results["analysis"][stock] = {"error": str(e)}
        
        # 推送消息
        if self.config.push_enabled and self.notifier:
            message = self._format_pre_market_message(results)
            await self.notifier.send_message(self.config.push_contact, message)
        
        return results
    
    async def morning_tracking(self) -> Dict[str, Any]:
        """
        早盘跟踪 (10:00)
        
        内容：
        - 对比预测与实际走势
        """
        logger.info("执行早盘跟踪...")
        
        if not is_trading_time():
            return {"task": "morning_tracking", "skipped": "非交易时间"}
        
        results = {
            "task": "morning_tracking",
            "time": datetime.now().isoformat(),
            "tracking": {}
        }
        
        if self.system and self.config.watch_list:
            for stock in self.config.watch_list:
                try:
                    quote = await self.system.data_hub.get_realtime_quote(stock)
                    results["tracking"][stock] = quote.get("data", [{}])[0] if quote.get("success") else {}
                except Exception as e:
                    results["tracking"][stock] = {"error": str(e)}
        
        return results
    
    async def morning_summary(self) -> Dict[str, Any]:
        """
        上午总结 (11:30)
        
        内容：
        - 上午收盘情况
        """
        logger.info("执行上午总结...")
        
        results = {
            "task": "morning_summary",
            "time": datetime.now().isoformat(),
            "summary": {}
        }
        
        if self.system and self.config.watch_list:
            for stock in self.config.watch_list:
                try:
                    quote = await self.system.data_hub.get_realtime_quote(stock)
                    if quote.get("success") and quote.get("data"):
                        data = quote["data"][0]
                        results["summary"][stock] = {
                            "price": data.get("最新价"),
                            "change_pct": data.get("涨跌幅"),
                            "volume": data.get("成交量"),
                        }
                except Exception as e:
                    results["summary"][stock] = {"error": str(e)}
        
        # 推送消息
        if self.config.push_enabled and self.notifier:
            message = self._format_morning_summary_message(results)
            await self.notifier.send_message(self.config.push_contact, message)
        
        return results
    
    async def afternoon_open(self) -> Dict[str, Any]:
        """
        下午开盘预判 (13:30)
        
        内容：
        - 下午走势预判
        """
        logger.info("执行下午开盘预判...")
        
        if not is_trading_time():
            return {"task": "afternoon_open", "skipped": "非交易时间"}
        
        results = {
            "task": "afternoon_open",
            "time": datetime.now().isoformat(),
            "prediction": {}
        }
        
        if self.system and self.config.watch_list:
            for stock in self.config.watch_list:
                try:
                    analysis = await self.system.analyze(stock)
                    results["prediction"][stock] = {
                        "trend": str(analysis.market_regime) if analysis.market_regime else "unknown",
                        "signal": str(analysis.consolidated_signal.signal.value) if analysis.consolidated_signal else "neutral",
                    }
                except Exception as e:
                    results["prediction"][stock] = {"error": str(e)}
        
        return results
    
    async def late_afternoon(self) -> Dict[str, Any]:
        """
        尾盘观察 (14:45)
        
        内容：
        - 建仓/加仓建议
        - 止损提醒
        """
        logger.info("执行尾盘观察...")
        
        if not is_trading_time():
            return {"task": "late_afternoon", "skipped": "非交易时间"}
        
        results = {
            "task": "late_afternoon",
            "time": datetime.now().isoformat(),
            "suggestions": {}
        }
        
        if self.system and self.config.watch_list:
            for stock in self.config.watch_list:
                try:
                    decision = await self.system.make_decision(stock, capital=10000)
                    if decision:
                        results["suggestions"][stock] = {
                            "action": decision.action,
                            "confidence": decision.confidence,
                            "position": decision.position_size,
                            "stop_loss": decision.stop_loss,
                            "take_profit": decision.take_profit,
                        }
                except Exception as e:
                    results["suggestions"][stock] = {"error": str(e)}
        
        # 推送消息（重要！）
        if self.config.push_enabled and self.notifier:
            message = self._format_late_afternoon_message(results)
            await self.notifier.send_message(self.config.push_contact, message)
        
        return results
    
    async def daily_close_record(self) -> Dict[str, Any]:
        """
        收盘记录 (15:30)
        
        内容：
        - 34字段数据收集
        - 当日交易记录
        """
        logger.info("执行收盘记录...")
        
        results = {
            "task": "daily_close_record",
            "time": datetime.now().isoformat(),
            "records": {}
        }
        
        if self.system and self.config.watch_list:
            for stock in self.config.watch_list:
                try:
                    # 获取完整数据
                    quote = await self.system.data_hub.get_realtime_quote(stock)
                    fund_flow = await self.system.data_hub.get_fund_flow(stock)
                    
                    if quote.get("success") and quote.get("data"):
                        data = quote["data"][0]
                        fund = fund_flow.get("data", {})
                        
                        # 34字段记录
                        results["records"][stock] = {
                            # 基本信息
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "stock_code": stock,
                            "stock_name": data.get("名称", ""),
                            
                            # 价格信息
                            "pre_close": data.get("昨收"),
                            "open": data.get("今开"),
                            "close": data.get("最新价"),
                            "high": data.get("最高"),
                            "low": data.get("最低"),
                            "change_pct": data.get("涨跌幅"),
                            "amplitude": data.get("振幅"),
                            
                            # 成交信息
                            "volume": data.get("成交量"),
                            "amount": data.get("成交额"),
                            "turnover_rate": data.get("换手率"),
                            "volume_ratio": data.get("量比"),
                            
                            # 委托信息
                            "bid_volume": data.get("委买量"),
                            "ask_volume": data.get("委卖量"),
                            
                            # 估值信息
                            "pe": data.get("市盈率"),
                            "total_mv": data.get("总市值"),
                            "circ_mv": data.get("流通市值"),
                            
                            # 主力资金
                            "main_net_inflow": fund.get("main_net_inflow"),
                            "main_net_inflow_ratio": fund.get("main_net_inflow_ratio"),
                        }
                except Exception as e:
                    results["records"][stock] = {"error": str(e)}
        
        # 推送每日总结
        if self.config.push_enabled and self.notifier:
            message = self._format_daily_close_message(results)
            await self.notifier.send_message(self.config.push_contact, message)
        
        return results
    
    # ============== 消息格式化 ==============
    
    def _format_pre_market_message(self, results: Dict) -> str:
        """格式化盘前消息"""
        lines = ["【盘前总结】", f"时间: {results['time'][:16]}", ""]
        
        for stock, analysis in results.get("analysis", {}).items():
            if "error" not in analysis:
                lines.append(f"• {stock}: {analysis.get('decision')} ({analysis.get('confidence', 0):.0%})")
            else:
                lines.append(f"• {stock}: 获取失败")
        
        return "\n".join(lines)
    
    def _format_morning_summary_message(self, results: Dict) -> str:
        """格式化上午总结消息"""
        lines = ["【上午总结】", f"时间: {results['time'][:16]}", ""]
        
        for stock, data in results.get("summary", {}).items():
            if "error" not in data:
                change = data.get("change_pct", 0)
                emoji = "🔴" if change < 0 else "🟢" if change > 0 else "⚪"
                lines.append(f"• {stock}: {data.get('price')}元 {emoji}{change}%")
            else:
                lines.append(f"• {stock}: 获取失败")
        
        return "\n".join(lines)
    
    def _format_late_afternoon_message(self, results: Dict) -> str:
        """格式化尾盘消息"""
        lines = ["【尾盘建议】", f"时间: {results['time'][:16]}", ""]
        
        for stock, suggestion in results.get("suggestions", {}).items():
            if "error" not in suggestion:
                action = suggestion.get("action", "hold")
                action_emoji = {"buy": "🟢买入", "sell": "🔴卖出", "hold": "⚪持有"}.get(action, action)
                lines.append(f"• {stock}: {action_emoji}")
                lines.append(f"  止损: {suggestion.get('stop_loss', 0):.2f} 止盈: {suggestion.get('take_profit', 0):.2f}")
            else:
                lines.append(f"• {stock}: 获取失败")
        
        return "\n".join(lines)
    
    def _format_daily_close_message(self, results: Dict) -> str:
        """格式化收盘记录消息"""
        lines = ["【收盘记录】", f"日期: {datetime.now().strftime('%Y-%m-%d')}", ""]
        
        for stock, record in results.get("records", {}).items():
            if "error" not in record:
                change = record.get("change_pct", 0)
                emoji = "🔴" if change < 0 else "🟢" if change > 0 else "⚪"
                main_flow = record.get("main_net_inflow", 0)
                flow_emoji = "↑" if main_flow > 0 else "↓" if main_flow < 0 else "-"
                
                lines.append(f"• {record.get('stock_name', stock)}({stock})")
                lines.append(f"  收盘: {record.get('close')}元 {emoji}{change}%")
                lines.append(f"  主力: {flow_emoji}{abs(main_flow)/10000:.0f}万")
                lines.append("")
        
        return "\n".join(lines)
    
    # ============== 调度控制 ==============
    
    async def start(self, block: bool = True) -> None:
        """
        启动调度器
        
        Args:
            block: 是否阻塞等待。False时立即返回，调度器在后台运行
        """
        if self._running:
            logger.warning("调度器已在运行")
            return
        
        self._running = True
        logger.info("启动股票监控调度器...")
        
        # 创建定时任务
        self._tasks = [
            asyncio.create_task(self._schedule_task("pre_market", self.pre_market_summary, "09:00")),
            asyncio.create_task(self._schedule_task("morning_track", self.morning_tracking, "10:00")),
            asyncio.create_task(self._schedule_task("morning_summary", self.morning_summary, "11:30")),
            asyncio.create_task(self._schedule_task("afternoon_open", self.afternoon_open, "13:30")),
            asyncio.create_task(self._schedule_task("late_afternoon", self.late_afternoon, "14:45")),
            asyncio.create_task(self._schedule_task("daily_close", self.daily_close_record, "15:30")),
        ]
        
        # 根据block参数决定是否等待
        if block:
            await asyncio.gather(*self._tasks)
        # block=False时立即返回，调度器在后台运行
    
    async def stop(self) -> None:
        """停止调度器"""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        logger.info("调度器已停止")
    
    async def _schedule_task(
        self,
        name: str,
        func: Callable,
        time_str: str
    ) -> None:
        """
        调度单个任务
        
        Args:
            name: 任务名称
            func: 任务函数
            time_str: 执行时间 (HH:MM)
        """
        hour, minute = map(int, time_str.split(":"))
        
        while self._running:
            now = datetime.now()
            
            # 计算下次执行时间
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            
            # 跳过周末
            while next_run.weekday() >= 5:
                next_run += timedelta(days=1)
            
            # 等待到执行时间
            wait_seconds = (next_run - now).total_seconds()
            if wait_seconds > 0:
                logger.debug(f"任务 {name} 将在 {next_run} 执行")
                await asyncio.sleep(wait_seconds)
            
            # 执行任务
            if self._running:
                try:
                    await func()
                except asyncio.CancelledError:
                    logger.info(f"任务 {name} 已取消")
                    raise
                except Exception as e:
                    logger.error(f"任务 {name} 执行失败: {e}")


# ============== 便捷函数 ==============

def create_scheduler(
    watch_list: List[str] = None,
    push_enabled: bool = True,
    push_contact: str = "文件传输助手"
) -> StockScheduler:
    """
    创建调度器便捷函数
    
    Args:
        watch_list: 监控股票列表
        push_enabled: 是否启用推送
        push_contact: 推送联系人
    """
    config = SchedulerConfig(
        watch_list=watch_list or [],
        push_enabled=push_enabled,
        push_contact=push_contact
    )
    return StockScheduler(config=config)


# ============== 测试 ==============

if __name__ == "__main__":
    print("=== 股票监控调度器测试 ===")
    print()
    
    # 测试交易时间判断
    now = datetime.now()
    print(f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"是否交易时间: {is_trading_time()}")
    print(f"是否盘前: {is_pre_market()}")
    print(f"是否盘后: {is_after_hours()}")
    print()
    
    # 测试调度器创建
    scheduler = create_scheduler(
        watch_list=["600519", "000001"],
        push_enabled=False
    )
    print(f"监控列表: {scheduler.config.watch_list}")
    print()
    
    # 测试单个任务（同步版本）
    async def test_tasks():
        print("测试收盘记录...")
        result = await scheduler.daily_close_record()
        print(f"结果: {result}")
    
    asyncio.run(test_tasks())

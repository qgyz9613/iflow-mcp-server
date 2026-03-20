# -*- coding: utf-8 -*-
"""
缠论完整实现模块
参考 QjySDK ChanLun.cs

完整缠论体系：
K线包含处理 → 分型识别 → 笔 → 线段 → 中枢 → 背驰 → 买卖点

Author: iFlow CLI
Version: 1.0.0
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class Direction(Enum):
    """方向枚举"""
    UP = 1      # 向上
    DOWN = -1   # 向下
    NONE = 0    # 无方向


class FractalType(Enum):
    """分型类型"""
    TOP = 1         # 顶分型
    BOTTOM = -1     # 底分型
    NONE = 0        # 无分型


class BuySellPoint(Enum):
    """买卖点类型"""
    BUY_1 = 1       # 一买：趋势底背驰
    BUY_2 = 2       # 二买：次级别回踩不破
    BUY_3 = 3       # 三买：突破中枢回踩
    SELL_1 = -1     # 一卖：趋势顶背驰
    SELL_2 = -2     # 二卖：次级别反弹不破
    SELL_3 = -3     # 三卖：跌破中枢反弹


@dataclass
class KLine:
    """K线数据结构"""
    index: int          # 索引
    high: float         # 最高价
    low: float          # 最低价
    open: float         # 开盘价
    close: float        # 收盘价
    volume: float       # 成交量
    # 包含处理后的值
    processed_high: float = 0.0
    processed_low: float = 0.0
    # 分型标记
    fractal_type: FractalType = FractalType.NONE
    # 笔标记
    bi_index: int = -1  # 所属笔的索引
    # 线段标记
    segment_index: int = -1  # 所属线段的索引


@dataclass
class Bi:
    """笔数据结构"""
    index: int                      # 笔索引
    start_index: int                # 起始K线索引
    end_index: int                  # 结束K线索引
    direction: Direction            # 方向
    start_price: float              # 起始价格
    end_price: float                # 结束价格
    high: float                     # 笔的最高价
    low: float                      # 笔的最低价
    length: float = 0.0             # 笔的长度（价格幅度）
    # 内部结构
    internal_fenxing_count: int = 0  # 内部分型数量


@dataclass
class Segment:
    """线段数据结构"""
    index: int                      # 线段索引
    start_index: int                # 起始笔索引
    end_index: int                  # 结束笔索引
    direction: Direction            # 方向
    start_price: float              # 起始价格
    end_price: float                # 结束价格
    high: float                     # 线段最高价
    low: float                      # 线段最低价
    bi_list: List[Bi] = field(default_factory=list)  # 包含的笔


@dataclass
class ZhongShu:
    """中枢数据结构"""
    index: int                      # 中枢索引
    start_index: int                # 起始索引（笔或线段）
    end_index: int                  # 结束索引
    zg: float                       # 中枢下沿（ZG）
    zd: float                       # 中枢上沿（ZD）
    gg: float                       # 中枢最高点（GG）
    dd: float                       # 中枢最低点（DD）
    zs_level: int = 1               # 中枢级别（1=1分钟级，2=5分钟级...）
    direction: Direction = Direction.NONE  # 中枢延伸方向
    # 中枢属性
    is_valid: bool = True           # 是否有效
    extension_count: int = 0        # 延伸次数


@dataclass
class BeiChi:
    """背驰数据结构"""
    index: int                      # 背驰点索引
    bei_chi_type: int               # 背驰类型（1=趋势背驰，2=盘整背驰）
    direction: Direction            # 方向（向上背驰/向下背驰）
    macd_height1: float             # 第一段MACD高度
    macd_height2: float             # 第二段MACD高度
    price_height1: float            # 第一段价格幅度
    price_height2: float            # 第二段价格幅度
    is_divergence: bool             # 是否背驰
    strength: float                 # 背驰强度（0-1）


@dataclass
class TradingPoint:
    """买卖点数据结构"""
    index: int                      # 买卖点索引
    point_type: BuySellPoint        # 买卖点类型
    price: float                    # 价格
    direction: Direction            # 方向
    bei_chi: Optional[BeiChi]       # 关联的背驰
    zhongshu: Optional[ZhongShu]    # 关联的中枢
    confidence: float = 0.5         # 置信度


class ChanLunAnalyzer:
    """
    缠论分析器
    
    完整实现缠论分析体系：
    1. K线包含处理
    2. 分型识别（顶分型/底分型）
    3. 笔的划分
    4. 线段的划分
    5. 中枢的识别
    6. 背驰的判断
    7. 买卖点的确定
    """
    
    def __init__(self):
        self.klines: List[KLine] = []
        self.bi_list: List[Bi] = []
        self.segment_list: List[Segment] = []
        self.zhongshu_list: List[ZhongShu] = []
        self.beichi_list: List[BeiChi] = []
        self.trading_points: List[TradingPoint] = []
        
    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        完整缠论分析
        
        Args:
            df: K线数据，需包含 high, low, open, close, volume 列
            
        Returns:
            分析结果字典
        """
        # 1. 初始化K线
        self._init_klines(df)
        
        # 2. K线包含处理
        self._process_contain()
        
        # 3. 分型识别
        self._identify_fractals()
        
        # 4. 笔的划分
        self._divide_bi()
        
        # 5. 线段的划分
        self._divide_segment()
        
        # 6. 中枢识别
        self._identify_zhongshu()
        
        # 7. 背驰判断
        self._identify_beichi(df)
        
        # 8. 买卖点确定
        self._identify_trading_points()
        
        return self._get_result()
    
    def _init_klines(self, df: pd.DataFrame):
        """初始化K线数据"""
        # 问题4修复：检查输入数据空值/NaN
        if df is None or df.empty:
            raise ValueError("输入数据不能为空")
        
        required_cols = ['high', 'low']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"缺少必需列: {col}")
        
        # 检查NaN值并清理
        original_len = len(df)
        df = df.dropna(subset=required_cols)
        if len(df) < original_len:
            logger.warning(f"移除了 {original_len - len(df)} 行包含NaN的数据")
        
        if len(df) == 0:
            raise ValueError("清理NaN后数据为空")
        
        self.klines = []
        for i, row in df.iterrows():
            kl = KLine(
                index=i,
                high=row['high'],
                low=row['low'],
                open=row.get('open', row['high']),
                close=row.get('close', row['low']),
                volume=row.get('volume', 0)
            )
            kl.processed_high = kl.high
            kl.processed_low = kl.low
            self.klines.append(kl)
    
    def _process_contain(self):
        """
        K线包含处理
        
        包含关系定义：
        当一根K线的高低点完全包含在另一根K线内时，需要合并处理
        
        处理规则：
        - 向上趋势：取高高、取高低
        - 向下趋势：取低高、取低低
        """
        if len(self.klines) < 2:
            return
            
        direction = Direction.NONE  # 当前趋势方向
        
        for i in range(1, len(self.klines)):
            prev = self.klines[i - 1]
            curr = self.klines[i]
            
            # 判断是否有包含关系
            if self._has_contain(prev, curr):
                # 确定处理方向
                if direction == Direction.NONE:
                    # 根据前两根K线确定方向
                    if i >= 2:
                        prev2 = self.klines[i - 2]
                        if prev2.processed_high < prev.processed_high:
                            direction = Direction.UP
                        else:
                            direction = Direction.DOWN
                    else:
                        if curr.high > prev.high:
                            direction = Direction.UP
                        else:
                            direction = Direction.DOWN
                
                # 合并K线
                if direction == Direction.UP:
                    # 向上趋势：取高高、取高低
                    curr.processed_high = max(prev.processed_high, curr.high)
                    curr.processed_low = max(prev.processed_low, curr.low)
                else:
                    # 向下趋势：取低高、取低低
                    curr.processed_high = min(prev.processed_high, curr.high)
                    curr.processed_low = min(prev.processed_low, curr.low)
            else:
                # 无包含关系，重置方向
                if curr.high > prev.processed_high:
                    direction = Direction.UP
                elif curr.low < prev.processed_low:
                    direction = Direction.DOWN
                else:
                    direction = Direction.NONE
    
    def _has_contain(self, k1: KLine, k2: KLine) -> bool:
        """判断两根K线是否有包含关系"""
        # K1包含K2
        if k1.processed_high >= k2.high and k1.processed_low <= k2.low:
            return True
        # K2包含K1
        if k2.high >= k1.processed_high and k2.low <= k1.processed_low:
            return True
        return False
    
    def _identify_fractals(self):
        """
        分型识别
        
        顶分型定义：
        中间K线的高点和低点都比左右两根K线高
        
        底分型定义：
        中间K线的高点和低点都比左右两根K线低
        """
        if len(self.klines) < 3:
            return
            
        for i in range(1, len(self.klines) - 1):
            prev = self.klines[i - 1]
            curr = self.klines[i]
            next_k = self.klines[i + 1]
            
            # 使用处理后的高低点
            # 顶分型
            if (curr.processed_high > prev.processed_high and 
                curr.processed_high > next_k.processed_high and
                curr.processed_low > prev.processed_low and
                curr.processed_low > next_k.processed_low):
                curr.fractal_type = FractalType.TOP
                
            # 底分型
            elif (curr.processed_low < prev.processed_low and 
                  curr.processed_low < next_k.processed_low and
                  curr.processed_high < prev.processed_high and
                  curr.processed_high < next_k.processed_high):
                curr.fractal_type = FractalType.BOTTOM
    
    def _divide_bi(self):
        """
        笔的划分
        
        笔的定义：
        从一个分型到另一个相反分型的过程
        
        笔的条件：
        1. 必须从顶分型到底分型（或相反）
        2. 中间必须有至少1根独立K线
        3. 笔的长度必须足够（至少3根K线）
        """
        self.bi_list = []
        
        # 找出所有分型点
        fenxing_list = []
        for i, kl in enumerate(self.klines):
            if kl.fractal_type != FractalType.NONE:
                fenxing_list.append((i, kl))
        
        if len(fenxing_list) < 2:
            return
        
        # 划分笔
        bi_start = fenxing_list[0]
        last_type = fenxing_list[0][1].fractal_type
        
        for i in range(1, len(fenxing_list)):
            idx, kl = fenxing_list[i]
            
            # 分型类型必须相反
            if kl.fractal_type == last_type:
                # 同类型分型，判断是否需要更新
                if last_type == FractalType.TOP:
                    if kl.processed_high > bi_start[1].processed_high:
                        bi_start = (idx, kl)
                else:
                    if kl.processed_low < bi_start[1].processed_low:
                        bi_start = (idx, kl)
                continue
            
            # 问题1修复：缠论中笔至少需要4根K线（两端分型K线+中间至少1根独立K线）
            # 原: if idx - bi_start[0] < 3: 错误，应为 < 4
            if idx - bi_start[0] < 4:
                # 不满足笔的条件：两端各1根分型K线，中间至少1根独立K线，共3根间距
                # idx - bi_start[0] 是K线数量差，需 >= 3 才能保证4根K线
                continue
            
            # 创建笔
            direction = Direction.UP if last_type == FractalType.BOTTOM else Direction.DOWN
            
            bi = Bi(
                index=len(self.bi_list),
                start_index=bi_start[0],
                end_index=idx,
                direction=direction,
                start_price=bi_start[1].processed_low if direction == Direction.UP else bi_start[1].processed_high,
                end_price=kl.processed_high if direction == Direction.UP else kl.processed_low,
                high=max(bi_start[1].processed_high, kl.processed_high),
                low=min(bi_start[1].processed_low, kl.processed_low),
                length=abs(kl.processed_high - bi_start[1].processed_low) if direction == Direction.UP 
                       else abs(bi_start[1].processed_high - kl.processed_low)
            )
            
            # 标记K线所属笔
            for j in range(bi_start[0], idx + 1):
                self.klines[j].bi_index = bi.index
            
            self.bi_list.append(bi)
            
            # 更新下一个笔的起点
            bi_start = (idx, kl)
            last_type = kl.fractal_type
    
    def _divide_segment(self):
        """
        线段的划分
        
        线段定义：
        由至少3笔组成，且笔的方向一致
        
        线段的破坏：
        当出现一笔反向笔且不创新高/新低时，线段结束
        
        问题2修复：记录线段极值，判断破坏时与线段极值比较
        """
        if len(self.bi_list) < 3:
            return
        
        self.segment_list = []
        segment_start = 0
        segment_direction = self.bi_list[0].direction
        # 问题2修复：记录线段极值
        segment_high = self.bi_list[0].high
        segment_low = self.bi_list[0].low
        
        for i in range(1, len(self.bi_list)):
            bi = self.bi_list[i]
            
            # 更新线段极值
            segment_high = max(segment_high, bi.high)
            segment_low = min(segment_low, bi.low)
            
            # 检查线段破坏
            if bi.direction != segment_direction:
                # 反向笔出现，检查是否破坏线段
                if segment_direction == Direction.UP:
                    # 向上线段，检查是否跌破线段最低点
                    # 问题2修复：与线段极值比较，而非相邻笔
                    if bi.low < segment_low:
                        # 破坏了线段，结束当前线段
                        self._create_segment(segment_start, i - 1, segment_direction)
                        segment_start = i - 1
                        segment_direction = Direction.DOWN
                        segment_high = bi.high
                        segment_low = bi.low
                else:
                    # 向下线段，检查是否突破线段最高点
                    # 问题2修复：与线段极值比较，而非相邻笔
                    if bi.high > segment_high:
                        # 破坏了线段
                        self._create_segment(segment_start, i - 1, segment_direction)
                        segment_start = i - 1
                        segment_direction = Direction.UP
                        segment_high = bi.high
                        segment_low = bi.low
        
        # 创建最后一个线段
        if segment_start < len(self.bi_list) - 1:
            self._create_segment(segment_start, len(self.bi_list) - 1, segment_direction)
    
    def _create_segment(self, start_idx: int, end_idx: int, direction: Direction):
        """创建线段"""
        bi_subset = self.bi_list[start_idx:end_idx + 1]
        
        segment = Segment(
            index=len(self.segment_list),
            start_index=start_idx,
            end_index=end_idx,
            direction=direction,
            start_price=bi_subset[0].start_price,
            end_price=bi_subset[-1].end_price,
            high=max(b.high for b in bi_subset),
            low=min(b.low for b in bi_subset),
            bi_list=bi_subset
        )
        
        # 标记笔所属线段
        for bi in bi_subset:
            bi.segment_index = segment.index
        
        self.segment_list.append(segment)
    
    def _identify_zhongshu(self):
        """
        中枢识别
        
        中枢定义：
        至少3个连续的笔（或线段），其价格区间有重叠部分
        
        中枢区间：
        ZG（中枢下沿）= max(各笔的低点)
        ZD（中枢上沿）= min(各笔的高点)
        GG（中枢最高点）= max(各笔的高点)
        DD（中枢最低点）= min(各笔的低点)
        """
        if len(self.bi_list) < 3:
            return
        
        self.zhongshu_list = []
        
        # 使用笔来识别中枢
        i = 0
        while i < len(self.bi_list) - 2:
            # 检查连续3笔是否构成中枢
            b1, b2, b3 = self.bi_list[i], self.bi_list[i+1], self.bi_list[i+2]
            
            # 计算重叠区间
            zg = max(b1.low, b2.low, b3.low)  # 中枢下沿（三个低点的最大值）
            zd = min(b1.high, b2.high, b3.high)  # 中枢上沿（三个高点的最小值）
            
            if zg < zd:  # 有重叠
                gg = max(b1.high, b2.high, b3.high)
                dd = min(b1.low, b2.low, b3.low)
                
                zs = ZhongShu(
                    index=len(self.zhongshu_list),
                    start_index=i,
                    end_index=i + 2,
                    zg=zg,
                    zd=zd,
                    gg=gg,
                    dd=dd,
                    zs_level=1
                )
                
                # 尝试延伸中枢
                j = i + 3
                while j < len(self.bi_list):
                    bi = self.bi_list[j]
                    new_zg = max(zs.zg, bi.low)
                    new_zd = min(zs.zd, bi.high)
                    
                    if new_zg < new_zd:  # 可以延伸
                        zs.end_index = j
                        zs.zg = new_zg
                        zs.zd = new_zd
                        zs.gg = max(zs.gg, bi.high)
                        zs.dd = min(zs.dd, bi.low)
                        zs.extension_count += 1
                        j += 1
                    else:
                        break
                
                self.zhongshu_list.append(zs)
                i = j  # 跳过已处理的笔
            else:
                i += 1
    
    def _identify_beichi(self, df: pd.DataFrame):
        """
        背驰判断
        
        背驰定义：
        趋势力度减弱，价格创新高/新低但MACD不创新高/新低
        
        背驰类型：
        1. 趋势背驰：两个同向趋势段比较
        2. 盘整背驰：盘整区间内比较
        """
        if len(self.segment_list) < 2 or 'close' not in df.columns:
            return
        
        self.beichi_list = []
        
        # 计算MACD
        try:
            close = df['close'].values
            ema12 = pd.Series(close).ewm(span=12, adjust=False).mean()
            ema26 = pd.Series(close).ewm(span=26, adjust=False).mean()
            dif = ema12 - ema26
            dea = dif.ewm(span=9, adjust=False).mean()
            macd = (dif - dea) * 2
        except Exception:
            return
        
        # 分析每个线段
        for i in range(1, len(self.segment_list)):
            prev_seg = self.segment_list[i - 1]
            curr_seg = self.segment_list[i]
            
            # 只比较同向线段
            if prev_seg.direction != curr_seg.direction:
                continue
            
            # 获取两个线段的MACD面积
            prev_macd_sum = self._get_macd_area(prev_seg, macd)
            curr_macd_sum = self._get_macd_area(curr_seg, macd)
            
            # 获取价格幅度
            prev_price_range = abs(prev_seg.end_price - prev_seg.start_price)
            curr_price_range = abs(curr_seg.end_price - curr_seg.start_price)
            
            # 判断背驰
            is_divergence = False
            if curr_seg.direction == Direction.UP:
                # 向上线段，价格创新高但MACD不创新高
                if curr_seg.end_price > prev_seg.end_price and curr_macd_sum < prev_macd_sum:
                    is_divergence = True
            else:
                # 向下线段，价格创新低但MACD不创新低
                if curr_seg.end_price < prev_seg.end_price and abs(curr_macd_sum) < abs(prev_macd_sum):
                    is_divergence = True
            
            if is_divergence:
                bei_chi = BeiChi(
                    index=len(self.beichi_list),
                    bei_chi_type=1,  # 趋势背驰
                    direction=Direction.DOWN if curr_seg.direction == Direction.UP else Direction.UP,
                    macd_height1=prev_macd_sum,
                    macd_height2=curr_macd_sum,
                    price_height1=prev_price_range,
                    price_height2=curr_price_range,
                    is_divergence=True,
                    strength=min(1.0, abs(prev_macd_sum - curr_macd_sum) / max(abs(prev_macd_sum), 0.0001))
                )
                self.beichi_list.append(bei_chi)
    
    def _get_macd_area(self, segment: Segment, macd: pd.Series) -> float:
        """计算线段区间的MACD面积"""
        try:
            start_idx = self.bi_list[segment.start_index].start_index
            end_idx = self.bi_list[segment.end_index].end_index
            macd_values = macd.iloc[start_idx:end_idx + 1]
            return float(macd_values.sum())
        except Exception:
            return 0.0
    
    def _identify_trading_points(self):
        """
        买卖点确定
        
        一买：趋势底背驰后的第一个底分型
        一卖：趋势顶背驰后的第一个顶分型
        二买：一买后，次级别回踩不破一买点的底分型
        二卖：一卖后，次级别反弹不破一卖点的顶分型
        三买：突破中枢后回踩不破中枢上沿的底分型
        三卖：跌破中枢后反弹不破中枢下沿的顶分型
        """
        self.trading_points = []
        
        # 根据背驰找一买一卖
        for bc in self.beichi_list:
            # 找到背驰点附近的分型
            seg = self.segment_list[-1] if self.segment_list else None
            if seg is None:
                continue
            
            # 问题3修复：seg.end_index是笔的索引，需转换为K线索引
            # 使用 self.bi_list[seg.end_index].end_index 获取K线索引
            try:
                kline_end_index = self.bi_list[seg.end_index].end_index
            except (IndexError, AttributeError):
                kline_end_index = seg.end_index
            
            # 确保索引在有效范围内
            kline_end_index = min(kline_end_index, len(self.klines) - 1)
                
            # 一买：向下背驰（预示上涨）
            if bc.direction == Direction.UP:
                # 找最近的底分型
                for kl in reversed(self.klines[:kline_end_index + 1]):
                    if kl.fractal_type == FractalType.BOTTOM:
                        tp = TradingPoint(
                            index=len(self.trading_points),
                            point_type=BuySellPoint.BUY_1,
                            price=kl.processed_low,
                            direction=Direction.UP,
                            bei_chi=bc,
                            zhongshu=None,
                            confidence=bc.strength
                        )
                        self.trading_points.append(tp)
                        break
            
            # 一卖：向上背驰（预示下跌）
            elif bc.direction == Direction.DOWN:
                for kl in reversed(self.klines[:kline_end_index + 1]):
                    if kl.fractal_type == FractalType.TOP:
                        tp = TradingPoint(
                            index=len(self.trading_points),
                            point_type=BuySellPoint.SELL_1,
                            price=kl.processed_high,
                            direction=Direction.DOWN,
                            bei_chi=bc,
                            zhongshu=None,
                            confidence=bc.strength
                        )
                        self.trading_points.append(tp)
                        break
        
        # 根据中枢找三买三卖
        for zs in self.zhongshu_list:
            # 找中枢后的突破
            if zs.end_index >= len(self.bi_list) - 1:
                continue
            
            # 检查是否有突破
            after_bi_list = self.bi_list[zs.end_index + 1:]
            for bi in after_bi_list:
                # 向上突破中枢
                if bi.direction == Direction.UP and bi.high > zs.zd:
                    # 三买：回踩不破中枢上沿
                    for next_bi in after_bi_list[after_bi_list.index(bi) + 1:]:
                        if next_bi.direction == Direction.DOWN:
                            if next_bi.low > zs.zg:  # 不破中枢下沿
                                tp = TradingPoint(
                                    index=len(self.trading_points),
                                    point_type=BuySellPoint.BUY_3,
                                    price=next_bi.low,
                                    direction=Direction.UP,
                                    bei_chi=None,
                                    zhongshu=zs,
                                    confidence=0.7
                                )
                                self.trading_points.append(tp)
                            break
                    break
                
                # 向下跌破中枢
                elif bi.direction == Direction.DOWN and bi.low < zs.zg:
                    # 三卖：反弹不破中枢下沿
                    for next_bi in after_bi_list[after_bi_list.index(bi) + 1:]:
                        if next_bi.direction == Direction.UP:
                            if next_bi.high < zs.zd:  # 不破中枢上沿
                                tp = TradingPoint(
                                    index=len(self.trading_points),
                                    point_type=BuySellPoint.SELL_3,
                                    price=next_bi.high,
                                    direction=Direction.DOWN,
                                    bei_chi=None,
                                    zhongshu=zs,
                                    confidence=0.7
                                )
                                self.trading_points.append(tp)
                            break
                    break
    
    def _get_result(self) -> Dict[str, Any]:
        """获取分析结果"""
        # 统计信息
        top_count = sum(1 for kl in self.klines if kl.fractal_type == FractalType.TOP)
        bottom_count = sum(1 for kl in self.klines if kl.fractal_type == FractalType.BOTTOM)
        
        # 当前趋势
        current_trend = Direction.NONE
        if self.segment_list:
            current_trend = self.segment_list[-1].direction
        
        # 当前中枢
        current_zs = None
        if self.zhongshu_list:
            current_zs = self.zhongshu_list[-1]
        
        # 最新买卖点
        latest_buy_point = None
        latest_sell_point = None
        for tp in reversed(self.trading_points):
            if tp.point_type.value > 0 and latest_buy_point is None:
                latest_buy_point = tp
            elif tp.point_type.value < 0 and latest_sell_point is None:
                latest_sell_point = tp
            if latest_buy_point and latest_sell_point:
                break
        
        return {
            'success': True,
            'kline_count': len(self.klines),
            'bi_count': len(self.bi_list),
            'segment_count': len(self.segment_list),
            'zhongshu_count': len(self.zhongshu_list),
            'beichi_count': len(self.beichi_list),
            'trading_point_count': len(self.trading_points),
            'fractal_stats': {
                'top_count': top_count,
                'bottom_count': bottom_count
            },
            'current_trend': current_trend.name,
            'current_zhongshu': {
                'zg': current_zs.zg,
                'zd': current_zs.zd,
                'gg': current_zs.gg,
                'dd': current_zs.dd
            } if current_zs else None,
            'latest_buy_point': {
                'type': latest_buy_point.point_type.name,
                'price': latest_buy_point.price,
                'confidence': latest_buy_point.confidence
            } if latest_buy_point else None,
            'latest_sell_point': {
                'type': latest_sell_point.point_type.name,
                'price': latest_sell_point.price,
                'confidence': latest_sell_point.confidence
            } if latest_sell_point else None,
            'bi_list': [{
                'index': bi.index,
                'direction': bi.direction.name,
                'start_price': bi.start_price,
                'end_price': bi.end_price,
                'length': bi.length
            } for bi in self.bi_list[-10:]],  # 最近10笔
            'trading_points': [{
                'type': tp.point_type.name,
                'price': tp.price,
                'confidence': tp.confidence
            } for tp in self.trading_points[-5:]]  # 最近5个买卖点
        }
    
    def get_current_signal(self) -> Dict[str, Any]:
        """获取当前交易信号"""
        result = self._get_result()
        
        signal = {
            'action': 'hold',
            'confidence': 0.0,
            'reason': ''
        }
        
        # 有最新买点
        if result['latest_buy_point']:
            buy = result['latest_buy_point']
            signal['action'] = 'buy'
            signal['confidence'] = buy['confidence']
            signal['reason'] = f"缠论{buy['type']}信号，价格{buy['price']:.2f}"
        
        # 有最新卖点
        elif result['latest_sell_point']:
            sell = result['latest_sell_point']
            signal['action'] = 'sell'
            signal['confidence'] = sell['confidence']
            signal['reason'] = f"缠论{sell['type']}信号，价格{sell['price']:.2f}"
        
        return signal


# 便捷函数
def analyze_chanlun(df: pd.DataFrame) -> Dict[str, Any]:
    """快速缠论分析"""
    analyzer = ChanLunAnalyzer()
    return analyzer.analyze(df)


def get_chanlun_signal(df: pd.DataFrame) -> Dict[str, Any]:
    """获取缠论交易信号"""
    analyzer = ChanLunAnalyzer()
    analyzer.analyze(df)
    return analyzer.get_current_signal()


if __name__ == '__main__':
    # 测试代码
    import numpy as np
    
    # 生成测试数据
    np.random.seed(42)
    n = 100
    close = 10 + np.cumsum(np.random.randn(n) * 0.1)
    high = close + np.random.rand(n) * 0.5
    low = close - np.random.rand(n) * 0.5
    open_ = close + np.random.randn(n) * 0.2
    
    df = pd.DataFrame({
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': np.random.randint(1000, 10000, n)
    })
    
    # 分析
    result = analyze_chanlun(df)
    print(f"缠论分析结果: {result}")

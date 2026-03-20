"""
A股选股模块 - 合并版
整合以下模块:
- stock_selector_10pct.py (10%涨幅选股)
- stock_predictor_10pct.py (预测器)
- tech_mainline_selection.py (技术主线选股)

特性:
- 只选主板股票 (60/00/002开头)
- 多维度评分选股
- 支持模型预测
- 技术形态筛选
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import asyncio
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from consolidated.data_sources import AStockDataSource
except ImportError:
    # 独立运行时的导入
    pass


class AStockPicker:
    """A股选股器"""
    
    # 主板前缀
    MAINBOARD_PREFIX = ['60', '00', '002']
    
    def __init__(self, model_path: Optional[str] = None):
        """
        初始化选股器
        
        Args:
            model_path: 模型路径
        """
        self.model = None
        self.feature_cols = []
        self.data_source = None
        
        if model_path:
            self.load_model(model_path)
    
    def load_model(self, path: str) -> bool:
        """加载模型"""
        try:
            from catboost import CatBoostClassifier
            self.model = CatBoostClassifier()
            self.model.load_model(path)
            
            # 加载特征列表
            import json
            meta_path = path.replace('.cbm', '_meta.json')
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
                    self.feature_cols = meta.get('feature_cols', [])
            
            return True
        except Exception as e:
            print(f"加载模型失败: {e}")
            return False
    
    def is_mainboard(self, code: str) -> bool:
        """判断是否主板股票"""
        code = str(code).replace("sh", "").replace("sz", "").zfill(6)
        
        # 排除ST
        if 'ST' in code:
            return False
        
        # 检查主板前缀
        for prefix in self.MAINBOARD_PREFIX:
            if code.startswith(prefix):
                return True
        return False
    
    def filter_mainboard(self, stocks: List[Dict]) -> List[Dict]:
        """过滤主板股票"""
        return [s for s in stocks if self.is_mainboard(s.get('code', ''))]
    
    # ==================== 技术指标计算 ====================
    
    def calculate_ma(self, prices: pd.Series, periods: List[int] = [5, 10, 20, 60]) -> pd.DataFrame:
        """计算移动平均线"""
        result = {}
        for p in periods:
            result[f'MA{p}'] = prices.rolling(p).mean()
        return pd.DataFrame(result)
    
    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """计算RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def calculate_macd(self, prices: pd.Series) -> pd.DataFrame:
        """计算MACD"""
        ema12 = prices.ewm(span=12, adjust=False).mean()
        ema26 = prices.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd = (dif - dea) * 2
        
        return pd.DataFrame({
            'MACD_DIF': dif,
            'MACD_DEA': dea,
            'MACD': macd,
        })
    
    def calculate_kdj(self, high: pd.Series, low: pd.Series, close: pd.Series, 
                      n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
        """计算KDJ"""
        llv = low.rolling(n).min()
        hhv = high.rolling(n).max()
        
        rsv = (close - llv) / (hhv - llv) * 100
        rsv = rsv.fillna(50)
        
        k = rsv.ewm(span=m1, adjust=False).mean()
        d = k.ewm(span=m2, adjust=False).mean()
        j = 3 * k - 2 * d
        
        return pd.DataFrame({'K': k, 'D': d, 'J': j})
    
    def calculate_bollinger(self, prices: pd.Series, period: int = 20, 
                           std_dev: float = 2) -> pd.DataFrame:
        """计算布林带"""
        mid = prices.rolling(period).mean()
        std = prices.rolling(period).std()
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        
        return pd.DataFrame({
            'BB_Mid': mid,
            'BB_Upper': upper,
            'BB_Lower': lower,
            'BB_Width': (upper - lower) / mid,
        })
    
    # ==================== 评分系统 ====================
    
    def score_trend(self, df: pd.DataFrame) -> int:
        """
        趋势评分 (0-35分)
        
        评分标准:
        - MA5 > MA10 > MA20 > MA60: +15分 (多头排列)
        - MA5上穿MA10: +10分 (金叉)
        - MA20上穿MA60: +10分 (中期金叉)
        """
        score = 0
        
        if len(df) < 60:
            return 0
        
        latest = df.iloc[-1]
        
        # 多头排列
        if latest['MA5'] > latest['MA10'] > latest['MA20'] > latest['MA60']:
            score += 15
        elif latest['MA5'] > latest['MA10'] > latest['MA20']:
            score += 10
        elif latest['MA5'] > latest['MA10']:
            score += 5
        
        # 金叉 (需要前一日数据)
        if len(df) >= 2:
            prev = df.iloc[-2]
            # MA5金叉MA10
            if prev['MA5'] <= prev['MA10'] and latest['MA5'] > latest['MA10']:
                score += 10
            # MA20金叉MA60
            if prev['MA20'] <= prev['MA60'] and latest['MA20'] > latest['MA60']:
                score += 10
        
        return min(35, score)
    
    def score_rsi(self, df: pd.DataFrame) -> int:
        """
        RSI评分 (0-15分)
        
        评分标准:
        - RSI < 30: +15分 (超卖)
        - RSI 30-50: +10分 (偏低)
        - RSI 50-70: +5分 (正常)
        - RSI > 70: 0分 (超买)
        """
        if 'RSI' not in df.columns or len(df) < 14:
            return 0
        
        rsi = df.iloc[-1]['RSI']
        
        if pd.isna(rsi):
            return 0
        elif rsi < 30:
            return 15
        elif rsi < 50:
            return 10
        elif rsi < 70:
            return 5
        else:
            return 0
    
    def score_macd(self, df: pd.DataFrame) -> int:
        """
        MACD评分 (0-20分)
        
        评分标准:
        - MACD金叉: +15分
        - MACD柱状图放大: +5分
        - DIF > 0: +5分
        """
        score = 0
        
        if 'MACD_DIF' not in df.columns or len(df) < 26:
            return 0
        
        latest = df.iloc[-1]
        
        # DIF > 0
        if latest['MACD_DIF'] > 0:
            score += 5
        
        if len(df) >= 2:
            prev = df.iloc[-2]
            
            # 金叉
            if prev['MACD_DIF'] <= prev['MACD_DEA'] and latest['MACD_DIF'] > latest['MACD_DEA']:
                score += 15
            # 柱状图放大
            elif abs(latest['MACD']) > abs(prev['MACD']):
                score += 5
        
        return min(20, score)
    
    def score_volume(self, df: pd.DataFrame) -> int:
        """
        成交量评分 (0-15分)
        
        评分标准:
        - 放量突破: +10分
        - 温和放量: +5分
        """
        if 'volume' not in df.columns or len(df) < 10:
            return 0
        
        vol = df['volume'].iloc[-1]
        vol_ma5 = df['volume'].rolling(5).mean().iloc[-1]
        
        if pd.isna(vol_ma5) or vol_ma5 == 0:
            return 0
        
        ratio = vol / vol_ma5
        
        if ratio > 2.0:
            return 15  # 放量
        elif ratio > 1.5:
            return 10  # 温和放量
        elif ratio > 1.0:
            return 5
        else:
            return 0
    
    def score_momentum(self, df: pd.DataFrame) -> int:
        """
        动量评分 (0-15分)
        
        评分标准:
        - 5日涨幅 > 10%: +15分
        - 5日涨幅 > 5%: +10分
        - 5日涨幅 > 0%: +5分
        """
        if 'close' not in df.columns or len(df) < 6:
            return 0
        
        close = df['close']
        momentum_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100
        
        if momentum_5d > 10:
            return 15
        elif momentum_5d > 5:
            return 10
        elif momentum_5d > 0:
            return 5
        else:
            return 0
    
    def calculate_total_score(self, df: pd.DataFrame) -> Dict:
        """计算总分"""
        scores = {
            '趋势': self.score_trend(df),
            'RSI': self.score_rsi(df),
            'MACD': self.score_macd(df),
            '成交量': self.score_volume(df),
            '动量': self.score_momentum(df),
        }
        
        scores['总分'] = sum(scores.values())
        
        return scores
    
    # ==================== 选股策略 ====================
    
    async def pick_by_technical(self, top_n: int = 20, min_score: int = 60,
                                min_price: float = 3.0, max_price: float = 100.0,
                                min_volume: float = 5000) -> List[Dict]:
        """
        技术选股
        
        Args:
            top_n: 返回数量
            min_score: 最低分数
            min_price: 最低价格
            max_price: 最高价格
            min_volume: 最小成交额(万)
        
        Returns:
            List of stock dict
        """
        # 获取涨幅榜作为候选池
        try:
            from consolidated.data_sources import AStockDataSource
            ds = AStockDataSource()
            candidates = await ds.top_gainers(
                top_n=100,
                min_change=0,
                max_change=9.5,
                min_volume=min_volume
            )
            await ds.close()
        except:
            # 备用: 使用预定义列表
            candidates = []
        
        # 过滤主板
        candidates = self.filter_mainboard(candidates)
        
        # 价格过滤
        candidates = [s for s in candidates 
                     if min_price <= s.get('price', 0) <= max_price]
        
        results = []
        
        for stock in candidates:
            code = stock.get('code', '')
            
            # 获取K线数据
            try:
                from consolidated.data_sources import AStockDataSource
                ds = AStockDataSource()
                df = await ds.kline(code, 100)
                await ds.close()
                
                if df.empty or len(df) < 60:
                    continue
                
                # 计算技术指标
                ma_df = self.calculate_ma(df['close'])
                df = pd.concat([df, ma_df], axis=1)
                
                df['RSI'] = self.calculate_rsi(df['close'])
                macd_df = self.calculate_macd(df['close'])
                df = pd.concat([df, macd_df], axis=1)
                
                kdj_df = self.calculate_kdj(df['high'], df['low'], df['close'])
                df = pd.concat([df, kdj_df], axis=1)
                
                # 计算评分
                scores = self.calculate_total_score(df)
                
                if scores['总分'] >= min_score:
                    stock['scores'] = scores
                    stock['price'] = df['close'].iloc[-1]
                    results.append(stock)
                    
            except Exception as e:
                continue
        
        # 按分数排序
        results.sort(key=lambda x: x['scores']['总分'], reverse=True)
        
        return results[:top_n]
    
    def pick_by_model(self, stocks_data: pd.DataFrame, threshold: float = 0.6) -> pd.DataFrame:
        """
        模型选股
        
        Args:
            stocks_data: 股票特征数据
            threshold: 概率阈值
        
        Returns:
            DataFrame with predictions
        """
        if self.model is None:
            print("模型未加载")
            return pd.DataFrame()
        
        if not self.feature_cols:
            print("特征列表为空")
            return pd.DataFrame()
        
        # 过滤有效特征
        valid_features = [f for f in self.feature_cols if f in stocks_data.columns]
        
        if not valid_features:
            print("没有有效特征")
            return pd.DataFrame()
        
        X = stocks_data[valid_features].values
        
        # 预测
        proba = self.model.predict_proba(X)[:, 1]
        pred = self.model.predict(X)
        
        result = stocks_data.copy()
        result['prediction'] = pred
        result['probability'] = proba
        
        # 过滤高概率
        result = result[result['probability'] >= threshold]
        
        return result.sort_values('probability', ascending=False)


# ============================================================
# 便捷函数
# ============================================================

async def pick_stocks(method: str = 'technical', **kwargs) -> List[Dict]:
    """
    选股便捷函数
    
    Args:
        method: 选股方法 ('technical' 或 'model')
        **kwargs: 参数
    
    Returns:
        List of stock dict
    """
    picker = AStockPicker()
    
    if method == 'technical':
        return await picker.pick_by_technical(**kwargs)
    elif method == 'model':
        print("模型选股需要提供数据")
        return []
    else:
        return []


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("A股选股模块测试")
    print("=" * 60)
    
    picker = AStockPicker()
    
    # 测试主板判断
    print("\n1. 主板判断测试:")
    test_codes = ["600519", "000001", "300001", "688001", "002415"]
    for code in test_codes:
        result = "主板" if picker.is_mainboard(code) else "非主板"
        print(f"   {code}: {result}")
    
    # 测试技术选股
    print("\n2. 技术选股测试:")
    try:
        results = asyncio.run(picker.pick_by_technical(top_n=10, min_score=50))
        if results:
            for i, stock in enumerate(results, 1):
                scores = stock.get('scores', {})
                print(f"   {i}. {stock.get('name', 'N/A')}({stock.get('code', 'N/A')}): "
                      f"总分{scores.get('总分', 0)}分, 价格{stock.get('price', 0):.2f}元")
        else:
            print("   无符合条件股票")
    except Exception as e:
        print(f"   选股失败: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")

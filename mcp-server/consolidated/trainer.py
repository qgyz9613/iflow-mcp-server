"""
A股模型训练模块 - 合并版
整合以下模块:
- train_a_stock.py (基础训练)
- train_mainboard_5pct_final.py (主板5%涨幅)
- train_mainboard_final.py (全面优化版)
- train_batches.py (批量训练)
- train_*.py 其他训练脚本

特性:
- 支持多股票批量训练
- 支持主板股票过滤
- 支持5%/10%涨幅预测
- 自动特征工程
- 模型评估和保存
"""

import pandas as pd
import numpy as np
from catboost import CatBoostClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, classification_report
from sklearn.feature_selection import SelectKBest, f_classif, mutual_info_classif
from sklearn.model_selection import train_test_split
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')


class AStockTrainer:
    """A股模型训练器"""
    
    # 主板前缀
    MAINBOARD_PREFIX = ['60', '00', '001', '002', '003']
    
    def __init__(self, db_config: Optional[Dict] = None):
        """
        初始化训练器
        
        Args:
            db_config: 数据库配置 (host, port, user, password, dbname)
        """
        self.db_config = db_config or {
            'host': '38.165.21.21',
            'port': 5432,
            'user': 'admin',
            'password': 'SX7YRCwXszkdtd4B',
            'dbname': 'postgres'
        }
        self.model = None
        self.feature_cols = []
        self.feature_importance = None
    
    def is_mainboard(self, code: str) -> bool:
        """判断是否主板股票"""
        code = str(code).zfill(6)
        # 排除ST
        if 'ST' in str(code):
            return False
        # 检查主板前缀
        for prefix in self.MAINBOARD_PREFIX:
            if code.startswith(prefix):
                return True
        return False
    
    def get_mainboard_stocks(self) -> List[str]:
        """获取主板股票列表"""
        try:
            import psycopg2
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            query = """
            SELECT DISTINCT ts_code FROM stocks
            WHERE ts_code LIKE '6%%' OR ts_code LIKE '000%%' 
               OR ts_code LIKE '001%%' OR ts_code LIKE '002%%' OR ts_code LIKE '003%%'
            """
            cursor.execute(query)
            stocks = [row[0] for row in cursor.fetchall()]
            cursor.close()
            conn.close()
            return stocks
        except Exception as e:
            print(f"获取股票列表失败: {e}")
            return []
    
    def fetch_price_data(self, stocks: List[str], days: int = 500) -> pd.DataFrame:
        """
        获取价格数据
        
        Args:
            stocks: 股票代码列表
            days: 历史天数
        
        Returns:
            DataFrame with price data
        """
        try:
            import psycopg2
            conn = psycopg2.connect(**self.db_config)
            
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days + 20)
            
            query = """
            SELECT ts_code, trade_date, open, high, low, close, vol, amount
            FROM stock_prices
            WHERE trade_date >= %s AND trade_date <= %s
            AND ts_code = ANY(%s)
            ORDER BY ts_code, trade_date
            """
            
            import psycopg2.extras
            cursor = conn.cursor()
            psycopg2.extras.execute_values(
                cursor,
                f"SELECT ts_code, trade_date, open, high, low, close, vol, amount FROM stock_prices WHERE trade_date >= '{start_date}' AND ts_code = ANY(%s) ORDER BY ts_code, trade_date",
                [stocks],
                template="(%s)"
            )
            
            df = pd.read_sql_query(
                "SELECT ts_code, trade_date, open, high, low, close, vol, amount FROM stock_prices WHERE trade_date >= %s AND ts_code = ANY(%s) ORDER BY ts_code, trade_date",
                conn, params=(start_date, stocks)
            )
            
            conn.close()
            
            # 类型转换
            for col in ['open', 'high', 'low', 'close', 'vol', 'amount']:
                df[col] = df[col].astype(float)
            
            return df
        except Exception as e:
            print(f"获取价格数据失败: {e}")
            return pd.DataFrame()
    
    def calculate_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算技术特征 (80+特征)
        
        Args:
            df: 原始价格数据
        
        Returns:
            DataFrame with features
        """
        df = df.sort_values(['ts_code', 'trade_date']).copy()
        
        # ===== 基础收益率 =====
        df['return_1d'] = df.groupby('ts_code')['close'].pct_change(1)
        df['return_3d'] = df.groupby('ts_code')['close'].pct_change(3)
        df['return_5d'] = df.groupby('ts_code')['close'].pct_change(5)
        df['return_10d'] = df.groupby('ts_code')['close'].pct_change(10)
        
        # ===== 移动平均线 =====
        df['MA5'] = df.groupby('ts_code')['close'].transform(lambda x: x.rolling(5).mean())
        df['MA10'] = df.groupby('ts_code')['close'].transform(lambda x: x.rolling(10).mean())
        df['MA20'] = df.groupby('ts_code')['close'].transform(lambda x: x.rolling(20).mean())
        df['MA60'] = df.groupby('ts_code')['close'].transform(lambda x: x.rolling(60).mean())
        
        # 价格相对位置
        df['Price_vs_MA5'] = (df['close'] - df['MA5']) / df['MA5']
        df['Price_vs_MA10'] = (df['close'] - df['MA10']) / df['MA10']
        df['Price_vs_MA20'] = (df['close'] - df['MA20']) / df['MA20']
        
        # ===== 布林带 =====
        df['BB_Mid'] = df['MA20']
        df['BB_Std'] = df.groupby('ts_code')['close'].transform(lambda x: x.rolling(20).std())
        df['BB_Upper'] = df['BB_Mid'] + 2 * df['BB_Std']
        df['BB_Lower'] = df['BB_Mid'] - 2 * df['BB_Std']
        df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Mid']
        df['BB_Position'] = (df['close'] - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower'])
        
        # ===== RSI =====
        def calculate_rsi(prices, period=14):
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            return 100 - (100 / (1 + rs))
        
        df['RSI_6'] = df.groupby('ts_code')['close'].transform(lambda x: calculate_rsi(x, 6))
        df['RSI_14'] = df.groupby('ts_code')['close'].transform(lambda x: calculate_rsi(x, 14))
        df['RSI_24'] = df.groupby('ts_code')['close'].transform(lambda x: calculate_rsi(x, 24))
        
        # ===== MACD =====
        def calc_macd(group):
            ema12 = group['close'].ewm(span=12, adjust=False).mean()
            ema26 = group['close'].ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            signal = macd.ewm(span=9, adjust=False).mean()
            hist = macd - signal
            return pd.DataFrame({'MACD': macd, 'MACD_Signal': signal, 'MACD_Hist': hist}, index=group.index)
        
        macd_df = df.groupby('ts_code', group_keys=False).apply(calc_macd)
        df = df.join(macd_df)
        
        # ===== 波动率 =====
        df['Volatility_5d'] = df.groupby('ts_code')['return_1d'].transform(lambda x: x.rolling(5).std())
        df['Volatility_10d'] = df.groupby('ts_code')['return_1d'].transform(lambda x: x.rolling(10).std())
        df['Volatility_20d'] = df.groupby('ts_code')['return_1d'].transform(lambda x: x.rolling(20).std())
        
        # ===== 成交量 =====
        df['Vol_MA5'] = df.groupby('ts_code')['vol'].transform(lambda x: x.rolling(5).mean())
        df['Vol_MA10'] = df.groupby('ts_code')['vol'].transform(lambda x: x.rolling(10).mean())
        df['Turnover_Ratio'] = df['vol'] / df['Vol_MA5']
        
        # ===== 动量 =====
        df['Momentum_5'] = df.groupby('ts_code')['close'].transform(lambda x: x / x.shift(5) - 1)
        df['Momentum_10'] = df.groupby('ts_code')['close'].transform(lambda x: x / x.shift(10) - 1)
        df['Momentum_20'] = df.groupby('ts_code')['close'].transform(lambda x: x / x.shift(20) - 1)
        
        # ===== 价格区间 =====
        df['Price_Range_20d'] = (
            (df['close'] - df.groupby('ts_code')['low'].transform(lambda x: x.rolling(20).min())) /
            (df.groupby('ts_code')['high'].transform(lambda x: x.rolling(20).max()) -
             df.groupby('ts_code')['low'].transform(lambda x: x.rolling(20).min()))
        )
        
        # ===== 振幅 =====
        df['Amplitude'] = (df['high'] - df['low']) / df['close']
        
        return df
    
    def create_target(self, df: pd.DataFrame, horizon: int = 5, gain_threshold: float = 0.05) -> pd.DataFrame:
        """
        创建训练标签
        
        Args:
            df: 特征数据
            horizon: 预测周期 (天)
            gain_threshold: 涨幅阈值 (默认5%)
        
        Returns:
            DataFrame with target column
        """
        df = df.copy()
        
        # 计算未来N天最高涨幅
        df['Max_Gain'] = df.groupby('ts_code')['close'].transform(
            lambda x: (x.rolling(horizon, min_periods=horizon).max() - x) / x
        )
        
        # 创建标签
        df['target'] = (df['Max_Gain'] >= gain_threshold).astype(int)
        
        return df
    
    def select_features(self, X: pd.DataFrame, y: pd.Series, k: int = 60) -> List[str]:
        """
        特征选择 (两阶段)
        
        Args:
            X: 特征数据
            y: 标签
            k: 选择特征数量
        
        Returns:
            选择的特征列表
        """
        # 过滤无效数据
        valid_idx = ~(X.isna().any(axis=1) | y.isna())
        X_clean = X[valid_idx]
        y_clean = y[valid_idx]
        
        # 第一阶段: F-test选择top 100
        selector_f = SelectKBest(f_classif, k=min(100, len(X_clean.columns)))
        selector_f.fit(X_clean, y_clean)
        f_selected = X_clean.columns[selector_f.get_support()]
        
        # 第二阶段: 互信息选择top k
        X_f = X_clean[f_selected]
        selector_mi = SelectKBest(mutual_info_classif, k=min(k, len(X_f.columns)))
        selector_mi.fit(X_f, y_clean)
        mi_selected = X_f.columns[selector_mi.get_support()]
        
        return list(mi_selected)
    
    def train(self, df: pd.DataFrame, target_col: str = 'target', 
              test_size: float = 0.2, feature_count: int = 60,
              **model_params) -> Dict:
        """
        训练模型
        
        Args:
            df: 带特征和标签的数据
            target_col: 标签列名
            test_size: 测试集比例
            feature_count: 特征数量
            **model_params: CatBoost参数
        
        Returns:
            训练结果字典
        """
        # 排除非特征列
        exclude_cols = ['ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'amount',
                        'return_1d', 'return_3d', 'return_5d', 'return_10d',
                        'Max_Gain', 'target']
        feature_cols = [col for col in df.columns if col not in exclude_cols]
        
        # 过滤无效数据
        df_clean = df.dropna(subset=feature_cols + [target_col])
        
        # 特征选择
        self.feature_cols = self.select_features(df_clean[feature_cols], df_clean[target_col], feature_count)
        
        # 按时间划分
        df_clean = df_clean.sort_values('trade_date')
        split_idx = int(len(df_clean) * (1 - test_size))
        
        train_df = df_clean.iloc[:split_idx]
        test_df = df_clean.iloc[split_idx:]
        
        X_train = train_df[self.feature_cols].values
        y_train = train_df[target_col].values
        X_test = test_df[self.feature_cols].values
        y_test = test_df[target_col].values
        
        # 默认参数
        default_params = {
            'iterations': 300,
            'learning_rate': 0.05,
            'depth': 6,
            'random_seed': 42,
            'verbose': 50,
            'auto_class_weights': 'Balanced',
            'eval_metric': 'AUC',
            'early_stopping_rounds': 50,
        }
        default_params.update(model_params)
        
        # 训练
        self.model = CatBoostClassifier(**default_params)
        self.model.fit(X_train, y_train, eval_set=(X_test, y_test), verbose=50)
        
        # 评估
        y_pred = self.model.predict(X_test)
        y_proba = self.model.predict_proba(X_test)[:, 1]
        
        # 特征重要性
        self.feature_importance = pd.DataFrame({
            'feature': self.feature_cols,
            'importance': self.model.feature_importances_
        }).sort_values('importance', ascending=False)
        
        return {
            'accuracy': accuracy_score(y_test, y_pred),
            'precision': precision_score(y_test, y_pred, zero_division=0),
            'recall': recall_score(y_test, y_pred, zero_division=0),
            'f1': f1_score(y_test, y_pred, zero_division=0),
            'auc': roc_auc_score(y_test, y_proba),
            'feature_importance': self.feature_importance,
            'train_samples': len(X_train),
            'test_samples': len(X_test),
        }
    
    def save_model(self, path: str):
        """保存模型"""
        if self.model is None:
            raise ValueError("模型未训练")
        self.model.save_model(path)
        
        # 保存特征
        import json
        meta_path = path.replace('.cbm', '_meta.json')
        with open(meta_path, 'w') as f:
            json.dump({
                'feature_cols': self.feature_cols,
                'train_time': datetime.now().isoformat(),
            }, f, indent=2)
    
    def load_model(self, path: str):
        """加载模型"""
        self.model = CatBoostClassifier()
        self.model.load_model(path)
        
        # 加载特征
        import json
        meta_path = path.replace('.cbm', '_meta.json')
        try:
            with open(meta_path, 'r') as f:
                meta = json.load(f)
                self.feature_cols = meta.get('feature_cols', [])
        except:
            pass
    
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        预测
        
        Args:
            df: 特征数据
        
        Returns:
            DataFrame with predictions
        """
        if self.model is None:
            raise ValueError("模型未训练")
        
        df = df.copy()
        X = df[self.feature_cols].values
        
        df['prediction'] = self.model.predict(X)
        df['probability'] = self.model.predict_proba(X)[:, 1]
        
        return df


# ============================================================
# 便捷函数
# ============================================================

def train_mainboard_model(gain_threshold: float = 0.05, days: int = 500, 
                          feature_count: int = 60) -> Tuple[CatBoostClassifier, Dict]:
    """
    训练主板预测模型
    
    Args:
        gain_threshold: 涨幅阈值 (默认5%)
        days: 历史数据天数
        feature_count: 特征数量
    
    Returns:
        (model, results)
    """
    trainer = AStockTrainer()
    
    # 获取主板股票
    stocks = trainer.get_mainboard_stocks()
    print(f"主板股票数量: {len(stocks)}")
    
    if not stocks:
        print("获取股票失败")
        return None, {}
    
    # 获取数据
    df = trainer.fetch_price_data(stocks[:100], days)  # 限制100只测试
    if df.empty:
        print("获取数据失败")
        return None, {}
    
    print(f"价格数据量: {len(df)}")
    
    # 计算特征
    df = trainer.calculate_features(df)
    
    # 创建标签
    df = trainer.create_target(df, gain_threshold=gain_threshold)
    
    # 训练
    results = trainer.train(df, feature_count=feature_count)
    
    print(f"\n训练结果:")
    print(f"  准确率: {results['accuracy']:.4f}")
    print(f"  精确率: {results['precision']:.4f}")
    print(f"  召回率: {results['recall']:.4f}")
    print(f"  AUC: {results['auc']:.4f}")
    
    return trainer.model, results


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("A股模型训练模块测试")
    print("=" * 60)
    
    model, results = train_mainboard_model(gain_threshold=0.05, days=300, feature_count=40)
    
    if model:
        # 保存模型
        model.save_model("mainboard_model.cbm")
        print("\n模型已保存: mainboard_model.cbm")

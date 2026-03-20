"""
ML预测模块 v1.0
整合fortune中的机器学习模型

功能:
1. 模型加载与管理
2. 股票预测
3. 特征工程
4. 批量预测
"""

import os
import sys
import pickle
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# fortune路径
FORTUNE_PATH = Path(__file__).parent.parent.parent / "fortune"
MODELS_PATH = FORTUNE_PATH / "models"
DATA_PATH = FORTUNE_PATH / "data"

if FORTUNE_PATH.exists():
    sys.path.insert(0, str(FORTUNE_PATH))


class ModelManager:
    """模型管理器"""
    
    # 已训练的模型
    AVAILABLE_MODELS = {
        "mainboard_5pct": {
            "file": "mainboard_5pct_final_model.cbm",
            "type": "catboost",
            "accuracy": 0.5438,
            "description": "主板5%涨幅预测模型",
            "features": 50,
            "stocks": 4079,
        },
        "a_stock_10pct": {
            "file": "a_stock_model.cbm",
            "type": "catboost",
            "accuracy": 0.54,
            "description": "A股10%涨幅预测模型",
            "features": 45,
            "stocks": 250,
        },
    }
    
    def __init__(self, model_dir: str = None):
        self.model_dir = Path(model_dir) if model_dir else MODELS_PATH
        self.loaded_models = {}
    
    def list_models(self) -> Dict:
        """列出可用模型"""
        result = {}
        for name, info in self.AVAILABLE_MODELS.items():
            model_path = self.model_dir / info["file"]
            result[name] = {
                **info,
                "exists": model_path.exists(),
                "path": str(model_path),
            }
        return result
    
    def load_model(self, model_name: str):
        """加载模型"""
        if model_name in self.loaded_models:
            return self.loaded_models[model_name]
        
        if model_name not in self.AVAILABLE_MODELS:
            raise ValueError(f"未知模型: {model_name}")
        
        model_info = self.AVAILABLE_MODELS[model_name]
        model_path = self.model_dir / model_info["file"]
        
        if not model_path.exists():
            raise FileNotFoundError(f"模型文件不存在: {model_path}")
        
        # 根据模型类型加载
        if model_info["type"] == "catboost":
            try:
                from catboost import CatBoostClassifier
                model = CatBoostClassifier()
                model.load_model(str(model_path))
            except ImportError:
                # 如果没有catboost，尝试pickle
                with open(model_path, "rb") as f:
                    model = pickle.load(f)
        else:
            with open(model_path, "rb") as f:
                model = pickle.load(f)
        
        self.loaded_models[model_name] = model
        return model
    
    def get_model_info(self, model_name: str) -> Dict:
        """获取模型信息"""
        if model_name not in self.AVAILABLE_MODELS:
            return {"error": f"未知模型: {model_name}"}
        
        info = self.AVAILABLE_MODELS[model_name].copy()
        model_path = self.model_dir / info["file"]
        info["exists"] = model_path.exists()
        info["loaded"] = model_name in self.loaded_models
        
        if model_path.exists():
            info["file_size_mb"] = round(model_path.stat().st_size / 1024 / 1024, 2)
        
        return info


class FeatureEngineer:
    """特征工程"""
    
    @staticmethod
    def create_features(df: pd.DataFrame) -> pd.DataFrame:
        """
        从OHLCV数据创建特征
        
        Args:
            df: 包含 open, high, low, close, volume 的DataFrame
        """
        features = pd.DataFrame()
        
        # 价格特征
        features["return_1d"] = df["close"].pct_change()
        features["return_5d"] = df["close"].pct_change(5)
        features["return_10d"] = df["close"].pct_change(10)
        features["return_20d"] = df["close"].pct_change(20)
        
        # 波动率
        features["volatility_5d"] = df["close"].pct_change().rolling(5).std()
        features["volatility_10d"] = df["close"].pct_change().rolling(10).std()
        features["volatility_20d"] = df["close"].pct_change().rolling(20).std()
        
        # 均线偏离
        features["price_vs_ma5"] = (df["close"] - df["close"].rolling(5).mean()) / df["close"].rolling(5).mean()
        features["price_vs_ma10"] = (df["close"] - df["close"].rolling(10).mean()) / df["close"].rolling(10).mean()
        features["price_vs_ma20"] = (df["close"] - df["close"].rolling(20).mean()) / df["close"].rolling(20).mean()
        
        # 高低点位置
        features["price_vs_high_5d"] = df["close"] / df["high"].rolling(5).max() - 1
        features["price_vs_high_20d"] = df["close"] / df["high"].rolling(20).max() - 1
        features["price_vs_low_5d"] = df["close"] / df["low"].rolling(5).min() - 1
        features["price_vs_low_20d"] = df["close"] / df["low"].rolling(20).min() - 1
        
        # 动量
        features["momentum_5"] = df["close"] / df["close"].shift(5) - 1
        features["momentum_10"] = df["close"] / df["close"].shift(10) - 1
        features["momentum_20"] = df["close"] / df["close"].shift(20) - 1
        
        # 成交量
        features["volume_ratio_5d"] = df["volume"] / df["volume"].rolling(5).mean()
        features["volume_ratio_20d"] = df["volume"] / df["volume"].rolling(20).mean()
        
        # RSI近似
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        features["rsi_14"] = 100 - (100 / (1 + rs))
        
        # 布林带位置
        mid = df["close"].rolling(20).mean()
        std = df["close"].rolling(20).std()
        upper = mid + 2 * std
        lower = mid - 2 * std
        features["boll_position"] = (df["close"] - lower) / (upper - lower)
        
        # MACD近似
        ema12 = df["close"].ewm(span=12).mean()
        ema26 = df["close"].ewm(span=26).mean()
        features["macd"] = ema12 - ema26
        features["macd_signal"] = features["macd"].ewm(span=9).mean()
        features["macd_hist"] = features["macd"] - features["macd_signal"]
        
        return features


class StockPredictor:
    """股票预测器"""
    
    def __init__(self, model_name: str = "mainboard_5pct"):
        self.model_manager = ModelManager()
        self.feature_engineer = FeatureEngineer()
        self.model_name = model_name
        self.model = None
    
    def load_model(self) -> bool:
        """加载模型"""
        try:
            self.model = self.model_manager.load_model(self.model_name)
            return True
        except Exception as e:
            print(f"加载模型失败: {e}")
            return False
    
    def predict(self, features: np.ndarray) -> Dict:
        """
        预测
        
        Args:
            features: 特征数组 (n_samples, n_features)
        """
        if self.model is None:
            if not self.load_model():
                return {"error": "模型未加载"}
        
        try:
            # 预测类别
            predictions = self.model.predict(features)
            
            # 预测概率
            if hasattr(self.model, "predict_proba"):
                probabilities = self.model.predict_proba(features)
            else:
                probabilities = None
            
            return {
                "predictions": predictions.tolist() if hasattr(predictions, "tolist") else list(predictions),
                "probabilities": probabilities.tolist() if probabilities is not None else None,
                "model": self.model_name,
            }
        except Exception as e:
            return {"error": str(e)}
    
    def predict_from_dataframe(self, df: pd.DataFrame) -> Dict:
        """
        从DataFrame预测
        
        Args:
            df: OHLCV数据
        """
        # 创建特征
        features_df = self.feature_engineer.create_features(df)
        
        # 移除NaN
        features_df = features_df.dropna()
        
        if len(features_df) == 0:
            return {"error": "特征数据不足"}
        
        # 转换为numpy
        features = features_df.values
        
        # 预测
        result = self.predict(features)
        result["features_used"] = len(features_df.columns)
        result["samples"] = len(features_df)
        
        return result


class MultiAgentSystem:
    """
    多代理系统简化版
    参考 fortune/ml_services/multi_agent_system.py
    """
    
    def __init__(self):
        self.agents = {
            "signal": self._signal_agent,
            "risk": self._risk_agent,
            "sentiment": self._sentiment_agent,
        }
    
    def _signal_agent(self, data: Dict) -> Dict:
        """信号代理"""
        signal = data.get("signal", "hold")
        confidence = data.get("confidence", 0.5)
        
        if confidence > 0.7:
            strength = "强"
        elif confidence > 0.5:
            strength = "中"
        else:
            strength = "弱"
        
        return {
            "agent": "signal",
            "recommendation": signal,
            "strength": strength,
            "confidence": confidence,
        }
    
    def _risk_agent(self, data: Dict) -> Dict:
        """风险代理"""
        var = data.get("var_pct", 0)
        
        if var > 5:
            level = "HIGH"
        elif var > 3:
            level = "MEDIUM"
        else:
            level = "LOW"
        
        return {
            "agent": "risk",
            "risk_level": level,
            "var_pct": var,
        }
    
    def _sentiment_agent(self, data: Dict) -> Dict:
        """情感代理"""
        news = data.get("news", [])
        positive_keywords = ["上涨", "利好", "增长", "突破", "盈利"]
        negative_keywords = ["下跌", "利空", "亏损", "暴跌", "风险"]
        
        positive = 0
        negative = 0
        
        for item in news:
            title = item.get("title", "")
            for kw in positive_keywords:
                if kw in title:
                    positive += 1
            for kw in negative_keywords:
                if kw in title:
                    negative += 1
        
        total = positive + negative
        if total > 0:
            sentiment_score = (positive - negative) / total
        else:
            sentiment_score = 0
        
        return {
            "agent": "sentiment",
            "sentiment_score": round(sentiment_score, 2),
            "positive": positive,
            "negative": negative,
        }
    
    def analyze(self, data: Dict) -> Dict:
        """
        综合分析
        
        Args:
            data: 包含 signal, var_pct, news 等字段
        """
        results = {}
        
        for name, agent in self.agents.items():
            results[name] = agent(data)
        
        # 综合判断
        signal_conf = results["signal"]["confidence"]
        risk_level = results["risk"]["risk_level"]
        sentiment = results["sentiment"]["sentiment_score"]
        
        # 综合分数
        score = signal_conf * 0.5 + (1 if risk_level == "LOW" else 0.5 if risk_level == "MEDIUM" else 0) * 0.3 + (sentiment + 1) / 2 * 0.2
        
        recommendation = "buy" if score > 0.6 else "sell" if score < 0.4 else "hold"
        
        return {
            "agents": results,
            "composite_score": round(score, 2),
            "recommendation": recommendation,
            "timestamp": datetime.now().isoformat()
        }


# ==================== MCP工具注册 ====================

def register_tools(mcp):
    """注册MCP工具"""
    
    model_manager = ModelManager()
    multi_agent = MultiAgentSystem()
    
    @mcp.tool()
    def list_ml_models() -> dict:
        """列出可用的ML模型"""
        return model_manager.list_models()
    
    @mcp.tool()
    def get_model_info(model_name: str = "mainboard_5pct") -> dict:
        """
        获取模型详细信息
        
        Args:
            model_name: 模型名称
        """
        return model_manager.get_model_info(model_name)
    
    @mcp.tool()
    def multi_agent_analyze(
        signal: str = "hold",
        confidence: float = 0.5,
        var_pct: float = 0,
        news: str = ""
    ) -> dict:
        """
        多代理综合分析
        
        Args:
            signal: 交易信号
            confidence: 信号置信度 0-1
            var_pct: 风险VaR百分比
            news: 新闻标题，分号分隔
        """
        data = {
            "signal": signal,
            "confidence": confidence,
            "var_pct": var_pct,
            "news": [{"title": n.strip()} for n in news.split(";") if n.strip()],
        }
        return multi_agent.analyze(data)


# ==================== 测试 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("ML预测模块测试")
    print("=" * 60)
    
    # 1. 列出模型
    print("\n1. 可用模型:")
    manager = ModelManager()
    models = manager.list_models()
    for name, info in models.items():
        status = "✓" if info["exists"] else "✗"
        print(f"  [{status}] {name}: {info['description']}")
        print(f"      准确率: {info['accuracy']}, 特征数: {info['features']}")
    
    # 2. 多代理测试
    print("\n2. 多代理分析测试:")
    agent = MultiAgentSystem()
    result = agent.analyze({
        "signal": "buy",
        "confidence": 0.75,
        "var_pct": 2.5,
        "news": [
            {"title": "公司业绩大幅上涨"},
            {"title": "利好政策发布"},
        ]
    })
    print(f"  综合分数: {result['composite_score']}")
    print(f"  推荐操作: {result['recommendation']}")
    for agent_name, agent_result in result['agents'].items():
        print(f"  {agent_name}代理: {agent_result}")
    
    print("\n" + "=" * 60)
    print("测试完成!")

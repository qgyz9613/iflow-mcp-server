"""
A股诊断工具模块 - 合并版
整合以下模块:
- check_data_quality.py (数据质量检查)
- check_mainboard_model.py (模型检查)
- check_db_data.py (数据库检查)
- check_*.py 其他检查脚本

特性:
- 数据质量检查
- 模型性能分析
- 数据库连接测试
- 特征诊断
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Any
import json
import os


class DataQualityChecker:
    """数据质量检查器"""
    
    def __init__(self, df: Optional[pd.DataFrame] = None):
        self.df = df
        self.report = {}
    
    def load_data(self, path: str) -> bool:
        """加载数据"""
        try:
            self.df = pd.read_csv(path)
            return True
        except Exception as e:
            print(f"加载失败: {e}")
            return False
    
    def check_basic_info(self) -> Dict:
        """基本信息检查"""
        if self.df is None:
            return {}
        
        info = {
            "总记录数": len(self.df),
            "列数": len(self.df.columns),
            "列名": list(self.df.columns),
            "内存使用": f"{self.df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB",
        }
        
        # 日期列检查
        date_cols = [c for c in self.df.columns if '日期' in c or 'date' in c.lower()]
        if date_cols:
            for col in date_cols:
                try:
                    dates = pd.to_datetime(self.df[col])
                    info[f"{col}范围"] = f"{dates.min()} ~ {dates.max()}"
                except:
                    pass
        
        self.report["基本信息"] = info
        return info
    
    def check_missing_values(self) -> Dict:
        """缺失值检查"""
        if self.df is None:
            return {}
        
        missing = self.df.isnull().sum()
        missing = missing[missing > 0]
        
        result = {
            "是否有缺失": len(missing) > 0,
            "缺失列数": len(missing),
            "缺失详情": {col: int(count) for col, count in missing.items()},
        }
        
        self.report["缺失值检查"] = result
        return result
    
    def check_duplicates(self) -> Dict:
        """重复值检查"""
        if self.df is None:
            return {}
        
        dup_count = self.df.duplicated().sum()
        
        result = {
            "重复行数": int(dup_count),
            "重复比例": f"{dup_count / len(self.df) * 100:.2f}%",
        }
        
        self.report["重复值检查"] = result
        return result
    
    def check_outliers(self, columns: Optional[List[str]] = None) -> Dict:
        """异常值检查"""
        if self.df is None:
            return {}
        
        if columns is None:
            columns = self.df.select_dtypes(include=[np.number]).columns.tolist()
        
        outliers = {}
        for col in columns:
            if col not in self.df.columns:
                continue
            
            data = self.df[col].dropna()
            if len(data) == 0:
                continue
            
            q1 = data.quantile(0.25)
            q3 = data.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            
            outlier_count = ((data < lower) | (data > upper)).sum()
            
            if outlier_count > 0:
                outliers[col] = {
                    "异常值数量": int(outlier_count),
                    "异常值比例": f"{outlier_count / len(data) * 100:.2f}%",
                    "正常范围": f"[{lower:.2f}, {upper:.2f}]",
                }
        
        result = {
            "有异常值的列数": len(outliers),
            "异常值详情": outliers,
        }
        
        self.report["异常值检查"] = result
        return result
    
    def check_distribution(self, columns: Optional[List[str]] = None) -> Dict:
        """分布检查"""
        if self.df is None:
            return {}
        
        if columns is None:
            columns = self.df.select_dtypes(include=[np.number]).columns.tolist()[:10]
        
        distributions = {}
        for col in columns:
            if col not in self.df.columns:
                continue
            
            data = self.df[col].dropna()
            if len(data) == 0:
                continue
            
            distributions[col] = {
                "均值": float(data.mean()),
                "标准差": float(data.std()),
                "最小值": float(data.min()),
                "最大值": float(data.max()),
                "中位数": float(data.median()),
            }
        
        self.report["分布检查"] = distributions
        return distributions
    
    def get_score(self) -> int:
        """计算数据质量评分 (0-100)"""
        score = 100
        
        # 缺失值扣分
        missing = self.report.get("缺失值检查", {})
        if missing.get("是否有缺失"):
            missing_ratio = sum(missing.get("缺失详情", {}).values()) / max(len(self.df), 1)
            score -= int(missing_ratio * 100)
        
        # 重复值扣分
        dup = self.report.get("重复值检查", {})
        dup_ratio = float(dup.get("重复比例", "0%").replace("%", "")) / 100
        score -= int(dup_ratio * 50)
        
        return max(0, score)
    
    def run_all_checks(self) -> Dict:
        """运行所有检查"""
        self.check_basic_info()
        self.check_missing_values()
        self.check_duplicates()
        self.check_outliers()
        self.check_distribution()
        
        self.report["质量评分"] = self.get_score()
        self.report["检查时间"] = datetime.now().isoformat()
        
        return self.report
    
    def print_report(self):
        """打印报告"""
        print("=" * 60)
        print("数据质量检查报告")
        print("=" * 60)
        
        for section, content in self.report.items():
            if section == "缺失值详情" or section == "异常值详情":
                continue
            
            print(f"\n【{section}】")
            if isinstance(content, dict):
                for key, value in content.items():
                    if key in ["缺失详情", "异常值详情"]:
                        continue
                    if isinstance(value, dict):
                        print(f"  {key}:")
                        for k, v in value.items():
                            print(f"    - {k}: {v}")
                    else:
                        print(f"  {key}: {value}")
            else:
                print(f"  {content}")
        
        print("\n" + "=" * 60)


class ModelDiagnostics:
    """模型诊断器"""
    
    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self.model_path = model_path
    
    def load_model(self, path: str) -> bool:
        """加载模型"""
        try:
            from catboost import CatBoostClassifier
            self.model = CatBoostClassifier()
            self.model.load_model(path)
            self.model_path = path
            return True
        except Exception as e:
            print(f"加载模型失败: {e}")
            return False
    
    def analyze_predictions(self, y_true: np.ndarray, y_pred: np.ndarray, 
                           y_proba: np.ndarray) -> Dict:
        """分析预测结果"""
        from sklearn.metrics import confusion_matrix, classification_report, roc_auc_score
        
        # 混淆矩阵
        cm = confusion_matrix(y_true, y_pred)
        tn, fp, fn, tp = cm.ravel()
        
        # 计算指标
        accuracy = (tp + tn) / (tp + tn + fp + fn)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        
        try:
            auc = roc_auc_score(y_true, y_proba)
        except:
            auc = 0
        
        return {
            "混淆矩阵": {
                "真负例(TN)": int(tn),
                "假正例(FP)": int(fp),
                "假负例(FN)": int(fn),
                "真正例(TP)": int(tp),
            },
            "指标": {
                "准确率": round(accuracy, 4),
                "精确率": round(precision, 4),
                "召回率": round(recall, 4),
                "特异度": round(specificity, 4),
                "F1分数": round(f1, 4),
                "AUC": round(auc, 4),
            },
            "样本分布": {
                "总样本": len(y_true),
                "正样本": int((y_true == 1).sum()),
                "负样本": int((y_true == 0).sum()),
                "正样本比例": round((y_true == 1).sum() / len(y_true), 4),
            },
        }
    
    def threshold_analysis(self, y_true: np.ndarray, y_proba: np.ndarray,
                          thresholds: List[float] = None) -> pd.DataFrame:
        """阈值分析"""
        from sklearn.metrics import precision_score, recall_score
        
        if thresholds is None:
            thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        
        results = []
        for threshold in thresholds:
            y_pred = (y_proba >= threshold).astype(int)
            
            if (y_pred == 1).sum() == 0:
                continue
            
            precision = precision_score(y_true, y_pred, zero_division=0)
            recall = recall_score(y_true, y_pred, zero_division=0)
            
            results.append({
                "阈值": threshold,
                "预测正样本数": int((y_pred == 1).sum()),
                "精确率": round(precision, 4),
                "召回率": round(recall, 4),
            })
        
        return pd.DataFrame(results)
    
    def feature_importance(self, feature_names: List[str], top_n: int = 20) -> pd.DataFrame:
        """特征重要性"""
        if self.model is None:
            return pd.DataFrame()
        
        importance = pd.DataFrame({
            "feature": feature_names,
            "importance": self.model.feature_importances_,
        }).sort_values("importance", ascending=False)
        
        return importance.head(top_n)


class DatabaseDiagnostics:
    """数据库诊断器"""
    
    def __init__(self, db_config: Optional[Dict] = None):
        self.db_config = db_config or {
            'host': '38.165.21.21',
            'port': 5432,
            'user': 'admin',
            'password': 'SX7YRCwXszkdtd4B',
            'dbname': 'postgres'
        }
        self.conn = None
    
    def test_connection(self) -> Dict:
        """测试连接"""
        result = {
            "连接状态": "失败",
            "错误信息": None,
        }
        
        try:
            import psycopg2
            self.conn = psycopg2.connect(**self.db_config)
            self.conn.close()
            result["连接状态"] = "成功"
        except Exception as e:
            result["错误信息"] = str(e)
        
        return result
    
    def get_table_info(self) -> Dict:
        """获取表信息"""
        try:
            import psycopg2
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # 获取所有表
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            tables = [row[0] for row in cursor.fetchall()]
            
            # 获取每个表的行数
            table_info = {}
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    table_info[table] = {"行数": count}
                except:
                    pass
            
            cursor.close()
            conn.close()
            
            return table_info
        except Exception as e:
            return {"错误": str(e)}
    
    def get_stock_count(self) -> Dict:
        """获取股票统计"""
        try:
            import psycopg2
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            
            # 总股票数
            cursor.execute("SELECT COUNT(*) FROM stocks")
            total = cursor.fetchone()[0]
            
            # 主板股票数
            cursor.execute("""
                SELECT COUNT(*) FROM stocks 
                WHERE ts_code LIKE '6%%' OR ts_code LIKE '000%%' 
                   OR ts_code LIKE '002%%'
            """)
            mainboard = cursor.fetchone()[0]
            
            # 价格数据量
            cursor.execute("SELECT COUNT(*) FROM stock_prices")
            prices = cursor.fetchone()[0]
            
            cursor.close()
            conn.close()
            
            return {
                "总股票数": total,
                "主板股票数": mainboard,
                "价格数据量": prices,
            }
        except Exception as e:
            return {"错误": str(e)}


# ============================================================
# 便捷函数
# ============================================================

def check_data_quality(df: pd.DataFrame) -> Dict:
    """检查数据质量"""
    checker = DataQualityChecker(df)
    return checker.run_all_checks()


def check_model_performance(model_path: str, X_test: np.ndarray, 
                           y_test: np.ndarray) -> Dict:
    """检查模型性能"""
    diag = ModelDiagnostics()
    if not diag.load_model(model_path):
        return {}
    
    y_pred = diag.model.predict(X_test)
    y_proba = diag.model.predict_proba(X_test)[:, 1]
    
    return diag.analyze_predictions(y_test, y_pred, y_proba)


def check_database(db_config: Optional[Dict] = None) -> Dict:
    """检查数据库"""
    diag = DatabaseDiagnostics(db_config)
    
    result = {
        "连接测试": diag.test_connection(),
        "表信息": diag.get_table_info(),
        "股票统计": diag.get_stock_count(),
    }
    
    return result


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("诊断工具测试")
    print("=" * 60)
    
    # 测试数据库连接
    print("\n1. 数据库诊断:")
    db_result = check_database()
    print(f"  连接状态: {db_result['连接测试']['连接状态']}")
    if "股票统计" in db_result and "错误" not in db_result["股票统计"]:
        print(f"  总股票数: {db_result['股票统计']['总股票数']}")
        print(f"  主板股票数: {db_result['股票统计']['主板股票数']}")
    
    # 测试数据质量检查
    print("\n2. 数据质量检查 (测试数据):")
    test_df = pd.DataFrame({
        'A': [1, 2, 3, 4, 5, None, 7, 8, 9, 10],
        'B': [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
        'C': ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'],
    })
    
    checker = DataQualityChecker(test_df)
    report = checker.run_all_checks()
    print(f"  质量评分: {report['质量评分']}/100")
    print(f"  缺失值: {report['缺失值检查']['缺失列数']}列")
    
    print("\n" + "=" * 60)
    print("测试完成")

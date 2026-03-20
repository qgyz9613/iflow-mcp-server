/**
 * MMR (Maximal Marginal Relevance) Re-ranking Module
 * 基于OpenClaw mmr.ts设计
 * 平衡相关性与多样性，避免搜索结果过于相似
 * 
 * MMR公式: λ * relevance - (1-λ) * max_similarity_to_selected
 * 参考论文: Carbonell & Goldstein (1998) "The Use of MMR, Diversity-Based Reranking"
 */

// ==================== 类型定义 ====================

/**
 * MMR项目类型
 */
class MMRItem {
  constructor({ id, score, content, metadata = {} }) {
    this.id = id;
    this.score = score;
    this.content = content;
    this.metadata = metadata;
  }
}

/**
 * MMR配置
 */
const DEFAULT_MMR_CONFIG = {
  enabled: false,       // 默认关闭，需显式启用
  lambda: 0.7,          // λ参数: 0=最大多样性, 1=最大相关性
  maxResults: 20,       // 最大返回结果数
  similarityThreshold: 0.9,  // 相似度阈值，超过则视为重复
};

// ==================== 核心函数 ====================

/**
 * 文本分词（用于Jaccard相似度）
 * 提取字母数字和下划线，转小写
 */
function tokenize(text) {
  if (!text || typeof text !== 'string') {
    return new Set();
  }
  const tokens = text.toLowerCase().match(/[a-z0-9_\u4e00-\u9fff]+/g) ?? [];
  return new Set(tokens);
}

/**
 * 计算Jaccard相似度
 * 两个集合的交集/并集
 */
function jaccardSimilarity(setA, setB) {
  if (setA.size === 0 && setB.size === 0) {
    return 1;
  }
  if (setA.size === 0 || setB.size === 0) {
    return 0;
  }

  let intersectionSize = 0;
  const smaller = setA.size <= setB.size ? setA : setB;
  const larger = setA.size <= setB.size ? setB : setA;

  for (const token of smaller) {
    if (larger.has(token)) {
      intersectionSize++;
    }
  }

  const unionSize = setA.size + setB.size - intersectionSize;
  return unionSize === 0 ? 0 : intersectionSize / unionSize;
}

/**
 * 计算文本相似度
 */
function textSimilarity(contentA, contentB) {
  return jaccardSimilarity(tokenize(contentA), tokenize(contentB));
}

/**
 * 计算与已选项目的最大相似度
 */
function maxSimilarityToSelected(item, selectedItems, tokenCache) {
  if (selectedItems.length === 0) {
    return 0;
  }

  let maxSim = 0;
  const itemTokens = tokenCache.get(item.id) ?? tokenize(item.content);

  for (const selected of selectedItems) {
    const selectedTokens = tokenCache.get(selected.id) ?? tokenize(selected.content);
    const sim = jaccardSimilarity(itemTokens, selectedTokens);
    if (sim > maxSim) {
      maxSim = sim;
    }
  }

  return maxSim;
}

/**
 * 计算MMR分数
 * MMR = λ * relevance - (1-λ) * max_similarity_to_selected
 */
function computeMMRScore(relevance, maxSimilarity, lambda) {
  return lambda * relevance - (1 - lambda) * maxSimilarity;
}

/**
 * MMR重排序主函数
 * 
 * 算法流程:
 * 1. 从最高分项目开始
 * 2. 迭代选择使MMR分数最大的项目
 * 3. 平衡相关性与多样性
 * 
 * @param {Array<MMRItem>} items - 待重排序的项目
 * @param {Object} config - MMR配置
 * @returns {Array<MMRItem>} 重排序后的项目
 */
function mmrRerank(items, config = {}) {
  const { 
    enabled = DEFAULT_MMR_CONFIG.enabled, 
    lambda = DEFAULT_MMR_CONFIG.lambda,
    maxResults = DEFAULT_MMR_CONFIG.maxResults 
  } = config;

  // 未启用或项目太少，直接返回
  if (!enabled || items.length <= 1) {
    return [...items];
  }

  // 限制lambda范围
  const clampedLambda = Math.max(0, Math.min(1, lambda));

  // lambda=1时，只按相关性排序（无多样性惩罚）
  if (clampedLambda === 1) {
    return [...items].sort((a, b) => b.score - a.score);
  }

  // 预分词所有项目，提高效率
  const tokenCache = new Map();
  for (const item of items) {
    tokenCache.set(item.id, tokenize(item.content));
  }

  // 归一化分数到[0,1]范围
  const maxScore = Math.max(...items.map(i => i.score));
  const minScore = Math.min(...items.map(i => i.score));
  const scoreRange = maxScore - minScore;

  const normalizeScore = (score) => {
    if (scoreRange === 0) {
      return 1; // 所有分数相等
    }
    return (score - minScore) / scoreRange;
  };

  const selected = [];
  const remaining = new Set(items);

  // 迭代选择
  while (remaining.size > 0 && selected.length < maxResults) {
    let bestItem = null;
    let bestMMRScore = -Infinity;

    for (const candidate of remaining) {
      const normalizedRelevance = normalizeScore(candidate.score);
      const maxSim = maxSimilarityToSelected(candidate, selected, tokenCache);
      const mmrScore = computeMMRScore(normalizedRelevance, maxSim, clampedLambda);

      // 使用原始分数作为tiebreaker
      if (
        mmrScore > bestMMRScore ||
        (mmrScore === bestMMRScore && candidate.score > (bestItem?.score ?? -Infinity))
      ) {
        bestMMRScore = mmrScore;
        bestItem = candidate;
      }
    }

    if (bestItem) {
      selected.push(bestItem);
      remaining.delete(bestItem);
    } else {
      break; // 安全退出
    }
  }

  return selected;
}

/**
 * 应用MMR到混合搜索结果
 */
function applyMMRToHybridResults(results, config = {}) {
  if (results.length === 0) {
    return results;
  }

  // 创建ID到原始项目的映射
  const itemById = new Map();

  // 创建MMR项目
  const mmrItems = results.map((r, index) => {
    const id = r.id || `${r.path || 'unknown'}:${r.startLine || 0}:${index}`;
    itemById.set(id, r);
    return new MMRItem({
      id,
      score: r.score,
      content: r.snippet || r.text || r.content || '',
      metadata: r.metadata || {}
    });
  });

  const reranked = mmrRerank(mmrItems, config);

  // 映射回原始项目
  return reranked.map(item => {
    const original = itemById.get(item.id);
    return {
      ...original,
      mmrScore: item.score,
      mmrApplied: true
    };
  });
}

/**
 * 应用MMR到记忆搜索结果
 */
function applyMMRToMemoryResults(results, config = {}) {
  if (results.length === 0) {
    return results;
  }

  const itemById = new Map();

  const mmrItems = results.map((r, index) => {
    const id = r.id || `memory:${index}`;
    itemById.set(id, r);
    return new MMRItem({
      id,
      score: r.score || r.relevance || 0,
      content: r.content || r.text || '',
      metadata: r.metadata || {}
    });
  });

  const reranked = mmrRerank(mmrItems, config);

  return reranked.map(item => {
    const original = itemById.get(item.id);
    return {
      ...original,
      mmrScore: item.score,
      mmrApplied: true
    };
  });
}

/**
 * 计算结果集的多样性得分
 */
function calculateDiversityScore(items) {
  if (items.length <= 1) {
    return 1;
  }

  const tokenCache = new Map();
  for (const item of items) {
    tokenCache.set(item.id, tokenize(item.content));
  }

  let totalSimilarity = 0;
  let pairCount = 0;

  for (let i = 0; i < items.length; i++) {
    for (let j = i + 1; j < items.length; j++) {
      const sim = jaccardSimilarity(
        tokenCache.get(items[i].id),
        tokenCache.get(items[j].id)
      );
      totalSimilarity += sim;
      pairCount++;
    }
  }

  // 多样性 = 1 - 平均相似度
  const avgSimilarity = pairCount > 0 ? totalSimilarity / pairCount : 0;
  return 1 - avgSimilarity;
}

// ==================== 导出 ====================

module.exports = {
  // 类
  MMRItem,
  
  // 配置
  DEFAULT_MMR_CONFIG,
  
  // 核心函数
  tokenize,
  jaccardSimilarity,
  textSimilarity,
  computeMMRScore,
  mmrRerank,
  
  // 应用函数
  applyMMRToHybridResults,
  applyMMRToMemoryResults,
  calculateDiversityScore
};

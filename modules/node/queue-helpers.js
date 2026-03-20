/**
 * Queue Helpers Module
 * 队列管理系统，支持丢弃策略、防抖、排空、摘要等
 * 整合自 OpenClaw queue-helpers.ts
 */

// ===== Queue State Management =====

/**
 * 清除队列摘要状态
 * @param {Object} state - 队列状态
 */
function clearQueueSummaryState(state) {
  state.droppedCount = 0;
  state.summaryLines = [];
}

/**
 * 省略队列文本
 * @param {string} text - 文本
 * @param {number} limit - 限制长度
 * @returns {string} 省略后的文本
 */
function elideQueueText(text, limit = 140) {
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

/**
 * 构建队列摘要行
 * @param {string} text - 文本
 * @param {number} limit - 限制长度
 * @returns {string} 摘要行
 */
function buildQueueSummaryLine(text, limit = 160) {
  const cleaned = text.replace(/\s+/g, ' ').trim();
  return elideQueueText(cleaned, limit);
}

// ===== Queue Drop Policy =====

/**
 * 应用队列丢弃策略
 * @param {Object} params - 参数
 * @returns {boolean} 是否应该添加项目
 */
function applyQueueDropPolicy(params) {
  const cap = params.queue.cap;
  if (cap <= 0 || params.queue.items.length < cap) {
    return true;
  }
  if (params.queue.dropPolicy === 'new') {
    return false;
  }
  const dropCount = params.queue.items.length - cap + 1;
  const dropped = params.queue.items.splice(0, dropCount);
  if (params.queue.dropPolicy === 'summarize') {
    for (const item of dropped) {
      params.queue.droppedCount += 1;
      params.queue.summaryLines.push(buildQueueSummaryLine(params.summarize(item)));
    }
    const limit = Math.max(0, params.summaryLimit ?? cap);
    while (params.queue.summaryLines.length > limit) {
      params.queue.summaryLines.shift();
    }
  }
  // 返回 true 表示应该继续添加（已经腾出空间）
  return true;
}

/**
 * 构建队列摘要提示
 * @param {Object} params - 参数
 * @returns {string|undefined} 摘要提示
 */
function buildQueueSummaryPrompt(params) {
  if (params.state.dropPolicy !== 'summarize' || params.state.droppedCount <= 0) {
    return undefined;
  }
  const noun = params.noun;
  const title =
    params.title ??
    `[Queue overflow] Dropped ${params.state.droppedCount} ${noun}${params.state.droppedCount === 1 ? '' : 's'} due to cap.`;
  const lines = [title];
  if (params.state.summaryLines.length > 0) {
    lines.push('Summary:');
    for (const line of params.state.summaryLines) {
      lines.push(`- ${line}`);
    }
  }
  clearQueueSummaryState(params.state);
  return lines.join('\n');
}

// ===== Queue Debounce =====

/**
 * 等待队列防抖
 * @param {Object} queue - 队列对象
 * @returns {Promise<void>}
 */
function waitForQueueDebounce(queue) {
  if (process.env.OPENCLAW_TEST_FAST === '1') {
    return Promise.resolve();
  }
  const debounceMs = Math.max(0, queue.debounceMs);
  if (debounceMs <= 0) {
    return Promise.resolve();
  }
  return new Promise(resolve => {
    const check = () => {
      const since = Date.now() - queue.lastEnqueuedAt;
      if (since >= debounceMs) {
        resolve();
        return;
      }
      setTimeout(check, debounceMs - since);
    };
    check();
  });
}

// ===== Queue Drain =====

/**
 * 开始排空队列
 * @param {Map} map - 队列映射
 * @param {string} key - 键
 * @returns {Object|undefined} 队列对象
 */
function beginQueueDrain(map, key) {
  const queue = map.get(key);
  if (!queue || queue.draining) {
    return undefined;
  }
  queue.draining = true;
  return queue;
}

/**
 * 排空下一个队列项
 * @param {Array} items - 项目列表
 * @param {Function} run - 运行函数
 * @returns {Promise<boolean>} 是否成功排空
 */
async function drainNextQueueItem(items, run) {
  const next = items[0];
  if (!next) {
    return false;
  }
  await run(next);
  items.shift();
  return true;
}

// ===== Queue Collection =====

/**
 * 构建收集提示
 * @param {Object} params - 参数
 * @returns {string} 收集提示
 */
function buildCollectPrompt(params) {
  const blocks = [params.title];
  if (params.summary) {
    blocks.push(params.summary);
  }
  params.items.forEach((item, idx) => {
    blocks.push(params.renderItem(item, idx));
  });
  return blocks.join('\n\n');
}

/**
 * 检查是否有跨频道项目
 * @param {Array} items - 项目列表
 * @param {Function} resolveKey - 解析键函数
 * @returns {boolean} 是否有跨频道项目
 */
function hasCrossChannelItems(items, resolveKey) {
  const keys = new Set();
  let hasUnkeyed = false;

  for (const item of items) {
    const resolved = resolveKey(item);
    if (resolved.cross) {
      return true;
    }
    if (!resolved.key) {
      hasUnkeyed = true;
      continue;
    }
    keys.add(resolved.key);
  }

  if (keys.size === 0) {
    return false;
  }
  if (hasUnkeyed) {
    return true;
  }
  return keys.size > 1;
}

// ===== Queue Helpers =====

/**
 * 预览队列摘要提示
 * @param {Object} params - 参数
 * @returns {string|undefined} 摘要提示
 */
function previewQueueSummaryPrompt(params) {
  return buildQueueSummaryPrompt({
    state: {
      dropPolicy: params.state.dropPolicy,
      droppedCount: params.state.droppedCount,
      summaryLines: [...params.state.summaryLines]
    },
    noun: params.noun,
    title: params.title
  });
}

/**
 * 跳过队列项目
 * @param {Object} params - 参数
 * @returns {boolean} 是否应该跳过
 */
function shouldSkipQueueItem(params) {
  if (!params.dedupe) {
    return false;
  }
  return params.dedupe(params.item, params.items);
}

module.exports = {
  clearQueueSummaryState,
  elideQueueText,
  buildQueueSummaryLine,
  applyQueueDropPolicy,
  buildQueueSummaryPrompt,
  waitForQueueDebounce,
  beginQueueDrain,
  drainNextQueueItem,
  buildCollectPrompt,
  hasCrossChannelItems,
  previewQueueSummaryPrompt,
  shouldSkipQueueItem
};
/**
 * Fetch Enhanced Module
 * 增强的 Fetch 功能，支持 AbortSignal、预连接等
 * 整合自 OpenClaw fetch.ts 和 fetch-timeout.ts
 */

// ===== Abort Relay =====
function relayAbort() {
  this.abort();
}

function bindAbortRelay(controller) {
  return relayAbort.bind(controller);
}

// ===== Fetch with Timeout =====

/**
 * 带超时的 Fetch 包装器
 * @param {string} url - 要获取的 URL
 * @param {RequestInit} init - 请求选项
 * @param {number} timeoutMs - 超时时间
 * @param {Function} fetchFn - Fetch 实现（默认为全局 fetch）
 * @returns {Promise<Response>} Fetch 响应
 * @throws {Error} 如果请求超时
 */
async function fetchWithTimeout(url, init, timeoutMs, fetchFn = globalThis.fetch) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1, timeoutMs));
  try {
    return await fetchFn(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

// ===== Fetch with AbortSignal Wrapper =====

const wrapFetchWithAbortSignalMarker = Symbol.for("iflow.fetch.abort-signal-wrapped");

function withDuplex(init, input) {
  const hasInitBody = init?.body != null;
  const hasRequestBody =
    !hasInitBody &&
    typeof Request !== "undefined" &&
    input instanceof Request &&
    input.body != null;
  if (!hasInitBody && !hasRequestBody) {
    return init;
  }
  if (init && "duplex" in init) {
    return init;
  }
  return init
    ? { ...init, duplex: "half" }
    : { duplex: "half" };
}

/**
 * 包装 Fetch 以支持 AbortSignal
 * @param {Function} fetchImpl - Fetch 实现
 * @returns {Function} 包装后的 Fetch
 */
function wrapFetchWithAbortSignal(fetchImpl) {
  if (fetchImpl?.[wrapFetchWithAbortSignalMarker]) {
    return fetchImpl;
  }

  const wrapped = (input, init) => {
    const patchedInit = withDuplex(init, input);
    const signal = patchedInit?.signal;
    if (!signal) {
      return fetchImpl(input, patchedInit);
    }
    if (typeof AbortSignal !== "undefined" && signal instanceof AbortSignal) {
      return fetchImpl(input, patchedInit);
    }
    if (typeof AbortController === "undefined") {
      return fetchImpl(input, patchedInit);
    }
    if (typeof signal.addEventListener !== "function") {
      return fetchImpl(input, patchedInit);
    }
    const controller = new AbortController();
    const onAbort = bindAbortRelay(controller);
    let listenerAttached = false;
    if (signal.aborted) {
      controller.abort();
    } else {
      signal.addEventListener("abort", onAbort, { once: true });
      listenerAttached = true;
    }
    const cleanup = () => {
      if (!listenerAttached || typeof signal.removeEventListener !== "function") {
        return;
      }
      listenerAttached = false;
      try {
        signal.removeEventListener("abort", onAbort);
      } catch {
        // 外部/自定义 AbortSignal 实现可能会抛出错误
        // 永远不要让清理掩盖原始 fetch 结果/错误
      }
    };
    try {
      const response = fetchImpl(input, { ...patchedInit, signal: controller.signal });
      return response.finally(cleanup);
    } catch (error) {
      cleanup();
      throw error;
    }
  };

  // 复制原始 fetch 的属性
  Object.assign(wrapped, fetchImpl);

  Object.defineProperty(wrapped, wrapFetchWithAbortSignalMarker, {
    value: true,
    enumerable: false,
    configurable: false,
    writable: false,
  });

  return wrapped;
}

/**
 * 解析 Fetch 实现
 * @param {Function} fetchImpl - Fetch 实现（可选）
 * @returns {Function|undefined} 解析后的 Fetch
 */
function resolveFetch(fetchImpl) {
  const resolved = fetchImpl ?? globalThis.fetch;
  if (!resolved) {
    return undefined;
  }
  return wrapFetchWithAbortSignal(resolved);
}

// ===== Helper Functions =====

/**
 * 创建预连接 Fetch
 * @param {Function} fetchImpl - Fetch 实现
 * @returns {Function} 带预连接功能的 Fetch
 */
function createFetchWithPreconnect(fetchImpl) {
  const wrapped = wrapFetchWithAbortSignal(fetchImpl || globalThis.fetch);
  wrapped.preconnect = () => {}; // 占位符，可扩展
  return wrapped;
}

// ===== Enhanced Fetch Instance =====
let enhancedFetchInstance = null;

/**
 * 获取增强的 Fetch 实例
 * @returns {Function} 增强的 Fetch
 */
function getEnhancedFetch() {
  if (!enhancedFetchInstance) {
    enhancedFetchInstance = resolveFetch(globalThis.fetch);
  }
  return enhancedFetchInstance;
}

/**
 * 设置自定义 Fetch 实现
 * @param {Function} fetchImpl - Fetch 实现
 */
function setEnhancedFetch(fetchImpl) {
  enhancedFetchInstance = resolveFetch(fetchImpl);
}

// ===== CommonJS Export =====
module.exports = {
  fetchWithTimeout,
  wrapFetchWithAbortSignal,
  resolveFetch,
  createFetchWithPreconnect,
  getEnhancedFetch,
  setEnhancedFetch,
  bindAbortRelay,
};
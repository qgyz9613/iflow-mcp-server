/**
 * Requirements Eval Module
 * 需求评估系统，支持 bins/env/config/os 需求检查
 * 整合自 OpenClaw requirements.ts
 */

// ===== Resolve Missing Requirements =====

/**
 * 解析缺失的二进制文件
 * @param {Object} params - 参数
 * @returns {string[]} 缺失的二进制文件列表
 */
function resolveMissingBins(params) {
  const remote = params.hasRemoteBin;
  return params.required.filter(bin => {
    if (params.hasLocalBin(bin)) {
      return false;
    }
    if (remote?.(bin)) {
      return false;
    }
    return true;
  });
}

/**
 * 解析缺失的任意二进制文件
 * @param {Object} params - 参数
 * @returns {string[]} 缺失的二进制文件列表
 */
function resolveMissingAnyBins(params) {
  if (params.required.length === 0) {
    return [];
  }
  // 如果任意一个本地二进制文件存在，则不返回缺失
  if (params.required.some(bin => params.hasLocalBin(bin))) {
    return [];
  }
  // 如果远程检查中有任意一个存在，则不返回缺失
  if (params.hasRemoteAnyBin && params.hasRemoteAnyBin(params.required)) {
    return [];
  }
  return params.required;
}

/**
 * 解析缺失的 OS 平台
 * @param {Object} params - 参数
 * @returns {string[]} 缺失的 OS 平台列表
 */
function resolveMissingOs(params) {
  if (params.required.length === 0) {
    return [];
  }
  if (params.required.includes(params.localPlatform)) {
    return [];
  }
  if (params.remotePlatforms?.some(platform => params.required.includes(platform))) {
    return [];
  }
  return params.required;
}

/**
 * 解析缺失的环境变量
 * @param {Object} params - 参数
 * @returns {string[]} 缺失的环境变量列表
 */
function resolveMissingEnv(params) {
  const missing = [];
  for (const envName of params.required) {
    if (params.isSatisfied(envName)) {
      continue;
    }
    missing.push(envName);
  }
  return missing;
}

/**
 * 构建配置检查列表
 * @param {Object} params - 参数
 * @returns {Array} 配置检查列表
 */
function buildConfigChecks(params) {
  return params.required.map(pathStr => {
    const satisfied = params.isSatisfied(pathStr);
    return { path: pathStr, satisfied };
  });
}

// ===== Evaluate Requirements =====

/**
 * 评估需求
 * @param {Object} params - 参数
 * @returns {Object} 评估结果
 */
function evaluateRequirements(params) {
  const missingBins = resolveMissingBins({
    required: params.required.bins,
    hasLocalBin: params.hasLocalBin,
    hasRemoteBin: params.hasRemoteBin
  });
  
  const missingAnyBins = resolveMissingAnyBins({
    required: params.required.anyBins,
    hasLocalBin: params.hasLocalBin,
    hasRemoteAnyBin: params.hasRemoteAnyBin
  });
  
  const missingOs = resolveMissingOs({
    required: params.required.os,
    localPlatform: params.localPlatform,
    remotePlatforms: params.remotePlatforms
  });
  
  const missingEnv = resolveMissingEnv({
    required: params.required.env,
    isSatisfied: params.isEnvSatisfied
  });
  
  const configChecks = buildConfigChecks({
    required: params.required.config,
    isSatisfied: params.isConfigSatisfied
  });
  
  const missingConfig = configChecks.filter(check => !check.satisfied).map(check => check.path);

  const missing = params.always
    ? { bins: [], anyBins: [], env: [], config: [], os: [] }
    : {
        bins: missingBins,
        anyBins: missingAnyBins,
        env: missingEnv,
        config: missingConfig,
        os: missingOs
      };

  const eligible =
    params.always ||
    (missing.bins.length === 0 &&
      missing.anyBins.length === 0 &&
      missing.env.length === 0 &&
      missing.config.length === 0 &&
      missing.os.length === 0);

  return { missing, eligible, configChecks };
}

/**
 * 从元数据评估需求
 * @param {Object} params - 参数
 * @returns {Object} 评估结果
 */
function evaluateRequirementsFromMetadata(params) {
  const required = {
    bins: params.metadata?.requires?.bins ?? [],
    anyBins: params.metadata?.requires?.anyBins ?? [],
    env: params.metadata?.requires?.env ?? [],
    config: params.metadata?.requires?.config ?? [],
    os: params.metadata?.os ?? []
  };

  const result = evaluateRequirements({
    always: params.always,
    required,
    hasLocalBin: params.hasLocalBin,
    hasRemoteBin: params.hasRemoteBin,
    hasRemoteAnyBin: params.hasRemoteAnyBin,
    localPlatform: params.localPlatform,
    remotePlatforms: params.remotePlatforms,
    isEnvSatisfied: params.isEnvSatisfied,
    isConfigSatisfied: params.isConfigSatisfied
  });
  
  return { required, ...result };
}

/**
 * 从元数据评估需求（支持远程）
 * @param {Object} params - 参数
 * @returns {Object} 评估结果
 */
function evaluateRequirementsFromMetadataWithRemote(params) {
  return evaluateRequirementsFromMetadata({
    always: params.always,
    metadata: params.metadata,
    hasLocalBin: params.hasLocalBin,
    hasRemoteBin: params.remote?.hasBin,
    hasRemoteAnyBin: params.remote?.hasAnyBin,
    localPlatform: params.localPlatform,
    remotePlatforms: params.remote?.platforms,
    isEnvSatisfied: params.isEnvSatisfied,
    isConfigSatisfied: params.isConfigSatisfied
  });
}

module.exports = {
  resolveMissingBins,
  resolveMissingAnyBins,
  resolveMissingOs,
  resolveMissingEnv,
  buildConfigChecks,
  evaluateRequirements,
  evaluateRequirementsFromMetadata,
  evaluateRequirementsFromMetadataWithRemote
};
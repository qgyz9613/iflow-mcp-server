/**
 * Runtime Env Module
 * 运行时环境解析和管理
 * 整合自 OpenClaw runtime.ts
 */

const util = require('util');

/**
 * 创建基于日志的运行时环境
 * @param {Object} params - 参数
 * @returns {Object} 运行时环境对象
 */
function createLoggerBackedRuntime(params) {
  return {
    log: (...args) => {
      params.logger.info(util.format(...args));
    },
    error: (...args) => {
      params.logger.error(util.format(...args));
    },
    exit: (code) => {
      throw params.exitError?.(code) ?? new Error(`exit ${code}`);
    }
  };
}

/**
 * 解析运行时环境
 * @param {Object} params - 参数
 * @returns {Object} 运行时环境对象
 */
function resolveRuntimeEnv(params) {
  return params.runtime ?? createLoggerBackedRuntime(params);
}

/**
 * 解析运行时环境（不可用退出）
 * @param {Object} params - 参数
 * @returns {Object} 运行时环境对象
 */
function resolveRuntimeEnvWithUnavailableExit(params) {
  return resolveRuntimeEnv({
    runtime: params.runtime,
    logger: params.logger,
    exitError: () => new Error(params.unavailableMessage ?? 'Runtime exit not available')
  });
}

module.exports = {
  createLoggerBackedRuntime,
  resolveRuntimeEnv,
  resolveRuntimeEnvWithUnavailableExit
};
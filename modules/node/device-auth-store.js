const deviceAuth = require('./device-auth.js');

function loadDeviceAuthTokenFromStore(params) {
  const store = params.adapter.readStore();
  if (!store || store.deviceId !== params.deviceId) {
    return null;
  }
  const role = deviceAuth.normalizeDeviceAuthRole(params.role);
  const entry = store.tokens[role];
  if (!entry || typeof entry.token !== 'string') {
    return null;
  }
  return entry;
}

function storeDeviceAuthTokenInStore(params) {
  const role = deviceAuth.normalizeDeviceAuthRole(params.role);
  const existing = params.adapter.readStore();
  const next = {
    version: 1,
    deviceId: params.deviceId,
    tokens:
      existing && existing.deviceId === params.deviceId && existing.tokens
        ? { ...existing.tokens }
        : {},
  };
  const entry = {
    token: params.token,
    role,
    scopes: deviceAuth.normalizeDeviceAuthScopes(params.scopes),
    updatedAtMs: Date.now(),
  };
  next.tokens[role] = entry;
  params.adapter.writeStore(next);
  return entry;
}

function clearDeviceAuthTokenFromStore(params) {
  const store = params.adapter.readStore();
  if (!store || store.deviceId !== params.deviceId) {
    return;
  }
  const role = deviceAuth.normalizeDeviceAuthRole(params.role);
  if (!store.tokens[role]) {
    return;
  }
  const next = {
    version: 1,
    deviceId: store.deviceId,
    tokens: { ...store.tokens },
  };
  delete next.tokens[role];
  params.adapter.writeStore(next);
}

module.exports = {
  loadDeviceAuthTokenFromStore,
  storeDeviceAuthTokenInStore,
  clearDeviceAuthTokenFromStore,
};
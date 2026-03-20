// 测试模块加载
console.log('=== Testing iFlow Modules ===\n');

// 1. 测试 Hooks
try {
  const hooks = require('./modules/hooks');
  const types = hooks.getTypes();
  console.log('✅ Hooks Module: OK');
  console.log('   - Hook types:', types.types.length);
  console.log('   - Test registration:', hooks.register('test', () => {}).status);
} catch (e) {
  console.log('❌ Hooks Module: FAILED -', e.message);
}

// 2. 测试 Skills
try {
  const skills = require('./modules/skills');
  const result = skills.list();
  console.log('\n✅ Skills Module: OK');
  console.log('   - Status:', result.status);
  console.log('   - Total skills:', result.total);
} catch (e) {
  console.log('\n❌ Skills Module: FAILED -', e.message);
}

// 3. 测试 Subagent
try {
  const subagent = require('./modules/subagent');
  const templates = subagent.templates();
  console.log('\n✅ Subagent Module: OK');
  console.log('   - Templates:', templates.templates.length);
  console.log('   - Complexity levels:', Object.keys(templates.effortScaling).length);
} catch (e) {
  console.log('\n❌ Subagent Module: FAILED -', e.message);
}

// 4. 测试 Heartbeat
try {
  const heartbeat = require('./modules/heartbeat');
  const health = heartbeat.healthCheck();
  console.log('\n✅ Heartbeat Module: OK');
  console.log('   - Status:', health.status);
  console.log('   - Active skills:', health.health?.skillsActive || 0);
  console.log('   - Interval running:', health.health?.intervalRunning);
} catch (e) {
  console.log('\n❌ Heartbeat Module: FAILED -', e.message);
}

// 5. 测试 Memory Index
try {
  const fs = require('fs');
  const indexPath = '../memory/index.json';
  if (fs.existsSync(indexPath)) {
    const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));
    console.log('\n✅ Memory Index: OK');
    console.log('   - Total entries:', Object.keys(index).length);
    const facts = Object.values(index).filter(x => x.category === 'fact').length;
    console.log('   - Facts:', facts);
  } else {
    console.log('\n⚠️ Memory Index: Not found');
  }
} catch (e) {
  console.log('\n❌ Memory Index: FAILED -', e.message);
}

console.log('\n=== Test Complete ===');
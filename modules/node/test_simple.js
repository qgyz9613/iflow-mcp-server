// 简化测试 - 避免模块加载阻塞
console.log('=== Simple Module Test ===\n');

const fs = require('fs');
const path = require('path');

// 1. 测试文件结构
const modulesDir = path.join(__dirname, 'modules');
const files = fs.readdirSync(modulesDir).filter(f => f.endsWith('.js'));
console.log('✅ Module files found:', files.length);
console.log('   Files:', files.slice(0, 10).join(', '));

// 2. 测试 hooks.js (独立模块)
try {
  const hooks = require('./modules/hooks');
  console.log('\n✅ Hooks: OK');
  console.log('   - Types:', hooks.getTypes().types.length);
} catch (e) {
  console.log('\n❌ Hooks:', e.message);
}

// 3. 测试 skills.js (独立模块)
try {
  const skills = require('./modules/skills');
  console.log('\n✅ Skills: OK');
  console.log('   - List status:', skills.list().status);
} catch (e) {
  console.log('\n❌ Skills:', e.message);
}

// 4. 测试 cron.js (独立模块)
try {
  const cron = require('./modules/heartbeat-cron');
  const parsed = cron.parseCronExpression('0 9 * * 1-5');
  console.log('\n✅ Cron: OK');
  console.log('   - Parsed:', parsed !== null);
} catch (e) {
  console.log('\n❌ Cron:', e.message);
}

// 5. 测试记忆系统
try {
  const indexPath = path.join(__dirname, '..', '..', 'memory', 'index.json');
  if (fs.existsSync(indexPath)) {
    const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'));
    console.log('\n✅ Memory Index: OK');
    console.log('   - Entries:', Object.keys(index).length);
    const facts = Object.values(index).filter(x => x.category === 'fact').length;
    console.log('   - Facts:', facts);
  } else {
    console.log('\n⚠️ Memory Index: Not found at', indexPath);
  }
} catch (e) {
  console.log('\n❌ Memory Index:', e.message);
}

console.log('\n=== Test Complete ===');
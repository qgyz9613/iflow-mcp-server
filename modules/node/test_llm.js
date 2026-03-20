// 测试 LLM 模块
console.log('=== LLM Module Test ===\n');

try {
  const llm = require('./modules/llm');
  console.log('✅ LLM Module: OK');
  console.log('   - Providers:', Object.keys(llm.providers).length);
  console.log('   - Cache stats:', llm.cacheStats().status);
  console.log('   - Main functions:', ['invoke', 'stream', 'batch', 'embed'].join(', '));
} catch (e) {
  console.log('❌ LLM Module:', e.message);
  console.log('   Stack:', e.stack?.split('\n')[0]);
}

console.log('\n=== Test Complete ===');
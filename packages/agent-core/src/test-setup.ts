// packages/agent-core/src/test-setup.ts
import 'dotenv/config';
import Anthropic from '@anthropic-ai/sdk';
import pg from 'pg';
const { Client } = pg;

async function testSetup() {
  console.log('🧪 Testing Development Environment Setup...\n');

  // Test 1: Environment Variables
  console.log('1️⃣ Checking environment variables...');
  console.log('DATABASE_URL:', process.env.DATABASE_URL);
  console.log('API Key present:', !!process.env.ANTHROPIC_API_KEY);
  
  if (!process.env.ANTHROPIC_API_KEY) {
    console.error('❌ ANTHROPIC_API_KEY not found in .env');
    process.exit(1);
  }
  console.log('✅ Environment variables loaded\n');

  // Test 2: Database Connection (with explicit config)
  console.log('2️⃣ Testing database connection...');
  try {
    const dbClient = new Client({
      host: 'localhost',
      port: 5432,
      database: 'ai_platform',
      user: 'dev',
      password: 'devpass',  // Explicit password
    });
    
    await dbClient.connect();
    const result = await dbClient.query('SELECT NOW()');
    console.log('✅ Database connected:', result.rows[0].now);
    
    // Check extensions
    const extensions = await dbClient.query("SELECT * FROM pg_extension WHERE extname IN ('uuid-ossp', 'vector')");
    console.log(`✅ Extensions installed: ${extensions.rows.length}/2`);
    
    await dbClient.end();
  } catch (error) {
    console.error('❌ Database connection failed:', error);
    process.exit(1);
  }
  console.log('');

  // Test 3: Claude API
  console.log('3️⃣ Testing Claude API connection...');
  try {
    const client = new Anthropic({
      apiKey: process.env.ANTHROPIC_API_KEY,
    });
    
    const response = await client.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 100,
      messages: [
        { role: 'user', content: 'Say "Setup working!" if you can read this.' }
      ],
    });
    
    const text = response.content[0].type === 'text' ? response.content[0].text : '';
    console.log('✅ Claude API response:', text);
  } catch (error) {
    console.error('❌ Claude API connection failed:', error);
    process.exit(1);
  }
  console.log('');

  console.log('🎉 All tests passed! Development environment is ready.\n');
}

testSetup().catch(console.error);
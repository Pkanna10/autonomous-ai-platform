import Anthropic from '@anthropic-ai/sdk';

export class ClaudeClient {
  private client: Anthropic;
  
  constructor() {
    this.client = new Anthropic({
      apiKey: process.env.ANTHROPIC_API_KEY,
    });
  }
  
  async chat(
    messages: Anthropic.MessageParam[],
    options?: {
      model?: string;
      maxTokens?: number;
      temperature?: number;
      systemPrompt?: string;
    }
  ) {
    const response = await this.client.messages.create({
      model: options?.model || 'claude-sonnet-4-20250514',
      max_tokens: options?.maxTokens || 4096,
      temperature: options?.temperature || 0,
      system: options?.systemPrompt,
      messages,
    });
    
    return response;
  }
  
  // Streaming for real-time responses
  async streamChat(
    messages: Anthropic.MessageParam[],
    onChunk: (text: string) => void
  ) {
    const stream = await this.client.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 4096,
      messages,
      stream: true,
    });
    
    for await (const event of stream) {
      if (event.type === 'content_block_delta' && 
          event.delta.type === 'text_delta') {
        onChunk(event.delta.text);
      }
    }
  }
}

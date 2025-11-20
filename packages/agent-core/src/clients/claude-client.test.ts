import type Anthropic from '@anthropic-ai/sdk';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ClaudeClient } from './claude-client';

// Mock the Anthropic SDK
const mockCreate = vi.fn();
vi.mock('@anthropic-ai/sdk', () => {
  return {
    default: class MockAnthropic {
      messages = {
        create: mockCreate,
      };
    },
  };
});

describe('ClaudeClient', () => {
  beforeEach(() => {
    // Set required environment variable for tests
    process.env['ANTHROPIC_API_KEY'] = 'test-api-key';
    // Reset mock between tests
    mockCreate.mockReset();
  });

  describe('constructor', () => {
    it('should create an instance of ClaudeClient', () => {
      // ARRANGE & ACT
      const client = new ClaudeClient();

      // ASSERT
      expect(client).toBeInstanceOf(ClaudeClient);
    });
  });

  describe('chat', () => {
    it('should send message with default options', async () => {
      // ARRANGE
      const client = new ClaudeClient();
      const messages: Anthropic.MessageParam[] = [{ role: 'user', content: 'Hello' }];
      const mockResponse = {
        id: 'msg_123',
        content: [{ type: 'text', text: 'Hi there!' }],
      };
      mockCreate.mockResolvedValue(mockResponse);

      // ACT
      const response = await client.chat(messages);

      // ASSERT
      expect(mockCreate).toHaveBeenCalledWith({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 4096,
        temperature: 0,
        system: undefined,
        messages,
      });
      expect(response).toEqual(mockResponse);
    });

    it('should send message with custom options', async () => {
      // ARRANGE
      const client = new ClaudeClient();
      const messages: Anthropic.MessageParam[] = [{ role: 'user', content: 'Hello' }];
      const options = {
        model: 'claude-opus-4-20250514',
        maxTokens: 2048,
        temperature: 0.7,
        systemPrompt: 'You are a helpful assistant.',
        enablePromptCaching: false, // Disable caching for simpler test assertions
      };
      const mockResponse = {
        id: 'msg_456',
        content: [{ type: 'text', text: 'How can I help?' }],
      };
      mockCreate.mockResolvedValue(mockResponse);

      // ACT
      const response = await client.chat(messages, options);

      // ASSERT
      expect(mockCreate).toHaveBeenCalledWith({
        model: 'claude-opus-4-20250514',
        max_tokens: 2048,
        temperature: 0.7,
        system: 'You are a helpful assistant.',
        messages,
      });
      expect(response).toEqual(mockResponse);
    });

    it('should use default values when options are undefined', async () => {
      // ARRANGE
      const client = new ClaudeClient();
      const messages: Anthropic.MessageParam[] = [{ role: 'user', content: 'Test' }];
      const options = {
        model: undefined,
        maxTokens: undefined,
        temperature: undefined,
        systemPrompt: undefined,
      };
      const mockResponse = {
        id: 'msg_789',
        content: [{ type: 'text', text: 'Test response' }],
      };
      mockCreate.mockResolvedValue(mockResponse);

      // ACT
      const response = await client.chat(messages, options);

      // ASSERT
      expect(mockCreate).toHaveBeenCalledWith({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 4096,
        temperature: 0,
        system: undefined,
        messages,
      });
      expect(response).toEqual(mockResponse);
    });
  });

  describe('streamChat', () => {
    it('should stream messages and call onChunk for each text delta', async () => {
      // ARRANGE
      const client = new ClaudeClient();
      const messages: Anthropic.MessageParam[] = [{ role: 'user', content: 'Tell me a story' }];
      const chunks: string[] = [];
      const onChunk = (text: string): void => {
        chunks.push(text);
      };

      // Mock async iterator
      const mockStream = {
        async *[Symbol.asyncIterator](): AsyncGenerator<{
          type: string;
          index?: number;
          content_block?: { type: string; text: string };
          delta?: { type: string; text: string };
        }> {
          yield {
            type: 'content_block_start',
            index: 0,
            content_block: { type: 'text', text: '' },
          };
          yield {
            type: 'content_block_delta',
            index: 0,
            delta: { type: 'text_delta', text: 'Once ' },
          };
          yield {
            type: 'content_block_delta',
            index: 0,
            delta: { type: 'text_delta', text: 'upon ' },
          };
          yield {
            type: 'content_block_delta',
            index: 0,
            delta: { type: 'text_delta', text: 'a time' },
          };
          yield {
            type: 'content_block_stop',
            index: 0,
          };
        },
      };
      mockCreate.mockResolvedValue(mockStream);

      // ACT
      await client.streamChat(messages, onChunk);

      // ASSERT
      expect(mockCreate).toHaveBeenCalledWith({
        model: 'claude-sonnet-4-20250514',
        max_tokens: 4096,
        messages,
        stream: true,
      });
      expect(chunks).toEqual(['Once ', 'upon ', 'a time']);
    });

    it('should ignore non-text-delta events when streaming', async () => {
      // ARRANGE
      const client = new ClaudeClient();
      const messages: Anthropic.MessageParam[] = [{ role: 'user', content: 'Hi' }];
      const chunks: string[] = [];
      const onChunk = (text: string): void => {
        chunks.push(text);
      };

      // Mock async iterator with mixed event types
      const mockStream = {
        async *[Symbol.asyncIterator](): AsyncGenerator<{
          type: string;
          index?: number;
          message?: Record<string, unknown>;
          delta?: { type: string; text: string };
        }> {
          yield { type: 'message_start', message: {} };
          yield {
            type: 'content_block_delta',
            index: 0,
            delta: { type: 'text_delta', text: 'Hello' },
          };
          yield { type: 'message_stop' };
        },
      };
      mockCreate.mockResolvedValue(mockStream);

      // ACT
      await client.streamChat(messages, onChunk);

      // ASSERT
      expect(chunks).toEqual(['Hello']);
    });
  });
});

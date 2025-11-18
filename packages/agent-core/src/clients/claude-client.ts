/* eslint-disable @typescript-eslint/naming-convention -- Required for Anthropic SDK environment variable access using bracket notation */
import Anthropic from '@anthropic-ai/sdk';

/**
 * Claude AI Client for interacting with Anthropic's API
 *
 * Provides methods for both standard and streaming chat interactions
 * with Claude Sonnet 4.5 model. Handles API authentication, message
 * formatting, and response parsing.
 *
 * @example
 * ```typescript
 * const client = new ClaudeClient();
 *
 * // Standard chat
 * const response = await client.chat([
 *   { role: 'user', content: 'Hello, Claude!' }
 * ]);
 *
 * // Streaming chat
 * await client.streamChat([
 *   { role: 'user', content: 'Tell me a story' }
 * ], (text) => console.log(text));
 * ```
 */
export class ClaudeClient {
  private readonly client: Anthropic;

  /**
   * Creates a new Claude client instance
   *
   * Initializes the Anthropic SDK with API key from environment variable.
   * Requires ANTHROPIC_API_KEY to be set.
   *
   * @throws {Error} If ANTHROPIC_API_KEY environment variable is not set
   */
  constructor() {
    this.client = new Anthropic({
      apiKey: process.env['ANTHROPIC_API_KEY'],
    });
  }

  /**
   * Send a chat message to Claude and receive a complete response
   *
   * @param messages - Array of message objects with role and content
   * @param options - Optional configuration for the chat request
   * @param options.model - Claude model to use (default: claude-sonnet-4-20250514)
   * @param options.maxTokens - Maximum tokens in response (default: 4096)
   * @param options.temperature - Randomness 0-1, 0=deterministic (default: 0)
   * @param options.systemPrompt - System prompt to set context/behavior
   * @returns Promise resolving to complete Claude message response
   *
   * @throws {Anthropic.APIError} If API request fails (network, auth, rate limit)
   * @throws {Anthropic.RateLimitError} If rate limit exceeded
   * @throws {Anthropic.AuthenticationError} If API key is invalid
   *
   * @example
   * ```typescript
   * const response = await client.chat([
   *   { role: 'user', content: 'Explain quantum computing' }
   * ], {
   *   model: 'claude-sonnet-4-20250514',
   *   maxTokens: 2048,
   *   temperature: 0.7,
   *   systemPrompt: 'You are a helpful physics teacher.'
   * });
   *
   * console.log(response.content[0].text);
   * ```
   */
  async chat(
    messages: Anthropic.MessageParam[],
    options?: {
      model?: string;
      maxTokens?: number;
      temperature?: number;
      systemPrompt?: string;
    }
  ): Promise<Anthropic.Message> {
    const response = await this.client.messages.create({
      model: options?.model ?? 'claude-sonnet-4-20250514',
      max_tokens: options?.maxTokens ?? 4096,
      temperature: options?.temperature ?? 0,
      system: options?.systemPrompt,
      messages,
    });

    return response;
  }

  /**
   * Stream chat response from Claude in real-time chunks
   *
   * Useful for long responses where you want to show incremental progress
   * to the user. The onChunk callback is called for each text delta received.
   *
   * @param messages - Array of message objects with role and content
   * @param onChunk - Callback function called for each text chunk received
   * @returns Promise that resolves when stream is complete
   *
   * @throws {Anthropic.APIError} If API request fails (network, auth, rate limit)
   * @throws {Anthropic.RateLimitError} If rate limit exceeded
   * @throws {Anthropic.AuthenticationError} If API key is invalid
   *
   * @example
   * ```typescript
   * // Stream to console
   * await client.streamChat([
   *   { role: 'user', content: 'Write a short story' }
   * ], (text) => {
   *   process.stdout.write(text); // Print each chunk immediately
   * });
   *
   * // Accumulate full response
   * let fullResponse = '';
   * await client.streamChat([
   *   { role: 'user', content: 'Explain TypeScript' }
   * ], (text) => {
   *   fullResponse += text;
   *   updateUI(fullResponse); // Update UI with incremental content
   * });
   * ```
   */
  async streamChat(
    messages: Anthropic.MessageParam[],
    onChunk: (text: string) => void
  ): Promise<void> {
    const stream = await this.client.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 4096,
      messages,
      stream: true,
    });

    for await (const event of stream) {
      if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
        onChunk(event.delta.text);
      }
    }
  }
}

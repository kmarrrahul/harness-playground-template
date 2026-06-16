import asyncio
import os
import sys

# Optional: Ensure ANTHROPIC_API_KEY is available
api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    print("Warning: ANTHROPIC_API_KEY is not set. The SDK might fail if it requires it.")

try:
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock
except ImportError:
    print("Please install claude-agent-sdk first.")
    sys.exit(1)

async def test_simple_query():
    print("--- Testing Claude Agent SDK ---")
    options = ClaudeAgentOptions(
        system_prompt="You are a helpful assistant",
        max_turns=1
    )
    
    try:
        # Simplest single prompt and catch response
        async for message in query(prompt="Tell me a short joke", options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(f"Claude: {block.text}")
    except Exception as e:
        print(f"Error during query: {e}")

async def main():
    await test_simple_query()

if __name__ == "__main__":
    asyncio.run(main())

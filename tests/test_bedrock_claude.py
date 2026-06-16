import asyncio
import os
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock, SystemMessage

# Print configuration verification to ensure PowerShell shared them correctly
print("--- Verifying PowerShell Variables ---")
print(f"CLAUDE_CODE_USE_BEDROCK: {os.environ.get('CLAUDE_CODE_USE_BEDROCK')}")
print(f"AWS_REGION: {os.environ.get('AWS_REGION')}")
print(f"AWS_BEARER_TOKEN_BEDROCK Status: {'Set' if os.environ.get('AWS_BEARER_TOKEN_BEDROCK') else 'Missing'}")
print("--------------------------------------\n")

async def main():
    try:
        options = ClaudeAgentOptions(
            allowed_tools=["read", "write", "bash"],
            max_turns=1  # Caps the loop to stop it from running forever
        )
        
        async for message in query(prompt="hi how are you?", options=options):
            
            # 1. Capture the actual Model Output
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text, end="", flush=True)
                        
            # 2. Capture structural changes or sub-process events
            elif isinstance(message, SystemMessage):
                print(f"\n[System Event Type]: {getattr(message, 'subtype', 'Generic')}")
                if hasattr(message, 'data'):
                    print(f"[Event Metadata]: {message.data}")
            
            # 3. Fallback tracking
            else:
                print(f"\n[Stream Chunk]: {type(message).__name__}")
                
    except Exception as e:
        # Fallback to general exception to catch ProcessError or CLI errors safely
        print(f"\n[Execution Stopped]: {type(e).__name__} - {e}")

if __name__ == "__main__":
    asyncio.run(main())

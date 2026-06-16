import asyncio
import os
import sys

try:
    from copilot import CopilotClient
except ImportError:
    print("Please install copilot SDK first.")
    sys.exit(1)

async def test_copilot_byok():
    # Ollama should be running
    print("Ensure Ollama is running on http://localhost:11434 before testing BYOK!")
    
    token = os.environ.get("COPILOT_GITHUB_TOKEN", "dummy-token")

    print("Testing GitHub Copilot SDK with BYOK (Ollama)...")
    
    try:
        client = CopilotClient()
        
        provider_config = {
            "type": "openai",
            "base_url": "http://localhost:11434/v1",
            "api_key": "dummy",
            "wire_api": "responses"
        }
        
        session = await client.create_session(
            model="qwen3.5:2b",
            provider=provider_config
        )
        print("Session created. Sending prompt...")
        
        events = []
        def on_event(event):
            if hasattr(event, "type") and event.type == "text":
                events.append(getattr(event, "text", ""))
                
        session.on(on_event)
        await session.send("Hello! Are you there?")
        
        # wait a bit for events to stream in
        await asyncio.sleep(5)
        
        response = "".join(events)
        print(f"Received Response chunks: {len(events)}")
        if response:
            print(f"Response snippet: {response[:100]}...")
            
        await session.disconnect()
        print("Success!")
    except Exception as e:
        print(f"Failed to use Copilot SDK BYOK: {e}")

if __name__ == "__main__":
    asyncio.run(test_copilot_byok())

import asyncio
import os
import sys

try:
    from copilot import CopilotClient
except ImportError:
    print("Please install copilot SDK first.")
    sys.exit(1)

async def test_copilot_pat():
    token = os.environ.get("COPILOT_GITHUB_TOKEN")
    if not token:
        print("Please set COPILOT_GITHUB_TOKEN environment variable.")
        return

    print("Testing GitHub Copilot SDK with PAT...")
    
    try:
        client = CopilotClient()
        session = await client.create_session(model="gpt-5-mini")
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
        print(f"Failed to use Copilot SDK: {e}")

if __name__ == "__main__":
    asyncio.run(test_copilot_pat())

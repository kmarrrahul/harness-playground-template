import asyncio
import os
import sys
from cursor_sdk import AsyncClient, LocalAgentOptions

async def test_auth_and_models(api_key: str):
    print(f"Testing with API Key: {api_key[:8]}...")
    try:
        async with await AsyncClient.launch_bridge(workspace=os.getcwd()) as client:
            print("Creating agent...")
            agent_cm = await client.agents.create(
                model="composer-2.5",
                api_key=api_key,
                local=LocalAgentOptions(cwd=os.getcwd())
            )
            agent = await agent_cm.__aenter__()
            print("Success! Agent created with ID:", agent.agent_id)
            
            print("Sending prompt...")
            # Note: Method might vary based on actual SDK version
            response = await agent.chat("Hi, are you there?")
            print(f"Response: {response}")
            return True
    except Exception as e:
        print(f"Failed to create agent or chat: {e}")
        return False

if __name__ == "__main__":
    api_key = os.environ.get("CURSOR_API_KEY", "")
    if not api_key:
        print("Please set CURSOR_API_KEY environment variable to test.")
        sys.exit(1)
        
    asyncio.run(test_auth_and_models(api_key))

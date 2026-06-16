from openai_codex import Codex

with Codex() as codex:
    # 1. Start the interactive ChatGPT browser login flow
    login = codex.login_chatgpt()
    print(f"Please open this URL to log in: {login.auth_url}")
    
    # 2. Wait for the user to complete browser authentication
    if login.wait().success:
        print("Successfully authenticated with ChatGPT!")
        
        # FIX: Explicitly target a consumer model compatible with ChatGPT accounts
        thread = codex.thread_start(model="gpt-5.4-mini") 
        
        # 3. Run your prompt cleanly
        result = thread.run("hi")
        print(result.final_response)

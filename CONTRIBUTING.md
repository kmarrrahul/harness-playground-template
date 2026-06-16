# Contributing to Harness Playground Template

First off, thank you for considering contributing! It's people like you that make this template a great starting point for the community.

## Setting Up Your Local Environment

1. **Fork & Clone**
   Fork the repository on GitHub, then clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/harness-playground-template.git
   cd harness-playground-template
   ```

2. **Create a Virtual Environment (Optional)** 
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the App Locally**
   Start the development server:
   ```bash
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
   ```
   Navigate to `http://localhost:8080` to view the app!

## Coding Style

- We use **PEP 8** for Python formatting.
- Please keep HTML templates clean and maintain the existing Tailwind CSS structures.
- Comment your logic, especially when dealing with async agent streams or new SDK integrations.

## 🧪 SDK Prompt Verification Checklist

Verify your local agent setup via prompt testing:
* **Agent Skills:** "Use Agent Skill `/hello-world` and share the response." (Make sure it is enabled in the UI menu).
* **CLI Execution:** "Use your native CLI tools to list standard resources in my account."

* **GitHub Access:** "List the repositories I have that are forked."

------------------------------

## 💻 Test Matrix Execution

Ensure your prompts and features work seamlessly across:

### 1. Local Environment
* Copilot SDK, Antigravity SDK, Claude Agent SDK, Cursor SDK, Codex SDK

### 2. Dockerized App
* Copilot SDK, Antigravity SDK, Claude Agent SDK, Cursor SDK, Codex SDK

------------------------------

## Submitting a Pull Request (PR)

1. Create a new branch for your feature or bugfix (`git checkout -b feature/my-cool-feature`).
2. Make your changes and test them locally.
3. Commit your changes with a clear, descriptive commit message.
4. Push your branch to your fork (`git push origin feature/my-cool-feature`).
5. Open a Pull Request against the `main` branch of this repository.

We will review your PR as quickly as possible. Thanks again!

# 🧪 SDK Integration Test Matrix

This document tracks the manual testing status of the various AI SDKs and their supported providers/authentication methods within the Harness Playground Template. 

Update the checkboxes below as new integration pathways are validated.
- `[x]` = Tested & Verified
- `[ ]` = Pending Testing

## 1. GitHub Copilot SDK
- [x] GitHub OAuth
- [x] GitHub Personal Access Token (PAT)
- [ ] OpenAI / Ollama (BYOK)
- [ ] Azure OpenAI (BYOK)
- [ ] Anthropic (BYOK)

## 2. Google Antigravity SDK
- [x] Gemini API Key

## 3. Claude Agent SDK
- [x] Amazon Bedrock (BYOK)
- [ ] Google GCP (Formerly Vertex AI)
- [ ] Anthropic Console API Key

## 4. Codex SDK
- [x] ChatGPT Subscription
- [x] Local Ollama
- [ ] OpenAI API Key
- [ ] AWS Bedrock (Mantle Endpoint)

## 5. Cursor SDK
- [ ] Cursor Auth Integration (Pending all tests)

---
*Note: Providers marked as (BYOK) rely on the Bring Your Own Keys mechanism.*

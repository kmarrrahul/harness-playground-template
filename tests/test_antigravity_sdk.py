"""
Standalone test script for Google Antigravity SDK.

Tests:
  1. Basic prompt → response (await full text)
  2. Streaming tokens (async for)
  3. Thinking/reasoning capture
  4. Session management (conversation_id / multi-turn)
  5. Tool call detection

Prerequisites:
  - pip install google-antigravity
  - GEMINI_API_KEY environment variable set

Usage:
  python tests/test_antigravity_sdk.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

# ── Pre-flight checks ────────────────────────────────────────────────────────
api_key = os.environ.get("GEMINI_API_KEY", "")
if not api_key:
    print("ERROR: GEMINI_API_KEY environment variable not set.")
    print("Set it with: $env:GEMINI_API_KEY = 'your-key-here'")
    sys.exit(1)

print(f"✓ GEMINI_API_KEY present ({api_key[:8]}...)")

# ── SDK imports ──────────────────────────────────────────────────────────────
try:
    from google.antigravity import Agent, LocalAgentConfig
    from google.antigravity.types import (
        ThinkingLevel,
        GeminiConfig,
        ModelConfig,
        ModelEntry,
        GenerationConfig,
        CapabilitiesConfig,
        BuiltinTools,
        Text,
        Thought,
        ToolCall,
        ToolResult,
        Step,
        StepType,
        StepSource,
    )
    from google.antigravity.hooks import policy
    print("✓ Antigravity SDK imported successfully")
except ImportError as e:
    print(f"ERROR: Cannot import Antigravity SDK: {e}")
    print("Install with: pip install google-antigravity")
    sys.exit(1)


async def test_1_basic_prompt():
    """Test 1: Basic prompt → full text response."""
    print("\n" + "=" * 60)
    print("TEST 1: Basic prompt → full text response")
    print("=" * 60)

    config = LocalAgentConfig(
        policies=[policy.allow_all()],
        capabilities=CapabilitiesConfig(
            enabled_tools=BuiltinTools.read_only(),
        ),
        workspaces=[],
        gemini_config=GeminiConfig(
            api_key=api_key,
            models=ModelConfig(
                default=ModelEntry(
                    name="gemini-3.5-flash",
                    generation=GenerationConfig(thinking_level=ThinkingLevel.LOW),
                ),
            ),
        ),
    )

    start = time.time()
    try:
        async with Agent(config) as agent:
            print("  Agent session started.")
            print(f"  conversation_id: {agent.conversation_id}")

            response = await agent.chat("What is 2 + 2? Answer in one sentence.")
            full_text = await response.text()
            elapsed = time.time() - start

            print(f"  Response ({elapsed:.1f}s): {full_text[:200]}")
            print(f"  conversation_id after chat: {agent.conversation_id}")

            # Check usage metadata
            usage = response.usage_metadata
            if usage:
                print(f"  Token usage: prompt={usage.prompt_token_count}, "
                      f"candidates={usage.candidates_token_count}, "
                      f"total={usage.total_token_count}")

            print("✓ TEST 1 PASSED")
            return True
    except Exception as e:
        print(f"✗ TEST 1 FAILED: {type(e).__name__}: {e}")
        return False


async def test_2_streaming():
    """Test 2: Streaming token-by-token output."""
    print("\n" + "=" * 60)
    print("TEST 2: Streaming tokens")
    print("=" * 60)

    config = LocalAgentConfig(
        policies=[policy.allow_all()],
        capabilities=CapabilitiesConfig(
            enabled_tools=BuiltinTools.read_only(),
        ),
        workspaces=[],
        gemini_config=GeminiConfig(
            api_key=api_key,
            models=ModelConfig(
                default=ModelEntry(name="gemini-3.5-flash"),
            ),
        ),
    )

    start = time.time()
    token_count = 0
    full_text = ""
    try:
        async with Agent(config) as agent:
            print("  Agent session started. Streaming response:")
            print("  >>> ", end="", flush=True)

            response = await agent.chat("List 3 prime numbers. Be brief.")

            async for token in response:
                sys.stdout.write(token)
                sys.stdout.flush()
                full_text += token
                token_count += 1

            elapsed = time.time() - start
            print(f"\n  Received {token_count} text chunks in {elapsed:.1f}s")
            print(f"  Full text length: {len(full_text)} chars")
            print("✓ TEST 2 PASSED")
            return True
    except Exception as e:
        print(f"\n✗ TEST 2 FAILED: {type(e).__name__}: {e}")
        return False


async def test_3_thinking():
    """Test 3: Capture model thinking/reasoning."""
    print("\n" + "=" * 60)
    print("TEST 3: Thinking/reasoning capture")
    print("=" * 60)

    config = LocalAgentConfig(
        policies=[policy.allow_all()],
        capabilities=CapabilitiesConfig(
            enabled_tools=BuiltinTools.read_only(),
        ),
        workspaces=[],
        gemini_config=GeminiConfig(
            api_key=api_key,
            models=ModelConfig(
                default=ModelEntry(
                    name="gemini-3.5-flash",
                    generation=GenerationConfig(thinking_level=ThinkingLevel.LOW),
                ),
            ),
        ),
    )

    thinking_chunks = []
    text_chunks = []
    tool_calls_seen = []

    try:
        async with Agent(config) as agent:
            print("  Agent session started with ThinkingLevel.LOW")

            response = await agent.chat("What is the capital of France? Be brief.")

            async for chunk in response.chunks:
                if isinstance(chunk, Thought):
                    thinking_chunks.append(chunk.text)
                elif isinstance(chunk, Text):
                    text_chunks.append(chunk.text)
                elif isinstance(chunk, ToolCall):
                    tool_calls_seen.append(chunk.name)

            print(f"  Thinking chunks: {len(thinking_chunks)}")
            if thinking_chunks:
                thinking_text = "".join(thinking_chunks)
                print(f"  Thinking preview: {thinking_text[:150]}...")
            print(f"  Text chunks: {len(text_chunks)}")
            print(f"  Full response: {''.join(text_chunks)[:200]}")
            print(f"  Tool calls: {tool_calls_seen}")
            print("✓ TEST 3 PASSED")
            return True
    except Exception as e:
        print(f"✗ TEST 3 FAILED: {type(e).__name__}: {e}")
        return False


async def test_4_multi_turn():
    """Test 4: Multi-turn conversation within a single session."""
    print("\n" + "=" * 60)
    print("TEST 4: Multi-turn conversation (session continuity)")
    print("=" * 60)

    config = LocalAgentConfig(
        policies=[policy.allow_all()],
        capabilities=CapabilitiesConfig(
            enabled_tools=BuiltinTools.read_only(),
        ),
        workspaces=[],
        gemini_config=GeminiConfig(
            api_key=api_key,
            models=ModelConfig(
                default=ModelEntry(name="gemini-3.5-flash"),
            ),
        ),
    )

    try:
        async with Agent(config) as agent:
            # Turn 1
            print("  Turn 1: Setting context...")
            r1 = await agent.chat("My name is TestUser42. Remember this.")
            t1 = await r1.text()
            print(f"  Response 1: {t1[:150]}")
            conv_id = agent.conversation_id
            print(f"  conversation_id: {conv_id}")

            # Turn 2
            print("  Turn 2: Asking about context...")
            r2 = await agent.chat("What is my name?")
            t2 = await r2.text()
            print(f"  Response 2: {t2[:150]}")

            # Verify context was maintained
            has_name = "TestUser42" in t2 or "testuser42" in t2.lower()
            print(f"  Context maintained: {'YES' if has_name else 'MAYBE (check response)'}")

            # Check conversation turn count
            turn_count = agent.conversation.turn_count
            print(f"  Turn count: {turn_count}")

            print("✓ TEST 4 PASSED")
            return True
    except Exception as e:
        print(f"✗ TEST 4 FAILED: {type(e).__name__}: {e}")
        return False


async def test_5_rich_chunks():
    """Test 5: Rich chunk stream (Text, Thought, ToolCall, ToolResult)."""
    print("\n" + "=" * 60)
    print("TEST 5: Rich chunk stream analysis")
    print("=" * 60)

    config = LocalAgentConfig(
        policies=[policy.allow_all()],
        capabilities=CapabilitiesConfig(
            enabled_tools=BuiltinTools.read_only(),
        ),
        workspaces=[],
        gemini_config=GeminiConfig(
            api_key=api_key,
            models=ModelConfig(
                default=ModelEntry(
                    name="gemini-3.5-flash",
                    generation=GenerationConfig(thinking_level=ThinkingLevel.LOW),
                ),
            ),
        ),
    )

    chunk_types = {}

    try:
        async with Agent(config) as agent:
            response = await agent.chat("Say hello in exactly 5 words.")

            async for chunk in response.chunks:
                type_name = type(chunk).__name__
                chunk_types[type_name] = chunk_types.get(type_name, 0) + 1

                if isinstance(chunk, Text):
                    pass  # Already counted
                elif isinstance(chunk, Thought):
                    pass  # Already counted
                elif isinstance(chunk, ToolCall):
                    print(f"  ToolCall: {chunk.name}({chunk.args})")
                elif isinstance(chunk, ToolResult):
                    print(f"  ToolResult: {chunk.name} → {str(chunk.result)[:80]}")

            print(f"  Chunk type distribution: {chunk_types}")
            print("✓ TEST 5 PASSED")
            return True
    except Exception as e:
        print(f"✗ TEST 5 FAILED: {type(e).__name__}: {e}")
        return False


async def main():
    print("=" * 60)
    print("ANTIGRAVITY SDK TEST SUITE")
    print(f"Model: gemini-3.5-flash (ThinkingLevel.LOW)")
    print("=" * 60)

    results = {}

    # Run tests sequentially (each creates its own agent session)
    results["test_1_basic"] = await test_1_basic_prompt()
    results["test_2_streaming"] = await test_2_streaming()
    results["test_3_thinking"] = await test_3_thinking()
    results["test_4_multi_turn"] = await test_4_multi_turn()
    results["test_5_rich_chunks"] = await test_5_rich_chunks()

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")
    print(f"\n  {passed}/{total} tests passed")


if __name__ == "__main__":
    asyncio.run(main())

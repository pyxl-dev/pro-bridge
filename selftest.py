"""Validate the CDP connection before wiring the bridge into an MCP client.

Run with the bridge browser already open and logged in:
    python selftest.py

Optional full round-trip:
    python selftest.py "Reply with exactly one word: PONG"
"""
import asyncio
import sys

from pro_bridge.chatgpt import ChatGPTDriver


async def main():
    driver = ChatGPTDriver()
    status = await driver.status()
    print("Connected:", status["connected"])
    print("Page URL:", status["url"])
    print("Model (last answer, if known):", status["model"])
    print("Conversation:", status["conversation_id"])

    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        print(f"\nSending in a NEW chat: {prompt!r}\n(waiting for ChatGPT)...")
        result = await driver.ask(prompt)
        print(
            "\n--- model:",
            result["model"],
            "conv:",
            result["conversation_id"],
            "---",
        )
        print(result["text"])

    await driver.aclose()


if __name__ == "__main__":
    asyncio.run(main())

"""Step-by-step ChatGPT ask diagnostics.

    python debug_ask.py "Reply with one word: PONG"
"""
import asyncio
import sys

from pro_bridge.chatgpt import ChatGPTDriver

ASSISTANT = '[data-message-author-role="assistant"]'


async def main():
    prompt = " ".join(sys.argv[1:]) or "Reply with exactly one word: PONG"
    driver = ChatGPTDriver()
    page = await driver._get_page(fresh=True)
    print("URL:", page.url)
    print("pages in context:", [p.url for p in page.context.pages])

    before = await page.locator(ASSISTANT).count()
    print("assistant count BEFORE:", before)

    print("sending...")
    await driver._send(page, prompt)
    print("sent. polling for 90s...")

    for i in range(45):
        await asyncio.sleep(2)
        count = await page.locator(ASSISTANT).count()
        state = await driver._completion_state(page)
        slug = await driver._last_assistant_slug(page)
        answer = ""
        try:
            answer = (await driver._extract_answer(page))[:60].replace("\n", " ")
        except Exception as exc:
            answer = f"<err {exc}>"
        print(
            f"[{i * 2:3d}s] url={page.url[-16:]} count={count} "
            f"stop={state['stopVisible']} copy={state['copyVisible']} "
            f"slug={slug} ans={answer!r}"
        )
        if count > before and state["copyVisible"] and answer:
            print(">>> high-confidence completion signal present")
            break

    await driver.aclose()


if __name__ == "__main__":
    asyncio.run(main())

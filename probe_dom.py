"""Deep DOM probe for the live ChatGPT page. Sends nothing.

Run with the bridge browser already running:
    python probe_dom.py

The probe is intentionally text-only so it is useful with a headless browser.
"""
import asyncio
import json

from pro_bridge.chatgpt import ChatGPTDriver

MSG_SELECTORS = [
    '[data-message-author-role="assistant"]',
    '[data-message-author-role]',
    '[data-message-id]',
    '[data-testid^="conversation-turn"]',
    'article',
    'main article',
    '.markdown',
    'main .markdown',
]


async def counts(page):
    for sel in MSG_SELECTORS:
        try:
            print(f"  {sel!r}: {await page.locator(sel).count()}")
        except Exception as e:
            print(f"  {sel!r}: ERR {e}")


async def main():
    d = ChatGPTDriver()
    page = await d._get_page()

    # Give the app a few seconds to hydrate before deciding the DOM is empty.
    await asyncio.sleep(5)

    diag = await page.evaluate(
        """() => ({
            title: document.title,
            readyState: document.readyState,
            bodyText: (document.body?.innerText || '').trim().slice(0, 2500),
            htmlLength: document.documentElement?.outerHTML?.length || 0,
            mainCount: document.querySelectorAll('main').length,
            promptCount: document.querySelectorAll('#prompt-textarea').length,
            textboxCount: document.querySelectorAll('[role="textbox"]').length,
            loginLinks: Array.from(document.querySelectorAll('a,button'))
                .map(el => (el.innerText || el.getAttribute('aria-label') || '').trim())
                .filter(Boolean)
                .filter(s => /log in|login|sign in|connexion|se connecter/i.test(s))
                .slice(0, 20),
            userAgent: navigator.userAgent,
            webdriver: navigator.webdriver,
        })"""
    )

    print("URL:", page.url)
    print("Title:", repr(diag["title"]))
    print("readyState:", diag["readyState"])
    print("HTML length:", diag["htmlLength"])
    print("main count:", diag["mainCount"])
    print("prompt count:", diag["promptCount"])
    print("textbox count:", diag["textboxCount"])
    print("navigator.webdriver:", diag["webdriver"])
    print("User-Agent:", diag["userAgent"])
    print("login-ish controls:", diag["loginLinks"])
    print("\n--- body text (first 2500 chars) ---")
    print(diag["bodyText"] or "<EMPTY BODY TEXT>")

    body_lower = (diag["bodyText"] or "").lower()
    markers = [
        "verify you are human",
        "checking your browser",
        "just a moment",
        "cloudflare",
        "captcha",
        "access denied",
        "something went wrong",
        "log in",
        "sign in",
        "se connecter",
    ]
    matched = [m for m in markers if m in body_lower]
    print("\nchallenge/login markers:", matched or "none")

    print("\n--- message selector counts ---")
    await counts(page)

    tags = await page.evaluate(
        """() => {
            const pick = document.querySelectorAll('main article, [data-message-id], .markdown');
            return Array.from(pick).slice(-2).map(el => {
                const attrs = {};
                for (const at of el.attributes) attrs[at.name] = at.value;
                return {
                    tag: el.tagName.toLowerCase(),
                    attrs,
                    textHead: (el.innerText || '').trim().slice(0, 100),
                };
            });
        }"""
    )
    print("\n--- last 2 message-ish containers ---")
    for tag in tags:
        print(json.dumps(tag, ensure_ascii=False))

    print("\n--- composer probe ---")
    if not diag["promptCount"] and not diag["textboxCount"]:
        print("No composer candidate exists in the DOM; skipping click test.")
    else:
        try:
            comp = page.locator('#prompt-textarea')
            if not await comp.count():
                comp = page.get_by_role("textbox").first
            print("composer visible:", await comp.is_visible())
        except Exception as e:
            print("composer probe ERR:", e)

    await d.aclose()


if __name__ == "__main__":
    asyncio.run(main())

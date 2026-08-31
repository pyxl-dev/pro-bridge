"""Drive an already-logged-in ChatGPT web session via CDP.

The driver intentionally uses the public web UI rather than private ChatGPT
backend APIs. It attaches to a real, logged-in Chromium-family browser over CDP,
serializes browser actions, and threads conversations by their /c/<uuid> URL.
"""
import asyncio
import logging
import re
import time

from playwright.async_api import async_playwright

from . import config

log = logging.getLogger("pro_bridge.chatgpt")

CONV_RE = re.compile(r"/c/([0-9a-fA-F-]{36})")
ASSISTANT = '[data-message-author-role="assistant"]'
CHATGPT_HOME = "https://chatgpt.com/"


class ChatGPTDriver:
    def __init__(self):
        self._pw = None
        self._browser = None
        # One browser tab is a shared mutable resource. Serialize all operations
        # so concurrent MCP clients cannot interleave prompts or navigate over
        # each other's conversations.
        self._lock = asyncio.Lock()

    async def _ensure(self):
        if self._browser is not None and self._browser.is_connected():
            return
        if self._pw is None:
            self._pw = await async_playwright().start()
        log.info("Connecting to Chrome via CDP at %s", config.CDP_URL)
        self._browser = await self._pw.chromium.connect_over_cdp(config.CDP_URL)

    async def _chatgpt_page(self):
        await self._ensure()
        contexts = self._browser.contexts
        if not contexts:
            raise RuntimeError(
                "No browser context over CDP. Start Chrome/Brave/Edge with "
                "--remote-debugging-port and a logged-in profile (see scripts/)."
            )
        ctx = contexts[0]
        for page in ctx.pages:
            if "chatgpt.com" in page.url or "chat.openai.com" in page.url:
                return page
        return await ctx.new_page()

    def _new_chat_url(self):
        if config.MODEL_SLUG:
            return f"{CHATGPT_HOME}?model={config.MODEL_SLUG}"
        return CHATGPT_HOME

    async def _get_page(self, conversation_id=None, *, fresh=False):
        """Return the bridge ChatGPT page, navigating it to the requested thread.

        conversation_id provided -> open that exact conversation.
        fresh=True              -> navigate to a real new-chat page.
        otherwise               -> preserve the page's current location.

        The distinction matters for multi-agent callers: an ask with no
        conversation_id must not accidentally append to whatever chat a previous
        caller left open.
        """
        page = await self._chatgpt_page()

        if conversation_id:
            target = f"{CHATGPT_HOME}c/{conversation_id}"
            if conversation_id not in page.url:
                await page.goto(target, wait_until="domcontentloaded")
        elif fresh:
            await page.goto(self._new_chat_url(), wait_until="domcontentloaded")
        elif "chatgpt.com" not in page.url and "chat.openai.com" not in page.url:
            await page.goto(self._new_chat_url(), wait_until="domcontentloaded")

        return page

    async def _last_assistant_slug(self, page):
        # Ground truth when available: assistant turns carry the model slug that
        # produced them. The attribute is not guaranteed, so absence is allowed.
        try:
            return await page.evaluate(
                """() => {
                    const els = document.querySelectorAll('[data-message-author-role=assistant]');
                    if (!els.length) return null;
                    return els[els.length - 1].getAttribute('data-message-model-slug');
                }"""
            )
        except Exception:
            return None

    async def current_model(self, page):
        return await self._last_assistant_slug(page)

    async def status(self):
        async with self._lock:
            page = await self._get_page()
            conv = None
            match = CONV_RE.search(page.url)
            if match:
                conv = match.group(1)
            return {
                "connected": True,
                "url": page.url,
                "model": await self.current_model(page),
                "conversation_id": conv,
            }

    async def new_chat(self):
        async with self._lock:
            page = await self._get_page(fresh=True)
            try:
                await page.bring_to_front()
            except Exception:
                pass
            return {"url": page.url, "conversation_id": None}

    async def ask(self, prompt, conversation_id=None):
        if not prompt or not prompt.strip():
            raise ValueError("prompt must not be empty")

        async with self._lock:
            # No conversation id means a NEW conversation by contract. This
            # prevents one agent from silently continuing another agent's thread.
            page = await self._get_page(
                conversation_id,
                fresh=conversation_id is None,
            )
            try:
                await page.bring_to_front()
            except Exception:
                pass

            model_holder = {}

            def on_request(req):
                try:
                    if req.method == "POST" and "/backend-api/conversation" in req.url:
                        data = req.post_data_json
                        if isinstance(data, dict) and data.get("model"):
                            model_holder["model"] = data["model"]
                except Exception:
                    # Request inspection is best-effort only; the bridge does not
                    # depend on ChatGPT's private API response format.
                    pass

            page.on("request", on_request)
            try:
                before = await page.locator(ASSISTANT).count()
                await self._send(page, prompt)
                await page.wait_for_function(
                    "n => document.querySelectorAll"
                    "('[data-message-author-role=assistant]').length > n",
                    arg=before,
                    timeout=config.ANSWER_TIMEOUT * 1000,
                )
                await self._wait_complete(page)
                text = await self._extract_answer(page)
            finally:
                page.remove_listener("request", on_request)

            model = await self._last_assistant_slug(page) or model_holder.get("model")
            conv = None
            match = CONV_RE.search(page.url)
            if match:
                conv = match.group(1)

            if not conv:
                raise RuntimeError(
                    "ChatGPT answered but no conversation id was found in the URL."
                )

            return {"text": text, "model": model, "conversation_id": conv}

    async def _extract_answer(self, page):
        loc = page.locator(ASSISTANT).last

        # Prefer rendered markdown when present. Fall back to the semantic
        # assistant container for non-markdown answer types.
        md = loc.locator(".markdown")
        try:
            if await md.count():
                text = (await md.last.inner_text()).strip()
                if text:
                    return text
        except Exception:
            pass

        text = (await loc.inner_text()).strip()
        if not text:
            raise RuntimeError("Latest ChatGPT assistant turn contains no text.")
        return text

    async def _send(self, page, prompt):
        composer = page.locator("#prompt-textarea")
        try:
            await composer.wait_for(state="visible", timeout=30000)
        except Exception:
            composer = page.get_by_role("textbox").first
            await composer.wait_for(state="visible", timeout=30000)

        await composer.click()
        try:
            await composer.fill(prompt)
        except Exception:
            # contenteditable implementations can occasionally reject fill().
            # Clear the composer before literal insertion to avoid appending to
            # stale/manual text.
            try:
                await composer.press("ControlOrMeta+A")
                await composer.press("Backspace")
            except Exception:
                pass
            await page.keyboard.insert_text(prompt)

        for selector in (
            '[data-testid="send-button"]',
            'button[aria-label*="Send" i]',
        ):
            try:
                button = page.locator(selector)
                if (
                    await button.count()
                    and await button.first.is_visible()
                    and await button.first.is_enabled()
                ):
                    await button.first.click()
                    return
            except Exception:
                continue

        await composer.press("Enter")

    async def _completion_state(self, page):
        """Return high-signal generation state from the current DOM.

        Copy action in the latest assistant turn is a strong completion signal.
        A visible Stop button is a strong in-progress signal. Both are treated as
        optional because ChatGPT's DOM changes over time.
        """
        try:
            return await page.evaluate(
                """() => {
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none' &&
                               style.visibility !== 'hidden' &&
                               rect.width > 0 && rect.height > 0;
                    };

                    const assistants = document.querySelectorAll(
                        '[data-message-author-role=assistant]'
                    );
                    const assistant = assistants.length
                        ? assistants[assistants.length - 1]
                        : null;
                    const turn = assistant
                        ? assistant.closest('[data-testid^="conversation-turn-"]')
                        : null;
                    const copy = turn
                        ? turn.querySelector('[data-testid="copy-turn-action-button"]')
                        : null;
                    const stop = document.querySelector('[data-testid="stop-button"]');

                    return {
                        copyVisible: visible(copy),
                        stopVisible: visible(stop),
                    };
                }"""
            )
        except Exception:
            return {"copyVisible": False, "stopVisible": False}

    async def _wait_complete(self, page):
        """Wait until the latest answer has genuinely settled.

        Fast path: latest turn exposes its Copy action and text is stable.
        Fallback: no visible Stop control and text is stable for ~15 seconds.
        The fallback is deliberately conservative to avoid returning a temporary
        thinking/tool summary as the final answer.
        """
        deadline = time.time() + config.ANSWER_TIMEOUT
        last = None
        stable = 0

        while time.time() < deadline:
            try:
                current = await self._extract_answer(page)
            except Exception:
                current = None

            state = await self._completion_state(page)

            if current and current == last:
                stable += 1
            else:
                last = current
                stable = 0

            if current and state["copyVisible"] and stable >= 1:
                return

            # UI-drift fallback: ~15 seconds of unchanged text while no visible
            # stop button exists.
            if current and not state["stopVisible"] and stable >= 10:
                return

            await asyncio.sleep(1.5)

        raise TimeoutError(
            f"ChatGPT response did not complete within {config.ANSWER_TIMEOUT} seconds."
        )

    async def aclose(self):
        # Disconnect Playwright only; never close the user's real browser.
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass

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
from .browser_guard import launch_local_browser

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

    @staticmethod
    def _is_driver_connection_error(exc: BaseException) -> bool:
        """Return True only for loss of the Playwright driver transport.

        Browser/page closures are deliberately not treated as this condition:
        after a prompt has been sent we must never blindly resend it. The known
        failure we can recover safely is the Python <-> Playwright driver pipe
        disappearing while the real CDP browser remains alive.
        """
        message = str(exc).lower()
        return "connection closed while reading from the driver" in message

    @staticmethod
    def _conversation_id_from_url(url: str | None) -> str | None:
        if not url:
            return None
        match = CONV_RE.search(url)
        return match.group(1) if match else None

    async def _discard_playwright_driver(self):
        """Drop a dead Playwright transport without closing the real browser."""
        old_pw = self._pw
        self._pw = None
        self._browser = None
        if old_pw is None:
            return
        try:
            # A dead driver normally fails immediately. Bound stop() anyway so a
            # broken transport cannot stall the recovery path.
            await asyncio.wait_for(old_pw.stop(), timeout=2.0)
        except Exception:
            pass

    async def _ensure(self):
        if self._browser is not None and self._browser.is_connected():
            return

        # Do not retain a disconnected Browser object across recovery attempts.
        self._browser = None

        if self._pw is None:
            self._pw = await async_playwright().start()

        log.info("Connecting to Chrome via CDP at %s", config.CDP_URL)
        try:
            self._browser = await self._pw.chromium.connect_over_cdp(config.CDP_URL)
            return
        except Exception as first_error:
            # server._ensure_browser_available() can succeed and then lose the
            # browser before Playwright actually connects. Recover once at the
            # connection boundary so that race does not fail the MCP call.
            if not config.AUTO_START_BROWSER:
                raise

            log.warning(
                "CDP connection failed at %s; attempting one browser recovery: %s",
                config.CDP_URL,
                first_error,
            )
            recovered = await launch_local_browser(
                config.CDP_URL,
                timeout=config.BROWSER_START_TIMEOUT,
                custom_command=config.BROWSER_START_COMMAND or None,
            )
            if not recovered:
                # Remote/non-local CDP endpoints must never trigger a local
                # browser launch. Preserve the original connection failure.
                raise

            log.info(
                "Browser recovery succeeded; retrying CDP connection at %s",
                config.CDP_URL,
            )
            # Exactly one reconnect attempt: if this fails, propagate that
            # second error rather than entering an auto-restart loop.
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

    async def _recover_inflight_page(self, conversation_id: str | None):
        """Reattach Playwright to an already-sent ChatGPT request.

        This method never sends a prompt. If the conversation id was not known
        yet (typical immediately after a brand-new chat), recovery is accepted
        only when the reattached ChatGPT page itself has a /c/<uuid> URL. This is
        intentionally fail-closed to avoid duplicating a prompt in another chat.
        """
        log.warning(
            "Playwright driver transport was lost after prompt send; "
            "reattaching to CDP without resending"
        )
        await self._discard_playwright_driver()
        await self._ensure()

        if conversation_id:
            page = await self._get_page(conversation_id)
            return page, conversation_id

        page = await self._chatgpt_page()
        recovered_id = self._conversation_id_from_url(page.url)
        if not recovered_id:
            raise RuntimeError(
                "Playwright driver disconnected after the prompt was sent, but "
                "the active ChatGPT conversation could not be identified safely. "
                "The prompt was not resent."
            )
        return page, recovered_id

    async def _assistant_snapshot(self, page):
        """Return the last non-empty assistant node and its completion metadata.

        ChatGPT can render multiple assistant nodes for one visible turn, including
        an empty trailing placeholder after the real answer. Selection therefore
        walks backwards and ignores empty nodes. Text, model slug and completion
        controls are all read from the same selected assistant/turn so they cannot
        disagree about which response is complete.
        """
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

                const assistants = Array.from(document.querySelectorAll(
                    '[data-message-author-role=assistant]'
                ));

                for (let index = assistants.length - 1; index >= 0; index -= 1) {
                    const assistant = assistants[index];
                    const markdowns = Array.from(assistant.querySelectorAll('.markdown'));
                    let text = '';

                    for (let mdIndex = markdowns.length - 1; mdIndex >= 0; mdIndex -= 1) {
                        const candidate = (markdowns[mdIndex].innerText || '').trim();
                        if (candidate) {
                            text = candidate;
                            break;
                        }
                    }

                    if (!text) {
                        text = (assistant.innerText || '').trim();
                    }
                    if (!text) {
                        continue;
                    }

                    const turn = assistant.closest('[data-testid^="conversation-turn-"]');
                    const copy = turn
                        ? turn.querySelector('[data-testid="copy-turn-action-button"]')
                        : null;
                    const turnStop = turn
                        ? turn.querySelector('[data-testid="stop-button"]')
                        : null;
                    const stop = turnStop || document.querySelector('[data-testid="stop-button"]');

                    return {
                        index,
                        text,
                        model: assistant.getAttribute('data-message-model-slug'),
                        copyVisible: visible(copy),
                        stopVisible: visible(stop),
                        turnId: turn ? turn.getAttribute('data-testid') : null,
                    };
                }

                return null;
            }"""
        )

    async def _last_assistant_slug(self, page):
        # Ground truth when available: use the same non-empty assistant node that
        # answer extraction and completion detection use.
        try:
            snapshot = await self._assistant_snapshot(page)
            return snapshot.get("model") if snapshot else None
        except Exception as exc:
            if self._is_driver_connection_error(exc):
                raise
            return None

    async def current_model(self, page):
        return await self._last_assistant_slug(page)

    async def status(self):
        async with self._lock:
            page = await self._get_page()
            conv = self._conversation_id_from_url(page.url)
            return {
                "connected": True,
                "url": page.url,
                "model": await self.current_model(page),
                "conversation_id": conv,
            }

    async def new_chat(self):
        async with self._lock:
            page = await self._get_page(fresh=True)
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

            listener_page = page
            page.on("request", on_request)
            try:
                before = await page.locator(ASSISTANT).count()
                # Recovery below begins only after _send() has returned. If the
                # driver dies during send itself we fail closed, because we cannot
                # know whether ChatGPT received the prompt and must not duplicate it.
                await self._send(page, prompt)
                deadline = time.monotonic() + config.ANSWER_TIMEOUT
                page, text, conv = await self._wait_for_answer(
                    page,
                    before,
                    conversation_id=conversation_id,
                    deadline=deadline,
                )
            finally:
                try:
                    listener_page.remove_listener("request", on_request)
                except Exception:
                    pass

            model = await self._last_assistant_slug(page) or model_holder.get("model")
            conv = conv or self._conversation_id_from_url(page.url)

            if not conv:
                raise RuntimeError(
                    "ChatGPT answered but no conversation id was found in the URL."
                )

            return {"text": text, "model": model, "conversation_id": conv}

    async def _extract_answer(self, page):
        snapshot = await self._assistant_snapshot(page)
        if not snapshot or not snapshot.get("text"):
            raise RuntimeError("No non-empty ChatGPT assistant turn was found.")
        return snapshot["text"]

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
        """Return completion state for the same non-empty assistant we extract."""
        try:
            snapshot = await self._assistant_snapshot(page)
            if not snapshot:
                return {"copyVisible": False, "stopVisible": False}
            return {
                "copyVisible": bool(snapshot.get("copyVisible")),
                "stopVisible": bool(snapshot.get("stopVisible")),
            }
        except Exception as exc:
            if self._is_driver_connection_error(exc):
                raise
            return {"copyVisible": False, "stopVisible": False}

    async def _wait_for_answer(
        self,
        page,
        before: int,
        *,
        conversation_id: str | None,
        deadline: float,
    ):
        """Wait for one new complete assistant turn under a single time budget.

        Polling uses one short DOM snapshot per iteration. The snapshot ignores
        empty trailing assistant placeholders and carries text/completion state
        from one selected assistant node. The prompt has already been sent when
        this method runs; driver recovery therefore never calls _send().
        """
        active_conversation = conversation_id
        recovered_driver = False
        last_text = None
        stable_since = None

        while time.monotonic() < deadline:
            try:
                if active_conversation is None:
                    active_conversation = self._conversation_id_from_url(page.url)

                snapshot = await self._assistant_snapshot(page)
                if not snapshot or snapshot.get("index", -1) < before:
                    await asyncio.sleep(0.75)
                    continue

                current = snapshot.get("text") or None
                now = time.monotonic()

                if current:
                    if current != last_text:
                        last_text = current
                        stable_since = now

                    # Copy belongs to the same selected non-empty assistant turn.
                    if snapshot.get("copyVisible"):
                        return page, current, active_conversation

                    # DOM-drift fallback: unchanged text for 15 seconds with no
                    # visible Stop control. Use elapsed time rather than polling
                    # counts so scheduling jitter cannot shorten this guard.
                    if (
                        not snapshot.get("stopVisible")
                        and stable_since is not None
                        and now - stable_since >= 15.0
                    ):
                        return page, current, active_conversation

                await asyncio.sleep(0.75)
            except Exception as exc:
                if recovered_driver or not self._is_driver_connection_error(exc):
                    raise
                recovered_driver = True
                page, recovered_id = await self._recover_inflight_page(
                    active_conversation
                )
                active_conversation = recovered_id
                # The same ChatGPT DOM remains authoritative. Preserve `before`
                # and stability state; only the Playwright transport changed.
                continue

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
        finally:
            self._pw = None
            self._browser = None

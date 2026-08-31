"""Auto-restart the dedicated local browser when its CDP endpoint disappears."""
from __future__ import annotations

import asyncio
import os
import shlex
import sys
from pathlib import Path
from urllib.parse import urlparse


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def cdp_target(cdp_url: str) -> tuple[str, int] | None:
    """Return (host, port) only for a local HTTP(S) CDP endpoint."""
    parsed = urlparse(cdp_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _LOCAL_HOSTS:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return host, port


def default_start_command() -> list[str] | None:
    """Resolve the repository launcher for this platform, if present."""
    root = Path(__file__).resolve().parent.parent
    if os.name == "nt":
        script = root / "scripts" / "start-chrome-debug.ps1"
        if not script.is_file():
            return None
        return [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ]

    script = root / "scripts" / "start-chrome-debug.sh"
    if not script.is_file():
        return None
    return [str(script), "--background"]


def resolve_start_command(custom_command: str | None = None) -> list[str] | None:
    """Use an explicit command when configured, otherwise the repo launcher."""
    if custom_command and custom_command.strip():
        return shlex.split(custom_command)
    return default_start_command()


async def _tcp_ready(host: str, port: int) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=0.75
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def launch_local_browser(
    cdp_url: str,
    *,
    timeout: float = 20.0,
    custom_command: str | None = None,
) -> bool:
    """Launch the dedicated browser and wait for its local CDP port.

    Returns False instead of launching anything when the configured CDP endpoint
    is remote/non-local. Raises when local auto-start is requested but no launcher
    can be resolved or the endpoint never becomes ready.
    """
    target = cdp_target(cdp_url)
    if target is None:
        return False
    host, port = target

    if await _tcp_ready(host, port):
        return True

    command = resolve_start_command(custom_command)
    if not command:
        raise RuntimeError(
            "No browser start command is available. Set "
            "CHATGPT_BRIDGE_BROWSER_START_COMMAND or start the browser manually."
        )

    env = os.environ.copy()
    # Keep the launcher aligned with the CDP URL even when a non-default local
    # port is configured.
    env["CHATGPT_BRIDGE_CDP_PORT"] = str(port)

    creationflags = 0
    kwargs = {}
    if os.name == "nt":
        creationflags = getattr(__import__("subprocess"), "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True

    proc = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        creationflags=creationflags,
        **kwargs,
    )

    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await _tcp_ready(host, port):
            return True
        if proc.returncode is None:
            await asyncio.sleep(0.2)
        else:
            break

    # Avoid waiting on a foreground browser process on Linux. If the launcher
    # already exited, collect it so we do not leave a zombie process.
    if proc.returncode is not None:
        try:
            await proc.wait()
        except Exception:
            pass

    raise RuntimeError(
        f"Bridge browser launcher ran but CDP did not become ready at {cdp_url} "
        f"within {timeout:.0f}s."
    )

"""Test-suite-wide environment (from task 7.4).

**The suite never talks to a real LLM.** `app/core/config.py` loads settings
from the developer's `.env`, which on this machine holds a working Gemini key —
so without this file, every existing chat test would quietly start making
billed network calls to Google, and `test_placeholder_answer_quotes_no_figures`
would fail for the interesting reason that the assistant had actually answered.

Setting `LLM_PROVIDER=none` here makes "not connected" the default state for
tests, which is what the chat tests written in 7.1–7.3 assert against. Tests
that need a *connected* assistant build a provider explicitly and inject it
through `app.dependency_overrides[current_provider]` — see
`test_ai_provider.py`. That keeps the reach-the-network decision explicit and
local, rather than a property of whose machine the suite is running on.

This runs before any test module is imported, and environment variables take
precedence over `.env` in pydantic-settings, so it wins wherever the settings
object is first constructed.
"""

import os

os.environ["LLM_PROVIDER"] = "none"
os.environ["LLM_API_KEY"] = ""

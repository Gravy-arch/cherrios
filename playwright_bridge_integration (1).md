# TelegramBridge — Playwright Integration Guide

This guide explains how to wire `TelegramBridge` into your existing
Playwright script so it can ask users questions, send progress screenshots,
and send status messages — all via Telegram.

---

## 1. Copy the bridge file

Copy `services/telegram_bridge.py` from the bot project into your
Playwright project (anywhere on the Python path, e.g. `services/`).

---

## 2. Install dependencies

```bash
pip install asyncpg aiohttp
```

---

## 3. Resolve the meeting UUID

The bot creates a `meetings` row when the user completes the attendance
flow. Playwright needs to look up that UUID before starting — it's the
shared key used for everything.

```python
import asyncpg

async def get_meeting_id(conn, telegram_user_id: int, meeting_name: str) -> str:
    row = await conn.fetchrow(
        """
        SELECT id FROM meetings
        WHERE telegram_id = $1 AND name = $2
        ORDER BY created_at DESC
        LIMIT 1
        """,
        telegram_user_id, meeting_name,
    )
    if not row:
        raise ValueError(f"No meeting found for user={telegram_user_id} name={meeting_name!r}")
    return str(row["id"])
```

---

## 4. Wire TelegramBridge into your main()

```python
import asyncio
import asyncpg
from services.telegram_bridge import TelegramBridge

DB_URL           = "postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres"
BOT_TOKEN        = "your-bot-token"
SUPABASE_URL     = "https://[REF].supabase.co"
SUPABASE_KEY     = "your-service-role-key"
TELEGRAM_USER_ID = 123456789

async def main():
    conn = await asyncpg.connect(DB_URL)
    meeting_id = await get_meeting_id(conn, TELEGRAM_USER_ID, "Daily Standup")

    await conn.execute(
        "UPDATE meetings SET status = 'in_progress' WHERE id = $1", meeting_id
    )

    async with TelegramBridge(
        telegram_id=TELEGRAM_USER_ID,
        session_id=meeting_id,
        db_url=DB_URL,
        bot_token=BOT_TOKEN,
        supabase_url=SUPABASE_URL,       # required for save_progress_screenshot()
        supabase_key=SUPABASE_KEY,       # required for save_progress_screenshot()
        supabase_bucket="screenshots",   # must match your Supabase bucket name
    ) as bridge:
        browser   = Browser()
        memory    = Memory()
        brain     = Brain(memory)
        validator = Validator()
        executor  = Executor(memory, bridge=bridge)

        await bridge.send_message("🚀 Session started. Navigating to the page…")
        await browser.open("https://your-url.com", headless=False)

        while True:
            try:
                page_data = await browser.extract_page()
                await asyncio.sleep(2)
                decision  = brain.decide(page_data)
                decision  = validator.validate(decision, page_data, memory)

                if any(a["type"] == "require_vision" for a in decision["actions"]):
                    screenshot_path = "page.png"
                    await browser.page.screenshot(path=screenshot_path, full_page=True)
                    # Sends to user AND saves to Supabase for /track view
                    await bridge.save_progress_screenshot(
                        screenshot_path, caption="👁 Vision fallback triggered"
                    )
                    vision_decision = await executor.handle_vision(screenshot_path, page_data)
                    decision = validator.validate(vision_decision, page_data, memory)

                await executor.execute(decision, browser.page, page_data)
                await asyncio.sleep(6)

            except Exception as e:
                print(str(e))
                continue

    await conn.execute(
        "UPDATE meetings SET status = 'completed', completed_at = NOW() WHERE id = $1",
        meeting_id,
    )
    await bridge.send_message("✅ Session completed successfully!")
    await conn.close()

asyncio.run(main())
```

---

## 5. Replace CLI input in Executor

```python
class Executor:
    def __init__(self, memory, bridge=None):
        self.memory = memory
        self.bridge = bridge

    async def _get_input(self, prompt: str) -> str:
        """Universal input helper — Telegram if bridge available, else CLI."""
        if self.bridge:
            return await self.bridge.ask_user(prompt)
        return input(prompt)   # fallback for local testing without bot
```

Replace every `input()` call:

```python
# Before
username = input("Enter your username: ")
password = input("Enter your password: ")

# After
username = await self._get_input("Please enter your university username:")
password = await self._get_input("Please enter your password:")
```

### What the user sees in Telegram

```
🤖 Your session needs input:

Please enter your university username:

[❌ Cancel Session]
```

User types reply → bot shows confirmation:

```
📝 Please confirm your reply:

Question: Please enter your university username:
Your answer: john.doe123

[✅ Confirm]  [✏️ Re-enter]
[❌ Cancel]
```

Only after **Confirm** does `ask_user()` return. **Re-enter** lets them retype.
**Cancel** raises `TimeoutError` — always handle it:

```python
try:
    username = await self._get_input("Enter your student username:")
    password = await self._get_input("Enter your password:")
    otp      = await self._get_input("Enter the OTP from your authenticator app:")
except TimeoutError:
    await self.bridge.send_message("❌ Session cancelled — no input received.")
    return
```

---

## 6. Screenshots — which method to use

There are two screenshot methods on the bridge. Use the right one:

| Method | Sends to user now | Saved for /track → 📸 Progress |
|---|---|---|
| `send_screenshot(path, caption)` | ✅ instant | ❌ not stored |
| `save_progress_screenshot(path, caption)` | ✅ instant | ✅ stored in Supabase |
| `send_message(text)` | ✅ text only | ❌ |

**Use `save_progress_screenshot()` for meaningful milestones** — login
confirmed, quiz page loaded, answer submitted etc. These build up the
visual timeline the user sees when they tap 📸 Progress in the bot.

**Use `send_screenshot()` for ephemeral/debug shots** you want the user
to see in the moment but don't need stored.

```python
await browser.page.screenshot(path="page.png", full_page=True)

# Milestone — store it AND send it
await bridge.save_progress_screenshot("page.png", caption="✅ Logged in successfully")

# Quick debug shot — send only, don't store
await bridge.send_screenshot("page.png", caption="Checking CAPTCHA…")
```

`save_progress_screenshot()` does three things in one call:
1. Uploads PNG to Supabase Storage at `screenshots/{meeting_id}/{timestamp}.png`
2. Inserts a `screenshots` DB row with the public URL
3. Sends the image to the user via Telegram Bot API instantly

No extra wiring needed — just call it.

---

## 7. Status messages

```python
await bridge.send_message("⏳ Navigating to the quiz page…")
await bridge.send_message("Question <b>5/12</b> answered ✅")   # HTML ok
await bridge.send_message("🎉 All done! Results screenshot coming up.")
```

---

## 8. Full data / status contract

| Who writes | What | When |
|---|---|---|
| **Bot** | `meetings` row (`status: pending`) | User completes attendance flow |
| **Playwright** | `meetings.status = in_progress` | Session starts |
| **Playwright** | `playwright_requests` row | Needs user input |
| **Bot poller** | Sets user FSM state, marks row `sent` | Every 2s scan |
| **User** | Types reply + confirms in Telegram | After seeing question |
| **Bot handler** | `playwright_requests.answer`, `status: answered` | User confirms |
| **Playwright** | `screenshots` row + Supabase Storage file | `save_progress_screenshot()` |
| **Playwright** | `meetings.status = completed` | Session ends |

-- =============================================================================
-- Attendance Bot — Full Database Schema
-- Run this once in the Supabase SQL Editor (or via psql).
-- Supabase Dashboard → SQL Editor → New query → paste → Run
-- =============================================================================


-- ── Users ──────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    telegram_id  BIGINT       PRIMARY KEY,
    username     VARCHAR(255),
    first_name   VARCHAR(255) NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);


-- ── Subscriptions ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS subscriptions (
    id           SERIAL        PRIMARY KEY,
    telegram_id  BIGINT        NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,

    -- 'one_time' or 'monthly'
    plan_type    VARCHAR(20)   NOT NULL,

    -- Status lifecycle:
    --   pending  → payment not yet confirmed
    --   active   → payment confirmed, can use the bot
    --   used     → one_time plan consumed after one attendance verification
    --   expired  → monthly plan past its expiry date
    status       VARCHAR(20)   NOT NULL DEFAULT 'pending',

    -- NOWPayments fields
    payment_id   VARCHAR(255)  NOT NULL UNIQUE,
    pay_address  VARCHAR(255)  NOT NULL,
    pay_amount   NUMERIC(18,8) NOT NULL,
    pay_currency VARCHAR(30)   NOT NULL,
    price_usd    NUMERIC(10,2) NOT NULL,

    -- Timestamps
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    expires_at   TIMESTAMPTZ,           -- monthly plans only
    used_at      TIMESTAMPTZ            -- one_time plans only
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_telegram_status
    ON subscriptions (telegram_id, status);

CREATE INDEX IF NOT EXISTS idx_subscriptions_payment_id
    ON subscriptions (payment_id);


-- ── Meetings ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS meetings (
    -- UUID shared between the bot and Playwright.
    -- Playwright queries: SELECT id FROM meetings WHERE telegram_id=$1 AND name=$2
    -- then uses this id as the Supabase Storage folder for screenshots.
    id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id  BIGINT        NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,

    -- Human-readable name the user gave this meeting (e.g. "Daily Standup")
    name         VARCHAR(100)  NOT NULL,

    -- The meeting URL submitted in the attendance flow
    link         TEXT          NOT NULL,

    -- Status lifecycle (updated by Playwright):
    --   pending     → bot submitted, Playwright hasn't started yet
    --   in_progress → Playwright is actively attending the meeting
    --   completed   → Playwright finished, all screenshots saved
    status       VARCHAR(20)   NOT NULL DEFAULT 'pending',

    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    CONSTRAINT meetings_name_length CHECK (char_length(name) >= 2)
);

CREATE INDEX IF NOT EXISTS idx_meetings_telegram_id
    ON meetings (telegram_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_meetings_user_name
    ON meetings (telegram_id, name);


-- ── Screenshots ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS screenshots (
    id           SERIAL       PRIMARY KEY,

    -- Foreign key to meetings.id (the shared UUID)
    meeting_id   UUID         NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,

    -- Full public URL in Supabase Storage.
    -- Storage path convention: screenshots/{meeting_id}/{taken_at_epoch_ms}.png
    storage_url  TEXT         NOT NULL,

    -- When Playwright took this screenshot
    taken_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screenshots_meeting_id
    ON screenshots (meeting_id, taken_at ASC);


-- ── Playwright Requests (bot ↔ Playwright message bus) ────────────────────────

CREATE TABLE IF NOT EXISTS playwright_requests (
    -- UUID so Playwright can reference a specific question row
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),

    -- The meetings.id UUID — ties this request to a specific session
    session_id   UUID         NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,

    -- The user Playwright needs input from
    telegram_id  BIGINT       NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,

    -- The question Playwright is asking
    question     TEXT         NOT NULL,

    -- The user's reply (written by the bot after the user responds)
    answer       TEXT,

    -- Status lifecycle:
    --   pending    → Playwright inserted row, bot hasn't sent it yet
    --   sent       → Bot forwarded the question to the user
    --   answered   → User replied, answer is written, Playwright can read it
    --   timed_out  → User didn't reply within the timeout window
    status       VARCHAR(20)  NOT NULL DEFAULT 'pending',

    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    sent_at      TIMESTAMPTZ,
    answered_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_playwright_requests_session
    ON playwright_requests (session_id);

CREATE INDEX IF NOT EXISTS idx_playwright_requests_user_status
    ON playwright_requests (telegram_id, status);
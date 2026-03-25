-- db/migrations/001_meetings_screenshots.sql
-- Run this after schema.sql if you already have the DB set up,
-- or append to schema.sql if you're starting fresh.
-- psql -U youruser -d yourdb -f db/migrations/001_meetings_screenshots.sql

-- ── Meetings ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS meetings (
    -- UUID is the shared key between the bot and Playwright.
    -- Playwright looks up this id by (user_id + name) and uses it
    -- as the folder/prefix when saving screenshots.
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id  BIGINT       NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,

    -- Human-readable name the user gave this meeting (e.g. "Daily Standup")
    name         VARCHAR(100) NOT NULL,

    -- The meeting URL submitted in the attendance flow
    link         TEXT         NOT NULL,

    -- Status lifecycle (updated by Playwright via direct DB write):
    --   pending     → bot submitted, Playwright hasn't started yet
    --   in_progress → Playwright is actively running the session
    --   completed   → Playwright finished, all screenshots saved
    status       VARCHAR(20)  NOT NULL DEFAULT 'pending',

    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    -- Soft uniqueness: same user shouldn't reuse the same name actively,
    -- but we allow it across different times (no UNIQUE constraint).
    CONSTRAINT meetings_name_length CHECK (char_length(name) >= 2)
);

-- Fast lookup: all meetings for a user ordered newest first
CREATE INDEX IF NOT EXISTS idx_meetings_telegram_id
    ON meetings (telegram_id, created_at DESC);

-- Playwright lookup: find a meeting by user + name
CREATE INDEX IF NOT EXISTS idx_meetings_user_name
    ON meetings (telegram_id, name);


-- ── Screenshots ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS screenshots (
    id           SERIAL       PRIMARY KEY,

    -- Foreign key to meetings.id (the shared UUID)
    meeting_id   UUID         NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,

    -- Full public URL in Supabase Storage (or S3/R2).
    -- Storage path convention: screenshots/{meeting_id}/{taken_at_epoch}.png
    storage_url  TEXT         NOT NULL,

    -- When Playwright took this screenshot
    taken_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screenshots_meeting_id
    ON screenshots (meeting_id, taken_at ASC);

-- ==============================================================================
-- QueueSense – Supabase PostgreSQL Cloud Schema
-- Run this script in your Supabase SQL Editor (https://supabase.com/dashboard)
-- ==============================================================================

-- 1. Real-time Queue Status Table
CREATE TABLE IF NOT EXISTS queue_status (
    queue_name TEXT PRIMARY KEY,
    occupancy INTEGER NOT NULL DEFAULT 0,
    total_entries INTEGER NOT NULL DEFAULT 0,
    total_exits INTEGER NOT NULL DEFAULT 0,
    average_wait_seconds REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- 2. Historical Snapshots Table
CREATE TABLE IF NOT EXISTS queue_history (
    id BIGSERIAL PRIMARY KEY,
    queue_name TEXT NOT NULL,
    occupancy INTEGER NOT NULL,
    total_entries INTEGER NOT NULL,
    total_exits INTEGER NOT NULL,
    average_wait_seconds REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    video_hash TEXT,
    session_id TEXT,
    video_name TEXT
);

CREATE INDEX IF NOT EXISTS idx_queue_history_recorded_at ON queue_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_queue_history_name_time ON queue_history(queue_name, recorded_at);
CREATE INDEX IF NOT EXISTS idx_queue_history_video_queue ON queue_history(video_hash, queue_name);
CREATE INDEX IF NOT EXISTS idx_queue_history_session ON queue_history(session_id);

-- 3. Queue Alert Limits (Hardware buzzer thresholds)
CREATE TABLE IF NOT EXISTS queue_alert_limits (
    queue_name TEXT PRIMARY KEY,
    limit_people INTEGER NOT NULL DEFAULT 5,
    updated_at TEXT NOT NULL
);

-- Insert default limits if not already present
INSERT INTO queue_alert_limits (queue_name, limit_people, updated_at)
VALUES 
    ('student', 3, NOW()::TEXT),
    ('faculty', 3, NOW()::TEXT),
    ('scholar', 3, NOW()::TEXT)
ON CONFLICT (queue_name) DO NOTHING;

-- 4. RFID Attendance Events
CREATE TABLE IF NOT EXISTS attendance_events (
    id BIGSERIAL PRIMARY KEY,
    card_uid TEXT NOT NULL,
    roll_number TEXT,
    student_name TEXT,
    event_type TEXT NOT NULL,
    event_time TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attendance_events_time ON attendance_events(event_time);
CREATE INDEX IF NOT EXISTS idx_attendance_events_roll ON attendance_events(roll_number);

-- Enable Row Level Security (RLS) with permissive access for QueueSense service
ALTER TABLE queue_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE queue_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE queue_alert_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_events ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service read/write on queue_status') THEN
        CREATE POLICY "Allow service read/write on queue_status" ON queue_status FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service read/write on queue_history') THEN
        CREATE POLICY "Allow service read/write on queue_history" ON queue_history FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service read/write on queue_alert_limits') THEN
        CREATE POLICY "Allow service read/write on queue_alert_limits" ON queue_alert_limits FOR ALL USING (true) WITH CHECK (true);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'Allow service read/write on attendance_events') THEN
        CREATE POLICY "Allow service read/write on attendance_events" ON attendance_events FOR ALL USING (true) WITH CHECK (true);
    END IF;
END $$;

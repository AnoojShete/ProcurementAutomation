-- Control Panel Kafka log, kept across restarts (FR-06). One row per
-- Kafka record (topic, partition, offset), holding only the summarised,
-- allow-listed fields the event monitor shows — never full payloads.
-- Old rows are deleted by the monitor (rule monitor.event_log_retention_days).
CREATE TABLE IF NOT EXISTS event_log (
  id BIGSERIAL PRIMARY KEY,
  topic TEXT NOT NULL,
  kafka_partition INTEGER NOT NULL,
  kafka_offset BIGINT NOT NULL,
  event_time TIMESTAMPTZ,
  event_type TEXT,
  source_service TEXT,
  correlation_id TEXT,
  message TEXT,
  fields JSONB NOT NULL DEFAULT '{}'::jsonb,
  stored_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (topic, kafka_partition, kafka_offset)
);
CREATE INDEX IF NOT EXISTS idx_event_log_time ON event_log (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_event_log_topic_time ON event_log (topic, event_time DESC);
CREATE INDEX IF NOT EXISTS idx_event_log_correlation ON event_log (correlation_id);

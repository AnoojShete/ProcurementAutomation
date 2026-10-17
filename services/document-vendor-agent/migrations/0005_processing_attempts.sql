-- How many times the worker has started processing a document. Lets the
-- stranded-document sweep retry after a crash or an infrastructure error,
-- but give up (and say so) instead of looping forever on a poison file.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS processing_attempts INTEGER NOT NULL DEFAULT 0

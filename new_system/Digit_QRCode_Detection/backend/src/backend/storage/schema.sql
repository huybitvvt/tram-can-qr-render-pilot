CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qr_data TEXT NOT NULL,
    raw_digits TEXT NOT NULL,
    numeric_value REAL NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_measurements_created_at ON measurements(created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_measurements_duplicate_lookup ON measurements(qr_data, numeric_value, created_at DESC);

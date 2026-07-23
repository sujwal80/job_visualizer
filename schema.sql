CREATE TABLE IF NOT EXISTS user_profiles (
    id TEXT PRIMARY KEY,
    email TEXT,
    name TEXT,
    picture TEXT,
    bio TEXT,
    skills TEXT,
    preferred_location TEXT,
    job_preferences TEXT
);

CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    company_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

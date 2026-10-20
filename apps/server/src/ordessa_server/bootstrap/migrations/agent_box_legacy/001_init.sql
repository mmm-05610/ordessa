-- agent-box schema (v2, ACS-only)
--
-- agent-box owns ONLY the local profile + session lifecycle. All
-- resource data (providers, MCP servers, skills, prompts) lives in
-- ACS (agent-config-store) and is read via
-- :mod:`agent_box.adapters.acs`. See:
--   workspace/specs/remove-agent-box-crud.md

-- 1. profiles
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    agent_type TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    provider_ref TEXT,
    claude_md_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. sessions
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    cwd TEXT,
    mode TEXT,
    pid INTEGER,
    launched_at TEXT NOT NULL,
    exited_at TEXT,
    exit_code INTEGER
);

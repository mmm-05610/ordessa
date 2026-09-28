-- 002: rename claude_md_ref → prompt_ref
-- The column previously tracked the Claude-specific prompt file reference.
-- "prompt" is the agent-type-agnostic term used by apply_prompt().

ALTER TABLE profiles RENAME COLUMN claude_md_ref TO prompt_ref;

-- =========================================================================
-- Normalize user_accounts for plain password auth
-- Use this if 006 was already run with password_hash/password_salt columns.
-- =========================================================================

ALTER TABLE user_accounts
ADD COLUMN IF NOT EXISTS password TEXT;

UPDATE user_accounts
SET password = COALESCE(password, '')
WHERE password IS NULL;

ALTER TABLE user_accounts
ALTER COLUMN password SET NOT NULL;

ALTER TABLE user_accounts
DROP COLUMN IF EXISTS password_hash;

ALTER TABLE user_accounts
DROP COLUMN IF EXISTS password_salt;

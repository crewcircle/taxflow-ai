-- Lightweight, non-authenticated staff list for the "reviewed/approved by"
-- sign-off feature. No login of its own - the firm's single Supabase account
-- picks a name from this list at sign-off time. Follows the same pattern as
-- the existing firm_style jsonb column: small, flexible, firm-level config
-- that doesn't need its own table.
ALTER TABLE clients ADD COLUMN staff_directory jsonb NOT NULL DEFAULT '[]';

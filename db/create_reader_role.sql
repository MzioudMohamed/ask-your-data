-- Read-only role used by the copilot to run generated SQL.
-- Run as the admin user:
--   psql -U askdata -d askdata -v reader_password=... -f /db/create_reader_role.sql
-- Re-runnable: the role is created once, then password, settings and grants are re-applied.

SELECT 'CREATE ROLE askdata_reader LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'askdata_reader')
\gexec

ALTER ROLE askdata_reader WITH LOGIN PASSWORD :'reader_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

-- Settings applied to every session of this role.
ALTER ROLE askdata_reader SET default_transaction_read_only = on;
ALTER ROLE askdata_reader SET statement_timeout = '10s';
ALTER ROLE askdata_reader SET idle_in_transaction_session_timeout = '10s';

-- No temporary tables for anybody except the admin user (superusers are not affected).
REVOKE TEMPORARY ON DATABASE askdata FROM PUBLIC;

-- Access: connect, and read the marts schema only.
GRANT CONNECT ON DATABASE askdata TO askdata_reader;
GRANT USAGE ON SCHEMA marts TO askdata_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA marts TO askdata_reader;

-- dbt drops and recreates the marts tables: tables created later must be readable too.
ALTER DEFAULT PRIVILEGES FOR ROLE askdata IN SCHEMA marts GRANT SELECT ON TABLES TO askdata_reader;
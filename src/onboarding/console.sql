CREATE TABLE console_sessions(session_hash text PRIMARY KEY,actor text NOT NULL,role text NOT NULL,
 companies jsonb NOT NULL,csrf text NOT NULL,expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE console_login_attempts(key text PRIMARY KEY,attempts integer NOT NULL,started_at timestamptz NOT NULL DEFAULT clock_timestamp());

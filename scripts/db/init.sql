-- Runs once when the Postgres volume is first created.
-- Extensions and the test database. Roles and tables come from Alembic migrations.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE DATABASE callwright_test OWNER callwright;
\connect callwright_test
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;

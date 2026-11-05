-- PostgreSQL initialisation script
-- Runs automatically when the container is first created.
-- Enables the pgvector extension required for semantic search.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgvector";

#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE hyperagent_logs;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" -d hyperagent_logs \
    -f /docker-hyperagent-logs/schema_hyperagent_logs.sql

"""Guarded PostgreSQL migration for AgentBridge fencing metadata.

This first migration is intentionally additive. Rollback never silently drops
existing operator data. More migrations must be added as reviewed immutable IDs
with independent rollback/no-rollback decisions.
"""
from __future__ import annotations

import hashlib

import psycopg
from psycopg import sql


class MigrationDenied(RuntimeError):
    pass


_MIGRATION="2026-10-12-fencing-v1"
_DDL=("CREATE TABLE agentbridge_fences ("
      "scope TEXT PRIMARY KEY,owner TEXT NOT NULL,"
      "epoch BIGINT NOT NULL CHECK(epoch>=1),expires TIMESTAMPTZ NOT NULL)")
_DIGEST=hashlib.sha256(_DDL.encode()).hexdigest()


class FencingMigration:
    def __init__(self,dsn,schema="public"):
        if not isinstance(dsn,str) or not dsn:
            raise ValueError("PostgreSQL DSN required")
        if not isinstance(schema,str) or not schema or len(schema)>63:
            raise ValueError("valid PostgreSQL schema name required")
        self.dsn,self.schema=dsn,schema

    def _table(self,name):
        return sql.Identifier(self.schema,name)

    def apply(self):
        with psycopg.connect(self.dsn) as conn,conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                         ("agentbridge-migrations:"+self.schema,))
            conn.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} ("
                                 "migration_id TEXT PRIMARY KEY,ddl_sha256 TEXT NOT NULL,"
                                 "created_table BOOLEAN NOT NULL,"
                                 "applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())").format(
                                     self._table("agentbridge_schema_migrations")))
            row=conn.execute(sql.SQL("SELECT ddl_sha256 FROM {} WHERE migration_id=%s").format(
                self._table("agentbridge_schema_migrations")),(_MIGRATION,)).fetchone()
            if row:
                if row[0]!=_DIGEST:
                    raise MigrationDenied("migration source digest changed")
                return False
            existed=conn.execute("SELECT to_regclass(%s)",(
                f"{self.schema}.agentbridge_fences",)).fetchone()[0] is not None
            if not existed:
                conn.execute(sql.SQL(_DDL.replace("agentbridge_fences","{}")).format(
                    self._table("agentbridge_fences")))
            conn.execute(sql.SQL("INSERT INTO {} (migration_id,ddl_sha256,created_table)"
                                 " VALUES(%s,%s,%s)").format(
                                     self._table("agentbridge_schema_migrations")),
                         (_MIGRATION,_DIGEST,not existed))
            return True

    def rollback(self):
        with psycopg.connect(self.dsn) as conn,conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                         ("agentbridge-migrations:"+self.schema,))
            row=conn.execute(sql.SQL(
                "SELECT ddl_sha256,created_table FROM {} WHERE migration_id=%s "
                "FOR UPDATE").format(self._table("agentbridge_schema_migrations")),
                             (_MIGRATION,)).fetchone()
            if row is None:
                return False
            if row[0]!=_DIGEST:
                raise MigrationDenied("cannot roll back altered migration")
            if row[1]:
                num=conn.execute(sql.SQL("SELECT count(*) FROM {}").format(
                    self._table("agentbridge_fences"))).fetchone()[0]
                if num:
                    raise MigrationDenied("fencing table contains live state; manual migration required")
                conn.execute(sql.SQL("DROP TABLE {}").format(
                    self._table("agentbridge_fences")))
            conn.execute(sql.SQL("DELETE FROM {} WHERE migration_id=%s").format(
                self._table("agentbridge_schema_migrations")),(_MIGRATION,))
            return True

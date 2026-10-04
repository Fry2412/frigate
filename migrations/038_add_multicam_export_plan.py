"""Persist all source cameras and the reproducible multicamera edit plan."""


def migrate(migrator, database, fake=False, **kwargs):
    migrator.sql("ALTER TABLE export ADD COLUMN composite_plan TEXT NULL")


def rollback(migrator, database, fake=False, **kwargs):
    migrator.sql("ALTER TABLE export DROP COLUMN composite_plan")

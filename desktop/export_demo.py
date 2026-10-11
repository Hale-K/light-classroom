"""Export one school's PostgreSQL data and referenced files to an offline demo.

Run with backend/.venv/Scripts/python.exe desktop/export_demo.py --phone ...
--output output/demo-seed. Source credentials come from backend/.env; the
source transaction is read-only. The destination must be a new directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlsplit


def export(phone: str, output: Path) -> None:
    backend = Path(__file__).resolve().parents[1] / "backend"
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    from sqlalchemy import create_engine, inspect, text
    from sqlmodel import SQLModel
    from app.core.config import settings
    from app.core.security import get_password_hash
    import app.models  # noqa: F401 — register every table, including AI models
    from app.db.session import _sync_schema
    from app.services.storage.minio_client import get_bytes

    output.mkdir(parents=True, exist_ok=False)
    source = create_engine(settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2"))
    target_path = output / "light-classroom.db"
    target = create_engine(f"sqlite:///{target_path.as_posix()}")
    with target.begin() as conn:
        _sync_schema(conn)
    target.dispose()
    rows_by_table: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    with source.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        matches = conn.execute(text('SELECT id, tenant_id, name FROM "user" WHERE phone=:phone'), {"phone": phone}).mappings().all()
        if len(matches) != 1:
            raise ValueError("Account must identify exactly one school")
        account = dict(matches[0])
        tenant_id = account["tenant_id"]
        inspector = inspect(conn)
        tables = inspector.get_table_names()
        quote = conn.dialect.identifier_preparer.quote
        columns = {name: {c["name"] for c in inspector.get_columns(name)} for name in tables}

        def read(name: str, where: str = "", params: dict | None = None) -> list[dict]:
            return [dict(row) for row in conn.execute(text(f"SELECT * FROM {quote(name)} {where}"), params or {}).mappings()]

        for name in tables:
            if "tenant_id" in columns[name]:
                rows_by_table[name] = read(name, "WHERE tenant_id=:tid", {"tid": tenant_id})
        rows_by_table["tenant"] = read("tenant", "WHERE id=:tid", {"tid": tenant_id})
        for name in ("permission", "menu", "menu_permission", "ai_intent_example"):
            rows_by_table[name] = read(name)
        child_tables = {
            "rolepermission": ("role_id", "role"),
            "userrole": ("user_id", "user"),
            "scheduling_grid_day": ("plan_id", "scheduling_grid_plan"),
            "scheduling_grid_slot": ("plan_id", "scheduling_grid_plan"),
            "scheduling_grid_subject": ("plan_id", "scheduling_grid_plan"),
            "walk_scheduling_room": ("plan_id", "walk_scheduling_plan"),
            "walk_scheduling_slot": ("plan_id", "walk_scheduling_plan"),
        }
        for name, (fk, parent) in child_tables.items():
            ids = [row["id"] for row in rows_by_table[parent]]
            rows_by_table[name] = read(name, f"WHERE {quote(fk)} IN ({','.join(str(int(i)) for i in ids)})") if ids else []
        unknown = set(tables) - set(rows_by_table) - {"platformadmin", "alembic_version"}
        if unknown:
            raise ValueError(f"Unclassified source tables: {sorted(unknown)}")

        # Include shared dictionary records referenced by this school; never
        # silently include records from another school to satisfy a foreign key.
        added = True
        while added:
            added = False
            for name in list(rows_by_table):
                for fk in inspector.get_foreign_keys(name):
                    local, remote = fk["constrained_columns"], fk["referred_columns"]
                    if len(local) != 1 or len(remote) != 1:
                        raise ValueError(f"Composite foreign key needs explicit handling: {name}")
                    parent = fk["referred_table"]
                    existing = {row[remote[0]] for row in rows_by_table.get(parent, [])}
                    needed = {row[local[0]] for row in rows_by_table[name] if row[local[0]] is not None} - existing
                    for value in needed:
                        found = read(parent, f"WHERE {quote(remote[0])}=:value", {"value": value})
                        if len(found) != 1 or found[0].get("tenant_id") not in (None, tenant_id):
                            raise ValueError(f"Missing/cross-school reference: {name}.{local[0]}")
                        rows_by_table.setdefault(parent, []).extend(found)
                        added = True
        school = rows_by_table["tenant"][0]
        for row in rows_by_table.get("ai_provider", []):
            row["api_key"] = ""
            row["status"] = 0
        rows_by_table["platformadmin"] = [{
            "id": 1, "username": "admin", "name": "演示管理员",
            "password_hash": get_password_hash("admin123456"), "status": "active",
            "created_at": datetime.now(timezone.utc).replace(tzinfo=None), "last_login_at": None,
        }]

        def sqlite_value(value):
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            if isinstance(value, (date, datetime)):
                return value.isoformat(" ") if isinstance(value, datetime) else value.isoformat()
            if isinstance(value, Decimal):
                return float(value)
            return value

        with sqlite3.connect(target_path) as db:
            for name, rows in rows_by_table.items():
                counts[name] = len(rows)
                target_columns = {r[1] for r in db.execute(f'PRAGMA table_info("{name}")')}
                if name not in SQLModel.metadata.tables:
                    raise ValueError(f"Source table is not registered in application: {name}")
                extra = columns.get(name, set()) - target_columns
                if extra:
                    raise ValueError(f"Source columns would be lost: {name} {sorted(extra)}")
                if not rows:
                    continue
                keys = list(rows[0])
                col_sql = ",".join(f'"{key}"' for key in keys)
                placeholders = ",".join("?" for _ in keys)
                db.executemany(f'INSERT INTO "{name}" ({col_sql}) VALUES ({placeholders})', [[sqlite_value(row[k]) for k in keys] for row in rows])
            failures = db.execute("PRAGMA foreign_key_check").fetchall()
            if failures:
                raise ValueError(f"Foreign key check failed: {failures[:10]}")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity check failed")

        files: list[dict] = []
        missing_files: list[str] = []

        def store_file(relative: str, data: bytes):
            dest = (output / relative).resolve()
            if not dest.is_relative_to(output.resolve()):
                raise ValueError("Unsafe attachment path")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            files.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

        keys = {str(row["object_key"]) for row in rows_by_table["file_transfer_job"] if row.get("object_key")}
        for key in sorted(keys):
            if settings.storage_local_dir and not (Path(settings.storage_local_dir) / key).is_file():
                missing_files.append("storage/" + key)
                continue
            store_file("storage/" + key, get_bytes(key))

        # Images and locally uploaded documents can occur in nested JSON settings.
        upload_paths: set[str] = set()
        def find_uploads(value):
            if isinstance(value, dict):
                for child in value.values(): find_uploads(child)
            elif isinstance(value, list):
                for child in value: find_uploads(child)
            elif isinstance(value, str):
                path = unquote(urlsplit(value).path)
                if path.startswith("/uploads/"):
                    upload_paths.add(path.removeprefix("/uploads/"))
        for rows in rows_by_table.values():
            for row in rows: find_uploads(row)
        upload_root = Path(os.environ.get("LIGHT_UPLOAD_DIR", str(backend / "uploads"))).resolve()
        for relative in sorted(upload_paths):
            attachment = (upload_root / relative).resolve()
            if not attachment.is_relative_to(upload_root):
                raise ValueError("Unsafe upload reference")
            if attachment.is_file():
                store_file("uploads/" + relative, attachment.read_bytes())
            else:
                missing_files.append("uploads/" + relative)

    manifest = {
        "format": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "school_code": school["code"], "school_name": school["name"],
        "tenant_id": tenant_id, "account_id": account["id"], "account_name": account["name"],
        "counts": counts, "files": files, "missing_files": missing_files,
        "provider_keys_removed": True,
        "database_sha256": hashlib.sha256(target_path.read_bytes()).hexdigest(),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "rows": sum(counts.values()), "tables": len(counts), "files": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(args.phone, args.output.resolve())

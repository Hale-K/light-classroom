# -*- coding: utf-8 -*-
"""诊断数据库字符集并修正乱码数据（租户名 / 用户名）。

乱码根因：建库时 client_encoding 未用 UTF8，中文写入时被映射成 '?' 丢失。
本脚本：(1) 打印数据库与客户端编码；(2) 将乱码(含 '?')的名称按已知映射修正为 UTF8 中文。
"""
import asyncio
import asyncpg

# 已知业务账号的期望名称：phone -> name
NAME_MAP = {
    "13900001111": "校长",
    "13800000000": "老师",
    "13800138899": "老师",
}
# 已知业务租户代码的期望名称：code -> name
TENANT_MAP = {
    "jxyn": "江淮一中",
    "demo": "演示学校",
}


async def main():
    c = await asyncpg.connect(
        user="postgres", password="123456", database="zhiheng",
        host="localhost", port=5432)
    try:
        print("DB 编码:       ", await c.fetchval(
            "SELECT encoding FROM pg_database WHERE datname='zhiheng'"))
        print("server_encoding:", await c.fetchval("SHOW server_encoding"))
        print("client_encoding:", await c.fetchval("SHOW client_encoding"))
        # 连接级强制 UTF8，保证后续写入正确
        await c.execute("SET client_encoding TO 'UTF8'")

        # 修正租户名
        print("\n===== 租户 =====")
        for code, new_name in TENANT_MAP.items():
            rows = await c.fetch('SELECT id, code, name FROM "tenant" WHERE code=$1', code)
            for r in rows:
                print(f"BEFORE: id={r['id']} code={r['code']} name={r['name']!r}")
                if r["name"] and "/[?]|[\uFFFD]/" and any(ch in (r["name"] or "") for ch in "?\ufffd"):
                    await c.execute('UPDATE "tenant" SET name=$1 WHERE id=$2', new_name, r["id"])
                after = await c.fetchval('SELECT name FROM "tenant" WHERE id=$1', r["id"])
                print(f"AFTER : id={r['id']} name={after!r}")

        # 修正用户名
        print("\n===== 用户 =====")
        for phone, new_name in NAME_MAP.items():
            rows = await c.fetch('SELECT id, phone, name, role FROM "user" WHERE phone=$1', phone)
            for r in rows:
                print(f"BEFORE: id={r['id']} phone={r['phone']} role={r['role']} name={r['name']!r}")
                cur = r["name"] or ""
                if any(ch in cur for ch in "?\ufffd") or (cur and not any('\u4e00' <= ch <= '\u9fff' for ch in cur)):
                    await c.execute('UPDATE "user" SET name=$1 WHERE id=$2', new_name, r["id"])
                    print(f"UPDATED: name -> {new_name!r}")
                after = await c.fetchval('SELECT name FROM "user" WHERE id=$1', r["id"])
                print(f"AFTER : id={r['id']} name={after!r}")

        print("\n===== 全部用户 =====")
        for r in await c.fetch('SELECT id, phone, name, role FROM "user" ORDER BY id'):
            print(f"id={r['id']} phone={r['phone']} role={r['role']} name={r['name']!r}")

        print("\n===== 全部租户 =====")
        for r in await c.fetch('SELECT id, code, name FROM "tenant" ORDER BY id'):
            print(f"id={r['id']} code={r['code']} name={r['name']!r}")
    finally:
        await c.close()


asyncio.run(main())
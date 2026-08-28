# -*- coding: utf-8 -*-
"""一次性脚本：修正 jxyn 乱的学校名称为「江淮一中」（不依赖命令行编码）。"""
import asyncio
import asyncpg

NEW_NAME = "江淮一中"


async def main() -> None:
    c = await asyncpg.connect(
        user="postgres", password="123456", database="zhiheng", host="localhost", port=5432
    )
    row = await c.fetchrow("SELECT id, code, name FROM tenant WHERE code=$1", "jxyn")
    if row is None:
        print("NOT_FOUND: jxyn")
        return
    print("BEFORE:", row["id"], row["code"], repr(row["name"]))
    await c.execute("UPDATE tenant SET name=$1 WHERE id=$2", NEW_NAME, row["id"])
    after = await c.fetchrow("SELECT id, code, name FROM tenant WHERE code=$1", "jxyn")
    print("AFTER: ", after["id"], after["code"], repr(after["name"]))
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
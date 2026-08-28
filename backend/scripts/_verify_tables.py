"""一次性验证：列出 lightclass 库实际表清单"""
import psycopg2

c = psycopg2.connect(host="localhost", port=5432, user="postgres", password="123456", dbname="lightclass")
cur = c.cursor()
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
rows = [r[0] for r in cur.fetchall()]
print(f"DB_TABLES={len(rows)}")
print(", ".join(rows))
c.close()
import sys, psycopg2
action = sys.argv[1]  # create | drop
c = psycopg2.connect(dbname='postgres', user='postgres', password='123456',
                     host='localhost', port='5432')
c.autocommit = True
cur = c.cursor()
if action == 'create':
    cur.execute("DROP DATABASE IF EXISTS zhiheng_alembic_baseline")
    cur.execute("CREATE DATABASE zhiheng_alembic_baseline")
    print('temp db created')
elif action == 'drop':
    cur.execute("DROP DATABASE IF EXISTS zhiheng_alembic_baseline")
    print('temp db dropped')
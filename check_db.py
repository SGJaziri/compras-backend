import os, django, psycopg2
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'purchases.settings')
django.setup()
from django.db import connection

print('ENGINE =', connection.settings_dict['ENGINE'])
print('DATABASE_URL =', os.getenv('DATABASE_URL'))

try:
    cur = connection.cursor()
    cur.execute('SELECT current_database(), current_user, version()')
    print('OK ->', cur.fetchone())
except Exception as e:
    print('ERROR TYPE =', type(e).__name__)
    print('ERROR STR  =', str(e))
    print('ARGS       =', getattr(e, 'args', None))
    print('CAUSE      =', repr(getattr(e, '__cause__', None)))

url = os.getenv("DATABASE_URL")
print("DATABASE_URL:", url)
try:
    conn = psycopg2.connect(url)
    with conn.cursor() as cur:
        cur.execute("SELECT 1;")
        print("DB OK:", cur.fetchone())
    conn.close()
except Exception as e:
    print("DB ERROR:", e)
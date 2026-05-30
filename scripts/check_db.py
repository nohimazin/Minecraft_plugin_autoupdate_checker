from pathlib import Path
import sqlite3
import sys

APP_DIR = Path.home() / ".minecraft_plugin_autoupdate_checker"
DB_PATH = APP_DIR / "plugin-manager.sqlite"


def check_master_db():
    print(f"Checking master DB: {DB_PATH}")
    if not DB_PATH.exists():
        print("  Master DB does not exist.")
        return 2
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print("  Tables:", tables)
        if 'servers' not in tables:
            print("  ERROR: 'servers' table missing")
            return 3
        if 'plugins' not in tables:
            print("  WARNING: master 'plugins' table missing (may be migrated)")
        servers = [r for r in cur.execute("SELECT id, name, db_path FROM servers").fetchall()]
        print(f"  {len(servers)} servers found")
        for s in servers:
            sid = s['id']
            dbp = s['db_path']
            print(f"    server {sid}: {s['name']} db_path={dbp}")
            if dbp:
                p = Path(dbp)
                if not p.exists():
                    print(f"      WARNING: server DB file missing: {p}")
                else:
                    try:
                        sc = sqlite3.connect(p)
                        st = [r[0] for r in sc.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                        print(f"      tables in server DB: {st}")
                        if 'plugins' not in st:
                            print("      ERROR: 'plugins' table missing in server DB")
                    except Exception as e:
                        print("      ERROR opening server DB:", e)
        return 0
    except Exception as e:
        print("ERROR reading master DB:", e)
        return 1


if __name__ == '__main__':
    sys.exit(check_master_db())

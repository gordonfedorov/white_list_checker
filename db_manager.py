import sqlite3

DB_NAME = "checker_results.db"

def apply_pragmas(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-64000")

def init_database(sources_data):
    with sqlite3.connect(DB_NAME) as conn:
        apply_pragmas(conn)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                local_file TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS results (
                domain TEXT PRIMARY KEY,
                http_code INTEGER,
                updated_at INTEGER,
                source_id INTEGER,
                FOREIGN KEY (source_id) REFERENCES sources (id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_results_source_updated 
            ON results (source_id, updated_at)
        """)
        for src in sources_data:
            cursor.execute("""
                INSERT OR IGNORE INTO sources (url, local_file) 
                VALUES (?, ?)
            """, (src["url"], src["file_name"]))
        conn.commit()

def sync_sources_mapping():
    with sqlite3.connect(DB_NAME) as conn:
        apply_pragmas(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT local_file, id FROM sources")
        # FIXED: Correct key-value pair mapping for dictionary lookup resolution
        return {row[0]: row[1] for row in cursor.fetchall()}

def load_processed_domains():
    with sqlite3.connect(DB_NAME) as conn:
        apply_pragmas(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT domain FROM results")
        return {row[0] for row in cursor.fetchall()}

def save_batch_to_db(batch_results, sources_map):
    with sqlite3.connect(DB_NAME) as conn:
        apply_pragmas(conn)
        cursor = conn.cursor()
        cursor.execute("BEGIN TRANSACTION;")
        for res in batch_results:
            domain, is_available, http_code, updated_at, source_file = res
            code_int = int(http_code) if is_available else -1
            source_id = sources_map.get(source_file)
            cursor.execute("""
                INSERT OR REPLACE INTO results (domain, http_code, updated_at, source_id) 
                VALUES (?, ?, ?, ?)
            """, (domain, code_int, updated_at, source_id))
        conn.commit()

def fetch_report_data(placeholders, sources_list):
    with sqlite3.connect(DB_NAME) as conn:
        apply_pragmas(conn)
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT r.domain, r.http_code, datetime(r.updated_at, 'unixepoch', 'localtime'), s.local_file 
            FROM results r
            INNER JOIN sources s ON r.source_id = s.id
            WHERE s.local_file IN ({placeholders}) AND r.http_code != -1
            ORDER BY r.domain ASC
        """, sources_list)
        return cursor.fetchall()

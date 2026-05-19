import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'tracker.db')

def get_conn():
    """建立安全連線，設定 timeout 避免 database is locked"""
    return sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_path TEXT UNIQUE,
                target_name TEXT,
                video_time TEXT,
                status TEXT DEFAULT 'Pending' 
            )
        ''')
        conn.commit()

def add_task(original_path, target_name, video_time):
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO jobs (original_path, target_name, video_time) 
                VALUES (?, ?, ?)
            ''', (original_path, target_name, video_time))
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False # 路徑已存在

def get_pending_task():
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE status = 'Pending' LIMIT 1")
        task = cursor.fetchone()
        return dict(task) if task else None

def update_task_status(task_id, new_status):
    with get_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, task_id))
        conn.commit()

def delete_tasks(task_ids):
    """刪除指定的任務 ID 清單"""
    if not task_ids:
        return
    with get_conn() as conn:
        cursor = conn.cursor()
        # 產生對應數量的問號，例如 task_ids=[1, 2, 3] 會變成 (?, ?, ?)
        placeholders = ','.join(['?'] * len(task_ids))
        cursor.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", tuple(task_ids))
        _reindex_job_ids(cursor)
        conn.commit()

def reset_tasks_to_pending(task_ids):
    """將指定的任務狀態改回 Pending (再試一次)"""
    if not task_ids:
        return
    with get_conn() as conn:
        cursor = conn.cursor()
        placeholders = ','.join(['?'] * len(task_ids))
        cursor.execute(f"UPDATE jobs SET status = 'Pending' WHERE id IN ({placeholders})", tuple(task_ids))
        conn.commit()


def _reindex_job_ids(cursor):
    """將 jobs.id 重排為從 1 開始的連續整數，並重置 AUTOINCREMENT 序列。"""
    cursor.execute("SELECT id FROM jobs ORDER BY id")
    current_ids = [row[0] for row in cursor.fetchall()]
    if not current_ids:
        cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'jobs'")
        return

    expected_ids = list(range(1, len(current_ids) + 1))
    if current_ids != expected_ids:
        offset = max(current_ids) + len(current_ids) + 1
        cursor.execute("UPDATE jobs SET id = id + ?", (offset,))
        for new_id, old_id in enumerate(current_ids, start=1):
            cursor.execute("UPDATE jobs SET id = ? WHERE id = ?", (new_id, old_id + offset))

    cursor.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'jobs'", (len(current_ids),))
    if cursor.rowcount == 0:
        cursor.execute("INSERT INTO sqlite_sequence(name, seq) VALUES('jobs', ?)", (len(current_ids),))

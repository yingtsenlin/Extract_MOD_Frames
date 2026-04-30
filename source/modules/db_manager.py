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
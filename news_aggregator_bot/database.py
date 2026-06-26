import sqlite3
from typing import List, Dict, Optional


class Database:
    def __init__(self, db_name: str = "favorites.db"):
        self.db_name = db_name
        self.init_db()
    
    def init_db(self):
        """Создаёт таблицу для избранного."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    title TEXT,
                    description TEXT,
                    link TEXT,
                    source TEXT,
                    category TEXT,
                    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
    
    def add_favorite(self, user_id: int, news: Dict) -> bool:
        """Добавляет новость в избранное."""
        try:
            with sqlite3.connect(self.db_name) as conn:
                conn.execute("""
                    INSERT INTO favorites 
                    (user_id, title, description, link, source, category)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    news["title"],
                    news["description"],
                    news["link"],
                    news["source"],
                    news.get("category", "общее")
                ))
            return True
        except Exception as e:
            print(f"Ошибка добавления: {e}")
            return False
    
    def get_favorites(self, user_id: int) -> List[Dict]:
        """Получает избранное пользователя."""
        with sqlite3.connect(self.db_name) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM favorites WHERE user_id = ? ORDER BY saved_at DESC",
                (user_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def remove_favorite(self, user_id: int, link: str) -> bool:
        """Удаляет новость из избранного."""
        with sqlite3.connect(self.db_name) as conn:
            conn.execute(
                "DELETE FROM favorites WHERE user_id = ? AND link = ?",
                (user_id, link)
            )
            return True
    
    def is_favorite(self, user_id: int, link: str) -> bool:
        """Проверяет, есть ли новость в избранном."""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM favorites WHERE user_id = ? AND link = ?",
                (user_id, link)
            )
            return cursor.fetchone() is not None

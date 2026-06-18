import sqlite3
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict

DB_PATH = "moderator_bot.db"

# ---------------------------- Инициализация базы ----------------------------
async def init_db():
    """Создаёт все необходимые таблицы, если их ещё нет."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_chat (
                user_id INTEGER,
                chat_id INTEGER,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                message_count INTEGER DEFAULT 0,
                warn_count INTEGER DEFAULT 0,
                muted_until TIMESTAMP,
                banned_until TIMESTAMP,
                PRIMARY KEY (user_id, chat_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(chat_id) REFERENCES chats(chat_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER,
                chat_id INTEGER,
                role TEXT CHECK(role IN ('owner', 'admin', 'senior_mod', 'moderator')) NOT NULL,
                PRIMARY KEY (user_id, chat_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(chat_id) REFERENCES chats(chat_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                chat_id INTEGER,
                admin_id INTEGER,
                action TEXT,
                target_id INTEGER,
                detail TEXT
            )
        """)
        await db.commit()

# --------------------- Вспомогательные функции ----------------------------
async def ensure_user(user_id: int, username: str = None, first_name: str = None):
    """Добавляет пользователя в таблицу users, если его там нет, и обновляет данные."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
            (user_id, username, first_name)
        )
        await db.commit()

async def ensure_chat(chat_id: int, title: str = None):
    """Добавляет чат в таблицу chats, если его там нет."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO chats (chat_id, title) VALUES (?, ?)",
            (chat_id, title)
        )
        await db.commit()

async def ensure_user_chat(user_id: int, chat_id: int):
    """Добавляет связку пользователь-чат, если её ещё нет (первое сообщение)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_chat (user_id, chat_id, first_seen) VALUES (?, ?, ?)",
            (user_id, chat_id, datetime.now())
        )
        await db.commit()

async def increment_message(user_id: int, chat_id: int):
    """Увеличивает счётчик сообщений пользователя в чате."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_chat SET message_count = message_count + 1 WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )
        await db.commit()

async def get_user_role(user_id: int, chat_id: int) -> Optional[str]:
    """Возвращает роль пользователя в чате (или None, если не админ)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role FROM admins WHERE user_id=? AND chat_id=?", (user_id, chat_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def get_role_priority(role: str) -> int:
    """Возвращает числовой приоритет роли (чем выше, тем больше прав)."""
    order = {'moderator': 1, 'senior_mod': 2, 'admin': 3, 'owner': 4}
    return order.get(role, 0)

async def is_higher_or_equal(actor_role: str, target_role: str) -> bool:
    """Проверяет, что actor_role >= target_role (владелец может всё)."""
    if actor_role == 'owner':
        return True
    return await get_role_priority(actor_role) >= await get_role_priority(target_role)

async def add_admin(user_id: int, chat_id: int, role: str):
    """Назначает пользователю роль в чате."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO admins (user_id, chat_id, role) VALUES (?, ?, ?)",
            (user_id, chat_id, role)
        )
        await db.commit()

async def remove_admin(user_id: int, chat_id: int):
    """Снимает пользователя с любой административной роли в чате."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        await db.commit()

async def get_admins_by_chat(chat_id: int) -> List[Tuple[int, str]]:
    """Возвращает список (user_id, role) всех админов чата."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, role FROM admins WHERE chat_id=?", (chat_id,)) as cursor:
            return await cursor.fetchall()

async def get_user_chats_with_role(user_id: int) -> List[Tuple[int, str, str]]:
    """Возвращает список (chat_id, role, title) чатов, где пользователь админ."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT a.chat_id, a.role, c.title FROM admins a JOIN chats c ON a.chat_id=c.chat_id WHERE a.user_id=?",
            (user_id,)
        ) as cursor:
            return await cursor.fetchall()

async def get_warns(user_id: int, chat_id: int) -> int:
    """Возвращает количество варнов пользователя в чате."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT warn_count FROM user_chat WHERE user_id=? AND chat_id=?", (user_id, chat_id)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def add_warn(user_id: int, chat_id: int) -> int:
    """Добавляет предупреждение, возвращает новое количество."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_chat SET warn_count = warn_count + 1 WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        await db.commit()
        return await get_warns(user_id, chat_id)

async def remove_warns(user_id: int, chat_id: int, count: int = 1):
    """Снимает указанное число предупреждений (не меньше 0)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_chat SET warn_count = MAX(0, warn_count - ?) WHERE user_id=? AND chat_id=?",
            (count, user_id, chat_id)
        )
        await db.commit()

async def clear_warns(user_id: int, chat_id: int):
    """Обнуляет варны пользователя в чате."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_chat SET warn_count = 0 WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        await db.commit()

async def set_mute(user_id: int, chat_id: int, minutes: int):
    """Сохраняет время окончания мута."""
    until = datetime.now() + timedelta(minutes=minutes)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_chat SET muted_until=? WHERE user_id=? AND chat_id=?", (until, user_id, chat_id))
        await db.commit()
    return until

async def clear_mute(user_id: int, chat_id: int):
    """Убирает информацию о муте."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_chat SET muted_until=NULL WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        await db.commit()

async def set_ban(user_id: int, chat_id: int):
    """Ставит отметку о бане навсегда."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_chat SET banned_until='9999-12-31' WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        await db.commit()

async def clear_ban(user_id: int, chat_id: int):
    """Снимает отметку о бане."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_chat SET banned_until=NULL WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        await db.commit()

async def get_user_status(user_id: int, chat_id: int) -> Dict:
    """Возвращает информацию о статусе пользователя в чате."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT first_seen, message_count, warn_count, muted_until, banned_until FROM user_chat WHERE user_id=? AND chat_id=?",
            (user_id, chat_id)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            now = datetime.now()
            muted_until = datetime.fromisoformat(row[3]) if row[3] else None
            banned_until = datetime.fromisoformat(row[4]) if row[4] else None
            status = "активен"
            if banned_until and banned_until > now:
                status = "забанен"
            elif muted_until and muted_until > now:
                status = "замучен"
            return {
                "first_seen": row[0],
                "message_count": row[1],
                "warn_count": row[2],
                "muted_until": muted_until,
                "banned_until": banned_until,
                "status": status
            }

async def get_top_messages(chat_id: int, days: int = None) -> List[Tuple[int, int]]:
    """Топ пользователей по числу сообщений. Если days задано — за последние N дней."""
    async with aiosqlite.connect(DB_PATH) as db:
        if days:
            since = datetime.now() - timedelta(days=days)
            async with db.execute(
                "SELECT user_id, message_count FROM user_chat WHERE chat_id=? AND first_seen >= ? ORDER BY message_count DESC LIMIT 10",
                (chat_id, since)
            ) as cursor:
                return await cursor.fetchall()
        else:
            async with db.execute(
                "SELECT user_id, message_count FROM user_chat WHERE chat_id=? ORDER BY message_count DESC LIMIT 10",
                (chat_id,)
            ) as cursor:
                return await cursor.fetchall()

async def log_action(chat_id: int, admin_id: int, action: str, target_id: int = None, detail: str = None):
    """Записывает действие в лог."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO logs (chat_id, admin_id, action, target_id, detail) VALUES (?, ?, ?, ?, ?)",
            (chat_id, admin_id, action, target_id, detail)
        )
        await db.commit()

async def get_logs(limit: int = 100) -> List[Tuple]:
    """Возвращает последние записи логов."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)) as cursor:
            return await cursor.fetchall()

async def migrate_chat(old_chat_id: int, new_chat_id: int):
    """Обновляет chat_id при миграции супергруппы."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE chats SET chat_id=? WHERE chat_id=?", (new_chat_id, old_chat_id))
        await db.execute("UPDATE user_chat SET chat_id=? WHERE chat_id=?", (new_chat_id, old_chat_id))
        await db.execute("UPDATE admins SET chat_id=? WHERE chat_id=?", (new_chat_id, old_chat_id))
        await db.execute("UPDATE logs SET chat_id=? WHERE chat_id=?", (new_chat_id, old_chat_id))
        await db.commit()
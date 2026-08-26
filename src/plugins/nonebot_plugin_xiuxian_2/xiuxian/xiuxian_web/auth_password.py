"""修仙 Web 玩家密码 fallback 认证辅助模块。

独立凭证表 + scrypt 哈希 + 内存级防爆破。
不引入新的 Session 体系，辅助 __init__.py 中的路由接线。
"""

import base64
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

DATABASE = Path.cwd() / "data" / "xiuxian" / "xiuxian.db"

TABLE = "xiuxian_web_auth_credentials"

SCHEMA = """
CREATE TABLE IF NOT EXISTS {table} (
    user_id INTEGER PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    algorithm TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_password_login_at TEXT
)
""".format(table=TABLE)

# scrypt 参数（与存储记录中的 algorithm/version 关联）
ALGORITHM = "scrypt"
VERSION = 1
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
DK_LEN = 32
SALT_BYTES = 16

MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128

# 防爆破（内存滑动窗口）
MAX_FAILURES = 5
WINDOW_SECONDS = 5 * 60
_LOCK = threading.Lock()
_FAILURES = {}

# 进程内固定 dummy 凭证，用于“无凭证/不支持版本”时执行相同工作量的 scrypt，
# 削弱账号枚举的时间侧信道。非敏感占位值，不涉及真实密码。
_DUMMY_SALT = secrets.token_bytes(SALT_BYTES)
_DUMMY_PASSWORD = b"dummy-xiuxian-web-auth-verify"
_DUMMY_HASH = hashlib.scrypt(
    _DUMMY_PASSWORD, salt=_DUMMY_SALT,
    n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=DK_LEN,
)


def _derive_scrypt_v1(password, salt):
    """统一 scrypt 派生，set / verify / dummy 共用同一参数。"""
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=DK_LEN,
    )


def _conn():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_valid_user_id(raw):
    """QQ 号严格规范化：strip 后必须纯十进制数字，长度约 5-20，
    数值必须落在 SQLite INTEGER(int64) 范围内。"""
    s = (raw or "").strip()
    if not s:
        return False
    if not (s.isascii() and s.isdigit()):
        return False
    if not 5 <= len(s) <= 20:
        return False
    return int(s) <= 9223372036854775807


def validate_password(pw):
    """密码规则校验，返回 None 表示通过，否则返回错误消息。"""
    if not isinstance(pw, str):
        return "密码格式不正确"
    length = len(pw)
    if length < MIN_PASSWORD_LEN:
        return f"密码长度至少 {MIN_PASSWORD_LEN} 位"
    if length > MAX_PASSWORD_LEN:
        return f"密码长度不能超过 {MAX_PASSWORD_LEN} 位"
    return None


def has_password(user_id):
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT user_id FROM {table} WHERE user_id=?".format(table=TABLE),
            (int(user_id),),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def verify_password(user_id, password):
    """校验密码。无凭证或 algorithm/version 不支持时执行 dummy scrypt 后返回 False，
    避免快速暴露账号是否存在；不日志密码。"""
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT password_hash, salt, algorithm, version FROM {table} WHERE user_id=?".format(table=TABLE),
            (int(user_id),),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        # dummy 路径：无凭证也执行一次相同工作量的 scrypt
        _derive_scrypt_v1(password, _DUMMY_SALT)
        return False
    try:
        row_version = int(row["version"]) if row["version"] is not None else None
    except (ValueError, TypeError):
        row_version = None
    if row["algorithm"] != ALGORITHM or row_version != VERSION:
        _derive_scrypt_v1(password, _DUMMY_SALT)
        return False
    try:
        expected = base64.b64decode(row["password_hash"])
        salt = base64.b64decode(row["salt"])
    except Exception:
        _derive_scrypt_v1(password, _DUMMY_SALT)
        return False
    try:
        dk = _derive_scrypt_v1(password, salt)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expected)


def set_password(user_id, password):
    """首次设置或覆盖更新密码（upsert）。"""
    salt = secrets.token_bytes(SALT_BYTES)
    dk = _derive_scrypt_v1(password, salt)
    now = _now()
    conn = _conn()
    try:
        existing = conn.execute(
            "SELECT created_at FROM {table} WHERE user_id=?".format(table=TABLE),
            (int(user_id),),
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT INTO {table}
                (user_id, password_hash, salt, algorithm, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                password_hash = excluded.password_hash,
                salt = excluded.salt,
                algorithm = excluded.algorithm,
                version = excluded.version,
                updated_at = excluded.updated_at
            """.format(table=TABLE),
            (
                int(user_id),
                base64.b64encode(dk).decode("ascii"),
                base64.b64encode(salt).decode("ascii"),
                ALGORITHM,
                VERSION,
                created_at,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mark_password_login(user_id):
    conn = _conn()
    try:
        conn.execute(
            "UPDATE {table} SET last_password_login_at=? WHERE user_id=?".format(table=TABLE),
            (_now(), int(user_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _fail_key(user_id, ip):
    return f"{int(user_id)}:{ip}"


def check_rate_limit(user_id, ip):
    """返回是否允许继续尝试。窗口内达到上限即锁定。"""
    key = _fail_key(user_id, ip)
    now = time.time()
    with _LOCK:
        times = [t for t in _FAILURES.get(key, []) if now - t < WINDOW_SECONDS]
        if times:
            _FAILURES[key] = times
        else:
            _FAILURES.pop(key, None)
        return len(times) < MAX_FAILURES


def record_failure(user_id, ip):
    key = _fail_key(user_id, ip)
    now = time.time()
    with _LOCK:
        times = [t for t in _FAILURES.get(key, []) if now - t < WINDOW_SECONDS]
        times.append(now)
        _FAILURES[key] = times


def clear_failures(user_id, ip):
    key = _fail_key(user_id, ip)
    with _LOCK:
        _FAILURES.pop(key, None)

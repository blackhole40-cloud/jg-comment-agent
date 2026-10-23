"""운영 규칙(허용 범위 · 영상당 1개 · 하루 상한)과 게시 기록(SQLite). 규칙은 여기서만 판단한다."""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "log.db"
KST = timezone(timedelta(hours=9))
_lock = threading.Lock()

# 진행 중이거나 성공한 기록만 '이미 댓글 단 영상'으로 본다. 실패는 다시 시도 가능.
ACTIVE = ("pending", "opening", "typing", "posted")


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            video_id TEXT NOT NULL,
            channel_id TEXT,
            channel TEXT,
            title TEXT,
            profile TEXT,
            comment TEXT,
            status TEXT NOT NULL,
            reason TEXT,
            shot TEXT
        )"""
    )
    return c


def now_kst() -> datetime:
    return datetime.now(KST)


def today_count() -> int:
    start = now_kst().strftime("%Y-%m-%d")
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM posts WHERE status='posted' AND substr(ts,1,10)=?", (start,)
        ).fetchone()[0]


def is_allowed(video_id: str, channel_id: str | None, cfg: dict | None = None) -> tuple[bool, str]:
    cfg = cfg or load_config()
    if video_id in (cfg.get("test_videos") or []):
        return True, "본인 테스트 영상"
    if channel_id in (cfg.get("channels") or {}):
        return True, cfg["channels"][channel_id]
    return False, "허용된 5개 채널(또는 본인 테스트 영상)의 영상이 아닙니다."


def check_can_post(video_id: str, channel_id: str | None) -> tuple[bool, str]:
    """게시 직전 최종 판정. (가능 여부, 사유)"""
    cfg = load_config()
    ok, why = is_allowed(video_id, channel_id, cfg)
    if not ok:
        return False, why
    with _conn() as c:
        row = c.execute(
            f"SELECT profile, status FROM posts WHERE video_id=? AND status IN ({','.join('?' * len(ACTIVE))}) LIMIT 1",
            (video_id, *ACTIVE),
        ).fetchone()
    if row:
        return False, f"이 영상에는 이미 댓글을 달았습니다 ({row['profile']}, {row['status']}). 영상당 1개만 허용됩니다."
    limit = int(cfg["limits"]["daily_max_comments"])
    if today_count() >= limit:
        return False, f"오늘 게시 상한({limit}개)에 도달했습니다."
    return True, "ok"


def create_post(video_id, channel_id, channel, title, profile, comment) -> int:
    """규칙 확인과 기록 생성을 한 번에 (동시 클릭으로 2개가 생기는 것 방지)."""
    with _lock:
        ok, why = check_can_post(video_id, channel_id)
        if not ok:
            raise PermissionError(why)
        with _conn() as c:
            cur = c.execute(
                "INSERT INTO posts (ts, video_id, channel_id, channel, title, profile, comment, status) "
                "VALUES (?,?,?,?,?,?,?, 'pending')",
                (now_kst().isoformat(timespec="seconds"), video_id, channel_id, channel, title, profile, comment),
            )
            return cur.lastrowid


def update_post(post_id: int, status: str, reason: str | None = None, shot: str | None = None) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE posts SET status=?, reason=COALESCE(?, reason), shot=COALESCE(?, shot) WHERE id=?",
            (status, reason, shot, post_id),
        )


def get_post(post_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    return dict(r) if r else None


def list_posts(limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM posts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def next_profile(available: list[str]) -> str | None:
    """영상마다 돌아가며 배정: 가장 최근에 쓴 프로필의 다음 프로필."""
    if not available:
        return None
    with _conn() as c:
        r = c.execute("SELECT profile FROM posts ORDER BY id DESC LIMIT 1").fetchone()
    if not r or r[0] not in available:
        return available[0]
    return available[(available.index(r[0]) + 1) % len(available)]

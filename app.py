"""운명원 댓글 에이전트 대시보드 (로컬 실행).
실행: python app.py  →  브라우저에서 http://127.0.0.1:8000
"""
import re
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import rules  # noqa: E402
from core.draft import make_draft, redact, validate  # noqa: E402
from core.fetch import _oembed_title, _video_meta, fetch_latest, find_rising, get_video_context  # noqa: E402
from core.profiles import PROFILES_DIR  # noqa: E402

app = FastAPI(title="운명원 댓글 에이전트")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

DRAFTS: dict[str, dict] = {}       # video_id -> 영상 정보 + 초안 (게시 시 채널 재확인용)
_post_lock = threading.Lock()       # 크롬 게시는 한 번에 하나만

_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([A-Za-z0-9_-]{11})")


def video_id_from(text: str) -> str | None:
    text = text.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    m = _ID_RE.search(text)
    return m.group(1) if m else None


def available_profiles(cfg) -> list[str]:
    return [p for p in cfg["profiles"] if (PROFILES_DIR / p).exists()]


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/config")
def api_config():
    cfg = rules.load_config()
    avail = available_profiles(cfg)
    return {
        "profiles": [{"id": k, "name": v, "ready": k in avail} for k, v in cfg["profiles"].items()],
        "next_profile": rules.next_profile(avail),
    }


@app.get("/api/videos")
def api_videos():
    cfg = rules.load_config()
    res = fetch_latest(5)
    tests = []
    for vid in cfg.get("test_videos") or []:
        title, published = None, ""
        try:  # 올린 날짜까지 표시 (요구사항: 썸네일·제목·채널·올린 날짜)
            meta = _video_meta(vid)
            if meta:
                title = meta["title"]
                published = datetime.fromtimestamp(meta["timestamp"], tz=timezone.utc).isoformat()
        except Exception:
            pass
        if not title:
            try:
                title = _oembed_title(vid)
            except Exception:
                title = "(제목을 불러오지 못함)"
        tests.append({
            "video_id": vid, "title": title, "channel": "내 테스트 영상", "channel_id": None,
            "published": published, "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "url": f"https://www.youtube.com/watch?v={vid}", "is_test": True,
        })
    return {"videos": tests + res["videos"], "errors": res["errors"]}


class DraftReq(BaseModel):
    video: str              # 영상 ID 또는 주소
    draft_only: bool = False  # 뜨기 직전 영상: 허용 채널이 아니어도 초안까지만 생성 (게시 불가)


@app.post("/api/draft")
def api_draft(req: DraftReq):
    vid = video_id_from(req.video)
    if not vid:
        raise HTTPException(400, "유튜브 영상 주소를 인식하지 못했습니다.")
    try:
        ctx = get_video_context(vid)
    except Exception as e:
        raise HTTPException(502, f"영상 정보를 가져오지 못했습니다: {redact(str(e).splitlines()[0])}")
    ok, why = rules.is_allowed(ctx["video_id"], ctx["channel_id"])
    if not ok and not req.draft_only:
        raise HTTPException(403, f"'{ctx['channel']}' 채널 영상입니다. {why}")
    try:
        d = make_draft(ctx)
    except Exception as e:
        raise HTTPException(502, f"초안 생성 실패: {redact(str(e).splitlines()[0])}")
    info = {
        "video_id": ctx["video_id"], "title": ctx["title"], "channel": ctx["channel"],
        "channel_id": ctx["channel_id"], "upload_date": ctx["upload_date"], "view_count": ctx["view_count"],
        "url": f"https://www.youtube.com/watch?v={ctx['video_id']}",
        "thumbnail": f"https://i.ytimg.com/vi/{ctx['video_id']}/hqdefault.jpg",
        "allowed_as": why,
    }
    if ok:  # 게시 허용 영상만 게시 대상으로 보관
        DRAFTS[ctx["video_id"]] = {**info, "draft": d}
    return {**info, "postable": ok, **{k: d[k] for k in ("worry", "comment", "chars", "ok", "errors")}}


@app.get("/api/rising")
def api_rising():
    try:
        return find_rising("연애")
    except Exception as e:
        raise HTTPException(502, f"검색 실패: {redact(str(e).splitlines()[0])}")


class PostReq(BaseModel):
    video_id: str
    profile: str | None = None  # 없으면 자동 배정


@app.post("/api/post")
def api_post(req: PostReq):
    cfg = rules.load_config()
    info = DRAFTS.get(req.video_id)
    if not info:
        raise HTTPException(400, "먼저 ②에서 영상을 선택해 초안을 만들어 주세요.")
    if not info["draft"].get("ok"):
        raise HTTPException(400, "검수를 통과하지 못한 초안이라 게시할 수 없습니다. 영상을 다시 선택해 새 초안을 만들어 주세요.")
    text = info["draft"]["comment"]  # AI 초안을 그대로 게시
    errs = validate(text)
    if errs:
        raise HTTPException(400, "댓글 규칙 위반으로 게시할 수 없습니다: " + "; ".join(errs))
    avail = available_profiles(cfg)
    profile = req.profile or rules.next_profile(avail)
    if profile not in avail:
        raise HTTPException(400, f"사용할 수 있는 크롬 프로필이 아닙니다: {profile}. scripts/setup_profile.py 로 먼저 로그인하세요.")
    if not _post_lock.acquire(blocking=False):
        raise HTTPException(409, "다른 댓글을 게시하는 중입니다. 끝난 뒤 다시 눌러 주세요.")
    try:
        post_id = rules.create_post(
            info["video_id"], info["channel_id"], info["channel"], info["title"], profile, text
        )
    except PermissionError as e:
        _post_lock.release()
        raise HTTPException(403, str(e))
    threading.Thread(target=_run_post, args=(post_id, profile, info["url"], text), daemon=True).start()
    return {"post_id": post_id, "profile": profile, "profile_name": cfg["profiles"][profile]}


def _run_post(post_id: int, profile: str, url: str, text: str) -> None:
    from core.poster import post_comment  # playwright는 게시할 때만 불러옴
    try:
        res = post_comment(PROFILES_DIR / profile, url, text,
                           on_status=lambda s: rules.update_post(post_id, s) if s != "failed" else None)
        if res.get("ok"):
            rules.update_post(post_id, "posted")
        else:
            shot = Path(res["shot"]).name if res.get("shot") else None
            rules.update_post(post_id, "failed", res.get("reason"), shot)
    except Exception as e:
        rules.update_post(post_id, "failed", f"unexpected: {e}")
    finally:
        _post_lock.release()


@app.get("/api/post/{post_id}")
def api_post_status(post_id: int):
    p = rules.get_post(post_id)
    if not p:
        raise HTTPException(404, "기록이 없습니다.")
    return p


@app.get("/api/log")
def api_log():
    cfg = rules.load_config()
    rows = rules.list_posts()
    for r in rows:
        r["profile_name"] = cfg["profiles"].get(r["profile"], r["profile"])
    return {"rows": rows}


@app.get("/shots/{name}")
def shot(name: str):
    p = (ROOT / "data" / "shots" / name).resolve()
    if p.parent != (ROOT / "data" / "shots").resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


if __name__ == "__main__":
    import uvicorn
    from core.window import open_dashboard

    def _open():  # 전용 크롬 앱 창으로 화면 왼쪽 절반에 열기 (안 되면 기본 브라우저)
        url = "http://127.0.0.1:8000"
        if not open_dashboard(url, PROFILES_DIR / "dashboard", "운명원 댓글 에이전트"):
            webbrowser.open(url)

    threading.Timer(1.5, _open).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

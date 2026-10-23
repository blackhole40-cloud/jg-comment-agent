"""영상 목록(yt-dlp 채널 탭, 실패 시 RSS)과 영상 자료(제목·설명·자막·인기 댓글) 수집. API 키 불필요."""
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

CHANNELS = {
    "UCxlc0Ky0aWoD8uI09ad44Tg": "외롭여",
    "UC-ee_ziASM251TMXe3P3VZA": "리즈시절 LizTV",
    "UC09L3JxGVcn7SKLa-pjTEmw": "러브커넥트 유지연",
    "UCVdtDW-HF4KluixGaBAcI4w": "연애데이터 노노",
    "UCkGl2jieOVhGiHPdXF77Yyw": "심리조각",
}

_UA = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"}
_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


def _get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------- ① 영상 목록 ----------
def fetch_channel(channel_id: str, limit: int = 5) -> list[dict]:
    """yt-dlp로 채널 '동영상' 탭을 가볍게(flat) 읽음. 실패 시 RSS로 재시도."""
    try:
        return _fetch_channel_ytdlp(channel_id, limit)
    except Exception as first:
        try:
            return _fetch_channel_rss(channel_id, limit)
        except Exception:
            raise first


def _fetch_channel_ytdlp(channel_id: str, limit: int) -> list[dict]:
    import yt_dlp
    from datetime import datetime, timezone

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
        # flat 모드에서도 '3일 전' 표기로 대략적 업로드 날짜를 채움
        # 날짜 근사치는 영어 표기("3 days ago")에서만 계산되므로 언어 설정을 넣지 않음.
        # 한국어 원제목은 _fix_titles(oEmbed)에서 따로 받음.
        "extractor_args": {"youtubetab": {"approximate_date": [""]}},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/channel/{channel_id}/videos", download=False)
    out = []
    for e in (info.get("entries") or [])[:limit]:
        vid = e.get("id")
        if not vid or e.get("availability") in ("subscriber_only", "premium_only", "needs_auth"):
            continue  # 회원 전용 등 댓글을 달 수 없는 영상 제외
        ts = e.get("timestamp") or e.get("release_timestamp")
        if ts:
            published = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        elif e.get("upload_date"):
            d = e["upload_date"]
            published = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        else:
            published = ""
        out.append({
            "video_id": vid,
            "title": e.get("title"),
            "channel_id": channel_id,
            "channel": CHANNELS.get(channel_id, info.get("channel")),
            "published": published,
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    if not out:
        raise RuntimeError("영상 목록이 비어 있습니다.")
    _fix_titles(out)
    return out


def _oembed_title(video_id: str):
    url = ("https://www.youtube.com/oembed?format=json&url="
           f"https://www.youtube.com/watch?v={video_id}")
    return json.loads(_get(url, timeout=10).decode("utf-8")).get("title")


def _fix_titles(videos: list[dict]) -> None:
    """채널 탭 목록은 자동 번역(영어) 제목이 올 수 있어, oEmbed로 원제목을 다시 받음.
    실패한 항목은 기존 제목 유지."""
    with ThreadPoolExecutor(max_workers=8) as ex:
        titles = list(ex.map(lambda v: _safe(_oembed_title, v["video_id"]), videos))
    for v, t in zip(videos, titles):
        if t:
            v["title"] = t


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


def _fetch_channel_rss(channel_id: str, limit: int) -> list[dict]:
    xml = _get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    root = ET.fromstring(xml)
    out = []
    for e in root.findall("a:entry", _NS)[:limit]:
        vid = e.findtext("yt:videoId", namespaces=_NS)
        thumb = e.find("media:group/media:thumbnail", _NS)
        out.append({
            "video_id": vid,
            "title": e.findtext("a:title", namespaces=_NS),
            "channel_id": channel_id,
            "channel": CHANNELS.get(channel_id, e.findtext("a:author/a:name", namespaces=_NS)),
            "published": e.findtext("a:published", namespaces=_NS),
            "thumbnail": thumb.get("url") if thumb is not None else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    return out


def fetch_latest(limit_per_channel: int = 5) -> dict:
    """5개 채널 최신 영상. 채널별 실패는 errors에 담고 나머지는 계속."""
    videos, errors = [], {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {cid: ex.submit(fetch_channel, cid, limit_per_channel) for cid in CHANNELS}
        for cid, f in futs.items():
            try:
                videos.extend(f.result())
            except Exception as e:  # 네트워크 등
                errors[CHANNELS[cid]] = str(e)
    videos.sort(key=lambda v: v["published"] or "", reverse=True)
    return {"videos": videos, "errors": errors}


# ---------- ② 영상 자료 ----------
def _pick_caption(info: dict):
    """한국어 자막 우선순위: 수동 자막 → 원본 자동자막(ko-orig) → 자동자막(ko)."""
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for src, table, keys in (
        ("manual", subs, [k for k in subs if k.startswith("ko")]),
        ("auto", auto, ["ko-orig", "ko"]),
    ):
        for k in keys:
            tracks = table.get(k) or []
            by_ext = {t.get("ext"): t for t in tracks}
            for ext in ("json3", "vtt"):
                if ext in by_ext:
                    return src, ext, by_ext[ext]["url"]
    return None


def _caption_text(ext: str, raw: bytes) -> str:
    if ext == "json3":
        data = json.loads(raw.decode("utf-8"))
        parts = []
        for ev in data.get("events", []):
            for seg in ev.get("segs") or []:
                parts.append(seg.get("utf8", ""))
        text = "".join(parts)
    else:
        lines = []
        for line in raw.decode("utf-8", "ignore").splitlines():
            if not line.strip() or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:")):
                continue
            line = re.sub(r"<[^>]+>", "", line).strip()
            if not lines or lines[-1] != line:
                lines.append(line)
        text = " ".join(lines)
    return re.sub(r"\s+", " ", text).strip()


def _friendly_error(e: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR:", "").strip()
    if any(k in msg for k in ("회원 전용", "members-only", "Join this channel")):
        return "채널 회원 전용 영상이라 내용을 읽거나 댓글을 달 수 없습니다."
    if any(k in msg for k in ("Private video", "비공개")):
        return "비공개 영상입니다."
    if any(k in msg for k in ("Video unavailable", "동영상을 재생할 수 없음")):
        return "볼 수 없는 영상입니다."
    return msg.splitlines()[0] if msg else "영상 정보를 가져오지 못했습니다."


def get_video_context(video: str, max_comments: int = 20, max_transcript_chars: int = 6000) -> dict:
    """영상 ID 또는 URL → 제목·설명·채널·조회수·자막·인기 댓글.
    transcript_source: 'manual' | 'auto' | 'none'(자막 없음 → 제목·설명으로 대체)"""
    import yt_dlp

    url = video if video.startswith("http") else f"https://www.youtube.com/watch?v={video}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "getcomments": True,
        "http_headers": {"Accept-Language": "ko-KR,ko;q=0.9"},
        "extractor_args": {"youtube": {
            "lang": ["ko"],
            "comment_sort": ["top"],
            "max_comments": [str(max_comments), str(max_comments), "0", "0"],
        }},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise RuntimeError(_friendly_error(e)) from None

    transcript, source = "", "none"
    cap = _pick_caption(info)
    if cap:
        try:
            transcript = _caption_text(cap[1], _get(cap[2]))
            source = cap[0] if transcript else "none"
        except Exception:
            transcript, source = "", "none"

    comments = sorted(
        (c for c in (info.get("comments") or []) if c.get("parent") in (None, "root")),
        key=lambda c: c.get("like_count") or 0, reverse=True,
    )[:max_comments]

    return {
        "video_id": info.get("id"),
        "title": info.get("title"),
        "description": (info.get("description") or "")[:2000],
        "channel_id": info.get("channel_id"),
        "channel": info.get("channel") or info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "view_count": info.get("view_count"),
        "transcript": transcript[:max_transcript_chars],
        "transcript_source": source,
        "top_comments": [{"text": c.get("text", ""), "likes": c.get("like_count") or 0} for c in comments],
    }


# ---------- 가점: '연애' 키워드로 뜨기 직전 영상 찾기 ----------
def _video_meta(video_id: str) -> dict | None:
    """조회수와 정확한 업로드 시각(timestamp)만 가볍게 조회 (댓글·자막 제외)."""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    ts = info.get("timestamp") or info.get("release_timestamp")
    if not ts or info.get("live_status") in ("is_live", "is_upcoming"):
        return None
    return {
        "video_id": video_id,
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id"),
        "view_count": info.get("view_count") or 0,
        "timestamp": ts,
    }


def find_rising(keyword: str = "연애", min_views: int = 1000, max_views: int = 5000,
                min_per_hour: float = 150, search_n: int = 50, max_check: int = 20) -> dict:
    """최근 24시간 업로드 검색 → 조회수 1,000~5,000 후보 → 업로드 후 경과 시간으로 시간당 조회수 계산 → 150 이상만.
    반환: {"videos": [...시간당 조회수 높은 순], "checked": 확인한 후보 수}"""
    import time
    import yt_dlp

    from urllib.parse import quote

    # 유튜브 검색 결과 페이지 + '업로드 날짜: 오늘' 필터(sp=EgIIAg==).
    # 조회수 1,000~5,000에 시간당 150회 이상이면 업로드 후 약 33시간 이내라 '오늘' 범위로 충분.
    url = f"https://www.youtube.com/results?search_query={quote(keyword)}&sp=EgIIAg%3D%3D"
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "playlistend": search_n}
    with yt_dlp.YoutubeDL(opts) as ydl:
        res = ydl.extract_info(url, download=False)
    entries = [e for e in (res.get("entries") or []) if e.get("id") and len(e["id"]) == 11]
    # 검색 목록에 조회수가 있으면 1차로 거름 (없으면 상세 조회에서 판단)
    cands = [e["id"] for e in entries
             if e.get("view_count") is None or min_views <= e["view_count"] <= max_views][:max_check]

    with ThreadPoolExecutor(max_workers=5) as ex:
        metas = [m for m in ex.map(lambda v: _safe(_video_meta, v), cands) if m]

    now = time.time()
    out = []
    for m in metas:
        hours = max((now - m["timestamp"]) / 3600, 0.25)  # 업로드 15분 이내는 15분으로 계산
        per_hour = m["view_count"] / hours
        if min_views <= m["view_count"] <= max_views and per_hour >= min_per_hour:
            out.append({
                **m,
                "hours": round(hours, 1),
                "per_hour": round(per_hour),
                "thumbnail": f"https://i.ytimg.com/vi/{m['video_id']}/hqdefault.jpg",
                "url": f"https://www.youtube.com/watch?v={m['video_id']}",
            })
    out.sort(key=lambda v: v["per_hour"], reverse=True)
    return {"videos": out, "checked": len(metas)}

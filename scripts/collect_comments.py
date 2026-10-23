"""연애 영상 실제 댓글 수집기 (말투 참고용). 멈출 때까지 천천히 계속 수집한다.

사용: python scripts/collect_comments.py        (멈추려면 Ctrl + C)
저장: data/style_corpus.jsonl   한 줄에 댓글 하나 {video_id, channel, title, source, text, likes, ts}
     data/style_corpus_done.json 이미 수집한 영상 ID (다시 켜도 이어서 수집)

- 작성자 이름은 저장하지 않는다.
- 유튜브에 부담을 주지 않도록 영상 하나마다 20~40초 쉰다.
- AI 호출 없음 (비용 0원).
"""
import hashlib
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from core.fetch import CHANNELS  # noqa: E402

DATA = ROOT / "data"
CORPUS = DATA / "style_corpus.jsonl"
DONE = DATA / "style_corpus_done.json"

SEARCH_QUERIES = ["연애", "연애 심리", "남자 심리", "여자 심리", "재회", "썸", "연애 상담", "이별", "짝사랑", "소개팅"]
PER_CHANNEL = 30          # 채널마다 최근 영상 수
PER_QUERY = 20            # 검색어마다 영상 수
COMMENTS_PER_VIDEO = 40   # 영상마다 인기 댓글 수
REST = (20, 40)           # 영상 사이 쉬는 시간(초)
ROUND_REST = 30 * 60      # 한 바퀴 다 돌면 30분 쉬고 새 영상 확인

_BAD = re.compile(r"(https?://|www\.|@\w|구독|광고|협찬|이벤트|링크)", re.I)


def clean(text: str) -> str | None:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not 10 <= len(t) <= 150 or _BAD.search(t) or not re.search(r"[가-힣]", t):
        return None
    return t


def list_videos() -> list[dict]:
    import yt_dlp
    out = []
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}
    for cid, name in CHANNELS.items():
        try:
            with yt_dlp.YoutubeDL({**opts, "playlistend": PER_CHANNEL}) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/channel/{cid}/videos", download=False)
            out += [{"video_id": e["id"], "channel": name, "source": "channel"}
                    for e in (info.get("entries") or []) if e.get("id")]
        except Exception as e:
            print(f"  채널 목록 실패 {name}: {str(e).splitlines()[0][:80]}")
    for q in SEARCH_QUERIES:
        try:
            url = f"https://www.youtube.com/results?search_query={quote(q)}"
            with yt_dlp.YoutubeDL({**opts, "playlistend": PER_QUERY}) as ydl:
                info = ydl.extract_info(url, download=False)
            out += [{"video_id": e["id"], "channel": e.get("channel") or e.get("uploader") or "", "source": f"search:{q}"}
                    for e in (info.get("entries") or []) if e.get("id") and len(e["id"]) == 11]
        except Exception as e:
            print(f"  검색 실패 '{q}': {str(e).splitlines()[0][:80]}")
        time.sleep(random.uniform(3, 6))
    seen, uniq = set(), []
    for v in out:
        if v["video_id"] not in seen:
            seen.add(v["video_id"])
            uniq.append(v)
    random.shuffle(uniq)
    return uniq


def fetch_comments(video_id: str) -> tuple[str, str, list[dict]]:
    import yt_dlp
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True, "getcomments": True,
        "http_headers": {"Accept-Language": "ko-KR,ko;q=0.9"},
        "extractor_args": {"youtube": {
            "lang": ["ko"], "comment_sort": ["top"],
            "max_comments": [str(COMMENTS_PER_VIDEO), str(COMMENTS_PER_VIDEO), "0", "0"],
        }},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    comments = [c for c in (info.get("comments") or []) if c.get("parent") in (None, "root")]
    return info.get("title") or "", info.get("channel") or "", comments


def load_done() -> set[str]:
    try:
        return set(json.loads(DONE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    done = load_done()
    seen_hash = set()
    if CORPUS.exists():
        for line in CORPUS.read_text(encoding="utf-8").splitlines():
            try:
                seen_hash.add(hashlib.md5(json.loads(line)["text"].encode()).hexdigest())
            except (ValueError, KeyError):
                continue
    total = len(seen_hash)
    print(f"수집 시작 · 지금까지 댓글 {total}개 · 영상 {len(done)}개 (멈추려면 Ctrl + C)")
    try:
        while True:
            videos = [v for v in list_videos() if v["video_id"] not in done]
            print(f"\n새로 볼 영상 {len(videos)}개")
            for n, v in enumerate(videos, 1):
                try:
                    title, channel, comments = fetch_comments(v["video_id"])
                except Exception as e:
                    print(f"  [{n}/{len(videos)}] 건너뜀: {str(e).splitlines()[0][:60]}")
                    done.add(v["video_id"])
                    continue
                added = 0
                with CORPUS.open("a", encoding="utf-8") as f:
                    for c in comments:
                        t = clean(c.get("text", ""))
                        if not t:
                            continue
                        h = hashlib.md5(t.encode()).hexdigest()
                        if h in seen_hash:
                            continue
                        seen_hash.add(h)
                        f.write(json.dumps({
                            "video_id": v["video_id"], "channel": channel or v["channel"], "title": title,
                            "source": v["source"], "text": t, "likes": c.get("like_count") or 0,
                            "ts": datetime.now().isoformat(timespec="seconds"),
                        }, ensure_ascii=False) + "\n")
                        added += 1
                done.add(v["video_id"])
                DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
                total += added
                print(f"  [{n}/{len(videos)}] +{added} (누적 {total}) {title[:30]}")
                time.sleep(random.uniform(*REST))
            print(f"\n한 바퀴 완료 · 누적 {total}개 · 30분 뒤 새 영상 확인")
            time.sleep(ROUND_REST)
    except KeyboardInterrupt:
        DONE.write_text(json.dumps(sorted(done)), encoding="utf-8")
        print(f"\n수집 중단 · 누적 댓글 {total}개 저장됨 ({CORPUS})")


if __name__ == "__main__":
    main()

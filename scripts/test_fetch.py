"""영상 수집 테스트.
사용: python scripts/test_fetch.py            → 5개 채널 최신 영상 목록
      python scripts/test_fetch.py <영상주소>  → 해당 영상 자료(자막·인기 댓글) 요약
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from core.fetch import fetch_latest, get_video_context  # noqa: E402


def main():
    if len(sys.argv) < 2:
        res = fetch_latest(3)
        for v in res["videos"]:
            print(f"{v['published'][:10]} | {v['channel']:<12} | {v['title'][:40]} | {v['url']}")
        print(f"\n총 {len(res['videos'])}개, 실패 채널: {res['errors'] or '없음'}")
        return

    c = get_video_context(sys.argv[1])
    print("제목:", c["title"])
    print("채널:", c["channel"], c["channel_id"])
    print("업로드:", c["upload_date"], "| 조회수:", c["view_count"])
    print("자막 출처:", c["transcript_source"], "| 자막 길이:", len(c["transcript"]))
    print("자막 앞부분:", c["transcript"][:200] or "(없음)")
    print(f"인기 댓글 {len(c['top_comments'])}개:")
    for x in c["top_comments"][:5]:
        print(f"  [{x['likes']}] {x['text'][:60]}")


if __name__ == "__main__":
    main()

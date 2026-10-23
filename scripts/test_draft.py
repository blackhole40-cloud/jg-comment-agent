"""초안 생성 테스트 (영상 하나씩 분석 → 초안 → 심사 결과 출력).
사용: python scripts/test_draft.py <영상주소> [<영상주소> ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from core.draft import make_draft  # noqa: E402
from core.fetch import get_video_context  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("사용: python scripts/test_draft.py <영상주소> [...]")
        return
    for url in sys.argv[1:]:
        ctx = get_video_context(url)
        d = make_draft(ctx)
        print("=" * 60)
        print("영상:", d["title"], f"(자막: {d['transcript_source']})")
        print("고민 한 줄:", d["worry"])
        print("짚을 장면:", " / ".join(d["scenes"]))
        print(f"댓글 ({d['chars']}자, 시도 {d['attempts']}회):", d["comment"])
        print("운명원에 물어볼 것:", d.get("ask", ""))
        print("심사:", d.get("score"), "점")
        print("검증:", "통과" if d["ok"] else "실패 - " + "; ".join(d["errors"]))
        if d.get("judge_reason"):
            print("선택 이유:", d["judge_reason"])


if __name__ == "__main__":
    main()

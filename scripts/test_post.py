"""post_comment 수동 테스트.

사용: python scripts/test_post.py youtube1 "https://www.youtube.com/watch?v=XXXX" "댓글 내용"
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.poster import post_comment  # noqa: E402
from core.profiles import display_name, resolve_profile  # noqa: E402


def main() -> int:
    if len(sys.argv) != 4:
        print('사용법: python scripts/test_post.py <profile> <video_url> "<text>"')
        return 2
    profile, url, text = sys.argv[1:]
    try:
        profile_dir = resolve_profile(profile)
    except ValueError as e:
        print(f"오류: {e}")
        return 2

    label = display_name(profile_dir.name)

    def on_status(status: str) -> None:
        print(f"{datetime.now():%H:%M:%S} [{label}] {status}", flush=True)

    result = post_comment(profile_dir, url, text, on_status)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

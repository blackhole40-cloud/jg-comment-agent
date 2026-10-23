"""댓글 품질 일괄 검증: 5개 채널 최신 영상(채널당 N개)마다 초안을 만들어 한 파일로 저장.
사용: python scripts/batch_drafts.py [채널당 개수=5]
기준 예시가 나온 영상은 베낄 수 있어 건너뛴다.
결과: data/batch_YYYYmmdd_HHMM.txt (영상 · 고민 한 줄 · 댓글 · 검증 결과)
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from core.draft import EXAMPLE_VIDEO_IDS, make_draft, redact, review_batch  # noqa: E402
from core.fetch import fetch_latest, get_video_context  # noqa: E402


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    videos = [v for v in fetch_latest(n)["videos"] if v["video_id"] not in EXAMPLE_VIDEO_IDS]
    print(f"영상 {len(videos)}개 초안 생성 시작 (몇 분 걸립니다)")
    # 영상 자료 수집은 병렬, 초안은 순서대로 (이전 댓글과 겹치지 않게 비교하기 위해)
    with ThreadPoolExecutor(max_workers=4) as ex:
        ctxs = list(ex.map(lambda v: (v, _safe_ctx(v)), videos))

    out = ROOT / "data" / f"batch_{datetime.now():%Y%m%d_%H%M}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    passed = 0
    finals = []  # (번호, 댓글) 묶음 검증용
    with out.open("w", encoding="utf-8") as f:
        for i, (v, ctx) in enumerate(ctxs, 1):
            f.write(f"[{i}] {v['channel']} | {v['title']}\n{v['url']}\n")
            if isinstance(ctx, str):
                f.write(f"  영상 정보 실패: {ctx}\n\n")
                print(f"{i}/{len(ctxs)} 실패")
                continue
            try:
                d = make_draft(ctx)
            except Exception as e:
                f.write(f"  초안 실패: {redact(str(e).splitlines()[0])}\n\n")
                print(f"{i}/{len(ctxs)} 실패")
                continue
            passed += d["ok"]
            if d["comment"]:
                finals.append((i, d["comment"]))
            f.write(f"  자막: {d['transcript_source']}\n  영상 결론: {d.get('message', '')}\n  고민: {d['worry']}\n  상황: {d.get('status', '')}\n  바람: {d.get('wish', '')}\n  물어볼 것: {d.get('ask', '')}\n")
            f.write(f"  댓글({d['chars']}자): {d['comment']}\n")
            f.write(f"  말투: {d.get('style', '')}\n  심사: {d.get('score')}점 · {d.get('judge_reason', '')}\n")
            f.write(f"  검증: {'통과' if d['ok'] else '실패 - ' + '; '.join(d['errors'])}\n")
            f.write("  내 점수(0~10)와 이유: \n\n")
            print(f"{i}/{len(ctxs)} {'통과' if d['ok'] else '검증 실패'}")
        # 묶음 검증: 댓글들 사이의 반복 (개별 판정과 분리)
        f.write("=" * 40 + "\n[묶음 검증] 댓글 사이 반복\n")
        try:
            rb = review_batch([c for _, c in finals])
            nums = [n for n, _ in finals]
            for it in rb.get("issues") or []:
                k = it.get("id")
                if isinstance(k, int) and 1 <= k <= len(nums):
                    sim = [nums[x - 1] for x in it.get("similar_to") or [] if isinstance(x, int) and 1 <= x <= len(nums)]
                    f.write(f"  [{nums[k - 1]}] ~ {sim}: {it.get('detail', '')}\n")
            f.write(f"  요약: {rb.get('summary', '')}\n")
        except Exception as e:
            f.write(f"  묶음 검증 실패: {redact(str(e).splitlines()[0])}\n")
    print(f"\n검증 통과 {passed}/{len(ctxs)} · 결과 파일: {out}")


def _safe_ctx(v):
    try:
        return get_video_context(v["video_id"])
    except Exception as e:
        return str(e).splitlines()[0]


if __name__ == "__main__":
    main()

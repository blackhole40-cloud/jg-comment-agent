"""영상 자료 → (1) 영상 분석 → (2) 말투 카드가 다른 후보 5개 작성 → (3) 코드 규칙 검사 → (4) 10점 척도 심사.
심사는 사용자가 직접 점수를 매긴 댓글을 기준점으로 삼고, 8점 이상만 통과시킨다.
"""
import difflib
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DRAFT_LOG = DATA / "drafts.jsonl"
CORPUS = DATA / "style_corpus.jsonl"   # scripts/collect_comments.py 가 모은 실제 댓글

PROMPT_VERSION = "v26"   # 이 버전으로 만든 댓글만 '이전 댓글'로 참고
BRAND = "운명원"
MIN_CHARS, MAX_CHARS = 40, 120
MAX_ATTEMPTS = 3
RECENT_N = 20
PASS_SCORE = 8

# 운명원을 직접 이용해 본 것처럼 꾸며낸 후기 표현 (운명원이 들어간 문장에서만 검사)
_FAKE_REVIEW = re.compile(
    r"(봤는데|봤더니|봤어|봤음|봤다|받았|받아봤|다녀왔|다녀옴|해봤|보고\s?왔|가봤|맞더라|맞았|맞췄|후기|상담\s?받)"
)
_PROMO = re.compile(r"(무조건|용하|용한|정확하게|꼭\s?가\s?봐|안\s?보면\s?손해|강추|짱이)")
_LINK = re.compile(r"(https?://|www\.|\.com|\.kr|\.net|youtu\.?be|bit\.ly|링크)", re.I)
_REVIEW_TONE = re.compile(r"(장면|영상에서|영상 보고|영상 듣고|영상 보니)")
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|(?<=ㅠㅠ)\s+|(?<=ㅋㅋ)\s+|(?<=ㅎㅎ)\s+")
_FIXED_BRAND_PHRASE = "운명원에서 사주 보면"
# 운명원 문장(+바로 앞 문장)에 '무엇을 보는지'가 있어야 함 (사용자 지적: '운명원에 봐볼까'로 끝나면 흥미가 안 생김)
_LURE_WHAT = re.compile(r"(마음이|속마음|진심|잘\s?될|잘\s?되|잘될|궁합|인연|짝|언제|타이밍|시기|만날|만나|재회|다시\s?만|행복|결혼|어떤\s?사람|어떤\s?준비|뭘\s?해야|준비|맞는\s?사람|좋은\s?사람|좋은\s?남자|좋은\s?여자|사귈\s?수|사귈지|연애운)")
# 사용자가 '옛날 말투/억지 신조어'로 지적한 표현
_OUTDATED = re.compile(r"(공감당|좋당|싶당|했당|해야징|봐야징|물어봐야징|준비해야징|레전드|개궁금|찐따|사귈각)")
_AS_PLACE = re.compile(r"(가서|가보|가 보|가봐|가야|갈래|가볼)")   # 운명원은 장소가 아님 (사용자 지적)

# ---------- 사용자가 직접 점수를 매긴 기준 댓글 ----------
# 8점 이상: 생성 예시이자 심사 기준점. (사용자 작성 또는 사용자 수정 문장으로 만든 것)
GOOD_EXAMPLES = [
    # 사용자가 직접 쓴 댓글 (8점 이상)
    "100일인데 '뭐 먹을까' 한마디에 기분 확 상했던 거 완전 내 경험이네. 저렇게 무심한 사람은 만나고 싶지 않은데. 친구가 운명원에서 보면 저런 거 잘 본다던데 나도 한번 봐보고 싶다",
    "힘들다고 보낸 톡에 한 번 더 뭐가 제일 힘들었냐고 물어봐 준 거 진짜 다 들어주는 사람 같았어. 내 얘기 같아서 마음이 아프네. 운명원에서 보면 이런 사람 만날 수 있다던데 나도 한번 좋은 사람 만나보고 싶네.",
    # 사용자가 10점으로 고쳐 쓴 댓글
    '며칠 뒤에 "발표 잘됐어요?" 라고 물어보면서 말문이라도 터보고 싶다. 그래도 너무 부끄러운데, 운명원에서 이 사람과 내가 잘 될지 한 번 봐볼까? 좋은 결과면 더 자신있게 말할 수 있을 거 같아!',
    "알파남.. 나도 그런 남자와 연애 해보고 싶다ㅠㅠ 운명원에서 내가 만나고 싶은 사람을 만나려면 어떤 준비를 해야하는지 물어봐야지",
    "내 전남친도 헤어지고 그 사람이랑 행복해보이던데... 그 사람이 날 다시 떠올리고 돌아온다 해도 그런 사람은 안만나고 싶은걸. 운명원에서 사주 봐서 더 좋은 남자 만나고 싶다ㅜㅜ",
    "라면 먹고 갈래? 라고 먼저 연락 오면 진짜 미칠텐데 ㅋㅋㅋㅋ 운명원에서 그런 타이밍 잘 알려준다는데 한번 해봐야지~",
    "잠자리 직후 행동이 진심을 보여준다니 속궁합이 안 맞으면 어쩌나 불안한걸. 썸남과 잘될지 운명원에 물어봐야겠네",
    # 사용자가 8점을 준 댓글
    "원래 그런 사람이라는 말로 자꾸 넘어가 주는 게 더 불안하더라. 나도 나한테 마음 써주는 사람 만나고 싶어. 운명원에서 보면 이런 사람이 언제쯤 올지 알 수 있다는데 행복한 연애 해보고 싶다.",
]
# 위 예시가 나온 영상 (베낄 수 있으므로 품질 평가에서 제외)
EXAMPLE_VIDEO_IDS = {
    "k_0c0m0Hk5k", "MoyX-1lkriw", "c-QzU4kuu90", "FE0YQTSqFuo",
    "c5vYhdNbkdk", "A7enhG70jeU", "hpEnIwoH_sw", "FBGY7JIM-84", "17Q1_JwDsq0", "_KG56fTIBFM", "uNiw0MsASGo",
}
# 8점 미만: 심사 기준점 (점수와 사용자가 말한 이유)
SCORED_ANCHORS = [
    {"score": 0, "comment": "한 줄 톡에 또 울컥하네 나 진짜 ㅠㅠ 말보다 꾸준한 행동과 책임 약속 보여주면 좋겠더라.. 운명원에 물어봐야겠다",
     "reason": "영상 결론은 '신중하게 판단하자'인데 댓글은 상대가 보여주길 바람. 운명원에 뭘 물어보는지도 없음"},
    {"score": 4, "comment": "현타.. 작은건 웃고 넘기고 큰건 지켜야 레전드임 ㅋㅋ 내 썸녀가 먼저 톡하면 사귈각인데 운명원 궁금함",
     "reason": "'운명원 궁금함'은 무슨 말인지 모름. 사주를 보고 싶어지지 않음"},
    {"score": 6, "comment": "말끝 흐리는 거 ㅇㅈ. 정적 견디는 연습부터 함. 분위기 생기면 여자가 더 끌리겠지. 운명원 확인해봐야겠다",
     "reason": "운명원에서 뭘 보는지, 그게 왜 좋은지가 없어서 흥미가 안 생김"},
    {"score": 6, "comment": "사진 확대 비유 완전 공감당~ 내 머릿속에서 썸남이 커져서 불안한데 덜 흔들리고 사귀고 싶당, 운명원에 물어봐야징~",
     "reason": "'~당 ~징'이 과하고 '공감당'은 실제로 안 쓰는 말. 옛날 말투"},
    {"score": 8, "comment": "'잘 지내?' 한 줄에 아직도 심장이 흔들리는 내 모습 진짜 공감돼ㅠㅠ 진짜 속내 알고 흔들리고 싶지 않아서 운명원에 봐볼까",
     "reason": "앞은 좋은데 '운명원에 봐볼까'로 끝남. 운명원에서 정확히 뭘 보고 그게 뭐가 좋은지 없으면 흥미가 안 생김"},
    {"score": 7, "comment": "늘 '오늘 밥 먹었어?'라며 챙겨주던 모습이 왜 이렇게 그리운지. 그런 사람과 다시 시작하고 싶어. 운명원에 사주로 재회 가능성을 알아보고 싶어",
     "reason": "영상은 회피형이 뒤늦게 연락하는 이유인데 댓글은 재회 바람이라 인과가 의심됨. 말투도 딱딱함"},
    {"score": 6, "comment": "남자들이 '난 안다'고 해도 사실은 모른다더라니 씁쓸했어. 내 진짜 감정 못 읽는 사람은 싫어. 운명원에서 그런 사람 올 시기 본다길래 나도 한번 가보고 싶네.",
     "reason": "'올 시기 본다길래'는 뜻이 읽히지 않음. 운명원은 장소가 아닌데 '가보고 싶네'라고 함"},
    {"score": 5, "comment": "며칠 뒤에 '발표 잘됐어요?' 먼저 챙겨주는 태도면 진짜 안심된다. 꾸준히 관심 주는 사람 만나고 싶어. 운명원에 그런 인연 가능성 궁금하다.",
     "reason": "'안심'이 왜 나오는지 모름. 영상은 말문 막힘인데 엉뚱한 바람. 썸 관계에서 '친해지기'는 친구 사이 표현"},
    {"score": 3, "comment": "정서적으로 안정된 사람이 편안하더라. 나도 그런 남자와 안정된 연애 하고 싶어. 운명원에서 그 시기를 알려준다더라, 궁금해",
     "reason": "영상 목적은 '가치 높은 여자가 되어 좋은 남자를 만나자'인데 뜬금없이 안정적인 남자 얘기로 시작함"},
    {"score": 0, "comment": "전 연인의 작은 장점이 다시 보인다는 얘기 와닿았어. 돌아와도 같은 상처 반복하고 싶지 않아. 운명원에서 재회해도 패턴 안 반복될지 알고 싶다.",
     "reason": "상대는 이미 새 연인과 행복함. 돌아올 가능성이 없는데 '돌아와도'를 전제로 함. 사람의 사고방식과 안 맞음"},
    {"score": 7, "comment": "혼자 있는 게 편하다며 떠난 사람이 뒤늦게 연락하면 진짜 속 터져. 저런 회피형은 만나고 싶지 않은데. 운명원에서 사주 보면 안정형 만날 수 있다는데 나도 한번 확인해보고 싶네.",
     "reason": "'않은데', '있다는데'처럼 ~데 연결이 두 번 들어가 매끄럽지 않음"},
    {"score": 6, "comment": "나한테 안 해 주던 걸 새 사람한테는 해주는 거 보니까 속상하네. 다시 만나도 같은 상처 받을까 봐 무서워. 운명원에서 사주 보면 이 사람이랑 계속 만나면 내가 어떨지 알 수 있을 것 같은데 궁금하다.",
     "reason": "'운명원에서 사주 보면'이 반복되면 부자연스러움"},
]

# ---------- 말투 카드: 후보마다 다른 사람처럼 쓰게 한다 ----------
STYLE_CARDS = {
    "여성": [
        ("감성 반말", "반말. ㅠㅠ, ㅜㅜ, .. 를 한두 번 (예: 알파남.. 나도 ~ㅠㅠ / ~안만나고 싶은걸)"),
        ("웃긴 반말", "솔직하게 웃으면서 쓰는 반말. ㅋㅋㅋㅋ 한 번 (예: 진짜 미칠텐데 ㅋㅋㅋㅋ)"),
        ("담백 반말", "이모티콘 없이 짧고 담백한 반말 (예: ~불안한걸. ~물어봐야겠네)"),
        ("존댓말", "자연스러운 20대 존댓말 ~요, ~것 같아요. '~구요/궁금하네요'를 반복하는 아줌마 말투는 피한다"),
    ],
    "남성": [
        ("담백 반말", "이모티콘 없이 짧은 반말 (~듯, ~해야겠다)"),
        ("웃긴 반말", "ㅋㅋ 섞인 솔직한 반말. 자조는 가볍게"),
        ("존댓말", "무난한 20대 남자 존댓말 ~네요, ~것 같아요"),
    ],
    "민감": [
        ("진중한 존댓말", "성·잠자리처럼 민감한 주제라 가볍지 않게 ~했어요, ~것 같아요"),
        ("담백한 존댓말", "이모티콘 없이 조심스러운 존댓말"),
        ("담백 반말", "가볍지 않게, 이모티콘 없이 짧은 반말 (예: ~불안한걸. ~물어봐야겠네)"),
    ],
}
_SENSITIVE = re.compile(r"(섹스|잠자리|속궁합|성관계|오르가|스킨십)")
SLIP_HINT = "이 후보는 실제 사람처럼 띄어쓰기 한 군데를 붙여 쓰거나(예: 안만나고, 할거같아) 구어 맞춤법(함, 넘, ~할텐데)을 써도 된다. 단 '운명원' 철자는 틀리지 않는다"


def _style_cards(speaker: str, recent_styles: list[str], topic: str = "") -> list[tuple[str, str]]:
    """후보 5개에 말투 카드 배정. 민감한 주제는 진중한 존댓말. 최근 말투는 뒤로. 1개에는 자연스러운 실수 허용."""
    key = "민감" if _SENSITIVE.search(topic) else ("남성" if "남" in str(speaker) else "여성")
    pool = list(STYLE_CARDS[key])
    random.shuffle(pool)
    pool.sort(key=lambda c: c[0] in recent_styles)
    cards = [list(pool[i % len(pool)]) for i in range(5)]
    cards[random.randrange(len(cards))][1] += f" / {SLIP_HINT}"
    return [tuple(c) for c in cards]


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _client():
    _load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("no_api_key: .env 파일에 OPENAI_API_KEY 를 넣어 주세요.")
    from openai import OpenAI
    return OpenAI()


def _model() -> str:
    _load_env()
    return os.environ.get("OPENAI_MODEL", "gpt-5-mini")


def _chat_json(client, system: str, user: str) -> dict:
    res = client.chat.completions.create(
        model=_model(),
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    data = json.loads(res.choices[0].message.content)
    return data if isinstance(data, dict) else {}


_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-*.]{4,}")


def redact(text) -> str:
    """오류 문구 등에 섞인 API 키 조각을 가린다 (화면·로그·녹화 노출 방지)."""
    return _KEY_RE.sub("sk-***", str(text))


def _sentences(text: str) -> list[str]:
    return [x for x in _SENT_SPLIT.split(text) if x.strip()]


def _as_int(v):
    """모델이 번호를 '0', 0.0 등으로 돌려줘도 정수로."""
    try:
        return int(float(str(v).strip().rstrip("점")))
    except (TypeError, ValueError):
        return None


def _as_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    return None


# ---------- 실제 시청자 댓글 (말투 참고) ----------
_REF_BAD = re.compile(r"(https?://|www\.|@\w|구독|광고|협찬|이벤트|링크)", re.I)
# 수집 댓글 중 연애 주제 영상의 댓글만 참고 (검색 결과에 게임·타로 영상 등이 섞임)
_LOVE_TITLE = re.compile(r"(연애|남자|여자|썸|재회|이별|헤어|짝사랑|고백|연락|남친|여친|결혼|사랑|소개팅|데이트|애인|호감|회피형|집착|권태)")
_TIMESTAMP = re.compile(r"\b\d{1,2}:\d{2}\b")
_MALE_HINT = re.compile(r"(연애데이터|여자가 먼저|여자를|여자 심리|여자의 본능|여자 호감|호감신호|여친|썸녀|남자가 알아야|남자 대화법)")
_corpus_cache = {"mtime": None, "rows": []}


def _clean_ref(t: str) -> str | None:
    t = re.sub(r"\s+", " ", t or "").strip()
    if not 10 <= len(t) <= 150 or _REF_BAD.search(t) or BRAND in t or not re.search(r"[가-힣]", t):
        return None
    return t


def _load_corpus() -> list[dict]:
    try:
        mtime = CORPUS.stat().st_mtime
    except OSError:
        return []
    if _corpus_cache["mtime"] != mtime:
        rows = []
        for line in CORPUS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if _clean_ref(r.get("text", "")):
                rows.append(r)
        _corpus_cache.update(mtime=mtime, rows=rows)
    return _corpus_cache["rows"]


def _style_refs(ctx: dict, speaker: str, k_video: int = 4, k_total: int = 10) -> list[str]:
    """이 영상의 인기 댓글 + 수집한 댓글 중 좋아요 많은 것. 남자 화자면 남성 대상 영상 댓글을 우선."""
    refs = []
    for c in sorted(ctx.get("top_comments") or [], key=lambda c: c.get("likes") or 0, reverse=True):
        t = _clean_ref(c.get("text", ""))
        if t and t not in refs:
            refs.append(t)
        if len(refs) >= k_video:
            break
    rows = [r for r in _load_corpus()
            if r.get("video_id") != ctx.get("video_id") and _LOVE_TITLE.search(r.get("title", ""))
            and not _TIMESTAMP.search(r.get("text", ""))]
    if rows:
        male = "남" in str(speaker)
        pref = [r for r in rows
                if bool(_MALE_HINT.search(f"{r.get('channel', '')} {r.get('title', '')}")) == male] or rows
        pool = sorted(pref, key=lambda r: r.get("likes") or 0, reverse=True)[:300]
        random.shuffle(pool)
        for r in pool:
            t = _clean_ref(r["text"])
            if t and t not in refs:
                refs.append(t)
            if len(refs) >= k_total:
                break
    return refs


# ---------- 1단계: 영상 분석 ----------
ANALYZE_SYSTEM = """너는 유튜브 연애 영상을 분석하는 편집자다.
주어진 제목·설명·자막·인기 댓글만 근거로, 지어내지 말고 아래 JSON으로 답한다. 제목보다 자막 내용을 우선한다.
{
  "message": "영상이 시청자에게 말하려는 결론이나 목적 한 문장 (예: 가치 높은 여자가 되어야 좋은 남자를 만난다)",
  "worry": "이 영상을 보는 시청자의 연애 고민 30자 안팎",
  "scenes": ["자막에 실제로 나온 구체적인 말이나 예시 3개 (자막에 없는 내용 금지)"],
  "speaker": "댓글 화자: 영상이 남성 시청자 대상이면 '20대 남성', 아니면 '20대 여성'",
  "status": "화자의 지금 상황 하나: 사귀는 사람 있음 / 썸·호감 상대 있음 / 헤어진 상대를 생각 중 / 상대 없음",
  "wish": "화자가 이 영상을 보고 바라게 되는 것 한 가지",
  "ask": "화자가 연애 사주로 가장 알고 싶을 것 하나 (아래 ask 규칙)",
  "natural": true 또는 false (위 화자로 억지 없이 연애 고민 댓글을 달 수 있는가),
  "unnatural_reason": "natural이 false면 이유"
}
wish 규칙:
- message에서 바로 나와야 한다. 영상이 '내가 바뀌자'고 말하면 wish도 '나도 그렇게 돼서 좋은 사람 만나기'처럼 내 쪽이다
- 상황상 현실적이어야 한다. 전 연인이 이미 새 사람과 행복하다면 '돌아오길 바람'이 아니라 '더 좋은 사람 만나기' 쪽이다
- 썸·호감 상대가 있으면 '친해지기'가 아니라 '가까워지기, 사귀기'다
- 영상 결론이 '신중하게 판단하라/휘둘리지 마라'면 바람도 '상대가 해주길'이 아니라 '휘둘리지 않고 판단하기' 쪽이다
- '안정적인 관계'처럼 어느 영상에나 붙는 막연한 말로 쓰지 않는다
ask 규칙: status와 wish에서 바로 나오는 것 하나를 고른다
- 상대 없음: 언제 좋은 사람 만날지 / 나랑 맞는 사람이 어떤 사람인지 / 좋은 사람 만나려면 뭘 준비할지
- 썸·호감: 이 사람과 잘 될지 / 이 사람 마음이 나한테 있는지. '고백 타이밍'은 영상이 고백을 직접 다룰 때만
- 헤어진 상대: 다시 만나도 잘 될지 / 다시 인연이 이어질지 / 새 인연은 언제 올지
- 사귀는 중: 이 사람과 앞으로도 잘 갈지 / 결혼까지 갈 인연인지"""


def _context_text(ctx: dict) -> str:
    comments = "\n".join(f"- ({c['likes']}) {c['text'][:150]}" for c in ctx["top_comments"][:15])
    transcript = ctx["transcript"] or "(자막 없음: 제목·설명·댓글로 판단)"
    return (
        f"[제목] {ctx['title']}\n[채널] {ctx['channel']}\n"
        f"[설명] {ctx['description'][:800]}\n\n[자막]\n{transcript}\n\n[인기 댓글]\n{comments}"
    )


# ---------- 2단계: 댓글 작성 ----------
WRITE_SYSTEM = f"""너는 방금 이 연애 영상을 본 시청자로서 유튜브 댓글을 하나 단다. 화자는 [화자]를 따른다.
목표: 이 댓글의 진짜 목적은 공감이 아니라, 읽은 사람이 '{BRAND}'에서 연애 사주를 보고 싶어지게 만드는 것이다.
공감은 그 목적을 위한 도입일 뿐이다. 진짜 사람이 폰으로 쓴 것처럼 써야 광고로 안 보인다.

흐름
1. 영상 속 구체적인 내용 하나에 대한 반응 ([영상의 결론]과 관련된 것. 영상 대사는 내 말로)
2. 내 얘기: [정리된 고민] [시청자 상황] [시청자가 바라는 것] 중 1~2개를 내 경험처럼 짧게 녹인다
   - 영상을 안 본 사람도 '아 이 사람 이런 상황이구나' 하고 공감할 수 있어야 한다
   - 예: "나도 썸남 답장 하나에 하루종일 기분이 왔다갔다 해서 ㅠㅠ" / "헤어지고 3개월째인데 아직도 연락 기다림"
   - 분석 문구를 그대로 옮기지 말고 내 말로 쓴다. 셋 다 넣어 설명처럼 늘어지게 하지 않는다
3. {BRAND} 부분 (가장 중요): [무엇을 본다는지] + [그걸 알면 나한테 뭐가 좋은지 또는 한번 해봐야지]
   - 무엇: [{BRAND}에 물어볼 것]을 기본으로 한다. 내 상황과 안 맞는 걸 묻지 않는다
   - '고백 타이밍'은 영상이 고백을 다루고 화자가 썸 상대가 있을 때만 쓴다
   - 좋은 점: 좋은 결과면 더 자신 있게 말할 수 있을 것 같다 / 그럼 덜 불안할 듯 / 그런 사람 만나고 싶다
   좋은 예: "운명원에서 이 사람과 내가 잘 될지 한 번 봐볼까? 좋은 결과면 더 자신있게 말할 수 있을 거 같아!"
            "운명원에서 그런 타이밍 잘 알려준다는데 한번 해봐야지~" / "썸남과 잘될지 운명원에 물어봐야겠네"
            "운명원 연애사주가 그렇게 잘 본다던데 나도 언제 짝 만나는지 한번 보고 싶다"
   나쁜 예(흥미가 안 생김): "운명원에 봐볼까" / "운명원 궁금함" / "운명원 확인해봐야겠다" / "운명원에 물어봐야겠다" (무엇을 보는지 없음)

{BRAND}은 연애 사주를 잘 보는 곳이다
- 연결할 내용: 이 사람이랑 잘 될지 / 이 사람과 행복할지 / 좋은 사람을 언제 만날지 / 좋은 사람 만나려면 뭘 준비할지 / 연락·고백 타이밍
- 감정의 원인 분석이나 심리 상담처럼 쓰지 않는다. 장소가 아니므로 '가서', '가보고 싶다'라고 쓰지 않는다 (봐볼까, 물어봐야지, 봐야겠다)

말투
- 후보마다 아래 [말투 카드]를 하나씩 따른다. 카드가 다르면 다른 사람이 쓴 것처럼 보여야 한다
- 딱딱한 문어체도, 억지 신조어도 AI 티가 난다. 기준 댓글처럼 요즘 20대가 쓰는 평범한 구어체로 쓴다
- '공감당', '~징', '레전드', '현타', '개궁금', '~각' 같은 억지·옛날 표현은 쓰지 않는다
- 화자가 20대 남성이면 남자가 실제로 쓰는 말투로, 상대를 여자/썸녀/여친 등으로 부른다
- 비하·혐오 표현은 쓰지 않는다

꼭 지킬 것
- 영상 결론과 반대되거나 현실적으로 말이 안 되는 상황을 만들지 않는다 (예: 새 연인과 행복한 전 애인이 돌아온다는 전제)
- [시청자 상황]과 맞게 쓴다. 상대가 없으면 '이 사람/지금 사람' 얘기를 하지 않는다
- '~는데/~던데' 연결이 연달아 붙어 늘어지지 않게 한다
- 한 댓글 안에서 같은 단어(고백, 타이밍, 잘될지 등)를 두 번 쓰지 않는다
- '{BRAND}에서 사주 보면'은 [이전 댓글]에 이미 있으면 쓰지 않는다. [이전 댓글]과 같은 결론을 표현만 바꿔 반복하지 않는다
- 영상이 {BRAND}을 언급한 것처럼 쓰지 않는다. '영상에서', '영상 보고', '장면' 같은 리뷰 말투 금지
- '{BRAND}'은 정확히 한 번. 전체 {MIN_CHARS}~{MAX_CHARS}자
- 금지: 링크, 해시태그, {BRAND}을 이용해 본 것 같은 후기(봤는데/맞더라 등), '무조건 맞는다/용하다' 같은 단정

[실제 시청자 댓글]은 연애 영상에 실제로 달린 댓글이다. 말투, 길이, 이모티콘 쓰는 법, 문장 끊는 법만 참고한다.
내용과 문장은 절대 베끼지 않는다 (비슷하면 탈락). 실제 댓글에는 {BRAND}이 없으므로 {BRAND} 부분은 아래 기준 댓글을 따른다.

아래는 실제 사람이 쓴 기준 댓글이다 (8~10점). 다른 영상용이므로 문장을 베끼지 말고 말투와 흐름만 참고한다:
""" + "\n".join(f"- {c}" for c in GOOD_EXAMPLES) + """

후보 5개를 [말투 카드] 순서대로 하나씩 쓴다.
JSON으로만 답한다: {"candidates": [{"comment": "..."}, ...]}"""


# ---------- 4단계: 10점 척도 심사 ----------
JUDGE_SYSTEM = f"""너는 한국어 유튜브 댓글을 사람 기준으로 채점하는 검수자다. 출력된 문장만 보고 판단한다.
이 댓글의 목적은 읽은 사람이 {BRAND}에서 연애 사주를 보고 싶어지게 하는 것이다. 문장이 자연스러워도 이 목적을 못 이루면 낮은 점수다.
점수 기준 (0~10):
- {BRAND} 부분에 '무엇을 본다는지'와 '그게 왜 나한테 좋은지(또는 해보고 싶은 이유)'가 없으면 5점 이하 ('운명원에 봐볼까', '운명원 궁금함' 류)
- 억지 신조어나 옛날 말투('공감당', '~징', '레전드' 등), 20대가 아니라 40대 같은 말투면 6점 이하
- 8~10: 실제 20대가 폰으로 쓴 것 같고, 영상의 결론에 정확히 맞고, 내 마음 → {BRAND} 궁금증이 자연스럽게 이어진다
- 6~7: 대체로 괜찮지만 연결이 조금 어색하거나, AI가 쓴 티가 나거나, 같은 연결어·관용구가 반복된다
- 정돈된 문어체로 모든 문장이 '~다/~싶다'로 끝나는 딱딱한 말투는 내용이 좋아도 최대 7점
- ㅋㅋ·ㅠㅠ·ㅎㅎ·신조어·구어 맞춤법·띄어쓰기 실수는 감점하지 않는다 (자연스러우면 오히려 좋다)
- {BRAND}을 장소처럼 쓰거나('가서', '가보고 싶다') 감정 분석·심리 상담 용도로 쓰면 6점 이하
- 영상 결론과 어긋나거나 현실적으로 말이 안 되는 전제(새 연인과 행복한 전 애인이 돌아온다 등)면 0~3점
- 0~5: 영상 고민과 어긋남 / 앞뒤 감정이 모순 / 화자 성별·연애 상황이 앞뒤로 다름 / 자막에 없는 내용을 영상 내용처럼 씀 /
  영상이 {BRAND}을 언급한 것처럼 씀 / {BRAND} 이용 후기를 꾸밈 / 사람이 안 쓰는 어색한 표현
- [이전 댓글]과 결론이 사실상 같으면(표현만 바꾼 같은 결론) 6점 이하로 한다. 단, 연애라는 주제가 같다는 것만으로 감점하지 않는다
- 영상을 안 본 사람이 읽어도 화자의 고민이나 상황을 알 수 있어야 8점 이상이다 (영상 대사 반응만 있고 내 얘기가 없으면 최대 7점)
- {BRAND}에 묻는 내용이 화자 상황과 안 맞으면 6점 이하 (영상이 고백을 다루지 않는데 '고백 타이밍', 상대가 없는데 '이 사람과 잘될지')
- 한 댓글 안에서 같은 단어(고백, 타이밍 등)가 반복되면 최대 7점
- [분석]의 고민·상황·바람이 자막과 맞지 않으면 분석을 믿지 말고 자막 기준으로 판단한다

사용자가 직접 매긴 점수 (이 기준에 맞춰 채점한다):
""" + "\n".join(f"- 8~10점: {c}" for c in GOOD_EXAMPLES) + "\n" + \
    "\n".join(f"- {a['score']}점: {a['comment']} (이유: {a['reason']})" for a in SCORED_ANCHORS) + """
[사용자 0점 판정]에 있는 댓글과 같은 이유의 문제가 있으면 5점 이하로 한다.

후보마다 점수와 구체적인 이유를 쓰고, 가장 높은 후보 하나를 best로 고른다.
JSON으로만 답한다: {"results": [{"id": 후보번호, "score": 점수, "reason": "구체적인 이유"}, ...], "best": 후보번호}"""


# ---------- 묶음 검증: 여러 댓글 사이의 반복 (batch_drafts.py 전용, 보고용) ----------
BATCH_SYSTEM = f"""너는 같은 시스템이 여러 영상에 단 댓글 묶음을 검수한다. 개별 품질이 아니라 댓글들 사이의 반복만 본다.
실질적으로 같은 결론, 같은 전개, 반복되는 관용구를 찾는다. 연애라는 주제가 같다는 것만으로는 중복이 아니다.
문제가 있는 댓글만 번호로 지정하고 무엇이 겹치는지 구체적으로 쓴다.
JSON으로만 답한다: {{"issues": [{{"id": 번호, "similar_to": [번호], "detail": "겹치는 요소"}}, ...], "summary": "한 줄 평"}}"""


def review_batch(comments: list[str]) -> dict:
    if len(comments) < 2:
        return {"issues": [], "summary": ""}
    listing = "\n".join(f"{i}. {c}" for i, c in enumerate(comments, 1))
    return _chat_json(_client(), BATCH_SYSTEM, listing)


def validate(comment: str, recent: list[str] | None = None, refs: list[str] | None = None,
             confess_ok: bool | None = None) -> list[str]:
    """코드로 확인할 수 있는 규칙 위반 사유 목록. 빈 목록이면 통과.
    confess_ok=False 면 영상이 고백을 다루지 않으므로 '고백' 언급을 막는다 (None이면 검사 안 함)."""
    errs = []
    if comment.count("고백") > 1 or comment.count("타이밍") > 1:
        errs.append("한 댓글에 '고백/타이밍'이 두 번 나옴")
    if confess_ok is False and "고백" in comment:
        errs.append("영상이 고백을 다루지 않는데 고백 얘기를 함")
    n = len(comment)
    if not MIN_CHARS <= n <= MAX_CHARS:
        errs.append(f"길이 {n}자 ({MIN_CHARS}~{MAX_CHARS}자여야 함)")
    if comment.count(BRAND) != 1:
        errs.append(f"'{BRAND}'을 정확히 한 번 언급해야 함 (현재 {comment.count(BRAND)}회)")
    if _LINK.search(comment):
        errs.append("링크/주소 표현 포함")
    if "#" in comment:
        errs.append("해시태그 포함")
    m = _PROMO.search(comment)
    if m:
        errs.append(f"과도한 홍보 표현: '{m.group(0)}'")
    sents = _sentences(comment)
    for sent in sents:
        if BRAND in sent and _FAKE_REVIEW.search(sent):
            errs.append(f"이용 후기처럼 보이는 표현: '{_FAKE_REVIEW.search(sent).group(0)}'")
            break
    brand_sent0 = next((x for x in sents if BRAND in x), "")
    if brand_sent0 and _AS_PLACE.search(brand_sent0[brand_sent0.index(BRAND):]):
        errs.append(f"{BRAND}을 장소처럼 씀 ('{_AS_PLACE.search(brand_sent0[brand_sent0.index(BRAND):]).group(0)}')")
    if brand_sent0:
        k = sents.index(brand_sent0)
        scope = " ".join(sents[max(0, k - 1):k + 1])
        if not _LURE_WHAT.search(scope):
            errs.append(f"{BRAND}에서 무엇을 보는지(잘 될지·언제 만날지·타이밍 등)가 없음")
    m = _OUTDATED.search(comment)
    if m:
        errs.append(f"억지·옛날 말투: '{m.group(0)}'")
    m = _REVIEW_TONE.search(comment)
    if m:
        errs.append(f"리뷰 말투: '{m.group(0)}'")
    if "·" in comment:
        errs.append("가운뎃점 사용")
    if len([x for x in sents if len(x) > 70]):
        errs.append("너무 긴 문장 (내용이 바뀌는 곳에서 끊을 것)")
    for ref in refs or []:
        sm = difflib.SequenceMatcher(None, comment, ref)
        if sm.ratio() > 0.5 or sm.find_longest_match(0, len(comment), 0, len(ref)).size >= 15:
            errs.append("실제 댓글을 베낌")
            break
    if recent:
        if _FIXED_BRAND_PHRASE in comment and any(_FIXED_BRAND_PHRASE in p for p in recent[-5:]):
            errs.append(f"'{_FIXED_BRAND_PHRASE}' 표현이 최근 댓글에 이미 있음")
        brand_sent = next((x for x in sents if BRAND in x), "")
        for prev in recent[-6:]:
            pb = next((x for x in _sentences(prev) if BRAND in x), "")
            if brand_sent and pb and difflib.SequenceMatcher(None, brand_sent, pb).ratio() > 0.75:
                errs.append(f"{BRAND} 문장이 최근 댓글과 거의 같음")
                break
        for prev in recent:
            if difflib.SequenceMatcher(None, comment, prev).ratio() > 0.6:
                errs.append("이전 댓글과 너무 비슷함")
                break
    return errs


def _user_feedback(limit: int = 10) -> list[dict]:
    """data/batch_*.txt 에서 사용자가 X(0점) 또는 5점 이하로 판정한 댓글과 이유."""
    out = []
    for f in sorted(DATA.glob("batch_*.txt")):
        comment = None
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*댓글\(\d+자\):\s*(.+)", line)
            if m:
                comment = m.group(1).strip()
                continue
            m = re.match(r"\s*내 판정\(O/X\)과 이유:\s*[Xx]\s*(.*)", line) or \
                re.match(r"\s*내 점수\(0~10\)와 이유:\s*([0-5])(?:점)?\b\s*(.*)", line)
            if m and comment:
                reason = (m.group(m.lastindex) if m.lastindex else "").strip().lstrip(".·:- ")
                out.append({"comment": comment, "reason": reason})
                comment = None
    return out[-limit:]


def _recent_comments(exclude_video: str, limit: int = RECENT_N) -> list[str]:
    """같은 프롬프트 버전으로 통과한 댓글만. 사용자가 0점/X 판정한 댓글은 제외."""
    if not DRAFT_LOG.exists():
        return []
    bad = {r["comment"] for r in _user_feedback(limit=1000)}
    rows = []
    for line in DRAFT_LOG.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return [r["comment"] for r in rows
            if r.get("pv") == PROMPT_VERSION and r.get("ok") and r.get("video_id") != exclude_video
            and r.get("comment") not in bad][-limit:]


def _recent_styles(n: int = 3) -> list[str]:
    if not DRAFT_LOG.exists():
        return []
    out = []
    for line in DRAFT_LOG.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("pv") == PROMPT_VERSION and r.get("ok") and r.get("style"):
            out.append(r["style"])
    return out[-n:]


def _log(row: dict) -> None:
    DRAFT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with DRAFT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def make_draft(ctx: dict) -> dict:
    """get_video_context() 결과 → {"worry","comment","chars","ok","errors","score",...}"""
    client = _client()
    source = _context_text(ctx)
    analysis = _chat_json(client, ANALYZE_SYSTEM, source)

    recent = _recent_comments(ctx["video_id"])
    recent_txt = json.dumps(recent, ensure_ascii=False) if recent else "없음"
    zero = _user_feedback()
    info = (
        f"[영상의 결론] {analysis.get('message')}\n"
        f"[정리된 고민] {analysis.get('worry')}\n"
        f"[짚을 수 있는 내용] {json.dumps(analysis.get('scenes', []), ensure_ascii=False)}\n"
        f"[화자] {analysis.get('speaker')}\n"
        f"[시청자 상황] {analysis.get('status')}\n"
        f"[시청자가 바라는 것] {analysis.get('wish')}\n"
        f"[{BRAND}에 물어볼 것] {analysis.get('ask')}\n"
    )
    base = f"{source}\n\n{info}[이전 댓글] {recent_txt}"
    judge_head = (
        f"[제목] {ctx['title']}\n[자막]\n" + (ctx["transcript"] or f"(자막 없음) [설명] {ctx['description'][:800]}") +
        f"\n\n[분석]\n{info}[이전 댓글] {recent_txt}\n"
        f"[사용자 0점 판정] {json.dumps(zero, ensure_ascii=False) if zero else '없음'}"
    )

    refs = _style_refs(ctx, analysis.get("speaker", ""))
    confess_ok = "고백" in f"{ctx['title']} {ctx['transcript'] or ''} {analysis.get('wish', '')}"
    refs_txt = "\n".join(f"- {r}" for r in refs) if refs else "없음"
    comment, errors, reason, score, style = "", ["미생성"], "", None, ""
    recent_styles = _recent_styles()
    attempts, feedback = 0, ""
    if _as_bool(analysis.get("natural")) is False:
        errors = [f"자연스러운 댓글을 만들 수 없는 영상: {analysis.get('unnatural_reason') or '사유 미기재'}"]
    else:
        for attempts in range(1, MAX_ATTEMPTS + 1):
            cards = _style_cards(analysis.get("speaker", ""), recent_styles, f"{ctx['title']} {analysis.get('worry', '')}")
            card_txt = "\n".join(f"후보 {i + 1}: [{name}] {desc}" for i, (name, desc) in enumerate(cards))
            out = _chat_json(client, WRITE_SYSTEM,
                             f"{base}\n\n[실제 시청자 댓글]\n{refs_txt}\n\n[말투 카드]\n{card_txt}{feedback}")
            cands = []
            for k, c in enumerate(out.get("candidates") or []):
                text = c.get("comment", "") if isinstance(c, dict) else c
                text = re.sub(r"\s+", " ", str(text)).strip()
                if text:
                    cands.append({"comment": text, "style": cards[k][0] if k < len(cards) else "",
                                  "errors": validate(text, recent, refs, confess_ok)})
            valid = [c for c in cands if not c["errors"]]
            problems = sorted({e for c in cands for e in c["errors"]})

            if valid:
                listing = "\n".join(f"{i}. {c['comment']}" for i, c in enumerate(valid))
                j = _chat_json(client, JUDGE_SYSTEM, f"{judge_head}\n\n[후보]\n{listing}")
                scored = {}
                for r in j.get("results") or []:
                    if isinstance(r, dict):
                        i, s = _as_int(r.get("id")), _as_int(r.get("score"))
                        if i is not None and 0 <= i < len(valid) and s is not None:
                            scored[i] = (s, str(r.get("reason", "")))
                if scored:
                    hi = max(s for s, _ in scored.values())
                    tops = [i for i in scored if scored[i][0] == hi]
                    fresh = [i for i in tops if valid[i]["style"] not in recent_styles]
                    best = _as_int(j.get("best"))
                    top = best if best in (fresh or tops) else (fresh or tops)[0]
                    comment, style, (score, reason) = valid[top]["comment"], valid[top]["style"], scored[top]
                    if score >= PASS_SCORE:
                        errors = []
                        break
                    errors = [f"심사 {score}점 (기준 {PASS_SCORE}점): {reason}"]
                    problems += [f"{s}점 — {valid[i]['comment'][:25]}… : {why}" for i, (s, why) in scored.items()]
                else:
                    comment, errors = valid[0]["comment"], ["심사 결과를 읽지 못함"]
            elif cands:
                comment, errors = cands[0]["comment"], cands[0]["errors"]
            feedback = ("\n\n[직전 후보들의 문제]\n- " + "\n- ".join(problems or ["후보 없음"]) +
                        "\n문장을 옮기거나 어미만 바꾸지 말고 위 문제가 없는 새 후보 5개를 써라.")

    result = {
        "pv": PROMPT_VERSION,
        "video_id": ctx["video_id"],
        "title": ctx["title"],
        "worry": analysis.get("worry", ""),
        "scenes": analysis.get("scenes", []),
        "speaker": analysis.get("speaker", ""),
        "status": analysis.get("status", ""),
        "wish": analysis.get("wish", ""),
        "ask": analysis.get("ask", ""),
        "comment": comment,
        "style": style,
        "style_refs": len(refs),
        "message": analysis.get("message", ""),
        "example_video": ctx["video_id"] in EXAMPLE_VIDEO_IDS,
        "chars": len(comment),
        "transcript_source": ctx["transcript_source"],
        "ok": not errors,
        "errors": errors,
        "score": score,
        "judge_reason": reason,
        "attempts": attempts,
        "model": _model(),
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    _log(result)
    return result

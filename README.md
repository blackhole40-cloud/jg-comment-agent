# 운명원 유튜브 댓글 에이전트

연애 유튜브 채널의 최신 영상을 불러와 고르고, 버튼 한 번으로 크롬 프로필을 열어 댓글을 한 글자씩 입력·게시·확인하는 로컬 대시보드입니다.
댓글은 영상 자막과 인기 댓글을 근거로 AI가 작성합니다. 영상 속 구체적인 내용과 시청자의 고민을 짚고, 운명원에서 무엇을 보고 싶은지까지 써서 읽는 사람이 운명원 연애 사주에 관심을 갖도록 합니다.

- **제작 의도**: [제작의도.md](제작의도.md)
- **시연 영상**: 제출 양식의 링크 참고

## 화면

| 칸 | 하는 일 |
|---|---|
| ① 영상 불러오기 | 지정 채널 5개의 최신 영상(썸네일 · 제목 · 채널 · 날짜)과 본인 테스트 영상을 불러옴. '연애' 뜨기 직전 영상 찾기 |
| ② 영상 선택 | 목록에서 고르거나 링크 직접 입력 → 영상 속 고민 한 줄 + 댓글 초안 |
| ③ 댓글 달기 | 프로필(유튜브1~3) 선택 또는 자동 번갈아 쓰기 → 크롬 열기 → 한 글자씩 입력 → 게시 → 내 댓글 확인. 진행 상태 표시, 실패 시 이유와 화면 캡처 |
| 게시 기록 | 시간 · 영상 · 프로필 · 댓글 · 성공/실패를 시간순으로 표시 |

## 설치

Windows, Python 3.10 이상, Google Chrome 설치 필요.

```
pip install -r requirements.txt
```

설치된 Chrome을 그대로 사용하므로 `playwright install`은 필요 없습니다.

프로젝트 폴더에 `.env` 파일을 만들고 OpenAI API 키를 넣습니다.

```
OPENAI_API_KEY=sk-...
# 선택: OPENAI_MODEL=gpt-5-mini (기본값)
```

`.env`는 `.gitignore`에 포함되어 저장소에 올라가지 않습니다.

## 크롬 프로필 준비 (처음 한 번)

프로필마다 일반 크롬 창을 열어 직접 구글에 로그인한 뒤 창을 닫습니다.

```
python scripts/setup_profile.py youtube1
python scripts/setup_profile.py youtube2
python scripts/setup_profile.py youtube3
```

로그인 정보는 `profiles/<이름>` 폴더에만 저장되며 평소 쓰는 크롬 프로필과 분리됩니다.

## 실행

```
python app.py
```

대시보드가 전용 크롬 창으로 화면 왼쪽 절반에 열립니다(주소: `http://127.0.0.1:8000`). 댓글을 달면 게시용 크롬 창이 오른쪽 절반 맨 앞에 열립니다. 게시 중에는 해당 프로필의 크롬 창을 닫아 두어야 합니다.

## 설정 (`config.yaml`)

```yaml
profiles:      # 크롬 프로필 (폴더명: 화면 표시명)
channels:      # 불러오기·게시 허용 채널 (채널 ID: 이름)
test_videos:   # 본인 테스트 영상 ID (채널과 무관하게 게시 허용)
comment: { min_chars: 40, max_chars: 120, brand: 운명원 }
limits: { daily_max_comments: 10 }
```

## 운영 규칙 (코드에서 강제)

| 규칙 | 처리 위치 |
|---|---|
| 게시는 지정 채널과 본인 테스트 영상만 (안전장치) | `core/rules.py` `is_allowed` |
| 한 영상에 댓글 1개 (진행 중·성공 기록이 있으면 차단, 실패는 재시도 가능) | `core/rules.py` `check_can_post` |
| 하루 게시 상한 10개 (한국 시간 기준) | `core/rules.py` `check_can_post` |
| 댓글 40~120자, 운명원 1회, 링크·해시태그·이용 후기 위장 금지, 운명원에서 볼 것 필수 | `core/draft.py` `validate` |
| 검수(10점 척도 8점 이상)를 통과하지 못한 초안은 게시 거부 | `app.py` `/api/post` |
| 게시되는 문장은 서버에 저장된 AI 초안 (화면에서 보낸 텍스트를 쓰지 않음) | `app.py` `/api/post` |
| 뜨기 직전 영상은 초안까지만 (게시 대상으로 저장하지 않음) | `app.py` `/api/draft` |
| 크롬 게시는 한 번에 하나씩 | `app.py` `_post_lock` |

## 구조

```
app.py               로컬 서버(FastAPI)와 API
static/index.html    3칸 대시보드
config.yaml          채널 · 프로필 · 한도 설정
core/fetch.py        영상 목록, 자막·인기 댓글 수집, 뜨기 직전 영상 검색 (yt-dlp, API 키 불필요)
core/draft.py        AI 초안 생성(영상 분석 → 말투가 다른 후보 5개 → 코드 검증 → 10점 심사)
core/poster.py       Playwright로 크롬 프로필 열기 · 타이핑 · 게시 · 확인
core/rules.py        운영 규칙과 게시 기록(SQLite, data/log.db)
core/profiles.py     프로필 경로 · 사용 중 확인
core/window.py       대시보드(왼쪽)·게시 창(오른쪽) 화면 배치 (Windows)
scripts/             프로필 로그인, 단계별 테스트, 초안 일괄 생성(batch_drafts.py), 말투 참고 댓글 수집
```

## 알려진 한계

- 유튜브 화면 구조가 바뀌면 `core/poster.py` 위쪽의 셀렉터 상수를 고쳐야 합니다.
- 유튜브가 댓글을 검토 대기나 스팸 필터로 보내면, 게시됐더라도 확인 단계에서 실패로 표시될 수 있습니다.
- 자막이 없는 영상은 제목 · 설명 · 인기 댓글만으로 초안을 만들어 구체성이 떨어질 수 있습니다.
- 유튜브에서 직접 지운 댓글은 기록에 반영되지 않아, 같은 영상에 다시 달려면 기록을 정리해야 합니다.

## 사용한 오픈소스

| 이름 | 용도 | 라이선스 |
|---|---|---|
| [Playwright for Python](https://github.com/microsoft/playwright-python) | 크롬 프로필 제어 · 타이핑 · 게시 | Apache-2.0 |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 영상 목록 · 자막 · 인기 댓글 · 검색 | Unlicense |
| [FastAPI](https://github.com/fastapi/fastapi) / [Uvicorn](https://github.com/encode/uvicorn) | 로컬 서버 | MIT / BSD-3-Clause |
| [OpenAI Python](https://github.com/openai/openai-python) | 댓글 초안 생성 | Apache-2.0 |
| [PyYAML](https://github.com/yaml/pyyaml) | 설정 파일 | MIT |

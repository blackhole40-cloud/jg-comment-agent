"""YouTube 댓글 게시: 크롬 프로필 열기 → 한 글자씩 입력 → 게시 → 최신순에서 확인 (한국어 UI 기준)."""
import random
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from core.profiles import ROOT, ProfileInUseError, ensure_profile_free
from core.window import arrange

SHOTS_DIR = ROOT / "data" / "shots"

# 셀렉터 (id / role / aria 우선)
SEL_COMMENTS = "ytd-comments#comments"
SEL_PLACEHOLDER = "ytd-comments#comments #simplebox-placeholder"
SEL_INPUT = "ytd-comments#comments ytd-commentbox #contenteditable-root"
SEL_SUBMIT_WRAP = "ytd-comments#comments ytd-commentbox #submit-button"
SEL_SORT_MENU = "ytd-comments#comments #sort-menu"
SEL_COMMENT_TEXT = "ytd-comments#comments #contents #content-text"
SEL_AVATAR = "ytd-masthead button#avatar-btn"
SEL_SIGNIN = "ytd-masthead a[aria-label='로그인']"
# 댓글 사용 중지 안내 (문구가 조금씩 달라 넓게 찾음)
TEXT_DISABLED = re.compile(r"댓글.{0,6}(일시\s?중지|사용\s?중지|사용이\s?중지|꺼져)")


class PostError(Exception):
    pass


def _to_watch_url(url: str) -> str:
    """Shorts·youtu.be 주소를 일반 시청 페이지(/watch?v=ID)로 변환.
    Shorts 화면은 댓글 UI 구조가 달라 일반 시청 페이지에서 게시한다."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    m = re.match(r"^/shorts/([A-Za-z0-9_-]{11})", parts.path)
    if m and "youtube.com" in host:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    if host.endswith("youtu.be"):
        vid = parts.path.lstrip("/")[:11]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            return f"https://www.youtube.com/watch?v={vid}"
    return url


def _with_korean_ui(url: str) -> str:
    """hl=ko 를 붙여 한국어 UI를 강제 (셀렉터 텍스트 일관성)."""
    parts = urlsplit(_to_watch_url(url))
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "hl"]
    q.append(("hl", "ko"))
    return urlunsplit(parts._replace(query=urlencode(q)))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _check_logged_in(page) -> None:
    page.locator(f"{SEL_AVATAR}, {SEL_SIGNIN}").first.wait_for(state="visible", timeout=20000)
    if not page.locator(SEL_AVATAR).first.is_visible():
        raise PostError("not_logged_in: 이 프로필은 구글에 로그인되어 있지 않습니다. setup_profile.py로 먼저 로그인하세요.")


def _scroll_to_comments(page, ready_selector: str, timeout_s: float = 40) -> None:
    """댓글 영역은 화면에 들어와야 로드되므로 조금씩 스크롤하며 대기."""
    page.locator(SEL_COMMENTS).first.wait_for(state="attached", timeout=20000)
    page.locator(SEL_COMMENTS).first.scroll_into_view_if_needed()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if page.locator(ready_selector).first.is_visible():
            page.locator(ready_selector).first.scroll_into_view_if_needed()
            return
        if page.locator("#below").get_by_text(TEXT_DISABLED).first.is_visible():
            raise PostError("comments_disabled: 이 영상은 댓글이 사용 중지되어 있습니다.")
        # 댓글 영역을 화면에 두고 기다림 (아래 추천 목록까지 계속 내려가지 않게)
        page.locator(SEL_COMMENTS).first.scroll_into_view_if_needed()
        page.mouse.wheel(0, 300)   # 스크롤 신호로 댓글 로드를 깨우고
        page.wait_for_timeout(400)
        page.mouse.wheel(0, -300)  # 제자리로 (아래로 밀려나지 않게)
        page.wait_for_timeout(400)
    raise PostError(f"comments_not_loaded: 댓글 영역을 찾지 못했습니다 ({ready_selector}).")


def _type_human(page, text: str) -> None:
    for ch in text:
        if ch == "\n":
            page.keyboard.press("Shift+Enter")
        else:
            page.keyboard.type(ch)
        page.wait_for_timeout(random.randint(80, 150))


def _sort_newest(page) -> None:
    _scroll_to_comments(page, SEL_SORT_MENU)
    page.locator(SEL_SORT_MENU).first.click()
    option = page.locator("tp-yt-paper-listbox").get_by_text("최신순", exact=True).first
    option.wait_for(state="visible", timeout=10000)
    option.click()
    page.wait_for_timeout(2000)


def _find_my_comment(page, text: str, timeout_s: float = 30) -> bool:
    target = _norm(text)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for t in page.locator(SEL_COMMENT_TEXT).all_inner_texts():
            if _norm(t) == target:
                return True
        page.wait_for_timeout(1000)
    return False


def _screenshot(page) -> str | None:
    try:
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        path = SHOTS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path)
    except Exception:
        return None


def post_comment(profile_dir, video_url: str, text: str, on_status=None) -> dict:
    """영상에 댓글 1개를 게시하고 최신순 정렬에서 보이는지 확인.

    on_status(status): "opening" / "typing" / "posted" / "failed"
    반환: 성공 {"ok": True, ...}, 실패 {"ok": False, "reason": str, "shot": str|None}
    """
    emit = on_status or (lambda s: None)
    profile_dir = Path(profile_dir)
    text = text.strip()

    if not text:
        emit("failed")
        return {"ok": False, "reason": "empty_text: 댓글 내용이 비어 있습니다.", "shot": None}
    if not profile_dir.exists():
        emit("failed")
        return {"ok": False, "reason": f"profile_not_found: {profile_dir} (setup_profile.py 먼저 실행)", "shot": None}
    try:
        ensure_profile_free(profile_dir)
    except ProfileInUseError as e:
        emit("failed")
        return {"ok": False, "reason": f"profile_in_use: {e}", "shot": None}

    emit("opening")
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                str(profile_dir),
                channel="chrome",
                headless=False,
                locale="ko-KR",
                no_viewport=True,
                chromium_sandbox=True,  # 크롬 보안 격리(샌드박스) 유지 → '--no-sandbox' 보안 경고 표시 안 됨
            )
        except PlaywrightError as e:
            emit("failed")
            msg = str(e)
            if "ProcessSingleton" in msg or "already in use" in msg or "lock" in msg.lower():
                msg = f"profile_in_use: 프로필 '{profile_dir.name}' 의 Chrome이 이미 실행 중입니다. 창을 닫고 다시 시도하세요."
            else:
                msg = f"launch_failed: {msg.splitlines()[0]}"
            return {"ok": False, "reason": msg, "shot": None}

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(15000)
        try:  # 게시 창을 화면 오른쪽 절반 + 맨 앞으로 (제목 표시로 이 창을 찾음)
            marker = f"운명원게시-{profile_dir.name}"
            page.evaluate("t => { document.title = t }", marker)
            arrange(marker, "right", front=True, wait_s=5)
        except Exception:
            pass
        try:
            page.goto(_with_korean_ui(video_url), wait_until="domcontentloaded", timeout=45000)
            _check_logged_in(page)

            _scroll_to_comments(page, SEL_PLACEHOLDER)
            page.locator(SEL_PLACEHOLDER).first.click()
            box = page.locator(SEL_INPUT).first
            box.wait_for(state="visible")
            box.click()

            emit("typing")
            _type_human(page, text)

            submit = page.locator(SEL_SUBMIT_WRAP).get_by_role("button", name="댓글").first
            submit.wait_for(state="visible")
            if not submit.is_enabled():
                raise PostError("submit_disabled: 게시 버튼이 비활성 상태입니다.")
            submit.click()

            # 게시되면 입력창이 닫힘. 실패해도 검증 단계에서 최종 판단.
            try:
                box.wait_for(state="hidden", timeout=15000)
            except PlaywrightTimeout:
                pass
            page.wait_for_timeout(3000)

            page.reload(wait_until="domcontentloaded", timeout=45000)
            _sort_newest(page)
            if not _find_my_comment(page, text):
                raise PostError("verify_failed: 새로고침 후 최신순에서 내 댓글을 찾지 못했습니다 (검토 대기/스팸 필터 가능).")

            emit("posted")
            return {"ok": True, "video_url": video_url, "text": text, "profile": profile_dir.name}

        except (PostError, PlaywrightError) as e:
            try:  # 실패 원인이 보이도록 댓글 영역으로 화면을 되돌린 뒤 캡처
                page.locator(SEL_COMMENTS).first.scroll_into_view_if_needed(timeout=3000)
                page.mouse.wheel(0, -150)
                page.wait_for_timeout(500)
            except Exception:
                pass
            shot = _screenshot(page)
            emit("failed")
            reason = str(e) if isinstance(e, PostError) else f"playwright: {str(e).splitlines()[0]}"
            return {"ok": False, "reason": reason, "shot": shot}
        finally:
            try:
                ctx.close()
            except Exception:
                pass

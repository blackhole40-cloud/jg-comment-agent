"""Windows 창 배치: 대시보드는 화면 왼쪽 절반, 게시용 유튜브 창은 오른쪽 절반 + 맨 앞.
Windows가 아니거나 실패하면 아무것도 하지 않는다 (게시 기능에는 영향 없음)."""
import os
import subprocess
import sys
import time
from pathlib import Path

IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _dwm = ctypes.windll.dwmapi
    try:  # 화면 배율(125%, 150% 등)과 상관없이 실제 픽셀 기준으로 계산
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            _user32.SetProcessDPIAware()
        except Exception:
            pass


def find_chrome() -> str | None:
    if not IS_WIN:
        return None
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as k:
                path = winreg.QueryValue(k, None)
                if path and Path(path).exists():
                    return path
        except OSError:
            continue
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            p = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if p.exists():
                return str(p)
    return None


def _work_area() -> tuple[int, int, int, int]:
    """작업 표시줄을 뺀 주 모니터 영역 (x, y, w, h)."""
    r = wintypes.RECT()
    _user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def half(side: str) -> tuple[int, int, int, int]:
    x, y, w, h = _work_area()
    lw = w // 2
    return (x, y, lw, h) if side == "left" else (x + lw, y, w - lw, h)


def _find_window(title_part: str) -> int | None:
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd):
            n = _user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                _user32.GetWindowTextW(hwnd, buf, n + 1)
                if title_part in buf.value:
                    found.append(hwnd)
                    return False
        return True

    _user32.EnumWindows(cb, 0)
    return found[0] if found else None


def _place(hwnd: int, rect: tuple[int, int, int, int]) -> None:
    """창의 보이는 테두리가 rect에 딱 맞도록 배치 (Windows 10/11의 투명 테두리 보정)."""
    x, y, w, h = rect
    _user32.ShowWindow(hwnd, 9)  # SW_RESTORE (최대화·최소화 해제)
    _user32.SetWindowPos(hwnd, 0, x, y, w, h, 0x0004 | 0x0010)  # NOZORDER | NOACTIVATE
    outer, inner = wintypes.RECT(), wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(outer))
    if _dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(inner), ctypes.sizeof(inner)) == 0:  # 실제 보이는 영역
        dl, dt = inner.left - outer.left, inner.top - outer.top
        dr, db = outer.right - inner.right, outer.bottom - inner.bottom
        _user32.SetWindowPos(hwnd, 0, x - dl, y - dt, w + dl + dr, h + dt + db, 0x0004 | 0x0010)


def _bring_to_front(hwnd: int) -> None:
    fg = _user32.GetForegroundWindow()
    cur = ctypes.windll.kernel32.GetCurrentThreadId()
    fg_thread = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(fg_thread and fg_thread != cur and _user32.AttachThreadInput(cur, fg_thread, True))
    try:
        _user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)  # 잠깐 맨 위 고정(TOPMOST)
        _user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)  # 고정 해제, 맨 앞 유지
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(cur, fg_thread, False)


def arrange(title_part: str, side: str, front: bool = False, wait_s: float = 10) -> bool:
    """제목에 title_part가 들어간 창을 찾아 화면 왼쪽/오른쪽 절반에 배치."""
    if not IS_WIN:
        return False
    try:
        deadline = time.time() + wait_s
        hwnd = _find_window(title_part)
        while not hwnd and time.time() < deadline:
            time.sleep(0.3)
            hwnd = _find_window(title_part)
        if not hwnd:
            return False
        _place(hwnd, half(side))
        if front:
            _bring_to_front(hwnd)
        return True
    except Exception:
        return False


def open_dashboard(url: str, profile_dir: Path, title: str) -> bool:
    """대시보드를 전용 크롬 앱 창으로 열어 화면 왼쪽 절반에 배치. 실패하면 False (기본 브라우저로 대체)."""
    chrome = find_chrome()
    if not chrome:
        return False
    try:
        subprocess.Popen([
            chrome, f"--user-data-dir={profile_dir}", f"--app={url}",
            "--no-first-run", "--no-default-browser-check",
        ])
    except OSError:
        return False
    arrange(title, "left", front=True, wait_s=15)
    return True

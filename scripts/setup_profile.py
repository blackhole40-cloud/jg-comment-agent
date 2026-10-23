"""설치된 Chrome을 전용 프로필로 일반 실행 (자동화 아님).

사용: python scripts/setup_profile.py youtube1
창이 뜨면 구글 로그인 후 Chrome 창을 닫으세요.
"""
import os
import subprocess
import sys
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.profiles import ProfileInUseError, display_name, ensure_profile_free, resolve_profile  # noqa: E402

LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com/?hl=ko"


def find_chrome() -> str | None:
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as k:
                path = winreg.QueryValue(k, None)
                if path and Path(path).exists():
                    return path
        except OSError:
            pass
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            path = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if path.exists():
                return str(path)
    return None


def main() -> int:
    if len(sys.argv) != 2:
        print("사용법: python scripts/setup_profile.py <name>   (예: youtube1)")
        return 2
    name = sys.argv[1]
    try:
        profile_dir = resolve_profile(name)
    except ValueError as e:
        print(f"오류: {e}")
        return 2

    chrome = find_chrome()
    if not chrome:
        print("오류: 설치된 Chrome(chrome.exe)을 찾지 못했습니다.")
        return 1

    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        ensure_profile_free(profile_dir)
    except ProfileInUseError as e:
        print(f"오류: {e}")
        return 1

    print(f"[{display_name(profile_dir.name)}] Chrome 실행: {profile_dir}")
    print("구글 계정으로 로그인한 뒤, Chrome 창을 닫으면 종료됩니다.")
    proc = subprocess.Popen([
        chrome,
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--lang=ko",
        LOGIN_URL,
    ])
    proc.wait()
    print(f"[{display_name(profile_dir.name)}] Chrome 종료됨. 프로필 저장 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

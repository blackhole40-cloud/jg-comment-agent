"""Chrome 프로필 경로/표시명/사용중 여부 헬퍼 (playwright 의존 없음)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES_DIR = ROOT / "profiles"

# 폴더명(ASCII) -> 화면 표시명
DISPLAY_NAMES = {
    "youtube1": "유튜브1",
    "youtube2": "유튜브2",
    "youtube3": "유튜브3",
}

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class ProfileInUseError(RuntimeError):
    pass


def display_name(name: str) -> str:
    return DISPLAY_NAMES.get(name, name)


def resolve_profile(name_or_path: str) -> Path:
    """'youtube1' 같은 이름이면 profiles/<name>, 경로면 그대로 사용."""
    p = Path(name_or_path)
    if p.is_absolute() or len(p.parts) > 1:
        return p.resolve()
    if not _NAME_RE.match(name_or_path):
        raise ValueError(f"프로필 이름은 ASCII 영문/숫자/_/- 만 가능합니다: {name_or_path!r}")
    return PROFILES_DIR / name_or_path


def is_profile_in_use(profile_dir: Path) -> bool:
    """Windows Chrome은 실행 중 <user-data-dir>/lockfile 을 배타적으로 열어둔다.
    파일이 있는데 열 수 없으면 해당 프로필의 Chrome이 실행 중인 것으로 판단."""
    lock = Path(profile_dir) / "lockfile"
    if not lock.exists():
        return False
    try:
        with open(lock, "a"):
            pass
        return False
    except OSError:
        return True


def ensure_profile_free(profile_dir: Path) -> None:
    if is_profile_in_use(profile_dir):
        raise ProfileInUseError(
            f"프로필 '{Path(profile_dir).name}' 의 Chrome 창이 이미 실행 중입니다. "
            f"해당 Chrome 창을 모두 닫은 뒤 다시 실행하세요. ({profile_dir})"
        )

"""실험 기록의 JSON 저장. 불완전한 JSON이 완료 파일처럼 보이지 않게 한다."""
import json
import os
import tempfile
from pathlib import Path


def write_json(path: Path, value, *, replace: bool = False) -> None:
    """같은 디렉터리 임시 파일에 다 쓴 다음 완성된 파일을 공개한다.

    기본은 덮어쓰기 금지다. manifest/state 갱신만 replace=True를 사용한다.
    no-replace에서는 hard link 생성으로 경쟁 상황에서도 기존 파일을 보존한다.
    이 함수의 atomic 보장은 개별 JSON 파일 단위이며 전체 실행 트랜잭션은 아니다.
    """
    path = Path(path)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".pending-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

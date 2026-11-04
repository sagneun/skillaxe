"""모델 호출의 입력·출력을 기록한다. SQL 생성과 두 단계 judge가 함께 사용한다."""
from copy import deepcopy
from time import monotonic
from uuid import uuid4

from .contracts import CallRecord, ChatClient, content_hash


def recorded_call(client: ChatClient, messages: list[dict[str, str]], stage: str, *, response_schema: dict | None = None) -> CallRecord:
    """실패도 기록으로 반환한다. 실패한 호출을 성공 응답이나 0점으로 바꾸지 않는다.

    예외의 원문에는 서버 URL, 인증 정보가 들어갈 수 있어 타입만 저장한다.
    요청 메시지는 별도로 보존해 대시보드에서 judge가 실제 본 증거를 확인한다.
    """
    saved = deepcopy(messages)
    start = monotonic()
    response, error_type = None, None
    try:
        response = client.complete_json(deepcopy(saved),response_schema) if response_schema is not None and hasattr(client,'complete_json') else client.complete(deepcopy(saved))
        if not isinstance(response, str):
            raise TypeError("model response must be text")
    except Exception as exc:
        error_type = type(exc).__name__
        response = None
    return CallRecord(call_id=str(uuid4()), stage=stage, settings=client.settings,
                      messages=saved, prompt_hash=content_hash(saved),
                      status="error" if error_type else "success", response=response,
                      error_type=error_type, elapsed_seconds=monotonic() - start, response_schema=deepcopy(response_schema))

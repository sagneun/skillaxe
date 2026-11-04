"""실험 참여자들이 주고받는 데이터의 약속(data contract).

읽는 순서: TaskInput → SkillVersion → ExecutionEvidence → Trace.
TaskInput에는 정답 필드가 아예 없다. 원본 dict를 전달하지 않고 허용한 값만
새 객체로 옮기는 것이 진단과 외부 정답 채점을 분리하는 첫 번째 경계다.
frozen=True는 실험 도중 식별자나 조건을 우연히 재대입하지 못하게 한다.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol

from llm.providers import ModelSettings


def content_hash(value: Any) -> str:
    """키 순서에 무관한 JSON 해시. NaN을 금지해 다른 도구에서도 읽을 수 있게 한다."""
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def require_text(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")


@dataclass(frozen=True)
class TaskInput:
    task_id: str
    question: str
    db_id: str
    schema: str

    def __post_init__(self):
        for name, value in asdict(self).items():
            require_text(name, value)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> TaskInput:
        """gold를 '삭제'하지 않고 네 필드만 복사한다.

        원본에 나중에 correctness, mismatch, 새로운 평가 필드가 추가되어도
        여기서 선택하지 않았으므로 진단 입력에는 들어오지 않는다. id는 기존
        starter의 이름이며 task_id는 새 실험의 이름이다. 값의 자동 문자열
        변환은 하지 않는다(잘못된 입력을 정상적인 질문처럼 숨기지 않기 위해).
        """
        return cls(task_id=record.get("task_id", record.get("id")),
                   question=record.get("question"), db_id=record.get("db_id"), schema=record.get("schema"))

    @property
    def input_hash(self) -> str:
        return content_hash(asdict(self))


@dataclass(frozen=True)
class SkillVersion:
    """한 번 생성해 동결한 L0 또는 사용자가 제공한 스킬. 개선 L1은 후속 단계다.

    해시는 본문뿐 아니라 description/적용·제외 조건도 포함한다. 따라서 어느
    문장이라도 달라지면 같은 스킬을 사용했다고 잘못 기록하지 않는다.
    """
    skill_id: str
    version: str
    description: str
    body: str
    applies_when: tuple[str, ...] = ()
    avoid_when: tuple[str, ...] = ()
    parent_hash: str | None = None

    def __post_init__(self):
        for name in ("skill_id", "version", "description", "body"):
            require_text(name, getattr(self, name))
        for name in ("applies_when", "avoid_when"):
            values = getattr(self, name)
            if not isinstance(values, (list, tuple)):
                raise ValueError(f"{name} must be a list of phrases")
            for value in values:
                require_text(name, value)
            object.__setattr__(self, name, tuple(values))

    @property
    def content_hash(self) -> str:
        return content_hash(asdict(self))

    def render(self) -> str:
        """JSON을 기준 데이터로 두고 에이전트가 읽을 자연어 표현을 만든다."""
        parts = [f"# {self.skill_id}", self.description]
        if self.applies_when:
            parts.append("Apply when:\n" + "\n".join(f"- {p}" for p in self.applies_when))
        if self.avoid_when:
            parts.append("Avoid when:\n" + "\n".join(f"- {p}" for p in self.avoid_when))
        return "\n\n".join([*parts, self.body])


@dataclass(frozen=True)
class ExecutionPolicy:
    """비교 조건 모두에 동일하게 적용하는 실행 제한. row_limit은 정답 개수가 아니다."""
    timeout_seconds: float = 5.0
    row_limit: int = 5
    max_cell_chars: int = 2000

    def __post_init__(self):
        for name in ("row_limit", "max_cell_chars"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        value = self.timeout_seconds
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("timeout_seconds must be finite and positive")




class ChatClient(Protocol):
    """LLM을 교체할 수 있는 최소 인터페이스. 테스트에서는 네트워크만 대체한다."""
    settings: ModelSettings

    def complete(self, messages: list[dict[str, str]]) -> str: ...


@dataclass(frozen=True)
class CallRecord:
    call_id: str
    stage: str
    settings: ModelSettings
    messages: list[dict[str, str]]
    prompt_hash: str
    status: str
    response: str | None
    error_type: str | None
    elapsed_seconds: float
    # 기존 provider는 응답 텍스트만 반환한다. 모르는 토큰 수를 0으로 만들지 않는다.
    usage: dict | None = None
    cache_hit: bool = False


@dataclass(frozen=True)
class ExecutionEvidence:
    """success = SQL이 실행됐다는 관찰일 뿐, 정답 SQL이라는 의미는 아니다.

    rows는 최대 row_limit개의 표본이다. rows_truncated가 True이면 전체 결과를
    보지 못했다. cells_truncated는 긴 문자열/BLOB 일부를 잘랐음을 뜻한다.
    이 두 제한은 judge의 uncertainty 판단과 향후 화면에 그대로 전달한다.
    """
    status: str
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    rows_truncated: bool
    cells_truncated: bool
    error: str | None
    policy: ExecutionPolicy
    elapsed_seconds: float


@dataclass(frozen=True)
class SQLExecutionRecord:
    """기존 execute 노드가 실행한 SQL과 그 관찰. fix가 있으면 여러 개가 생긴다."""
    sql: str
    evidence: ExecutionEvidence


@dataclass(frozen=True)
class Trace:
    """한 조건의 독립 실행. 같은 SQL이 나와도 trace_id는 서로 달라야 한다.

    agent_calls/execution_steps는 전체 기록, agent_call/execution은 마지막
    호출과 최종 SQL의 실행 증거다. 생성 전 graph가 실패하면 agent_call=None이다.
    node_order는 우리가 예상한 순서가 아니라 GRAPH.stream에서 관찰한 완료 노드다.
    """
    trace_id: str
    task_id: str
    input_hash: str
    db_hash: str
    condition: str
    replicate: int
    skill_hash: str | None
    config_hash: str
    status: str
    sql: str
    agent_call: CallRecord | None
    execution: ExecutionEvidence | None
    agent_calls: tuple[CallRecord, ...] = ()
    execution_steps: tuple[SQLExecutionRecord, ...] = ()
    node_order: tuple[str, ...] = ()
    engine: str = "sql_agent.run.GRAPH"
    agent_source_hash: str | None = None
    graph_error_type: str | None = None

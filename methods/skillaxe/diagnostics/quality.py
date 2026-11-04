"""논문 §3.1: Quality(s, task) = 방향 d × 변화 크기 m.

이 점수는 gold SQL과 비교한 정답률이 아니다. 같은 문제의 두 실행을 LLM이
상대적으로 평가한 값이다. 첫 호출은 선호 방향만, 두 번째 호출은 그 방향을
고정한 채 크기만 판단한다. A/B가 뒤집혀도 양수는 항상 '스킬이 도움됨'이다.
프롬프트는 논문이 공개한 원문이 아니라 §3.1을 구현하기 위한 자체 선택이다.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..calls import recorded_call
from ..contracts import CallRecord, ChatClient, TaskInput, Trace, require_text


@dataclass(frozen=True)
class QualityDiagnostic:
    """향후 대시보드가 사용할 원자료. 점수와 그 근거를 함께 남긴다.

    unavailable이면 score=None이다. API/파싱 실패를 tie(0점)로 바꾸지 않는다.
    두 번째 호출만 실패하면 첫 호출의 direction과 evidence는 보존한다.
    presentation은 A/B를 원래 trace/조건으로 되돌리는 지도이며 judge에게는
    보여주지 않는다. calls에는 실제 제시 순서와 프롬프트 해시도 남는다.
    """
    diagnosis_id: str
    metric: str
    rubric_version: str
    skill_hash: str
    task_ids: tuple[str, ...]
    trace_refs: tuple[str, ...]
    seed: int
    presentation: dict[str, dict[str, str]]
    status: str
    preference: str | None
    direction: int | None
    magnitude: float | None
    score: float | None
    direction_evidence: str | None
    magnitude_evidence: str | None
    uncertainty: bool
    uncertainty_reasons: tuple[str, ...]
    error: str | None
    calls: tuple[CallRecord, ...]


def _validate_pair(task: TaskInput, baseline: Trace, with_skill: Trace) -> None:
    """비교할 수 없는 실행은 judge를 부르기 전에 거부한다(0점 처리하지 않는다)."""
    if baseline.condition != "no_skill" or baseline.skill_hash is not None:
        raise ValueError("baseline must be the no-skill condition")
    if not with_skill.skill_hash or with_skill.condition == "no_skill":
        raise ValueError("with_skill must reference an assigned skill")
    if baseline.trace_id == with_skill.trace_id:
        raise ValueError("conditions must have independent trace IDs")
    for trace in (baseline, with_skill):
        if trace.task_id != task.task_id or trace.input_hash != task.input_hash:
            raise ValueError("trace does not match this task input")
    for field in ("replicate", "db_hash", "config_hash", "engine", "agent_source_hash"):
        if getattr(baseline, field) != getattr(with_skill, field):
            raise ValueError(f"paired traces differ in {field}")


def _judge_evidence(trace: Trace) -> dict:
    """Trace 전체를 직렬화하지 않는다. 스킬 유무·모델 응답 설명을 숨긴다.

    모델이 '성공했다'고 주장한 원문 대신 실제 SQL/실행 결과만 전달한다.
    실행 시간이나 condition 이름은 선호 판단에 불필요한 단서를 주므로 제외한다.
    """
    evidence = {"sql": trace.sql, "status": trace.status, "execution": None}
    if trace.execution is not None:
        result = trace.execution
        evidence["execution"] = {
            "status": result.status, "columns": result.columns, "rows": result.rows,
            "rows_truncated": result.rows_truncated, "cells_truncated": result.cells_truncated,
            "row_limit": result.policy.row_limit, "max_cell_chars": result.policy.max_cell_chars,
            "error": result.error,
        }
    return evidence


def _messages(stage: str, payload: dict) -> list[dict[str, str]]:
    prompt = Path(__file__).resolve().parents[1] / "prompts" / f"quality_{stage}.md"
    return [{"role": "system", "content": prompt.read_text(encoding="utf-8")},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False)}]


def _parse(record: CallRecord, field: str) -> dict:
    """JSON 형태만 맞는 응답도 값 범위를 검증한다. 문자열 'false'는 bool이 아니다."""
    if record.status != "success":
        raise ValueError("model_call_failed")
    try:
        value = json.loads(record.response)
    except (ValueError, TypeError):
        raise ValueError("invalid_json") from None
    required = {field, "evidence", "uncertainty", "uncertainty_reason"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("invalid_response_fields")
    require_text("evidence", value["evidence"])
    if type(value["uncertainty"]) is not bool or not isinstance(value["uncertainty_reason"], str):
        raise ValueError("invalid_uncertainty")
    if value["uncertainty"]:
        require_text("uncertainty_reason", value["uncertainty_reason"])
    elif value["uncertainty_reason"]:
        raise ValueError("unexpected_uncertainty_reason")
    if field == "preference":
        if value[field] not in ("A", "B", "tie"):
            raise ValueError("invalid_preference")
    else:
        number = value[field]
        # bool은 Python에서 int의 하위 타입이므로 isinstance(number, int)만으로
        # 검사하면 true를 magnitude=1로 잘못 받아들인다. 정확한 타입을 검사한다.
        # 범위를 먼저 검사하면 JSON의 매우 큰 정수를 float로 바꾸다가 발생하는
        # OverflowError도 피할 수 있다. 범위 밖 값은 언제나 invalid 응답이다.
        if type(number) not in (int, float) or not 0 <= number <= 1 or not math.isfinite(number):
            raise ValueError("invalid_magnitude")
    return value


def diagnose_quality(task: TaskInput, baseline: Trace, with_skill: Trace, judge: ChatClient,
                     *, seed: int = 0) -> QualityDiagnostic:
    """두 실행을 무작위로 제시하고, 방향과 크기를 분리해 계산한다.

    seed는 제시 순서 재현용이다. 모델의 생성 난수나 DB 실행 순서를 통제하지
    않는다. tie이면 d=0이어서 m을 평가할 필요가 없으므로 2번째 호출을 생략한다.
    이는 비용을 줄이기 위한 구현 선택이며 m=0, score=0을 명시적으로 기록한다.
    """
    _validate_pair(task, baseline, with_skill)
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    ordered = [baseline, with_skill]
    random.Random(seed).shuffle(ordered)
    presentation = {label: {"trace_id": trace.trace_id, "condition": trace.condition}
                    for label, trace in zip(("A", "B"), ordered)}
    # TaskInput에는 gold가 없지만 judge 입력은 여기서도 필요한 필드만 선택한다.
    payload = {"task": {"question": task.question, "schema": task.schema},
               "responses": {label: _judge_evidence(trace) for label, trace in zip(("A", "B"), ordered)}}
    calls, reasons = [], []
    preference = direction = magnitude = score = None
    direction_evidence = magnitude_evidence = error = None
    stage = "direction"
    try:
        # SQL을 실제 생성한 뒤 실행이 실패한 것은 에이전트 행동의 관찰이다.
        # 반면 인증/네트워크 등으로 생성 호출 자체가 실패했다면 비교할 산출물이
        # 없다. 그런 장애를 스킬의 효과로 채점하지 않고 judge 호출도 생략한다.
        if any(trace.status == "agent_error" for trace in (baseline, with_skill)):
            raise ValueError("agent_graph_failed")
        if any(trace.agent_call is None or trace.agent_call.status != "success"
               or any(call.status != "success" for call in trace.agent_calls)
               for trace in (baseline, with_skill)):
            raise ValueError("generation_call_failed")
        first = recorded_call(judge, _messages(stage, payload), "quality_direction")
        calls.append(first)
        decision = _parse(first, "preference")
        preference, direction_evidence = decision["preference"], decision["evidence"]
        if decision["uncertainty"]:
            reasons.append(decision["uncertainty_reason"])
        if preference == "tie":
            direction, magnitude, score = 0, 0.0, 0.0
        else:
            # A가 이겼다는 것 자체는 양수가 아니다. A가 어느 조건인지 매핑해야 한다.
            winner_id = presentation[preference]["trace_id"]
            direction = 1 if winner_id == with_skill.trace_id else -1
            stage = "magnitude"
            second_payload = {**payload, "preferred": preference, "direction_evidence": direction_evidence}
            second = recorded_call(judge, _messages(stage, second_payload), "quality_magnitude")
            calls.append(second)
            strength = _parse(second, "magnitude")
            magnitude = float(strength["magnitude"])
            magnitude_evidence = strength["evidence"]
            score = direction * magnitude
            if strength["uncertainty"]:
                reasons.append(strength["uncertainty_reason"])
    except ValueError as exc:
        # 파싱/호출 오류에는 점수를 부여하지 않는다. 원 응답은 calls에 보존되어
        # 형식 오류와 모델 호출 실패를 나중에 구별할 수 있다.
        error = f"{stage}: {exc}"
        reasons.append("Diagnosis unavailable; inspect the recorded judge call.")
    return QualityDiagnostic(
        diagnosis_id=str(uuid4()), metric="quality_impact", rubric_version="quality-v1",
        skill_hash=with_skill.skill_hash, task_ids=(task.task_id,),
        trace_refs=(baseline.trace_id, with_skill.trace_id), seed=seed, presentation=presentation,
        status="unavailable" if error else "available", preference=preference, direction=direction,
        magnitude=magnitude, score=score, direction_evidence=direction_evidence,
        magnitude_evidence=magnitude_evidence, uncertainty=bool(reasons),
        uncertainty_reasons=tuple(reasons), error=error, calls=tuple(calls))

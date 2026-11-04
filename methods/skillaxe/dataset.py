"""기존 문제 형식과 스키마 추출기를 정답 없는 TaskInput으로 연결한다.

원본 데이터 파일을 수정하지 않고 지정한 ID만 선택한다. 정답 여부나 오답
유형으로 사례를 고르지 않는다. 기존 schema_text의 테이블/열/FK 표현을 그대로
사용하므로 스키마 포맷을 별도로 구현하거나 사람이 옮겨 적을 필요가 없다.
"""
from __future__ import annotations

import json
from pathlib import Path

from sql_agent.schema import schema_text

from .contracts import TaskInput, require_text

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _check_source(path: Path) -> None:
    """문제 파일뿐 아니라 스키마 경로로 잘못 지정한 경우에도 읽기 전에 막는다."""
    if path.resolve() == (PROJECT_ROOT / "data/test.json").resolve():
        raise ValueError("official test data must not be used for SkillAxe diagnostics")


def load_task(path: Path, *, task_id: str | None = None, tables_path: Path | None = None) -> TaskInput:
    """준비된 단일 객체 또는 기존 문제 목록에서 한 문제를 읽는다.

    목록 입력은 반드시 task_id를 지정한다. '첫 문제'를 몰래 선택하지 않으며
    중복 ID도 거부한다. tables_path를 지정하면 해당 카탈로그가 스키마의 기준이다.
    지정하지 않으면 준비된 schema를 쓰고, schema가 없을 때만 프로젝트의 기존
    data/tables.json을 사용한다. 공식 test 파일은 읽기 전에 명시적으로 거부한다.
    """
    path = Path(path)
    _check_source(path)
    if task_id is not None:
        require_text("task_id", task_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        if task_id is None:
            raise ValueError("task_id is required when the input contains a list of tasks")
        if not all(isinstance(item, dict) for item in raw):
            raise ValueError("every task must be a JSON object")
        matches = [item for item in raw if item.get("task_id", item.get("id")) == task_id]
        if len(matches) != 1:
            raise ValueError("task_id must match exactly one task")
        record = matches[0]
    elif isinstance(raw, dict):
        record = raw
        if task_id is not None and record.get("task_id", record.get("id")) != task_id:
            raise ValueError("task_id does not match the supplied task")
    else:
        raise ValueError("task input must be a JSON object or list")

    # 원본 객체를 수정하거나 그대로 넘기지 않는다. gold_sql, correctness,
    # mismatch 같은 필드가 원본에 있어도 아래 네 값 외에는 가져오지 않는다.
    selected_id = record.get("task_id", record.get("id"))
    question, db_id = record.get("question"), record.get("db_id")
    for name, value in (("task_id", selected_id), ("question", question), ("db_id", db_id)):
        require_text(name, value)
    schema = record.get("schema")
    if tables_path is not None or schema is None or schema == "":
        catalog = Path(tables_path) if tables_path is not None else PROJECT_ROOT / "data/tables.json"
        _check_source(catalog)
        try:
            schema = schema_text(str(catalog.resolve()), db_id)
        except KeyError as exc:
            raise ValueError("database or required schema fields are absent from the catalog") from exc
    return TaskInput(task_id=selected_id, question=question, db_id=db_id, schema=schema)

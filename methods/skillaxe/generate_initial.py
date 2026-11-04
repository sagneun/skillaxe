"""SkillsBench 기반 초기 L0 한 번 생성. SQL 실행·평가·개선은 수행하지 않는다.

generate_initial_skill은 입력 TaskInput만 받는다. 원본 문제 객체나 정답 SQL을
생성 프롬프트에 넘길 수 없게 하고, 결과 폴더가 있으면 API 호출 전에 중단한다.
한 번 얻은 문서는 형식만 검사하며 사람이 본문을 보정하거나 다시 생성하지 않는다.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path

from .calls import recorded_call
from llm.providers import Client
from .contracts import ChatClient, SkillVersion, TaskInput, require_text
from .dataset import load_task
from .records import write_json

SOURCE = "https://arxiv.org/html/2602.12670v1#A3.SS6"
ADAPTATIONS = [
    "Paraphrased SkillsBench C.6 authoring instructions; not a verbatim prompt reproduction.",
    "Generate one SQLite Text-to-SQL skill, instead of 1–5 skills across arbitrary domains.",
    "Use preselected development questions and schemas; do not solve tasks or receive grading feedback.",
    "Return description/body JSON; application saves Markdown rather than asking the model to write files.",
    "Separate generation from later independent No-skill/L0 agent executions.",
]


def generate_initial_skill(tasks: list[TaskInput], client: ChatClient, output: Path,
                           *, skill_id: str = "sqlite-text-to-sql",
                           selection_policy: str = "Explicit task IDs selected before generation") -> SkillVersion:
    """한 번의 모델 응답을 저장한다. 재시도·자동 교정·후보 선별은 하지 않는다."""
    require_text("skill_id", skill_id)
    if not tasks or not all(isinstance(task, TaskInput) for task in tasks):
        raise ValueError("generation requires nonempty TaskInput examples")
    if len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError("generation task IDs must be unique")
    prompt = (Path(__file__).parent / "prompts/initial_skill.md").read_text(encoding="utf-8")
    payload = {"skill_scope": "Reusable SQLite Text-to-SQL procedures",
               "development_tasks": [asdict(task) for task in tasks]}
    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False)}]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": "skillaxe-initial-generation-v1", "status": "generating",
        "created_at": datetime.now(timezone.utc).isoformat(), "mode": client.settings.mode,
        "skill_id": skill_id, "version": "L0", "source_url": SOURCE, "adaptations": ADAPTATIONS,
        "selection_policy": selection_policy, "input_task_ids": [task.task_id for task in tasks],
        "input_hashes": {task.task_id: task.input_hash for task in tasks},
        "model_settings": asdict(client.settings), "generation_calls": 0, "call": None,
    }
    write_json(output / "generation.json", record)
    write_json(output / "inputs.json", payload)
    (output / "generation_prompt.md").write_text(prompt, encoding="utf-8")
    try:
        call = recorded_call(client, messages, "initial_skill_generation")
        metadata = getattr(client, "response_metadata", {})
        call = replace(call, usage=metadata.get("usage"))
        record.update({"generation_calls": 1, "call": asdict(call), "provider_response": metadata})
        # 검증보다 먼저 원 응답을 저장한다. 잘린 JSON이나 API 실패도 보존하며
        # 모델에게 자동으로 '다시 써 달라'고 요청하지 않는다.
        write_json(output / "generation.json", record, replace=True)
        if call.status != "success":
            raise ValueError(f"initial generation call failed: {call.error_type}")
        if metadata.get("finish_reason") not in (None, "stop"):
            raise ValueError("initial generation did not finish normally")
        value = json.loads(call.response)
        if not isinstance(value, dict) or set(value) != {"description", "body"}:
            raise ValueError("initial skill response must contain only description and body")
        skill = SkillVersion(skill_id=skill_id, version="L0", **value)
        write_json(output / "L0.json", {**asdict(skill), "content_hash": skill.content_hash})
        # JSON이 기준 데이터다. Markdown의 본문은 모델 출력 그대로이며, YAML
        # 이름/설명 포장만 추가한다. JSON 문자열은 YAML에서도 안전한 scalar다.
        markdown = (f"---\nname: {json.dumps(skill.skill_id)}\n"
                    f"description: {json.dumps(skill.description, ensure_ascii=False)}\n---\n\n{skill.body}\n")
        (output / "SKILL.md").write_text(markdown, encoding="utf-8")
        record.update({"status": "frozen", "content_hash": skill.content_hash})
        write_json(output / "generation.json", record, replace=True)
        return skill
    except Exception as exc:
        record.update({"status": "failed", "error_type": type(exc).__name__})
        write_json(output / "generation.json", record, replace=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate and freeze one L0 skill with one model request")
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--task-id", action="append", required=True)
    parser.add_argument("--tables", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--skill-id", default="sqlite-text-to-sql")
    parser.add_argument("--selection-policy", default="Explicit task IDs selected before generation")
    args = parser.parse_args(argv)
    try:
        if args.out.exists():
            raise FileExistsError("output already exists; generation will not be repeated")
        tasks = [load_task(args.tasks, task_id=task_id, tables_path=args.tables) for task_id in args.task_id]
        from loop.env import load_env
        load_env()
        client = Client(role="agent", max_tokens=4096, single_request=True)
        skill = generate_initial_skill(tasks, client, args.out, skill_id=args.skill_id,
                                       selection_policy=args.selection_policy)
        print(json.dumps({"status": "frozen", "skill": str(args.out / "L0.json"),
                          "content_hash": skill.content_hash, "generation_calls": 1}, ensure_ascii=False))
        return 0
    except (ValueError, TypeError, OSError) as exc:
        # API 예외 원문은 recorded_call에서 숨긴다. 여기에는 우리 입력/형식 오류만 온다.
        parser.exit(2, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

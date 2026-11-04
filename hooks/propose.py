"""후보 patch를 몇 개 어떻게 만들지. 기본: LLM 1회 호출, patch 1개."""
from __future__ import annotations
from loop.context import RoundContext
from loop.patch import Patch, parse_patch
from uuid import uuid4
from methods.skillaxe.records import write_json


def propose(ctx: RoundContext, messages: list[dict]) -> list[Patch]:
    if ctx.config.get("target_kind") == "skill":
        return propose_skill(ctx, messages)
    p = parse_patch(ctx.llm(messages, role="improver", max_tokens=ctx.config.get("improver_max_tokens", 4096)))
    return [p] if p else []


def propose_skill(ctx,messages):
    record={'messages':messages,'status':'running','response':None,'error_type':None}
    target=ctx.skillaxe_output/'refiner'/f'{uuid4().hex}.json' if hasattr(ctx,'skillaxe_output') else None
    if target: write_json(target,record)
    try:
        response=ctx.llm(messages,role='improver',max_tokens=ctx.config.get('improver_max_tokens',4096))
        record.update(status='success',response=response)
        return [Patch('skill',response,'SkillAxe diagnostic-guided refinement')]
    except Exception as exc:
        record.update(status='failed',error_type=type(exc).__name__)
        raise
    finally:
        if target: write_json(target,record,replace=True)

"""후보를 적용 전에 검토하는 hook. 현재는 그대로 통과하며 최종 판정은 기존 kernel이 수행한다."""
from __future__ import annotations
from loop.context import RoundContext
from loop.patch import Patch


def review_patch(ctx: RoundContext, patch: Patch) -> Patch | None:
    return patch

"""screen 평가 점수가 screen_drop보다 많이 떨어지면 full 평가 전에 중단한다."""
from __future__ import annotations
from loop.context import RoundContext


def after_screen(ctx: RoundContext, screen_before: int, screen_after: int) -> bool:
    return screen_after >= screen_before - ctx.config["screen_drop"]

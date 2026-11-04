install:
	uv sync

check:   # LLM 비용 없이 설치를 확인: self-check + mock 2 round (별도 git worktree, 자기 logs/는 안 건드림)
	uv run python -m loop.kernel
	uv run python -m loop.patch
	uv run python -m loop.archive
	uv run python -m loop.meta selfcheck
	uv run python -m llm.providers
	uv run python -m scripts.operator.make_splits selfcheck
	uv run python -m scripts.operator.make_catalog selfcheck
	@T=$$(mktemp -d) && git worktree add --quiet -B _rsi_check "$$T" HEAD && \
	cp -R hooks config.yaml "$$T"/ && cp -R loop/prompts "$$T"/loop/ && { [ ! -d methods ] || cp -R methods "$$T"/; } && \
	(cd "$$T" && LLM_BACKEND=mock LLM_BASE_URL=x LLM_MODEL=mock RULER_OVERRIDE=1 uv run python -m loop.run --rounds 2); rc=$$?; \
	git worktree remove --force "$$T"; git branch -D -q _rsi_check; \
	exit $$rc
	@echo "check ok"

test:
	uv run python -m scripts.test_eval --runs 3

round:
	uv run python -m loop.run --rounds $(or $(N),20)

# SkillAxe 전용 명령. 기존 starter의 round/test 명령은 유지한다.
skillaxe-round:
	uv run --frozen --extra skillaxe python -m loop.run --config $(or $(CONFIG),methods/skillaxe/configs/loop.yaml) --rounds $(or $(N),1)

skillaxe-eval:
	uv run --frozen --extra skillaxe python -m methods.skillaxe.evaluate_skill --config $(or $(CONFIG),methods/skillaxe/configs/loop.yaml) --split validation --condition $(or $(CONDITION),candidate) $(if $(RUN),--run $(RUN)) $(if $(filter 1,$(RECOVER)),--recover-candidate)

skillaxe-test:
	uv run --frozen --extra skillaxe python -m methods.skillaxe.evaluate_skill --config $(or $(CONFIG),methods/skillaxe/configs/loop.yaml) --split test $(if $(RUN),--run $(RUN))

results:
	uv run python -m scripts.results --week $(W) --config $(or $(CONFIG),methods/skillaxe/configs/loop.yaml)

ruler:   # 운영자만: 지금 commit을 고정 파일의 기준으로. loop/kernel.py의 RULER_TAG 번호를 올린 뒤 실행 (tag를 origin에 push)
	T=$$(uv run python -c "from loop.kernel import RULER_TAG; print(RULER_TAG)"); git tag -f $$T && git push -f origin $$T && echo "tagged $$T"

meta-propose:
	uv run python -m loop.meta propose

meta-eval:
	uv run python -m loop.meta eval $(if $(FILE),--file $(FILE)) $(if $(N),--n $(N)) $(if $(SEED),--seed $(SEED))

meta-adopt:
	uv run python -m loop.meta adopt $(if $(FILE),--file $(FILE)) $(if $(filter 1 true yes,$(FORCE)),--force --reason "$(REASON)")

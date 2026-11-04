# SkillAxe: 기존 SQL 에이전트와 loop에 네 진단축 연결

실험의 주 실행기는 기존 `loop/run.py`다. SkillAxe는 진단과 스킬 수정 방법을 제공하며, 최종 채점·kernel accept·champion 관리는 기존 코드를 사용한다.

## 1. 코드 읽는 순서

```text
loop/run.py begin
  → parent 스킬 복원 / 기존 evaluator로 기준 성능 측정
  → hooks/diagnose.py
      → diagnose_round(): 실행 증거 수집과 네 진단 호출
          → 기존 SQL agent GRAPH로 No-skill / 현재 스킬 실행
          → Quality / Trigger / Compliance / Coverage
          → brief.py: 네 진단을 근거·보존 지침으로 묶기
  → hooks/build_prompt.py: 현재 스킬 + 브리핑으로 Refiner 요청 작성
  → hooks/propose.py: 공통 llm 호출로 수정 스킬 후보 생성
  → loop precheck / review / apply: 문서 검사 / 기본 통과 / 후보 저장
  → 기존 screen / full / kernel_accept / champion / 로그
```

| 코드 | 역할 |
|---|---|
| `sql_agent/run.py` | `run_with_skill()`로 스킬 적용·GRAPH 실행·증거 수집. SQL 도구와 병렬 실행 격리도 이 파일에서 처리 |
| `hooks/diagnose.py` | 진단 작업 선택·실행·네 축 호출·기록 |
| `hooks/build_prompt.py`, `hooks/propose.py` | 브리핑으로 수정 요청 구성·후보 생성·호출 기록 |
| `diagnostics/quality.py` | 무작위 A/B 방향과 크기, d×m |
| `diagnostics/trigger.py` | dependency parser로 문구·부정 범위 추출, 세 거리 계산 |
| `diagnostics/compliance.py` | 작업을 숨긴 규칙 추출 → 작업별 준수·품질·책임 판정 |
| `diagnostics/coverage.py` | 스킬을 숨긴 경로 후보 생성 → 문단별 임베딩 유사도 |
| `diagnostics/suite.py` | 네 진단의 공통 호출과 실패 차단 |
| `embeddings.py` | 두 진단이 공유하는 실제 임베딩과 설정·텍스트 해시 캐시 |
| `brief.py` | 네 진단의 근거와 보존 지침을 브리핑으로 정리 |
| `skills.py` | 문서 로딩·내용 검증·버전/해시·후보 참조 검사 |
| `calls.py` → `llm/providers.py` | 모든 진단이 공유하는 호출 기록과 provider |

SQL 생성·fix·추출 노드의 EVOLVE-BLOCK은 변경하지 않았다. 새 연결은 실행 지원 코드에 있으며 kernel/evaluator/archive의 규칙도 변경하지 않았다. 독립 runner·데모·별도 모듈 로더와 실행용 어댑터 파일은 제거했다. 실행 기능은 SQL agent에, 방법론 연결은 각 hook에 통합했다. 테스트도 원본 에이전트를 직접 사용한다.

## 2. 설치와 설정

```bash
uv sync --frozen --extra skillaxe
```

선택 의존성은 spaCy, 영문 `en_core_web_sm` 3.8.0, sentence-transformers다. 기존 기본 실행은 이 선택 의존성을 필요로 하지 않는다. 임베딩 최초 실행은 모델 파일을 다운로드하며 유료 LLM API 호출과는 별개다.

`configs/loop.yaml`이 기존 loop용 예제다. 기본 `config.yaml`은 변경하지 않았다.

- 초기 생성에 사용했던 개발 ID 5개를 명시한다. 정답·오답으로 고르지 않는다.
- 임베딩 모델 revision은 변경 불가능한 commit SHA로 고정한다. 모델/문구 추출/α=.5/청크 1200자/overlap 0은 구현 선택이며 논문 전체 설정의 복원이라고 주장하지 않는다.
- 모델은 기존 `LLM_*`와 `IMPROVER_LLM_*` 환경변수를 사용한다.
- 진단과 최종 평가 모두 같은 `skillaxe.agent_max_tokens`, `sql_timeout_sec`를 전달한다.
- SkillAxe 실행은 `LLM_CACHE`가 켜져 있으면 거부한다. 임베딩 캐시는 텍스트+모델 설정 해시로 별도 관리한다.
- 초기 통합은 스킬 하나, task별 실행 1회다. 매 round 네 축 전체를 사용하며 축 생략 실험은 지원하지 않는다.

## 3. 활성 스킬과 실행

생성된 `skills/sqlite-text-to-sql-L0/L0.json`은 동결 원본이다. 수정 후보용 활성 파일을 별도로 준비한다.

```bash
cp methods/skillaxe/skills/sqlite-text-to-sql-L0/L0.json methods/skillaxe/skills/active.json
```

활성 파일은 loop 시작 parent에 존재해야 하므로 구현 변경과 함께 검토·commit한 뒤 시작한다. 코드는 자동으로 초기 스킬을 재생성하거나 사용자 변경을 commit하지 않는다. loop 실행 자체의 후보 commit/채택은 기존 Archive의 동작이다.

```bash
RULER_OVERRIDE=1 uv run --frozen --extra skillaxe python -m loop.run \
  --config methods/skillaxe/configs/loop.yaml --rounds 1
```

이 명령은 **실제 LLM 호출·후보 commit·최종 채택**을 수행한다. 초기 기준 평가와 screen/full 평가도 실행하므로 진단 5문제만의 비용이 아니다. 이번 통합에서는 `loop/run.py`를 작업자가 확장했으므로 기존 ruler 비교에 차이가 난다. kernel을 우회하도록 코드를 바꾸지 않았으며 명시적 override와 결과의 `ruler: override` 기록이 필요하다.

별도 archive/log는 `logs/skillaxe/archive.json`, `logs/skillaxe/rounds.jsonl`이다. 기존 코드 개선 실험의 archive와 섞지 않는다. 원래 `make test` 스크립트는 기본 config/archive/에이전트 CLI를 사용하므로 이 별도 스킬 모드의 공식 test 평가로 간주하면 안 된다. 이 구현에서는 loop의 validation 최종 평가까지 연결했으며 공식 test 경로는 변경·실행하지 않았다.

## 4. 판단에 사용하는 정보

- Quality: 질문·스키마, 두 조건의 SQL·실행 오류·열·행 표본. tie는 0, API 실패는 unavailable.
- Trigger: description와 명시적 applies_when/avoid_when의 noun phrase, 문장 문맥, 원문 위치. 부정의 dependency 범위를 추적한다. 본문의 일반 지침을 자동으로 적용 조건으로 간주하지 않는다.
- Compliance: 규칙별 관련성·severity·a/g/f/c·증거·증거 부족 표시. 관련 규칙만 집계하며 f=0인 규칙은 보존 지침으로 전달한다.
- Coverage: 질문·스키마·설정된 스킬 유형으로 제안한 경로와 본문 청크. 후보는 검증된 정답 경로가 아니고 cosine은 정답률이 아니다.

계산은 설계서 수식을 따른다. 부족한 문구/관련 규칙 없음은 이유가 있는 N/A다. API·파싱·임베딩 실패는 unavailable이며 하나라도 있으면 Refiner를 호출하지 않는다. 진단/Refiner는 gold·correctness·mismatch·채택 이력·전체 RoundContext를 입력으로 받지 않는다.

최종 후보 채택과 다음 parent 선택은 기존 정답 기반 정책이다. 따라서 이 통합 실험은 **정답 없이 스킬 수정안을 생성하고, 기존 kernel으로 채택하는 방식**이며 원래 독립 실험 설계의 ‘정답 기반 후보 선택 없음’과 구분한다.

## 5. 기록

```text
logs/skillaxe/round-<N>-<id>/
  manifest.json
  inputs/                    진단에 실제 사용한 gold 없는 입력
  skills/                    현재 스킬 원문
  traces/                    No-skill / 스킬의 실제 SQL·오류·결과 표본·노드·호출
  diagnostics/               네 진단별 점수·근거·실제 judge 요청/응답
  brief.json
  refiner/                   요청·응답 또는 실패 종류
  candidate.json             거절되어도 남는 수정 스킬
  revision.json              이전/새 해시, 브리핑·진단 참조와 수정 설명
  external_evaluation/
    parent/                  기준 예측·trace·채점 결과
    screen/                  후보 screen 평가
    candidate/               후보 full 평가 (screen 통과한 경우)
```

`external_evaluation`은 진단에서 읽지 않는다. parent/candidate 기록을 덮어쓰지 않는다. 거절되면 활성 파일은 기존 Archive가 복원하고 후보 문서·기록은 남는다. 무변경 후보는 재요청 없이 `no_change`로 끝난다. 형식 오류는 최대 1회 교정하며 review hook은 추가 LLM 심사를 하지 않는다.

자동 중간 단계 재개는 아직 없다. 실패한 round의 기록은 보존하고 새 실행에서 새 폴더를 만든다. SQL 표본은 잘림을 표시하며 실행 성공과 정답을 구분한다. 기존 SQL 추출기의 문자열 내부 세미콜론 처리 한계는 유지한다.

## 6. 비용 없는 검증

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --frozen --extra skillaxe python -m unittest discover -s methods/skillaxe/tests -v
```

테스트는 고정 벡터·모의 LLM·임시 SQLite로 수식과 전체 loop 연결을 검증한다. 기본 테스트는 인터넷·유료 LLM·공식 test 없이 동작하며 parser가 설치돼 있을 때 실제 dependency scope 회귀 테스트도 수행한다.

참고 API: [SentenceTransformer](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html), [spaCy dependency parsing](https://spacy.io/usage/linguistic-features#dependency-parse). 논문 진단 수식·Appendix G rubric은 제공된 `docs/skillaxe.pdf`를 기준으로 구현했다.

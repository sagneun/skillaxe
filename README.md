# SkillAxe · Text-to-SQL 스킬 개선

기존 SQL 에이전트에 스킬 문서를 적용하고, **네 진단축의 브리핑으로 다음 버전의 스킬을 만드는 프로젝트**다. 실행과 개선 반복은 기존 `sql_agent/run.py`와 `loop/run.py`를 사용한다.

개선 대상은 스킬 문서다. SkillAxe 모드의 Refiner는 에이전트 코드나 loop를 수정하지 않는다. 진단은 정답 없이 수정 근거를 만들고, 생성된 후보의 최종 채택은 기존 evaluator·kernel·champion 규칙으로 결정한다.

## 1. 디렉터리 구조

```text
skillaxe/
├── sql_agent/
│   ├── run.py                  기존 GRAPH 실행 + 스킬 주입 + 실행 증거 수집
│   └── schema.py               DB 스키마 구성
│
├── loop/
│   ├── run.py                  round 진행, 후보 검사·반영, screen/full 평가 연결
│   ├── kernel.py               고정 최종 accept 판정
│   ├── archive.py              후보 commit, parent 복원, champion 관리
│   └── patch.py                기존 코드 모드의 EVOLVE-BLOCK 처리
│
├── hooks/
│   ├── on_round_start.py       SkillAxe 모드의 개선 대상을 skill로 지정
│   ├── diagnose.py             진단 작업 선택 → 실행 증거 수집 → 네 축 → 브리핑
│   ├── build_prompt.py         현재 스킬과 브리핑으로 Refiner 입력 구성
│   ├── propose.py              수정 스킬 후보 생성, 호출 기록
│   ├── review_patch.py         현재는 후보를 그대로 통과
│   └── ...                    기존 선택·screen·accept·종료 hook
│
├── llm/
│   └── providers.py           에이전트·진단에서 공유하는 모델 호출
│
├── methods/skillaxe/
│   ├── diagnostics/
│   │   ├── suite.py            네 진단 실행과 실패 상태 집계
│   │   ├── quality.py          ① Quality Impact: 스킬 적용 전후 품질 비교
│   │   ├── trigger.py          ② Trigger: 적용·제외 조건의 범위와 경계
│   │   ├── compliance.py       ③ Compliance: 규칙 준수와 실패 책임
│   │   ├── coverage.py         ④ Coverage: 해결 경로와 스킬 내용의 대응
│   │   └── common.py           진단 공통 형식·JSON 응답 처리
│   ├── embeddings.py          Trigger·Coverage 공통 임베딩과 캐시
│   ├── brief.py               진단 결과를 수정 근거·보존 지침으로 정리
│   ├── skills.py              스킬 로딩, 문서 검증, 버전·해시·후보 참조 검사
│   ├── contracts.py           작업·스킬·호출·실행 증거의 공통 자료형
│   ├── calls.py               모델 요청·응답·실패 기록
│   ├── records.py             JSON 기록 저장
│   ├── dataset.py             진단 입력과 스키마 로딩
│   ├── generate_initial.py    초기 스킬 L0 생성
│   ├── prompts/               진단·초기 생성·수정 프롬프트
│   ├── configs/loop.yaml      SkillAxe 실행 설정
│   ├── skills/
│   │   ├── sqlite-text-to-sql-L0/  동결한 초기 스킬과 생성 근거
│   │   └── active.json        실행할 활성 스킬 (최초 준비 시 생성)
│   └── tests/                 수식·증거 수집·기존 loop 연결 테스트
│
├── evaluator/                 기존 최종 채점 코드
├── data/                      고정 데이터와 SQLite DB
├── config.yaml                기존 코드 개선 모드 설정
└── logs/skillaxe/              SkillAxe 실행 기록 (실행 시 생성)
```

실행용 별도 runner나 adapter는 없다. 스킬을 적용하고 SQL 실행 결과를 모으는 코드는 `sql_agent/run.py`에, 진단과 후보 생성 연결은 각 hook에 들어 있다. 진단축마다 별도의 LLM client를 만들지 않고 공통 provider를 사용한다.

## 2. 한 round의 흐름

```text
loop/run.py
  begin
    ├─ parent 스킬 복원
    └─ 기존 evaluator로 parent의 validation 성능 측정
  diagnose → hooks/diagnose.py
    ├─ 미리 지정한 작업에서 No-skill / 현재 스킬 실행
    ├─ Quality · Trigger · Compliance · Coverage 진단
    └─ brief.py로 브리핑 구성
  propose
    ├─ hooks/build_prompt.py: 현재 스킬 + 브리핑
    └─ hooks/propose.py: Refiner가 다음 스킬 후보 생성
  precheck → 후보 문서 형식·변경 여부·진단 참조 검사
  review   → 현재는 추가 심사 없이 통과
  apply    → 후보·수정 근거 저장, active.json 반영, 후보 commit
  screen   → validation 일부로 사전 평가
  full     → validation 전체 평가
  accept   → 기존 kernel 판정과 champion 규칙 적용
```

여기서 **후보**는 브리핑을 바탕으로 새로 생성한 다음 버전의 스킬이다. Refiner가 수정하는 문서 필드는 `description`, `applies_when`, `avoid_when`, `body`다. 버전·부모 해시 등 식별 정보는 프로그램이 관리한다.

`precheck`는 스킬의 성능을 채점하지 않는다. 적용 가능한 문서인지, 실제 변경이 있는지, 수정 설명이 진단 근거를 참조하는지 검사한다. 무변경은 `no_change`로 끝내고, 형식 오류는 최대 한 번 교정한다. 채택되지 않은 후보도 기록에 남으며 활성 스킬은 parent로 복원된다.

## 3. 네 진단축과 필요한 증거

| 진단축 | 사용하는 정보 | 계산·판단 |
|---|---|---|
| **Quality Impact** | 같은 질문·스키마에서 No-skill / 스킬의 SQL, 실행 결과·오류·행 표본 | 무작위 A/B 비교로 방향 `d`를 정한 뒤 크기 `m`을 판정하여 `d × m`. 동률은 0 |
| **Trigger** | `description`, `applies_when`, `avoid_when`의 명사구·문맥·부정 범위 | 적용 조건 사이의 breadth, 제외 조건의 negative specificity, 적용/제외 경계의 sharpness |
| **Compliance** | 스킬에서 추출한 규칙과 작업별 실행 trace | 관련 규칙의 준수도 `a`, 품질 `g`, 실패 책임 `f`를 판정하고 severity 가중치로 집계 |
| **Coverage** | 질문·스키마로 생성한 해결 경로 후보와 스킬 본문 청크 | 경로별 가장 가까운 청크의 cosine 유사도를 구하고 평균 |

실행 증거는 `sql_agent/run.py`가 수집한다. 생성 SQL, 읽기 전용 SQL 실행의 성공·오류, 열 이름, 행 표본과 잘림 여부, 실행 노드와 모델 호출 기록을 남긴다. SQL 실행 성공 자체를 정답으로 간주하지 않는다.

- Quality judge에는 스킬 원문이나 조건 이름을 보여 주지 않는다.
- Trigger는 본문의 일반 지침을 적용 조건으로 추정하지 않고 명시적 조건을 분석한다.
- Compliance는 먼저 작업을 숨긴 채 규칙을 추출하고, 이후 작업별로 판정한다. 관련 규칙만 집계하며 `f=0`인 규칙은 보존 지침으로 전달한다.
- Coverage 경로는 스킬 본문 없이 생성한다. 경로 후보는 검증된 정답이 아니며 유사도는 정답률이 아니다.

진단과 Refiner 입력에는 정답 SQL·정오답 표시·최종 채택 이력을 전달하지 않는다. 다만 **최종 채택과 다음 parent 선택은 기존 정답 기반 평가 정책**을 사용한다.

관련 규칙이나 비교할 문구가 없으면 이유와 함께 `N/A`로 기록한다. API·파싱·임베딩 실패는 `unavailable`이며, 한 축이라도 이 상태이면 Refiner 호출을 중단한다. 실패를 0점으로 대체하지 않는다.

## 4. 설치와 실행

저장소 루트에서 실행한다. Python 3.11 이상과 uv가 필요하다.

### 의존성과 모델 설정

```bash
uv sync --frozen --extra skillaxe
```

기존 환경 설정이 없다면 `.env.example`을 `.env`로 복사하고 모델 접속 정보를 입력한다. 기존 `.env`가 있으면 그대로 사용한다.

```dotenv
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=<API 키>
LLM_MODEL=openai/gpt-4.1-nano
LLM_CONCURRENCY=8
```

필요하면 `LLM_PROVIDER`로 서빙 provider를 지정한다. Improver 모델은 기존 `IMPROVER_LLM_*` 설정을 사용하며, 별도 설정이 없으면 기본 모델 설정을 따른다. SkillAxe 실행 시 환경변수와 `.env`의 `LLM_CACHE`는 제거하거나 비워 둔다.

Trigger는 spaCy `en_core_web_sm` 3.8.0, Trigger·Coverage는 `sentence-transformers/all-MiniLM-L6-v2`를 공유한다. 임베딩 revision은 설정에 고정하며 최초 사용 시 모델 파일을 다운로드한다. 텍스트와 모델 설정에 따른 임베딩 캐시는 별도로 유지한다.

### 활성 스킬 준비 — 최초 한 번

이미 생성된 L0를 활성 파일로 복사한다. L0 원본은 보존한다. 진행 중인 실험에서는 이 명령으로 활성 스킬을 덮어쓰지 않는다.

```bash
cp methods/skillaxe/skills/sqlite-text-to-sql-L0/L0.json \
  methods/skillaxe/skills/active.json
```

loop가 Git commit에서 parent를 복원하므로, **구현 변경과 활성 파일을 검토·commit한 뒤 실행**한다. 시작 commit에 활성 파일이 없으면 실행을 거부한다.

### SkillAxe 한 round 실행

```bash
RULER_OVERRIDE=1 uv run --frozen --extra skillaxe python -m loop.run \
  --config methods/skillaxe/configs/loop.yaml --rounds 1
```

이 명령은 실제 LLM 호출, 후보 commit, 평가와 채택을 수행한다. 진단 작업 외에도 parent·screen·full 평가를 실행한다.

이번 통합은 기존 실행 코드를 확장했으므로 ruler의 고정 파일 비교에 차이가 있다. 이를 명시하는 `RULER_OVERRIDE=1`이 필요하며 결과에 override가 기록된다. 최종 채점·kernel accept·champion 규칙은 유지한다.

**`make round`는 기본 `config.yaml`을 사용하므로 위 SkillAxe 실행과 다르다. `make test`도 별도 SkillAxe archive와 활성 스킬에 연결되어 있지 않다.** 현재 연결 범위는 loop의 validation 평가까지다.

### 주요 설정

실행 설정은 [methods/skillaxe/configs/loop.yaml](methods/skillaxe/configs/loop.yaml)에 모여 있다.

| 설정 | 현재 값·역할 |
|---|---|
| `target_kind` / `skill_path` | `skill` / 활성 스킬 JSON 경로 |
| `editable_blocks` / `evolve_files` | 스킬과 활성 파일만 개선 대상으로 지정 |
| `skillaxe.task_ids` | 미리 지정한 진단 작업 5개. 정오답으로 선택하지 않음 |
| `skillaxe.replicates` | 작업별 실행 1회 |
| `skillaxe.agent_max_tokens` / `sql_timeout_sec` | 512 토큰 / SQL 실행 5초. 진단과 최종 평가에 동일하게 전달 |
| `skillaxe.path_count` / `chunk_chars` | Coverage 경로 3개 / 본문 청크 최대 1200자 |
| `skillaxe.alpha` | Trigger 문구·문맥 임베딩 혼합 비율 0.5 |
| `screen_size` | 사전 평가 20문제 |
| `skillaxe.archive` / `log` | 기존 코드 실험과 분리한 archive와 round 로그 |

현재는 스킬 하나를 대상으로 매 round 네 축 전체를 사용한다. SkillAxe 모드는 few-shot 없이 실행한다.

## 5. 실행 기록

```text
logs/skillaxe/
├── archive.json                parent·후보·champion 정보
├── rounds.jsonl                round별 요약
├── embedding-cache/            공통 임베딩 캐시
└── round-<N>-<id>/
    ├── manifest.json           실행 설정과 식별 정보
    ├── inputs/                 정답을 제외한 진단 입력
    ├── skills/                 현재 스킬 원문
    ├── traces/                 No-skill / 스킬 실행 증거
    ├── diagnostics/            축별 점수·근거·judge 호출 기록
    ├── brief.json              Refiner에 전달한 브리핑
    ├── refiner/                수정 요청·응답·실패 기록
    ├── candidate.json          생성된 후보 문서
    ├── revision.json           변경 설명·해시·진단 참조
    └── external_evaluation/
        ├── parent/             기준 성능 평가
        ├── screen/             후보 사전 평가
        └── candidate/          후보 전체 평가
```

실제로 도달한 단계의 기록만 생성된다. 진단은 `external_evaluation/`을 읽지 않는다. 후보가 거절되거나 실행이 실패해도 이미 저장한 기록은 남긴다. 중간 단계부터 자동 재개하는 기능은 없으며 재실행하면 새 round 폴더를 만든다.

## 6. 검증

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --frozen --extra skillaxe python \
  -m unittest discover -s methods/skillaxe/tests -v
```

테스트는 모의 LLM, 고정 임베딩, 임시 SQLite를 사용해 진단 수식·실행 증거·후보 검증·기존 loop의 채택/거절 연결을 확인한다. 의존성 설치 후 테스트 자체에는 유료 LLM 호출이나 공식 test 데이터가 필요하지 않다.

테스트 통과와 실제 성능 향상은 별개다. 네 축을 연결한 실제 LLM round의 성능 향상과 공식 test 결과는 아직 검증하지 않았다.

# SkillAxe · Text-to-SQL 스킬 개선

기존 SQL 에이전트에 스킬 문서를 적용하고, **네 진단축의 브리핑으로 다음 버전의 스킬을 만드는 프로젝트**다. 실행과 개선 반복은 기존 `sql_agent/run.py`와 `loop/run.py`를 사용한다.

개선 대상은 스킬 문서다. SkillAxe 모드의 Refiner는 에이전트 코드나 loop를 수정하지 않는다. 진단 LLM은 정답 SQL 없이 수정 근거를 만들고, 생성된 후보의 최종 채택은 기존 evaluator·kernel·champion 규칙으로 결정한다.

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
│   ├── diagnose.py             선택된 오답의 기존 실행 증거 → 네 축 → 브리핑
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
│   │   ├── sqlite-text-to-sql-L0/     이전 영문 초기 스킬과 생성 근거
│   │   ├── sqlite-text-to-sql-ko-L0/  한국어 초기 스킬과 생성 근거
│   │   └── active.json        실행할 활성 스킬 (최초 준비 시 생성)
│   └── tests/                 수식·증거 수집·기존 loop 연결 테스트
│
├── showcase/skillaxe/          별도 환경의 읽기 전용 Reflex 대시보드
│   ├── dashboard/              로컬 실행 기록 조회·화면·스킬 diff
│   └── tests/                  기록 로딩·화면 데이터 테스트
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

진단 프롬프트는 `methods/skillaxe/prompts/`에 한국어로 작성되어 있다. 품질 영향은 요청한 출력과 실제 SQL·실행 증거를 비교하고, 지침 준수는 스킬 원문의 실행 가능한 규칙과 적용 조건을 추출해 규칙별로 판단한다. 해결 경로는 스키마에 근거한 전략과 적용 조건을 생성한다. 적용 조건(Trigger) 축은 파서·임베딩으로 계산하므로 별도 LLM 프롬프트가 없다. 프롬프트를 수정해도 기존 로그와 점수는 바뀌지 않으며, 새 진단 결과는 다음 실행에서 생성된다.

진단과 Refiner 입력에는 정답 SQL·정오답 표시·최종 채택 이력을 전달하지 않는다. 다만 **진단할 사례 선택에는 현재 parent의 validation 정오답을 사용**한다. 이는 정답 기반 오답 표본 선택이며, 완전히 정답과 무관한 방법은 아니다. 최종 채택과 다음 parent 선택은 기존 정답 기반 평가 정책을 사용한다.

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

SkillAxe 진단 모델은 `.env`의 `SKILLAXE_LLM_MODEL`로 별도 지정한다. 초기값은 `openai/gpt-4.1-nano`이며, 이 값만 변경하면 SQL 에이전트와 Improver에 영향을 주지 않는다. 진단용 접속 정보가 다르면 `SKILLAXE_LLM_BASE_URL`, `SKILLAXE_LLM_API_KEY`, `SKILLAXE_LLM_PROVIDER`도 지정할 수 있다. 미설정 값은 기본 `LLM_*`를 사용하며 `IMPROVER_LLM_*`를 상속하지 않는다. 변경은 다음 실행부터 적용되며 실제 진단 모델은 실행 기록의 `judge.model`에 저장된다.

진단 모델을 바꿀 때는 provider 제한도 확인한다. 기본 `LLM_PROVIDER=Azure`인 환경에서 `openai/gpt-oss-120b`를 사용할 경우, 진단 전용 `SKILLAXE_LLM_PROVIDER=deepinfra/bf16`를 지정해 Azure 제한의 상속을 피했다. SQL 에이전트·Improver의 기본 provider 설정은 유지한다. 지원 provider와 구조화 응답 지원 여부는 서비스 상태에 따라 달라질 수 있다.

한국어 실험의 Trigger는 spaCy `ko_core_news_sm` 3.8.0, Trigger·Coverage는 다국어 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`를 공유한다. 한국어 명사구는 의존 구문의 명사와 복합명사 수식어로 추출하며, 부정 표현의 지배 범위를 사용한다. 영문 파서는 기존 기록 재현용으로 유지한다. 임베딩 revision은 설정에 고정하며 최초 사용 시 모델 파일을 다운로드한다. 텍스트와 모델 설정에 따른 임베딩 캐시는 별도로 유지한다.

### 활성 스킬 준비 — 최초 한 번

현재 저장소에는 `active.json`이 이미 포함돼 있어 바로 실행할 수 있다. 활성 파일이 없는 새 실험 환경에서만 L0를 복사한다. 진행 중인 실험에서는 활성 스킬을 덮어쓰지 않는다.

```bash
cp methods/skillaxe/skills/sqlite-text-to-sql-ko-L0/L0.json \
  methods/skillaxe/skills/active.json
```

loop가 Git commit에서 parent를 복원하므로, **구현 변경과 활성 파일을 검토·commit한 뒤 실행**한다. 시작 commit에 활성 파일이 없으면 실행을 거부한다.

### SkillAxe 한 round 실행

```bash
RULER_OVERRIDE=1 uv run --frozen --extra skillaxe python -m loop.run \
  --config methods/skillaxe/configs/loop.yaml --rounds 1
```

이 명령은 실제 LLM 호출, 후보 commit, 평가와 채택을 수행한다. 진단 작업 외에도 parent·screen·full 평가를 실행한다.

새 저장소에는 기존 `ruler-v14` 태그가 없어 현재 실행은 `ruler: skipped`로 기록된다. 위 환경변수만으로 `override`가 기록되는 것은 아니다. 기존 기준 태그가 있고 파일이 다를 때 `RULER_OVERRIDE=1`로 차이를 명시할 수 있다. 기준 태그를 새 구현에 맞춰 임의로 만들지 않았다. 최종 채점·kernel accept·champion 규칙은 유지한다.

**`make round`는 기본 `config.yaml`을 사용하므로 위 SkillAxe 실행과 다르다. `make test`도 별도 SkillAxe archive와 활성 스킬에 연결되어 있지 않다.** 현재 연결 범위는 loop의 validation 평가까지다.

### 주요 설정

실행 설정은 [methods/skillaxe/configs/loop.yaml](methods/skillaxe/configs/loop.yaml)에 모여 있다.

| 설정 | 현재 값·역할 |
|---|---|
| `target_kind` / `skill_path` | `skill` / 활성 스킬 JSON 경로 |
| `editable_blocks` / `evolve_files` | 스킬과 활성 파일만 개선 대상으로 지정 |
| `skillaxe.task_ids` | 진단 후보군: validation 100개 전체. 실제 진단 대상은 매 round의 오답에서 선택 |
| `on_round_start.skillaxe_diagnose_n` | 최대 진단 문제 수 20개. 오류 유형·DB별로 분산 선택하고 round seed로 재현 |
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

테스트 통과와 실제 성능 향상은 별개다. 실제 validation 실행 결과는 아래와 같으며 공식 test는 실행하지 않았다.


## 7. 실제 실행 결과 (2026-11-04)

초기 영문 실험 기록은 보존한다. 현재 기본 실행 설정은 한국어 초기 스킬과 별도 `korean-archive.json`을 사용한다. 스킬 본문뿐 아니라 진단 설명·수정 이유도 한국어로 생성하며 SQL 식별자와 JSON 필드명은 유지한다.

### 이전 영문 실험

모델은 `openai/gpt-4.1-nano`, 진단 작업은 설정의 5개다. 두 실행 모두 `ruler: skipped`다.

| Round | 기준 validation | 후보 validation | 결과 |
|---|---:|---:|---|
| 1 | 70/100 | 미실행 | Compliance·Coverage 응답 형식 오류로 Refiner 호출 전 중단 |
| 2 | 66/100 | 69/100 | 네 진단·후보 생성·screen/full 완료, kernel accept 거절 |

추가로 같은 조건의 No-skill validation 평가를 수행해 **71/100**을 얻었다. 현재 세 조건은 **No-skill 71 → 초기 L0 66 → 진화 L1 후보 69**이며, 후보가 No-skill보다 좋다는 결과는 아니다.

Round 2의 screen은 13/20 → 15/20이었다. 전체 평가에서 6문제를 새로 맞히고 3문제를 잃어 순증은 3이다. SQL이 바뀐 작업이 63개여서 고정 kernel의 해당 구간 조건인 순증 4 이상에 미달했다. 활성 스킬은 L0로 복원됐고 후보는 기록과 로컬 Git ref에 남아 있다.

Round 간 기준 점수도 70과 66으로 달랐다. 독립 모델 호출의 변동이 있으므로 70 → 69를 후보의 전후 성능으로 해석하지 않는다. 단일 실행으로 일반적인 성능 향상을 입증한 것은 아니다.

첫 실행에서 실제 응답의 필수 JSON 필드 누락·타입 차이를 확인해 진단 프롬프트의 출력 계약을 명확히 했다. 실패를 정상 점수로 보정하거나 채점 규칙을 변경하지 않았다.

### 한국어 재측정

한국어 초기 스킬을 LLM으로 새로 생성하고, 한국어 진단·수정 지침으로 다시 실행했다. 기존 영문 기록을 번역해서 점수만 재사용한 것이 아니다.

| 조건 | validation 결과 |
|---|---:|
| No-skill | **72/100** |
| 한국어 초기 스킬 L0 | **69/100** |
| 한국어 진화 후보 L1 | **70/100** |

최종 비교 기록은 `logs/skillaxe/round-4-4f41ac34/`다. 세 조건 모두 같은 모델·설정·SQL agent 소스와 validation 100문제를 사용했으며 독립 실행 1회씩이다. 네 진단축 모두 계산을 완료했다. 후보는 초기 스킬보다 1문제 개선됐지만 고정 kernel의 채택 기준에 미달해 활성 스킬은 한국어 L0를 유지한다. No-skill보다 성능이 높다는 결과도 아니다.

직전 한국어 round 3은 초기 스킬 69/100, No-skill 72/100을 기록했지만 JSON 문법·원문 인용 오류로 후보 생성 전에 중단됐다. 이 기록은 보존했다. 이후 공통 provider에 응답 스키마를 지정하고 규칙의 원문 줄 ID를 선택하게 해 형식 오류를 해결했다. 원문 줄은 프로그램이 그대로 연결하며 기존 rubric과 채점 기준은 유지한다.

현재 한국어 설정에서는 다국어 임베딩과 한국어 의존 구문 분석기를 사용하므로 이전 영문 실험의 진단 거리 수치와 직접 비교하지 않는다. 한국어 문구 추출은 분석기의 품사·구문 분석 오류에 영향을 받을 수 있다.

### 진단 프롬프트 수정 후 재측정 (round 5)

기록: `logs/skillaxe/round-5-bd5e7428/`. SQL 에이전트·Improver·진단 모델 모두 `openai/gpt-4.1-nano`이며 수정한 한국어 진단 프롬프트로 실행했다. 세 조건 모두 validation 100문제를 새로 실행했다.

| 조건 | validation 결과 |
|---|---:|
| No-skill | 71/100 |
| 한국어 초기 스킬 L0 | 70/100 |
| 진화 후보 L1 | 71/100 |

screen은 16/20 → 17/20, 전체 평가에서는 3문제 개선·2문제 악화로 순증 +1이었다. SQL이 바뀐 문제는 23개이며 고정 kernel의 해당 구간 채택 조건(순증 4 이상)에 미달해 거절됐다. 활성 스킬은 L0로 유지한다. loop 실행은 약 109초였으며 No-skill 평가는 별도로 실행했다. `ruler: skipped`이며 공식 test는 실행하지 않았다.

**진단의 의미적 문제는 해결되지 않았다.** Compliance는 5문제 모두 빈 규칙 배열을 반환해 N/A였다. 실제 스킬에는 실행 절차가 있으므로 이를 지침이 없다는 증거로 해석하면 안 된다. Quality는 결제 수단 문제에서 요청하지 않은 집계 열을 더 보여준다는 이유로 No-skill을 우세하게 판단하는 문제를 반복했다. 후보는 적용·회피 조건을 추가하고 마지막 소개 문단을 제거했지만 SQL 작성 절차와 예제는 유지했으며, 수정 이유도 기존 규칙 유지라는 일반적인 설명을 반복했다. 따라서 +1만으로 근거 있는 스킬 개선이나 프롬프트 수정의 효과를 입증하지 못한다. manifest의 `complete`는 처리 완료 상태이며 모든 진단이 유효하다는 뜻이 아니다.

평가셋 100개는 SkillAxe의 요구가 아니라 기존 프로젝트의 고정 validation 구성이다. `scripts/operator/split_spec.yaml`은 validation 100·test 200·few-shot 300과 고정 seed를 지정한다. SQL 특징과 초기 모델의 오류 유형을 반영해 구성하며, 현재 설정의 진단 5문제·screen 20문제·전체 validation 100문제는 서로 다른 단계다.

### 진단 모델 변경 후 재실행 (round 6·7)

SQL 에이전트와 Improver는 `openai/gpt-4.1-nano`로 유지하고 진단 모델만 `openai/gpt-oss-120b`로 변경했다. round 6은 기본 Azure provider 제한을 상속해 진단 API가 404로 실패했으며 후보 생성 전에 중단됐다. 기록은 `logs/skillaxe/round-6-19c3e916/`에 보존했다(No-skill 73/100, 초기 L0 69/100).

진단 전용 `SKILLAXE_LLM_PROVIDER=deepinfra/bf16`를 설정하고 규칙 추출 한 건을 검증한 뒤 round 7을 실행했다. 기록은 `logs/skillaxe/round-7-b5e32ad1/`이다.

| 조건 | validation 결과 |
|---|---:|
| No-skill | 72/100 |
| 한국어 초기 스킬 L0 | 70/100 |
| 진화 후보 (보완 평가) | 70/100 |

네 진단축은 모두 available 상태로 완료됐다. Compliance는 문제마다 9개 규칙을 추출했고 적용 대상 규칙을 SQL 근거로 판단했다. 준수 점수는 순서대로 1.0, 1.0, 1.0, 약 0.927, 1.0이다. 결제 방법 문제의 Quality는 요청하지 않은 건수 열을 추가한 No-skill보다 요청한 코드만 반환한 스킬 SQL을 우세하게 평가해 +0.25를 기록했다. 나머지 4문제의 Quality는 0이다. 집계 조건을 HAVING으로 처리하는 SQL과 스킬의 WHERE 지침 사이 차이도 진단했다. 이는 관측된 진단 개선이며 모델 전반의 정확성이 입증된 것은 아니다.

그러나 nano Improver는 `changes`에서 Quality 진단 ID에 Compliance 규칙 ID들을 연결했다. 해당 진단에는 그 규칙들이 없으므로 `unknown rule reference` 검증 오류가 발생했고 자동 교정 1회도 같은 오류로 실패했다. SQL 작성 절차도 그대로인 수정안이었으며, 검증된 후보가 없어 screen/full 후보 평가는 실행되지 않았다. 활성 스킬은 L0를 유지한다. 진단은 완료됐지만 자동 loop에서는 후보 평가에 도달하지 못했다.

이후 사용자 요청으로 마지막 Improver 응답의 스킬 내용을 그대로 보존해 **validation 100문제 보완 평가**를 수행했다. 기존 `loop.run.eval_on`과 고정 채점·`kernel_accept`를 사용했으며 진단은 재실행하지 않았다. 후보는 70/100으로 초기 L0의 70/100과 같고, 1문제 개선·1문제 악화로 순증 0이었다(SQL 변경 23문제, kernel 판정 false). 스킬 미적용 72/100보다 낮다. `evaluation_followup.json`에 원본 응답 경로, 참조 검증 오류, 보완 평가 결과를 기록했다. 원래 round의 guard 거절 기록은 유지하고, 후보 문서·평가 결과만 추가했으며 자동 채택하지 않았다. 대시보드의 후보 점수는 이 보완 평가 결과다.

round 7은 약 956초(16분)가 걸렸다. 진단 모델의 순차 호출 시간이 대부분을 차지했다. 기준 태그가 없어 `ruler: skipped`이며 공식 test는 실행하지 않았다. 진단 모델·provider 변경 외에 프롬프트, 토큰 한도, 채점·채택 규칙은 실행 중 변경하지 않았다.

### 진단 사례 선택 수정

round 7까지는 고정 5문제를 반복 진단했고, 그 5문제는 초기 스킬의 전체 평가에서 모두 정답이었다. 이 표본 선택 문제 때문에 기존 결과를 실패 사례 기반 개선 실험으로 해석할 수 없다.

현재는 `hooks/on_round_start.py`가 이번 parent 평가의 validation 오답에서 최대 20개를 선택한다. 실행·생성 오류와 결과 불일치를 번갈아 다루고 DB도 분산한다. 정답 SQL 실행 실패(`gold failed`)는 에이전트 실패에서 제외한다. 선택 대상과 오류 분류는 manifest의 `selection`에 보존하며, 진단 LLM·Improver에는 이 채점 정보를 보내지 않는다. 실패가 없으면 정답 문제로 채우지 않고 진단·수정을 건너뛴다(진단 상태 `no_failures`; 기존 loop에서는 브리핑 미준비로 중단).

`hooks/diagnose.py`는 선택된 문제의 `external_evaluation/parent/traces.jsonl`을 재사용한다. 스킬 적용 SQL을 다시 생성하지 않으므로 진단에서 원래 실패가 사라지지 않는다. No-skill 비교 실행만 추가하며, 문제·스킬·DB·실행 설정의 기존 일치 검증을 유지한다. 선택된 실패 trace가 없으면 재생성으로 덮어쓰지 않고 진단 실패로 기록한다. JSON 복원은 기존 `Trace` 계약에서 처리하며 별도 runner/client는 추가하지 않았다.

round 7 저장 기록으로 선택 경로를 재검증했을 때, 기존 정답 5개 대신 실제 오답 30개 중 5개가 선택됐고 원래의 없는 컬럼·모호한 컬럼 오류와 실행 성공 후 결과 불일치 기록이 유지됐다. 이 검증은 기존 기록 재생이다. 이후 최대 진단 개수를 20개로 늘린 실제 실행은 아래 round 8에 기록했다.

### 실제 오답 20개 진단·평가 (round 8)

기록: `logs/skillaxe/round-8-88bef016/`. 사용자가 진단 모델을 `openai/gpt-4.1-nano`로 변경해 SQL 에이전트·Improver·진단 모두 nano로 실행했다. 이전 모델용 DeepInfra 제한이 남아 있어 진단 provider는 nano에 사용하던 `Azure`로 맞췄다.

| 조건 | validation 결과 |
|---|---:|
| No-skill | 71/100 |
| 초기 스킬 L0 | 71/100 |
| 후보 L1 (보완 평가) | 70/100 |

이번 parent가 틀린 29문제에서 실제 오답 20개를 선택했다. 원래 parent 평가의 실패 trace 20개를 그대로 사용한 것을 검증했다. Quality·Coverage는 각 20건 완료됐지만 Compliance는 모두 규칙을 빈 배열로 반환해 N/A였다. Trigger는 계산 완료이며 기존 빈 회피 조건에 따른 일부 지표는 N/A다.

Improver는 진단 참조 오류로 자동 검증을 두 번 통과하지 못했다. 마지막 응답은 diagnosis_ids와 rule_ids에 `unknown`을 반환했다. 기존 요청에 따라 마지막 후보의 문서 내용은 수정하지 않고 validation 100문제 보완 평가를 수행했다. 후보는 2문제 개선·3문제 악화로 순증 -1, SQL 변경 24문제였고 기존 kernel 판정도 false였다. 원래 guard 거절 기록과 보완 평가 `evaluation_followup.json`을 함께 보존하며 활성 스킬은 L0를 유지한다. SQL 작성 절차·예제는 그대로였고 주로 설명과 적용·회피 조건이 달라졌다.

자동 round는 약 212초였고 이후 후보 보완 평가를 별도로 수행했다. 대시보드 round 8은 위 세 점수를 읽는다. `ruler: skipped`이며 공식 test는 실행하지 않았다. 실제 실패를 진단하도록 표본 선택은 바뀌었지만 이번 nano 진단·Improver 조합에서는 성능 향상이 없었다.

## 8. 대시보드

대시보드는 `logs/skillaxe/round-*`의 실제 기록을 바로 읽는다. 내보내기 단계는 없다.

```bash
cd showcase/skillaxe
uv sync --frozen
uv run --frozen reflex run --env dev --backend-host 127.0.0.1
```

브라우저에서 **http://localhost:3000**을 연다. 최초 실행에는 프런트엔드 의존성 다운로드가 필요하다. 종료는 서버 터미널에서 `Ctrl+C`.

첫 화면에서 세 조건을 비교한다.

1. **No skill**: 스킬 없이 실행한 평가 결과
2. **초기 생성 스킬**: LLM이 생성한 L0를 적용한 평가 결과
3. **진화한 스킬**: 네 진단축으로 수정한 L1 후보의 평가 결과

아래에서 작업을 선택하고 **Quality Impact / Trigger / Compliance / Coverage**의 실제 점수와 근거를 확인한다. 초기·진화 스킬 문서와 diff, 작업별 SQL 비교는 펼쳐서 볼 수 있다. 진단 결과는 L1을 만드는 데 사용한 L0 진단이며, L1을 재진단한 것으로 표시하지 않는다.

화면은 읽기 전용이다. 모델 호출·재시도·채택 버튼이 없으며 실행 기록을 변경하지 않는다. 실패·미실행·N/A는 0점과 구분한다. 새 round가 생기면 새로고침 버튼으로 목록을 갱신한다.

### No-skill 전체 평가 추가

loop는 현재 스킬과 후보를 전체 평가한다. No-skill 전체 비교가 필요하면 같은 round 폴더에 아래처럼 별도로 저장한다. 진단 작업 5개의 No-skill trace와 validation 100문제의 평가는 서로 다르다.

저장소 루트에서 `RUN_DIR`을 실제 round 폴더로 바꿔 실행한다. 이미 평가한 폴더는 덮어쓰지 않는다.

```bash
RUN_DIR=logs/skillaxe/round-4-4f41ac34
mkdir "$RUN_DIR/external_evaluation/no_skill" && \
uv run --frozen --extra skillaxe python -m sql_agent.run \
  --problems data/validation.json \
  --out "$RUN_DIR/external_evaluation/no_skill/predictions.jsonl" \
  --trace-out "$RUN_DIR/external_evaluation/no_skill/traces.jsonl" \
  --max-tokens 512 --sql-timeout 5 && \
uv run --frozen --extra skillaxe python -m evaluator.evaluate \
  --pred "$RUN_DIR/external_evaluation/no_skill/predictions.jsonl" \
  --problems data/validation.json --db-dir data/database \
  > "$RUN_DIR/external_evaluation/no_skill/evaluation.json"
```

실행한 round의 모델과 토큰·SQL 시간 제한을 동일하게 사용한다. 위 평가 CLI는 집계 점수만 저장하므로 작업별 정오 표시가 없을 수 있다. 현재 보관된 No-skill 실험은 작업별 채점도 저장했다. 공식 test는 이 경로에서 사용하지 않는다.

대시보드 테스트는 저장소 루트에서 실행한다.

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --frozen --extra skillaxe python \
  -m unittest discover -s showcase/skillaxe/tests -v
```

[대시보드 상세 안내](showcase/skillaxe/README.md)

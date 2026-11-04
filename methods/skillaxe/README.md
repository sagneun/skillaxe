# SkillAxe 방법론 코드

기존 `loop/run.py`와 `sql_agent/run.py`를 사용한다. 네 진단과 스킬 문서 검증만 이 디렉터리에서 구현한다.

- `diagnostics/`: 품질 영향, 적용 조건, 지침 준수, 해결 경로 포함도
- `embeddings.py`: Trigger·Coverage 공통 임베딩
- `brief.py`: 진단 결과를 수정 근거와 보존 지침으로 정리
- `skills.py`: 스킬 로딩·해시·후보 검증
- `generate_initial.py`: 초기 스킬 한 번 생성 후 동결
- `prompts/`: 한국어 스킬·진단·수정 출력 지침
- `configs/loop.yaml`: 현재 한국어 실험 설정
- `skills/sqlite-text-to-sql-ko-L0/`: 한국어 초기 스킬과 생성 근거
- `skills/sqlite-text-to-sql-L0/`: 이전 영문 초기 스킬과 생성 근거
- `tests/`: 수식·한국어 분석·실행 증거·기존 loop 연결 검증

현재 설정은 한국어 spaCy 분석기와 고정 revision의 다국어 임베딩을 사용한다. 한국어 문구 추출은 분석기의 품사·의존 구문 품질에 영향을 받는다. 분석기가 명사를 다른 품사로 잘못 분류하면 문구를 놓칠 수 있으며 모든 한국어 표현을 완전하게 분석한다고 보장하지 않는다.

LLM 호출은 공통 `llm/providers.py`를 사용한다. Compliance·Coverage는 응답 스키마를 지정하고, 규칙 인용은 모델이 고른 실제 원문 줄 ID에서 가져온다. 형식과 기존 수식·rubric 검증은 별개이며 형식 오류를 0점으로 바꾸지 않는다.

[설치·실행·실제 결과·대시보드 안내](../../README.md)

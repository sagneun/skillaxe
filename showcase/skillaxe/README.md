# SkillAxe 대시보드

**No skill → LLM 초기 스킬 → 진화한 스킬**의 평가 결과와 진단축별 결과물을 확인한다. 저장소의 `logs/skillaxe/round-*`를 직접 읽는다. 내보내기나 별도 데이터 준비는 필요 없다.

## 실행

```bash
cd showcase/skillaxe
uv sync --frozen
uv run --frozen reflex run --env dev --backend-host 127.0.0.1
```

http://localhost:3000 에 접속한다. 최초 실행에는 프런트엔드 도구 다운로드가 필요하다. 종료는 Ctrl+C. 실험 의존성이나 API key 없이 저장된 기록을 조회하며, 대시보드 자체는 모델을 호출하지 않는다.

## 화면

- 상단: 세 조건의 정답 수 / 평가 문제 수. 후보 채택 여부도 함께 표시.
- 스킬 문서: 초기 L0, 진화 후보 L1, 실제 문서 diff.
- 하단: 진단 작업을 선택해 Quality Impact, Trigger, Compliance, Coverage의 점수와 근거 확인.
- SQL 비교: 선택 작업의 세 조건 실행 결과를 펼쳐서 확인.

진단 결과는 스킬 진화에 사용한 초기 스킬의 진단이다. 진화 후 재진단 결과를 만들어 표시하지 않는다. 실패·미실행은 0점이 아니다. 새 실행을 마친 뒤 상단 새로고침을 누른다.

## 구조

```text
dashboard/
  dashboard.py   화면과 실행·작업 선택
  loader.py      로컬 round 기록 읽기
  views.py       점수·진단·SQL 표시
  diff.py        스킬 문서 비교
```

No-skill 전체 평가가 없으면 해당 카드에 미실행으로 표시한다. 추가 평가 명령은 [루트 README](../../README.md#8-대시보드)에 있다. 진단 작업에서 실행한 No-skill 5개를 전체 100문제 성능으로 표시하지 않는다.

포트 충돌 시 이전 서버를 종료하거나 `--frontend-port 3001 --backend-port 8001`을 지정한다. Node.js 20.19 이상을 권장한다.

[Reflex 공식 문서](https://reflex.dev/docs/getting-started/introduction/)

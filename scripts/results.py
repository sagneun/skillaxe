"""rounds.jsonl → 결과 표 5칸 중 자동으로 채울 수 있는 것(전/후, 비용, 거부 사유 분포)."""
from __future__ import annotations
import argparse, json, os
from collections import Counter
from pathlib import Path


def skillaxe_report(rows, week):
    """보고는 집계 JSON만 읽는다. test 문제·예측·오답은 읽지 않는다."""
    def read(path):
        return json.loads(path.read_text()) if path.exists() else {}

    last=rows[-1]
    run=Path(last['skillaxe']['output'])
    print(f"week {week}: SkillAxe, rounds {len(rows)}, 최종 round {last['round']}")
    for row in rows:
        correction=row.get('week_correction')
        if correction:
            print(f"주차 정정: round {row['round']}, week {correction['from']} → {correction['to']} (평가 수치 변경 없음)")
    print(f"근거: {run}")
    manifest=read(run/'manifest.json')
    print(f"진단 대상: 실제 오답 {len(manifest.get('task_ids',[]))}개")
    candidate=read(run/'candidate.json')
    version=candidate.get('version','L1')
    scores={}
    for stage in ('no_skill','parent','candidate'):
        record=read(run/f'external_evaluation/{stage}/evaluation.json')
        if record: scores[stage]=record.get('result',record)
    def score(stage):
        r=scores.get(stage)
        return f"{r['correct']}/{r['n']}" if r else '미평가'
    print(f"validation: No-skill {score('no_skill')} / parent {score('parent')} → 후보 {version} {score('candidate')}")
    print(f"활성 스킬: {score('candidate') if last.get('champion') else score('parent')} (후보 채택: {last['accepted']})")
    followup=read(run/'evaluation_followup.json')
    if followup:
        print(f"후보 점수: 보완 평가 ({followup.get('status')}); 자동 검증·채택과 별도")
    tests=[]
    for path in [*sorted(run.parent.glob('test-*/single_run_result.json')),run/'test/single_run_result.json']:
        record=read(path)
        if (record.get('status')=='complete' and candidate.get('content_hash')
                and record.get('skill_hash')==candidate['content_hash']
                and Path(record.get('source_skill','')).resolve()==(run/'candidate.json').resolve()):
            tests.append((path,record))
    if tests:
        path,record=tests[-1];result=record['selected_run']
        print(f"test: {version} {result['correct']}/{result['n']} ({100*result['correct']/result['n']:.1f}%), 1회 보고")
        print(f"test 근거: {path}")
        if record.get('additional_completed_runs'):
            print(f"test 추가 완료 {record['additional_completed_runs']}회는 사용자 요청에 따라 보고 점수에서 제외")
    else: print('test: 해당 후보와 일치하는 1회 보고 기록 없음')
    calls=sum(r['llm_calls'] for r in rows);seconds=sum(r['seconds'] or 0 for r in rows)
    print(f"작업량: 자동 round 기록 LLM {calls}회")
    print(f"시간: 자동 round {seconds:.1f}초 ({seconds/60:.1f}분)")
    print('집계 범위: 호출 수는 parent 평가 미포함. 별도 No-skill 전체 평가·후보 보완 평가·test의 호출/시간도 미포함')
    print('고정 파일 검사:',dict(Counter(r.get('ruler','?') for r in rows)))
    print('후보 미채택 사유:',last.get('reason') if not last['accepted'] else '없음')
    print('meta 판정·채택: 별도 ledger 확인 필요' if Path('logs/improver_ledger.jsonl').exists() else 'meta 판정: 안 함 / meta 채택: 안 함')
    print('서비스 판단: 작성자가 선택')


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--week", type=int, required=True); ap.add_argument("--log"); ap.add_argument("--config")
    a = ap.parse_args()
    log=a.log
    if not log and a.config:
        import yaml
        log=yaml.safe_load(Path(a.config).read_text())['log']
    path=Path(log or 'logs/rounds.jsonl')
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []
    rows = [r for r in rows if r["week"] == a.week]
    if not rows:
        print("no rounds for week", a.week); return
    if all(r.get("skillaxe",{}).get("output") for r in rows):
        skillaxe_report(rows,a.week); return
    first, last = rows[0], rows[-1]
    best_after = max((r["full"]["after"] for r in rows if r["accepted"]), default=None)
    print(f"week {a.week}: rounds {len(rows)}, hook_changed={last['hook_changed']}")
    rul = Counter(r.get("ruler", "?") for r in rows); anch = sorted({r.get("anchors_sha", "?") for r in rows})
    print(f"고정 파일 검사: {dict(rul)} | anchors_sha: {', '.join(anch)}" + ("  ← override/변경 있음. 전제 조건에 적을 것" if set(rul) - {"ok"} else ""))
    print(f"validation 전/후: {first['full']['before']}/{first['full']['n']} -> {best_after if best_after is not None else first['full']['before']}/{first['full']['n']}")
    print(f"비용: LLM 호출 {sum(r['llm_calls'] for r in rows)}회, {sum(r['seconds'] or 0 for r in rows)/60:.1f}분")
    tok_rows = [r["tokens"] for r in rows if r.get("tokens")]
    if tok_rows:
        tin, tout = sum(t["in"] for t in tok_rows), sum(t["out"] for t in tok_rows)
        price_in, price_out = float(os.environ.get("PRICE_IN", 0.10)), float(os.environ.get("PRICE_OUT", 0.40))
        cost = tin / 1e6 * price_in + tout / 1e6 * price_out
        print(f"비용(토큰): in {tin} / out {tout}, 추정 ${cost:.4f} (PRICE_IN={price_in}, PRICE_OUT={price_out} $/1M)")
    print("accept", sum(r["accepted"] for r in rows), "/ 거부 사유:", dict(Counter(r["rejected_by"] for r in rows if r["rejected_by"])))
    print("진단 목록:"); [print(" -", r["diagnosis"]) for r in rows]
    print("test 전/후, 실패 유형, 전제 조건, 서비스에 넣는다면 은 사람이 적습니다.")


if __name__ == "__main__":
    main()

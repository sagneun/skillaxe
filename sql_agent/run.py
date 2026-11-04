"""SQL agent (LangGraph). 사용법: python -m sql_agent.run --problems p.json --out o.jsonl
입력 문제에는 gold_sql이 없다. 출력은 한 줄에 {"id","sql"}.
문제 하나 = graph 한 번 실행. 배선(select_schema → generate → execute → fix)은 고정이고, 노드 본문은 `code` 블록이 정한다."""
from __future__ import annotations
import argparse, json, os, re, sqlite3, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
import llm
from sql_agent.schema import schema_text
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, replace
from time import monotonic
from uuid import uuid4
import hashlib
import math
from methods.skillaxe.calls import recorded_call
from methods.skillaxe.contracts import (
    ChatClient, ExecutionEvidence, ExecutionPolicy, SkillVersion,
    SQLExecutionRecord, TaskInput, Trace, content_hash,
)

# 병렬 문제마다 모델/SQL 관찰자를 따로 연결한다.
_observer = ContextVar("sql_agent_observer", default=None)


def current():
    return _observer.get()

@contextmanager
def observe(ask, execute):
    token = _observer.set((ask, execute))
    try:
        yield
    finally:
        _observer.reset(token)


DATA_DIR = Path(os.environ.get("STARTER_DATA_DIR", "data"))
MAX_STEPS = 25   # graph가 END에 못 가고 맴돌 때 자르는 단계 수 (fix 5회 = 3 + 2*5 = 13 노드 + 여유)


class AgentState(TypedDict, total=False):
    question: str
    schema: str
    db_id: str
    fewshot: list[dict]
    sql: str          # 답. END에서 이 값을 낸다
    result: dict      # 마지막 run_sql 결과 {"ok","rows","error"}
    attempts: int     # 블록 안 노드가 올리는 값(참고용). 상한은 executions로 건다
    executions: int   # execute 노드가 올린다. 블록이 바꿀 수 없음


SQL_TIMEOUT = float(os.environ.get("SQL_TIMEOUT_SEC", "5"))   # try_sql 한 번의 상한(초). evaluator와 같은 방식


def database_hash(path: Path) -> str:
    """DB가 같은 이름만 가진 다른 파일인지 구별한다. 큰 DB도 블록 단위로 읽는다.

    이 단계는 정적 SQLite 파일만 지원한다. WAL에 미반영 변경이 있으면 본체
    해시만으로 입력을 고정할 수 없으므로 WAL이 존재하는 DB는 명시적으로 거부한다.
    """
    path = Path(path)
    if Path(str(path) + "-wal").exists():
        raise ValueError("use a static SQLite database without a WAL file")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256")
    return digest.hexdigest()


def _authorize(action, arg1, arg2, database, trigger):
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
    if action not in allowed:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in {"load_extension", "readfile", "writefile"}:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _cell(value, limit: int):
    """JSON에서 표현할 수 없는 BLOB/무한대는 명시적인 타입 표시로 보존한다."""
    if isinstance(value, bytes):
        text = value.hex()
        return {"type": "blob", "hex": text[:limit]}, len(text) > limit
    if isinstance(value, float) and not math.isfinite(value):
        return {"type": "nonfinite", "value": str(value)}, False
    if isinstance(value, str):
        return value[:limit], len(value) > limit
    return value, False


def execute_sql(database: Path, sql: str, policy: ExecutionPolicy) -> ExecutionEvidence:
    """한 SQL만 실행하고 표본을 반환한다. 재작성·재시도·정답 판정은 하지 않는다.

    limit+1행을 읽어야 '정확히 limit행'과 '더 있지만 잘린 결과'를 구분할 수
    있다. 제한 시간은 SQLite VM의 progress handler와 lock 대기에 적용한다.
    OS I/O를 강제 종료하는 프로세스 수준의 hard timeout은 아니다.
    """
    start = monotonic()
    status, error = "success", None
    columns, rows = (), ()
    rows_truncated, cells_truncated = False, False
    connection = None
    try:
        connection = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True,
                                     timeout=policy.timeout_seconds)
        connection.execute("PRAGMA query_only=ON")
        connection.set_authorizer(_authorize)
        deadline = start + policy.timeout_seconds
        connection.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
        # executescript는 여러 문장을 허용하므로 사용하지 않는다. SQL 문자열 안의
        # ';'를 split하지도 않는다. SQLite가 단일 문장 여부를 정확하게 판정한다.
        cursor = connection.execute(sql)
        if cursor.description is None:
            raise sqlite3.OperationalError("query must return columns")
        columns = tuple(column[0] for column in cursor.description)
        fetched = cursor.fetchmany(policy.row_limit + 1)
        rows_truncated = len(fetched) > policy.row_limit
        normalized = []
        for row in fetched[:policy.row_limit]:
            cells = []
            for value in row:
                cell, truncated = _cell(value, policy.max_cell_chars)
                cells.append(cell)
                cells_truncated |= truncated
            normalized.append(tuple(cells))
        rows = tuple(normalized)
    except sqlite3.Error as exc:
        status = "timeout" if monotonic() >= start + policy.timeout_seconds else "error"
        error = f"{type(exc).__name__}: {exc}"[:1000]
    finally:
        if connection is not None:
            connection.close()
    return ExecutionEvidence(status=status, columns=columns, rows=rows, rows_truncated=rows_truncated,
                             cells_truncated=cells_truncated, error=error, policy=policy,
                             elapsed_seconds=monotonic() - start)

def try_sql(db_id: str, sql: str, limit: int | None = None, timeout: float | None = None) -> dict:
    """SQL을 읽기 전용으로 실행해 본다. execute 노드가 쓰는 도구.
    반환: {"ok": bool, "rows": [...최대 limit행], "error": str | None}. 정답은 모른다.
    timeout초를 넘기면 progress handler가 중단시키고 ok=False, error="timeout"."""
    observer = current()
    if observer is not None:
        return observer[1](db_id, sql, limit=limit, timeout=timeout)
    limit = 5 if limit is None else limit
    timeout = SQL_TIMEOUT if timeout is None else timeout
    db = DATA_DIR / "database" / db_id / f"{db_id}.sqlite"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=timeout)
        try:
            con.execute(f"PRAGMA busy_timeout={int(timeout*1000)}")
            deadline = time.monotonic() + timeout
            con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
            rows = con.execute(sql).fetchmany(limit)
        finally:
            con.close()
        return {"ok": True, "rows": [tuple(r) for r in rows], "error": None}
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e).lower():
            return {"ok": False, "rows": [], "error": f"timeout: query exceeded {timeout:g}s"}
        return {"ok": False, "rows": [], "error": f"{type(e).__name__}: {e}"[:200]}
    except sqlite3.Error as e:
        return {"ok": False, "rows": [], "error": f"{type(e).__name__}: {e}"[:200]}

# === EVOLVE-BLOCK-START: prompt ===
SYSTEM_PROMPT = "You are a Text-to-SQL assistant for SQLite. Answer with one SQL query only, no explanation."
FEWSHOT_IDS: list[str] = []   # data/fewshot_pool.json 의 id. 비어 있으면 few-shot 없음.


def build_messages(question: str, schema: str, fewshot: list[dict]) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex in fewshot:
        msgs.append({"role": "user", "content": f"Schema:\n{ex['schema']}\nQuestion: {ex['question']}"})
        msgs.append({"role": "assistant", "content": ex["sql"]})
    msgs.append({"role": "user", "content": f"Schema:\n{schema}\nQuestion: {question}"})
    return msgs
# === EVOLVE-BLOCK-END ===


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S)
    sql = (m.group(1) if m else text).strip()
    return sql.split(";")[0].strip()


def ask(messages: list[dict]) -> str:
    """SQL agent 역할의 LLM 호출. 블록 안 노드가 쓴다. EVOLVE-BLOCK 밖."""
    observer = current()
    if observer is not None:
        return observer[0](messages)
    return llm.chat(messages, role="agent")


# === EVOLVE-BLOCK-START: code ===
# 노드 본문. 배선(select_schema → generate → execute → route → fix/END)은 아래 make_graph가 고정한다.
# 노드는 s(AgentState) -> 바뀐 key만 담은 dict. ask(messages) -> str 는 LLM 호출. s["result"]는 직전 execute의 {"ok","rows","error"}.
MAX_ATTEMPTS = 1   # route가 fix로 보낼 수 있는 generate+fix 총 횟수. 1이면 재시도 없음(v0)


def select_schema(s: AgentState) -> dict:
    """질문과 관련된 테이블만 남겨 s["schema"]를 줄인다. v0: 전체 스키마 그대로(변경 없음)."""
    return {}


def generate(s: AgentState) -> dict:
    return {"sql": extract_sql(ask(build_messages(s["question"], s["schema"], s["fewshot"]))), "attempts": s.get("attempts", 0) + 1}


def fix(s: AgentState) -> dict:
    """execute가 실패했을 때 오류를 보여 주고 SQL을 다시 받는다. v0에서는 route가 여기로 보내지 않는다."""
    msgs = build_messages(s["question"], s["schema"], s["fewshot"])
    msgs.append({"role": "assistant", "content": s["sql"]})
    msgs.append({"role": "user", "content": f"That SQL failed on SQLite: {s['result']['error']}\nReply with the corrected SQL only."})
    return {"sql": extract_sql(ask(msgs)), "attempts": s["attempts"] + 1}


def route(s: AgentState) -> str:
    """execute 뒤 어디로 갈지: "fix" 또는 END. v0: 항상 END."""
    return END
# === EVOLVE-BLOCK-END ===


MAX_FIX = 5   # route가 뭐라 하든 fix는 문제당 이 횟수를 넘지 않는다 (비용 상한). 블록 밖. 블록 안 attempts와 무관하게 execute 횟수로 센다.


def execute(s: AgentState) -> dict:
    return {"result": try_sql(s["db_id"], s["sql"]), "executions": s.get("executions", 0) + 1}


def _route(s: AgentState) -> str:
    r = ROUTE(s)
    fixes_so_far = s.get("executions", 1) - 1   # 첫 execute는 generate 뒤. 그 다음부터가 fix
    return "fix" if r == "fix" and fixes_so_far < MAX_FIX else END


def make_graph():
    """고정 배선. 노드 본문은 code 블록이 정한다. 블록이 이름을 빼먹으면 여기서 NameError."""
    global ROUTE
    ROUTE = route
    for name, fn in (("select_schema", select_schema), ("generate", generate), ("fix", fix), ("route", route)):
        if not callable(fn):
            raise TypeError(f"code block: {name} must be a function")
    int(MAX_ATTEMPTS)
    g = StateGraph(AgentState)
    g.add_node("select_schema", select_schema)
    g.add_node("generate", generate)
    g.add_node("execute", execute)
    g.add_node("fix", fix)
    g.add_edge(START, "select_schema")
    g.add_edge("select_schema", "generate")
    g.add_edge("generate", "execute")
    g.add_edge("fix", "execute")
    g.add_conditional_edges("execute", _route, {"fix": "fix", END: END})
    return g.compile()


GRAPH = make_graph()   # import 시점에 배선. 블록이 route/fix 등을 빼먹으면 여기서 NameError → loop guard의 compile 검사가 잡는다


def answer(graph, question: str, schema: str, db_id: str, fewshot: list[dict]) -> str:
    out = graph.invoke({"question": question, "schema": schema, "db_id": db_id, "fewshot": fewshot},
                       {"recursion_limit": MAX_STEPS})
    return out.get("sql", "")


class _ModelCallFailed(RuntimeError):
    """원본 graph를 중단시키는 내부 신호. 실제 실패 종류는 CallRecord에 보존한다."""

def run_with_skill(task: TaskInput, skill: SkillVersion | None, database: Path, client: ChatClient,
              policy: ExecutionPolicy, *, replicate: int = 1) -> Trace:
    """같은 원본 에이전트를 No-skill/L0 조건의 독립 실행 상태로 호출한다.

    원본이 fix 경로를 고르면 그대로 실행한다. 현재 원본 route는 항상 END라서
    SQL 생성은 1회다. 원본의 MAX_FIX/MAX_STEPS도 수정하지 않는다. 스킬을
    전달하려고 질문이나 스키마를 바꾸지 않고 실제 ask 호출 직전에만 추가한다.
    """
    if type(replicate) is not int or replicate < 1:
        raise ValueError("replicate must be a positive integer")
    db_hash = database_hash(database)
    calls, execution_steps, nodes = [], [], []
    state = {"question": task.question, "schema": task.schema, "db_id": task.db_id, "fewshot": []}
    graph_error = None

    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    base_messages = build_messages(task.question, task.schema, [])
    config_hash = content_hash({
        "agent_version": 4, "engine": "sql_agent.run.GRAPH", "source_hash": source_hash,
        "base_messages": base_messages, "model": asdict(client.settings),
        "execution": asdict(policy), "max_steps": MAX_STEPS, "max_fix": MAX_FIX,
    })

    def observed_ask(messages):
        # generate 또는 fix가 원래 build_messages로 만든 메시지를 받는다.
        # 기존 메시지는 그대로 유지하며 스킬 메시지 하나만 추가한다.
        supplied = list(messages)
        if skill is not None:
            supplied.insert(1, {"role": "system", "content": "Assigned skill:\n" + skill.render()})
        call = recorded_call(client, supplied, "sql_generation" if not calls else "sql_fix")
        calls.append(call)
        if call.status != "success":
            raise _ModelCallFailed()
        # SQL 추출은 원본 generate/fix가 원본 extract_sql로 수행한다.
        return call.response

    def observed_sql(db_id, sql, limit=None, timeout=None):
        # 원본 execute 노드가 호출하는 도구를 연결한다. 임시 DB 경로를 원본
        # DATA_DIR 전역에 넣거나 데이터를 복사하지 않으며, 다른 DB로 바뀌면
        # 잘못된 실험을 실행하는 대신 실패시킨다.
        if db_id != task.db_id:
            raise ValueError("agent requested a database outside the assigned task")
        evidence = execute_sql(database, sql, replace(policy, row_limit=policy.row_limit if limit is None else limit,
                                                          timeout_seconds=policy.timeout_seconds if timeout is None else timeout))
        execution_steps.append(SQLExecutionRecord(sql=sql, evidence=evidence))
        # 기존 agent가 기대하는 도구 반환 계약은 그대로 유지한다. 풍부한
        # 열 이름/잘림 정보는 별도 execution_steps에 남기며 SQL은 한 번만 실행한다.
        return {"ok": evidence.status == "success", "rows": list(evidence.rows), "error": evidence.error}

    # 원본 노드·GRAPH는 그대로 두고 실행별 관찰자만 연결한다.
    try:
        # stream은 이미 실행한 결과를 흉내 내는 것이 아니라 실제 GRAPH 실행
        # API다. 업데이트에서 완료 노드와 최종 SQL을 관찰할 뿐 분기하지 않는다.
        with observe(observed_ask, observed_sql):
            for update in GRAPH.stream(dict(state), {"recursion_limit": MAX_STEPS},
                                               stream_mode="updates"):
                for node, delta in update.items():
                    nodes.append(node)
                    if isinstance(delta, dict):
                        state.update(delta)
    except Exception as exc:
        graph_error = type(exc).__name__
    sql = state.get("sql", "")
    execution = execution_steps[-1].evidence if execution_steps and execution_steps[-1].sql == sql else None
    last_call = calls[-1] if calls else None
    if any(call.status != "success" for call in calls):
        status = "generation_error"
    elif graph_error or last_call is None:
        status = "agent_error"
        graph_error = graph_error or "MissingModelCall"
    elif not sql:
        status = "generation_invalid"
    elif execution is None:
        status, graph_error = "agent_error", "MissingExecution"
    else:
        status = execution.status
    return Trace(
        trace_id=str(uuid4()), task_id=task.task_id, input_hash=task.input_hash, db_hash=db_hash,
        condition="no_skill" if skill is None else skill.version, replicate=replicate,
        skill_hash=None if skill is None else skill.content_hash, config_hash=config_hash,
        status=status, sql=sql, agent_call=last_call, execution=execution,
        agent_calls=tuple(calls), execution_steps=tuple(execution_steps), node_order=tuple(nodes),
        agent_source_hash=source_hash, graph_error_type=graph_error)

def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--problems", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skill", type=Path, help="assigned skill JSON; omitted means no skill")
    ap.add_argument("--trace-out", type=Path, help="detailed evidence JSONL, separate from predictions")
    ap.add_argument("--tables", type=Path)
    ap.add_argument("--db-dir", type=Path)
    ap.add_argument("--max-tokens", type=int)
    ap.add_argument("--sql-timeout", type=float)
    a = ap.parse_args(argv)
    if a.skill or a.trace_out:
        # 기존 GRAPH에 실행별 스킬과 증거 기록을 연결한다.
        from dataclasses import asdict
        from loop.env import load_env
        from llm.providers import Client
        from methods.skillaxe.contracts import TaskInput, ExecutionPolicy
        from methods.skillaxe.skills import load_skill
        load_env()
        skill = load_skill(a.skill) if a.skill else None
        client = Client(role="agent", max_tokens=a.max_tokens if a.max_tokens is not None else int(os.environ.get("LLM_MAX_TOKENS", "512")), independent=True)
        problems = json.loads(Path(a.problems).read_text())
        def traced_solve(p):
            task = TaskInput(str(p["id"]), p["question"], p["db_id"], schema_text(str(a.tables or DATA_DIR / "tables.json"), p["db_id"]))
            return run_with_skill(task, skill, (a.db_dir or DATA_DIR / "database") / p["db_id"] / f"{p['db_id']}.sqlite", client,
                             ExecutionPolicy(timeout_seconds=a.sql_timeout if a.sql_timeout is not None else SQL_TIMEOUT))
        from contextlib import ExitStack
        with ExitStack() as stack:
            out = stack.enter_context(open(a.out, "w"))
            evidence = stack.enter_context(a.trace_out.open("w")) if a.trace_out else None
            pool = stack.enter_context(ThreadPoolExecutor(max_workers=int(os.environ.get("LLM_CONCURRENCY", "8"))))
            for trace in pool.map(traced_solve, problems):
                out.write(json.dumps({"id":trace.task_id,"sql":trace.sql})+"\n")
                if evidence:
                    evidence.write(json.dumps(asdict(trace), ensure_ascii=False, allow_nan=False)+"\n")
        return
    tables = str(DATA_DIR / "tables.json")
    pool = {p["id"]: p for p in json.loads((DATA_DIR / "fewshot_pool.json").read_text())}
    fewshot = []
    for fid in FEWSHOT_IDS:
        if fid in pool:
            ex = {"question": pool[fid]["question"], "sql": pool[fid]["gold_sql"], "schema": schema_text(tables, pool[fid]["db_id"]), "db_id": pool[fid]["db_id"]}
            fewshot.append(ex)
    problems = json.loads(Path(a.problems).read_text())
    graph = GRAPH

    def solve(p: dict) -> dict:
        try:
            fs = [ex for ex in fewshot if ex["db_id"] != p["db_id"]]   # 같은 DB 예시 제외 (validation과 pool이 같은 DB를 써서, 같은 DB 예시는 test로 이어지지 않는다)
            return {"id": p["id"], "sql": answer(graph, p["question"], schema_text(tables, p["db_id"]), p["db_id"], fs)}
        except Exception as e:  # 한 문제 실패가 전체를 멈추지 않게. 빈 sql은 틀린 것으로 채점됨.
            print(f"[sql_agent] {p['id']} failed: {type(e).__name__}: {e}", flush=True)
            return {"id": p["id"], "sql": ""}

    workers = int(os.environ.get("LLM_CONCURRENCY", "8"))  # 로컬 LM Studio면 1
    with ThreadPoolExecutor(max_workers=workers) as ex, open(a.out, "w") as f:
        for row in ex.map(solve, problems):
            f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()

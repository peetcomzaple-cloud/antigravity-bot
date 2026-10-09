import sqlite3
import json
import os
import re
import time
from typing import List, Dict, Any, Optional

from .config import DB_PATH

def get_connection():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 60000;")
    except Exception:
        pass
    return conn

def _init_db_tables(conn):
    cursor = conn.cursor()
    
    # 1. Runs Table (Long-horizon sessions)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        goal TEXT NOT NULL,
        success_criteria TEXT,
        status TEXT NOT NULL DEFAULT 'idle',
        current_step INTEGER DEFAULT 0,
        max_steps INTEGER DEFAULT 20,
        guidance_question TEXT DEFAULT '',
        guidance_options TEXT DEFAULT '[]',
        guidance_response TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 2. Plan Checklist Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        step_index INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        assigned_agent TEXT DEFAULT 'coder',
        action_type TEXT DEFAULT 'write_file',
        target_file_or_cmd TEXT DEFAULT '',
        depends_on TEXT DEFAULT '[]',
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES runs (run_id)
    )
    ''')

    # 3. Execution Steps Table (State Machine logs: Plan -> Act -> Observe -> Reflect)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        step_index INTEGER NOT NULL,
        agent_role TEXT NOT NULL,
        state TEXT NOT NULL,
        thought TEXT,
        action_type TEXT,
        action_payload TEXT,
        observation TEXT,
        reflection TEXT,
        duration_sec REAL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES runs (run_id)
    )
    ''')

    # 4. Artifacts Table (Diffs, Screenshots, Terminal logs, Decision records)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        step_index INTEGER DEFAULT 0,
        artifact_type TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT,
        file_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES runs (run_id)
    )
    ''')

    # 5. Memory Bank (Hierarchical memory: short-term, mid-term, lessons learned)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 6. Skill Library (Persistent reusable engineering patterns)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        category TEXT DEFAULT 'general',
        description TEXT,
        instructions TEXT NOT NULL,
        code_template TEXT,
        source_run_id TEXT,
        usage_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 7. Checkpoints Table (Safe rollback points for long-horizon stability)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS checkpoints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        step_index INTEGER NOT NULL,
        commit_hash TEXT,
        snapshot_path TEXT,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES runs (run_id)
    )
    ''')

    # 8. lnwjud Pillar 1: Tool Execution Audit Log
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tool_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        step_index INTEGER DEFAULT 0,
        actor_agent TEXT DEFAULT 'system',
        tool_name TEXT NOT NULL,
        action_class TEXT NOT NULL,
        args_json TEXT DEFAULT '{}',
        result_summary TEXT DEFAULT '',
        exit_code INTEGER DEFAULT 0,
        duration_ms REAL DEFAULT 0.0,
        is_allowed INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # 9. lnwjud Pillar 3: Durable State for Crash Recovery & Rehydration
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS durable_states (
        run_id TEXT PRIMARY KEY,
        current_phase TEXT DEFAULT 'idle',
        completed_steps TEXT DEFAULT '[]',
        context_vars TEXT DEFAULT '{}',
        last_checkpoint_commit TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (run_id) REFERENCES runs (run_id)
    )
    ''')

    # 10. Antigravity Advanced: Dynamic Subagents Registry
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS subagents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT,
        role_name TEXT UNIQUE NOT NULL,
        role_title TEXT NOT NULL,
        system_prompt TEXT NOT NULL,
        assigned_model TEXT DEFAULT 'qwen/qwen3-coder:free',
        status TEXT DEFAULT 'idle',
        task_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Safe Schema Migrations for existing DB instances
    migrations = [
        ("runs", "guidance_question", "TEXT DEFAULT ''"),
        ("runs", "guidance_options", "TEXT DEFAULT '[]'"),
        ("runs", "guidance_response", "TEXT DEFAULT ''"),
        ("runs", "complexity", "TEXT DEFAULT 'medium'"),
        ("runs", "escalation_threshold", "INTEGER DEFAULT 2"),
        ("runs", "token_budget", "INTEGER DEFAULT 50000"),
        ("runs", "tokens_used", "INTEGER DEFAULT 0"),
        ("runs", "high_confidence_flags", "TEXT DEFAULT '[]'"),
        ("runs", "watch_points", "TEXT DEFAULT '[]'"),
        ("runs", "human_review_reason", "TEXT DEFAULT ''"),
        ("plans", "action_type", "TEXT DEFAULT 'write_file'"),
        ("plans", "target_file_or_cmd", "TEXT DEFAULT ''"),
        ("plans", "depends_on", "TEXT DEFAULT '[]'"),
        ("plans", "difficulty", "TEXT DEFAULT 'normal'"),
        ("plans", "is_disputed", "INTEGER DEFAULT 0"),
        ("plans", "escalated", "INTEGER DEFAULT 0"),
        ("plans", "model_used", "TEXT DEFAULT ''"),
        ("plans", "is_flagged", "INTEGER DEFAULT 0"),
        ("plans", "is_watch_point", "INTEGER DEFAULT 0"),
        ("plans", "winning_model", "TEXT DEFAULT ''"),
        ("skills", "source_run_id", "TEXT"),
        ("skills", "high_value", "INTEGER DEFAULT 0"),
        ("skills", "verified_hard", "INTEGER DEFAULT 0"),
        ("skills", "dual_critic_approved", "INTEGER DEFAULT 1"),
        ("skills", "trust_score", "REAL DEFAULT 1.0"),
        ("skills", "failure_count", "INTEGER DEFAULT 0"),
        ("runs", "criteria_pass_rate", "REAL DEFAULT 0.0"),
        ("runs", "dual_critic_rescues", "INTEGER DEFAULT 0"),
        ("runs", "candidate_winner_model", "TEXT DEFAULT ''"),
        ("artifacts", "status", "TEXT DEFAULT 'pending'"),
    ]
    for table, col, col_def in migrations:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
        except sqlite3.OperationalError:
            pass  # column already exists

    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_plans_run_id ON plans(run_id);",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_plans_run_step ON plans(run_id, step_index);",
        "CREATE INDEX IF NOT EXISTS idx_steps_run_id ON steps(run_id);",
        "CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON artifacts(run_id);",
        "CREATE INDEX IF NOT EXISTS idx_checkpoints_run_id ON checkpoints(run_id);",
        "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);",
        "CREATE INDEX IF NOT EXISTS idx_durable_states_run_id ON durable_states(run_id);",
        "CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);",
    ]
    for idx_sql in indexes:
        try:
            cursor.execute(idx_sql)
        except Exception:
            pass

    conn.commit()

def init_db():
    conn = get_connection()
    try:
        _init_db_tables(conn)
    finally:
        conn.close()

# --- Run Operations ---
def create_run(run_id: str, goal: str, success_criteria: str = "", max_steps: int = 20, complexity: str = "medium", escalation_threshold: int = 2) -> Dict[str, Any]:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO runs (run_id, goal, success_criteria, status, current_step, max_steps, complexity, escalation_threshold) VALUES (?, ?, ?, 'planning', 0, ?, ?, ?)",
            (run_id, goal, success_criteria, max_steps, complexity, escalation_threshold)
        )
        conn.commit()
        return {"run_id": run_id, "goal": goal, "status": "planning", "current_step": 0, "complexity": complexity, "escalation_threshold": escalation_threshold}

    finally:
        conn.close()
def update_run_complexity(run_id: str, complexity: str, escalation_threshold: int):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE runs SET complexity = ?, escalation_threshold = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (complexity, escalation_threshold, run_id)
        )
        conn.commit()

    finally:
        conn.close()
def update_run_token_usage(run_id: str, tokens_added: int) -> int:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE runs SET tokens_used = tokens_used + ? WHERE run_id = ?", (tokens_added, run_id))
        c.execute("SELECT tokens_used, token_budget FROM runs WHERE run_id = ?", (run_id,))
        row = c.fetchone()
        conn.commit()
        return row["tokens_used"] if row else 0

    finally:
        conn.close()
def mark_run_needs_human_review(run_id: str, reason: str):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE runs SET status = 'needs_human_review', human_review_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (reason, run_id)
        )
        conn.commit()

    finally:
        conn.close()
def get_human_review_queue() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM runs WHERE status = 'needs_human_review' ORDER BY updated_at DESC")
        rows = c.fetchall()
        return [dict(r) for r in rows]

    finally:
        conn.close()
def save_dual_critic_consensus(run_id: str, high_confidence_flags: List[int], watch_points: List[int], glm_review: Optional[Dict[str, Any]] = None, qwen_review: Optional[Dict[str, Any]] = None):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE runs SET high_confidence_flags = ?, watch_points = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (json.dumps(high_confidence_flags), json.dumps(watch_points), run_id)
        )
        conn.commit()
        if glm_review or qwen_review:
            audit_body = f"### GLM-5.3 Review\n```json\n{json.dumps(glm_review or {}, indent=2)}\n```\n\n### Qwen3 Review\n```json\n{json.dumps(qwen_review or {}, indent=2)}\n```"
            record_artifact(run_id, 0, "audit", "Dual-Critic Audit Consensus", content=audit_body)

    finally:
        conn.close()
def update_run_status(run_id: str, status: str, current_step: Optional[int] = None):
    conn = get_connection()
    try:
        c = conn.cursor()
        if current_step is not None:
            c.execute(
                "UPDATE runs SET status = ?, current_step = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
                (status, current_step, run_id)
            )
        else:
            c.execute(
                "UPDATE runs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
                (status, run_id)
            )
        conn.commit()

    finally:
        conn.close()
def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = c.fetchone()
        return dict(row) if row else None

    finally:
        conn.close()
def get_latest_run(include_tests: bool = False) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        if include_tests:
            c.execute("SELECT * FROM runs ORDER BY updated_at DESC LIMIT 1")
        else:
            c.execute("SELECT * FROM runs WHERE run_id NOT LIKE 'test_%' AND run_id NOT LIKE 'stress_%' AND run_id NOT LIKE 'cycle_%' ORDER BY updated_at DESC LIMIT 1")
        row = c.fetchone()
        return dict(row) if row else None

    finally:
        conn.close()
def list_runs(limit: int = 15, include_tests: bool = False) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        if include_tests:
            c.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
        else:
            c.execute("SELECT * FROM runs WHERE run_id NOT LIKE 'test_%' AND run_id NOT LIKE 'stress_%' AND run_id NOT LIKE 'cycle_%' ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        return [dict(r) for r in rows]

    # --- Human-in-the-Loop Guidance ---
    finally:
        conn.close()
def request_guidance(run_id: str, question: str, options: Optional[List[str]] = None):
    conn = get_connection()
    try:
        c = conn.cursor()
        opts_json = json.dumps(options or [])
        c.execute(
            "UPDATE runs SET status = 'waiting_for_guidance', guidance_question = ?, guidance_options = ?, guidance_response = '', updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (question, opts_json, run_id)
        )
        conn.commit()

    finally:
        conn.close()
def answer_guidance(run_id: str, response: str):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE runs SET status = 'running', guidance_response = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (response, run_id)
        )
        conn.commit()
    finally:
        conn.close()

# --- Plan Operations ---
def save_plan_steps(run_id: str, steps: List[Dict[str, Any]], preserve_status: bool = True):
    conn = get_connection()
    try:
        c = conn.cursor()
        existing_meta = {}
        if preserve_status:
            try:
                c.execute("SELECT step_index, status, difficulty, is_disputed, escalated, model_used, is_flagged, is_watch_point, winning_model FROM plans WHERE run_id = ?", (run_id,))
                for row in c.fetchall():
                    existing_meta[row["step_index"]] = dict(row)
            except Exception:
                pass

        c.execute("DELETE FROM plans WHERE run_id = ?", (run_id,))
        for idx, s in enumerate(steps, 1):
            step_idx = s.get("step", idx)
            prev = existing_meta.get(step_idx, {}) if preserve_status else {}
            status = s.get("status") or (prev.get("status", "pending") if preserve_status else "pending")
            difficulty = s.get("difficulty") or prev.get("difficulty", "normal")
            is_disputed = 1 if (s.get("is_disputed") or prev.get("is_disputed")) else 0
            escalated = 1 if (s.get("escalated") or prev.get("escalated")) else 0
            model_used = s.get("model_used") or prev.get("model_used", "")
            is_flagged = 1 if (s.get("is_flagged") or prev.get("is_flagged")) else 0
            is_watch_point = 1 if (s.get("is_watch_point") or prev.get("is_watch_point")) else 0
            winning_model = s.get("winning_model") or prev.get("winning_model", "")
            depends = json.dumps(s.get("depends_on", []))
            c.execute(
                '''INSERT INTO plans (run_id, step_index, title, description, assigned_agent, 
                                      action_type, target_file_or_cmd, depends_on, status,
                                      difficulty, is_disputed, escalated, model_used,
                                      is_flagged, is_watch_point, winning_model) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (run_id, step_idx, s.get("title", ""), s.get("description", ""), s.get("agent", "coder"),
                 s.get("action_type", "write_file"), s.get("target_file_or_cmd", ""), depends, status,
                 difficulty, is_disputed, escalated, model_used,
                 is_flagged, is_watch_point, winning_model)
            )
        conn.commit()

    finally:
        conn.close()
def get_plan_steps(run_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM plans WHERE run_id = ? ORDER BY step_index ASC", (run_id,))
        rows = c.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["depends_on"] = json.loads(d.get("depends_on") or "[]")
            except Exception:
                d["depends_on"] = []
            d["is_disputed"] = bool(d.get("is_disputed", 0))
            d["escalated"] = bool(d.get("escalated", 0))
            d["is_flagged"] = bool(d.get("is_flagged", 0))
            d["is_watch_point"] = bool(d.get("is_watch_point", 0))
            result.append(d)
        return result

    finally:
        conn.close()
def update_plan_step_status(run_id: str, step_index: int, status: str):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE plans SET status = ? WHERE run_id = ? AND step_index = ?",
            (status, run_id, step_index)
        )
        conn.commit()

    finally:
        conn.close()
def update_plan_step_model(run_id: str, step_index: int, model_used: str, escalated: bool = False, winning_model: str = ""):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE plans SET model_used = ?, escalated = ?, winning_model = ? WHERE run_id = ? AND step_index = ?",
            (model_used, 1 if escalated else 0, winning_model, run_id, step_index)
        )
        conn.commit()

    finally:
        conn.close()
def flag_plan_step(run_id: str, step_index: int, is_flagged: bool = False, is_watch_point: bool = False, winning_model: str = ""):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE plans SET is_flagged = ?, is_watch_point = ?, winning_model = ? WHERE run_id = ? AND step_index = ?",
            (1 if is_flagged else 0, 1 if is_watch_point else 0, winning_model, run_id, step_index)
        )
        conn.commit()

    finally:
        conn.close()
def mark_step_disputed(run_id: str, step_index: int, is_disputed: bool = True):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE plans SET is_disputed = ? WHERE run_id = ? AND step_index = ?",
            (1 if is_disputed else 0, run_id, step_index)
        )
        conn.commit()

    # --- Step Execution Logs ---
    finally:
        conn.close()
def record_step(run_id: str, step_index: int, agent_role: str, state: str,
                thought: str, action_type: str, action_payload: str,
                observation: str, reflection: str, duration_sec: float = 0.0):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO steps (run_id, step_index, agent_role, state, thought, 
                                  action_type, action_payload, observation, reflection, duration_sec)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (run_id, step_index, agent_role, state, thought,
             action_type, action_payload, observation, reflection, duration_sec)
        )
        conn.commit()

    finally:
        conn.close()
def get_steps_for_run(run_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM steps WHERE run_id = ? ORDER BY id ASC", (run_id,))
        rows = c.fetchall()
        return [dict(r) for r in rows]

    # --- Artifact Operations ---
    finally:
        conn.close()
def record_artifact(run_id: str, step_index: int, artifact_type: str,
                    title: str, content: str = "", file_path: str = ""):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO artifacts (run_id, step_index, artifact_type, title, content, file_path) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, step_index, artifact_type, title, content, file_path)
        )
        conn.commit()

    finally:
        conn.close()
def record_decision(run_id: str, title: str, context: str, decision: str, consequences: str = "", step_index: int = 0):
    """Logs an Architectural Decision Record (ADR) as an artifact."""
    body = f"### Context & Problem\n{context}\n\n### Decision Taken\n{decision}"
    if consequences:
        body += f"\n\n### Consequences & Trade-offs\n{consequences}"
    record_artifact(run_id, step_index, "decision", f"ADR: {title}", content=body)

def get_artifacts_for_run(run_id: str, artifact_type: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        if artifact_type:
            c.execute(
                "SELECT * FROM artifacts WHERE run_id = ? AND artifact_type = ? ORDER BY id DESC",
                (run_id, artifact_type)
            )
        else:
            c.execute(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY id DESC",
                (run_id,)
            )
        rows = c.fetchall()
        return [dict(r) for r in rows]

    finally:
        conn.close()
def update_artifact_status(artifact_id: int, status: str):
    """Updates the status of an artifact (e.g. 'accepted', 'reverted', 'pending')."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE artifacts SET status = ? WHERE id = ?", (status, artifact_id))
        conn.commit()

    finally:
        conn.close()
def get_artifact_by_id(artifact_id: int) -> Optional[Dict[str, Any]]:
    """Fetches a specific artifact by its primary ID."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
        row = c.fetchone()
        return dict(row) if row else None

    # --- Memory & Self-Improvement ---
    finally:
        conn.close()
def add_memory(category: str, title: str, content: str, run_id: Optional[str] = None):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO memories (run_id, category, title, content) VALUES (?, ?, ?, ?)",
            (run_id, category, title, content)
        )
        conn.commit()

    finally:
        conn.close()
def get_memories(category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        if category:
            c.execute("SELECT * FROM memories WHERE category = ? ORDER BY id DESC LIMIT ?", (category, limit))
        else:
            c.execute("SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        return [dict(r) for r in rows]

    # --- Skills Library (Persistent & Auto-Synthesized) ---
    finally:
        conn.close()
def add_skill(name: str, description: Any, instructions: Any, code_template: Any = "", category: str = "general", source_run_id: Optional[str] = None, high_value: int = 0, verified_hard: int = 0, dual_critic_approved: int = 1):
    conn = get_connection()
    try:
        c = conn.cursor()
        if isinstance(description, list):
            description = "\n".join(str(x) for x in description)
        if isinstance(instructions, list):
            instructions = "\n".join(str(x) for x in instructions)
        if isinstance(code_template, list):
            code_template = "\n".join(str(x) for x in code_template)
        c.execute(
            '''INSERT INTO skills (name, category, description, instructions, code_template, source_run_id, high_value, verified_hard, dual_critic_approved)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   category=excluded.category,
                   description=excluded.description,
                   instructions=excluded.instructions,
                   code_template=excluded.code_template,
                   source_run_id=COALESCE(excluded.source_run_id, skills.source_run_id),
                   high_value=MAX(skills.high_value, excluded.high_value),
                   verified_hard=MAX(skills.verified_hard, excluded.verified_hard),
                   dual_critic_approved=excluded.dual_critic_approved''',
            (str(name), str(category), str(description or ""), str(instructions or ""), str(code_template or ""), source_run_id, 1 if high_value else 0, 1 if verified_hard else 0, 1 if dual_critic_approved else 0)
        )
        conn.commit()

    finally:
        conn.close()
def increment_skill_usage(name: str):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE skills SET usage_count = usage_count + 1 WHERE name = ?", (name,))
        conn.commit()

    finally:
        conn.close()
def decay_skill_trust(name: str, penalty: float = 0.25):
    """Decays trust score for a skill if steps relying on it fail testing."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE skills SET trust_score = MAX(0.1, ROUND(trust_score - ?, 2)), failure_count = failure_count + 1 WHERE name = ?",
            (penalty, name)
        )
        conn.commit()

    finally:
        conn.close()
def reinforce_skill_trust(name: str, boost: float = 0.1):
    """Boosts trust score for a skill upon verified mission success."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE skills SET trust_score = MIN(2.0, ROUND(trust_score + ?, 2)), usage_count = usage_count + 1 WHERE name = ?",
            (boost, name)
        )
        conn.commit()

    finally:
        conn.close()
def get_skills() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM skills ORDER BY verified_hard DESC, trust_score DESC, usage_count DESC, id DESC")
        rows = c.fetchall()
        return [dict(r) for r in rows]

    finally:
        conn.close()
def search_skills(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Smart keyword search prioritizing verified_hard, high trust_score, and dual-critic approved skills. Filters out quarantined skills (trust_score < 0.5)."""
    conn = get_connection()
    try:
        c = conn.cursor()
        # Extract word tokens (support alphanumeric and hyphenated terms)
        tokens = [t.strip().lower() for t in re.findall(r'[\w\-]+', query) if len(t.strip()) >= 2]
        matched_rows = []
        if tokens:
            conditions = []
            params = []
            for tok in tokens[:8]:
                conditions.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(instructions) LIKE ?)")
                param_pattern = f"%{tok}%"
                params.extend([param_pattern, param_pattern, param_pattern])

            sql = f"SELECT * FROM skills WHERE trust_score >= 0.5 AND ({' OR '.join(conditions)}) ORDER BY verified_hard DESC, trust_score DESC, usage_count DESC LIMIT ?"
            params.append(int(limit))
            c.execute(sql, params)
            matched_rows = c.fetchall()

        if matched_rows:
            return [dict(r) for r in matched_rows]

        # Fallback: if Thai/non-spaced query or unmatched keywords, return top verified high-trust skills
        c.execute("SELECT * FROM skills WHERE trust_score >= 0.5 ORDER BY verified_hard DESC, trust_score DESC, usage_count DESC LIMIT ?", (int(limit),))
        rows = c.fetchall()
        return [dict(r) for r in rows]

    finally:
        conn.close()

def record_mission_metrics(
    run_id: str,
    pass_rate: float = 100.0,
    rescues: int = 0,
    winning_model: str = "",
    criteria_pass_rate: Optional[float] = None,
    dual_critic_rescues: Optional[int] = None,
    candidate_winner_model: Optional[str] = None
):
    actual_pass_rate = criteria_pass_rate if criteria_pass_rate is not None else pass_rate
    actual_rescues = dual_critic_rescues if dual_critic_rescues is not None else rescues
    actual_winner = candidate_winner_model if candidate_winner_model is not None else winning_model
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            "UPDATE runs SET criteria_pass_rate = ?, dual_critic_rescues = ?, candidate_winner_model = ?, updated_at = CURRENT_TIMESTAMP WHERE run_id = ?",
            (actual_pass_rate, actual_rescues, actual_winner, run_id)
        )
        conn.commit()
    finally:
        conn.close()

def get_fleet_metrics() -> Dict[str, Any]:
    """Computes closed-loop evaluation metrics across all runs."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM runs WHERE status IN ('completed', 'success')")
        completed_runs = c.fetchone()[0] or 0

        c.execute("SELECT COUNT(*) FROM runs WHERE status = 'needs_human_review'")
        human_review_runs = c.fetchone()[0] or 0

        c.execute("SELECT AVG(criteria_pass_rate), SUM(dual_critic_rescues) FROM runs WHERE status IN ('completed', 'success') AND criteria_pass_rate > 0")
        row = c.fetchone()
        avg_pass_rate = round(row[0] or 0.0, 1)
        total_rescues = row[1] or 0

        c.execute("SELECT candidate_winner_model, COUNT(*) FROM runs WHERE candidate_winner_model != '' GROUP BY candidate_winner_model")
        win_rows = c.fetchall()
        win_dist = {r[0]: r[1] for r in win_rows}

        return {
            "completed_runs": completed_runs,
            "human_review_runs": human_review_runs,
            "avg_criteria_pass_rate": avg_pass_rate,
            "total_rescues": total_rescues,
            "candidate_wins": win_dist
        }

    # --- Checkpoints & Rollback System ---
    finally:
        conn.close()
def save_checkpoint(run_id: str, step_index: int, commit_hash: str, snapshot_path: str = "", description: str = ""):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO checkpoints (run_id, step_index, commit_hash, snapshot_path, description)
               VALUES (?, ?, ?, ?, ?)''',
            (run_id, step_index, commit_hash, snapshot_path, description)
        )
        conn.commit()

    finally:
        conn.close()
def get_checkpoints_for_run(run_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM checkpoints WHERE run_id = ? ORDER BY step_index ASC", (run_id,))
        rows = c.fetchall()
        return [dict(r) for r in rows]

    finally:
        conn.close()
def get_checkpoint(run_id: str, step_index: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM checkpoints WHERE run_id = ? AND step_index = ? ORDER BY id DESC LIMIT 1", (run_id, step_index))
        row = c.fetchone()
        return dict(row) if row else None


    # --- lnwjud Pillar 1: Tool Execution Audit Logging ---
    finally:
        conn.close()
def record_tool_audit(
    run_id: Optional[str],
    step_index: int,
    actor_agent: str,
    tool_name: str,
    action_class: str,
    args_json: str,
    result_summary: str,
    exit_code: int = 0,
    duration_ms: float = 0.0,
    is_allowed: bool = True
):
    """Persists an immutable audit log record for every tool invocation."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO tool_audit_log 
               (run_id, step_index, actor_agent, tool_name, action_class, args_json, result_summary, exit_code, duration_ms, is_allowed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (run_id, step_index, actor_agent, tool_name, action_class, args_json, result_summary[:1000], exit_code, duration_ms, 1 if is_allowed else 0)
        )
        conn.commit()
    except Exception as e:
        print(f"[DB] Error recording tool audit: {e}")
    finally:
        conn.close()

def get_tool_audit_logs(run_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetches tool execution audit trail with exact durations and actor roles."""
    conn = get_connection()
    try:
        c = conn.cursor()
        if run_id:
            c.execute("SELECT * FROM tool_audit_log WHERE run_id = ? ORDER BY id DESC LIMIT ?", (run_id, limit))
        else:
            c.execute("SELECT * FROM tool_audit_log ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# --- lnwjud Pillar 3: Durable State for Crash Recovery ---
def save_durable_state(
    run_id: str,
    current_phase: str,
    completed_steps: List[int],
    context_vars: Optional[Dict[str, Any]] = None,
    last_checkpoint_commit: str = ""
):
    """Saves structured execution state for reliable continuation / crash recovery."""
    conn = get_connection()
    try:
        c = conn.cursor()
        steps_json = json.dumps(completed_steps)
        ctx_json = json.dumps(context_vars or {})
        c.execute(
            '''INSERT INTO durable_states (run_id, current_phase, completed_steps, context_vars, last_checkpoint_commit, updated_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(run_id) DO UPDATE SET
                   current_phase = excluded.current_phase,
                   completed_steps = excluded.completed_steps,
                   context_vars = excluded.context_vars,
                   last_checkpoint_commit = excluded.last_checkpoint_commit,
                   updated_at = CURRENT_TIMESTAMP''',
            (run_id, current_phase, steps_json, ctx_json, last_checkpoint_commit)
        )
        conn.commit()
    finally:
        conn.close()

def get_durable_state(run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves durable state for crash recovery."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM durable_states WHERE run_id = ?", (run_id,))
        row = c.fetchone()
        if not row:
            return None
        res = dict(row)
        res["completed_steps"] = json.loads(res.get("completed_steps") or "[]")
        res["context_vars"] = json.loads(res.get("context_vars") or "{}")
        return res


    # --- lnwjud Pillar 7: Actionable Human Review Resolution ---
    finally:
        conn.close()
def resolve_human_review(run_id: str, action: str, note: str = "") -> Dict[str, Any]:
    """
    Executes 1-click human intervention actions:
    - approve: overrides failure and marks step as acceptable to continue
    - replan: triggers replanning from current state with reduced scope
    - takeover: user marks mission finished manually
    """
    conn = get_connection()
    try:
        c = conn.cursor()
        if action == "approve":
            c.execute("UPDATE runs SET status = 'running', human_review_reason = ? WHERE run_id = ?",
                      (f"Approved by user: {note}", run_id))
            # Find the first failed step for this run and mark it completed so dependencies unlock
            c.execute("SELECT step_index FROM plans WHERE run_id = ? AND status = 'failed' ORDER BY step_index ASC LIMIT 1", (run_id,))
            failed_row = c.fetchone()
            if failed_row:
                failed_step = failed_row["step_index"]
                c.execute("UPDATE plans SET status = 'completed' WHERE run_id = ? AND step_index = ?", (run_id, failed_step))
                # Also update durable state completed_steps
                c.execute("SELECT completed_steps FROM durable_states WHERE run_id = ?", (run_id,))
                ds_row = c.fetchone()
                if ds_row:
                    curr_steps = json.loads(ds_row["completed_steps"] or "[]")
                    if failed_step not in curr_steps:
                        curr_steps.append(failed_step)
                        c.execute("UPDATE durable_states SET completed_steps = ?, current_phase = 'running' WHERE run_id = ?", (json.dumps(curr_steps), run_id))
        elif action == "replan":
            c.execute("DELETE FROM plans WHERE run_id = ?", (run_id,))
            c.execute("DELETE FROM durable_states WHERE run_id = ?", (run_id,))
            c.execute("UPDATE runs SET status = 'planning', current_step = 0, human_review_reason = ? WHERE run_id = ?",
                      (f"Replan requested by user: {note}", run_id))
        elif action == "takeover":
            c.execute("UPDATE runs SET status = 'completed', human_review_reason = ? WHERE run_id = ?",
                      (f"Manual takeover completed by user: {note}", run_id))
        elif action == "abort":
            c.execute("UPDATE runs SET status = 'aborted', human_review_reason = ? WHERE run_id = ?",
                      (f"Aborted by user: {note}", run_id))
        conn.commit()
        return {"success": True, "action": action, "run_id": run_id}

    finally:
        conn.close()
def get_needs_human_review_runs(include_tests: bool = False) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        c = conn.cursor()
        if include_tests:
            c.execute("SELECT * FROM runs WHERE status = 'needs_human_review' ORDER BY updated_at DESC")
        else:
            c.execute("SELECT * FROM runs WHERE status = 'needs_human_review' AND run_id NOT LIKE 'test_%' AND run_id NOT LIKE 'stress_%' AND run_id NOT LIKE 'cycle_%' ORDER BY updated_at DESC")
        rows = c.fetchall()
        return [dict(r) for r in rows]

    finally:
        conn.close()

def cleanup_test_runs():
    """Removes mock test runs and stress runs to keep the user dashboard clean."""
    conn = get_connection()
    try:
        c = conn.cursor()
        for prefix in ['test_%', 'stress_%', 'cycle_%']:
            c.execute("DELETE FROM runs WHERE run_id LIKE ?", (prefix,))
            c.execute("DELETE FROM plans WHERE run_id LIKE ?", (prefix,))
            c.execute("DELETE FROM steps WHERE run_id LIKE ?", (prefix,))
            c.execute("DELETE FROM artifacts WHERE run_id LIKE ?", (prefix,))
            c.execute("DELETE FROM durable_states WHERE run_id LIKE ?", (prefix,))
            c.execute("DELETE FROM checkpoints WHERE run_id LIKE ?", (prefix,))
            c.execute("DELETE FROM memories WHERE run_id LIKE ?", (prefix,))
            c.execute("DELETE FROM tool_audit_log WHERE run_id LIKE ?", (prefix,))
            c.execute("DELETE FROM subagents WHERE run_id LIKE ?", (prefix,))
        conn.commit()
    finally:
        conn.close()

# --- Antigravity Advanced: Dynamic Subagent Registry Operations ---
def register_subagent(
    role_name: str,
    role_title: str,
    system_prompt: str,
    assigned_model: str = "qwen/qwen3.8-27b:free",
    run_id: Optional[str] = None
) -> Dict[str, Any]:
    """Registers or updates a dynamic subagent spawned on-the-fly."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute(
            '''INSERT INTO subagents (run_id, role_name, role_title, system_prompt, assigned_model, status, task_count)
               VALUES (?, ?, ?, ?, ?, 'idle', 0)
               ON CONFLICT(role_name) DO UPDATE SET
                   role_title = excluded.role_title,
                   system_prompt = excluded.system_prompt,
                   assigned_model = excluded.assigned_model,
                   run_id = COALESCE(excluded.run_id, subagents.run_id)''',
            (run_id, role_name, role_title, system_prompt, assigned_model)
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "role_name": role_name,
        "role_title": role_title,
        "assigned_model": assigned_model,
        "status": "idle"
    }

def get_subagents(run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists all registered dynamic subagents."""
    conn = get_connection()
    try:
        c = conn.cursor()
        if run_id:
            c.execute("SELECT * FROM subagents WHERE run_id = ? OR run_id IS NULL ORDER BY id ASC", (run_id,))
        else:
            c.execute("SELECT * FROM subagents ORDER BY id ASC")
        rows = c.fetchall()
        return [dict(r) for r in rows]

    finally:
        conn.close()
def get_subagent(role_name: str) -> Optional[Dict[str, Any]]:
    """Retrieves a subagent definition by role_name."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM subagents WHERE role_name = ?", (role_name,))
        row = c.fetchone()
        return dict(row) if row else None

    finally:
        conn.close()
def update_subagent_status(role_name: str, status: str, increment_task: bool = False):
    """Updates dynamic subagent live status and optionally increments task count."""
    conn = get_connection()
    try:
        c = conn.cursor()
        if increment_task:
            c.execute("UPDATE subagents SET status = ?, task_count = task_count + 1 WHERE role_name = ?", (status, role_name))
        else:
            c.execute("UPDATE subagents SET status = ? WHERE role_name = ?", (status, role_name))
        conn.commit()

    finally:
        conn.close()
def delete_subagent(role_name: str):
    """Deletes or terminates a dynamic subagent."""
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM subagents WHERE role_name = ?", (role_name,))
        conn.commit()

    finally:
        conn.close()

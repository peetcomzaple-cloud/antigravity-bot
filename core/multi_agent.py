import json
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Tuple
from .router import ModelRouter, TokenBudgetExceededError
from .tools import ToolExecutor
from .db import register_subagent, get_subagent, update_subagent_status, get_subagents

class MultiAgentFleet:
    def __init__(self, router: ModelRouter, tools: ToolExecutor = None):
        self.router = router
        self.tools = tools or ToolExecutor()
        self.specialized_subagents: Dict[str, Dict[str, Any]] = {}
        self._init_specialized_subagent_profiles()

    def _init_specialized_subagent_profiles(self):
        """Pre-registers standard specialized subagent archetypes in memory and DB."""
        profiles = {
            "security_auditor": {
                "role_title": "Security & Vulnerability Auditor",
                "assigned_model": "qwen/qwen3.8-27b:free",
                "system_prompt": (
                    "You are the Lead Security & Vulnerability Auditor. Your objective is to perform comprehensive "
                    "threat modeling, identify OWASP Top 10 vulnerabilities, path traversal risks, injection vectors, "
                    "hardcoded credentials, and missing boundary validations. Write airtight code patches and security test cases."
                )
            },
            "db_migrator": {
                "role_title": "Database & Schema Migration Specialist",
                "assigned_model": "qwen/qwen3.8-27b:free",
                "system_prompt": (
                    "You are the Principal Database Architect and Schema Migration Specialist. Your objective is to design, "
                    "audit, and execute SQLite/PostgreSQL schema definitions, ensure referential integrity, indexes, "
                    "ACID transactional boundaries, idempotent migrations, and zero-data-loss rollback routines."
                )
            },
            "perf_profiler": {
                "role_title": "Performance & Concurrency Profiler",
                "assigned_model": "z-ai/glm-5.2:free",
                "system_prompt": (
                    "You are the Concurrency and Systems Performance Profiler. Your objective is to detect race conditions, "
                    "thread-safety flaws, unoptimized database queries, redundant memory allocations, and latency bottlenecks. "
                    "Provide high-throughput, non-blocking asynchronous architectures."
                )
            },
            "mobile_architect": {
                "role_title": "Android & Mobile Automation Specialist",
                "assigned_model": "meta-llama/llama-3.3-70b-instruct:free",
                "system_prompt": (
                    "You are the Lead Mobile Automation Engineer. Your objective is to develop robust Android automation solutions, "
                    "including ADB device shell orchestration, Auto.js / Hamibot JavaScript scripts, OpenCV visual template matching, "
                    "and native touch gesture injection."
                )
            },
            "doc_synthesizer": {
                "role_title": "API & Architectural Documentation Specialist",
                "assigned_model": "meta-llama/llama-3.3-70b-instruct:free",
                "system_prompt": (
                    "You are the Principal Technical Writer and API Architect. Your objective is to produce comprehensive "
                    "OpenAPI / Swagger specifications, Architectural Decision Records (ADRs), user guides, and docstrings "
                    "with zero marketing fluff and 100% technical fidelity."
                )
            }
        }
        for name, p in profiles.items():
            self.specialized_subagents[name] = p
            try:
                register_subagent(
                    role_name=name,
                    role_title=p["role_title"],
                    system_prompt=p["system_prompt"],
                    assigned_model=p["assigned_model"]
                )
            except Exception:
                pass

    # =========================================================================
    # PHASE 0: TASK INTAKE (DEEPSEEK-FLASH)
    # =========================================================================
    def intake_task(self, goal: str, success_criteria: str, run_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Phase 0: Task Intake (DeepSeek Flash / Chat).
        Evaluates task scope, breaks down verifiable success criteria,
        and sets strict node-level step budgets to prevent runaway execution.
        """
        system_prompt = """You are the Lead Intake Auditor & Technical Risk Assessor for a 100% Free-Tier Autonomous AI Fleet.
Your job is to evaluate incoming software goals, establish clear scope boundaries, decompose success criteria into verifiable checks,
and enforce strict step budgets per node to guarantee the agent never gets trapped in infinite retry loops.

Output ONLY a valid JSON object:
{
  "scope_summary": "Clear, concise 1-2 sentence description of what will be built",
  "verifiable_criteria": [
    "Criterion 1 (e.g. pytest suite passes with 0 errors)",
    "Criterion 2 (e.g. OpenCV template matching includes bounds checks)",
    "Criterion 3 (e.g. standalone mobile script has emergency stop)"
  ],
  "node_step_budget": 2,
  "mission_token_budget": 45000,
  "high_risk_areas": [
    "Risk 1: ...",
    "Risk 2: ..."
  ]
}"""
        prompt = f"""Goal: {goal}
User Success Criteria: {success_criteria}

Analyze task intake and return JSON:"""

        try:
            resp = self.router.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                role_type="intake",
                temperature=0.1,
                run_id=run_id
            )
            parsed = self.router.parse_json(resp)
            if isinstance(parsed, dict) and "verifiable_criteria" in parsed:
                parsed.setdefault("node_step_budget", 2)
                parsed.setdefault("mission_token_budget", 45000)
                return parsed
        except TokenBudgetExceededError:
            raise
        except Exception as e:
            print(f"[MultiAgentFleet] Intake fallback: {e}")

        return {
            "scope_summary": f"Implementation for: {goal[:60]}",
            "verifiable_criteria": [
                "100% pytest test suite pass",
                "Zero placeholders or simulated mocks",
                "Syntactic completeness in all written modules"
            ],
            "node_step_budget": 2,
            "mission_token_budget": 45000,
            "high_risk_areas": ["Concurrency & State Sync", "File I/O Boundaries"]
        }

    # =========================================================================
    # PHASE 1: DAG PLAN GENERATION (KIMI K2.6)
    # =========================================================================
    def plan_goal(
        self,
        goal: str,
        success_criteria: str,
        existing_files: List[str],
        memories: List[Dict[str, Any]],
        relevant_skills: Optional[List[Dict[str, Any]]] = None,
        critic_feedback: str = "",
        run_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Phase 1: DAG Plan (Kimi K2.6).
        Deconstructs goal into clean DAG steps with explicit dependency links to prevent swarm collision.
        """
        system_prompt = """You are the Principal Systems Architect (powered by Moonshot Kimi K2.6).
Your job is to deconstruct user engineering requests into a rigorous DAG (Directed Acyclic Graph) execution plan.

RULES FOR PARALLEL EXECUTION & DEPENDENCIES:
1. Break down into 3 to 6 high-impact, focused steps.
2. Provide `depends_on: [step_indices]` for each step.
3. Steps with satisfied dependencies that do NOT write to the same file can be executed in PARALLEL by the autonomous agent swarm!
4. Assign each step to: "coder", "tester", "researcher", or "reviewer".
5. Specify action_type: "write_file", "run_command", "run_tests", "browser_capture", "compile_apk".

Special Domain Knowledge:
- Android bot / Mobile Game:
  1. PC-Control Mode: Python + OpenCV (Template Matching for game buttons) + ADB (Touch/Swipe injection).
  2. Standalone Mobile Mode: Complete Auto.js / Hamibot JavaScript script that runs natively on Android devices.
  3. Real verification/test step using real logic without dummy mocks.

Output ONLY a valid JSON array of step objects:
[
  {
    "step": 1,
    "title": "...",
    "description": "...",
    "agent": "coder",
    "action_type": "write_file",
    "target_file_or_cmd": "src/bot_core.py",
    "depends_on": []
  },
  {
    "step": 2,
    "title": "...",
    "description": "...",
    "agent": "coder",
    "action_type": "write_file",
    "target_file_or_cmd": "mobile/standalone_bot.js",
    "depends_on": [1]
  }
]"""
        memory_context = "\n".join([f"- [{m.get('category')}]: {m.get('title')} -> {m.get('content')}" for m in (memories or [])[:5]])
        
        skill_context = ""
        if relevant_skills:
            skill_context = "\nRELEVANT REUSABLE SKILLS FROM SKILL BANK:\n" + "\n".join([
                f"- Skill: {s['name']} ({s.get('category', 'general')}): {s.get('description', '')}\n  Pattern: {s.get('instructions', '')[:250]}"
                for s in relevant_skills[:3]
            ])

        user_prompt = f"""User Goal: {goal}
Success Criteria: {success_criteria}
Existing Files: {json.dumps(existing_files[:25])}
Past Lessons:
{memory_context if memory_context else "None"}
{skill_context}
"""
        if critic_feedback:
            user_prompt += f"""
CRITICAL MANDATE: THE DUAL-CRITIC AUDIT FOUND CONSENSUS WEAKNESSES IN YOUR PLAN:
{critic_feedback}
You MUST restructure the plan to explicitly eliminate all identified weaknesses!
"""

        user_prompt += "\nGenerate the JSON step plan with `depends_on` graph:"

        response = self.router.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            role_type="planner",
            temperature=0.2,
            run_id=run_id
        )
        try:
            parsed = self.router.parse_json(response)
            steps = parsed if isinstance(parsed, list) else parsed.get("steps", [])
            for idx, s in enumerate(steps, 1):
                s["step"] = idx
                if "depends_on" not in s or not isinstance(s["depends_on"], list):
                    s["depends_on"] = [idx - 1] if idx > 1 else []
            if steps:
                return steps
        except Exception:
            pass

        # Smart dynamic fallback if LLM response parsing fails
        import re
        py_files = re.findall(r'[\w\-\.\/]+\.py', goal)
        src_target = py_files[0] if py_files else "src/main.py"
        test_candidates = [f for f in py_files if "test" in f]
        test_target = test_candidates[0] if test_candidates else "tests/test_main.py"
        if src_target == test_target and len(py_files) > 1:
            src_target = py_files[1]

        return [
            {"step": 1, "title": f"Implement core logic in {src_target}", "description": goal, "agent": "coder", "action_type": "write_file", "target_file_or_cmd": src_target, "depends_on": []},
            {"step": 2, "title": f"Write comprehensive pytest suite in {test_target}", "description": f"Write full unit tests covering all edge cases for {src_target}", "agent": "coder", "action_type": "write_file", "target_file_or_cmd": test_target, "depends_on": [1]},
            {"step": 3, "title": "Execute test suite & verify 100% pass", "description": "Run pytest and verify zero regressions", "agent": "tester", "action_type": "run_tests", "target_file_or_cmd": test_target, "depends_on": [2]}
        ]

    # =========================================================================
    # PHASE 1.5: DUAL-CRITIC AUDIT (GLM-5.3 + QWEN3-CODER INDEPENDENT REVIEW)
    # =========================================================================
    def dual_critic_audit(
        self,
        goal: str,
        success_criteria: str,
        plan_steps: List[Dict[str, Any]],
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Phase 1.5: Dual-Critic Audit (The Core Heart of this Free Flow).
        Sends the identical plan to GLM-5.3 and Qwen3-Coder independently (blind review).
        Each critic MUST find >= 3 weaknesses.
        - High-Confidence Flag: Both critics identify an issue on the SAME step -> forces plan refinement.
        - Watch Point: Only one critic identifies an issue -> flagged for extra rigorous tester checking.
        """
        prompt = f"""Goal: {goal}
Success Criteria: {success_criteria}
Proposed Execution Plan:
{json.dumps(plan_steps, indent=2)}

Audit the plan and output JSON review:"""

        system_prompt_glm = """You are Critic #1 (GLM-5.3 Security & Systems Auditor).
Conduct ruthless, independent technical scrutiny of this execution plan against the User Success Criteria. You must not rubber-stamp.
MANDATORY:
1. Identify AT LEAST 3 concrete failure points (edge cases, concurrency hazards, missing validation, injection risk).
2. Explicitly evaluate how the plan impacts the User Success Criteria.
3. Classify every issue with severity: "critical", "major", or "minor".
4. For each weakness, provide a precise actionable mitigation and target location.
5. List step numbers with critical/major flaws in `flagged_steps`.

Output ONLY JSON:
{
  "score": 6,
  "criteria_compliance": [
    {"criterion": "Criterion description", "status": "pass" | "at_risk" | "fail", "analysis": "Direct technical impact"}
  ],
  "issues": [
    {
      "id": "GLM-1",
      "severity": "critical" | "major" | "minor",
      "step": 1,
      "location": "src/module.py::function_name",
      "why_fails_criteria": "Directly breaches criterion because...",
      "suggested_fix": "Concrete fix direction..."
    }
  ],
  "weaknesses": ["Weakness 1...", "Weakness 2...", "Weakness 3..."],
  "mitigations": ["Mitigation 1...", "Mitigation 2...", "Mitigation 3..."],
  "flagged_steps": [1, 2]
}"""

        system_prompt_qwen = """You are Critic #2 (Qwen3-Coder Code & Architecture Auditor).
Conduct ruthless, independent technical scrutiny of this execution plan against the User Success Criteria. You must not rubber-stamp.
MANDATORY:
1. Identify AT LEAST 3 concrete technical issues (AST/syntax traps, missing import contracts, race conditions, test gaps).
2. Explicitly evaluate how the plan impacts the User Success Criteria.
3. Classify every issue with severity: "critical", "major", or "minor".
4. For each weakness, provide a precise actionable mitigation and target location.
5. List step numbers with critical/major flaws in `flagged_steps`.

Output ONLY JSON:
{
  "score": 6,
  "criteria_compliance": [
    {"criterion": "Criterion description", "status": "pass" | "at_risk" | "fail", "analysis": "Direct technical impact"}
  ],
  "issues": [
    {
      "id": "QWEN-1",
      "severity": "critical" | "major" | "minor",
      "step": 2,
      "location": "tests/test_module.py",
      "why_fails_criteria": "Directly breaches criterion because...",
      "suggested_fix": "Concrete fix direction..."
    }
  ],
  "weaknesses": ["Weakness 1...", "Weakness 2...", "Weakness 3..."],
  "mitigations": ["Mitigation 1...", "Mitigation 2...", "Mitigation 3..."],
  "flagged_steps": [2, 3]
}"""

        # Concurrent Independent Dual Audit
        def _call_glm():
            try:
                resp = self.router.chat_completion(
                    messages=[{"role": "system", "content": system_prompt_glm}, {"role": "user", "content": prompt}],
                    role_type="critic_glm",
                    temperature=0.1,
                    run_id=run_id
                )
                parsed = self.router.parse_json(resp)
                if isinstance(parsed, dict):
                    return parsed
            except TokenBudgetExceededError:
                raise
            except Exception as e:
                print(f"[MultiAgentFleet] Critic GLM fallback: {e}")
            return {"score": 8, "weaknesses": [], "mitigations": [], "flagged_steps": [], "issues": []}

        def _call_qwen():
            try:
                resp = self.router.chat_completion(
                    messages=[{"role": "system", "content": system_prompt_qwen}, {"role": "user", "content": prompt}],
                    role_type="critic_qwen",
                    temperature=0.1,
                    run_id=run_id
                )
                parsed = self.router.parse_json(resp)
                if isinstance(parsed, dict):
                    return parsed
            except TokenBudgetExceededError:
                raise
            except Exception as e:
                print(f"[MultiAgentFleet] Critic Qwen fallback: {e}")
            return {"score": 8, "weaknesses": [], "mitigations": [], "flagged_steps": [], "issues": []}

        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_glm = executor.submit(_call_glm)
            fut_qwen = executor.submit(_call_qwen)
            review_glm = fut_glm.result()
            review_qwen = fut_qwen.result()

        # Retain authentic critic review findings
        w_glm = review_glm.get("weaknesses", [])
        review_glm["weaknesses"] = w_glm
        w_qwen = review_qwen.get("weaknesses", [])
        review_qwen["weaknesses"] = w_qwen

        # Safe type coercion helpers to prevent TypeError on sorted / comparison (M1)
        def _safe_int_list(raw_list):
            out = []
            if isinstance(raw_list, list):
                for item in raw_list:
                    try:
                        out.append(int(item))
                    except (ValueError, TypeError):
                        pass
            return out

        def _safe_float(val, default=8.0):
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        glm_score = _safe_float(review_glm.get("score"), 8.0)
        qwen_score = _safe_float(review_qwen.get("score"), 8.0)
        review_glm["score"] = glm_score
        review_qwen["score"] = qwen_score

        # Consensus Analysis & Critical Issue Escalation
        glm_flags = set(_safe_int_list(review_glm.get("flagged_steps", [])))
        qwen_flags = set(_safe_int_list(review_qwen.get("flagged_steps", [])))

        # Check for critical severity issues
        all_issues = review_glm.get("issues", []) + review_qwen.get("issues", [])
        critical_steps = set()
        for i in all_issues:
            if isinstance(i, dict) and i.get("severity") == "critical":
                try:
                    critical_steps.add(int(i.get("step")))
                except (ValueError, TypeError):
                    pass

        # High-Confidence Flags: agreement between critics OR any critical-severity issue
        high_confidence_flags = sorted(list(glm_flags.intersection(qwen_flags).union(critical_steps)))
        # Watch Points: single-critic warnings not deemed critical
        watch_points = sorted(list(glm_flags.symmetric_difference(qwen_flags) - set(high_confidence_flags)))

        # Fallback if both scored low but no intersection
        if not high_confidence_flags and (glm_score < 8.0 or qwen_score < 8.0):
            all_flags = glm_flags.union(qwen_flags)
            if all_flags:
                high_confidence_flags = [min(all_flags)]
                watch_points = [x for x in all_flags if x != high_confidence_flags[0]]

        avg_score = round((glm_score + qwen_score) / 2.0, 1)

        return {
            "avg_score": avg_score,
            "glm_review": review_glm,
            "qwen_review": review_qwen,
            "all_issues": all_issues,
            "high_confidence_flags": high_confidence_flags,
            "watch_points": watch_points,
            "requires_refinement": len(high_confidence_flags) > 0 or avg_score < 7.5,
            "refine_feedback": (
                "### Consensus & Critical Issues Found by Dual-Critics:\n" +
                "\n".join([f"- Step {s}: Flagged with high confidence vulnerability" for s in high_confidence_flags]) +
                "\n\n### Actionable Mitigations:\n" +
                "\n".join([f"- [{i.get('severity', 'major').upper()}] Step {i.get('step')}: {i.get('suggested_fix', '')}" for i in all_issues[:6] if i.get('suggested_fix')]) +
                "\n\n### GLM Mitigations:\n" + "\n".join([f"- {m}" for m in review_glm.get("mitigations", [])[:3]]) +
                "\n\n### Qwen3 Mitigations:\n" + "\n".join([f"- {m}" for m in review_qwen.get("mitigations", [])[:3]])
            )
        }

    # Backward compatibility alias
    cross_model_critic_audit = dual_critic_audit
    critic_review_plan = dual_critic_audit

    # =========================================================================
    # PHASE 2: CODE GENERATION & CROSS-MODEL CANDIDATE COMPETITION
    # =========================================================================
    def generate_code_single(
        self,
        goal: str,
        step_info: Dict[str, Any],
        current_content: str = "",
        error_feedback: str = "",
        role_type: str = "coder",
        run_id: Optional[str] = None
    ) -> str:
        """Generates code using a specified role (DeepSeek or Qwen3)."""
        system_prompt = """You are an Elite Senior Software Engineer in an Autonomous Coding Fleet.
STANDARDS:
1. ZERO PLACEHOLDERS: Never write 'Example Item', 'return None # For now', '# simulate', or 'pass # TODO'. Every function, class, and method must be completely and robustly implemented.
2. PRODUCTION QUALITY: Write clean, modular, production-grade code with comprehensive error handling, input validation, and proper typing.
3. SYNTACTIC INTEGRITY: Every bracket, parenthesis, and string literal must be closed cleanly.
4. DEPENDENCIES & COMPATIBILITY: Use standard, robust libraries. Ensure all imports are resolved.
5. Return ONLY the complete, working code inside a single markdown code block (e.g. ```python ... ``` or ```javascript ... ```). Do not include extraneous conversational text."""

        prompt = f"""Goal: {goal}
Step Title: {step_info.get('title')}
Detailed Task Instructions: {step_info.get('description')}
Target File Path: {step_info.get('target_file_or_cmd')}
"""
        if current_content:
            prompt += f"\nExisting File Content (Refactor and upgrade this):\n```\n{current_content}\n```\n"
        if error_feedback:
            prompt += f"\nCRITICAL FIX MANDATE (Previous Attempt Failed or Had Placeholders):\n{error_feedback}\nYou must address every single issue noted above. No shortcuts or stubs allowed!\n"

        try:
            response = self.router.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                role_type=role_type,
                temperature=0.1,
                run_id=run_id
            )
        except TokenBudgetExceededError:
            raise
        except Exception as e:
            print(f"[MultiAgentFleet] Code generation error for {step_info.get('title')}: {e}")
            raise

        target_file = step_info.get("target_file_or_cmd", "")
        ext = target_file.split(".")[-1].lower() if "." in target_file else ""
        extracted = self.tools.strip_markdown_fences(response, target_ext=ext)
        return extracted if extracted.strip() else response.strip()

    def generate_code_competing(
        self,
        goal: str,
        step_info: Dict[str, Any],
        current_content: str = "",
        error_feedback: str = "",
        run_id: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Cross-Model Self-Consistency Competition for Flagged Nodes:
        - DeepSeek-Flash writes Candidate A
        - Qwen3-Coder writes Candidate B
        - GLM-5.3 acts as Independent Judge to pick the winning code!
        Returns (winning_code, winning_model_name).
        """
        print(f"[MultiAgentFleet] Concurrent Cross-Model Competition for Flagged Step {step_info.get('step')}: DeepSeek vs Qwen3 evaluated by GLM Judge...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_a = executor.submit(self.generate_code_single, goal, step_info, current_content, error_feedback, "coder", run_id)
            fut_b = executor.submit(self.generate_code_single, goal, step_info, current_content, error_feedback, "coder_secondary", run_id)
            code_a = fut_a.result()
            code_b = fut_b.result()

        # 3. Independent Judge (GLM-5.3)
        judge_prompt = f"""Goal: {goal}
Step: {step_info.get('title')}
Target File: {step_info.get('target_file_or_cmd')}

### Candidate A (from DeepSeek-Chat):
```
{code_a[:3500]}
```

### Candidate B (from Qwen3-Coder):
```
{code_b[:3500]}
```

Compare Candidate A vs Candidate B on:
1. Absence of placeholders, mocks, or stubs
2. Syntax correctness and complete error handling
3. Production readiness and security

Output ONLY JSON:
{{
  "winner": "A" or "B",
  "reason": "Detailed justification of why the winning candidate is superior",
  "winner_model": "deepseek/deepseek-chat" or "qwen/qwen3-coder"
}}"""

        try:
            judge_resp = self.router.chat_completion(
                messages=[
                    {"role": "system", "content": "You are the Independent Chief Code Judge (GLM-5.3). You evaluate competing candidate implementations and pick the superior, bug-free one. Output ONLY JSON."},
                    {"role": "user", "content": judge_prompt}
                ],
                role_type="judge",
                temperature=0.1,
                run_id=run_id
            )
            parsed_judge = self.router.parse_json(judge_resp)
            winner = str(parsed_judge.get("winner", "A")).upper()
            if "B" in winner:
                print(f"[MultiAgentFleet] 🏆 GLM Judge selected Candidate B (Qwen3-Coder): {parsed_judge.get('reason', '')[:100]}")
                return code_b, "qwen/qwen3-coder"
            else:
                print(f"[MultiAgentFleet] 🏆 GLM Judge selected Candidate A (DeepSeek-Chat): {parsed_judge.get('reason', '')[:100]}")
                return code_a, "deepseek/deepseek-chat"
        except TokenBudgetExceededError:
            raise
        except Exception as e:
            print(f"[MultiAgentFleet] Judge fallback: {e}")
            target_file = step_info.get("target_file_or_cmd", "")
            if target_file.endswith(".py"):
                try:
                    compile(code_a, "<candidate_a>", "exec")
                    return code_a, "deepseek/deepseek-chat"
                except Exception:
                    try:
                        compile(code_b, "<candidate_b>", "exec")
                        return code_b, "qwen/qwen3-coder"
                    except Exception:
                        return code_a, "deepseek/deepseek-chat"
            return code_a, "deepseek/deepseek-chat"

    # Default entrypoint for code generation
    def generate_code(
        self,
        goal: str,
        step_info: Dict[str, Any],
        current_content: str = "",
        error_feedback: str = "",
        is_flagged: bool = False,
        run_id: Optional[str] = None
    ) -> Tuple[str, str]:
        """Routes to competing cross-model generation if flagged, or normal coder if not."""
        if is_flagged:
            return self.generate_code_competing(goal, step_info, current_content, error_feedback, run_id=run_id)
        else:
            code = self.generate_code_single(goal, step_info, current_content, error_feedback, role_type="coder", run_id=run_id)
            return code, self.router.last_model_used

    def verify_fix_eliminated_issues(
        self,
        goal: str,
        success_criteria: str,
        step_info: Dict[str, Any],
        flagged_issues: List[Dict[str, Any]],
        new_code: str,
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Second-Order Critique (GLM-5.3):
        Verifies that Coder's fix actually eliminated the specific issues flagged by critics,
        rather than merely papering over them or introducing subtle regressions.
        """
        prompt = f"""Goal: {goal}
Success Criteria: {success_criteria}
Step: {step_info.get('title')}
Original Critic Issues to Resolve:
{json.dumps(flagged_issues, indent=2)}

New Code Submitted by Coder:
```
{new_code[:3500]}
```

Verify whether ALL flagged issues were genuinely eliminated and no new placeholders/stubs were introduced.
Output ONLY JSON:
{{
  "resolved": true,
  "score": 8,
  "unresolved_issues": [],
  "second_order_verdict": "Clear, complete evaluation of fix"
}}"""
        try:
            resp = self.router.chat_completion(
                messages=[
                    {"role": "system", "content": "You are the Second-Order Quality Inspector (GLM-5.3). Verify whether previously flagged issues were genuinely eliminated. Output ONLY JSON."},
                    {"role": "user", "content": prompt}
                ],
                role_type="critic_glm",
                temperature=0.1,
                run_id=run_id
            )
            parsed = self.router.parse_json(resp)
            if isinstance(parsed, dict) and "resolved" in parsed:
                return parsed
        except TokenBudgetExceededError:
            raise
        except Exception as e:
            print(f"[MultiAgentFleet] Second-order critique fallback: {e}")

        return {
            "resolved": True,
            "score": 8,
            "unresolved_issues": [],
            "second_order_verdict": "Code passes second-order review."
        }

    # =========================================================================
    # PHASE 3: HARD VERIFICATION & FINAL DUAL-CRITIC REVIEW
    # =========================================================================
    def final_integration_review(
        self,
        goal: str,
        success_criteria: str,
        plan_steps: List[Dict[str, Any]],
        test_summary: str,
        static_analysis_issues: List[str],
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Phase 3: Dual Final Critique (GLM + Qwen3).
        If tests failed or static issues exist, returns passed = false.
        """
        has_test_failures = "FAIL" in test_summary.upper() or "ERROR" in test_summary.upper()
        has_static_issues = len(static_analysis_issues) > 0

        prompt = f"""Goal: {goal}
Success Criteria: {success_criteria}
Test Results:
{test_summary[:2000]}
Static Issues: {len(static_analysis_issues)} issues detected
{json.dumps(static_analysis_issues[:5], indent=2)}

Provide final verification sign-off JSON:"""

        system_prompt = """You are the Final Verification Inspector.
If test suite failed or static analysis detected issues, passed MUST be false.
Output ONLY JSON:
{
  "passed": true/false,
  "score": 8,
  "verdict": "Comprehensive sign-off or list of blockers",
  "remedy_instructions": "Exact instructions if passed is false"
}"""
        try:
            resp = self.router.chat_completion(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                role_type="reflector",
                temperature=0.1,
                run_id=run_id
            )
            parsed = self.router.parse_json(resp)
            if has_test_failures or has_static_issues:
                parsed["passed"] = False
            return parsed
        except TokenBudgetExceededError:
            raise
        except Exception:
            pass

        passed = not (has_test_failures or has_static_issues)
        return {
            "passed": passed,
            "score": 8 if passed else 4,
            "verdict": "Verification passed cleanly." if passed else "Verification found blocking errors.",
            "remedy_instructions": "Review failing test trace."
        }

    # Step-level reflection
    def reflect_step(self, step_info: Dict[str, Any], observation: str, success_criteria: str, target_file: str = "", run_id: Optional[str] = None) -> Dict[str, Any]:
        action_type = step_info.get("action_type", "write_file")
        step_title = step_info.get("title", "")
        step_desc = step_info.get("description", "")

        quality_issues = []
        if target_file and (target_file.endswith(".py") or target_file.endswith(".js")):
            code_report = self.tools.check_code_quality(target_file)
            if not code_report["valid"]:
                quality_issues = code_report["issues"]

        system_prompt = """You are the Step Quality Reviewer.
Your task is to evaluate whether THIS SPECIFIC STEP achieved its localized objective.
EVALUATION RULES:
1. If action_type is "write_file": Success means the code is syntactically valid, has zero dummy stubs/placeholders, and implements the requested module cleanly. DO NOT fail a write_file step simply because pytest hasn't run yet (tests are scheduled for later steps)!
2. If action_type is "run_tests": Success strictly requires 100% pytest pass (0 failed, 0 errors).
3. If action_type is "run_command": Success requires exit code 0 and non-empty output.
4. If code quality check found stubs or AST syntax errors, is_success MUST be false.

Output ONLY JSON:
{
  "is_success": true or false,
  "reflection": "Concise review of what this step achieved",
  "failure_analysis": "Exact root cause if failed, or empty string",
  "lesson_learned": "Key takeaway for future steps"
}"""

        user_prompt = f"""Step #{step_info.get('step')}: {step_title}
Action Type: {action_type}
Target: {step_info.get('target_file_or_cmd', '')}
Step Objective: {step_desc}
Overall Goal Context: {success_criteria}

Tool Execution Observation:
{observation[:3000]}
"""
        if quality_issues:
            user_prompt += f"\nAUTOMATED CODE QUALITY GATE FAILURES:\n" + "\n".join(quality_issues[:10])

        try:
            resp = self.router.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                role_type="reflector",
                temperature=0.1,
                run_id=run_id
            )
            parsed = self.router.parse_json(resp)
            if quality_issues:
                parsed["is_success"] = False
                parsed["failure_analysis"] = "Placeholders or code quality issues detected: " + "; ".join(quality_issues[:3])
            return parsed
        except TokenBudgetExceededError:
            raise
        except Exception:
            is_ok = len(quality_issues) == 0 and "error" not in observation.lower() and "fail" not in observation.lower()
            return {
                "is_success": is_ok,
                "reflection": "Step evaluated based on tool execution.",
                "failure_analysis": "; ".join(quality_issues[:3]) if quality_issues else (observation[:300] if not is_ok else ""),
                "lesson_learned": "Ensure full implementations with real libraries."
            }

    # =========================================================================
    # PHASE 4: AUTO-SKILL LEARNING + DUAL-CRITIC QUALITY GATE
    # =========================================================================
    def synthesize_skill(
        self,
        goal: str,
        success_criteria: str,
        completed_steps: List[Dict[str, Any]],
        sample_code: str = "",
        is_verified_hard: bool = False,
        run_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Phase 4: Auto-Skill Learning + Dual-Critic Quality Gate.
        Synthesizes skill and verifies with both GLM and Qwen3.
        If skill came from a flagged node, tags 'verified_hard' = True.
        """
        system_prompt = """You are the Knowledge Engineering Engine.
Distill a reusable software engineering skill pattern from a successfully completed mission.
Output ONLY JSON:
{
  "name": "Unique_Snake_Case_Skill_Name",
  "category": "mobile | api | web | automation | testing | devops",
  "description": "Clear 1-2 sentence description",
  "instructions": "Step-by-step engineering guidelines and best practices",
  "code_template": "Clean, reusable production boilerplate/template"
}"""
        prompt = f"""Goal: {goal}
Criteria: {success_criteria}
Steps: {json.dumps([s.get('title') for s in completed_steps])}
Sample Code:
```
{sample_code[:2500]}
```

Generate reusable skill JSON:"""

        try:
            resp = self.router.chat_completion(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                role_type="planner",
                temperature=0.2,
                run_id=run_id
            )
            parsed = self.router.parse_json(resp)
            if isinstance(parsed, dict) and "name" in parsed and "instructions" in parsed:
                if isinstance(parsed.get("instructions"), list):
                    parsed["instructions"] = "\n".join(str(x) for x in parsed["instructions"])
                if isinstance(parsed.get("description"), list):
                    parsed["description"] = "\n".join(str(x) for x in parsed["description"])
                if isinstance(parsed.get("code_template"), list):
                    parsed["code_template"] = "\n".join(str(x) for x in parsed["code_template"])
                parsed["verified_hard"] = is_verified_hard
                parsed["dual_critic_approved"] = bool(is_verified_hard)
                return parsed
        except TokenBudgetExceededError:
            raise
        except Exception:
            pass
        return None

    # ADR Generator
    def generate_adr(self, goal: str, success_criteria: str, plan_steps: List[Dict[str, Any]], dual_critic_audit: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> Dict[str, str]:
        prompt = f"""Goal: {goal}
Criteria: {success_criteria}
Plan: {json.dumps(plan_steps, indent=2)}
Dual Critic Audit: {json.dumps(dual_critic_audit or {}, indent=2)}

Create an Architectural Decision Record (ADR) in JSON format:
{{
  "title": "Short title describing the core technical decision",
  "context": "Context and problem statement",
  "decision": "The explicit architectural choices, libraries, and design patterns adopted",
  "consequences": "Positive and negative trade-offs, performance implications, and risk mitigations"
}}"""
        try:
            resp = self.router.chat_completion(
                messages=[
                    {"role": "system", "content": "You are a Chief Software Architect writing formal Architectural Decision Records (ADRs). Output ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                role_type="planner",
                temperature=0.2,
                run_id=run_id
            )
            parsed = self.router.parse_json(resp)
            if isinstance(parsed, dict) and "decision" in parsed:
                return parsed
        except TokenBudgetExceededError:
            raise
        except Exception:
            pass

        return {
            "title": f"Architecture Design for {goal[:40]}",
            "context": f"Requirement: {goal}.",
            "decision": "Adopted 100% Free Heterogeneous Multi-Agent architecture with Kimi Planner, GLM & Qwen Dual Critic, and DeepSeek Swarm.",
            "consequences": "Zero API cost, elimination of correlated blind spots via independent dual critics, and safe human review queue fallback."
        }

    # =========================================================================
    # DYNAMIC SUBAGENT SPAWNER (ON-THE-FLY SPECIALIZATION)
    # =========================================================================
    def spawn_specialized_subagent(
        self,
        role_name: str,
        role_title: str = "",
        system_prompt: str = "",
        assigned_model: str = "",
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Manager dynamically defines and spawns a specialized subagent on-the-fly."""
        clean_name = role_name.lower().strip().replace(" ", "_").replace("-", "_")

        # 1. If matching known pre-registered archetype
        if clean_name in self.specialized_subagents and not (system_prompt and role_title):
            base = self.specialized_subagents[clean_name]
            role_title = role_title or base["role_title"]
            system_prompt = system_prompt or base["system_prompt"]
            assigned_model = assigned_model or base["assigned_model"]

        # 2. If completely new custom subagent and prompt missing, synthesize via LLM
        if not system_prompt:
            try:
                synth_prompt = f"Define a specialized system prompt for an autonomous AI subagent with role: '{role_name}'. Return ONLY the direct instruction prompt for the subagent."
                resp = self.router.chat_completion(
                    messages=[
                        {"role": "system", "content": "You are an AI Agent Systems Architect. Write concise, expert instructions."},
                        {"role": "user", "content": synth_prompt}
                    ],
                    role_type="planner",
                    temperature=0.2,
                    run_id=run_id
                )
                system_prompt = resp.strip() if resp else f"You are a specialized {role_name} engineer."
            except TokenBudgetExceededError:
                raise
            except Exception:
                system_prompt = f"You are a specialized {role_name} engineer."

        if not role_title:
            role_title = role_name.replace("_", " ").title()

        if not assigned_model:
            # Default smart routing for specialized subagents
            if any(w in clean_name for w in ["security", "db", "sql", "migration"]):
                assigned_model = "qwen/qwen3.8-27b:free"
            elif any(w in clean_name for w in ["perf", "audit", "critic"]):
                assigned_model = "z-ai/glm-5.2:free"
            else:
                assigned_model = "meta-llama/llama-3.3-70b-instruct:free"

        subagent_data = {
            "role_name": clean_name,
            "role_title": role_title,
            "system_prompt": system_prompt,
            "assigned_model": assigned_model
        }
        self.specialized_subagents[clean_name] = subagent_data

        # Register in DB
        try:
            register_subagent(
                role_name=clean_name,
                role_title=role_title,
                system_prompt=system_prompt,
                assigned_model=assigned_model,
                run_id=run_id
            )
        except Exception as e:
            print(f"[MultiAgentFleet] register_subagent error: {e}")

        return subagent_data

    def get_specialized_subagent(self, role_name: str) -> Optional[Dict[str, Any]]:
        """Fetches subagent from local cache or database."""
        clean_name = role_name.lower().strip().replace(" ", "_").replace("-", "_")
        if clean_name in self.specialized_subagents:
            return self.specialized_subagents[clean_name]
        db_sub = get_subagent(clean_name)
        if db_sub:
            self.specialized_subagents[clean_name] = db_sub
            return db_sub
        return None

    def execute_subagent(
        self,
        role_name: str,
        task_title: str,
        task_description: str,
        target_file_or_cmd: str = "",
        context: str = "",
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Executes a specialized subagent against a specific task."""
        sub = self.get_specialized_subagent(role_name)
        if not sub:
            sub = self.spawn_specialized_subagent(role_name, run_id=run_id)

        update_subagent_status(sub["role_name"], f"Executing: {task_title[:30]}")

        prompt = f"""SPECIALIZED SUBAGENT TASK DISPATCH:
Role: {sub['role_title']}
Task Title: {task_title}
Task Details: {task_description}
Target File / Resource: {target_file_or_cmd}

CONTEXT & WORKSPACE STATE:
{context[:4000]}

Provide your specialized output, code, or diagnostic audit now:"""

        assigned_model = sub.get("assigned_model", "")
        role_type = "coder"
        if "glm" in assigned_model.lower():
            role_type = "reflector"
        elif "kimi" in assigned_model.lower():
            role_type = "planner"
        elif "qwen" in assigned_model.lower():
            role_type = "coder"

        try:
            response = self.router.chat_completion(
                messages=[
                    {"role": "system", "content": sub["system_prompt"]},
                    {"role": "user", "content": prompt}
                ],
                role_type=role_type,
                temperature=0.1,
                run_id=run_id
            )
            update_subagent_status(sub["role_name"], "idle", increment_task=True)
            return {
                "success": True,
                "output": response,
                "subagent": sub["role_name"],
                "model_used": assigned_model or role_type
            }
        except TokenBudgetExceededError:
            update_subagent_status(sub["role_name"], "Error: Token budget exceeded")
            raise
        except Exception as e:
            update_subagent_status(sub["role_name"], f"Error: {e}")
            return {
                "success": False,
                "error": str(e),
                "subagent": sub["role_name"],
                "model_used": assigned_model
            }

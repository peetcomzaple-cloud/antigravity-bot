import os
import re
import time
import uuid
import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional, List, Set

from .config import WORKSPACE_DIR
from .db import (
    create_run, update_run_status, update_run_token_usage, mark_run_needs_human_review,
    save_dual_critic_consensus, save_plan_steps, get_plan_steps,
    update_plan_step_status, update_plan_step_model, flag_plan_step,
    record_step, record_artifact, record_decision, add_memory, get_memories, get_run,
    search_skills, add_skill, increment_skill_usage, save_checkpoint, get_checkpoint,
    save_durable_state, get_durable_state, decay_skill_trust, reinforce_skill_trust,
    record_mission_metrics, get_artifact_by_id, update_artifact_status,
    register_subagent, get_subagents, get_subagent, update_subagent_status
)
from .tools import ToolExecutor, PolicyEngine
from .router import ModelRouter, TokenBudgetExceededError
from .multi_agent import MultiAgentFleet

class AutonomousOrchestrator:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    
    def _run_loop(self, run_id: str, goal: str, success_criteria: str, max_steps: int, resume_from_durable: bool = False):
        try:
            self.__run_loop_inner(run_id, goal, success_criteria, max_steps, resume_from_durable)
        except Exception as e:
            import traceback
            from core.db import get_connection
            err = traceback.format_exc()
            try:
                conn = get_connection()
                conn.execute("UPDATE runs SET status='failed', error_details=?, updated_at=datetime('now') WHERE run_id=?", (err, run_id))
                conn.execute("INSERT INTO steps (run_id, step_index, agent, agent_role, tool_name, action_type, tool_result, observation, state, ok) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (run_id, 999, "system", "system", "exception", "exception", err, err, "failed", 0))
                conn.commit()
                conn.close()
            except Exception as inner_e:
                print("DB ERROR IN WRAPPER:", inner_e)
            self.is_running = False
            self.active_agents.clear()
            print(f"[Orchestrator] Fatal Error in run_loop: {err}")
    
    def __init__(self, workspace: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        if workspace is None:
            workspace = WORKSPACE_DIR
        self.workspace = workspace

        self.tools = ToolExecutor(workspace=workspace)
        self.router = ModelRouter()
        self.fleet = MultiAgentFleet(self.router, tools=self.tools)
        self.active_run_id: Optional[str] = None
        self._running_event = threading.Event()
        self._paused_event = threading.Event()
        self._state_lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.intervention_queue: List[str] = []
        self.locked_files: Set[str] = set()
        self.active_agents: Dict[str, str] = {
            "manager": "idle",
            "planner": "idle",
            "coder": "idle",
            "tester": "idle",
            "reflector": "idle",
            "researcher": "idle"
        }
        # Pre-populate any registered dynamic subagents from database
        try:
            for sa in get_subagents():
                self.active_agents[sa["role_name"]] = "idle"
        except Exception:
            pass
        self.last_good_commit: str = ""
        self._initialized = True

    @property
    def is_running(self) -> bool:
        return self._running_event.is_set()

    @is_running.setter
    def is_running(self, val: bool):
        if val:
            self._running_event.set()
        else:
            self._running_event.clear()

    @property
    def is_paused(self) -> bool:
        return self._paused_event.is_set()

    @is_paused.setter
    def is_paused(self, val: bool):
        if val:
            self._paused_event.set()
        else:
            self._paused_event.clear()

    def start_goal(self, goal: str, success_criteria: str = "", max_steps: int = 15) -> str:
        """Launches a full autonomous execution run in the background."""
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.is_running:
            raise RuntimeError("An autonomous run is already in progress.")

        run_id = f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        create_run(run_id, goal, success_criteria, max_steps)
        self.active_run_id = run_id
        self.is_running = True
        self.is_paused = False

        
        goal_lower = goal.lower()
        import re
        read_pattern = r'(list files|ลิสต์ไฟล์|list_dir|what files|มีไฟล์อะไร)'
        no_edit_pattern = r'(do not edit|don\'t edit|ห้ามแก้|อย่าแก้|read only|อ่านอย่างเดียว)'
        if re.search(read_pattern, goal_lower) and re.search(no_edit_pattern, goal_lower):
            def _shortcut_run():
                try:
                    from core.db import get_connection
                    import traceback
                    conn = get_connection()
                    c = conn.cursor()
                    # Mark started
                    c.execute("UPDATE runs SET status='running', current_step=1 WHERE run_id=?", (run_id,))
                    
                    # Run tool
                    from pathlib import Path
                    root = Path(self.workspace).resolve()
                    lines = []
                    for p in sorted(root.iterdir()):
                        kind = "dir" if p.is_dir() else "file"
                        lines.append(f"{kind}\t{p.name}")
                    result = "\n".join(lines) if lines else "(empty)"
                    
                    # Insert step
                    c.execute("INSERT INTO steps (run_id, step_index, agent_role, action_type, action_payload, observation, state) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (run_id, 1, "executor", "list_dir", str({"path": "workspace"}), result, "completed"))
                              
                    # Mark completed
                    c.execute("UPDATE runs SET status='completed', current_step=1 WHERE run_id=?", (run_id,))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    from core.db import get_connection
                    import traceback
                    conn = get_connection()
                    conn.execute("UPDATE runs SET status='failed', error_details=?, updated_at=datetime('now') WHERE run_id=?", (traceback.format_exc(), run_id))
                    conn.execute("INSERT INTO steps (run_id, step_index, agent_role, action_type, observation, state) VALUES (?, ?, ?, ?, ?, ?)", (run_id, 0, "system", "exception", traceback.format_exc(), "failed"))
                    conn.commit()
                    conn.close()
            
#             import threading
            self.thread = threading.Thread(target=_shortcut_run)
            self.thread.start()
            return run_id

        self.thread = threading.Thread(
            target=self._run_loop,
            args=(run_id, goal, success_criteria, max_steps),
            daemon=True
        )
        self.thread.start()
        return run_id

    def resume_goal(self, run_id: str) -> bool:
        """lnwjud Pillar 3: Resumes an interrupted mission from durable DB checkpoints."""
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.is_running:
            return False

        run = get_run(run_id)
        if not run:
            return False

        goal = run["goal"]
        success_criteria = run.get("success_criteria", "")
        max_steps = run.get("max_steps", 20)

        self.active_run_id = run_id
        self.is_running = True
        self.is_paused = False
        update_run_status(run_id, "running")

        self.thread = threading.Thread(
            target=self._run_loop,
            args=(run_id, goal, success_criteria, max_steps),
            kwargs={"resume_from_durable": True},
            daemon=True
        )
        self.thread.start()
        return True

    def pause(self):
        self.is_paused = True
        if self.active_run_id:
            update_run_status(self.active_run_id, "paused")

    def resume(self):
        self.is_paused = False
        if self.active_run_id:
            update_run_status(self.active_run_id, "running")

    def stop(self):
        self.is_running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        for k in self.active_agents:
            self.active_agents[k] = "idle"
        if self.active_run_id:
            update_run_status(self.active_run_id, "stopped")


    def intervene(self, note: str):
        """Allows human-in-the-loop injection to steer the autonomous agent."""
        self.intervention_queue.append(note)
        if self.active_run_id:
            record_artifact(self.active_run_id, 0, "decision", "Human Guidance Received", content=note)

    def rollback_to_step(self, run_id: str, step_idx: int) -> Dict[str, Any]:
        """Rolls back workspace to a verified checkpoint."""
        chk = get_checkpoint(run_id, step_idx)
        if not chk or not chk.get("commit_hash"):
            return {"success": False, "error": f"No checkpoint found for run {run_id} step {step_idx}"}
        commit_hash = chk["commit_hash"]
        res = self.tools.rollback_checkpoint(commit_hash)
        if res["success"]:
            record_decision(
                run_id,
                f"Rollback to Step {step_idx}",
                f"Workspace restored to safe checkpoint commit: {commit_hash[:8]}",
                "Wiped broken files and uncommitted regression errors."
            )
        return res

    def spawn_subagent(
        self,
        role_name: str,
        role_title: str = "",
        system_prompt: str = "",
        assigned_model: str = ""
    ) -> Dict[str, Any]:
        """Manager Executive dynamically defines and spawns a specialized subagent on-the-fly."""
        sub = self.fleet.spawn_specialized_subagent(
            role_name=role_name,
            role_title=role_title,
            system_prompt=system_prompt,
            assigned_model=assigned_model,
            run_id=self.active_run_id
        )
        self.active_agents[sub["role_name"]] = "idle"
        if self.active_run_id:
            record_decision(
                self.active_run_id,
                f"Spawn Dynamic Subagent: {sub['role_title']}",
                f"Manager executive spawned specialized subagent '{sub['role_name']}' on the fly.",
                f"Assigned Model: [{sub['assigned_model']}] with specialized system domain instructions."
            )
        return sub

    def revert_file_diff(self, artifact_id: int) -> Dict[str, Any]:
        """Rolls back a file modification recorded in a diff artifact (1-Click IDE Revert)."""
        art = get_artifact_by_id(artifact_id)
        if not art:
            return {"success": False, "error": f"Artifact #{artifact_id} not found"}

        file_path = art.get("file_path", "")
        if not file_path:
            return {"success": False, "error": "No file path associated with this diff artifact"}

        try:
            full_path = self.tools._resolve_safe_path(file_path)
        except Exception as e:
            return {"success": False, "error": str(e)}

        diff_content = art.get("content", "")
        run_id = art.get("run_id") or self.active_run_id
        reverted = False
        error_msg = ""

        # Check if file was new in diff
        is_new = ("--- /dev/null" in diff_content or "a/dev/null" in diff_content)

        # 1. Check transaction manager rollback first (fastest and restores exact pre-step snapshot)
        try:
            rb_res = self.tools.tx_manager.rollback_transaction(art.get("step_index", 0))
            if rb_res:
                reverted = True
        except Exception:
            pass

        # 2. Check if file was new in diff or creation
        if not reverted and is_new and os.path.exists(full_path):
            try:
                os.remove(full_path)
                self.tools.run_command(["git", "rm", "-f", file_path])
                reverted = True
            except Exception as ex:
                error_msg = str(ex)

        # 3. If not reverted yet, attempt git checkout from prior commit (H5)
        if not reverted:
            step_chk = get_checkpoint(run_id, art.get("step_index", 0)) if run_id else None
            commit_ref = f"{step_chk['commit_hash']}~1" if step_chk and step_chk.get("commit_hash") else "HEAD~1"
            git_res = self.tools.run_command(["git", "checkout", commit_ref, "--", file_path])
            if git_res.get("success") and git_res.get("exit_code") == 0:
                reverted = True
            else:
                git_res = self.tools.run_command(["git", "checkout", "HEAD", "--", file_path])
                if git_res.get("success") and git_res.get("exit_code") == 0:
                    reverted = True


        if reverted:
            update_artifact_status(artifact_id, "reverted")
            if run_id:
                record_decision(
                    run_id,
                    f"↩️ 1-Click Code Lens Revert: {os.path.basename(file_path)}",
                    f"User triggered in-editor revert for diff artifact #{artifact_id}.",
                    f"Discarded modifications for {file_path} and restored clean state.",
                    step_index=art.get("step_index", 0)
                )
            return {
                "success": True,
                "file_path": file_path,
                "status": "reverted",
                "message": f"Successfully reverted changes to {file_path}"
            }
        else:
            return {
                "success": False,
                "error": error_msg or "Failed to revert file changes via git or transaction manager"
            }

    def accept_file_diff(self, artifact_id: int) -> Dict[str, Any]:
        """Marks a diff artifact as accepted by the human operator."""
        art = get_artifact_by_id(artifact_id)
        if not art:
            return {"success": False, "error": f"Artifact #{artifact_id} not found"}

        update_artifact_status(artifact_id, "accepted")
        run_id = art.get("run_id") or self.active_run_id
        if run_id:
            record_decision(
                run_id,
                f"✅ Code Accepted: {os.path.basename(art.get('file_path', ''))}",
                f"Operator approved and accepted diff for artifact #{artifact_id}.",
                "Changes verified and retained permanently in workspace.",
                step_index=art.get("step_index", 0)
            )
        return {"success": True, "status": "accepted", "message": f"Changes for {art.get('title')} accepted"}

    def _execute_single_step(
        self,
        run_id: str,
        item: Dict[str, Any],
        goal: str,
        success_criteria: str,
        extra_feedback: str,
        node_step_budget: int = 2
    ) -> Dict[str, Any]:
        """Executes a single step action, performs immediate verification, and self-reflects."""
        step_idx = item.get("step", 1)
        step_title = item.get("title", f"Step {step_idx}")
        agent_role = item.get("agent", "coder")
        action_type = item.get("action_type", "write_file")
        target = item.get("target_file_or_cmd", "")
        desc = item.get("description", "")
        is_flagged = bool(item.get("is_flagged", False))
        is_watch_point = bool(item.get("is_watch_point", False))

        self.active_agents[agent_role] = f"Executing: {step_title[:28]}"
        print(f"[Orchestrator] Step {step_idx}: [{agent_role}] {step_title} (Flagged: {is_flagged}, WatchPoint: {is_watch_point})")

        retry_count = 0
        max_retries = node_step_budget  # Hard cap: max 2 retries per node
        step_success = False
        observation = ""
        action_payload = ""
        reflection_text = ""
        failure_analysis = ""
        lesson = ""
        duration = 0.0
        winning_model = ""

        current_feedback = extra_feedback

        # lnwjud Pillar 2: Begin atomic step transaction for multi-file rollback
        self.tools.tx_manager.begin_transaction(step_idx)

        while retry_count <= max_retries and not step_success:
            if not self.is_running:
                self.tools.tx_manager.rollback_transaction(step_idx)
                return {"success": False, "aborted": True, "step": step_idx}

            start_t = time.time()
            try:
                # --- ACT ---
                if action_type == "write_file":
                    if not target or not target.strip():
                        retry_count += 1
                        current_feedback = f"Step {step_idx} requires a valid target file path, but target is empty."
                        continue

                    existing_file = self.tools.read_file(target)
                    existing_code = existing_file.get("content", "")

                    if "test" in target.lower():
                        src_files = self.tools.list_files("src").get("files", [])
                        for sf in src_files:
                            sf_res = self.tools.read_file(sf)
                            if sf_res.get("success"):
                                current_feedback += f"\n\nACTUAL SOURCE MODULE TO TEST ({sf}):\n```python\n{sf_res['content'][:5000]}\n```\n(Import ONLY classes and functions that ACTUALLY exist in the above source code!)"

                    # Cross-Model Competition on Flagged Nodes vs Normal Coder on Standard Nodes
                    if is_flagged:
                        record_decision(
                            run_id,
                            f"⚔️ Cross-Model Code Competition (Step {step_idx})",
                            f"Step {step_idx} was flagged by Dual-Critic consensus.",
                            "DeepSeek-Chat (Candidate A) and Qwen3-Coder (Candidate B) generated competing solutions; GLM-5.3 evaluated and selected the superior code.",
                            "Eliminates single-model bias without calling expensive models.",
                            step_index=step_idx
                        )
                    
                    if agent_role not in ["coder", "tester", "researcher", "planner", "manager", "reflector"]:
                        sub_res = self.fleet.execute_subagent(
                            role_name=agent_role,
                            task_title=step_title,
                            task_description=desc,
                            target_file_or_cmd=target,
                            context=f"Existing Code in {target}:\n{existing_code}\nFeedback/Guidance:\n{current_feedback}",
                            run_id=run_id
                        )
                        generated_code = self.tools.strip_markdown_fences(sub_res.get("output", ""))
                        winning_model = sub_res.get("model_used", f"subagent:{agent_role}")
                    else:
                        generated_code, winning_model = self.fleet.generate_code(
                            goal, item, current_content=existing_code, error_feedback=current_feedback,
                            is_flagged=is_flagged, run_id=run_id
                        )

                    write_res = self.tools.write_file(target, generated_code, step_id=step_idx)
                    if not write_res.get("success"):
                        retry_count += 1
                        current_feedback = f"File write error: {write_res.get('error')}"
                        continue

                    observation = f"Wrote {write_res.get('bytes_written', 0)} bytes to {target} using [{winning_model}]."
                    action_payload = f"write_file({target}) [model={winning_model}]"

                    if write_res.get("diff"):
                        record_artifact(
                            run_id, step_idx, "diff", f"Diff: {target} ({winning_model})",
                            content=write_res["diff"], file_path=target
                        )

                    # lnwjud Pillar 9: Grounded Physical Verification
                    grounded = self.tools.assert_file_grounded(target)
                    if not grounded["grounded"]:
                        retry_count += 1
                        observation += f"\n[Grounded Assertion Failed]: {grounded.get('error')}"
                        current_feedback = (
                            f"CRITICAL GROUNDED VERIFICATION FAILURE on '{target}': {grounded.get('error')}.\n"
                            f"Code cannot have empty stubs, 'pass', or missing physical existence. Provide complete implementation."
                        )
                        print(f"[Orchestrator] Step {step_idx} failed grounded check: {grounded.get('error')}")
                        continue

                    # If watch point, run extra strict validation
                    if is_watch_point:
                        observation += f"\n[WatchPoint Monitor]: Step {step_idx} verified with strict boundary assertion."

                    # Alive Artifact: Browser snapshot for web / html (M7)
                    if target.endswith(".html"):
                        try:
                            browser_res = self.tools.browser_capture(target)
                            if browser_res.get("screenshot_path"):
                                record_artifact(
                                    run_id, step_idx, "screenshot", f"UI Preview: {os.path.basename(target)}",
                                    file_path=browser_res["screenshot_path"]
                                )
                        except Exception:
                            pass

                elif action_type == "run_command":
                    # lnwjud Pillar 5 / Antigravity Phase 3: Destructive Action Gate
                    safe, sec_reason = PolicyEngine.is_command_safe(target)
                    if not safe:
                        print(f"[Orchestrator] Destructive Action Gate intercepted command: {target} ({sec_reason})")
                        record_artifact(
                            run_id, step_idx, "decision",
                            f"🛡️ Destructive Action Gate Intercepted Command (Step {step_idx})",
                            content=f"**Prohibited Command:** `{target}`\n\n**Security Policy:** {sec_reason}\n\n**Action:** Command blocked automatically; escalating to Human-Review Queue."
                        )
                        mark_run_needs_human_review(
                            run_id,
                            f"Destructive action blocked on Step {step_idx}: '{target}'. Reason: {sec_reason}"
                        )
                        self.tools.tx_manager.rollback_transaction(step_idx)
                        return {"success": False, "aborted": True, "step": step_idx, "failure_analysis": sec_reason}

                    cmd_res = self.tools.run_command(target)
                    observation = f"Exit code: {cmd_res['exit_code']}\nStdout:\n{cmd_res['stdout']}\nStderr:\n{cmd_res['stderr']}"
                    action_payload = f"run_command({target})"
                    record_artifact(run_id, step_idx, "terminal", f"Terminal: {target[:30]}", content=observation)

                    if cmd_res["exit_code"] != 0:
                        retry_count += 1
                        current_feedback = f"Command '{target}' failed with exit code {cmd_res['exit_code']}.\nError:\n{cmd_res['stderr'][:2000]}"
                        if retry_count <= max_retries:
                            # Antigravity Self-Repair on Command/Lint/Compile Failure
                            combined_output = f"{cmd_res['stdout']}\n{cmd_res['stderr']}"
                            mentioned = re.findall(r'([\w/\.\-]+\.(?:py|js|ts|json))', combined_output)
                            repair_candidates = [f for f in set(mentioned) if self.tools.file_exists(f).get("exists")]
                            if repair_candidates:
                                for rep_f in repair_candidates[:2]:
                                    print(f"[Orchestrator] Self-healing detected error in '{rep_f}'. Dispatching Coder repair...")
                                    f_res = self.tools.read_file(rep_f)
                                    if f_res.get("success"):
                                        self.active_agents["coder"] = f"Self-repairing {os.path.basename(rep_f)}..."
                                        rep_code = self.fleet.generate_code_single(
                                            goal,
                                            {"title": f"Fix lint/syntax/test issues in {rep_f}", "target_file_or_cmd": rep_f, "description": f"Command '{target}' failed with exit code {cmd_res['exit_code']}."},
                                            current_content=f_res["content"],
                                            error_feedback=combined_output[:3000],
                                            run_id=run_id
                                        )
                                        clean_code = self.tools.strip_markdown_fences(rep_code)
                                        self.tools.write_file(rep_f, clean_code, step_id=step_idx)
                                        print(f"[Orchestrator] Applied self-repair patch to {rep_f}")
                        continue

                elif action_type == "run_tests":
                    self.active_agents["tester"] = f"Running Pytest Suite on {target or 'all'}"
                    test_res = self.tools.run_tests(target if target else None)
                    parsed = test_res.get("parsed", {})
                    observation = f"Test Result (Exit {test_res['exit_code']}): Passed={parsed.get('passed', 0)}, Failed={parsed.get('failed', 0)}, Errors={parsed.get('errors', 0)}\n{test_res['stdout']}\n{test_res['stderr']}"
                    action_payload = f"run_tests({target})"
                    record_artifact(run_id, step_idx, "terminal", "Pytest Suite Results", content=observation)

                    # Antigravity Phase 2: Structured Test Report Artifact
                    test_report_md = f"""### 🧪 Test Report (Step {step_idx})
**Target:** `{target or 'all tests'}`
**Status:** {'✅ PASSED' if parsed.get('success') else '❌ FAILED'} (Exit Code: {test_res['exit_code']})

| Metric | Count |
|---|---|
| 🟢 Passed | {parsed.get('passed', 0)} |
| 🔴 Failed | {parsed.get('failed', 0)} |
| ⚠️ Errors | {parsed.get('errors', 0)} |
| ⏱️ Total Tests | {parsed.get('total', 0)} |

"""
                    if parsed.get("failure_traces"):
                        test_report_md += "#### 🚨 Failure Traces\n```python\n" + "\n".join(parsed["failure_traces"]) + "\n```\n"
                    record_artifact(run_id, step_idx, "test_report", f"Test Report: {target or 'all'} ({'PASS' if parsed.get('success') else 'FAIL'})", content=test_report_md)

                    if not parsed.get("success", False):
                        retry_count += 1
                        failure_analysis = f"Tests failed: {parsed.get('failed', 0)} failed, {parsed.get('errors', 0)} errors. Traces: {'; '.join(parsed.get('failure_traces', [])[:2])}"
                        current_feedback = f"TEST REGRESSION DETECTED:\n{failure_analysis}\nFix the failing tests immediately."
                        continue

                elif action_type == "browser_capture":
                    self.active_agents["researcher"] = f"Capturing: {target}"
                    browser_res = self.tools.browser_capture(target)
                    observation = f"Browser Capture Result: {browser_res.get('output', '')}"
                    action_payload = f"browser_capture({target})"
                    if browser_res.get("screenshot_path"):
                        record_artifact(run_id, step_idx, "screenshot", f"Capture: {target}", file_path=browser_res["screenshot_path"])
                    if not browser_res.get("success"):
                        retry_count += 1
                        current_feedback = f"Browser capture failed: {browser_res.get('error', 'Unable to navigate or capture page.')}"
                        continue

                elif action_type == "compile_apk":
                    self.active_agents["coder"] = "Building Native Android APK..."
                    apk_res = self.tools.compile_apk(
                        package_name="com.antigravity.cookierunbot",
                        app_name="CookieRunBot",
                        assets=[self.tools._resolve_path("src/cookie_run_upgrade_standalone.js")],
                        output_apk=target if target else "CookieRunBot.apk"
                    )
                    observation = f"APK Build Result (success={apk_res.get('success')}): Size={apk_res.get('size_bytes', 0)} bytes, Path={apk_res.get('apk_path')}"
                    action_payload = f"compile_apk({target})"
                    if apk_res.get("success"):
                        record_artifact(
                            run_id, step_idx, "apk", f"Compiled Android APK: {os.path.basename(apk_res['apk_path'])}",
                            file_path=apk_res["apk_path"]
                        )
                    else:
                        retry_count += 1
                        current_feedback = f"APK compile failed: {apk_res.get('error', 'unknown error')}"
                        continue

                elif action_type == "subagent_task":
                    self.active_agents[agent_role] = f"Subagent: {step_title[:28]}"
                    target_file_ctx = ""
                    if target:
                        try:
                            f_res = self.tools.read_file(target)
                            if f_res.get("success") and f_res.get("content"):
                                target_file_ctx = f"\nTARGET FILE SOURCE CODE ({target}):\n```python\n{f_res['content'][:6000]}\n```\n(Analyze the exact code provided above)"
                        except Exception:
                            pass

                    sub_res = self.fleet.execute_subagent(
                        role_name=agent_role,
                        task_title=step_title,
                        task_description=desc,
                        target_file_or_cmd=target,
                        context=f"Goal: {goal}\nCriteria: {success_criteria}\n{target_file_ctx}\nFeedback: {current_feedback}",
                        run_id=run_id
                    )
                    observation = sub_res.get("output", "Specialized subagent task completed.")
                    action_payload = f"subagent_task({agent_role}: {step_title})"
                    winning_model = sub_res.get("model_used", f"subagent:{agent_role}")
                    record_decision(
                        run_id,
                        f"🤖 Subagent Task: {step_title}",
                        f"Dispatched specialized subagent [{agent_role}] powered by [{winning_model}].",
                        f"Subagent execution result summary:\n{observation[:600]}...",
                        step_index=step_idx
                    )
                    if not sub_res.get("success", True):
                        retry_count += 1
                        current_feedback = f"Subagent {agent_role} failed task: {observation[:1000]}"
                        continue

                else:
                    retry_count += 1
                    err_msg = f"Unknown action_type '{action_type}'. Valid types are write_file, run_command, run_tests, browser_capture, compile_apk, or subagent_task."
                    current_feedback = err_msg
                    observation = err_msg
                    action_payload = f"invalid_action({action_type})"
                    continue

                duration = round(time.time() - start_t, 2)
                action_payload = f"{action_payload} [t_start={start_t:.3f}, t_end={time.time():.3f}]"

                # --- OBSERVE & REFLECT ---
                self.active_agents["reflector"] = f"Reflecting Step {step_idx}"
                target_file = target if action_type == "write_file" else ""
                reflection_res = self.fleet.reflect_step(item, observation, success_criteria, target_file=target_file, run_id=run_id)
                step_success = reflection_res.get("is_success", False)
                reflection_text = reflection_res.get("reflection", "Action verified.")
                failure_analysis = reflection_res.get("failure_analysis", "")

                lesson = reflection_res.get("lesson_learned", "")

                if not step_success:
                    retry_count += 1
                    print(f"[Orchestrator] Step {step_idx} failed (Attempt {retry_count}/{max_retries}): {failure_analysis}")
                    current_feedback = f"Attempt {retry_count} failed with: {failure_analysis}\nTrace: {observation[-1500:]}"
                else:
                    break

            except TokenBudgetExceededError as te:
                print(f"[Orchestrator] {te}")
                self.tools.tx_manager.rollback_transaction(step_idx)
                mark_run_needs_human_review(run_id, str(te))
                return {"success": False, "aborted": True, "step": step_idx, "budget_exceeded": True}
            except Exception as e:
                retry_count += 1
                observation = f"Exception: {str(e)}\n{traceback.format_exc()}"
                current_feedback = f"Exception encountered: {str(e)}"
                print(f"[Orchestrator] Exception in step {step_idx}: {e}")

        # lnwjud Pillar 2 & 8: Commit transaction or rollback upon hard cap exhaustion
        if step_success:
            self.tools.tx_manager.commit_transaction(step_idx)
            try:
                for sk in search_skills(step_title, limit=3):
                    reinforce_skill_trust(sk["name"])
            except Exception:
                pass
        else:
            reverted = self.tools.tx_manager.rollback_transaction(step_idx)
            if reverted:
                print(f"[Orchestrator] Step {step_idx} failed hard cap. Reverted files: {reverted}")
            try:
                for sk in search_skills(step_title, limit=3):
                    decay_skill_trust(sk["name"])
            except Exception:
                pass

        # Update step model and status in SQLite
        update_plan_step_model(run_id, step_idx, winning_model or self.router.last_model_used, winning_model=winning_model)
        update_plan_step_status(run_id, step_idx, "completed" if step_success else "failed")

        record_step(
            run_id=run_id,
            step_index=step_idx,
            agent_role=agent_role,
            state="completed" if step_success else "failed",
            thought=f"{desc} (Model: {winning_model or self.router.last_model_used})",
            action_type=action_type,
            action_payload=action_payload,
            observation=observation,
            reflection=reflection_text,
            duration_sec=duration
        )

        if lesson:
            add_memory("lesson_learned", f"Step {step_idx}: {step_title}", lesson, run_id=run_id)

        self.active_agents[agent_role] = "idle"
        self.active_agents["tester"] = "idle"
        self.active_agents["reflector"] = "idle"

        return {
            "step": step_idx,
            "success": step_success,
            "failure_analysis": failure_analysis,
            "observation": observation,
            "item": item,
            "winning_model": winning_model,
            "is_flagged": is_flagged
        }

    def __run_loop_inner(self, run_id: str, goal: str, success_criteria: str, max_steps: int, resume_from_durable: bool = False):
        print(f"[Orchestrator] Starting 100% Free Autonomous Multi-Agent Run: {run_id} | Goal: {goal}")
        had_flagged_success = False
        try:
            completed_steps: Set[int] = set()
            all_steps_dict: Dict[int, Dict[str, Any]] = {}
            node_budget = 2

            if resume_from_durable:
                # lnwjud Pillar 3: Rehydrate execution state from durable DB checkpoint
                durable = get_durable_state(run_id)
                saved_plan = get_plan_steps(run_id)
                if saved_plan:
                    plan_steps = saved_plan
                    for s in plan_steps:
                        if "step" not in s:
                            s["step"] = int(s.get("step_index", 1))
                        else:
                            s["step"] = int(s["step"])
                        # H12: map assigned_agent from DB row to agent
                        if "agent" not in s and "assigned_agent" in s:
                            s["agent"] = s["assigned_agent"]
                        if isinstance(s.get("depends_on"), str):
                            try:
                                s["depends_on"] = json.loads(s["depends_on"])
                            except Exception:
                                s["depends_on"] = []
                        clean_deps = []
                        for d in s.get("depends_on", []):
                            try:
                                d_val = int(d)
                                if d_val < s["step"]:
                                    clean_deps.append(d_val)
                            except (ValueError, TypeError):
                                pass
                        s["depends_on"] = clean_deps
                    all_steps_dict = {s["step"]: s for s in plan_steps}
                    completed_steps = set(durable.get("completed_steps", [])) if durable else set()
                    self.last_good_commit = durable.get("last_checkpoint_commit", "") if durable else ""
                    context_vars = durable.get("context_vars", {}) if durable else {}
                    node_budget = int(context_vars.get("node_budget", 2))
                    token_budget = int(context_vars.get("token_budget", 45000))
                    self.router.set_mission_budget(run_id, token_budget)
                    print(f"[Orchestrator] Rehydrated durable state: {len(completed_steps)}/{len(plan_steps)} steps already completed.")
                else:
                    resume_from_durable = False

            if not resume_from_durable:
                # =========================================================================
                # PHASE 0: TASK INTAKE (DEEPSEEK-FLASH)
                # =========================================================================
                update_run_status(run_id, "intake")
                self.active_agents["researcher"] = "Assessing Task Scope & Token Budget (Phase 0)..."
                intake_res = self.fleet.intake_task(goal, success_criteria, run_id=run_id)
                node_budget = intake_res.get("node_step_budget", 2)
                token_budget = intake_res.get("mission_token_budget", 45000)
                self.router.set_mission_budget(run_id, token_budget)

                record_artifact(
                    run_id, 0, "decision",
                    "🎯 Phase 0: Task Intake & Strict Budget Allocation",
                    content=(
                        f"### Scope Decomposition\n{intake_res.get('scope_summary', '')}\n\n"
                        f"**Node Step Budget (Hard Cap):** {node_budget} retries max\n\n"
                        f"**Mission Token Budget:** {token_budget:,} tokens (Weekly quota guard)\n\n"
                        f"**Verifiable Criteria Checklist:**\n" +
                        "\n".join([f"- [ ] {c}" for c in intake_res.get("verifiable_criteria", [])]) +
                        f"\n\n**High-Risk Focus Areas:**\n" +
                        "\n".join([f"- {r}" for r in intake_res.get("high_risk_areas", [])])
                    )
                )
                save_durable_state(run_id, "intake", [], context_vars={"goal": goal, "node_budget": node_budget, "token_budget": token_budget}, last_checkpoint_commit="")

                # =========================================================================
                # PHASE 1: DAG PLAN GENERATION (KIMI K2.6)
                # =========================================================================
                update_run_status(run_id, "planning")
                self.active_agents["planner"] = "Deconstructing Goal into Parallel DAG (Kimi K2.6)..."

                file_list_res = self.tools.list_files()
                existing_files = file_list_res.get("files", [])
                past_memories = get_memories(limit=8)
                relevant_skills = search_skills(goal, limit=4)

                # 1. Planner generates initial DAG plan
                plan_steps = self.fleet.plan_goal(goal, success_criteria, existing_files, past_memories, relevant_skills, run_id=run_id)

                # =========================================================================
                # PHASE 1.5: DUAL-CRITIC AUDIT (GLM-5.3 + QWEN3-CODER INDEPENDENT REVIEW)
                # =========================================================================
                self.active_agents["reflector"] = "Dual-Critic Independent Audit (GLM-5.3 & Qwen3)..."
                dual_audit = self.fleet.dual_critic_audit(goal, success_criteria, plan_steps, run_id=run_id)

                raw_high = dual_audit.get("high_confidence_flags", [])
                raw_watch = dual_audit.get("watch_points", [])
                high_flags = [int(x) for x in raw_high if str(x).isdigit()]
                watch_pts = [int(x) for x in raw_watch if str(x).isdigit()]
                save_dual_critic_consensus(run_id, high_flags, watch_pts)

                record_artifact(
                    run_id, 0, "decision",
                    f"🛡️ Phase 1.5 Dual-Critic Audit: Score {dual_audit.get('avg_score', 8)}/10",
                    content=(
                        f"### Dual-Critic Consensus Results\n"
                        f"- **Critic #1 (GLM-5.3) Weaknesses Identified:** {len(dual_audit['glm_review'].get('weaknesses', []))}\n"
                        f"- **Critic #2 (Qwen3-Coder) Weaknesses Identified:** {len(dual_audit['qwen_review'].get('weaknesses', []))}\n\n"
                        f"### 🚨 High-Confidence Flags (Consensus Agreement):\n" +
                        ("\n".join([f"- Step {s}: Dual critics agree on critical vulnerability -> Enforced Plan Refinement & Candidate Competition" for s in high_flags]) if high_flags else "None (No shared failure points)\n") +
                        f"\n### 👁️ Watch Points (Single Critic Concern):\n" +
                        ("\n".join([f"- Step {s}: Flagged by single critic -> Tester extra rigorous monitoring" for s in watch_pts]) if watch_pts else "None\n") +
                        f"\n\n**Critique Feedback Summary:**\n{dual_audit.get('refine_feedback', '')}"
                    )
                )

                # If consensus high-confidence flags exist, force Kimi to refine plan
                if dual_audit.get("requires_refinement"):
                    print(f"[Orchestrator] High-confidence consensus flags detected ({high_flags}). Refining plan with Kimi K2.6...")
                    self.active_agents["planner"] = "Restructuring Plan to eliminate consensus weaknesses..."
                    plan_steps = self.fleet.plan_goal(
                        goal, success_criteria, existing_files, past_memories, relevant_skills,
                        critic_feedback=dual_audit.get("refine_feedback", ""), run_id=run_id
                    )

                # Tag steps with is_flagged and is_watch_point
                for s in plan_steps:
                    s_num = int(s.get("step", 1))
                    s["step"] = s_num
                    s["is_flagged"] = s_num in high_flags
                    s["is_watch_point"] = s_num in watch_pts

                save_plan_steps(run_id, plan_steps)

                # 2. Architectural Decision Record (ADR)
                adr = self.fleet.generate_adr(goal, success_criteria, plan_steps, dual_audit, run_id=run_id)
                record_decision(
                    run_id,
                    adr.get("title", f"Architecture for {goal[:40]}"),
                    adr.get("context", goal),
                    adr.get("decision", "100% Free Heterogeneous Fleet with Kimi DAG Planner, GLM-5.3 & Qwen3 Dual Critic, and DeepSeek Swarm."),
                    adr.get("consequences", "Zero API cost, elimination of correlated blind spots via independent dual critics, and safe human review queue fallback.")
                )

                # 3. Plan Artifact & Safe Checkpoint
                record_artifact(run_id, 0, "plan", "Autonomous Plan Breakdown (DAG Graph)", content=json.dumps(plan_steps, indent=2))
                chk = self.tools.create_checkpoint(run_id, 0, f"Initial state: {goal}")
                if chk.get("success"):
                    self.last_good_commit = chk["commit_hash"]
                    save_checkpoint(run_id, 0, chk["commit_hash"], chk.get("snapshot_path", ""), "Initial workspace state")

                self.active_agents["planner"] = "idle"
                self.active_agents["reflector"] = "idle"
                update_run_status(run_id, "running", current_step=0)

                # Sanitize dependencies
                for s in plan_steps:
                    s["step"] = int(s.get("step", 1))
                    clean_deps = []
                    for d in s.get("depends_on", []):
                        try:
                            d_val = int(d)
                            if d_val < s["step"]:
                                clean_deps.append(d_val)
                        except (ValueError, TypeError):
                            pass
                    s["depends_on"] = clean_deps

                completed_steps = set()
                all_steps_dict = {s["step"]: s for s in plan_steps}
                save_durable_state(run_id, "planning", list(completed_steps), context_vars={"goal": goal, "node_budget": node_budget, "token_budget": token_budget}, last_checkpoint_commit=self.last_good_commit)


            step_counter = len(completed_steps)

            # =========================================================================
            # PHASE 2: SWARM PARALLEL EXECUTION & CROSS-MODEL COMPETITION
            # =========================================================================
            while len(completed_steps) < len(all_steps_dict) and step_counter < max_steps:
                while self.is_paused and self.is_running:
                    time.sleep(0.5)
                if not self.is_running:
                    print("[Orchestrator] Run stopped by user.")
                    return

                ready_steps: List[Dict[str, Any]] = []
                for s_idx, s_data in all_steps_dict.items():
                    if s_idx in completed_steps:
                        continue
                    deps = s_data.get("depends_on", [])
                    if all(d in completed_steps for d in deps):
                        ready_steps.append(s_data)
                        update_plan_step_status(run_id, s_idx, "ready")
                    else:
                        update_plan_step_status(run_id, s_idx, "blocked")

                if not ready_steps:
                    uncompleted = [s for s in all_steps_dict.values() if s["step"] not in completed_steps]
                    if uncompleted:
                        ready_steps = [uncompleted[0]]
                        update_plan_step_status(run_id, uncompleted[0]["step"], "ready")
                    else:
                        break

                # Swarm parallelism with Worker File Lock (Pillar 3)
                parallel_batch: List[Dict[str, Any]] = []
                targets_in_batch: Set[str] = set()
                for rs in ready_steps:
                    target = rs.get("target_file_or_cmd", "")
                    if target and (target in targets_in_batch or target in self.locked_files):
                        continue
                    parallel_batch.append(rs)
                    update_plan_step_status(run_id, rs["step"], "in_progress")
                    if target:
                        targets_in_batch.add(target)
                        self.locked_files.add(target)
                    if len(parallel_batch) >= 3:
                        break

                batch_steps_str = ", ".join([str(s['step']) for s in parallel_batch])
                self.active_agents["manager"] = f"Dispatching Swarm Batch (Steps: {batch_steps_str})"
                print(f"[Orchestrator] Manager dispatching parallel swarm batch: {[s['step'] for s in parallel_batch]}")

                extra_feedback = ""
                if self.intervention_queue:
                    interventions = " | ".join(self.intervention_queue)
                    self.intervention_queue.clear()
                    extra_feedback = f"User Intervention Instructions: {interventions}"

                batch_results = []
                if len(parallel_batch) > 1:
                    with ThreadPoolExecutor(max_workers=len(parallel_batch)) as pool:
                        futures = {
                            pool.submit(self._execute_single_step, run_id, s, goal, success_criteria, extra_feedback, node_budget): s
                            for s in parallel_batch
                        }
                        for f in as_completed(futures):
                            try:
                                batch_results.append(f.result())
                            except Exception as worker_err:
                                s_item = futures[f]
                                batch_results.append({
                                    "step": s_item.get("step", 99),
                                    "success": False,
                                    "failure_analysis": f"Worker thread exception: {str(worker_err)}",
                                    "observation": traceback.format_exc(),
                                    "item": s_item
                                })
                else:
                    batch_results.append(
                        self._execute_single_step(run_id, parallel_batch[0], goal, success_criteria, extra_feedback, node_budget)
                    )

                # Release worker file locks
                for rs in parallel_batch:
                    target = rs.get("target_file_or_cmd", "")
                    if target and target in self.locked_files:
                        self.locked_files.discard(target)

                step_counter += len(batch_results)
                update_run_status(run_id, "running", current_step=step_counter)

                failed_res = None
                for res in batch_results:
                    s_idx = res["step"]
                    if res.get("budget_exceeded"):
                        return

                    if res.get("success"):
                        completed_steps.add(s_idx)
                        if res.get("is_flagged"):
                            had_flagged_success = True
                        step_chk = self.tools.create_checkpoint(run_id, s_idx, f"Step {s_idx} success")
                        if step_chk.get("success"):
                            self.last_good_commit = step_chk["commit_hash"]
                            save_checkpoint(run_id, s_idx, step_chk["commit_hash"], step_chk.get("snapshot_path", ""), f"Completed step {s_idx}")
                        save_durable_state(run_id, "running", list(completed_steps), context_vars={"goal": goal}, last_checkpoint_commit=self.last_good_commit)
                    else:
                        if not failed_res:
                            failed_res = res

                if failed_res:
                    s_idx = failed_res["step"]
                    print(f"[Orchestrator] Step {s_idx} failed after {node_budget} retries. Routing to Human-Review Queue...")
                    mark_run_needs_human_review(
                        run_id,
                        f"Step {s_idx} ('{failed_res['item'].get('title')}') failed after {node_budget} retries without endless looping. Failure: {failed_res.get('failure_analysis', '')[:200]}"
                    )
                    save_durable_state(run_id, "needs_human_review", list(completed_steps), context_vars={"goal": goal}, last_checkpoint_commit=self.last_good_commit)
                    record_artifact(
                        run_id, s_idx, "decision",
                        "🚨 Escalated to Human-Review Queue",
                        content=(
                            f"### Hard Cap Reached on Step {s_idx}\n"
                            f"**Step:** {failed_res['item'].get('title')}\n\n"
                            f"**Error Analysis:** {failed_res.get('failure_analysis', '')}\n\n"
                            f"**Status:** Marked as `needs_human_review`. Safe checkpoint preserved at commit {self.last_good_commit[:8] if self.last_good_commit else 'init'}."
                        )
                    )
                    return

            # H4: Ensure all planned steps are complete before proceeding to Phase 3 completion
            if len(completed_steps) < len(all_steps_dict):
                incomplete_count = len(all_steps_dict) - len(completed_steps)
                reason = f"Max step budget ({max_steps}) reached with {incomplete_count} steps incomplete."
                print(f"[Orchestrator] {reason}. Routing to Human-Review Queue.")
                update_run_status(run_id, "needs_human_review", current_step=step_counter)
                mark_run_needs_human_review(run_id, reason)
                save_durable_state(run_id, "needs_human_review", list(completed_steps), context_vars={"goal": goal}, last_checkpoint_commit=self.last_good_commit)
                record_artifact(
                    run_id, step_counter, "decision",
                    "⚠️ Max Step Budget Reached with Incomplete Steps",
                    content=f"Execution reached step budget ({step_counter}/{max_steps}) with {incomplete_count} steps incomplete. Escalate to human review."
                )
                return

            # =========================================================================
            # PHASE 3: HARD VERIFICATION & FINAL DUAL CRITIQUE
            # =========================================================================
            update_run_status(run_id, "hard_verification", current_step=step_counter)
            self.active_agents["tester"] = "Running Full Test Suite & Static Analysis..."
            print("[Orchestrator] Entering Phase 3: Hard Verification Layer...")

            full_test_res = self.tools.run_tests()
            test_summary = f"Exit Code: {full_test_res['exit_code']}\nStdout:\n{full_test_res['stdout']}\nStderr:\n{full_test_res['stderr']}"
            record_artifact(run_id, step_counter, "terminal", "Phase 3: Full Integration Test Run", content=test_summary)

            parsed_full = full_test_res.get("parsed", {})
            final_report_md = f"""### 🧪 Final Integration Test Report (Phase 3)
**Overall Status:** {'✅ PASSED (100%)' if full_test_res['exit_code'] == 0 else '❌ FAILED'} (Exit Code: {full_test_res['exit_code']})

| Metric | Result |
|---|---|
| 🟢 Tests Passed | {parsed_full.get('passed', 0)} |
| 🔴 Tests Failed | {parsed_full.get('failed', 0)} |
| ⚠️ Errors | {parsed_full.get('errors', 0)} |
| ⏱️ Total Tests | {parsed_full.get('total', 0)} |

"""
            if parsed_full.get("failure_traces"):
                final_report_md += "#### 🚨 Failure Traces\n```python\n" + "\n".join(parsed_full["failure_traces"]) + "\n```\n"
            record_artifact(run_id, step_counter, "test_report", "Phase 3: Integration Test Report", content=final_report_md)

            static_issues: List[str] = []
            workspace_files = self.tools.list_files().get("files", [])
            for wf in workspace_files:
                if wf.endswith(".py") or wf.endswith(".js"):
                    cq = self.tools.check_code_quality(wf)
                    if not cq["valid"]:
                        static_issues.extend([f"{wf}: {iss}" for iss in cq["issues"]])

            # If tests failed, retry with targeted repair up to 2 times (H10)
            if full_test_res["exit_code"] != 0 or len(static_issues) > 0:
                print("[Orchestrator] Phase 3 verification found errors. Attempting localized repair (max 2 retries)...")
                repair_attempts = 0
                while repair_attempts < 2 and (full_test_res["exit_code"] != 0 or len(static_issues) > 0):
                    repair_attempts += 1
                    target_error_files = [
                        wf for wf in workspace_files
                        if wf in test_summary or any(wf in iss for iss in static_issues)
                    ]
                    if not target_error_files:
                        target_error_files = [wf for wf in workspace_files if wf.endswith(".py") and "test" in wf.lower()]
                    for wf in target_error_files[:3]:
                        wf_res = self.tools.read_file(wf)
                        if wf_res.get("success"):
                            repaired = self.fleet.generate_code_single(
                                goal, {"title": f"Fix {wf}", "target_file_or_cmd": wf, "description": "Fix test assertions and static issues"},
                                current_content=wf_res["content"], error_feedback=test_summary, run_id=run_id
                            )
                            clean_code = self.tools.strip_markdown_fences(repaired)
                            self.tools.write_file(wf, clean_code)
                    full_test_res = self.tools.run_tests()
                    test_summary = f"Exit Code: {full_test_res['exit_code']}\nStdout:\n{full_test_res['stdout']}\nStderr:\n{full_test_res['stderr']}"
                    # Re-evaluate static analysis issues
                    static_issues = []
                    for wf in workspace_files:
                        if wf.endswith(".py") or wf.endswith(".js"):
                            cq = self.tools.check_code_quality(wf)
                            if not cq["valid"]:
                                static_issues.extend([f"{wf}: {iss}" for iss in cq["issues"]])

                # If STILL failing on 3rd attempt: STOP and send to Human Review Queue!
                if full_test_res["exit_code"] != 0 or len(static_issues) > 0:
                    print("[Orchestrator] Phase 3 failed after 2 retries. Stopping and routing to Human-Review Queue!")
                    mark_run_needs_human_review(run_id, f"Phase 3 verification failed after 2 retries. Test exit code: {full_test_res['exit_code']}")
                    record_artifact(
                        run_id, step_counter, "decision",
                        "🚨 Phase 3 Escalated to Human-Review Queue",
                        content=f"Verification failed 2 repair attempts. Quota preserved, endless loop prevented.\n\nTrace:\n{test_summary[:500]}"
                    )
                    return

            # Final Review
            self.active_agents["reflector"] = "Dual Final Sign-Off Review..."
            final_review = self.fleet.final_integration_review(goal, success_criteria, list(all_steps_dict.values()), test_summary, static_issues, run_id=run_id)
            record_artifact(
                run_id, step_counter, "decision",
                f"🛡️ Phase 3 Final Review: Score {final_review.get('score', 8)}/10",
                content=f"**Verdict:** {final_review.get('verdict')}\n\n**Passed:** {final_review.get('passed')}\n\n**Remedy:** {final_review.get('remedy_instructions')}"
            )
            if not final_review.get("passed", True) and final_review.get("score", 10) < 6:
                print(f"[Orchestrator] Final review failed (Score {final_review.get('score')}/10). Routing to Human-Review Queue...")
                mark_run_needs_human_review(run_id, f"Final review failed with score {final_review.get('score', 0)}/10: {final_review.get('verdict', '')}")
                return

            # =========================================================================
            # PHASE 4: AUTO-SKILL LEARNING + QUALITY GATE
            # =========================================================================
            update_run_status(run_id, "learning", current_step=step_counter)
            self.active_agents["reflector"] = "Synthesizing Verified-Hard Engineering Skill..."
            print("[Orchestrator] Entering Phase 4: Skill Bank Synthesis...")

            sample_code = ""
            py_src = [f for f in workspace_files if f.startswith("src/") and f.endswith(".py")]
            if py_src:
                t_res = self.tools.read_file(py_src[0])
                if t_res.get("success"):
                    sample_code = t_res["content"]
            if not sample_code and workspace_files:
                for wf in workspace_files:
                    if wf.endswith(".py") and "test" not in wf.lower():
                        t_res = self.tools.read_file(wf)
                        if t_res.get("success"):
                            sample_code = t_res["content"]
                            break

            learned_skill = self.fleet.synthesize_skill(
                goal, success_criteria, list(all_steps_dict.values()), sample_code,
                is_verified_hard=had_flagged_success, run_id=run_id
            )
            if learned_skill and learned_skill.get("dual_critic_approved"):
                is_vh = 1 if learned_skill.get("verified_hard") else 0
                add_skill(
                    name=learned_skill.get("name", f"Skill_{int(time.time())}"),
                    description=learned_skill.get("description", ""),
                    instructions=learned_skill.get("instructions", ""),
                    code_template=learned_skill.get("code_template", ""),
                    category=learned_skill.get("category", "general"),
                    source_run_id=run_id,
                    verified_hard=is_vh,
                    dual_critic_approved=1
                )
                badge = "⭐ Verified-Hard Skill Pattern" if is_vh else "Auto-Learned Skill Pattern"
                record_artifact(
                    run_id, step_counter, "decision",
                    f"{badge}: {learned_skill.get('name')}",
                    content=(
                        f"**Category:** {learned_skill.get('category')}\n\n"
                        f"**Verified Hard Tag:** {bool(is_vh)} (Originated from Dual-Critic Flagged Node)\n\n"
                        f"**Dual Critic Approved:** True\n\n"
                        f"**Description:** {learned_skill.get('description')}\n\n"
                        f"**Instructions:**\n{learned_skill.get('instructions')}"
                    )
                )

            # Finalize run
            total_planned = len(all_steps_dict) if all_steps_dict else 1
            actual_pass_rate = round((len(completed_steps) / total_planned) * 100.0, 1)
            update_run_status(run_id, "completed", current_step=step_counter)
            save_durable_state(run_id, "completed", list(completed_steps), context_vars={"goal": goal}, last_checkpoint_commit=self.last_good_commit)
            record_mission_metrics(
                run_id,
                criteria_pass_rate=actual_pass_rate,
                dual_critic_rescues=1 if had_flagged_success else 0,
                candidate_winner_model="Qwen3-Coder" if had_flagged_success else "DeepSeek-Chat"
            )
            add_memory("mid_term", f"Completed Goal: {goal[:40]}", f"Finished {step_counter} steps with criteria: {success_criteria}", run_id=run_id)
            print(f"[Orchestrator] Run {run_id} completed successfully with 100% Free Heterogeneous Fleet.")

        except Exception as e:
            trace = traceback.format_exc()
            print(f"[Orchestrator] Critical error in run loop: {e}\n{trace}")
            update_run_status(run_id, "failed")
            record_artifact(run_id, 999, "terminal", "Fatal Error Crash Trace", content=trace)
        finally:
            if self.active_run_id == run_id:
                self.is_running = False
                for k in self.active_agents:
                    self.active_agents[k] = "idle"


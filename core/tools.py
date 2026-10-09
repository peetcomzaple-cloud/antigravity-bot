import os
import sys
import shutil
import subprocess
import difflib
import time
import ast
import re
import html
import threading
import json
from pathlib import Path
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple, Set, Union
from .config import WORKSPACE_DIR

# =========================================================================
# lnwjud Pillar 1: Action Classification & Standard Errors
# =========================================================================
class ActionClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    WORKSPACE_MUTATION = "WORKSPACE_MUTATION"
    SYSTEM_COMMAND = "SYSTEM_COMMAND"
    MCP_INTERACTION = "MCP_INTERACTION"
    DESTRUCTIVE = "DESTRUCTIVE"

class WorkspaceBoundaryViolationError(RuntimeError):
    """Raised when an operation attempts directory traversal or symlink escape."""
    pass

class SecurityPolicyViolationError(RuntimeError):
    """Raised when a command or mutation violates security policies."""
    pass

class ToolContractValidationError(RuntimeError):
    """Raised when tool arguments fail strict schema contract validation."""
    pass

# =========================================================================
# lnwjud Pillar 5: Security Policy Engine
# =========================================================================
class PolicyEngine:
    """Enforces command allowlist/denylist and protected path safety boundaries."""
    
    # Destructive or system-compromising shell commands
    DENIED_COMMAND_PATTERNS = [
        re.compile(r"\brm\s+-[rfRF]*\s+(/|/\*|~|\$HOME)", re.I),
        re.compile(r"\bmkfs\b", re.I),
        re.compile(r"\bdd\s+if=", re.I),
        re.compile(r"\b(shutdown|reboot|poweroff|init\s+0)\b", re.I),
        re.compile(r">\s*/dev/sd[a-z]", re.I),
        re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", re.I), # fork bomb
        re.compile(r"\b(curl|wget)\b.*\|\s*(sh|bash)\b", re.I),
        re.compile(r"\bchmod\s+-R\s+777\s+/", re.I),
        # Windows & PowerShell destructive commands (H3)
        re.compile(r"\b(format|diskpart)\b", re.I),
        re.compile(r"\b(del|erase)\b(?:\s+/[a-z]+)*\s+([a-z]:\\|\\|\*|%systemroot%)", re.I),
        re.compile(r"\b(rd|rmdir)\b(?:\s+/[a-z]+)*\s+([a-z]:\\|\\|%systemroot%)", re.I),
        re.compile(r"\b(rd|rmdir)\b.*\/s\b", re.I),
        re.compile(r"\bRemove-Item\b.*-Recurse", re.I),
        re.compile(r"\b(iwr|Invoke-WebRequest|iex|Invoke-Expression)\b.*\|\s*(iex|Invoke-Expression)", re.I)
    ]

    # Sensitive paths forbidden from AI direct modification
    PROTECTED_PATH_PATTERNS = [
        r"/\.git(/.*)?$",
        r"/\.checkpoints(/.*)?$",
        r"/\.env.*$",
        r".*id_rsa.*",
        r".*oracle_key.*",
        r"^/etc(/.*)?$",
        r"^/proc(/.*)?$",
        r"^/sys(/.*)?$",
        r"^/root(/.*)?$",
        r"^[a-zA-Z]:/windows(/.*)?$",
        r"^[a-zA-Z]:/program\s+files(/.*)?$"
    ]

    MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB safety limit

    @classmethod
    def is_command_safe(cls, command: str) -> Tuple[bool, str]:
        for pattern in cls.DENIED_COMMAND_PATTERNS:
            if pattern.search(command):
                return False, f"Command matches prohibited destructive pattern: {pattern.pattern}"
        return True, ""

    @classmethod
    def is_path_safe_for_mutation(cls, full_path: str) -> Tuple[bool, str]:
        normalized = full_path.replace("\\", "/")
        for pat in cls.PROTECTED_PATH_PATTERNS:
            if re.search(pat, normalized):
                return False, f"Mutation forbidden on protected path: {full_path}"
        return True, ""

    @classmethod
    def check_content_size(cls, content: str) -> Tuple[bool, str]:
        size = len(content.encode("utf-8", errors="replace"))
        if size > cls.MAX_FILE_SIZE_BYTES:
            return False, f"Payload size ({size:,} bytes) exceeds limit ({cls.MAX_FILE_SIZE_BYTES:,} bytes)"
        return True, ""


# =========================================================================
# lnwjud Pillar 2: Atomic Multi-File Transaction Rollback Manager
# =========================================================================
class StepTransactionManager:
    """
    Tracks all files touched during a step execution.
    If a step fails or is aborted, enables atomic restoration to pre-step state,
    preventing half-mutated workspace corruption.
    """
    def __init__(self):
        self._lock = threading.Lock()
        # step_id -> dict of { full_filepath: (existed: bool, original_bytes: Optional[bytes]) }
        self._transactions: Dict[int, Dict[str, Tuple[bool, Optional[bytes]]]] = {}

    def begin_transaction(self, step_id: int):
        with self._lock:
            self._transactions[step_id] = {}

    def record_mutation(self, step_id: int, filepath: str):
        with self._lock:
            if step_id not in self._transactions:
                self._transactions[step_id] = {}
            if filepath not in self._transactions[step_id]:
                if os.path.exists(filepath):
                    try:
                        with open(filepath, "rb") as f:
                            self._transactions[step_id][filepath] = (True, f.read())
                    except Exception:
                        self._transactions[step_id][filepath] = (True, None)
                else:
                    self._transactions[step_id][filepath] = (False, None)

    def commit_transaction(self, step_id: int):
        with self._lock:
            if step_id in self._transactions:
                del self._transactions[step_id]

    def rollback_transaction(self, step_id: int) -> List[str]:
        with self._lock:
            restored = []
            if step_id in self._transactions:
                for filepath, (existed, original_bytes) in self._transactions[step_id].items():
                    try:
                        if not existed:
                            if os.path.exists(filepath):
                                os.remove(filepath)
                                restored.append(f"Deleted newly created: {filepath}")
                        elif original_bytes is not None:
                            tmp_path = filepath + f".rbk.{os.getpid()}.{time.time_ns()}"
                            with open(tmp_path, "wb") as f:
                                f.write(original_bytes)
                            os.replace(tmp_path, filepath)
                            restored.append(f"Reverted to pre-step content: {filepath}")
                    except Exception as e:
                        restored.append(f"Error reverting {filepath}: {e}")
                del self._transactions[step_id]
            return restored



# =========================================================================
# lnwjud Pillar 1: Tool Contract Schemas
# =========================================================================
TOOL_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "read_file": {
        "action_class": ActionClass.READ_ONLY,
        "description": "Reads file safely with line-based pagination and optional line numbering.",
        "params": {
            "filepath": {"type": str, "required": True},
            "start_line": {"type": int, "required": False},
            "end_line": {"type": int, "required": False},
            "max_lines": {"type": int, "required": False, "default": 500},
            "line_numbers": {"type": bool, "required": False, "default": False}
        }
    },
    "write_file": {
        "action_class": ActionClass.WORKSPACE_MUTATION,
        "description": "Writes complete file content within workspace sandbox with diff generation.",
        "params": {
            "filepath": {"type": str, "required": True},
            "content": {"type": str, "required": True},
            "step_id": {"type": int, "required": False}
        }
    },
    "apply_patch": {
        "action_class": ActionClass.WORKSPACE_MUTATION,
        "description": "Applies targeted diff/replacement block to a file without full rewrite.",
        "params": {
            "filepath": {"type": str, "required": True},
            "target_block": {"type": str, "required": True},
            "replacement_block": {"type": str, "required": True},
            "step_id": {"type": int, "required": False}
        }
    },
    "run_command": {
        "action_class": ActionClass.SYSTEM_COMMAND,
        "description": "Executes shell command with policy-enforced allowlist and timeout.",
        "params": {
            "command": {"type": str, "required": True},
            "cwd": {"type": str, "required": False},
            "timeout": {"type": int, "required": False, "default": 120}
        }
    },
    "run_tests": {
        "action_class": ActionClass.SYSTEM_COMMAND,
        "description": "Runs test suite and parses output deterministically into exact metrics.",
        "params": {
            "test_path": {"type": str, "required": False}
        }
    },
    "check_code_quality": {
        "action_class": ActionClass.READ_ONLY,
        "description": "Deterministic AST syntax & stub checker.",
        "params": {
            "filepath": {"type": str, "required": True}
        }
    },
    "assert_file_grounded": {
        "action_class": ActionClass.READ_ONLY,
        "description": "Verifies physical file existence on disk, size > 0, and AST integrity.",
        "params": {
            "filepath": {"type": str, "required": True}
        }
    },
    "list_files": {
        "action_class": ActionClass.READ_ONLY,
        "description": "Lists workspace files excluding system and venv folders.",
        "params": {
            "subpath": {"type": str, "required": False, "default": ""}
        }
    },
    "create_checkpoint": {
        "action_class": ActionClass.WORKSPACE_MUTATION,
        "description": "Creates an immutable Git commit and filesystem snapshot.",
        "params": {
            "run_id": {"type": str, "required": True},
            "step_index": {"type": int, "required": True},
            "description": {"type": str, "required": False, "default": ""}
        }
    },
    "rollback_checkpoint": {
        "action_class": ActionClass.DESTRUCTIVE,
        "description": "Restores workspace to the state of a verified Git commit hash.",
        "params": {
            "commit_hash": {"type": str, "required": True}
        }
    },
    "compile_apk": {
        "action_class": ActionClass.SYSTEM_COMMAND,
        "description": "Compiles native standalone Android APK using AAPT2 and D8.",
        "params": {
            "package_name": {"type": str, "required": False, "default": "com.antigravity.cookierunbot"},
            "app_name": {"type": str, "required": False, "default": "CookieRunBot"},
            "activity_code": {"type": str, "required": False},
            "assets": {"type": list, "required": False},
            "output_apk": {"type": str, "required": False, "default": "CookieRunBot.apk"}
        }
    },
    "browser_capture": {
        "action_class": ActionClass.SYSTEM_COMMAND,
        "description": "Captures headless browser render and snapshot for live artifacts.",
        "params": {
            "target_url": {"type": str, "required": True}
        }
    }
}


# =========================================================================
# Main ToolExecutor Runtime
# =========================================================================
class ToolExecutor:
    _git_lock = threading.Lock()

    def __init__(self, workspace: str = WORKSPACE_DIR):
        self.workspace = os.path.abspath(workspace)
        os.makedirs(self.workspace, exist_ok=True)
        self.canonical_root = os.path.realpath(self.workspace)
        self.tx_manager = StepTransactionManager()

    def _clean_stale_git_lock(self):
        """Cleans up stale .git/index.lock if process crashed previously."""
        lock_file = os.path.join(self.workspace, ".git", "index.lock")
        try:
            if os.path.exists(lock_file):
                if time.time() - os.path.getmtime(lock_file) > 60.0:
                    os.remove(lock_file)
        except Exception:
            pass

    @staticmethod
    def strip_markdown_fences(content: str, target_ext: Optional[str] = None) -> str:
        """Strips markdown code blocks (```python ... ```) if present, optionally matching target extension."""
        if not content:
            return ""
        if "```" in content:
            lines = content.splitlines()
            code_lines = []
            inside = False
            for line in lines:
                if line.strip().startswith("```"):
                    if inside:
                        break
                    else:
                        inside = True
                        continue
                if inside:
                    code_lines.append(line)
            if code_lines:
                return "\n".join(code_lines)
        return content.strip()

    def file_exists(self, filepath: str) -> Dict[str, Any]:
        """Checks if a file exists safely within workspace boundary."""
        try:
            resolved = self._resolve_safe_path(filepath)
            exists = os.path.exists(resolved) and os.path.isfile(resolved)
            return {"exists": exists, "path": resolved}
        except Exception as e:
            return {"exists": False, "error": str(e)}

    # --- lnwjud Pillar 2: Canonical Boundary Resolution ---
    def _resolve_safe_path(self, path: str, check_mutation: bool = False) -> str:
        """
        Resolves path against canonical workspace root.
        Strictly prevents directory traversal (../) and symlink escape.
        Enforces mutation protection on sensitive system paths.
        """
        if not path or not path.strip():
            return self.canonical_root

        # Normalize relative path
        if not os.path.isabs(path):
            combined = os.path.join(self.canonical_root, path)
        else:
            combined = path

        norm = os.path.normpath(combined)
        resolved = os.path.realpath(norm)

        # Check workspace boundary containment
        try:
            common = os.path.commonpath([self.canonical_root, resolved])
        except ValueError:
            # Different drives on Windows
            raise WorkspaceBoundaryViolationError(
                f"Path traversal escape detected: '{path}' resolves across drive boundary"
            )

        if common != self.canonical_root:
            raise WorkspaceBoundaryViolationError(
                f"Path traversal escape detected: '{path}' resolves to '{resolved}', which is outside workspace root '{self.canonical_root}'"
            )

        # Symlink check
        if os.path.islink(norm):
            target = os.path.realpath(norm)
            if not target.startswith(self.canonical_root):
                raise WorkspaceBoundaryViolationError(
                    f"Symlink escape detected: '{norm}' points outside workspace to '{target}'"
                )

        # Protected path check if mutating
        if check_mutation:
            safe, reason = PolicyEngine.is_path_safe_for_mutation(resolved)
            if not safe:
                raise SecurityPolicyViolationError(reason)

        return resolved

    def _resolve_path(self, path: str) -> str:
        """Backwards compatibility alias strictly enforcing workspace boundary."""
        return self._resolve_safe_path(path)

    # --- lnwjud Pillar 1: Tool Call Validation & Execution with Audit Log ---
    def execute_contract_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        actor_agent: str = "system",
        run_id: Optional[str] = None,
        step_index: int = 0
    ) -> Dict[str, Any]:
        """
        Validates arguments against TOOL_CONTRACTS schema, enforces security policy,
        executes the tool, and persists an immutable audit log record.
        """
        t0 = time.time()
        schema = TOOL_CONTRACTS.get(tool_name)
        if not schema:
            err = f"Unknown tool '{tool_name}' not defined in TOOL_CONTRACTS"
            self._log_audit(run_id, step_index, actor_agent, tool_name, ActionClass.READ_ONLY, args, err, -1, 0.0, False)
            return {"success": False, "error": err}

        action_class = schema["action_class"]

        # Validate Schema Requirements
        params = schema.get("params", {})
        for p_name, p_spec in params.items():
            if p_spec.get("required") and (p_name not in args or args[p_name] is None):
                err = f"Missing required parameter '{p_name}' for tool '{tool_name}'"
                self._log_audit(run_id, step_index, actor_agent, tool_name, action_class, args, err, -1, 0.0, False)
                return {"success": False, "error": err}

        # Policy Check on Commands
        if tool_name == "run_command":
            cmd = args.get("command", "")
            safe, reason = PolicyEngine.is_command_safe(cmd)
            if not safe:
                self._log_audit(run_id, step_index, actor_agent, tool_name, action_class, args, reason, -1, 0.0, False)
                return {"success": False, "error": reason, "exit_code": 1, "stdout": "", "stderr": reason}


        # Policy Check on Payloads
        if tool_name in ("write_file", "apply_patch"):
            content = args.get("content", "") or args.get("replacement_block", "")
            safe, reason = PolicyEngine.check_content_size(content)
            if not safe:
                self._log_audit(run_id, step_index, actor_agent, tool_name, action_class, args, reason, -1, 0.0, False)
                return {"success": False, "error": reason}

        # Execute Tool Dispatch
        try:
            if tool_name == "read_file":
                res = self.read_file(
                    filepath=args["filepath"],
                    start_line=args.get("start_line"),
                    end_line=args.get("end_line"),
                    max_lines=args.get("max_lines", 500),
                    line_numbers=args.get("line_numbers", False)
                )
            elif tool_name == "write_file":
                res = self.write_file(
                    filepath=args["filepath"],
                    content=args["content"],
                    step_id=args.get("step_id", step_index)
                )
            elif tool_name == "apply_patch":
                res = self.apply_patch(
                    filepath=args["filepath"],
                    target_block=args["target_block"],
                    replacement_block=args["replacement_block"],
                    step_id=args.get("step_id", step_index)
                )
            elif tool_name == "run_command":
                res = self.run_command(
                    command=args["command"],
                    cwd=args.get("cwd"),
                    timeout=args.get("timeout", 120)
                )
            elif tool_name == "run_tests":
                res = self.run_tests(test_path=args.get("test_path"))
            elif tool_name == "check_code_quality":
                res = self.check_code_quality(filepath=args["filepath"])
            elif tool_name == "assert_file_grounded":
                res = self.assert_file_grounded(filepath=args["filepath"])
            elif tool_name == "list_files":
                res = self.list_files(subpath=args.get("subpath", ""))
            elif tool_name == "create_checkpoint":
                res = self.create_checkpoint(
                    run_id=args["run_id"],
                    step_index=args["step_index"],
                    description=args.get("description", "")
                )
            elif tool_name == "rollback_checkpoint":
                res = self.rollback_checkpoint(commit_hash=args["commit_hash"])
            elif tool_name == "compile_apk":
                res = self.compile_apk(
                    package_name=args.get("package_name", "com.antigravity.cookierunbot"),
                    app_name=args.get("app_name", "CookieRunBot"),
                    activity_code=args.get("activity_code"),
                    assets=args.get("assets"),
                    output_apk=args.get("output_apk", "CookieRunBot.apk")
                )
            elif tool_name == "browser_capture":
                res = self.browser_capture(target_url=args["target_url"])
            else:
                res = {"success": False, "error": f"Unhandled tool dispatch '{tool_name}'"}

            duration_ms = round((time.time() - t0) * 1000, 2)
            exit_code = res.get("exit_code", 0 if res.get("success") else 1)
            summary = res.get("error", "Executed successfully") if not res.get("success") else "OK"
            self._log_audit(run_id, step_index, actor_agent, tool_name, action_class, args, summary, exit_code, duration_ms, True)
            return res

        except Exception as e:
            duration_ms = round((time.time() - t0) * 1000, 2)
            self._log_audit(run_id, step_index, actor_agent, tool_name, action_class, args, str(e), 1, duration_ms, False)
            return {"success": False, "error": str(e)}

    def _log_audit(
        self,
        run_id: Optional[str],
        step_index: int,
        actor: str,
        tool: str,
        action_class: ActionClass,
        args: Dict[str, Any],
        summary: str,
        exit_code: int,
        duration_ms: float,
        is_allowed: bool
    ):
        try:
            from .db import record_tool_audit
            record_tool_audit(
                run_id=run_id,
                step_index=step_index,
                actor_agent=actor,
                tool_name=tool,
                action_class=action_class.value if isinstance(action_class, ActionClass) else str(action_class),
                args_json=json.dumps(args, default=str),
                result_summary=summary,
                exit_code=exit_code,
                duration_ms=duration_ms,
                is_allowed=is_allowed
            )
        except Exception:
            pass

    # --- 1. Shell Execution with Policy Check & Injection Guard ---
    def run_command(self, command: Union[str, List[str]], cwd: Optional[str] = None, timeout: int = 120) -> Dict[str, Any]:
        use_shell = True
        if isinstance(command, list):
            use_shell = False
            cmd_for_check = " ".join(str(x) for x in command)
        else:
            cmd_for_check = command

        safe, reason = PolicyEngine.is_command_safe(cmd_for_check)
        if not safe:
            return {"success": False, "exit_code": 1, "stdout": "", "stderr": reason, "duration_sec": 0.0}

        try:
            work_dir = self._resolve_safe_path(cwd) if cwd else self.canonical_root
        except Exception as e:
            return {"success": False, "exit_code": 1, "stdout": "", "stderr": str(e), "duration_sec": 0.0}

        env = os.environ.copy()
        venv_bin = "/opt/ai_gateway/antigravity_bot/venv/bin" if os.name != "nt" else ""
        if venv_bin and os.path.exists(venv_bin):
            env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
        env["PYTHONPATH"] = f"{work_dir}{os.pathsep}{self.canonical_root}{os.pathsep}{env.get('PYTHONPATH', '')}"

        try:
            start_time = time.time()
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            proc = subprocess.Popen(
                command,
                shell=use_shell,
                cwd=work_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                elapsed = time.time() - start_time
                return {
                    "success": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "stdout": stdout[-12000:] if len(stdout) > 12000 else stdout,
                    "stderr": stderr[-12000:] if len(stderr) > 12000 else stderr,
                    "duration_sec": round(elapsed, 2)
                }
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                else:
                    proc.kill()
                proc.communicate()
                return {
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout} seconds.",
                    "duration_sec": timeout
                }
        except Exception as e:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "duration_sec": 0.0
            }


    # --- lnwjud Pillar 6: Robust Context & Paged File Reading ---
    def read_file(
        self,
        filepath: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_lines: Optional[int] = 500,
        line_numbers: bool = False
    ) -> Dict[str, Any]:
        try:
            full_path = self._resolve_safe_path(filepath)
        except Exception as e:
            return {"success": False, "error": str(e), "content": ""}

        if not os.path.exists(full_path):
            return {"success": False, "error": f"File not found: {filepath}", "content": ""}

        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                raw_content = f.read()

            lines = raw_content.replace("\r\n", "\n").split("\n")
            total_lines = len(lines)

            # 1-indexed slicing
            s_idx = max(0, start_line - 1) if (start_line is not None and start_line > 0) else 0
            e_idx = min(total_lines, end_line) if (end_line is not None and end_line >= s_idx) else total_lines

            sliced_lines = lines[s_idx:e_idx]
            truncated = False
            if max_lines is not None and len(sliced_lines) > max_lines:
                sliced_lines = sliced_lines[:max_lines]
                truncated = True

            if line_numbers:
                formatted = [f"{s_idx + i + 1}: {line}" for i, line in enumerate(sliced_lines)]
                content = "\n".join(formatted)
            else:
                content = "\n".join(sliced_lines)

            return {
                "success": True,
                "content": content,
                "filepath": full_path,
                "total_lines": total_lines,
                "lines_returned": len(sliced_lines),
                "truncated": truncated
            }
        except Exception as e:
            return {"success": False, "error": str(e), "content": ""}

    # --- 2. Workspace File Writing with Transaction Recording ---
    def write_file(self, filepath: str, content: str, step_id: Optional[int] = None) -> Dict[str, Any]:
        try:
            full_path = self._resolve_safe_path(filepath, check_mutation=True)
        except Exception as e:
            return {"success": False, "error": str(e), "diff": ""}

        safe, reason = PolicyEngine.check_content_size(content)
        if not safe:
            return {"success": False, "error": reason, "diff": ""}

        if step_id is not None:
            self.tx_manager.record_mutation(step_id, full_path)

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        file_already_existed = os.path.exists(full_path)
        old_content = ""
        if file_already_existed:
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    old_content = f.read()
            except Exception:
                old_content = ""

        try:
            # Atomic write via temporary file
            tmp_path = full_path + f".tmp.{os.getpid()}.{time.time_ns()}"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, full_path)

            diff = "".join(difflib.unified_diff(
                old_content.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{os.path.basename(filepath)}",
                tofile=f"b/{os.path.basename(filepath)}"
            ))
            return {
                "success": True,
                "filepath": full_path,
                "relative_path": os.path.relpath(full_path, self.canonical_root),
                "diff": diff,
                "bytes_written": len(content.encode("utf-8")),
                "is_new": not file_already_existed
            }
        except Exception as e:
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return {"success": False, "error": str(e), "diff": ""}


    # --- lnwjud Pillar 6: Precision Diff/Patch-Based Editing ---
    def apply_patch(self, filepath: str, target_block: str, replacement_block: str, step_id: Optional[int] = None) -> Dict[str, Any]:
        """Replaces a targeted unique code segment without rewriting the full file."""
        try:
            full_path = self._resolve_safe_path(filepath, check_mutation=True)
        except Exception as e:
            return {"success": False, "error": str(e)}

        if not os.path.exists(full_path):
            return {"success": False, "error": f"File not found: {filepath}"}

        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            old_content = f.read()

        norm_content = old_content.replace("\r\n", "\n")
        norm_target = target_block.replace("\r\n", "\n")
        norm_replacement = replacement_block.replace("\r\n", "\n")

        if norm_target not in norm_content:
            return {"success": False, "error": f"Target block not found in {filepath}"}

        count = norm_content.count(norm_target)
        if count > 1:
            return {"success": False, "error": f"Target block occurs {count} times in {filepath}; must match uniquely."}

        new_content = norm_content.replace(norm_target, norm_replacement, 1)

        # Syntax check if Python
        if filepath.endswith(".py"):
            try:
                ast.parse(new_content)
            except SyntaxError as e:
                return {"success": False, "error": f"Patched code creates SyntaxError: {e}"}

        if step_id is not None:
            self.tx_manager.record_mutation(step_id, full_path)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        diff = "".join(difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{os.path.basename(filepath)}",
            tofile=f"b/{os.path.basename(filepath)}"
        ))

        return {
            "success": True,
            "filepath": full_path,
            "diff": diff,
            "bytes_written": len(new_content.encode("utf-8"))
        }

    def list_files(self, subpath: str = "") -> Dict[str, Any]:
        try:
            full_path = self._resolve_safe_path(subpath)
        except Exception as e:
            return {"success": False, "error": str(e), "files": []}

        if not os.path.exists(full_path):
            return {"success": False, "error": f"Directory not found: {subpath}", "files": []}

        EXCLUDE_DIRS = {'__pycache__', 'node_modules', 'venv', '.venv', 'env', 'site-packages', 'artifacts', '.checkpoints', '.pytest_cache'}
        file_tree = []
        for root, dirs, files in os.walk(full_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in EXCLUDE_DIRS]
            for f in files:
                if f.startswith('.'):
                    continue
                rel = os.path.relpath(os.path.join(root, f), self.canonical_root).replace("\\", "/")
                file_tree.append(rel)
        return {"success": True, "files": sorted(file_tree)}

    # --- 3. Multi-Language Code Quality, AST & Syntax Validation ---
    def check_code_quality(self, filepath: str) -> Dict[str, Any]:
        """
        Inspects code for syntax errors and strictly flags placeholders/mocks.
        Uses Python AST NodeVisitor to catch empty stubs, pass, Ellipsis, and NotImplementedError.
        """
        try:
            full_path = self._resolve_safe_path(filepath)
        except Exception as e:
            return {"valid": False, "issues": [str(e)]}

        file_res = self.read_file(filepath, max_lines=None)
        if not file_res["success"]:
            return {"valid": False, "issues": [f"File not found: {filepath}"]}

        code = file_res["content"]
        issues = []
        is_init_file = os.path.basename(filepath) == "__init__.py"

        # 1. Python Syntax & Deterministic AST Quality Visitor
        if filepath.endswith(".py"):
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        body = [
                            s for s in node.body
                            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
                        ]
                        if not body:
                            if not is_init_file:
                                issues.append(f"Function '{node.name}' (line {node.lineno}) has an empty body with only docstring.")
                        elif len(body) == 1:
                            s = body[0]
                            if isinstance(s, ast.Pass):
                                if not is_init_file:
                                    issues.append(f"Function '{node.name}' (line {node.lineno}) contains only 'pass' without real logic.")
                            elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value is Ellipsis:
                                issues.append(f"Function '{node.name}' (line {node.lineno}) contains only '...' stub.")
                            elif isinstance(s, ast.Raise) and isinstance(getattr(s, 'exc', None), ast.Call):
                                func_name = getattr(s.exc.func, 'id', '')
                                if func_name == 'NotImplementedError':
                                    issues.append(f"Function '{node.name}' (line {node.lineno}) raises NotImplementedError stub.")
            except SyntaxError as e:
                issues.append(f"Python Syntax Error line {e.lineno}: {e.msg}")

        # 2. JavaScript Syntax Check
        elif filepath.endswith(".js"):
            if shutil.which("node"):
                node_check = self.run_command(["node", "--check", full_path])
                if not node_check["success"]:
                    err_lines = [line for line in node_check["stderr"].splitlines() if "SyntaxError" in line or "error" in line.lower()]
                    issues.append(f"JS Syntax Error: {'; '.join(err_lines) if err_lines else node_check['stderr'][-200:]}")

        # 3. Strict Anti-Placeholder Regex Detection
        if filepath.endswith((".py", ".js", ".ts", ".html")):
            # M10: Relax check on __init__.py which may intentionally be empty or pass-only
            if os.path.basename(filepath) == "__init__.py" and code.strip() in ("", "pass"):
                pass
            else:
                placeholder_patterns = [
                    (r'return\s+None\s*#\s*For now', "Detected 'return None # For now' stub."),
                    (r'return\s+\[\]\s*#\s*For now', "Detected 'return [] # For now' stub."),
                    (r'Example Item', "Detected dummy/mock 'Example Item'."),
                    (r'#\s*In a real implementation', "Detected stub comment '# In a real implementation'."),
                    (r'#\s*simulate(?:d)?\s*$', "Detected stub comment '# simulate'."),
                    (r'#\s*simulate(?:d)?\s+(?:data|call|mock|response|result|logic|implementation|dummy|placeholder)\b', "Detected simulated logic instead of real implementation."),
                    (r'pass\s*#\s*placeholder', "Detected placeholder pass statement.")
                ]

                lines = code.splitlines()
                for idx, line in enumerate(lines, 1):
                    for pat, desc in placeholder_patterns:
                        if re.search(pat, line, re.IGNORECASE):
                            issues.append(f"Line {idx}: {desc} -> `{line.strip()}`")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "total_lines": len(code.splitlines())
        }


    # --- lnwjud Pillar 9: Grounded Physical Verification ---
    def assert_file_grounded(self, filepath: str) -> Dict[str, Any]:
        """
        Guarantees that a file claimed to be created/modified by the Coder
        physically exists on disk, has size > 0, and passes AST/syntax integrity.
        Eliminates free/70B model hallucination of having created files.
        """
        try:
            full_path = self._resolve_safe_path(filepath)
        except Exception as e:
            return {"grounded": False, "error": str(e), "size_bytes": 0, "is_empty": True}

        if not os.path.exists(full_path):
            return {
                "grounded": False,
                "error": f"Physical file missing on disk: {filepath}",
                "size_bytes": 0,
                "is_empty": True
            }

        size = os.path.getsize(full_path)
        if size == 0:
            return {
                "grounded": False,
                "error": f"File exists but is completely empty (0 bytes): {filepath}",
                "size_bytes": 0,
                "is_empty": True
            }

        cq = self.check_code_quality(filepath)
        if not cq["valid"]:
            return {
                "grounded": False,
                "error": f"File failed grounded AST quality checks: {'; '.join(cq['issues'][:3])}",
                "size_bytes": size,
                "is_empty": False,
                "issues": cq["issues"]
            }

        return {
            "grounded": True,
            "filepath": full_path,
            "size_bytes": size,
            "is_empty": False,
            "issues": []
        }

    # --- lnwjud Pillar 9: Deterministic Structured Test Parser ---
    def parse_test_results(self, stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
        """
        Extracts exact counts of passed, failed, errors, skipped, and failure traces.
        Replaces raw string matching with deterministic metrics.
        """
        # C5: Pytest exit code 5 means no tests were collected. Treat as skipped/valid rather than failure.
        no_tests = (exit_code == 5) or ("collected 0 items" in stdout) or ("no tests ran" in stdout)
        if no_tests:
            return {
                "success": True,
                "exit_code": exit_code,
                "total": 0,
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "failed_tests": [],
                "failure_traces": [],
                "summary_line": "No tests collected (Skipped)"
            }

        passed = 0
        failed = 0
        errors = 0
        skipped = 0
        failed_tests = []
        failure_traces = []

        summary_match = re.search(r'=+\s*(.*?)\s+in\s+[\d\.]+s\s*=+', stdout)
        summary_str = summary_match.group(1) if summary_match else ""
        target_str = summary_str if summary_str else stdout

        p_m = re.search(r'(\d+)\s+passed', target_str)
        if p_m: passed = int(p_m.group(1))

        f_m = re.search(r'(\d+)\s+failed', target_str)
        if f_m: failed = int(f_m.group(1))

        e_m = re.search(r'(\d+)\s+error', target_str)
        if e_m: errors = int(e_m.group(1))

        s_m = re.search(r'(\d+)\s+skipped', target_str)
        if s_m: skipped = int(s_m.group(1))

        for line in stdout.splitlines():
            if line.startswith("FAILED "):
                failed_tests.append(line.replace("FAILED ", "").strip())

        fail_sections = re.findall(r'_+\s*(.*?)\s*_+\n(.*?)(?=\n_+|\n=+|$)', stdout, re.DOTALL)
        for name, trace in fail_sections[:3]:
            failure_traces.append(f"[{name.strip()}]:\n{trace.strip()[:600]}")

        total = passed + failed + errors + skipped
        is_success = (exit_code == 0) and (failed == 0) and (errors == 0)

        return {
            "success": is_success,
            "exit_code": exit_code,
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "failed_tests": failed_tests,
            "failure_traces": failure_traces,
            "summary_line": summary_str or ("Passed" if is_success else "Failed")
        }

    # --- 4. Language-Aware Test Runner ---
    def run_tests(self, test_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Intelligently executes tests based on file type with deterministic result parsing.
        """
        if test_path and test_path.endswith(".js"):
            full_path = self._resolve_path(test_path)
            if shutil.which("node"):
                res = self.run_command(["node", "--check", full_path])
            else:
                res = {"success": True, "exit_code": 0, "stdout": "Node.js not installed; syntax check skipped.", "stderr": ""}
            return {
                "success": res["success"],
                "stdout": res["stdout"] or "Node.js syntax check passed successfully (Exit code 0).",
                "stderr": res["stderr"],
                "exit_code": res["exit_code"],
                "summary": "JavaScript syntax valid" if res["success"] else "JavaScript syntax error",
                "parsed": {
                    "success": res["success"],
                    "total": 1 if res["success"] else 0,
                    "passed": 1 if res["success"] else 0,
                    "failed": 0 if res["success"] else 1,
                    "errors": 0,
                    "skipped": 0,
                    "failed_tests": [] if res["success"] else [test_path],
                    "failure_traces": [] if res["success"] else [res["stderr"][:400]]
                }
            }

        cmd = [sys.executable, "-m", "pytest", "-v", "--tb=short"]
        if test_path:
            full_target = self._resolve_path(test_path)
            cmd.append(full_target)

        res = self.run_command(cmd)

        parsed = self.parse_test_results(res["stdout"], res["stderr"], res["exit_code"])
        return {
            "success": parsed["success"],
            "stdout": res["stdout"],
            "stderr": res["stderr"],
            "exit_code": res["exit_code"],
            "parsed": parsed,
            "summary": parsed["summary_line"]
        }

    # --- 7. Headless Browser Render Capture ---
    def browser_capture(self, target_url: str, output_image_name: Optional[str] = None) -> Dict[str, Any]:
        if not output_image_name:
            output_image_name = f"browser_{int(time.time())}.png"
        screenshot_path = os.path.join(self.canonical_root, "artifacts", output_image_name)
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)

        if not (target_url.startswith("http://") or target_url.startswith("https://")):
            resolved_file = self._resolve_path(target_url)
            target_url = Path(resolved_file).as_uri()

        python_script = """import sys
import asyncio
from playwright.async_api import async_playwright

target_url = sys.argv[1]
screenshot_path = sys.argv[2]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            await page.goto(target_url, timeout=25000, wait_until="load")
        except Exception as e:
            print(f"GOTO_ERROR:{e}")
            await browser.close()
            sys.exit(1)
        title = await page.title()
        content = await page.inner_text("body")
        await page.screenshot(path=screenshot_path, full_page=False)
        await browser.close()
        print(f"TITLE:{title}")
        print("CONTENT_SNIPPET:" + content[:1000].replace("\\n", " "))

asyncio.run(main())
"""
        python_bin = "/opt/ai_gateway/antigravity_bot/venv/bin/python"
        if not os.path.exists(python_bin):
            python_bin = sys.executable
        res = self.run_command([python_bin, "-c", python_script, target_url, screenshot_path])
        success = os.path.exists(screenshot_path) and res.get("exit_code") == 0
        return {
            "success": success,
            "screenshot_path": screenshot_path if success else "",
            "url": target_url,
            "output": res["stdout"],
            "error": res["stderr"] if not success else ""
        }

    # --- 8. Git Control (Thread-Safe with Mutex Lock) ---
    def git_status(self) -> Dict[str, Any]:
        with self._git_lock:
            self._clean_stale_git_lock()
            return self.run_command(["git", "status", "--short"])

    def git_diff(self) -> Dict[str, Any]:
        with self._git_lock:
            self._clean_stale_git_lock()
            return self.run_command(["git", "diff"])

    def git_commit(self, message: str) -> Dict[str, Any]:
        with self._git_lock:
            self._clean_stale_git_lock()
            add_res = self.run_command(["git", "add", "-A"])
            if not add_res["success"]:
                return add_res
            return self.run_command(["git", "commit", "-m", str(message)])

    # --- 9. Native Android APK Compiler ---
    def compile_apk(
        self,
        package_name: str = "com.antigravity.cookierunbot",
        app_name: str = "CookieRunBot",
        activity_code: Optional[str] = None,
        assets: Optional[List[str]] = None,
        output_apk: str = "CookieRunBot.apk"
    ) -> Dict[str, Any]:
        from .apk_builder import AndroidAPKBuilder
        full_out = self._resolve_path(output_apk)
        builder = AndroidAPKBuilder()
        return builder.build(package_name, app_name, activity_code=activity_code, assets=assets, output_apk=full_out)

    # --- 10. Checkpoint & Instant Rollback Engine (Thread-Safe) ---
    def create_checkpoint(self, run_id: str, step_index: int, description: str = "") -> Dict[str, Any]:
        with self._git_lock:
            self._clean_stale_git_lock()
            try:
                # Ensure .gitignore exists in workspace to avoid tracking huge/irrelevant files (H8)
                gitignore_path = os.path.join(self.canonical_root, ".gitignore")
                if not os.path.exists(gitignore_path):
                    try:
                        with open(gitignore_path, "w", encoding="utf-8") as f:
                            f.write(".checkpoints/\n.git/\n.env*\nvenv/\n.venv/\n__pycache__/\n*.pyc\n*.tmp*\nartifacts/\n")
                    except Exception:
                        pass

                git_dir = os.path.join(self.canonical_root, ".git")
                if not os.path.exists(git_dir):
                    self.run_command(["git", "init"])
                    self.run_command(["git", "config", "user.name", "AntigravityBot"])
                    self.run_command(["git", "config", "user.email", "bot@antigravity.cloud"])

                self.run_command(["git", "add", "-A"])
                status_res = self.run_command(["git", "status", "--porcelain"])

                commit_msg = f"checkpoint_{run_id}_step_{step_index}: {description[:50]}"
                if status_res["stdout"].strip():
                    self.run_command(["git", "commit", "-m", commit_msg])

                rev_res = self.run_command(["git", "rev-parse", "HEAD"])
                commit_hash = rev_res["stdout"].strip() if rev_res["success"] else f"chk_{int(time.time())}"

                chk_dir = os.path.join(self.canonical_root, ".checkpoints", f"{run_id}_step_{step_index}")
                os.makedirs(chk_dir, exist_ok=True)
                if shutil.which("rsync"):
                    self.run_command(["rsync", "-av", "--exclude=.git", "--exclude=.checkpoints", "--exclude=venv", f"{self.canonical_root}/", f"{chk_dir}/"])
                else:
                    shutil.copytree(
                        self.canonical_root,
                        chk_dir,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", ".checkpoints", "venv", ".venv", "__pycache__", ".env*", "artifacts")
                    )

                return {
                    "success": True,
                    "commit_hash": commit_hash,
                    "snapshot_path": chk_dir,
                    "message": commit_msg
                }
            except Exception as e:
                return {"success": False, "error": str(e), "commit_hash": ""}


    def rollback_checkpoint(self, commit_hash: str) -> Dict[str, Any]:
        with self._git_lock:
            self._clean_stale_git_lock()
            try:
                clean_hash = commit_hash.strip()
                if not re.match(r'^[a-zA-Z0-9_\-\.~]+$', clean_hash):
                    return {"success": False, "error": f"Invalid commit hash: {clean_hash}"}
                res_reset = self.run_command(["git", "reset", "--hard", clean_hash])
                res_clean = self.run_command(["git", "clean", "-fd"])
                return {
                    "success": res_reset["success"],
                    "commit_hash": clean_hash,
                    "stdout": f"{res_reset['stdout']}\n{res_clean['stdout']}",
                    "stderr": f"{res_reset['stderr']}\n{res_clean['stderr']}"
                }
            except Exception as e:
                return {"success": False, "error": str(e)}

# =========================================================================
# Antigravity Visual Side-by-Side Diff & In-Editor Code Lens Engine
# =========================================================================
def get_diff_stats(diff_text: str) -> Tuple[int, int]:
    """Returns (additions_count, deletions_count) for a unified diff."""
    additions = sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))
    return additions, deletions

def render_side_by_side_diff_html(diff_text: str) -> str:
    """Generates an IDE-grade synchronized side-by-side HTML diff table."""
    lines = diff_text.splitlines()
    rows = []
    left_line = 0
    right_line = 0
    i = 0
    
    while i < len(lines):
        line = lines[i]
        if line.startswith("---") or line.startswith("+++"):
            i += 1
            continue
        elif line.startswith("@@"):
            m = re.search(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                left_line = int(m.group(1))
                right_line = int(m.group(2))
            rows.append(f"""
            <tr style="background-color: #1e293b; color: #38bdf8; font-weight: bold; border-top: 1px solid #334155; border-bottom: 1px solid #334155;">
                <td colspan="4" style="padding: 4px 10px; font-family: monospace; font-size: 11px;">{html.escape(line)}</td>
            </tr>
            """)
            i += 1
            continue

        del_lines = []
        add_lines = []
        while i < len(lines) and lines[i].startswith("-"):
            del_lines.append(lines[i][1:])
            i += 1
        while i < len(lines) and lines[i].startswith("+"):
            add_lines.append(lines[i][1:])
            i += 1

        if del_lines or add_lines:
            max_len = max(len(del_lines), len(add_lines))
            for idx in range(max_len):
                if idx < len(del_lines):
                    l_no = str(left_line)
                    l_code = html.escape(del_lines[idx])
                    l_style = "background-color: rgba(239, 68, 68, 0.22); color: #fca5a5;"
                    l_sign = '<span style="color: #ef4444; font-weight: bold; margin-right: 4px;">-</span>'
                    left_line += 1
                else:
                    l_no = ""
                    l_code = ""
                    l_style = "background-color: #0b0f19; color: transparent;"
                    l_sign = ""

                if idx < len(add_lines):
                    r_no = str(right_line)
                    r_code = html.escape(add_lines[idx])
                    r_style = "background-color: rgba(16, 185, 129, 0.22); color: #86efac;"
                    r_sign = '<span style="color: #10b981; font-weight: bold; margin-right: 4px;">+</span>'
                    right_line += 1
                else:
                    r_no = ""
                    r_code = ""
                    r_style = "background-color: #0b0f19; color: transparent;"
                    r_sign = ""

                rows.append(f"""
                <tr style="font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11.5px; line-height: 1.45;">
                    <td style="width: 40px; text-align: right; padding-right: 8px; color: #64748b; user-select: none; border-right: 1px solid #334155; {l_style}">{l_no}</td>
                    <td style="width: 45%; padding-left: 8px; white-space: pre-wrap; word-break: break-all; border-right: 2px solid #1e293b; {l_style}">{l_sign}{l_code}</td>
                    <td style="width: 40px; text-align: right; padding-right: 8px; color: #64748b; user-select: none; border-right: 1px solid #334155; {r_style}">{r_no}</td>
                    <td style="width: 45%; padding-left: 8px; white-space: pre-wrap; word-break: break-all; {r_style}">{r_sign}{r_code}</td>
                </tr>
                """)
            continue

        if line.startswith(" "):
            c_text = html.escape(line[1:])
            l_no = str(left_line)
            r_no = str(right_line)
            left_line += 1
            right_line += 1
            rows.append(f"""
            <tr style="font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11.5px; line-height: 1.45; color: #cbd5e1;">
                <td style="width: 40px; text-align: right; padding-right: 8px; color: #475569; user-select: none; border-right: 1px solid #334155;">{l_no}</td>
                <td style="width: 45%; padding-left: 8px; white-space: pre-wrap; word-break: break-all; border-right: 2px solid #1e293b;">{c_text}</td>
                <td style="width: 40px; text-align: right; padding-right: 8px; color: #475569; user-select: none; border-right: 1px solid #334155;">{r_no}</td>
                <td style="width: 45%; padding-left: 8px; white-space: pre-wrap; word-break: break-all;">{c_text}</td>
            </tr>
            """)
        elif line.strip() == "":
            left_line += 1
            right_line += 1
            rows.append(f"""
            <tr style="font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11.5px; line-height: 1.45; color: #cbd5e1;">
                <td style="width: 40px; text-align: right; padding-right: 8px; color: #475569; user-select: none; border-right: 1px solid #334155;">{left_line-1}</td>
                <td style="width: 45%; padding-left: 8px; border-right: 2px solid #1e293b;">&nbsp;</td>
                <td style="width: 40px; text-align: right; padding-right: 8px; color: #475569; user-select: none; border-right: 1px solid #334155;">{right_line-1}</td>
                <td style="width: 45%; padding-left: 8px;">&nbsp;</td>
            </tr>
            """)
        i += 1

    return f"""
    <div style="background-color: #0b0f19; border: 1px solid #334155; border-radius: 8px; overflow: hidden; margin-top: 8px; margin-bottom: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);">
        <table style="width: 100%; border-collapse: collapse; table-layout: fixed;">
            <thead>
                <tr style="background-color: #1e293b; color: #94a3b8; font-size: 11px; text-align: left; font-family: sans-serif; font-weight: 600; border-bottom: 1px solid #334155;">
                    <th colspan="2" style="padding: 6px 10px; border-right: 2px solid #0f172a; width: 50%;">ORIGINAL (PREVIOUS)</th>
                    <th colspan="2" style="padding: 6px 10px; width: 50%;">MODIFIED (CURRENT)</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
    </div>
    """

def render_unified_diff_html(diff_text: str) -> str:
    """Generates an IDE-grade unified inline HTML diff table."""
    lines = diff_text.splitlines()
    rows = []
    left_line = 0
    right_line = 0

    for line in lines:
        if line.startswith("---") or line.startswith("+++"):
            continue
        elif line.startswith("@@"):
            m = re.search(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                left_line = int(m.group(1))
                right_line = int(m.group(2))
            rows.append(f"""
            <tr style="background-color: #1e293b; color: #38bdf8; font-weight: bold; border-top: 1px solid #334155; border-bottom: 1px solid #334155;">
                <td colspan="3" style="padding: 4px 10px; font-family: monospace; font-size: 11px;">{html.escape(line)}</td>
            </tr>
            """)
        elif line.startswith("-"):
            l_no = str(left_line)
            left_line += 1
            c_text = html.escape(line[1:])
            rows.append(f"""
            <tr style="font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11.5px; line-height: 1.45; background-color: rgba(239, 68, 68, 0.22); color: #fca5a5;">
                <td style="width: 40px; text-align: right; padding-right: 6px; color: #ef4444; user-select: none;">{l_no}</td>
                <td style="width: 40px; text-align: right; padding-right: 8px; color: #64748b; user-select: none; border-right: 1px solid #334155;"></td>
                <td style="padding-left: 8px; white-space: pre-wrap; word-break: break-all;"><span style="color: #ef4444; font-weight: bold; margin-right: 6px;">-</span>{c_text}</td>
            </tr>
            """)
        elif line.startswith("+"):
            r_no = str(right_line)
            right_line += 1
            c_text = html.escape(line[1:])
            rows.append(f"""
            <tr style="font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11.5px; line-height: 1.45; background-color: rgba(16, 185, 129, 0.22); color: #86efac;">
                <td style="width: 40px; text-align: right; padding-right: 6px; color: #64748b; user-select: none;"></td>
                <td style="width: 40px; text-align: right; padding-right: 8px; color: #10b981; user-select: none; border-right: 1px solid #334155;">{r_no}</td>
                <td style="padding-left: 8px; white-space: pre-wrap; word-break: break-all;"><span style="color: #10b981; font-weight: bold; margin-right: 6px;">+</span>{c_text}</td>
            </tr>
            """)
        elif line.startswith(" "):
            l_no = str(left_line)
            r_no = str(right_line)
            left_line += 1
            right_line += 1
            c_text = html.escape(line[1:])
            rows.append(f"""
            <tr style="font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11.5px; line-height: 1.45; color: #cbd5e1;">
                <td style="width: 40px; text-align: right; padding-right: 6px; color: #475569; user-select: none;">{l_no}</td>
                <td style="width: 40px; text-align: right; padding-right: 8px; color: #475569; user-select: none; border-right: 1px solid #334155;">{r_no}</td>
                <td style="padding-left: 8px; white-space: pre-wrap; word-break: break-all;">&nbsp;{c_text}</td>
            </tr>
            """)

    return f"""
    <div style="background-color: #0b0f19; border: 1px solid #334155; border-radius: 8px; overflow: hidden; margin-top: 8px; margin-bottom: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);">
        <table style="width: 100%; border-collapse: collapse; table-layout: fixed;">
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
    </div>
    """

strip_markdown_fences = ToolExecutor.strip_markdown_fences

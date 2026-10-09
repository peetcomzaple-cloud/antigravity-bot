import os
import json
import time
import httpx
from typing import List, Dict, Any, Optional, Tuple, Union
from dotenv import load_dotenv

# Load environment configuration securely
for env_path in ["/opt/ai_gateway/antigravity_bot/.env", os.path.join(os.path.dirname(__file__), "..", ".env"), ".env"]:
    if os.path.exists(env_path):
        load_dotenv(env_path)

from .config import AI_GATEWAY_URL, AI_GATEWAY_KEY

GATEWAY_URL = AI_GATEWAY_URL
GATEWAY_KEY = AI_GATEWAY_KEY

def get_openrouter_keys() -> List[str]:
    """Dynamically loads healthy OpenRouter API keys from environment only."""
    keys: List[str] = []
    if os.environ.get("OPENROUTER_API_KEYS"):
        for k in os.environ["OPENROUTER_API_KEYS"].split(","):
            if k.strip():
                keys.append(k.strip())
    for i in range(1, 11):
        k = os.environ.get(f"OPENROUTER_API_KEY_{i}")
        if k and k.strip() and k.strip() not in keys:
            keys.append(k.strip())
    single = os.environ.get("OPENROUTER_API_KEY")
    if single and single.strip() and single.strip() not in keys:
        keys.append(single.strip())
    return keys

# Heterogeneous Multi-Model Fallback Chains with Zero-Cost and Ultra-Low-Cost Backups
ROLE_FALLBACK_CHAINS = {
    # Phase 0: Task Intake
    "intake": ["qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free", "google/gemini-2.0-flash-lite-preview-02-05:free", "speed"],
    # Phase 1: DAG Planner (Kimi K2.6)
    "planner": ["google/gemini-2.0-flash-lite-preview-02-05:free", "qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free", "google/gemini-2.0-flash-lite-preview-02-05:free"],
    # Phase 1.5: Dual-Critic #1 (GLM Family)
    "critic_glm": ["google/gemini-2.0-flash-lite-preview-02-05:free", "z-ai/glm-5.2:free", "google/gemini-2.0-flash-exp:free"],
    # Phase 1.5: Dual-Critic #2 (Qwen Family)
    "critic_qwen": ["qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free"],
    # Phase 2: Swarm Coder Primary (DeepSeek)
    "coder": ["qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free", "google/gemini-2.0-flash-lite-preview-02-05:free", "speed"],
    # Phase 2: Swarm Coder Secondary (Qwen - for flagged node competition or 429 backup)
    "coder_secondary": ["qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free"],
    # Phase 2: Independent Judge (GLM compares DeepSeek vs Qwen candidate code)
    "judge": ["google/gemini-2.0-flash-lite-preview-02-05:free", "google/gemini-2.0-flash-exp:free", "qwen/qwen-2.5-coder-32b-instruct:free"],
    # Reflection & AST Reviews
    "reflector": ["google/gemini-2.0-flash-lite-preview-02-05:free", "qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free"],
    "speed": ["speed", "qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free"],
    "auto": ["qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free", "google/gemini-2.0-flash-lite-preview-02-05:free", "speed"]
}


class TokenBudgetExceededError(RuntimeError):
    pass

class ModelRouter:
    def __init__(self, base_url: str = GATEWAY_URL, api_key: str = GATEWAY_KEY):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.last_model_used = "auto"
        self.last_latency = 0.0
        self.last_tokens_used = 0
        self.mission_tokens_tracker: Dict[str, int] = {}
        self.mission_token_budgets: Dict[str, int] = {}
        self.models_used_per_run: Dict[str, List[str]] = {}
        # Key cooldown tracker: {key_fingerprint: timestamp_when_available}
        self.key_cooldowns: Dict[str, float] = {}

    def set_mission_budget(self, run_id: str, budget: int = 50000):
        self.mission_token_budgets[run_id] = budget
        if run_id not in self.mission_tokens_tracker:
            self.mission_tokens_tracker[run_id] = 0

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        role_type: str = "auto",
        model: Optional[str] = None,
        temperature: float = 0.2,
        response_format: Optional[Dict[str, str]] = None,
        max_tokens: int = 4096,
        run_id: Optional[str] = None
    ) -> str:
        """
        Executes chat completion adhering strictly to the 100% Free / Ultra-Low-Cost Fallback Chain:
        - If role is 'planner', uses moonshotai/kimi-k2.6
        - If role is 'critic_glm', uses z-ai/glm-5.3-flash
        - If role is 'critic_qwen', uses qwen/qwen3-coder
        - If role is 'coder', uses deepseek/deepseek-chat, cascading to qwen/qwen3-coder upon 429
        - If role is 'judge', uses z-ai/glm-5.3-flash to pick winning candidate
        - Enforces Token Budget per mission to prevent quota exhaustion
        - Never escalates to expensive/paid Opus models
        """
        # Check mission token budget
        if run_id and run_id in self.mission_token_budgets:
            used = self.mission_tokens_tracker.get(run_id, 0)
            budget = self.mission_token_budgets[run_id]
            if used >= budget:
                raise TokenBudgetExceededError(f"Mission token budget reached ({used}/{budget} tokens). Pausing to preserve weekly quota.")

        t_start = time.time()
        
        # Build candidate model list for this role
        if model:
            candidate_models = [model]
        else:
            candidate_models = ROLE_FALLBACK_CHAINS.get(role_type, ["qwen/qwen-2.5-coder-32b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free", "speed"])

        last_error = None
        for candidate in candidate_models:
            try:
                if candidate == "speed":
                    content, tokens = self._call_gateway("speed", messages, temperature, max_tokens, response_format)
                elif "/" in candidate:
                    content, tokens = self._call_openrouter(candidate, messages, temperature, max_tokens, response_format=response_format)
                else:
                    content, tokens = self._call_gateway(candidate, messages, temperature, max_tokens, response_format)

                if content:
                    self.last_model_used = candidate
                    self.last_latency = round(time.time() - t_start, 3)
                    self.last_tokens_used = tokens
                    if run_id:
                        self.mission_tokens_tracker[run_id] = self.mission_tokens_tracker.get(run_id, 0) + tokens
                        if run_id not in self.models_used_per_run:
                            self.models_used_per_run[run_id] = []
                        if candidate not in self.models_used_per_run[run_id]:
                            self.models_used_per_run[run_id].append(candidate)
                        try:
                            from .db import update_run_token_usage
                            update_run_token_usage(run_id, tokens)
                        except Exception:
                            pass
                    return content
            except Exception as e:
                last_error = e
                print(f"[ModelRouter] Candidate '{candidate}' failed for role '{role_type}': {e}. Cascading to next candidate...")
                continue

        raise RuntimeError(f"All candidates in fallback chain {candidate_models} failed for role '{role_type}'. Last error: {last_error}")

    def _estimate_tokens(self, text: str) -> int:
        """Estimates token count handling both ASCII code and CJK/Thai characters."""
        if not text:
            return 0
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        non_ascii_chars = len(text) - ascii_chars
        return (ascii_chars // 4) + (non_ascii_chars // 2) + 1

    def _call_openrouter(
        self,
        model_slug: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, str]] = None
    ) -> Tuple[Optional[str], int]:
        """Calls OpenRouter rotating across healthy keys with cooldown tracking and retry."""
        payload: Dict[str, Any] = {
            "model": model_slug,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if response_format:
            payload["response_format"] = response_format

        all_keys = get_openrouter_keys()
        if not all_keys:
            print("[ModelRouter] ⚠️ No OpenRouter API keys available in environment.")
            return None, 0

        # Sort keys: healthy keys first, cooldown keys last
        now = time.time()
        sorted_keys = sorted(all_keys, key=lambda k: self.key_cooldowns.get(k[-8:], 0.0))

        for key in sorted_keys:
            k_tag = key[-8:]
            cooldown_until = self.key_cooldowns.get(k_tag, 0.0)
            if cooldown_until > now:
                # Key is currently in rate-limit cooldown
                continue

            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://antigravity.cloud",
                "X-Title": "Antigravity Cloud IDE"
            }
            try:
                timeout_config = httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0)
                with httpx.Client(timeout=timeout_config) as client:
                    resp = client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        choices = data.get("choices", [])
                        if not choices:
                            continue
                        msg_obj = choices[0].get("message", {})
                        content = msg_obj.get("content") or msg_obj.get("reasoning") or ""
                        usage = data.get("usage", {})
                        total_tok = usage.get("total_tokens", 0)
                        if total_tok == 0:
                            total_tok = self._estimate_tokens(json.dumps(messages)) + self._estimate_tokens(content)
                        return content, total_tok
                    elif resp.status_code == 429:
                        print(f"[ModelRouter] ⏳ Key ...{k_tag} hit rate limit (429). Setting 60s cooldown.")
                        self.key_cooldowns[k_tag] = time.time() + 60.0
                        continue
                    elif resp.status_code in (401, 402):
                        print(f"[ModelRouter] ⛔ Key ...{k_tag} auth/credit failure ({resp.status_code}). Setting 300s cooldown.")
                        self.key_cooldowns[k_tag] = time.time() + 300.0
                        continue
                    elif resp.status_code in (400, 404):
                        print(f"[ModelRouter] OpenRouter HTTP {resp.status_code} ({model_slug}): {resp.text[:200]}")
                        # Model slug or request error; skip to next candidate model
                        break
                    else:
                        print(f"[ModelRouter] OpenRouter HTTP {resp.status_code}: {resp.text[:200]}")
            except Exception as ex:
                pass # print(f"[ModelRouter] Exception calling OpenRouter with key ...{k_tag}: {ex}")
                continue

        return None, 0


    def _call_gateway(
        self,
        model_name: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict[str, str]]
    ) -> Tuple[Optional[str], int]:
        """Calls local AI Gateway (Groq LPU speed)."""
        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            with httpx.Client(timeout=40.0) as client:
                resp = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        usage = data.get("usage", {})
                        total_tok = usage.get("total_tokens", self._estimate_tokens(json.dumps(messages)) + self._estimate_tokens(content))
                        return content, total_tok
        except Exception as ex:
            print(f"[ModelRouter] AI Gateway error: {ex}")
        return None, 0

    def parse_json(self, content: str) -> Union[Dict[str, Any], List[Any]]:
        """Safely extract and parse JSON from markdown code blocks or raw text."""
        cleaned = content.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()
        
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1:
                return json.loads(cleaned[start:end+1])
            start_arr = cleaned.find("[")
            end_arr = cleaned.rfind("]")
            if start_arr != -1 and end_arr != -1:
                return json.loads(cleaned[start_arr:end_arr+1])
            raise

import streamlit as st
import os
import time
import json
import html
from datetime import datetime

# Configure page
st.set_page_config(
    page_title="Antigravity Cloud IDE - Autonomous AI Pair Programmer",
    page_icon="🌌",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Cyberpunk / Modern Dark Styling
st.markdown("""
<style>
    .main { background-color: #0b0f19; color: #e2e8f0; }
    .stTabs [data-baseweb="tab-list"] { gap: 12px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #1e293b;
        border-radius: 8px 8px 0px 0px;
        padding: 8px 18px;
        color: #94a3b8;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background-color: #3b82f6 !important;
        color: #ffffff !important;
    }
    .metric-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 14px;
        margin-bottom: 12px;
    }
    .agent-active {
        border-left: 4px solid #10b981;
    }
    .agent-idle {
        border-left: 4px solid #64748b;
    }
    .loop-step-active {
        background-color: #1e3a8a;
        color: #60a5fa;
        font-weight: bold;
        border-radius: 6px;
        padding: 4px 8px;
        display: inline-block;
    }
    .loop-step-done {
        background-color: #064e3b;
        color: #34d399;
        border-radius: 6px;
        padding: 4px 8px;
        display: inline-block;
    }
    .loop-step-idle {
        background-color: #1e293b;
        color: #94a3b8;
        border-radius: 6px;
        padding: 4px 8px;
        display: inline-block;
    }
    .badge-auto {
        background-color: #7c3aed;
        color: white;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: bold;
    }
    .badge-core {
        background-color: #0284c7;
        color: white;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# Import Core Modules
import html
import re
from typing import Tuple, List, Dict, Any, Optional

from core.db import (
    init_db, get_latest_run, get_run, list_runs,
    get_plan_steps, get_steps_for_run, get_artifacts_for_run,
    get_memories, get_skills, add_skill, get_checkpoints_for_run,
    answer_guidance, resolve_human_review, get_tool_audit_logs,
    get_fleet_metrics, get_needs_human_review_runs,
    get_subagents, register_subagent, update_subagent_status,
    delete_subagent, get_artifact_by_id, update_artifact_status
)
from core.orchestrator import AutonomousOrchestrator
from core.tools import ToolExecutor

# --- Visual Side-by-Side Diff & Code Lens Engine ---
def get_diff_stats(diff_text: str) -> Tuple[int, int]:
    additions = sum(1 for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff_text.splitlines() if line.startswith("-") and not line.startswith("---"))
    return additions, deletions

def render_side_by_side_diff_html(diff_text: str) -> str:
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

# Initialize SQLite Database & Orchestrator Singleton (Cached to prevent repetitive ALTER TABLE)
@st.cache_resource
def get_fleet_singletons():
    init_db()
    return AutonomousOrchestrator(), ToolExecutor()

orchestrator, tools = get_fleet_singletons()

from core.config import AUTH_TOKEN
import hmac
query_token = st.query_params.get("token")
if query_token and hmac.compare_digest(query_token.strip(), AUTH_TOKEN):
    st.session_state["authenticated"] = True
    # We won't delete it immediately so Streamlit doesn't refresh instantly on mobile, breaking ngrok.


# --- Security & Authentication Gate ---
from core.config import AUTH_TOKEN, WORKSPACE_DIR
from core.router import get_openrouter_keys
import hmac

# Check if authenticated via URL param


if not st.session_state.get("authenticated", False):
    st.markdown("""
    <div style="max-width: 480px; margin: 50px auto 20px auto; padding: 25px; background-color: #0f172a; border-radius: 12px; border: 1px solid #334155; text-align: center;">
        <h2 style="color: #38bdf8; margin-bottom: 5px;">🌌 Google Antigravity Cloud</h2>
        <p style="color: #94a3b8; font-size: 0.85rem;">Autonomous Fleet Control Plane • Restricted Access</p>
    </div>
    """, unsafe_allow_html=True)
    
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        with st.form("auth_form"):
            token_input = st.text_input("Enter Admin Access Token:", type="password", placeholder="Access key...")
            sub = st.form_submit_button("🔓 Authenticate & Enter Fleet", type="primary")
            if sub:
                if hmac.compare_digest(token_input.strip(), AUTH_TOKEN):
                    st.session_state["authenticated"] = True
                    try:
                        del st.query_params["token"]
                    except Exception:
                        pass
                    st.success("Authenticated successfully!")
                    st.rerun()
                else:
                    st.error("Invalid access token. Access denied.")
    st.stop()





# ==============================================================================
# GROK-LIKE UI V3 (OpenBot/Rakazo Clone)
# ==============================================================================
import time
from datetime import datetime

# --- CUSTOM CSS (Grok Theme) ---
st.markdown("""
<style>
    /* Reset and hide Streamlit Chrome */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Colors and Background */
    .stApp {
        background-color: #0a0a0b;
        color: #e2e8f0;
        font-family: 'Inter', 'Segoe UI', sans-serif;
    }
    
    /* Center Column Max Width */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 6rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        max-width: 1400px; /* To allow Left+Center+Right */
    }
    
    /* Sidebar Styling (Left Panel) */
    [data-testid="stSidebar"] {
        background-color: #141416 !important;
        border-right: 1px solid rgba(255,255,255,0.08);
        width: 280px !important;
    }
    
    /* Chat Bubbles */
    .stChatMessage { 
        background-color: transparent !important; 
        border: none !important;
    }
    .stChatMessage[data-testid="chat-message-user"] {
        background-color: #1c1c1f !important;
        border-radius: 18px;
        padding: 1rem;
        margin-left: auto;
        margin-bottom: 1rem;
        border: 1px solid rgba(255,255,255,0.05);
    }
    .stChatMessage[data-testid="chat-message-assistant"] {
        padding: 0;
        margin-bottom: 1rem;
    }
    
    /* Tool Cards */
    .tool-card {
        background-color: #101012;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 8px;
        padding: 12px;
        margin-top: 8px;
        font-family: 'ui-monospace', monospace;
        font-size: 0.85rem;
    }
    .tool-header {
        color: #8b5cf6; /* Purple dot working */
        font-weight: 600;
        margin-bottom: 8px;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .tool-card pre {
        background-color: #0a0a0b;
        padding: 8px;
        border-radius: 4px;
        border: 1px solid rgba(255,255,255,0.05);
        color: #a1a1aa;
        overflow-x: auto;
    }
    
    /* Error Details */
    .error-card {
        background-color: #271212;
        border: 1px solid #7f1d1d;
        border-radius: 8px;
        padding: 12px;
        margin-top: 8px;
    }
</style>
""", unsafe_allow_html=True)

# 1. State Management
if "selected_history" not in st.session_state:
    st.session_state.selected_history = None

# Auto-fail stuck missions (now protected by ensure_schema)
cleanup_stuck_runs()

available_runs = list_runs(limit=30, include_tests=False)
active_run_id = orchestrator.active_run_id

# 2. LEFT PANEL (Sidebar)
with st.sidebar:
    st.markdown("<h2 style='font-size: 1.2rem; font-weight: 600; margin-bottom: 20px;'>Antigravity</h2>", unsafe_allow_html=True)
    
    if st.button("➕ New Chat", use_container_width=True):
        st.session_state.selected_history = None
        if orchestrator.is_running:
            orchestrator.stop()
        st.rerun()
        
    st.markdown("---")
    if available_runs:
        for r in available_runs:
            status = r['status']
            if status == 'running':
                dot = "🟡"
            elif status == 'completed':
                dot = "🟢"
            else:
                dot = "🔴"
                
            btn_label = f"{dot} {r['goal'][:20]}..."
            btn_type = "primary" if r['run_id'] == st.session_state.selected_history else "secondary"
            if st.button(btn_label, key=f"hist_{r['run_id']}", use_container_width=True, type=btn_type):
                st.session_state.selected_history = r['run_id']
                st.rerun()

# Determine which run to display
display_run_id = st.session_state.selected_history if st.session_state.selected_history else active_run_id

# 3. TOP BAR
if display_run_id:
    r_info = get_run(display_run_id)
    if r_info:
        col_t1, col_t2 = st.columns([3, 1])
        with col_t1:
            st.markdown(f"<span style='color:#a1a1aa; font-size:0.9rem;'>{r_info['goal']}</span>", unsafe_allow_html=True)
        with col_t2:
            if r_info['status'] == 'running':
                st.markdown(f"<div style='text-align:right; font-size:0.9rem;'><span style='color:#a855f7;'>●</span> Step {r_info['current_step']}/{r_info['max_steps']}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div style='text-align:right; font-size:0.9rem;'>{r_info['status']} | Final Step {r_info['current_step']}/{r_info['max_steps']}</div>", unsafe_allow_html=True)
st.markdown("<hr style='margin-top:5px; margin-bottom:20px; border-color:rgba(255,255,255,0.08);'>", unsafe_allow_html=True)

# 4. MAIN LAYOUT (Center + Right Preview)
main_col, preview_col = st.columns([2, 1])

with main_col:
    # Transcript
    if display_run_id:
        r_info = get_run(display_run_id)
        if r_info:
            # User Message
            with st.chat_message("user"):
                st.markdown(r_info['goal'])
                
            # Assistant Stream
            with st.chat_message("assistant"):
                st.markdown("<div style='color:#a1a1aa; font-size:0.75rem; font-weight:600; margin-bottom:10px;'>ANTIGRAVITY</div>", unsafe_allow_html=True)
                steps = get_steps_for_run(display_run_id)
                
                if not steps and r_info['status'] == 'failed':
                    err_msg = r_info.get('error_details', '')
                    st.markdown(f"<div class='error-card'><b>failed before first step:</b><br><pre>{err_msg}</pre></div>", unsafe_allow_html=True)
                else:
                    for s in steps:
                        # Map schema flexibly to support both new and old inserts during this transition
                        tool = s.get('tool_name', s.get('action_type', ''))
                        args = s.get('tool_args', s.get('action_payload', ''))
                        res = s.get('tool_result', s.get('observation', ''))
                        ok = s.get('ok', 0)
                        state = s.get('state', '')
                        
                        if tool == 'exception':
                            st.markdown(f"<div class='error-card'><b>Error:</b><br><pre>{res}</pre></div>", unsafe_allow_html=True)
                        elif tool:
                            # Hide workspace path
                            if "C:/Users/User/.gemini/antigravity/scratch/antigravity_bot/workspace" in str(args):
                                args = str(args).replace("C:/Users/User/.gemini/antigravity/scratch/antigravity_bot/workspace", "workspace")
                            elif "C:\\Users\\User\\.gemini\\antigravity\\scratch\\antigravity_bot\\workspace" in str(args):
                                args = str(args).replace("C:\\Users\\User\\.gemini\\antigravity\\scratch\\antigravity_bot\\workspace", "workspace")
                                
                            status_mark = "✅" if (ok == 1 or state == 'completed') else "❌"
                            st.markdown(f"<div class='tool-card'><div class='tool-header'>● {tool}</div><div style='color:#a1a1aa;'>args={args}</div></div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='text-align:center; color:#52525b; margin-top:100px;'><h2>How can I help you?</h2></div>", unsafe_allow_html=True)

with preview_col:
    # Right panel for tool previews
    if display_run_id:
        steps = get_steps_for_run(display_run_id)
        if steps:
            st.markdown("<div style='color:#a1a1aa; font-size:0.8rem; font-weight:600; margin-bottom:10px;'>COMPUTER PREVIEW</div>", unsafe_allow_html=True)
            for s in steps:
                tool = s.get('tool_name', s.get('action_type', ''))
                res = s.get('tool_result', s.get('observation', ''))
                
                if tool and tool != 'exception' and res:
                    lines = str(res).split('\n')
                    if len(lines) > 80:
                        res = '\n'.join(lines[:80]) + "\n... [truncated]"
                    
                    with st.expander(f"Output: {tool}", expanded=True):
                        st.markdown(f"<pre style='font-size:0.75rem; background:#0a0a0b;'>{res}</pre>", unsafe_allow_html=True)

# 5. BOTTOM COMPOSER
# Streamlit chat_input is always pinned to bottom natively.
placeholder = "Message Antigravity"
if orchestrator.is_running:
    placeholder = "Mission in progress..."

prompt = st.chat_input(placeholder)

if prompt:
    st.session_state.selected_history = None
    if orchestrator.is_running:
        orchestrator.intervene(prompt)
    else:
        run_id = orchestrator.start_goal(prompt, "Complete task", max_steps=15)
    st.rerun()

# Auto-refresh if running
if orchestrator.is_running:
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=2000, key="grok_refresh")
    except:
        time.sleep(2)
        st.rerun()

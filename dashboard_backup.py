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

# --- Security & Authentication Gate ---
from core.config import AUTH_TOKEN, WORKSPACE_DIR
from core.router import get_openrouter_keys
import hmac

# Check if authenticated via URL param
query_token = st.query_params.get("token")
if query_token and hmac.compare_digest(query_token.strip(), AUTH_TOKEN):
    st.session_state["authenticated"] = True
    try:
        del st.query_params["token"]
    except Exception:
        pass
    st.rerun()

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


# Header Section
col_head1, col_head2 = st.columns([3, 1])
with col_head1:
    st.title("🌌 Google Antigravity Cloud - Autonomous Fleet")
    st.caption("AI Pair-Programming Agent • DAG Parallel Execution • Checkpoint Rollback • Auto-Skill Synthesis")

with col_head2:
    status_text = "🟢 RUNNING" if orchestrator.is_running else ("🟡 PAUSED" if orchestrator.is_paused else "⚪ IDLE")
    active_keys_count = len(get_openrouter_keys())
    st.markdown(f"""
    <div style="background-color: #1e293b; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #334155;">
        <div style="font-size: 0.8rem; color: #94a3b8;">SYSTEM STATE</div>
        <div style="font-size: 1.1rem; font-weight: bold; color: {'#10b981' if orchestrator.is_running else '#cbd5e1'};">{status_text}</div>
        <div style="font-size: 0.75rem; color: #38bdf8;">{active_keys_count} AI Keys Configured • DAG Parallel</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# Sidebar: Controls & Active Workspace
with st.sidebar:
    st.header("⚙️ Workspace & Mission Control")
    st.info(f"📁 **Workspace:**\n`{orchestrator.workspace}`")
    
    try:
        from streamlit_autorefresh import st_autorefresh
        has_autorefresh = True
    except ImportError:
        has_autorefresh = False

    # Auto-refresh checkbox (Non-blocking via st_autorefresh)
    auto_refresh = st.checkbox("🔄 Live Realtime Auto-refresh (3s)", value=orchestrator.is_running, key="auto_refresh_toggle")
    if auto_refresh:
        if has_autorefresh:
            st_autorefresh(interval=3000, key="antigravity_auto_refresh")
        else:
            time.sleep(3)
            st.rerun()

    if st.button("🔒 Lock & Log Out", use_container_width=True):
        st.session_state["authenticated"] = False
        st.query_params.clear()
        st.rerun()

    st.subheader("💡 Goal Presets")
    preset = st.selectbox(
        "Choose a template:",
        [
            "-- Custom Goal --",
            "Refactor and Upgrade Cookie Run Bot: Add real OpenCV template matching & Auto.js standalone mobile script",
            "Audit all workspace code and eliminate all placeholders with production implementations",
            "Build JWT Authentication API in FastAPI with Pytest",
            "Build a Real-Time Markdown Blog with SQLite & Pytest",
            "Scrape HackerNews Front Page and Save to JSON & HTML"
        ]
    )

    st.markdown("---")
    st.markdown("### 🛡️ Safety & Resource Guard")
    max_steps = st.slider("Max Step Budget", min_value=3, max_value=30, value=15, help="Prevents infinite loops by bounding the maximum steps.")
    
    # Direct APK Download Button (Lazy stream)
    apk_file_path = os.path.join(orchestrator.workspace, "CookieRunBot.apk")
    if os.path.exists(apk_file_path):
        st.markdown("---")
        st.markdown("### 📱 Mobile Android APK")
        try:
            apk_size_kb = os.path.getsize(apk_file_path) // 1024
            with open(apk_file_path, "rb") as f_apk:
                st.download_button(
                    label=f"📥 Download CookieRunBot.apk ({apk_size_kb} KB)",
                    data=f_apk,
                    file_name="CookieRunBot.apk",
                    mime="application/vnd.android.package-archive",
                    use_container_width=True
                )
        except Exception:
            pass

    st.markdown("---")
    import platform
    st.caption(f"Antigravity Cloud Engine v2.5 • {platform.system()} ({platform.node()}) Autonomous")

# Autonomous Goal Control Panel
with st.container():
    st.markdown("### 🎯 Autonomous Goal Intake")
    
    default_goal = preset if preset != "-- Custom Goal --" else ""
    goal_input = st.text_area(
        "What should the Autonomous Fleet build?",
        value=default_goal,
        placeholder="e.g. เพิ่ม JWT auth ใน FastAPI โปรเจกต์นี้ แล้วเขียน pytest ให้ผ่าน 100%",
        height=70
    )
    
    criteria_input = st.text_input(
        "Success Criteria (สิ่งที่บอกว่าสำเร็จ):",
        placeholder="e.g. pytest suite ผ่านทั้งหมด, มีไฟล์ auth.py, token สร้างและถอดรหัสได้",
        value="pytest ผ่าน 100% และไม่มีข้อผิดพลาด syntax" if default_goal else ""
    )

    btn_col1, btn_col2, btn_col3, btn_col4, btn_col5 = st.columns([2, 1, 1, 1, 2])
    
    with btn_col1:
        if st.button("🚀 Start Autonomous Goal", type="primary", use_container_width=True, disabled=orchestrator.is_running):
            if not goal_input.strip():
                st.warning("กรุณาระบุ Goal ก่อนเริ่มทำงานครับ")
            else:
                run_id = orchestrator.start_goal(goal_input, criteria_input, max_steps=max_steps)
                st.success(f"เริ่มภารกิจสำเร็จ! Run ID: {run_id}")
                st.rerun()

    with btn_col2:
        if st.button("⏸️ Pause", use_container_width=True, disabled=not orchestrator.is_running or orchestrator.is_paused):
            orchestrator.pause()
            st.info("หยุดชั่วคราวแล้ว")
            st.rerun()

    with btn_col3:
        if st.button("▶️ Resume", use_container_width=True, disabled=not orchestrator.is_paused):
            orchestrator.resume()
            st.success("ทำงานต่อแล้ว")
            st.rerun()

    with btn_col4:
        if st.button("🛑 Stop", use_container_width=True, disabled=not orchestrator.is_running):
            orchestrator.stop()
            st.error("ยุติการทำงานแล้ว")
            st.rerun()

    with btn_col5:
        with st.popover("⚡ Human Guidance"):
            intervene_note = st.text_input("สั่งการ/ชี้แนะด่วนระหว่างบอทรัน:")
            if st.button("ส่งคำสั่งชี้แนะ"):
                if intervene_note.strip():
                    orchestrator.intervene(intervene_note)
                    st.success("บันทึกคำสั่งชี้แนะแล้ว บอทจะนำไปปรับปรุงใน step ถัดไป")

# Fetch available missions for selection
available_runs = list_runs(limit=30, include_tests=False)
run_map = {r["run_id"]: r for r in available_runs}

default_run_id = None
if orchestrator.active_run_id and orchestrator.is_running:
    default_run_id = orchestrator.active_run_id
elif "current_selected_run" in st.session_state and st.session_state["current_selected_run"] in run_map:
    default_run_id = st.session_state["current_selected_run"]
elif available_runs:
    default_run_id = available_runs[0]["run_id"]

if available_runs:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🎯 Mission Inspector")
    run_format = lambda r_id: f"{'🟢' if run_map[r_id]['status']=='completed' else ('🔴' if 'fail' in run_map[r_id]['status'] or 'review' in run_map[r_id]['status'] else '🟡')} {r_id[:16]} • {run_map[r_id]['goal'][:30]}..."
    selected_run_id = st.sidebar.selectbox(
        "Active / Inspected Mission:",
        options=list(run_map.keys()),
        index=list(run_map.keys()).index(default_run_id) if default_run_id in run_map else 0,
        format_func=run_format
    )
    st.session_state["current_selected_run"] = selected_run_id
    active_run = run_map[selected_run_id]
else:
    active_run = None

run_id = active_run["run_id"] if active_run else None

# --- lnwjud Pillar 7: Actionable Human-in-the-Loop Review Queue ---
human_queue = get_needs_human_review_runs()
if human_queue:
    st.error(f"🚨 **Human-Review Queue Active ({len(human_queue)} mission(s) pending operator decision)**")
    for hq in human_queue:
        with st.container(border=True):
            st.markdown(f"### 🛑 Mission Escalation: `{hq['run_id']}`")
            st.markdown(f"**Goal:** {hq['goal']}")
            st.markdown(f"**Root Failure Analysis:** `{hq.get('human_review_reason', 'Node step budget (2 retries) reached without progress')}`")
            st.caption(f"Status: `{hq['status']}` • Steps: {hq['current_step']}/{hq['max_steps']} • Escalated at: {hq['updated_at']}")

            act_col1, act_col2, act_col3, act_col4, act_col5 = st.columns([1.2, 1.2, 2.0, 1.2, 1.0])
            with act_col1:
                if st.button("✅ Approve & Proceed", key=f"app_{hq['run_id']}", use_container_width=True):
                    resolve_human_review(hq['run_id'], "approve", "Approved by human operator")
                    orchestrator.resume_goal(hq['run_id'])
                    st.success("Mission approved and resumed!")
                    st.rerun()
            with act_col2:
                if st.button("🔄 Replan Scope", key=f"rep_{hq['run_id']}", use_container_width=True):
                    resolve_human_review(hq['run_id'], "replan", "Operator requested scope replan")
                    orchestrator.resume_goal(hq['run_id'])
                    st.info("Replan initiated!")
                    st.rerun()
            with act_col3:
                guidance_txt = st.text_input("Operator Guidance:", key=f"guid_{hq['run_id']}", placeholder="e.g. Use mock template / bypass check...")
                if st.button("💡 Resume with Guidance", key=f"send_guid_{hq['run_id']}", use_container_width=True):
                    if guidance_txt.strip():
                        orchestrator.intervene(guidance_txt)
                        resolve_human_review(hq['run_id'], "approve", f"Guidance: {guidance_txt}")
                        orchestrator.resume_goal(hq['run_id'])
                        st.success("Guidance injected and mission resumed!")
                        st.rerun()
            with act_col4:
                if st.button("🏁 Take Over / Done", key=f"done_{hq['run_id']}", use_container_width=True):
                    resolve_human_review(hq['run_id'], "takeover", "Completed manually by operator")
                    st.success("Mission marked completed via manual takeover!")
                    st.rerun()
            with act_col5:
                if st.button("🛑 Abort", key=f"abort_{hq['run_id']}", use_container_width=True):
                    resolve_human_review(hq['run_id'], "abort", "Aborted by human operator")
                    st.warning("Mission aborted and state preserved.")
                    st.rerun()

# --- Closed-Loop Fleet Evaluation Metrics ---
fleet_metrics = get_fleet_metrics()
met_c1, met_c2, met_c3, met_c4, met_c5 = st.columns(5)
with met_c1:
    st.metric("🏆 Completed Missions", fleet_metrics.get("completed_runs", 0))
with met_c2:
    st.metric("🚨 Human Escalations", fleet_metrics.get("human_review_runs", 0))
with met_c3:
    st.metric("🎯 Avg Pass Rate", f"{fleet_metrics.get('avg_criteria_pass_rate', 100.0)}%")
with met_c4:
    st.metric("🛡️ Critic Rescues", fleet_metrics.get("total_rescues", 0))
with met_c5:
    wins = fleet_metrics.get("candidate_wins", {})
    win_str = " / ".join([f"{k.split('/')[-1]}:{v}" for k, v in wins.items()]) or "Equal"
    st.metric("⚔️ Coder Wins", win_str)

if active_run:
    t_used = active_run.get('tokens_used', 0)
    t_budget = active_run.get('token_budget', 50000)
    st.caption(f"📊 **Mission Token Usage:** {t_used:,} / {t_budget:,} tokens (Weekly quota guard) • State: `{active_run.get('status', 'idle')}`")

st.markdown("<br>", unsafe_allow_html=True)

# Main Tabs
tab_manager, tab_artifacts, tab_memory, tab_sandbox, tab_history = st.tabs([
    "🛰️ Manager View & DAG Loop",
    "📦 Alive Artifacts & ADR",
    "🧠 Memory & Skill Bank",
    "🛠️ Direct Terminal & Files",
    "📜 Mission History & Checkpoints"
])

# ==============================================================================
# TAB 1: MANAGER VIEW & DAG PARALLEL LOOP
# ==============================================================================
with tab_manager:
    # 1. Multi-Agent Fleet Status with Live Dynamic Indicators
    st.subheader("👥 Active Multi-Agent Fleet (Live Concurrency)")
    f_col0, f_col1, f_col2, f_col3, f_col4, f_col5 = st.columns(6)
    
    ag = orchestrator.active_agents

    with f_col0:
        mg_active = ag.get("manager", "idle") != "idle"
        st.markdown(f"""
        <div class="metric-card {'agent-active' if mg_active else 'agent-idle'}">
            <div style="font-size: 1.2rem;">👑 <b>Manager</b></div>
            <div style="font-size: 0.8rem; color: #94a3b8;">Autonomous Executive</div>
            <div style="color: {'#10b981' if mg_active else '#64748b'}; font-weight: bold; font-size: 0.85rem;">
                {ag.get('manager', '○ Idle')}
            </div>
            <div style="font-size: 0.7rem; color: #38bdf8;">DAG & Swarm Director</div>
        </div>
        """, unsafe_allow_html=True)
    
    with f_col1:
        pl_active = ag.get("planner", "idle") != "idle"
        st.markdown(f"""
        <div class="metric-card {'agent-active' if pl_active else 'agent-idle'}">
            <div style="font-size: 1.2rem;">🧠 <b>Planner</b></div>
            <div style="font-size: 0.8rem; color: #94a3b8;">DAG Architect</div>
            <div style="color: {'#10b981' if pl_active else '#64748b'}; font-weight: bold; font-size: 0.85rem;">
                {ag.get('planner', '○ Idle')}
            </div>
            <div style="font-size: 0.7rem; color: #38bdf8;">Moonshot Kimi K2.6</div>
        </div>
        """, unsafe_allow_html=True)

    with f_col2:
        cd_active = ag.get("coder", "idle") != "idle"
        st.markdown(f"""
        <div class="metric-card {'agent-active' if cd_active else 'agent-idle'}">
            <div style="font-size: 1.2rem;">💻 <b>Coder Swarm</b></div>
            <div style="font-size: 0.8rem; color: #94a3b8;">Primary & 429 Backup</div>
            <div style="color: {'#10b981' if cd_active else '#64748b'}; font-weight: bold; font-size: 0.85rem;">
                {ag.get('coder', '○ Idle')}
            </div>
            <div style="font-size: 0.7rem; color: #38bdf8;">DeepSeek / Qwen3-Coder</div>
        </div>
        """, unsafe_allow_html=True)

    with f_col3:
        ts_active = ag.get("tester", "idle") != "idle"
        st.markdown(f"""
        <div class="metric-card {'agent-active' if ts_active else 'agent-idle'}">
            <div style="font-size: 1.2rem;">🧪 <b>Tester</b></div>
            <div style="font-size: 0.8rem; color: #94a3b8;">Pytest & WatchPoint Check</div>
            <div style="color: {'#10b981' if ts_active else '#64748b'}; font-weight: bold; font-size: 0.85rem;">
                {ag.get('tester', '○ Idle')}
            </div>
            <div style="font-size: 0.7rem; color: #38bdf8;">Strict Boundary Validator</div>
        </div>
        """, unsafe_allow_html=True)

    with f_col4:
        rf_active = ag.get("reflector", "idle") != "idle"
        st.markdown(f"""
        <div class="metric-card {'agent-active' if rf_active else 'agent-idle'}">
            <div style="font-size: 1.2rem;">🛡️ <b>Dual Critic</b></div>
            <div style="font-size: 0.8rem; color: #94a3b8;">Consensus & WatchPoints</div>
            <div style="color: {'#10b981' if rf_active else '#64748b'}; font-weight: bold; font-size: 0.85rem;">
                {ag.get('reflector', '○ Idle')}
            </div>
            <div style="font-size: 0.7rem; color: #38bdf8;">GLM-5.3 & Qwen3-Coder</div>
        </div>
        """, unsafe_allow_html=True)

    with f_col5:
        rs_active = ag.get("researcher", "idle") != "idle"
        st.markdown(f"""
        <div class="metric-card {'agent-active' if rs_active else 'agent-idle'}">
            <div style="font-size: 1.2rem;">⚖️ <b>Judge / Web</b></div>
            <div style="font-size: 0.8rem; color: #94a3b8;">Cross-Model Judge & Capture</div>
            <div style="color: {'#10b981' if rs_active else '#64748b'}; font-weight: bold; font-size: 0.85rem;">
                {ag.get('researcher', '○ Standby')}
            </div>
            <div style="font-size: 0.7rem; color: #38bdf8;">GLM-5.3 Candidate Judge</div>
        </div>
        """, unsafe_allow_html=True)

    # Dynamic & Specialized Subagent Fleet (Google Antigravity On-the-Fly Spawning)
    subagents_list = get_subagents()
    if subagents_list:
        st.markdown("<div style='margin-top: 10px; margin-bottom: 6px; font-weight: 600; color: #cbd5e1;'>⚡ Specialized Subagents (Spawned On-the-Fly)</div>", unsafe_allow_html=True)
        n_cols = min(5, len(subagents_list))
        sa_cols = st.columns(n_cols)
        for idx, sa in enumerate(subagents_list):
            with sa_cols[idx % n_cols]:
                sa_role = sa["role_name"]
                sa_status = ag.get(sa_role, sa.get("status", "idle"))
                is_sa_act = sa_status != "idle" and not sa_status.startswith("○")
                model_short = sa.get("assigned_model", "qwen3-coder").split("/")[-1]
                st.markdown(f"""
                <div class="metric-card {'agent-active' if is_sa_act else 'agent-idle'}" style="padding: 10px; margin-bottom: 8px;">
                    <div style="font-size: 0.95rem;">🤖 <b>{sa['role_title']}</b></div>
                    <div style="font-size: 0.72rem; color: #a855f7;"><code>{sa_role}</code> • Done: {sa.get('task_count', 0)}</div>
                    <div style="color: {'#10b981' if is_sa_act else '#64748b'}; font-weight: bold; font-size: 0.78rem; margin: 3px 0;">
                        {sa_status}
                    </div>
                    <div style="font-size: 0.68rem; color: #38bdf8;">Model: {model_short}</div>
                </div>
                """, unsafe_allow_html=True)

    with st.popover("🚀 Spawn Specialized Subagent On-The-Fly"):
        st.markdown("#### Define and Launch a Dynamic Subagent")
        preset_sub = st.selectbox(
            "Select Archetype or Custom:",
            [
                "Security Auditor (OWASP, Bounds & Injection)",
                "DB Migrator (SQLite Schema & ACID)",
                "Performance Profiler (Latency & Concurrency)",
                "Mobile Architect (Android Auto.js / ADB)",
                "API Doc Synthesizer (Specs & ADR)",
                "-- Custom Dynamic Subagent --"
            ],
            key="spawn_preset_sel"
        )
        if preset_sub.startswith("Security"):
            p_name = "security_auditor"
            p_title = "Security & Vulnerability Auditor"
            p_model = "qwen/qwen3-coder:free"
        elif preset_sub.startswith("DB"):
            p_name = "db_migrator"
            p_title = "Database & Schema Migration Specialist"
            p_model = "qwen/qwen3-coder:free"
        elif preset_sub.startswith("Perf"):
            p_name = "perf_profiler"
            p_title = "Performance & Concurrency Profiler"
            p_model = "z-ai/glm-5.3-flash:free"
        elif preset_sub.startswith("Mobile"):
            p_name = "mobile_architect"
            p_title = "Android & Mobile Automation Specialist"
            p_model = "deepseek/deepseek-chat:free"
        elif preset_sub.startswith("API"):
            p_name = "doc_synthesizer"
            p_title = "API & Architectural Documentation Specialist"
            p_model = "deepseek/deepseek-chat:free"
        else:
            p_name = ""
            p_title = ""
            p_model = "qwen/qwen3-coder:free"

        sub_name_in = st.text_input("Subagent Role Name (snake_case):", value=p_name, key="sp_name_in")
        sub_title_in = st.text_input("Display Title:", value=p_title, key="sp_title_in")
        sub_prompt_in = st.text_area("Specialized System Instructions:", placeholder="System prompt detailing role expertise...", key="sp_prompt_in")
        sub_model_in = st.selectbox(
            "Assigned Free-Tier Model:",
            ["qwen/qwen3-coder:free", "deepseek/deepseek-chat:free", "z-ai/glm-5.3-flash:free", "moonshotai/kimi-k2.6:free"],
            index=0,
            key="sp_model_sel"
        )

        if st.button("✨ Spawn Subagent", type="primary", key="btn_do_spawn"):
            if sub_name_in.strip():
                spawned = orchestrator.spawn_subagent(
                    role_name=sub_name_in,
                    role_title=sub_title_in,
                    system_prompt=sub_prompt_in,
                    assigned_model=sub_model_in
                )
                st.success(f"Subagent '{spawned['role_title']}' spawned and active in fleet!")
                st.rerun()
            else:
                st.error("Please enter a valid role name.")

    # 2. 100% Free Dual-Critic 5-Phase State Machine
    st.subheader("🔄 100% Free Dual-Critic Multi-Agent State Machine")
    st.markdown("""
    <div style="display: flex; gap: 6px; align-items: center; justify-content: space-between; background: #1e293b; padding: 12px; border-radius: 8px; border: 1px solid #334155; margin-bottom: 20px; font-size: 0.78rem;">
        <span class="loop-step-done">Phase 0: Intake & Token Budget (DeepSeek)</span> ➔
        <span class="loop-step-done">Phase 1: DAG Plan (Kimi K2.6)</span> ➔
        <span class="loop-step-active">Phase 1.5: Dual-Critic Audit (GLM-5.3 & Qwen3)</span> ➔
        <span class="loop-step-active">Phase 2: Swarm & Candidate Competition</span> ➔
        <span class="loop-step-done">Phase 3: Verification & HR Queue</span> ➔
        <span class="loop-step-done">Phase 4: Verified-Hard Skill Bank</span>
    </div>
    """, unsafe_allow_html=True)

    # 3. Live Execution Step Timeline
    st.subheader("⏱️ Live Execution Timeline (Thought ➔ Action ➔ Observation ➔ Reflection)")
    if run_id:
        steps_history = get_steps_for_run(run_id)
        if not steps_history:
            st.info("กำลังรอผลลัพธ์ขั้นตอนแรก หรือเตรียมการวางแผน...")
        else:
            for s in reversed(steps_history):
                step_icon = "✅" if s["state"] == "completed" else ("❌" if s["state"] in ("failed", "error") else "🔄")
                with st.expander(f"{step_icon} Step {s['step_index']}: [{s['agent_role'].upper()}] - {s['thought'][:60]}... ({s['duration_sec']}s)", expanded=False):
                    c_act, c_ref = st.columns(2)
                    with c_act:
                        st.markdown(f"**⚡ Action Taken ({s['action_type']}):**")
                        st.code(s['action_payload'] or "No action payload", language="bash")
                        st.markdown("**👁️ Observation (Tool Output):**")
                        st.text_area("Stdout/Stderr", value=s['observation'] or "No observation", height=120, disabled=True, key=f"obs_{s['id']}")
                    with c_ref:
                        st.markdown("**🪞 Self-Reflection & Critique:**")
                        st.info(s['reflection'] or "No reflection recorded.")
                        st.caption(f"Recorded at: {s['created_at']}")
    else:
        st.write("ยังไม่มีภารกิจที่รันอยู่ กรุณาระบุ Goal แล้วกด 'Start Autonomous Goal'")

# ==============================================================================
# TAB 2: ARTIFACTS PANEL (ALIVE ARTIFACTS, ADR, & DIFFS)
# ==============================================================================
with tab_artifacts:
    st.subheader("📦 Mission Artifacts & Architectural Decisions")
    if not run_id:
        st.info("ยังไม่มีข้อมูล Artifacts")
    else:
        art_subtab1, art_subtab2, art_subtab3, art_subtab4, art_subtab5, art_subtab6, art_subtab7 = st.tabs([
            "📋 DAG Task Checklist & Graph",
            "⚖️ Architectural Decisions (ADR)",
            "🧪 Structured Test Reports",
            "📝 File Diffs",
            "💻 Live Terminal Logs",
            "🖼️ Browser Captures",
            "📱 Mobile APK"
        ])

        # Subtab 1: DAG Task Checklist & Graph
        with art_subtab1:
            plan_items = get_plan_steps(run_id)
            if plan_items:
                total = len(plan_items)
                completed_count = sum(1 for p in plan_items if p["status"] == "completed")
                st.progress(completed_count / total if total > 0 else 0)
                st.caption(f"DAG Progress: {completed_count}/{total} steps completed")

                # Live DAG Flowchart Graph (Interactive Graphviz with Mermaid Fallback)
                with st.expander("📊 Visual DAG Flowchart (Live Graph)", expanded=True):
                    dot_lines = [
                        "digraph {",
                        "  rankdir=LR;",
                        "  node [shape=box, style=filled, fontname=\"Helvetica\", fontsize=10];",
                        "  edge [color=\"#38bdf8\", arrowhead=vee];"
                    ]
                    mermaid_lines = ["```mermaid", "graph TD"]
                    for p in plan_items:
                        s_id = f"S{p['step_index']}"
                        clean_title = p['title'].replace('"', "'")[:22]
                        status = p.get("status", "pending")
                        if status == "completed":
                            fill = "#10b981"
                            fcolor = "#ffffff"
                        elif status == "in_progress":
                            fill = "#f59e0b"
                            fcolor = "#000000"
                        elif status == "failed":
                            fill = "#ef4444"
                            fcolor = "#ffffff"
                        else:
                            fill = "#1e293b"
                            fcolor = "#cbd5e1"
                        dot_lines.append(f'  {s_id} [label="Step {p["step_index"]}: {clean_title}\\n[{status.upper()}]", fillcolor="{fill}", fontcolor="{fcolor}"];')
                        mermaid_lines.append(f'    {s_id}["Step {p["step_index"]}: {clean_title} [{status.upper()}]"]')
                        deps = json.loads(p.get("depends_on") or "[]") if isinstance(p.get("depends_on"), str) else p.get("depends_on", [])
                        for d in deps:
                            dot_lines.append(f'  S{d} -> {s_id};')
                            mermaid_lines.append(f'    S{d} --> {s_id}')
                    dot_lines.append("}")
                    mermaid_lines.append("```")
                    try:
                        st.graphviz_chart("\n".join(dot_lines), use_container_width=True)
                    except Exception:
                        st.markdown("\n".join(mermaid_lines))

                for p in plan_items:
                    status = p.get("status", "pending")
                    if status == "completed":
                        icon = "✅"
                        status_badge = " `[COMPLETED]`"
                    elif status == "in_progress":
                        icon = "🔄"
                        status_badge = " ⚡ `[RUNNING]`"
                    elif status == "blocked":
                        icon = "⛔"
                        status_badge = " ⚠️ `[BLOCKED on parents]`"
                    elif status == "failed":
                        icon = "❌"
                        status_badge = " 🚨 `[FAILED]`"
                    else:
                        icon = "⬜"
                        status_badge = " `[READY]`"

                    deps_str = f"depends_on: {p.get('depends_on')}" if p.get("depends_on") else "Root Task"
                    diff = p.get('difficulty', 'normal')
                    diff_badge = "🔥 `[CRITICAL]`" if diff == "critical" else ("⚡ `[COMPLEX]`" if diff == "complex" else "`[NORMAL]`")
                    flag_badge = " 🚩 **[HIGH-CONFIDENCE FLAG]**" if p.get("is_flagged") else ""
                    watch_badge = " 👁️ **[WATCH POINT]**" if p.get("is_watch_point") else ""
                    winner_badge = f" 🏆 *Winner: {p.get('winning_model')}*" if p.get("winning_model") else ""
                    model_info = f" • *Model: {p.get('model_used')}*" if p.get("model_used") else ""

                    st.markdown(f"**{icon} Step {p['step_index']}: {p['title']}** {status_badge}{diff_badge}{flag_badge}{watch_badge}{winner_badge}{model_info}")
                    st.caption(f"{p['description']} | Agent: `{p['assigned_agent']}` | `{deps_str}`")
            else:
                st.info("ไม่มีรายการ Plan สำหรับรอบนี้")

        # Subtab 2: Architectural Decision Records (ADR)
        with art_subtab2:
            dec_artifacts = get_artifacts_for_run(run_id, "decision")
            if dec_artifacts:
                for dec in dec_artifacts:
                    with st.expander(f"📌 {dec['title']} ({dec['created_at']})", expanded=True):
                        st.markdown(dec["content"])
            else:
                st.info("ยังไม่มีบันทึกการตัดสินใจทางสถาปัตยกรรม (ADR)")

        # Subtab 3: Structured Test Reports (lnwjud & Antigravity Pillar)
        with art_subtab3:
            test_rep_artifacts = get_artifacts_for_run(run_id, "test_report")
            if test_rep_artifacts:
                for tr in test_rep_artifacts:
                    with st.expander(f"🧪 {tr['title']} ({tr['created_at']})", expanded=True):
                        st.markdown(tr["content"])
            else:
                st.info("ยังไม่มีผลการทดสอบ Structured Test Report บอทจะสร้างอัตโนมัติเมื่อรัน pytest")

        # Subtab 4: File Diffs (Visual Side-by-Side Diff Viewer & In-Editor Code Lens)
        with art_subtab4:
            diff_artifacts = get_artifacts_for_run(run_id, "diff")
            if diff_artifacts:
                for d in diff_artifacts:
                    d_id = d["id"]
                    diff_content = d.get("content", "")
                    file_path = d.get("file_path", "")
                    art_status = d.get("status", "pending")
                    adds, dels = get_diff_stats(diff_content)
                    
                    with st.container(border=True):
                        # Header with status badge and stats
                        h_col1, h_col2 = st.columns([3, 2])
                        with h_col1:
                            st.markdown(f"#### 📄 `{file_path or d['title']}`")
                            st.caption(f"Artifact #{d_id} • Step {d.get('step_index', 0)} • Recorded: {d['created_at']}")
                        with h_col2:
                            status_badge = (
                                '<span style="background-color: #065f46; color: #6ee7b7; padding: 3px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold;">✅ Accepted</span>'
                                if art_status == "accepted" else
                                ('<span style="background-color: #991b1b; color: #fecaca; padding: 3px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold;">↩️ Reverted</span>'
                                 if art_status == "reverted" else
                                 '<span style="background-color: #1e3a8a; color: #93c5fd; padding: 3px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold;">⏳ Pending Review</span>')
                            )
                            st.markdown(f"""
                            <div style="text-align: right;">
                                {status_badge}
                                <span style="background-color: #1e293b; color: #10b981; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.8rem; margin-left: 6px;">+{adds}</span>
                                <span style="background-color: #1e293b; color: #ef4444; font-weight: bold; padding: 3px 8px; border-radius: 4px; font-size: 0.8rem; margin-left: 4px;">-{dels}</span>
                            </div>
                            """, unsafe_allow_html=True)

                        # Antigravity In-Editor Code Lens Action Controls
                        ctl_col1, ctl_col2, ctl_col3 = st.columns([2, 1.2, 1.2])
                        with ctl_col1:
                            view_mode = st.radio(
                                "Diff View Mode:",
                                ["Visual Split (Side-by-Side)", "Unified Inline", "Raw Patch"],
                                horizontal=True,
                                key=f"vm_{d_id}"
                            )
                        with ctl_col2:
                            if st.button("✅ Accept Changes", key=f"acc_diff_{d_id}", type="primary", use_container_width=True, disabled=(art_status == "accepted")):
                                res = orchestrator.accept_file_diff(d_id)
                                st.success(res.get("message", "Diff accepted!"))
                                st.rerun()
                        with ctl_col3:
                            if st.button("↩️ Revert File", key=f"rev_diff_{d_id}", use_container_width=True, disabled=(art_status == "reverted")):
                                res = orchestrator.revert_file_diff(d_id)
                                if res.get("success"):
                                    st.warning(res.get("message", "File reverted!"))
                                else:
                                    st.error(res.get("error", "Revert failed!"))
                                st.rerun()

                        # Render Visual Diffs
                        if view_mode == "Visual Split (Side-by-Side)":
                            st.markdown(render_side_by_side_diff_html(diff_content), unsafe_allow_html=True)
                        elif view_mode == "Unified Inline":
                            st.markdown(render_unified_diff_html(diff_content), unsafe_allow_html=True)
                        else:
                            st.code(diff_content, language="diff")

                        # Toggle Full File Content Inspection
                        if file_path:
                            with st.expander(f"🔍 View Current File in Workspace (`{os.path.basename(file_path)}`)", expanded=False):
                                file_res = tools.read_file(file_path)
                                if file_res.get("success"):
                                    st.code(file_res.get("content", ""), line_numbers=True)
                                else:
                                    st.info(f"File not currently present on disk: {file_res.get('error')}")
            else:
                st.info("ยังไม่มี File Diff ที่ถูกสร้าง")

        # Subtab 5: Live Terminal Logs
        with art_subtab5:
            term_artifacts = get_artifacts_for_run(run_id, "terminal")
            if term_artifacts:
                for t in term_artifacts:
                    st.markdown(f"#### 📟 {t['title']}")
                    st.code(t["content"], language="bash")
            else:
                st.info("ยังไม่มี Terminal Log")

        # Subtab 6: Browser Captures
        with art_subtab6:
            img_artifacts = get_artifacts_for_run(run_id, "screenshot")
            if img_artifacts:
                for img in img_artifacts:
                    st.markdown(f"#### 🌐 {img['title']}")
                    if img.get("file_path") and os.path.exists(img["file_path"]):
                        st.image(img["file_path"], caption=img["title"], use_container_width=True)
                    else:
                        st.warning(f"File not found: {img.get('file_path')}")
            else:
                st.info("ยังไม่มีภาพ Screenshot จาก Playwright")

        # Subtab 7: Mobile APK
        with art_subtab7:
            apk_artifacts = get_artifacts_for_run(run_id, "apk")
            if apk_artifacts:
                for a in apk_artifacts:
                    st.markdown(f"### 📱 {a['title']}")
                    if a.get("file_path") and os.path.exists(a["file_path"]):
                        apk_size = os.path.getsize(a["file_path"])
                        with open(a["file_path"], "rb") as f_apk:
                            st.download_button(
                                label=f"📥 Download {os.path.basename(a['file_path'])} ({apk_size // 1024} KB)",
                                data=f_apk.read(),
                                file_name=os.path.basename(a["file_path"]),
                                mime="application/vnd.android.package-archive",
                                key=f"apk_dl_{a['id']}"
                            )
            else:
                st.info("ยังไม่มี APK Artifact ที่คอมไพล์ในรอบนี้")

# ==============================================================================
# TAB 3: MEMORY & SKILL BANK (AUTO-LEARNED & REUSABLE)
# ==============================================================================
with tab_memory:
    st.subheader("🧠 Hierarchical Memory & Auto-Synthesized Skill Bank")
    mem_col1, mem_col2 = st.columns([1, 1])

    with mem_col1:
        st.markdown("### 📚 Lessons Learned (Self-Reflection Memory)")
        memories = get_memories(category="lesson_learned", limit=20)
        if memories:
            for m in memories:
                with st.chat_message("assistant"):
                    st.markdown(f"**{m['title']}**")
                    st.write(m['content'])
                    st.caption(f"Learned at: {m['created_at']}")
        else:
            st.info("ยังไม่มีบทเรียนที่บันทึกไว้ บอทจะสร้างอัตโนมัติเมื่อแก้ข้อผิดพลาดสำเร็จ")

    with mem_col2:
        st.markdown("### 🛠️ Reusable Skill Library (Auto-Learning Enabled)")
        skills = get_skills()
        for sk in skills:
            is_auto = bool(sk.get("source_run_id"))
            is_high_val = bool(sk.get("high_value"))
            is_verified_hard = bool(sk.get("verified_hard"))
            trust_score = float(sk.get("trust_score", 1.0) or 1.0)
            is_quarantined = trust_score < 0.5
            badge_html = '<span class="badge-auto">🤖 Auto-Synthesized</span>' if is_auto else '<span class="badge-core">📦 Built-in</span>'
            if is_verified_hard:
                badge_html += ' <span style="background-color: #065f46; color: #6ee7b7; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold;">🛡️ Verified-Hard (Dual-Critic Approved)</span>'
            elif is_high_val:
                badge_html += ' <span style="background-color: #1e3a8a; color: #93c5fd; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold;">⭐ High-Value Pattern</span>'
            
            if is_quarantined:
                badge_html += ' <span style="background-color: #991b1b; color: #fecaca; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold;">⚠️ Quarantined (Trust < 0.5)</span>'
            else:
                badge_html += f' <span style="background-color: #1e293b; color: #38bdf8; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">Trust: {trust_score:.2f}</span>'
            
            safe_name = html.escape(str(sk.get('name', '')))
            safe_cat = html.escape(str(sk.get('category', '')))
            with st.expander(f"📦 {safe_name} ({safe_cat}) - Trust: {trust_score:.2f} | Used: {sk.get('usage_count', 0)} times"):
                st.markdown(badge_html, unsafe_allow_html=True)
                st.markdown(f"**Description:** {sk['description']}")
                st.markdown(f"**Instructions:**\n{sk['instructions']}")
                if sk['code_template']:
                    st.code(sk['code_template'], language="python")

        with st.popover("➕ Add New Engineering Skill"):
            sk_name = st.text_input("Skill Name (e.g. FastApi_JWT_Auth):", key="pop_sk_name")
            sk_desc = st.text_input("Description:", key="pop_sk_desc")
            sk_inst = st.text_area("Instructions:", key="pop_sk_inst")
            sk_temp = st.text_area("Code Template (optional):", key="pop_sk_temp")
            if st.button("Save Skill", key="pop_sk_btn"):
                if sk_name and sk_inst:
                    add_skill(sk_name, sk_desc, sk_inst, sk_temp)
                    st.success("บันทึกทักษะเรียบร้อยแล้ว!")
                    st.rerun()

# ==============================================================================
# TAB 4: DIRECT TERMINAL & WORKSPACE FILES
# ==============================================================================
with tab_sandbox:
    st.subheader("🛠️ Direct Terminal & Workspace Explorer")
    t_col1, t_col2 = st.columns([1, 1])

    with t_col1:
        st.markdown("#### 💻 Interactive Diagnostic Command")
        st.caption("Protected Sandbox • Validated by Security Policy & Recorded in Tool Contract Audit Trail")
        direct_cmd = st.text_input("Enter command to run in workspace:", placeholder="e.g. ls -la; pytest; git status")
        confirm_exec = st.checkbox("Confirm command execution in workspace sandbox", value=False)
        if st.button("▶️ Execute Command", disabled=not confirm_exec):
                res = tools.execute_contract_tool("run_command", {"command": direct_cmd}, actor_agent="admin_interactive")
                exit_c = res.get('exit_code', -1)
                stdout_c = res.get('stdout', '')
                stderr_c = res.get('stderr', res.get('error', ''))
                st.code(f"Exit Code: {exit_c}\n\nSTDOUT:\n{stdout_c}\n\nSTDERR:\n{stderr_c}", language="bash")


    with t_col2:
        st.markdown("#### 📁 Workspace Files")
        file_tree = tools.list_files()
        st.write(f"Total files: {len(file_tree.get('files', []))}")
        selected_file = st.selectbox("Select file to view:", ["-- Select --"] + file_tree.get("files", []))
        if selected_file and selected_file != "-- Select --":
            content_res = tools.read_file(selected_file)
            if content_res["success"]:
                st.download_button(
                    label=f"📥 Download {os.path.basename(selected_file)} to Phone/PC",
                    data=content_res["content"],
                    file_name=os.path.basename(selected_file),
                    mime="text/plain",
                    use_container_width=True
                )
                st.code(content_res["content"], language="python" if selected_file.endswith(".py") else ("javascript" if selected_file.endswith(".js") else "text"))
            else:
                st.error(content_res.get("error"))

    st.markdown("---")
    st.markdown("#### 🛡️ Tool Contract Execution Audit Trail (lnwjud Standard)")
    audit_logs = get_tool_audit_logs(limit=25)
    if audit_logs:
        audit_display = []
        for l in audit_logs:
            audit_display.append({
                "Timestamp": l.get("created_at", ""),
                "Tool": l.get("tool_name", ""),
                "Class": l.get("action_class", ""),
                "Actor": l.get("actor_agent", ""),
                "Allowed": "✅ Yes" if l.get("is_allowed") else "⛔ Blocked",
                "Duration": f"{l.get('duration_ms', 0):.1f} ms",
                "Exit": l.get("exit_code", 0),
                "Summary": l.get("result_summary", "")[:70]
            })
        st.dataframe(audit_display, use_container_width=True)
    else:
        st.info("No tool audit logs recorded yet. Tool executions will be logged here.")

# ==============================================================================
# TAB 5: MISSION HISTORY & SAFE CHECKPOINT ROLLBACK
# ==============================================================================
with tab_history:
    st.subheader("📜 Historical Checkpoints & Safe Rollback Control")
    
    h_col1, h_col2 = st.columns([1, 1])
    
    with h_col1:
        st.markdown("### ⏪ Workspace Safe Checkpoints (Active Run)")
        if run_id:
            checkpoints = get_checkpoints_for_run(run_id)
            if checkpoints:
                for chk in checkpoints:
                    with st.expander(f"📍 Step {chk['step_index']}: {chk['commit_hash'][:8]} ({chk['created_at']})"):
                        st.markdown(f"**Description:** {chk.get('description', 'Checkpoint')}")
                        st.markdown(f"**Commit Hash:** `{chk['commit_hash']}`")
                        if st.button(f"⏪ Rollback Workspace to Step {chk['step_index']}", key=f"rb_{chk['id']}"):
                            rb_res = orchestrator.rollback_to_step(run_id, chk["step_index"])
                            if rb_res["success"]:
                                st.success(f"กู้คืนโค้ดกลับไปยัง Step {chk['step_index']} สำเร็จ!")
                                st.rerun()
                            else:
                                st.error(f"Rollback failed: {rb_res.get('error')}")
            else:
                st.info("ยังไม่มี Checkpoint สำหรับรอบนี้")
        else:
            st.info("ไม่มีภารกิจที่เลือก")

    with h_col2:
        st.markdown("### 🏆 Past Completed Runs")
        past_runs = list_runs(limit=15)
        if past_runs:
            for r in past_runs:
                status_emoji = "✅" if r["status"] == "completed" else ("🔄" if r["status"] == "running" else "⏸️")
                with st.expander(f"{status_emoji} [{r['status'].upper()}] {r['goal'][:60]}..."):
                    st.markdown(f"**Run ID:** `{r['run_id']}`")
                    st.markdown(f"**Goal:** {r['goal']}")
                    st.markdown(f"**Success Criteria:** {r['success_criteria']}")
                    st.markdown(f"**Steps:** {r['current_step']}/{r['max_steps']} | **Date:** {r['created_at']}")
        else:
            st.info("ไม่มีประวัติภารกิจ")

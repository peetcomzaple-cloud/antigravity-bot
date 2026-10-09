import os
import re

dashboard_path = r"C:\Users\User\.gemini\antigravity\scratch\antigravity_bot\dashboard.py"

with open(dashboard_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find where the Header Section starts
start_idx = -1
for i, line in enumerate(lines):
    if "# Header Section" in line:
        start_idx = i
        break

if start_idx != -1:
    original_core = lines[:start_idx]
    
    # We will append the new mobile UI
    mobile_ui = """
# ==============================================================================
# GROK-LIKE MOBILE-FIRST UI (Replaced Legacy Dashboard)
# ==============================================================================

# Custom Mobile CSS
st.markdown(\"\"\"
<style>
    /* Hide headers and adjust padding for mobile */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 5rem !important;
        max-width: 800px;
    }
    
    /* Clean Expanders */
    .streamlit-expanderHeader {
        background-color: #1e293b;
        border-radius: 8px;
        color: #e2e8f0;
        font-weight: 600;
    }
    
    /* Grok-style chat */
    .stChatMessage {
        padding: 0.5rem 0;
    }
</style>
\"\"\", unsafe_allow_html=True)

# 1. State Management
if "messages" not in st.session_state:
    st.session_state.messages = []

# Fetch available runs
available_runs = list_runs(limit=30, include_tests=False)
run_map = {r["run_id"]: r for r in available_runs}
active_run_id = orchestrator.active_run_id

# 2. Sidebar (Hamburger Menu for Advanced Tools & History)
with st.sidebar:
    st.header("⚙️ Settings & History")
    st.info(f"Workspace:\\n`{orchestrator.workspace}`")
    
    if st.button("🔒 Lock & Log Out", use_container_width=True):
        st.session_state["authenticated"] = False
        st.query_params.clear()
        st.rerun()
        
    st.markdown("---")
    st.subheader("🛡️ Safety")
    max_steps = st.slider("Max Step Budget", 3, 30, 15)
    
    st.markdown("---")
    st.subheader("📜 Past Missions")
    if available_runs:
        for r in available_runs[:10]:
            icon = "✅" if r["status"] == "completed" else ("🔴" if "fail" in r["status"] or "review" in r["status"] else "🟡")
            with st.expander(f"{icon} {r['goal'][:30]}..."):
                st.caption(f"ID: {r['run_id']}")
                st.caption(f"Status: {r['status']}")
                if st.button("View Details", key=f"view_{r['run_id']}"):
                    st.session_state.selected_history = r['run_id']
    else:
        st.caption("No missions yet.")

# 3. Top Header Bar
col1, col2, col3 = st.columns([1, 4, 1])
with col2:
    st.markdown("<h3 style='text-align: center; color: #f1f5f9; margin:0;'>🌌 Antigravity</h3>", unsafe_allow_html=True)
with col3:
    status_text = "🟢" if orchestrator.is_running else ("🟡" if orchestrator.is_paused else "⚪")
    st.markdown(f"<div style='text-align: right; margin-top: 5px; font-size: 1.2rem;'>{status_text}</div>", unsafe_allow_html=True)

st.divider()

# 4. Human Review Queue (Escalations)
human_queue = get_needs_human_review_runs()
if human_queue:
    for hq in human_queue:
        with st.chat_message("assistant", avatar="🚨"):
            st.error(f"**Mission Escalated:** {hq['goal']}")
            st.markdown(f"**Reason:** `{hq.get('human_review_reason', 'Needs operator decision')}`")
            
            h_col1, h_col2 = st.columns(2)
            with h_col1:
                if st.button("✅ Approve", key=f"app_{hq['run_id']}", use_container_width=True):
                    resolve_human_review(hq['run_id'], "approve", "Approved by human")
                    orchestrator.resume_goal(hq['run_id'])
                    st.rerun()
            with h_col2:
                if st.button("🛑 Abort", key=f"abt_{hq['run_id']}", use_container_width=True):
                    resolve_human_review(hq['run_id'], "abort", "Aborted by human")
                    st.rerun()

# 5. Render Active Mission Stream
if orchestrator.is_running and active_run_id:
    active_run = get_run(active_run_id)
    with st.chat_message("assistant", avatar="🌌"):
        st.markdown(f"**Working on:** {active_run['goal']}")
        st.caption(f"Step {active_run['current_step']}/{active_run['max_steps']} | Tokens: {active_run['tokens_used']:,}")
        
        # Display DAG active agents
        ag = orchestrator.active_agents
        active_list = [k for k, v in ag.items() if v != "idle"]
        if active_list:
            st.markdown(f"**Active Agents:** {', '.join(active_list)}")
            
        st.markdown("---")
        
        # Action Buttons
        p_col1, p_col2 = st.columns(2)
        with p_col1:
            if st.button("⏸️ Pause", use_container_width=True):
                orchestrator.pause()
                st.rerun()
        with p_col2:
            if st.button("🛑 Stop", type="primary", use_container_width=True):
                orchestrator.stop()
                st.rerun()
                
    # Auto-refresh on mobile
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=3000, key="mobile_refresh")
    except:
        time.sleep(3)
        st.rerun()
        
elif orchestrator.is_paused and active_run_id:
    with st.chat_message("assistant", avatar="🟡"):
        st.warning("Mission is paused.")
        if st.button("▶️ Resume", use_container_width=True):
            orchestrator.resume()
            st.rerun()

# 6. Legacy Chat Session History
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 7. Bottom Sticky Chat Input
prompt = st.chat_input("Ask Antigravity to build or fix something...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    if orchestrator.is_running:
        st.session_state.messages.append({"role": "assistant", "content": f"I am currently busy. I will queue or process: {prompt}"})
        orchestrator.intervene(prompt)
    else:
        run_id = orchestrator.start_goal(prompt, "Complete the requested task", max_steps=max_steps)
        st.session_state.messages.append({"role": "assistant", "content": f"🚀 Started mission to: {prompt}"})
    st.rerun()
"""
    
    with open(dashboard_path, "w", encoding="utf-8") as f:
        f.writelines(original_core)
        f.write(mobile_ui)
    
    print("UI Replaced Successfully.")
else:
    print("Could not find '# Header Section'")

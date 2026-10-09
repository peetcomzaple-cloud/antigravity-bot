# BUG_REPORT — antigravity_bot (ตรวจแบบอ่านอย่างเดียว, 2026-09-26)

**โปรเจกต์นี้คืออะไร:** แดชบอร์ด Streamlit (`dashboard.py`) ที่ควบคุมเอเจนต์เขียนโค้ดอัตโนมัติแบบหลายเอเจนต์ ซึ่งเลียนแบบ Google Antigravity ขั้นตอนคือ Intake → Planner วางแผนเป็น DAG → Critic 2 ตัวรีวิวแผน → Coder หลายตัวทำงานขนานกัน (เขียนไฟล์/รันคำสั่ง/pytest/Playwright/APK) → Verify → บันทึก Skill ใช้ OpenRouter หลายคีย์ผ่าน `core/router.py` เก็บสถานะใน SQLite (`core/db.py`) รันคำสั่งใน workspace ผ่าน `core/tools.py` และมี checkpoint git, diff artifact, คิว human-review
**สิ่งที่ตรวจ:** ไฟล์ .py ทั้ง 7 ไฟล์ (~5.9k บรรทัด) + .bat, `py_compile` ผ่าน, ใช้ pyflakes/ruff, รันทดสอบฟังก์ชันจริงบน sandbox (ไม่เรียก API), ตรวจเครื่องผู้ใช้แบบอ่านอย่างเดียว (Python 3.14.7, streamlit 1.64, locale **cp874**, ไม่มี pytest/node/rsync/zip/javac, มี git)
**สรุปจำนวน:** Critical 5 · High 12 · Medium 19 · Low 8  (✔ = ยืนยันด้วยการรัน/ตรวจจริงแล้ว)

---
## 🔴 Critical
| ID | file:line | ปัญหา | อาการ/ผลกระทบ | วิธีแก้ |
|---|---|---|---|---|
| C1✔ | db.py:7, tools.py:14-15, orchestrator.py:35, dashboard.py:91,290 | อ่าน env ตอน import **ก่อน** `load_dotenv` (dotenv ถูกโหลดใน router.py ซึ่ง import ทีหลัง) และ `AutonomousOrchestrator()` ไม่ได้ส่ง workspace เข้าไป | บน Windows ข้อมูลไปอยู่ที่ `C:\opt\ai_gateway\antigravity_bot\antigravity.db` + `workspace` (ยืนยันแล้ว: DB นี้ถูกเขียนเมื่อ 00:01 ส่วน DB กับ workspace ในโปรเจกต์ไม่ถูกใช้เลย) บน Linux ที่ไม่มีสิทธิ์เขียนจะเจอ `PermissionError` ตอน import | สร้าง `core/config.py` ให้โหลด dotenv เป็นอย่างแรก (หรือเรียก load_dotenv บรรทัดแรกของ dashboard.py) อ่าน path ใน runtime และส่ง `workspace=WORKSPACE_DIR` เข้า orchestrator |
| C2✔ | orchestrator.py:360,451 (+multi_agent.py:163, orchestrator.py:351) | เรียก `self.tools.strip_markdown_fences` ซึ่งไม่มีอยู่ใน ToolExecutor | เกิด AttributeError ทุกครั้งที่ step `write_file` ถูกมอบให้ agent ที่ไม่ใช่ built-in และ prompt ของ planner เองก็แนะนำ `"reviewer"` ไว้ จึงเข้าเส้นทางนี้บ่อย → retry จนหมดแล้วไปค้างในคิว human review | เพิ่มเมธอด `strip_markdown_fences` (ใช้ตรรกะเดียวกับ multi_agent.py:476-489) แล้ว map `reviewer` เข้ากลุ่ม built-in หรือเอาออกจาก prompt |
| C3✔ | orchestrator.py:436-437 | ใช้ `re` โดยไม่ได้ import (pyflakes F821) และเรียก `self.tools.file_exists` ที่ไม่มีอยู่จริง | ทุกครั้งที่ `run_command` fail จะเกิด NameError → self-repair ไม่เคยทำงานเลย และ exception นี้ถูกนับเป็น retry | ใส่ `import re` และเพิ่ม `file_exists()` (หรือใช้ `os.path.exists(self.tools._resolve_safe_path(f))`) |
| C4✔ | run_dashboard.bat:7-10, dashboard.py:294-299,1062-1067, tools.py:506 | Streamlit bind ทุก interface (ยืนยันว่ากำลังฟังที่ `:::8501`) + ใช้ token ค่า default ที่ hardcode ไว้ และ bat พิมพ์ token/ลิงก์ auto-login ออกจอ + ส่ง token ผ่าน `?token=` ใน URL + เทียบค่าแบบไม่ constant-time + แท็บ Direct Terminal รันด้วย `shell=True` | ใครก็ได้ในวง LAN รันคำสั่งใดก็ได้บน PC (RCE) | `--server.address 127.0.0.1`, token ต้องมาจาก env เท่านั้นและห้ามมีค่า default, ลบ token ออกจาก bat, ใช้ `hmac.compare_digest`, ล้าง query param หลัง login, ปิด Terminal หรือทำเป็น allowlist + ยืนยันทุกครั้ง, หมุน (rotate) token |
| C5✔ | tools.py:751,884,903-905; orchestrator.py:892-954 | สั่ง `pytest`/`node` แบบ bare ใส่ path ครอบด้วย `'...'` ภายใต้ `shell=True` แต่ cmd.exe ไม่ถือ single quote เป็นตัวครอบ และเครื่องผู้ใช้ไม่มีทั้ง pytest และ node; ถ้าไม่มีเทสต์ pytest จะคืน exit 5 = fail | Phase 3 fail **ทุก run** → เข้า repair loop → human review ทำให้ไม่มีงานไหนไปถึงสถานะ `completed` บน PC เครื่องนี้ได้ | ใช้ list args: `[sys.executable,"-m","pytest",...]`, `["node","--check",path]`, ตรวจว่ามี tool ด้วย `shutil.which` ก่อน, ถ้าไม่มีเทสต์ (exit 5) ให้ถือว่า "ข้าม" ไม่ใช่ fail, ตรวจชนิดโปรเจกต์ก่อน (py/js) และเพิ่ม pytest ใน requirements |

## 🟠 High
| ID | file:line | ปัญหา | อาการ/ผลกระทบ | วิธีแก้ |
|---|---|---|---|---|
| H1✔ | tools.py:717 (→read_file max_lines=500); dashboard.py:943,1075-1084 | `check_code_quality` อ่านไฟล์แค่ 500 บรรทัดแรกแล้วเอาไป `ast.parse` | ไฟล์ .py ที่ยาวเกิน 500 บรรทัดถูกรายงานว่า SyntaxError ทั้งที่ไม่ผิด → grounded fail/retry วน, หน้า viewer และปุ่มดาวน์โหลดได้ไฟล์ที่ถูกตัด | อ่านทั้งไฟล์ (`max_lines=None`) เวลาเช็ก AST/ดาวน์โหลด |
| H2✔ | tools.py:506-514 | `subprocess.run(text=True)` ถอดรหัสด้วย cp874, ไม่ได้ตั้ง `stdin=DEVNULL`, และเมื่อ timeout ภายใต้ shell=True บน Windows ไม่ฆ่า process ลูกหลาน | UnicodeDecodeError/ตัวอักษรเพี้ยน, คำสั่งที่ถาม input ค้าง, สั่งรัน server แล้ว orchestrator ค้างถาวร | ใส่ `encoding="utf-8", errors="replace", stdin=DEVNULL`, ใช้ `Popen` + `CREATE_NEW_PROCESS_GROUP` + `taskkill /T /F` ตอน timeout, เพิ่มโหมดรัน background |
| H3 | tools.py:46-55; orchestrator.py:411-428 | ใช้ denylist ที่มีแต่ pattern ของ Linux (ไม่ครอบคลุม `del /s`, `rd /s`, `Remove-Item -Recurse`, `format`, `iwr\|iex`) และคำสั่งที่ LLM วางแผนถูกรันทันทีโดยไม่ขออนุมัติ | Prompt injection (จากไฟล์หรือเว็บ) พาไปรันคำสั่งทำลายเครื่องได้ | เปลี่ยนเป็น allowlist + policy แบบ Antigravity (Off/Auto/Turbo) คำสั่งเสี่ยงต้องให้คนกดอนุมัติ, parse ด้วย `shlex` |
| H4 | orchestrator.py:767,888,1018 | พอ step ครบ `max_steps` ลูปจะออกไป Phase 3 แล้วตั้งสถานะ `completed` ทั้งที่ยังมี step ไม่เสร็จ | รายงานว่าสำเร็จทั้งที่ทำไม่ครบ | ถ้า `len(completed)<len(all_steps)` ให้ตั้งสถานะเป็น `needs_human_review`/`incomplete` |
| H5 | orchestrator.py:221-233 | Revert: transaction ถูก commit ไปแล้วหลัง step ผ่าน และ checkpoint commit ก็รวมการแก้ไขนั้นไว้แล้ว ดังนั้น `git checkout HEAD -- file` ไม่ได้เปลี่ยนอะไร | ขึ้นว่า "reverted" แต่ไฟล์ไม่เปลี่ยน หรือถ้า tx ยังเปิดอยู่จะ revert ทุกไฟล์ใน step | เก็บ pre-image ของไฟล์ไว้ใน artifact หรือใช้ `git checkout <step_commit>~1 -- file` แล้ว revert เฉพาะไฟล์นั้น |
| H6 | multi_agent.py:470-474; 124,350,365,693,759,823,854,1000 | LLM ล้มเหลว (รวมถึง `TokenBudgetExceededError`) → คืน `current_content` เดิม และหลายเมธอดกลืน exception ไว้หมด | step "สำเร็จ" ทั้งที่ไฟล์ไม่เปลี่ยน, token budget ไม่ถูกบังคับจริง | ปล่อยให้ `TokenBudgetExceededError` เด้งขึ้นไป (`except TokenBudgetExceededError: raise`), ถ้า generation fail ต้องให้ step fail |
| H7 | orchestrator.py:88-105,144-149,1034-1037 | `stop()` แค่เคลียร์ flag แต่ thread เดิมยังทำงานอยู่ จึงกด Start ใหม่ได้ทันที | มี 2 run แชร์ tx/active_agents กัน และ `finally` ของ run เก่าไปตั้ง `is_running=False` ทำให้ run ใหม่หยุด | ใช้ cancel token ต่อ run + `thread.join(timeout)` ก่อนเริ่มใหม่ และ finally ต้องรีเซ็ตเฉพาะ run ของตัวเอง |
| H8✔ | tools.py:1002-1020,1038-1039,1016 | `git add -A` โดยไม่มี .gitignore (จึง commit `.checkpoints`/artifacts/venv/.env), rollback ใช้ `reset --hard`+`clean -fd`, ไม่มี rsync บน Windows ทำให้ snapshot ว่างแต่ยังคืน success, ถ้าไม่มี git จะได้ hash ปลอม `chk_<ts>` | repo บวมเรื่อยๆ, งานของผู้ใช้ที่ยังไม่ commit และ snapshot ใหม่ๆ ถูกลบ, ถ้า workspace เป็น repo ของผู้ใช้ history จะถูกปนเปื้อน | เขียน `.gitignore`, ใช้ shadow repo แยก (`--git-dir`), ใช้ `shutil.copytree` แทน rsync, ถ้า git fail ต้องคืน success=False |
| H9✔ | router.py:33-52,113-118; multi_agent.py:20,29,38,47,56; dashboard.py:692-719; db.py:174 | ประกาศว่า "100% Free" แต่ตรวจ OpenRouter /models แล้วพบว่า deepseek-chat, qwen3-coder, kimi-k2.6, glm-5.3-flash, gemini-2.5-flash **เป็นรุ่นเสียเงิน**; slug `:free` ของ subagent **ไม่มีอยู่จริง** และไม่เคยถูกใช้ (974-981 ใช้แค่เลือก role); gateway `127.0.0.1:8500` ปิดอยู่ | เสียเครดิตจริง; เจอ 402 → ทุกคีย์ติด cooldown 300s → mission fail; fallback "speed" ใช้ไม่ได้ | แก้ chain ให้ใช้ slug ที่มีอยู่จริง/ฟรีจริง (เช่น `z-ai/glm-5.2:free`, `qwen/qwen3.8-27b:free`) หรือเขียนให้ตรงความจริง, ให้ subagent ใช้ `model=assigned_model` จริง, ตรวจ health ของ gateway |
| H10 | orchestrator.py:913-954,958-1018; tools.py:700 | Phase 3 เอาไฟล์ .py ที่ชื่อมี test/bot/main ไปเขียนทับด้วยผลจาก LLM แบบไม่ grounded, ไม่มี tx, ไม่มี diff; `list_files` ไม่ได้ตัด `venv/` ออก; ผล `final_review.passed` ถูกละทิ้ง | โค้ดที่ใช้งานได้อาจพัง, static issue ขึ้นตลอด (โค้ดใน site-packages), ผ่าน review ไม่ได้แต่สถานะยังเป็น completed | ซ่อมเฉพาะไฟล์ที่ traceback ชี้ถึง, ผ่าน grounded+tx+diff artifact, ตัด venv/.venv/site-packages ออก, ต้องให้ passed=True ก่อนจึงจะตั้ง completed |
| H11 | orchestrator.py:851-883 | ใน batch ขนาน ถ้าเจอ fail ตัวแรกจะ `return` ทันที | step ที่สำเร็จใน batch เดียวกันไม่ถูกบันทึก completed/checkpoint/durable → พอ resume ก็ทำซ้ำ | ประมวลผลทุก result ให้ครบก่อน แล้วค่อย escalate |
| H12✔ | orchestrator.py:634-647,659-661; db.py:904-920 | ตอน resume: แถวจาก DB ใช้คีย์ `assigned_agent` ไม่ใช่ `agent` (ยืนยันแล้ว) ทำให้ทุก step กลายเป็น coder, ไม่ได้คืนค่า token/node budget, ไม่ได้ sanitize deps; ส่วน "Approve" ตั้ง step ที่ fail (ซึ่งไฟล์ถูก rollback ไปแล้ว) เป็น completed | resume แล้วพฤติกรรมเพี้ยน, step ถัดไปทำงานบนไฟล์ที่ไม่มีอยู่ | map `assigned_agent→agent`, เก็บ budget ไว้ใน durable_state/runs, ตอน approve ต้องมีไฟล์อยู่จริงหรือให้รัน step นั้นซ้ำ |

## 🟡 Medium
| ID | file:line | ปัญหา → วิธีแก้ |
|---|---|---|
| M1 | orchestrator.py:756; multi_agent.py:229-233,382-401; orchestrator.py:321,659-661; router.py:99 | JSON จาก LLM มีชนิดข้อมูลไม่ตรง: deps เป็น string ถูกทิ้ง (ลำดับหาย/ชนกันตอนรันขนาน), `flagged_steps`/`score` เป็น str → `sorted`/`<` เกิด TypeError ทำให้ run ล่ม, budget เป็น str → TypeError → ให้ coerce เป็น `int()` + clamp + validate ด้วย pydantic schema |
| M2 | orchestrator.py:718-729 | flag ของ critic อิงเลข step ของแผน**เก่า** แต่ถูกนำไปใช้กับแผนที่ refine ใหม่ → ให้ audit แผนใหม่ซ้ำหรือจับคู่ด้วย title/target |
| M3 | orchestrator.py:329-539 | ไม่ validate `action_type`/target: ชนิดที่ไม่รู้จัก (`read_file`, `apply_patch`) กลายเป็น no-op แล้วให้ LLM ตัดสินว่าสำเร็จ; target ว่างแปลว่าเขียนลงโฟลเดอร์ → validate แผนก่อนรัน แล้ว reject/replan |
| M4 | multi_agent.py:438-448,166-170,476-489; router.py:82 | prompt ของ coder บังคับ 100-250 บรรทัดและ hardcode โดเมน Cookie Run/OpenCV/ADB, เขียนทับทั้งไฟล์, ดึงแค่ code fence แรก (อาจได้บล็อก bash), max_tokens 4096 ทำให้ output ถูกตัด → ลบข้อจำกัด/โดเมนออก, ใช้ apply_patch, ตรวจการถูกตัดจาก `finish_reason=="length"` |
| M5 | orchestrator.py:547-548 | ผลจาก reflect ของ LLM ทับผล deterministic (exit≠0 ก็ยังผ่านได้), ถ้า parse ไม่ได้ default เป็น True → ให้ exit code/test result เป็นตัวตัดสินหลัก, default False |
| M6 | tools.py:499-502,953 | `PYTHONPATH` ใช้ `:` คั่น (Windows ต้องใช้ `;`), path venv เป็นของ Linux → ใช้ `os.pathsep` และตั้งค่า venv ผ่าน config |
| M7 | tools.py:925-927; orchestrator.py:400-409 | `file://C:\...` เป็น URI ที่ไม่ถูกต้อง, ถ่าย screenshot ไฟล์ .js ซึ่งไม่มีความหมาย, error ตอน goto ถูกกลืน, success วัดแค่ว่าไฟล์มีอยู่ → ใช้ `Path.as_uri()`, ถ่ายเฉพาะ .html, คืน error จริง |
| M8 | tools.py:118-125,138-146 | ถ้าอ่าน pre-image ไม่ได้จะเก็บเป็น None → ตอน rollback **ลบไฟล์เดิมทิ้ง**; อ่านด้วย errors=replace ทำให้ไฟล์ที่ไม่ใช่ UTF-8 เสีย; เขียนแบบไม่ atomic → เก็บ bytes (`rb`), แยก sentinel สำหรับ "ไฟล์ใหม่", เขียน tmp แล้ว `os.replace` |
| M9 | tools.py:646-673 | apply_patch ใช้ errors=replace, ไม่มี try (exception หลุดออกไปถ้าเรียกตรง), และ orchestrator ไม่เคยเรียกใช้ → แก้ encoding/try แล้วนำไปใช้จริง |
| M10✔ | tools.py:757-770,841-851 | regex placeholder ให้ false positive (`# simulated annealing`, `__init__` ที่มีแค่ `pass`) และใช้กับทุกชนิดไฟล์; parse ผลเทสต์นับคำว่า "3 errors" จาก log ของแอปไปด้วย → ใช้กับ .py เท่านั้น, เข้มขึ้น, parse เฉพาะบรรทัดสรุปของ pytest (หรือใช้ `--junitxml`) |
| M11 | tools.py:359-363; dashboard.py:1067 | ไม่ validate ชนิดตาม TOOL_CONTRACTS, dict ที่ return ก่อนเวลาไม่มี `exit_code/stdout` ทำให้ dashboard เจอ KeyError เมื่อคำสั่งถูก block → ตรวจ type และใช้ `res.get(...)` |
| M12 | db.py:720-739,820-830,850-874,966-987,394-431 | connection รั่วเพราะไม่มี try/finally; ไม่มี `UNIQUE(run_id,step_index)`; `preserve_status` คัดลอกสถานะ "completed" ไปใส่ step ใหม่ที่ใช้เลข index เดิมหลัง replan → ใส่ try/finally/`with`, เพิ่ม constraint, ถ้า replan ให้ preserve_status=False |
| M13 | db.py:171,983; multi_agent.py:64-74 | `subagents.role_name` เป็น UNIQUE ทั้งระบบ ทำให้ชนกันข้าม run, register ซ้ำทุกครั้งที่ init → ใช้ UNIQUE(run_id,role_name) หรือแยก global/run ออกจากกัน |
| M14✔ | db.py:699-716,752 | `search_skills` แยก token ด้วยช่องว่าง → goal ภาษาไทยไม่เจอเลย (ยืนยันว่าได้ `[]`); ค่า AVG pass rate นับ run ที่มีค่า default 0 ไปด้วย → ใช้ FTS5/n-gram หรือตัดคำไทย, ใส่ `WHERE criteria_pass_rate>0` |
| M15 | dashboard.py:331-337,577-673,801-823 | ส่ง string จาก LLM/ผู้ใช้เข้า `unsafe_allow_html` โดยไม่ escape (HTML injection); `st.markdown` render mermaid ไม่ได้ → `html.escape` ทุกค่า, ใช้ `streamlit-mermaid`/graphviz (`st.graphviz_chart`) |
| M16 | dashboard.py:289-291,384-397,1071 | ทุก rerun (ทุก 3s) เรียก `init_db()` (ALTER 30 ครั้ง), อ่าน APK ทั้งไฟล์เข้าหน่วยความจำ, walk workspace → ใช้ `@st.cache_resource` สำหรับ init/orchestrator และโหลด APK แบบ lazy |
| M17 | orchestrator.py:316,768,812-816 | Pause มีผลเฉพาะระหว่าง batch ไม่มีผลกลาง step; คำชี้แนะของผู้ใช้หายหลัง retry แรก (current_feedback ถูกเขียนทับ) → เช็ก pause/cancel ในลูป retry และ prepend interventions ทุก attempt |
| M18 | router.py:168-211,116,182 | timeout 40s ต่อคีย์ × 4 คีย์ × 3 โมเดล ≈ 8 นาทีต่อ call; HTTP 400/404 ก็ยังวนลองคีย์ถัดไป; ไม่ส่ง `response_format` ให้ OpenRouter; `content=None` (reasoning model) → ถ้า 4xx ที่ไม่ใช่ 429 ให้ข้ามไปโมเดลถัดไป, ใส่ backoff, ส่ง response_format/structured outputs, ใช้ `httpx.Client` เดียวร่วมกัน |
| M19 | apk_builder.py:6-15,44-68,113-136; orchestrator.py:499 | ใช้ได้เฉพาะ Linux (`/opt`,`/tmp`,`zip`, ไม่มี `.bat` ต่อท้าย d8/apksigner), app_name ใส่ใน XML โดยไม่ escape, ไฟล์ .class เก่าค้างข้าม build, asset path hardcode, ใช้ `uses-permission BIND_ACCESSIBILITY_SERVICE` ผิดวิธี → ใช้ `tempfile.mkdtemp`, `zipfile`, `shutil.which`, `xml.sax.saxutils.escape`, ส่ง asset มาจากแผน |

## 🟢 Low
| ID | file:line | ปัญหา → วิธีแก้ |
|---|---|---|
| L1 | ทั้งโปรเจกต์ | import ที่ไม่ได้ใช้ 26 จุด (pyflakes), diff renderer ซ้ำกัน (dashboard.py:104-286 ≡ tools.py:1052-1237), f-string ที่ไม่มี placeholder (orchestrator.py:672,711; multi_agent.py:742), `verify_fix_eliminated_issues` เป็น dead code, judge fallback ใช้ `compile()` ของ Python กับโค้ด JS (multi_agent.py:562-570) → ล้างทิ้งและ import renderer จาก tools |
| L2 | dashboard.py:335,402; orchestrator.py:1024; multi_agent.py:820-821 | สถานะ/เมตริกปลอม ("11/11 AI Keys Ready", "Oracle VM", winner model hardcode, `dual_critic_approved = is_verified_hard` โดยไม่มี critic จริง) → แสดงค่าจริง |
| L3 | db.py (CURRENT_TIMESTAMP) | เก็บเวลาเป็น UTC แล้วแสดงดิบๆ (ผู้ใช้อยู่ UTC+7) → แปลงเวลาตอนแสดง |
| L4 | dashboard.py:353-359,758 | checkbox auto-refresh ไม่มี key (state รีเซ็ต), fallback ใช้ `time.sleep` บล็อก UI, step ที่ fail แสดงเป็น 🔄 → ใส่ key, ใช้ ❌ |
| L5 | dashboard.py (หลายจุด) | `use_container_width` deprecated ใน Streamlit 1.64 → ใช้ `width="stretch"` |
| L6 | tools.py:272-280 | ลบ `index.lock` ที่อายุเกิน 5s อาจทำลาย git op ของผู้ใช้ที่กำลังทำงานอยู่ → เพิ่มเป็น >60s และเช็ก process ก่อน |
| L7 | db.py:944,950-961 | human-review queue ไม่ได้กรอง `cycle_%`; cleanup ไม่ลบ memories/tool_audit_log/subagents → ทำให้สอดคล้องกัน |
| L8 | tools.py:630; router.py:14 | `is_new` ผิดเมื่อไฟล์เดิมเป็นไฟล์ว่าง; key default `ag-pool-key` → ใช้ `os.path.exists` ก่อนเขียน และบังคับให้ต้องตั้ง env |

## 🔐 ตำแหน่ง secret (ไม่แสดงค่า)
- `.env`: OPENROUTER_API_KEY_1..4, ANTIGRAVITY_AUTH_TOKEN, ANTIGRAVITY_PASSWORD, AI_GATEWAY_KEY เป็น plaintext (ไม่ใช่ git repo แต่ถ้าจะ push ต้องทำ .gitignore)
- `run_dashboard.bat:7-8`: admin token + ลิงก์ auto-login เป็น plaintext; `dashboard.py:294` มีค่า fallback เดียวกัน และ token ใน `.env` ยาว 22 ตัวเท่ากับค่านี้ จึงน่าจะเป็นค่าเดียวกัน → **ควร rotate**
- `apk_builder.py:147,156-157`: รหัส debug keystore `android` (เป็นค่ามาตรฐานของ debug ยอมรับได้ แต่ห้ามใช้ release)

---
## สิ่งที่ควรปรับปรุง (ให้ทำงานใกล้ Antigravity) — เรียงตามความสำคัญ
1. **Agent loop แบบ tool-calling (ReAct)** แทนการยิง LLM ครั้งเดียวต่อ step: ให้โมเดลเรียก `list_dir/read_file(range)/grep_search/apply_patch(multi-edit)/run_command/browser_*` วนจนงานเสร็จ ใช้ function-calling ของ OpenRouter (`tools=`) แทนการ parse JSON เอง
2. **Implementation Plan + Task list artifact ที่ต้องรีวิวก่อนรัน** (review policy: Always proceed / Agent decides / Request review) ให้ผู้ใช้คอมเมนต์รายบรรทัดได้ แล้ว replan
3. **Terminal policy** แบบ Off/Auto/Turbo + allow/deny list + ปุ่มอนุมัติคำสั่ง รองรับ background process (start/status/kill/อ่าน log) และ stream output สด
4. **แก้ไขแบบ diff** (apply_patch/multi-edit) แทนการเขียนทับทั้งไฟล์ + revert ต่อไฟล์ได้จริง (ดู H5) + ใช้ shadow-git checkpoint ที่ไม่ยุ่งกับ repo ผู้ใช้
5. **เปิดโฟลเดอร์โปรเจกต์จริงเป็น workspace** (เลือก path ใน UI) + context แบบ repo map/สรุปไฟล์/grep แทนการส่งแค่ชื่อไฟล์ 25 ไฟล์
6. **Verification ที่ไม่ผูกกับภาษา**: ตรวจชนิดโปรเจกต์ (pytest/npm test/go test), รันเทสต์เฉพาะที่เกี่ยวข้อง, ถือว่า "ไม่มีเทสต์" ไม่ใช่ fail, ใช้ Browser subagent ที่ click/type/assert ได้จริง (ไม่ใช่แค่ screenshot)
7. **Walkthrough artifact** ตอนจบ: สรุปไฟล์ที่เปลี่ยน, หลักฐานการทดสอบ, screenshot/recording
8. **สนทนาต่อเนื่องใน run เดียวกัน** (chat thread + follow-up) และ cancel/pause ได้ทันทีในระดับ LLM call/subprocess
9. เลิก hardcode โดเมน (Cookie Run/ADB/OpenCV, 100-250 บรรทัด), ใช้โมเดลที่รองรับ tool calling ได้ดีเป็นหลัก ส่วนโมเดลฟรีให้เป็น fallback, ใช้ structured outputs
10. จัดการ context/token: สรุป history, จำกัดขนาด observation, เก็บ token budget ใน DB จริง, เก็บ memory/knowledge items ที่ค้นได้ทั้งภาษาไทยและอังกฤษ

## ลำดับการแก้ที่แนะนำ (สำหรับ Antigravity)
1. C1 (config/dotenv) → C4 (ปิด LAN/token) → C2, C3 (AttributeError/NameError) → C5 (คำสั่งทดสอบบน Windows)
2. H2, H3 (subprocess/policy) → H1 → H4, H10, H11 (ตรรกะการตัดสินว่าเสร็จ) → H6, H7 → H5, H8 (revert/checkpoint) → H12 → H9
3. M1, M3, M5 (validate แผน/ผลลัพธ์) → M4 → M8, M12 → ส่วน Medium ที่เหลือ → Low
4. เริ่มทำข้อปรับปรุง #1-#4 หลัง Critical/High ผ่านแล้ว; ทุกครั้งที่แก้ต้องเพิ่ม pytest ให้ tools.py/db.py (ส่วนที่ deterministic) ก่อน

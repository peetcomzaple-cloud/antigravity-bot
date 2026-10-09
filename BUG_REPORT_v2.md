# BUG_REPORT_v2: antigravity_bot (ตรวจซ้ำหลัง Antigravity แก้ไข) · 2026-09-26 (เวลา BKK)
**สรุป:** บั๊กเดิม 44 ข้อ → Fixed 17 / Partial 20 / Not fixed 7 · บั๊กใหม่ 19 ข้อ (High 2 / Medium 10 / Low 7) · ส่วน C1-C3 ที่ทำให้ระบบพังตอนนี้แก้แล้ว
**ความปลอดภัย:** แก้ได้บางส่วน: bind 127.0.0.1 แล้ว, ลบ default token แล้ว, ไม่ print token แล้ว แต่ `.env` ยังไม่เปลี่ยน (token 22 ตัว วันที่ไฟล์ 2025-09-25) → น่าจะยังเป็น token เดิมที่เคยหลุด ต้อง rotate · Direct Terminal ยังใช้แค่ denylist

วิธีตรวจ: ดึงสำเนาใหม่มาวางบน box แล้ว diff กับชุด v1 · py_compile ผ่าน · pyflakes/ruff เหลือ 29 จุด (ส่วนใหญ่เป็น unused import) · ทดสอบฟังก์ชันแบบ offline ใน /tmp (ไม่ได้เรียก LLM/API และไม่ได้รันอะไรบน PC) · BUG_REPORT.md เดิมไม่ถูกแก้ (SHA256 ตรงกับเดิม) · ไฟล์ที่เปลี่ยน: config.py (ไฟล์ใหม่), db.py, multi_agent.py, orchestrator.py, router.py, tools.py, dashboard.py, run_dashboard.bat · apk_builder.py ไม่ได้แตะ

## 1. สถานะบั๊กเดิม 44 ข้อ
| ID | สถานะ | หมายเหตุ |
|---|---|---|
| C1 | Fixed | `core/config.py` โหลด dotenv ก่อน · ทดสอบบน box แล้ว path มาจาก .env ถูกต้อง แม้ import `core.db` ก่อน |
| C2 | Fixed | มี `strip_markdown_fences` แล้ว (tools.py:295) แต่ดู N15 |
| C3 | Fixed | มี `import re` และ `file_exists` แล้ว · เช็คว่า attribute `self.tools.*` / `self.fleet.*` มีอยู่จริงครบ |
| C4 | Partial | bat ใช้ 127.0.0.1 และไม่ print token แล้ว, ใช้ `hmac` · แต่ token ยังไม่ rotate, `streamlit run` ตรงๆ ยัง bind ทุก interface, terminal ยังเป็น denylist |
| C5 | Partial | `sys.executable -m pytest` และนับ exit 5 เป็นผ่านแล้ว · แต่ Phase 3 ยังเช็คแค่ exit_code (N3) |
| H1 | Fixed | `check_code_quality` ใช้ `max_lines=None` (tools.py:787) · ทดสอบไฟล์ 600 บรรทัดผ่าน · viewer/download ใน dashboard ยังตัดที่ 500 บรรทัด |
| H2 | Fixed | Popen แบบ utf-8, `stdin=DEVNULL`, `taskkill /T` (tools.py:548-586) · `communicate()` หลัง kill ยังไม่มี timeout |
| H3 | Partial | เพิ่ม pattern ของ Windows แล้ว แต่ยังไม่มี approval gate · ยังเลี่ยงได้ด้วย `python -c shutil.rmtree` หรือ `powershell -enc` · และบล็อกคำสั่งปกติผิด (N7) |
| H4 | Fixed | step ที่ค้างอยู่ → `needs_human_review` |
| H5 | Partial | revert ด้วย `<commit>~1` ได้แล้ว · แต่ `is_new` ไม่มีทางเป็นจริง และ fallback ไป HEAD รายงาน success ทั้งที่ไม่ได้ revert อะไร (N9) |
| H6 | Fixed | re-raise `TokenBudgetExceededError` ครบ · `generate_code_single` ไม่คืนโค้ดเดิมแล้ว |
| H7 | Partial | เพิ่ม `join(timeout=2)` · แต่ thread เก่ายังรันซ้อนกับ run ใหม่ (N11) |
| H8 | Partial | `.gitignore` สร้างเฉพาะตอนไม่มีไฟล์, ใช้ `copytree` แทน rsync · ยังมี hash ปลอม `chk_<ts>` (tools.py:1132), ไม่เช็ค error ของ git, `reset --hard`+`clean -fd` (tools.py:1163-1164) และไม่มี shadow repo |
| H9 | Partial | เพิ่ม `:free` แต่ 3 slug ไม่มีอยู่จริง (N10) · model แบบจ่ายเงินยังอยู่ลำดับแรก · `assigned_model` ยังไม่ถูกใช้ |
| H10 | Partial | ซ่อมเฉพาะไฟล์ที่ถูกอ้างถึง · แต่บน Windows path เป็น backslash จึง match ไม่ได้ → ไปแก้ไฟล์ test แทน · ไม่มี tx/diff artifact · final review บล็อกเฉพาะเมื่อ `passed=False` และ score<6 (orchestrator.py:1071) |
| H11 | Fixed | ประมวลผลผลลัพธ์ทั้ง batch ก่อน escalate |
| H12 | Partial | resume map `assigned_agent`→`agent` แล้ว · แต่ budget ถูกเขียนทับ (N6), approve step ที่ rollback แล้วยังถูกนับว่า completed |
| M1 | Partial | critic/plan ถูก coerce แล้ว · แต่ budget จาก intake ยังไม่ถูกแปลงเป็น int (orchestrator.py:726-727) |
| M2 | Not fixed | critic flag ยังอ้างเลขข้อของแผนก่อน refine |
| M3 | Fixed | จัดการ target ว่างและ `action_type` ที่ไม่รู้จักแล้ว |
| M4 | Partial | เอา domain hardcode ออกจาก coder แล้ว · planner ยังมี "Special Domain Knowledge" (multi_agent.py:168-172), ยังเขียนทับทั้งไฟล์, `max_tokens=4096` |
| M5 | Fixed | reflect ตั้งค่าเริ่มต้นเป็น False, คำสั่ง/test ที่ fail จะ `continue` |
| M6 | Fixed | ใช้ `os.pathsep` |
| M7 | Fixed | ใช้ `as_uri()`, จับภาพเฉพาะไฟล์ .html |
| M8 | Fixed | backup เป็น bytes, เขียนแบบ atomic ด้วย `os.replace` |
| M9 | Not fixed | `apply_patch` เหมือนเดิม และ orchestrator ยังไม่เรียกใช้ |
| M10 | Partial | ทดสอบแล้ว: `# simulated annealing` ไม่ถูก flag แล้ว · แต่ `def __init__(self): pass` ยังถูก flag |
| M11 | Partial | response ที่ถูก policy บล็อกมี `exit_code` แล้ว, ขาด param แล้วคืน error ได้ถูก · แต่ยังไม่ validate type |
| M12 | Fixed | ใช้ try/finally, มี UNIQUE index · แต่ DB เก่าที่มีข้อมูลซ้ำจะสร้าง index ไม่สำเร็จแบบเงียบๆ (db.py:222) |
| M13 | Not fixed | `role_name` ยังเป็น UNIQUE ทั้งตาราง |
| M14 | Partial | ทดสอบแล้ว: regex ตัดคำภาษาไทยผิด (`สร`,`างระบบล`...) และ fallback คืน skill ที่ไม่เกี่ยว (N8) |
| M15 | Not fixed | HTML ยังไม่ escape (dashboard.py:681-690 subagent card และอีกหลาย card · มี `unsafe_allow_html` 17 จุด) |
| M16 | Partial | ใช้ `cache_resource` แล้ว · แต่ยังอ่าน APK และเรียก `list_files` ทุกครั้งที่ rerun |
| M17 | Not fixed | pause/intervention เหมือนเดิม |
| M18 | Partial | timeout 25s, 400/404 ข้ามไป model ถัดไป · แต่เพิ่ม fallback ไปใช้ `reasoning` (N4) |
| M19 | Not fixed | apk_builder.py ไม่ได้แก้ |
| L1 | Partial | ยังมี unused import หลายจุด (config.py:2 `sys`, dashboard.py:87 import `html` ซ้ำ, dashboard.py:297 `WORKSPACE_DIR`) |
| L2 | Partial | จำนวน key เป็นค่าจริงแล้ว · `candidate_winner_model` ยัง hardcode (orchestrator.py:1135) |
| L3 | Not fixed | timestamp ยังเป็น UTC |
| L4 | Fixed | step ที่ fail แสดง ❌ แล้ว, checkbox มี key |
| L5 | Partial | ยังใช้ `use_container_width` |
| L6 | Fixed | lock ค้างนานเกิน 60s จึงลบ |
| L7 | Fixed | กรอง `cycle_%` และ cleanup ครบตาราง |
| L8 | Partial | `is_new` ใน write_file ถูกแล้ว · ยังมี default `ag-pool-key` (config.py:42) |

## 2. บั๊กใหม่ / regression
### High
- **N1** orchestrator.py:355 (ไฟล์ target), 469 (self-repair), 1034 (Phase 3) + context ที่ 361/552/1086/1092 · `read_file()` ตัดที่ 500 บรรทัดเป็นค่าเริ่มต้น (tools.py:603) แล้วส่งให้ LLM เขียนไฟล์ใหม่ทั้งไฟล์ → **โค้ดหลังบรรทัด 500 หายถาวร** (ข้อนี้รอบก่อนตรวจไม่เจอ) · แก้: `read_file(target, max_lines=None)` ทุกจุดที่เขียนกลับ และบล็อกการเขียนเมื่อ `truncated=True`
- **N2** tools.py:913 · `"collected 0 items" in stdout` ถูกนับเป็น no-tests=ผ่าน · ทดสอบแล้ว: กรณี collection error (`collected 0 items / 1 error`, exit 2) → `success=True` → test ที่ import พังผ่าน gate ของ step ได้ · แก้: ใช้แค่ `exit_code == 5` เป็นเงื่อนไข no-tests
### Medium
- **N3** orchestrator.py:1022/1025/1053 · Phase 3 เช็ค `exit_code != 0` ไม่ได้ใช้ผลจาก parser → โปรเจกต์ที่ไม่มี test (exit 5) โดนวน repair แล้วจบที่ human review · และถ้าไม่มีไฟล์ที่ match (บรรทัด 1032) จะส่ง prompt "Fix test assertions" ไปแก้ไฟล์ test → LLM อาจทำ test ให้อ่อนลงจนผ่าน (reward hacking) · แก้: ใช้ `parse_test_results()["success"]`, normalize path `\`→`/`, ห้ามแก้ test เพื่อให้ผ่าน
- **N4** router.py:204 · `content or reasoning` → ถ้า content ว่าง ข้อความ reasoning ของ model จะถูกเขียนลงไฟล์เป็นโค้ด หรือถูก parse เป็น JSON · แก้: ถ้า content ว่างให้ถือว่า fail แล้วข้ามไป model ถัดไป
- **N5** orchestrator.py:1140 · `TokenBudgetExceededError` ที่เกิดนอก step (critic ใน thread, final review, synthesize_skill, ADR) ไปตก catch-all → run ถูกตั้งเป็น `failed` แม้งานเสร็จแล้ว · แก้: เพิ่ม `except TokenBudgetExceededError` → `needs_human_review` พร้อม checkpoint
- **N6** orchestrator.py:946/958/978/1130 · `save_durable_state(context_vars={"goal": goal})` เขียนทับ budget ที่บันทึกไว้ที่ 743/840 → resume แล้ว budget หาย · แก้: merge dict แทนการเขียนทับ
- **N7** tools.py (denylist `\b(format|diskpart)\b`) · ทดสอบแล้ว: `ruff format .`, `git log --format=%H`, `'{}'.format(1)` ถูกบล็อก → ใน orchestrator ทำให้ทั้ง run escalate ไป human review · ในขณะที่ `python -c "shutil.rmtree('C:/Users')"` และ `powershell -enc` ยังผ่าน · แก้: match เฉพาะ `^format\s+[a-z]:` และใช้ allowlist + approval
- **N8** db.py:726 + orchestrator.py:625/634 · ถ้าค้นไม่เจอ fallback จะคืน top skills (ทดสอบแล้ว: goal ภาษาไทยได้ `FastAPI_JWT_Auth`, `OpenCV_Template`) → inject context ผิด และ reinforce/decay trust ของ skill ที่ไม่เกี่ยว · แก้: ไม่เจอให้คืน [] หรือใช้ embedding/tokenizer ภาษาไทย และปรับ trust เฉพาะ skill ที่ถูกใช้จริง
- **N9** orchestrator.py:231/256-260 · `is_new` เช็คหา `/dev/null` แต่ diff จาก write_file เป็น `--- a/<name>` (ทดสอบแล้ว) → ไฟล์ใหม่ไม่ถูกลบตอน revert · fallback `checkout HEAD` ไม่เปลี่ยนอะไรแต่รายงาน success · tx rollback ย้อนทั้ง step · ถ้า step ไม่ได้ commit (tools.py:1128) `~1` จะย้อนไปไกลเกิน 1 step · แก้: ใช้ flag `is_new` จากผลของ write_file, ตรวจ diff หลัง revert, เก็บ commit ก่อน step ไว้ตรงๆ
- **N10** router.py:37-53, multi_agent.py:20-56/943-947 · slug `meta-llama/llama-3.3-70b-instruct:free`, `google/gemini-2.0-flash-exp:free`, `z-ai/glm-5.2:free` **ไม่มีใน /api/v1/models ตอนนี้** → subagent ที่ใช้ slug เหล่านี้และ free fallback ใช้ไม่ได้ · `qwen/qwen3.8-27b:free` ยังมีอยู่แต่ไม่ประกาศว่ารองรับ `response_format` · แก้: validate กับ models API ตอนเริ่มระบบ แล้ว cache ผล
- **N11** orchestrator.py:96-103/154-156 · stop → join 2s → start run ใหม่ แต่ thread เก่ายังรันอยู่ และเห็น `is_running=True` (342/851) จึงรันต่อคู่กับ run ใหม่ ใช้ git/workspace ร่วมกัน · แก้: ใช้ stop-event แยกต่อ run และห้าม start จนกว่า thread เก่า `is_alive()==False`
- **N15** tools.py:295 · `strip_markdown_fences` ไม่ได้ใช้ `target_ext` · ทดสอบแล้ว: คำตอบที่มี ```bash ก่อน ```python จะเขียน `pip install x` ลงไฟล์ .py · แก้: เลือก fence ที่ภาษาตรงกับนามสกุลไฟล์ ถ้าไม่มีให้เลือก fence ที่ยาวที่สุด
### Low
- **N12** config.py:35-37 · ถ้าไม่มี token ใน .env จะสุ่ม token ขึ้นมาแต่ไม่แสดงที่ไหนเลย → ผู้ใช้ login ไม่ได้ · แก้: fail พร้อมข้อความ หรือเขียน token ลงไฟล์ local ที่มีสิทธิ์จำกัด
- **N13** dashboard.py:303/325 · `hmac.compare_digest` กับ input ที่ไม่ใช่ ASCII (เช่นพิมพ์ไทย) → TypeError แล้วหน้าพัง (ทดสอบแล้ว) · แก้: `.encode()` ทั้งสองฝั่ง
- **N14** dashboard.py:1094 · Direct Terminal ไม่เช็คคำสั่งว่างแล้ว · แก้: เพิ่ม `if direct_cmd.strip()`
- **N16** dashboard.py:828 · label ใน DOT escape แค่ `"` ยังไม่ escape `\` และ newline → graph อาจพัง
- **N17** dashboard.py:419 · แสดง hostname (`platform.node()`) ใน UI → ข้อมูลเครื่องรั่ว (เล็กน้อย)
- **N18** db.py:222 · สร้าง UNIQUE index ไม่สำเร็จบน DB เก่าที่มีข้อมูลซ้ำ แต่ไม่มีการแจ้ง · แก้: dedupe ก่อนสร้างและ log error
- **N19** tools.py:1139 · `copytree` snapshot ทั้ง workspace ทุก step (ไม่ exclude `node_modules`/`build`) → ใช้ disk เพิ่มขึ้นเรื่อยๆ · แก้: ใช้ git อย่างเดียว หรือ hardlink และตั้ง retention

## 3. ลำดับการแก้ (ทำตามนี้)
1. **Security:** rotate `ANTIGRAVITY_AUTH_TOKEN` ทันที · เพิ่ม `.streamlit/config.toml` (`server.address="127.0.0.1"`) · Direct Terminal ใช้ allowlist + ยืนยันทุกครั้ง · แก้ N13
2. **N1** (ข้อมูลหาย) → `max_lines=None` + บล็อกเมื่อ truncated
3. **Verification gate:** N2 + N3 + C5 → ใช้ parser เดียวกันทุก phase, exit 5 = ไม่มี test, ห้ามแก้ test เพื่อให้ผ่าน
4. **N4 + N15:** กันขยะ (reasoning, bash snippet) ไม่ให้ถูกเขียนลงไฟล์
5. **N10 + H9:** validate slug, เรียงลำดับ free/paid ให้ตรงกับที่ตั้งใจ, ใช้ `assigned_model`
6. **N5, N6, H12:** budget error → human review, merge context ตอนบันทึก, approve ต้องไม่ mark completed ให้ step ที่ rollback แล้ว
7. **N9 + H5 + H8:** revert/checkpoint ที่เชื่อถือได้ (shadow git repo, เช็ค error, ไม่ใช้ hash ปลอม)
8. **N11 + H7 + M17:** lifecycle ของ thread, pause/stop ที่ทำงานจริง
9. **N7 + H3:** policy แบบ allowlist + approval (เหมือน Antigravity "Request review")
10. ที่เหลือ: M2, M9, M13, M14/N8, M15, M16, M19, L-series

## 4. ทิศทางให้ทำงานใกล้เคียง Antigravity
- **แก้เป็น diff แทนเขียนทั้งไฟล์:** ใช้ `apply_patch`/search-replace ที่ verify ได้ (M9) → แก้ N1/M4 ตั้งแต่ต้นทาง และทำให้ไฟล์ใหญ่ทำงานได้
- **Artifact + review gate:** plan → diff → รัน test → screenshot แล้วให้ผู้ใช้กด approve/reject ราย step ด้วย revert ที่ทำงานจริง (N9)
- **Terminal policy 3 ระดับ:** auto / request review / deny + allowlist ต่อโปรเจกต์ แทน regex denylist
- **Verification ที่ซื่อตรง:** ถ้าไม่มี test ให้สร้าง smoke test แทน, ห้ามแก้ test ให้อ่อนลง, final review ต้องบล็อกเมื่อ `passed=False` เพียงอย่างเดียว
- **Model routing:** health-check slug ตอนเริ่ม, เลือกตาม `supported_parameters`, แสดงค่าใช้จ่ายจริงต่อ run
- **Knowledge/skills:** retrieval ด้วย embedding (รองรับภาษาไทย) และปรับ trust เฉพาะ skill ที่ถูกใช้จริง
- **Browser subagent:** ใช้ Playwright ดู DOM/console error ของแอปที่รันจริง ไม่ใช่แค่ screenshot ไฟล์ .html

## ข้อจำกัดของการตรวจ
ไม่ได้เรียก LLM/API และไม่ได้รัน dashboard · พฤติกรรมเฉพาะ Windows (taskkill, path แบบ backslash) อนุมานจากโค้ด · ข้อสรุปว่า token ไม่ได้ rotate มาจากวันที่และความยาวของ `.env` เท่านั้น (ไม่ได้อ่านค่า) · ไม่ได้ทดสอบ APK build · ไม่ได้เปิด DB/`C:\opt`

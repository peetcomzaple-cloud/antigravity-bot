# Antigravity Bot

โปรเจกต์บอตช่วยพัฒนาโค้ด พร้อม Streamlit dashboard และระบบ Planner / Critic / Coder
สำเนานี้มาจากโปรเจกต์ที่ Antigravity แก้ล่าสุดในเครื่อง เมื่อ 9 ตุลาคม 2026
ต้นทาง commit `5b7dda7` ไม่รวมฐานข้อมูล ประวัติงาน API key หรือรหัสเข้าใช้งานจริง

## เริ่มใช้งานบน Windows

ต้องมี Python 3.12 และ Git หากต้องการใช้ความสามารถ checkpoint ที่อาศัย Git

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

แก้ `.env` ใส่ API key และรหัสเข้า dashboard ของคุณ ก่อนเริ่มโปรแกรม:

```powershell
python -m streamlit run dashboard.py --server.address 127.0.0.1 --server.port 8501 --theme.base dark
```

เปิด `http://127.0.0.1:8501` และกรอกรหัสที่ตั้งไว้ใน `ANTIGRAVITY_AUTH_TOKEN`
เปลี่ยนพอร์ตด้วย `--server.port` ถ้าเครื่องมีแอปอื่นใช้พอร์ต 8501 อยู่แล้ว

## โครงสร้าง

- `dashboard.py`: หน้า dashboard ปัจจุบัน
- `core/orchestrator.py`: ควบคุมแผนและวงจรการทำงานของบอต
- `core/multi_agent.py`: Planner, Critic, Coder และการตรวจผล
- `core/router.py`: เลือกโมเดลและจัดการ API
- `core/tools.py`: จัดการไฟล์ คำสั่ง การตรวจโค้ด และ checkpoint
- `core/db.py`: จัดเก็บงานและประวัติใน SQLite
- `BUG_REPORT.md`, `BUG_REPORT_v2.md`: รายงานตรวจรุ่นก่อนหน้า วันที่ในรายงานไม่ใช่ผลทดสอบล่าสุด
- `dashboard_backup.py`, `rewrite_dashboard.py`: ไฟล์สำรองและสคริปต์เดิมที่เก็บมาจากต้นทาง

## สถานะ

นี่คือสำเนาโค้ดจาก Antigravity ไม่ใช่การรับรองว่าแก้บักทั้งหมดแล้ว
ก่อนสำรองขึ้น GitHub ตรวจ syntax ของไฟล์ Python และตรวจไม่ให้มี credential ติดมาด้วย
ยังไม่ได้รันการทดสอบครบระบบหรือเรียกโมเดลจริงกับสำเนานี้
รายชื่อโมเดลและ fallback ใน `core/router.py` ต้องตรวจให้ตรงกับบริการ API ที่คุณใช้

เวอร์ชันเว็บ FastAPI ที่ติดตั้งบน Oracle ในงานก่อนหน้าเป็นอีกชุดโค้ดหนึ่ง
repository นี้เก็บเวอร์ชันล่าสุดจากโฟลเดอร์ Antigravity ตามคำขอ โดยไม่มีการแก้บริการบน Oracle

## ข้อมูลส่วนตัว

`.env`, ฐานข้อมูล SQLite, โฟลเดอร์ `workspace/`, ไฟล์ log และ private keys ถูกกันออกด้วย `.gitignore`
เก็บข้อมูลเหล่านี้แยกจาก GitHub หากต้องการย้ายเครื่อง

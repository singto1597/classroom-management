# CHANGELOG — ระบบบริหารจัดการห้องเรียน

> **นี่คือบันทึกการเดินทางของโปรเจกต์ ไม่ใช่แค่รายการสิ่งที่เปลี่ยน**
>
> เริ่มจาก commit แรก `35bcbba` ในคืนวันที่ 19 มีนาคม 2026 — bot Discord 4 ไฟล์ 568 บรรทัด
> ที่ต่อ PostgreSQL ตรง ๆ เพื่อจัดการตารางเรียนของห้องหนึ่งห้อง
>
> ถึงวันนี้ (31 ตุลาคม 2026) มันกลายเป็นระบบโรงเรียนที่รันอยู่จริง: FastAPI + Vue 3 SPA +
> Discord bot + PostgreSQL + Redis + Gotenberg, 741 commits, 95 pull request ที่ merge,
> 4 ประวัติที่ถูกหลอมรวมเป็น monorepo เดียว, 56 เวอร์ชัน
>
> เอกสารนี้เขียนให้ **เปิดกลับมาอ่านแล้วเห็นภาพว่าตอนนั้นคิดอะไรอยู่** — ไม่ใช่เพื่อให้
> git log อ่านง่ายขึ้น แต่เพื่อให้รู้ว่าทุกก้าวมาจากการตัดสินใจอะไร มีอะไรพัง และผ่านมาได้อย่างไร

---

## วิธีอ่านเอกสารนี้

แต่ละเวอร์ชันเล่า 6 อย่าง:

| หัวข้อ | ตอบคำถาม |
|---|---|
| **บริบท ณ ตอนนั้น** | ตอนนั้นระบบมีอะไรแล้ว ขาดอะไร โค้ดโตแค่ไหน |
| **สิ่งที่ทำ** | งานก้อนนี้คืออะไร เล่าเป็นเรื่อง |
| **ตัดสินใจเพราะ** | เจอทางเลือกอะไร ทำไมเลือกทางนี้ |
| **เทคโนโลยีที่เปลี่ยน/ลอง** | เพิ่ม ถอด หรือทดลองอะไร |
| **พังแล้วแก้อย่างไร** | bug / incident และบทเรียน |
| **สิ่งที่ยาก / ภูมิใจ** | อุปสรรคของรอบนั้น |

ข้อความเชิง "ตัดสินใจ" ทุกอันมีที่มากำกับ:
- `> ที่มา: …` = มีหลักฐานตรง (PR body, commit message, เอกสาร ณ ตอนนั้น)
- `> อนุมานจาก diff` = อ่านจากโค้ดที่เปลี่ยนแล้วสรุป — เป็นการตีความ ไม่ใช่คำพูดของใคร

เวอร์ชันเรียงจากเก่าไปใหม่ เพราะนี่คือเรื่องเล่า ไม่ใช่ release note

---

## ภาพรวมการเดินทาง

| | |
|---|---|
| commit ทั้งหมดที่ reachable จาก HEAD | **741** |
| first-parent (เส้นหลักของ monorepo) | 193 |
| commit ฝั่ง main (รวม PR branch) | 437 |
| commit ใน 4 ประวัติย่อยที่ import เข้ามา | 304 |
| pull request ที่ merge | **95** (#1–#98, ปิดไม่ merge 3 ตัว: #3 #4 #91) |
| ประวัติต้นทาง (root) | **4** — bot, backend, frontend_php, frontend_ts |
| เวอร์ชัน | **56** (16 ก่อน 1.0.0 + 40 ตั้งแต่ 1.0.0) |
| ช่วงเวลา | 19 มี.ค. 2026 → 31 ต.ค. 2026 (7 เดือน 12 วัน) |
| migration file | 0 ณ ตอนเขียน (schema ยังอยู่ใน `init_db.py` — ดู v1.27.0) |

### หกยุค

| ยุค | ช่วง | เกิดอะไร |
|---|---|---|
| **1. bot ตัวเดียว และการเกิดเว็บ** | 0.1.0–0.9.0 (มี.ค.–พ.ค.) | Discord bot → PHP web → FastAPI → Vue SPA, แยก service ทีละตัว |
| **2. monorepo, identity, V1** | 0.10.0–1.0.0 (มิ.ย.) | รวม repo ด้วย submodule, Google Login, ระบบห้อง/ผู้ใช้, ประกาศ V1 |
| **3. สิทธิ์, การรวมประวัติ, bot ใหม่** | 1.1.0–1.4.0 (ก.ค.) | RBAC, subtree merge 4 repo → monorepo, bot ถอยเป็น notification-only |
| **4. บัญชีคู่, กิจกรรม, consent** | 1.5.0–1.16.0 (ส.ค.) | double-entry, Activity 3 ชั้น, English-primary identity, Consent Model |
| **5. การเงิน ERP-grade + audit** | 1.17.0–1.26.0 (ก.ย.) | General Journal, เอกสาร F1–F6, Excel export, ปิดผลตรวจระบบ 23 ก.ย. |
| **6. P0/P1 และ versioning** | 1.27.0–1.29.0 (ต.ค.) | migrations runner, CI 5 ด่าน, design tokens, แยก shell, ระบบ versioning นี้ |

---

## ก้าวผ่านเทคโนโลยี — สิ่งที่เปลี่ยนไปตามกาลเวลา

ตารางนี้คือกระดูกสันหลังของเรื่องทั้งหมด แต่ละแถวคือการตัดสินใจที่ย้อนกลับไม่ได้ (หรือย้อนกลับยาก)

| จาก | ไป | เวอร์ชัน | เพราะอะไร |
|---|---|---|---|
| bot ต่อ PostgreSQL ตรง | bot เป็น API client ล้วน | 0.7.0 | สองที่เขียน DB เดียวกัน = กติกาแตกเป็นสองชุด |
| PHP MVC + PDO | Vue 3 + TypeScript SPA | 0.3.0 → 0.8.0 | หน้าจอเริ่มซับซ้อน jQuery/PHP เรนเดอร์ไม่ไหว |
| PHP คงอยู่คู่กัน | archive | 1.3.0 | มีสองหน้าจอทำเรื่องเดียวกัน = ต้องแก้สองที่ |
| 4 repo + git submodule | monorepo ด้วย git subtree | 0.10.0 → 1.3.0 | PR ข้าม component ทำไม่ได้, version ข้าม repo ประสานไม่ลง |
| Discord OAuth | Google OAuth + JWT (user_id) | 0.12.0–0.13.0 | ครู/นักเรียนไม่ได้มี Discord ทุกคน; Discord กลายเป็นช่องทางเสริม |
| `server_id` (ห้อง Discord) | `room_id` (ห้องเรียน) | 0.13.0–0.14.0 | แนวคิดหลักคือ "ห้องเรียน" ไม่ใช่ "เซิร์ฟเวอร์" |
| ชื่อไทยเป็นหลัก | English-primary + `nickname_en` | 1.14.0 | ชื่อเล่นอังกฤษคือชื่อที่ใช้จริงในห้อง |
| บัญชีเดี่ยว (single-entry) | บัญชีคู่ (double-entry) | 1.7.0 | ต้องตอบให้ได้ว่าเงินมาจากไหน ไปไหน และกระทบยอด |
| Tailwind อิสระรายหน้า | Academic Ledger → design tokens + lint | 1.20.0 → 1.27.0 | หน้าจอเริ่มไม่เป็นภาษาเดียวกัน |
| ไม่มี test | pytest → bot unittest 101 → CI 5 ด่าน → Playwright e2e | 0.11.0 → 1.27.0 | deploy บ่อยขึ้นเรื่อย ๆ จนความมั่นใจด้วยตาไม่พอ |
| `deploy.yml` ต่อ repo | `pull_all.sh` + image tag = commit hash | 0.9.0 → 0.10.0 | 4 workflow แยกกัน deploy ไม่พร้อมกัน |
| `docker stack deploy` ตรง ๆ | + compose gate + `IMAGE_TAG` trap | 1.25.2 | deploy ด้วย `latest` เงียบ ๆ เคยทำให้เข้าใจผิดว่าโค้ดใหม่ขึ้นแล้ว |
| ไม่มีเลขเวอร์ชัน | `VERSION` → `/api/version` → UI | 1.29.0 | ต้องตอบได้ว่า production รันอะไรอยู่ |

---

## สิ่งที่ลองแล้วถอย / ลองแล้วเก็บ

การทดลองที่ล้มเหลวก็เป็นประวัติ — บางอันถูกถอดออกภายในวันเดียว

| สิ่งที่ลอง | ผล | เวอร์ชัน |
|---|---|---|
| Redis pub/sub แจ้งเตือน web → Discord | เงียบไม่ทำงานช่วงแรก แล้วแก้ที่ channel/encoding | 0.10.0 → 1.8.0 |
| Adminer (ดู DB ผ่านเว็บ) | เก็บไว้ ใช้ประโยชน์ได้ | 1.3.1 |
| Bytebase | เพิ่มแล้วถอดออกวันเดียวกัน — หนักเกินความจำเป็น | 1.3.1 |
| backend 3 replicas | ลดเหลือตามความจำเป็นของเครื่อง 12 GB | 1.3.1 |
| PHP frontend | archive หลัง Vue SPA ทำงานครบ | 1.3.0 |
| dynamic smart forms (กิจกรรม) | เก็บ แต่ต้องมี guard ไม่ให้ฟอร์มเพี้ยน | 1.13.0 |
| bot เป็น UI เต็มรูปแบบ | ถอยเป็น notification-only + ลิงก์ไปเว็บ | 1.4.0 |
| `oh_shit.sh` (ถอย 1 commit) | ไม่พอหลัง deploy ข้ามหลาย PR → `rollback.sh <tag>` | 1.29.0 |
| `npm run format` ทั้ง repo | ไม่ปลอดภัย — rewrite 67 ไฟล์ที่ไม่เกี่ยว | บันทึกใน docs/skills.md |

---

## หลักการนับเวอร์ชันของโปรเจกต์นี้

1. **1 version = 1 ช่วงงานที่ coherent** ไม่ใช่ 1 commit หรือ 1 PR
2. **ตัดตามเหตุการณ์ ไม่ตัดตามปฏิทิน** — จุดที่งานก้อนหนึ่งจบและก้อนใหม่เริ่ม
3. **MINOR** = ผู้ใช้เห็นความสามารถใหม่ หรือ milestone เชิงโครงสร้างที่เปลี่ยนวิธีพัฒนา
4. **PATCH** = fix / UI / docs / infra ล้วน
5. **MAJOR** = เปลี่ยนความหมายของข้อมูลหรือการใช้งานแบบ breaking (รอบนี้มีครั้งเดียว: 1.0.0)
6. **ก่อน 1 ก.ค. 2026 ประวัติไม่เป็นเส้นเดียว** — มี 4 root ที่แยกกัน จึงระบุ "component tips"
   ของทุกตัว ณ วันนั้นในทุกเวอร์ชันช่วงนั้น
7. **ไม่ backdate** — tag/Release ย้อนหลังสร้างวันที่ 31 ต.ค. 2026 แต่หัวข้อระบุวันที่เดิม

---

# ยุคที่ 1 — bot ตัวเดียว และการเกิดเว็บ (มี.ค.–พ.ค. 2026)

> ช่วงนี้ยังไม่มี monorepo ไม่มี CI ไม่มี test ไม่มี Docker ด้วยซ้ำ
> มีแต่คนคนหนึ่งกับ terminal กลางคืน กับปัญหา "ตารางเวรห้องเรียนมันหากันยาก"

---

## [0.1.0] — 2026-03-20 — คืนแรก: ตารางเรียนย้ายเข้า Discord

**บริบท ณ ตอนนั้น** — ยังไม่มีอะไรเลย ไม่มีเว็บ ไม่มี API ไม่มีฐานข้อมูลกลาง
repo เดียวมี 4 ไฟล์ 568 บรรทัด: `main.py` (44), `commands.py` (260), `db.py` (260), `.gitignore`
bot ต่อ PostgreSQL ตรงด้วย `asyncpg` และ **สร้างตารางเองตอนเริ่ม** 6 ตัว:
`rooms`, `default_schedules`, `schedule_overrides`, `tasks`, `daily_notes`, `audit_logs`
เวลาใช้ `Asia/Bangkok` (UTC+7) ตั้งแต่คืนแรก

**สิ่งที่ทำ** — commit แรก `35bcbba` วันที่ 19 มี.ค. 22:38 สร้าง bot ที่ตอบคำสั่งใน Discord:
ตั้งห้อง (`setup_room`), ผูกช่องประกาศ (`set_channel`), ตั้งตารางสอนประจำ (`set_schedule`),
ตั้งตารางแทน/เลื่อน (`schedule_overrides`), เพิ่ม/แก้งาน (`tasks`), จดโน้ต (`daily_notes`),
ดูตารางวันนี้/พรุ่งนี้ และ autocomplete ชื่อนักเรียน/งาน
จากนั้นอีก 4 commit ปิดรอบ: `automation service` (แจ้งเตือนอัตโนมัติตามเวลา),
`edit type of table` (แก้ชนิดคอลัมน์ก่อนข้อมูลจริงจะทับถม), `change message`, `add tag`

**ตัดสินใจเพราะ** — เริ่มจาก Discord ไม่ใช่เว็บ เพราะนั่นคือที่ที่นักเรียนอยู่ในชีวิตจริง
การเปิดแอปใหม่เพื่อดูตารางเวรเป็นกำแพงที่สูงเกินไป แต่การพิมพ์ `/schedule` ในเซิร์ฟเวอร์ที่มีอยู่แล้ว
คือระยะห่างศูนย์คลิก และ bot เขียนลง DB ตรงก็เพียงพอสำหรับคนเดียวดูแล
— `> อนุมานจากโครงสร้างโค้ด: ไม่มี API layer, ไม่มี Docker, ไม่มี config แยก`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Python 3 + `discord.py` + `asyncpg` + PostgreSQL
แนวคิด "ตารางปกติ + ตาราง override" ถูกใช้ครั้งแรกที่นี่ และ **ยังอยู่ถึงวันนี้** ในชื่อ
`default_schedules` / `schedule_overrides`

**พังแล้วแก้อย่างไร** — commit `edit type of table` เกิดก่อนมีข้อมูลจริง จึงแก้ชนิดคอลัมน์ได้ถูก
(ถ้าช้ากว่านี้จะกลายเป็น migration) — เป็นครั้งแรกที่ได้บทเรียนว่า "แก้ schema ตอนยังไม่มีคนใช้"
เป็นสิทธิพิเศษที่หมดอายุเร็วมาก

**เพิ่ม**
- คำสั่งจัดการห้อง ตารางสอน งาน และโน้ต ผ่าน Discord
- ตาราง 6 ตัว + audit log ตั้งแต่ version แรก
- ระบบเวลาไทย UTC+7

**สิ่งที่ยาก / ภูมิใจ** — ทั้งระบบอยู่ใน 568 บรรทัด และมันใช้งานได้จริงในคืนเดียว
นี่คือจุดที่โปรเจกต์นี้พิสูจน์ว่าตัวเองควรมีอยู่ต่อ

**Migration:** ไม่มี — schema สร้างจากโค้ด bot โดยตรง
**อ้างอิง:** bot commits `35bcbba..1fc2e0d` (5 commits)

---

## [0.2.0] — 2026-04-22 — /help, หน้าต่างกรอกข้อมูล, readme แรก

**บริบท ณ ตอนนั้น** — bot ทำงานได้ แต่ใช้งานยาก: ทุกอย่างต้องพิมพ์พารามิเตอร์ยาว ๆ
ในช่องแชท และไม่มีใครนอกจากคนเขียนรู้ว่ามีคำสั่งอะไรบ้าง

**สิ่งที่ทำ** — เพิ่ม `/help`, เพิ่ม `ui/` 4 ตัว (`add_note_ui`, `add_task_ui`, `edit_task_ui`,
`set_override_ui`) ที่ใช้ `discord.ui.Modal` ให้กรอกเป็นฟอร์มแทนการพิมพ์ยาว
และเขียน `readme.md` 101 บรรทัด + `requirements.txt` 13 บรรทัด — ครั้งแรกที่โปรเจกต์
อธิบายตัวเองได้โดยไม่ต้องถามเจ้าของ

**ตัดสินใจเพราะ** — modal ใน Discord ให้ประสบการณ์ใกล้เคียงฟอร์มเว็บ โดยไม่ต้องสร้างเว็บ
และช่วยลดข้อผิดพลาดจากการพิมพ์ผิด — `> อนุมานจาก diff: UI ถูกแยกโฟลเดอร์จาก commands`

**เทคโนโลยีที่เปลี่ยน/ลอง** — `discord.ui.Modal` / `View` และรูปแบบ "UI แยกจาก logic"
ซึ่งกลายเป็นโครงเดียวกับที่ bot ยังใช้ถึงทุกวันนี้ (`bot_discord/ui/`)

**เพิ่ม**
- `/help`
- ฟอร์มเพิ่มโน้ต เพิ่มงาน แก้งาน ตั้งตารางแทน
- readme + requirements

**แก้ไข**
- `main.py` ปรับการโหลดคำสั่ง (9 ไฟล์, +429/−79)

**สิ่งที่ยาก / ภูมิใจ** — การเขียน readme ครั้งแรกคือการยอมรับว่าโปรเจกต์นี้จะถูกใช้ต่อ
ไม่ใช่สคริปต์ส่วนตัวอีกต่อไป

**Migration:** ไม่มี
**อ้างอิง:** bot commits `a553624..ea6e768` (3 commits)

---

## [0.3.0] — 2026-04-30 — เว็บ PHP เกิด: ตารางสอนบนเบราว์เซอร์

**บริบท ณ ตอนนั้น** — Discord ตอบโจทย์ "ดูเร็ว ๆ" แต่ไม่ตอบโจทย์ "ดูทั้งสัปดาห์"
และไม่ตอบโจทย์ครูที่ต้องการแก้หลายอย่างพร้อมกัน ต้องมีหน้าจอจริง

**สิ่งที่ทำ** — เกิดโปรเจกต์ที่สอง: `classroom-management_web-announcement_php`
โครง MVC เรียบง่าย — `index.php`, `config/database.php` (PDO), `controllers/`
(Cron, Note, Schedule, Task), `models/` (AuditLog, Note, Schedule, Task), `views/`
(tasks, notes, schedules, dashboard) — หน้าแรกมี dashboard สรุปงาน/ตาราง
มีระบบ filter และแก้ bug ด้านความปลอดภัย (escape ข้อมูลก่อนเรนเดอร์)

**ตัดสินใจเพราะ** — เลือก PHP เพราะโฮสต์ที่ใช้อยู่รัน PHP ได้ทันที ไม่ต้องตั้ง process manager
และเป็นภาษาที่แก้เร็วกว่าในช่วงที่ยังไม่รู้ว่ารูปแบบหน้าจอควรเป็นอย่างไร
— `> อนุมานจาก diff: ใช้ PDO ตรงกับ MySQL/PostgreSQL ผ่าน config/database.php ไม่มี framework`

**เทคโนโลยีที่เปลี่ยน/ลอง** — PHP + PDO + MVC แบบบ้าน ๆ, session login, cron controller
สำหรับงานประจำ (`CronController`) — แนวคิด "งานตามเวลา" ที่ bot ทำด้วย `tasks` เริ่มแยกเป็นของเว็บด้วย

**พังแล้วแก้อย่างไร** — commit `edit bug and vulnerability` แก้ช่องโหว่ตั้งแต่สัปดาห์แรก
(น่าจะเป็นการเรนเดอร์ข้อมูลผู้ใช้โดยไม่ escape) — บทเรียนแรกเรื่อง "ข้อมูลที่ผู้ใช้กรอก
ต้องถือว่าเป็นอันตรายเสมอ"

**เพิ่ม**
- หน้า dashboard, งาน, โน้ต, ตารางสอน บนเว็บ
- filter รายการ
- cron endpoint

**แก้ไข**
- ช่องโหว่การเรนเดอร์ข้อมูล (XSS)
- bug การแสดงผลตาราง

**ความปลอดภัย**
- escape ข้อมูลก่อนแสดงผล

**สิ่งที่ยาก / ภูมิใจ** — การมีสองหน้าจอ (Discord + เว็บ) ทั้งที่ยังไม่มี API กลาง
หมายความว่าทั้งสองที่เขียน DB เอง — หนี้ทางสถาปัตยกรรมก้อนแรกที่ต้องใช้ v0.7.0 มาชดใช้

**Migration:** ไม่มี
**อ้างอิง:** php commits `683b44d..a32b65e` (5 commits)

---

## [0.4.0] — 2026-05-08 — FastAPI เกิด: ชั้น API กลาง

**บริบท ณ ตอนนั้น** — bot ต่อ DB ตรง, PHP ต่อ DB ตรง — สองที่ สองชุดกติกา
เริ่มมีข้อมูลนักเรียนที่ต้องใช้ร่วมกัน และเริ่มมีคำถามว่า "ใครแก้อะไร"

**สิ่งที่ทำ** — เกิดโปรเจกต์ที่สาม: `classroom-management_api` (FastAPI)
commit แรกมี `main.py`, `core/config.py`, `core/dependencies.py`, `models/`
(`classroom_sync_schemas`, `maintenance_schemas`, `student_schemas`), `routers/`
(`classroom_sync_router`, `maintenance_router`, `student_router`), `services/` ตามลำดับ
จากนั้นในรอบเดียวกัน: student info, log service + restore, maintenance service (ยังไม่เสร็จ),
login ด้วย Discord + เลือกห้อง, และ patch สิทธิ์การ export Excel

**ตัดสินใจเพราะ** — FastAPI ให้ schema อัตโนมัติ (OpenAPI) และ async ตรงกับภาระงานที่รอ I/O
การแยก API ออกมาทำให้ bot/PHP เลิกเขียน DB ตรงได้ในอนาคต
— `> ที่มา: commit "add login with discord and selection room" + "add log service and restore func"`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Python 3.12 + FastAPI + Pydantic v2 + asyncpg
รูปแบบ **router → service → SQL** ถูกวางครั้งแรกที่นี่ และยังเป็นกฎเหล็กของ repo ถึงวันนี้

**พังแล้วแก้อย่างไร** — `maintenance service but not finished` ถูก commit ทั้งที่ยังไม่เสร็จ
(ยอมรับสภาพกลางทาง) — เป็นครั้งแรกที่เห็นนิสัยของโปรเจกต์นี้: **ของที่ยังไม่ครบถูก merge
ถ้ามันไม่ทำให้ของเดิมพัง** แล้วค่อยปิดทีหลัง

**เพิ่ม**
- API กลางสำหรับนักเรียน, classroom sync, maintenance
- log service + restore
- Discord login + เลือกห้อง
- สิทธิ์การ export Excel

**สิ่งที่ยาก / ภูมิใจ** — การมี API กลางเปลี่ยนคำถามจาก "หน้าไหนแก้อะไร" เป็น
"service ไหนรับผิดชอบ" — ยังไม่ตอบได้ทั้งหมด แต่วางทิศถูกตั้งแต่เดือนที่สอง

**Migration:** ไม่มี — ยังไม่มี `init_db.py`; ตารางยังมาจาก bot/PHP
**อ้างอิง:** backend commits `71ef439..3e24246` (7 commits)

---

## [0.5.0] — 2026-05-10 — นักเรียนบนเว็บ + ลบถาวร + login ห้อง

**บริบท ณ ตอนนั้น** — API มี student router แล้ว แต่เว็บยังไม่มีหน้าเพิ่ม/แก้/ลบนักเรียน
และ bot ยังเป็นทางเดียวที่ผูกผู้ใช้กับห้องได้

**สิ่งที่ทำ** — เพิ่มนักเรียนเข้าระบบผ่านเว็บ, ปุ่ม hard delete, login Discord + room selection
ครบวงจร, และแก้สิทธิ์ export Excel ให้ตรงบทบาท

**ตัดสินใจเพราะ** — hard delete ถูกใส่ก่อน soft delete เพราะยังเชื่อว่าการลบคือการลบ
— การตัดสินใจนี้ถูกพลิกใน v0.7.0 เมื่อ audit log ทำให้เห็นว่าข้อมูลที่หายไปคือหลักฐาน

**เทคโนโลยีที่เปลี่ยน/ลอง** — เริ่มใช้ `room_id` ใน flow ของ student (ก่อนจะ refactor
ทั้งระบบใน v0.13.0–0.14.0)

**พังแล้วแก้อย่างไร** — การเพิ่มนักเรียนชนกับข้อมูลเดิมที่ bot สร้าง (schema ไม่ตรงกัน)
ต้องแก้ DTO ทั้งสองฝั่ง — บทเรียน: **schema กลางต้องมาก่อนหน้าจอ ไม่ใช่ตามหลัง**

**เพิ่ม**
- หน้าเพิ่ม/แก้/ลบนักเรียนบนเว็บ
- login Discord + เลือกห้อง
- hard delete

**แก้ไข**
- สิทธิ์ export Excel
- schema นักเรียนให้ตรงกับ API

**สิ่งที่ยาก / ภูมิใจ** — ครั้งแรกที่เว็บกับ bot แตะข้อมูลชุดเดียวกันโดยไม่พัง

**Migration:** ไม่มี — DDL ยังกระจายอยู่ระหว่าง bot กับ API
**อ้างอิง:** backend/php commits (5 commits, +123/−13 ใน cut)

---

## [0.6.0] — 2026-05-11 — ระบบการเงิน: 1,022 บรรทัดในวันเดียว

**บริบท ณ ตอนนั้น** — ห้องเรียนมีค่าใช้จ่ายจริง: เก็บเงินค่ากิจกรรม ค่าอุปกรณ์
การจดในสมุดแล้วตามเก็บทีหลังทำให้ยอดขาด

**สิ่งที่ทำ** — commit `add finance management` เดียว เพิ่ม 4 ไฟล์ 1,022 บรรทัด:
`models/finance_schemas.py` (160), `routers/finance_router.py` (197),
`services/finance_service.py` (602), และแก้ `main.py` (63)
ครอบคลุมบัญชีการเงิน หมวดหมู่ รายการรับ–จ่าย การเก็บเงินรายคน และหน้าจอ PHP ที่เรียกใช้

**ตัดสินใจเพราะ** — เริ่มจาก **single-entry** (รายการรับ/จ่าย + หมวด) เพราะโจทย์จริงตอนนั้น
คือ "ใครยังไม่จ่าย" ไม่ใช่ "งบดุลต้องกระทบยอด" — ทางเลือกที่เร็วและพอใช้
และเป็นหนี้ที่จะถูกชดใช้ใน v1.7.0 (double-entry) เกือบ 3 เดือนต่อมา

**เทคโนโลยีที่เปลี่ยน/ลอง** — เริ่มใช้ `NUMERIC/DECIMAL` สำหรับเงิน (asyncpg คืน `Decimal`)
และ transaction หลายตารางใน service เดียว — รูปแบบที่ยังอยู่ถึงวันนี้

**พังแล้วแก้อย่างไร** — ยังไม่มี test; ความถูกต้องของยอดพึ่งการอ่านโค้ด
— `> อนุมานจาก diffstat: ไม่มีไฟล์ test ใน commit นี้`

**เพิ่ม**
- บัญชี/หมวด/รายการ/การเก็บเงิน
- หน้าจอการเงินฝั่ง PHP

**สิ่งที่ยาก / ภูมิใจ** — เขียน business logic การเงิน 602 บรรทัดในคืนเดียว
โดยไม่มีสเปก — มันใช้งานได้ และผ่านการใช้งานจริงมาหลายเดือนก่อนถูกแทนที่ด้วยบัญชีคู่

**Migration:** ไม่มี — ตารางการเงินถูกสร้างผ่าน API/PHP
**อ้างอิง:** backend/php commits

---

## [0.7.0] — 2026-05-17 — bot เลิกแตะ DB + audit log + soft delete

**บริบท ณ ตอนนั้น** — สามที่เขียน DB เดียวกัน (bot, PHP, API) เริ่มทำให้เกิดข้อมูลที่อธิบายไม่ได้
เช่น "ใครลบนักเรียนคนนี้" คำตอบคือ "ไม่รู้"

**สิ่งที่ทำ** — PR แรกของ bot: `refactor/migrate-to-api` — bot เปลี่ยนจาก `asyncpg` ตรง
เป็น `services/api_client.py` ที่เรียก API ด้วย `X-API-Key`
พร้อมกันนั้นฝั่ง backend เพิ่ม audit log + data validation, เปลี่ยน hard delete เป็น soft delete
(`deleted_at`), เพิ่มความปลอดภัยและ UX, และแก้บั๊กการเงินหลายจุด (ช่วงวันที่, dashboard, loop)

**ตัดสินใจเพราะ** — "หนึ่งระบบ หนึ่งประตู" — ให้ backend เป็นเจ้าของข้อมูลเพียงผู้เดียว
เป็นหลักการที่เขียนไว้ใน `CLAUDE.md` ถึงวันนี้ — `> ที่มา: PR #1 ชื่อ refactor/migrate-to-api`

**เทคโนโลยีที่เปลี่ยน/ลอง** — `X-API-Key` + `X-Discord-Id` สำหรับ bot
และ audit log ที่เก็บ `old_values`/`new_values` ใน transaction เดียวกับการแก้ข้อมูล

**พังแล้วแก้อย่างไร** — ระหว่างย้าย bot เจอ infinite loop และบั๊กวันที่ (`edit end and start
when get_transactions date bug`) — แก้ในรอบเดียวกัน

**เพิ่ม**
- audit log + validation
- soft delete
- bot ผ่าน API เท่านั้น

**แก้ไข**
- bug ช่วงวันที่ของรายการเงิน
- finance dashboard
- infinite loop

**ความปลอดภัย**
- ยกเลิกการต่อ DB ตรงจาก bot

**สิ่งที่ยาก / ภูมิใจ** — นี่คือ refactor ที่เจ็บที่สุดของยุคแรก: ต้องแก้ bot ทั้งตัว
ขณะที่ข้อมูลจริงกำลังถูกใช้อยู่ และไม่มี test รองรับเลย

**Migration:** ตาราง `audit_logs` ถูกใช้จริงเต็มรูปแบบ; เพิ่มคอลัมน์ `deleted_at` (soft delete)
**อ้างอิง:** bot PR #1 · commits `4d4df15` และรอบการเงิน/ความปลอดภัย

---

## [0.8.0] — 2026-05-24 — Vue 3 + TypeScript SPA เกิด

**บริบท ณ ตอนนั้น** — PHP เรนเดอร์หน้าจอทีละหน้า เริ่มช้าและกระตุกเมื่อมี filter/ตารางใหญ่
และต้องการ state ร่วม (ผู้ใช้, ห้อง, บทบาท) ที่ PHP ไม่ถนัด

**สิ่งที่ทำ** — เกิดโปรเจกต์ที่สี่: `classroom-management_frontend_ts` — Vite + Vue 3 + TypeScript
commit แรกมี `src/stores/auth.ts`, `src/types/student.ts`, `src/views/students/`
(AddStudent, EditStudent, StudentList, StudentProfile), `vite.config.ts`
จากนั้นในรอบเดียวกัน: refactor คำตอบ API เป็น JSON, เพิ่ม role, แก้ timezone,
ส่ง `X-Discord-Id`, ทำ flow เชื่อมต่อด้วย token, เพิ่ม `discord_id_str`, และ deploy

**ตัดสินใจเพราะ** — Vue 3 + TS ให้ type ตรวจสอบตอน build และ SPA ทำให้เปลี่ยนหน้าไม่ต้องโหลดใหม่
การเลือก TS แทน JS ตั้งแต่ต้นทำให้ `any` เป็นสิ่งที่ต้องขออนุญาต — `> ที่มา: diff เพิ่ม tsconfig/types`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Vue 3 `<script setup>`, Pinia, vue-router, axios,
Tailwind, SweetAlert2, Chart.js — stack ที่ยังอยู่ถึงวันนี้ (แม้จะเปลี่ยนดีไซน์หลายรอบ)

**พังแล้วแก้อย่างไร** — ปัญหา timezone ระหว่าง PHP/JS/Postgres ปรากฏชัด
แก้ด้วยการกำหนด `Asia/Bangkok` ให้เป็นค่าเดียวกันทุกชั้น

**เพิ่ม**
- SPA นักเรียน (list/add/edit/profile)
- auth store + role
- deploy frontend

**แก้ไข**
- timezone
- JSON response shape

**สิ่งที่ยาก / ภูมิใจ** — เขียน SPA ใหม่ทั้งตัวทั้งที่ PHP ยังใช้งานอยู่
ต้องเลือกอย่างมีสติว่าจะย้ายอะไรก่อน — เริ่มจากนักเรียนเพราะเป็นข้อมูลที่ใช้บ่อยที่สุด

**Migration:** ไม่มี
**อ้างอิง:** ts commits `b4c12c0..e41808f` (3 commits ใน cut, +899/−34)

---

## [0.9.0] — 2026-05-31 — deploy ทุก component + โมดูลงาน + มือถือ

**บริบท ณ ตอนนั้น** — สี่โปรเจกต์ทำงานแยกกัน แต่ยังไม่มีวิธี deploy พร้อมกัน
และหน้าเว็บยังใช้งานบนมือถือไม่ดี ซึ่งเป็นอุปกรณ์หลักของนักเรียน

**สิ่งที่ทำ** — เพิ่ม `deploy.yml` ให้ทุก component, โมดูลงาน (task) ครบวงจรบนเว็บ,
การเงินบน dashboard, animation, ปุ่มย้อนกลับ, `web domain`, `memory function`,
แก้บั๊ก python tab และอีกหลายจุด — ปิดท้ายด้วย PR #3 ของ backend

**ตัดสินใจเพราะ** — deploy แยกทีละ repo ทำให้เวอร์ชันไม่ตรงกัน (frontend ใหม่ + API เก่า)
จึงเริ่มพยายาม deploy พร้อมกัน — ความพยายามนี้จะกลายเป็น `pull_all.sh` ในอีก 2 วัน

**เทคโนโลยีที่เปลี่ยน/ลอง** — GitHub Actions (`deploy.yml`) ต่อ repo,
responsive layout, animation เบา ๆ ด้วย CSS

**พังแล้วแก้อย่างไร** — `edit bug when build` — build ล้มเพราะ type/import ค้าง
แก้ก่อน merge; บทเรียนว่า CI build ต้องมาก่อน deploy เสมอ

**เพิ่ม**
- deploy pipeline ทุก component
- task module
- finance บน dashboard
- animation + ปุ่มย้อนกลับ

**แก้ไข**
- บั๊ก build
- python tab
- callback login

**สิ่งที่ยาก / ภูมิใจ** — สิ้นเดือนพฤษภาคม 2026 มีระบบครบวงจร: bot, เว็บ 2 ตัว, API
และ deploy ได้ — จาก 4 ไฟล์ในเดือนมีนาคม

**Migration:** ไม่มี
**อ้างอิง:** backend PR #3 · commits `ab8b515` และรอบ deploy/task

---

# ยุคที่ 2 — monorepo, identity, V1 (มิ.ย. 2026)

> ยุคที่ระบบเลิกเป็น "ชุดโปรเจกต์ที่บังเอิญทำงานด้วยกัน" และเริ่มเป็น "ระบบเดียว"
> ราคาที่จ่ายคือ dependency hell ของ submodule และ refactor identity ที่แตะทุกชั้น

---

## [0.10.0] — 2026-06-01 — root repo + submodules + Docker + Redis → Discord

**บริบท ณ ตอนนั้น** — สี่ repo แยกกัน (bot, api, php, ts) แต่ละอันมี CI ของตัวเอง
การ deploy พร้อมกันเป็นเรื่องที่ต้องทำด้วยมือ และเวอร์ชันหลุดจากกันเรื่อย ๆ
นอกจากนี้การแจ้งเตือนจากเว็บไป Discord ยังไม่มีทางไป

**สิ่งที่ทำ** — เกิด repo ที่ห้า: `classroom-management` (root) ที่รวมทุกอย่างด้วย
**git submodule** — commit `b1870d9 feat: setup infrastructure with git submodules`
พร้อม `pull_all.sh`, `.env.example`, readme กลาง, Dockerfile ของแต่ละ component
และ commit `feat: add notify from Backend to Discord with Redis` — backend publish
เข้า Redis channel แล้ว bot มี `cogs/redis_listener.py` คอยฟัง
ปิดท้ายด้วย `make it can run with terminal` และ `add custom message`

**ตัดสินใจเพราะ** — submodule ถูกเลือกเพราะ "ไม่ต้องเขียนประวัติใหม่" — repo ย่อยยังเป็น
repo จริงที่ clone เดี่ยวได้ และ root แค่ชี้ไปที่ commit หนึ่ง
— `> ที่มา: commit message "setup infrastructure with git submodules"`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Docker ครั้งแรกของโปรเจกต์, Docker Compose, Redis pub/sub,
submodule workflow — ทั้งหมดนี้จะถูกแทนที่ในอีก 2 เดือน (v1.3.0 subtree merge)

**พังแล้วแก้อย่างไร** — Redis listener ไม่ส่งข้อความช่วงแรก (`edit redis listener` 4 commits)
สาเหตุคือรูปแบบ payload/channel ไม่ตรงกันระหว่างผู้ส่งกับผู้รับ
— บทเรียน: **สัญญาระหว่าง service ต้องเขียนไว้ที่เดียว ไม่ใช่เดาจากโค้ดอีกฝั่ง**

**เพิ่ม**
- root repo + submodules
- Docker ทุก component
- Redis → Discord notification
- `.env.example` กลาง

**แก้ไข**
- submodule pointer ไม่ตรงกัน
- Redis listener

**สิ่งที่ยาก / ภูมิใจ** — การมี repo เดียวที่ `git clone --recursive` แล้วได้ทั้งระบบ
คือความรู้สึกว่า "นี่คือผลิตภัณฑ์" ไม่ใช่แค่โฟลเดอร์ทดลอง

**Migration:** ไม่มี
**อ้างอิง:** main commits `b1870d9..af54701`
**Component tips ณ วันนั้น:** backend `af032b8` · frontend_ts `f317057` · frontend_php `6517051` · bot `c345dc8`

---

## [0.11.0] — 2026-06-02 — ป้องกันข้อมูลเพื่อน + test suite แรกของ backend

**บริบท ณ ตอนนั้น** — ระบบเริ่มเก็บข้อมูลส่วนตัว (ชื่อ เบอร์ โปรไฟล์) และเริ่มมีคนอื่น
นอกจากเจ้าของใช้ — ความเสี่ยง PII กลายเป็นเรื่องจริง

**สิ่งที่ทำ** — เพิ่มการปกป้องข้อมูลเพื่อน (ไม่ให้เห็นข้อมูลติดต่อของคนอื่นโดยไม่จำเป็น)
ทั้งฝั่ง API และ UI และ commit `Feature: add test case of backend` — **pytest ชุดแรกของโปรเจกต์**

**ตัดสินใจเพราะ** — test ถูกเขียนตอนที่ยังมี endpoint ไม่กี่ตัว เพราะถ้ารอให้ครบจะไม่มีวันเริ่ม
— `> อนุมานจาก diffstat: test file แรกมาพร้อมกับ endpoint student/classroom`

**เทคโนโลยีที่เปลี่ยน/ลอง** — pytest + FastAPI TestClient + Postgres จริง
(แนวทาง integration test ที่ยังใช้ถึงวันนี้)

**พังแล้วแก้อย่างไร** — การซ่อนข้อมูลต้องทำที่ **response model** ไม่ใช่แค่ UI
เพราะ client อ่าน API ตรงได้ — บทเรียนที่กลายเป็นกฎ "declare response_model เสมอ"

**เพิ่ม**
- การปกป้องข้อมูลติดต่อส่วนตัว
- backend test suite

**ความปลอดภัย**
- จำกัดการมองเห็นข้อมูลเพื่อน

**สิ่งที่ยาก / ภูมิใจ** — การเขียน test แรกเจ็บเพราะต้องสร้าง/ล้าง DB ทุกครั้ง
แต่มันคือจุดเริ่มของ CI ที่จะตามมาในอีกหลายเดือน

**Migration:** ไม่มี
**อ้างอิง:** main commits `e009ec9..8facffa`
**Component tips:** backend `6763263` · frontend_ts `64a4124` · frontend_php `6517051` · bot `c345dc8`

---

## [0.12.0] — 2026-06-03 — breadcrumbs, sidebar, migrate_user

**บริบท ณ ตอนนั้น** — หน้าเว็บเริ่มมีหลายชั้น (dashboard → นักเรียน → โปรไฟล์)
ผู้ใช้หลงทาง และระบบยังไม่มีตาราง `users` ที่เป็นของตัวเอง — identity ผูกกับ Discord ตรง ๆ

**สิ่งที่ทำ** — เพิ่ม breadcrumb navigation (2 รอบ) + sidebar + แก้ z-index
และเริ่ม `migrate_user for user system` พร้อม `phase 2: add to support google token`
ฝั่ง backend เพิ่ม `room_router` และตาราง `users` (จาก 15 → 16 ตาราง)

**ตัดสินใจเพราะ** — ต้องมี `users` กลางก่อนจะรองรับผู้ให้บริการ login หลายเจ้า
มิฉะนั้นทุก provider จะต้องมีตารางของตัวเอง — `> อนุมานจาก diff: users table + google token phase`

**เทคโนโลยีที่เปลี่ยน/ลอง** — โครง navigation ใหม่ (sidebar + breadcrumb) ที่ยังอยู่ถึงปัจจุบัน
และการเตรียม OAuth หลายเจ้า

**พังแล้วแก้อย่างไร** — z-index ของ sidebar ทับ modal — แก้ด้วยการกำหนด layer ให้ชัด
(`Fix: Z-index Adjust`)

**เพิ่ม**
- breadcrumb + sidebar
- ตาราง `users`
- room router
- google token phase 2

**แก้ไข**
- z-index

**สิ่งที่ยาก / ภูมิใจ** — การ migrate identity จาก "Discord ID คือตัวตน" เป็น "users คือตัวตน"
เป็น refactor ที่ต้องทำโดยไม่ทำให้คนที่ login อยู่หลุด

**Migration:** เพิ่มตาราง `users` (ยังไม่มี migration runner — DDL อยู่ใน init_db)
**อ้างอิง:** main commits `96fdaeb..6e0c0fe`
**Component tips:** backend `c622952` · frontend_ts `3a03589` · frontend_php `6517051` · bot `c6e8895`

---

## [0.13.0] — 2026-06-07 — Google Login สมบูรณ์ + สงคราม user_id และ room_id

**บริบท ณ ตอนนั้น** — Discord login ใช้ได้ แต่ไม่ใช่ทุกคนมี Discord; ครูจำนวนมากมี Google
และระบบยังใช้ `server_id` (ห้องใน Discord) เป็นกุญแจหลัก ซึ่งผิดความหมายของ "ห้องเรียน"

**สิ่งที่ทำ** — Google Login ครบวงจร (OAuth callback, ผูกบัญชี, หน้า `GoogleCallback`,
`DiscordCallback`), refactor frontend ให้ใช้ `room_id`, และแก้ปัญหา `user_id`
ไปกลับระหว่าง string กับ int หลายรอบ (`change user_id to string` 4 commits →
`change to int before keep in db` 4 commits) พร้อม `phase 4: refactor student/classroom/finance`

**ตัดสินใจเพราะ** — Discord ID เป็นตัวเลข 64-bit ที่ใหญ่กว่า int32 และบาง library
ส่งมาเป็น string — ต้องเลือกจุดเดียวที่แปลง และเก็บเป็นชนิดเดียวตลอด
— `> ที่มา: commit subjects ระหว่าง 2026-06-07`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Google OAuth, JWT แบบมี `user_id` claim,
การแยก identity provider ออกจากตัวผู้ใช้

**พังแล้วแก้อย่างไร** — ปัญหา `user_id` int/string ทำให้ login บางคนได้ บางคนไม่ได้
แก้โดย normalize เป็น string ที่ขอบระบบ แล้วแปลงเป็น int ตอนเก็บ
— เป็น bug ที่กินเวลาเป็นวัน และกลายเป็นบทเรียนใน docs/skills.md

**เพิ่ม**
- Google Login
- `room_id` ทั้ง frontend
- refactor student/classroom/finance (phase 4)

**แก้ไข**
- user_id ชนิดข้อมูล
- path/link/variable เก่าที่ค้าง

**สิ่งที่ยาก / ภูมิใจ** — การเปลี่ยน "ห้อง" จากแนวคิด Discord เป็นแนวคิดห้องเรียน
แตะทุกหน้าจอและทุก endpoint — แต่หลังรอบนี้ ระบบพูดภาษาเดียวกันทั้งระบบ

**Migration:** ตาราง `users` ใช้งานเต็มรูปแบบ; เพิ่ม `room_id` ใน flow
**อ้างอิง:** backend `8e1d920..7fde8b9` · frontend `0daa897`
**Component tips:** backend `7fde8b9` · frontend_ts `0daa897` · frontend_php `6517051` · bot `c6e8895`

---

## [0.14.0] — 2026-06-21 — Lobby, สร้างห้อง, เข้าห้องด้วยรหัส

**บริบท ณ ตอนนั้น** — ผู้ใช้ใหม่ต้องถูกเพิ่มเข้าห้องโดยแอดมินเท่านั้น ระบบยังไม่มีแนวคิด
"ห้องหลายห้องที่ผู้ใช้เลือกเองได้" อย่างจริงจัง

**สิ่งที่ทำ** — เพิ่มหน้า `Lobby` (รายการห้อง), สร้างห้องใหม่, เข้าห้องด้วย `room_code`,
แสดงรหัสห้อง, กำหนดบทบาท `president`, และ refactor ทั้งระบบให้ยึด `user_id` + `room_id`
(`Refactor all function to user_id and room_id base`) รวมถึงแก้บั๊ก join room
และ "get user in room"

**ตัดสินใจเพราะ** — `room_code` สั้นและจำง่าย ทำให้แชร์ห้องได้โดยไม่ต้องมีสิทธิ์แอดมิน
— `> อนุมานจาก diff: เพิ่มคอลัมน์ room_code และหน้าแสดงรหัส`

**เทคโนโลยีที่เปลี่ยน/ลอง** — แนวคิด multi-tenant ระดับห้อง (room-scoped data)
ที่ทุก query ต้องกรองด้วย `room_id`

**พังแล้วแก้อย่างไร** — join room ล้มเพราะ role ไม่ตรง (`edit role to president`),
และ "classrooms" vs "classroom" ใน API path ทำให้ 404 — แก้ทั้งสองจุดในรอบเดียว

**เพิ่ม**
- Lobby
- สร้าง/เข้าห้อง
- room_code
- บทบาท president

**แก้ไข**
- บั๊ก join room
- ชื่อ path/role ไม่ตรงกัน

**สิ่งที่ยาก / ภูมิใจ** — ระบบกลายเป็น multi-room จริง ๆ — ห้องหนึ่งไม่เห็นข้อมูลอีกห้อง
และผู้ใช้สลับห้องได้เอง นี่คือจุดที่โปรเจกต์เริ่มรองรับ "ทั้งโรงเรียน" ไม่ใช่ "ห้องเดียว"

**Migration:** เพิ่ม `room_code`; เปลี่ยนความหมายของ `room_id`
**อ้างอิง:** backend `3e2558c..7f9f5db` · frontend `033a3e2`
**Component tips:** backend `89f3adc` · frontend_ts `033a3e2` · frontend_php `6517051` · bot `fe2e36b`

---

## [0.15.0] — 2026-06-22 — Sync Profile, Onboarding, bot กลายเป็นลูกค้าเว็บ

**บริบท ณ ตอนนั้น** — ผู้ใช้ใหม่เข้ามาแล้วไม่มีชื่อที่ถูกต้อง (ได้ชื่อจาก Google/Discord
ซึ่งไม่ใช่ชื่อที่เพื่อนเรียก) และ bot ยังมีฟังก์ชัน UI ที่ซ้ำกับเว็บ

**สิ่งที่ทำ** — เพิ่มหน้า `Onboarding` ให้กรอกชื่อเล่น/คำนำหน้า/เบอร์เมื่อสมัครครั้งแรก,
`Sync Profile` ให้ดึงข้อมูลจาก provider มาช่วยกรอก, และ PR #7 `refactor/web-centric`
ทำให้ bot เปลี่ยนเป็น "ทางลัดไปเว็บ" ไม่ใช่ที่ทำงานหลัก

**ตัดสินใจเพราะ** — การกรอกข้อมูลซ้ำคือสาเหตุอันดับหนึ่งที่ผู้ใช้ทิ้งระบบ
จึงดึงชื่อจาก provider มาเป็นค่าเริ่มต้น แล้วให้แก้เฉพาะที่ไม่ตรง
— `> ที่มา: commit "Feature: add name form when new account" + "Add Sync Profile"`

**เทคโนโลยีที่เปลี่ยน/ลอง** — onboarding guard ใน router (ยังอยู่ถึงวันนี้),
การแยก "ข้อมูลจาก provider" กับ "ข้อมูลที่ผู้ใช้ยืนยัน"

**พังแล้วแก้อย่างไร** — "name did not show" และ "cant click sync" — ปัญหา state
ระหว่าง onboarding กับ auth store แก้ด้วยการโหลดโปรไฟล์ก่อนเข้า guard

**เพิ่ม**
- Onboarding
- Sync Profile
- web-centric bot

**แก้ไข**
- ชื่อไม่แสดง
- ปุ่ม sync กดไม่ได้

**สิ่งที่ยาก / ภูมิใจ** — การยอมรับว่า bot ไม่ควรเป็น UI หลัก คือการตัดของที่ตัวเองสร้าง
— แต่ทำให้ bot เบาลงและเว็บเป็นแหล่งความจริงเดียว

**Migration:** เพิ่มฟิลด์โปรไฟล์ (prefix, nickname, phone)
**อ้างอิง:** backend PR #7 · frontend `bc5aa1b`
**Component tips:** backend `5c3f6cb` · frontend_ts `bc5aa1b` · frontend_php `6517051` · bot `fe2e36b`

---

## [0.16.0] — 2026-06-23 — PR แรกของ root repo

**บริบท ณ ตอนนั้น** — งานทั้งหมดเกิดขึ้นใน repo ย่อย แต่ root repo ยังไม่มี PR flow
ของตัวเอง — การอัปเดต pointer ของ submodule ทำด้วยมือ

**สิ่งที่ทำ** — PR #1 ของ root (`refactor/web-centric`) รวมการอัปเดต submodule pointer
ให้ชี้ commit ล่าสุดของทุก component พร้อม `🚀 chore: sync all submodules to latest staging`
และแก้ `pull_all.sh`

**ตัดสินใจเพราะ** — root repo ควรเป็นที่เดียวที่บอกว่า "ระบบทั้งระบบอยู่ที่ commit ไหน"
— `> อนุมานจาก diff: PR นี้แตะเฉพาะ submodule pointer + script`

**พังแล้วแก้อย่างไร** — submodule pointer ชี้ commit ที่ยังไม่ push ขึ้น remote
ทำให้ `git clone --recursive` ล้ม — แก้โดย push component ก่อนแล้วค่อยอัปเดต pointer

**เพิ่ม**
- PR flow ของ root
- sync submodule อัตโนมัติ

**สิ่งที่ยาก / ภูมิใจ** — เป็นครั้งแรกที่ "ทั้งระบบ" ถูก merge เป็นหน่วยเดียว
แม้ยังเป็น submodule อยู่ก็ตาม

**Migration:** ไม่มี
**อ้างอิง:** PR #1 · commits `5c3f6cb..a79fd94`
**Component tips:** backend `5c3f6cb` · frontend_ts `bc5aa1b` · frontend_php `6517051` · bot `fe2e36b`

---

## [1.0.0] — 2026-06-30 — V1: ระบบพร้อมใช้จริง

**บริบท ณ ตอนนั้น** — ผ่านมา 3 เดือนครึ่ง มี 4 component, ระบบห้อง, login 2 เจ้า,
การเงิน, งาน, โน้ต, ตารางสอน — แต่ยังขาดสิ่งที่ทำให้ "ใช้งานจริงจบวงจร" เช่น การ export ข้อมูล
และอัตลักษณ์ของผลิตภัณฑ์ (โลโก้)

**สิ่งที่ทำ** — PR #2 `staging` รวม: **Export Students** (หน้าใหม่ + `vuedraggable` สำหรับจัดลำดับคอลัมน์),
โลโก้, แก้บั๊กหลายจุด และอัปเดต `docker-compose.yml`

**ตัดสินใจเพราะ** — การ export คือสิ่งที่โรงเรียนต้องการก่อนใช้งานจริง (ส่งรายชื่อให้ฝ่ายทะเบียน,
สำรองข้อมูล) และเป็น feature แรกที่ผู้ใช้ภายนอกขอ — `> อนุมานจาก diff: ExportStudent.vue + dependency vuedraggable`

**เทคโนโลยีที่เปลี่ยน/ลอง** — `vuedraggable` สำหรับเลือก/จัดลำดับคอลัมน์ export

**พังแล้วแก้อย่างไร** — build ล้มเพราะ dependency ใหม่ + type ของ export — แก้ก่อน merge
(`Fix: edit bug` 2 commits)

**เพิ่ม**
- Export นักเรียน
- โลโก้ผลิตภัณฑ์

**แก้ไข**
- บั๊กหน้าเว็บหลายจุด
- docker-compose

**สิ่งที่ยาก / ภูมิใจ** — การประกาศ 1.0.0 ไม่ได้หมายความว่าโค้ดสมบูรณ์
แต่หมายความว่า **มีคนใช้จริงและเราพร้อมรับผิดชอบ** — นี่คือจุดที่โปรเจกต์ส่วนตัว
กลายเป็นระบบของโรงเรียน

**Migration:** ไม่มี
**อ้างอิง:** PR #2 · commits `a79fd94..dc411ef`
**Component tips:** backend `02a2fa5` · frontend_ts `35484c5` · frontend_php `6517051` · bot `68eb30f`

---

# ยุคที่ 3 — สิทธิ์, การรวมประวัติ, bot ใหม่ (ก.ค. 2026)

> เดือนนี้คือเดือนที่โปรเจกต์ "โตเป็นระบบ" — มี RBAC, รวม 4 ประวัติเข้า monorepo,
> และยอมถอดของที่ตัวเองสร้าง (PHP, bot UI) ออก

---

## [1.1.0] — 2026-07-14 — เก็บเงินรายคน + ซิงก์ submodule

**บริบท ณ ตอนนั้น** — การเงินมีรายการรับ–จ่ายแล้ว แต่การเก็บเงินค่ากิจกรรมยังต้องจดแยก
และอีกปัญหาที่เจ็บเงียบ ๆ: submodule pointer ใน root repo ชี้ commit เก่า ทำให้ deploy
ได้โค้ดที่ไม่มีฟีเจอร์ล่าสุด

**สิ่งที่ทำ** — เพิ่มการเก็บเงินรายคน (collection per person) ฝั่ง backend + frontend
(backend PR #9, frontend PR #6) และซิงก์ submodule pointer ให้ตรงกับ remote main

**ตัดสินใจเพราะ** — การเก็บเงินต้องตอบว่า "ใครจ่ายแล้ว ใครยังไม่จ่าย" ที่ระดับบุคคล
ไม่ใช่ยอดรวม — `> อนุมานจาก diff: fee_collections + student_payments`

**เทคโนโลยีที่เปลี่ยน/ลอง** — เริ่มเห็นปัญหา submodule ชัดขึ้น: การอัปเดต pointer
เป็นงาน manual ที่ลืมได้ง่าย — เมล็ดของ decision ที่จะนำไปสู่ subtree merge ใน v1.3.0

**พังแล้วแก้อย่างไร** — `update submodule refs to latest main` ต้องรันซ้ำ
เพราะ pointer ถูกแก้ระหว่างที่ component ยังมี commit ใหม่เข้ามา

**เพิ่ม**
- การเก็บเงินรายคน

**แก้ไข**
- submodule pointer ค้าง

**สิ่งที่ยาก / ภูมิใจ** — ระบบการเงินเริ่มตอบคำถามจริงของห้องเรียนได้ ไม่ใช่แค่บันทึกรายรับรายจ่าย

**Migration:** เพิ่มตาราง/คอลัมน์การเก็บเงิน (DDL ใน init_db)
**อ้างอิง:** backend PR #9 · frontend PR #6 · main `da859a5`
**Component tips:** backend `66511d7` · frontend_ts `995a117` · frontend_php `6517051` · bot `68eb30f`

---

## [1.1.1] — 2026-07-17 — แก้โปรไฟล์ไม่ได้

**บริบท ณ ตอนนั้น** — ผู้ใช้แก้โปรไฟล์ไม่ได้หลังเปลี่ยน schema เป็น Optional
— ฟอร์มส่งค่าบางฟิลด์ว่าง แล้ว API reject

**สิ่งที่ทำ** — แก้การอัปเดตโปรไฟล์ให้รองรับ Optional จริง (`Fix: cant edit profile` 3 รอบ)
ปรับ `docker-compose.yml` และ `.env` ให้ตรงกับ environment

**ตัดสินใจเพราะ** — ทางแรกคือบังคับกรอกทุกช่อง (ง่ายแต่ผู้ใช้แย่) — เลือกแก้ที่ schema
ให้ optional และให้ service ใช้ `exclude_unset` — `> อนุมานจาก diff: PATCH update แบบ exclude_unset`

**พังแล้วแก้อย่างไร** — แก้สามรอบเพราะแต่ละรอบเจอฟิลด์ถัดไปที่ยัง required อยู่
— บทเรียน: **PATCH ต้องแยก "ไม่ส่งมา" กับ "ส่งค่าว่าง" ให้ชัด**

**แก้ไข**
- แก้โปรไฟล์ไม่ได้
- docker-compose / .env ไม่ตรงกัน

**สิ่งที่ยาก / ภูมิใจ** — bug เล็กที่กระทบทุกคน และใช้เวลาเป็นวัน — แต่หลังแก้แล้ว
โปรไฟล์กลายเป็นสิ่งที่แก้ได้ตลอด ซึ่งจำเป็นมากสำหรับข้อมูลที่เปลี่ยนทุกปีการศึกษา

**Migration:** ไม่มี
**อ้างอิง:** backend PR #10–#11 · frontend PR #11 · main `b18be80`
**Component tips:** backend `3e68447` · frontend_ts `8a325e7` · frontend_php `6517051` · bot `68eb30f`

---

## [1.2.0] — 2026-07-18 — RBAC: สิทธิ์แบบละเอียด

**บริบท ณ ตอนนั้น** — ทุกคนในห้องเห็นทุกอย่าง หรือไม่ก็ต้องให้แอดมินทำ
ไม่มีแนวคิด "ประธานห้องทำได้ แต่กรรมการทำไม่ได้"

**สิ่งที่ทำ** — เพิ่ม Permissions Function: `core/rbac.py` + `require_permission`
โดยเก็บ permission เป็น JSONB array บนแถว `students` ของห้องนั้น
มี `SUPER_ADMIN_ID` และ `is_admin` ที่ข้ามการตรวจ

**ตัดสินใจเพราะ** — เก็บ permission บน membership (students row) ไม่ใช่บน user
เพราะคนเดียวกันเป็นประธานห้องหนึ่งแต่เป็นสมาชิกธรรมดาอีกห้อง — สิทธิ์ต้องผูกกับ "ห้อง"
— `> อนุมานจาก diff: require_permission(conn, room_id, user_id, permission)`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Permission-based แทน Role-based ล้วน
(บทบาทเป็นเพียง preset ของ permission)

**พังแล้วแก้อย่างไร** — endpoint เก่าบางตัวยังไม่เรียก `require_permission`
ทำให้ bypass ได้ — แก้ทีละ router

**เพิ่ม**
- `require_permission`
- permission ต่อห้อง
- admin bypass

**ความปลอดภัย**
- ตรวจสิทธิ์ระดับ endpoint

**สิ่งที่ยาก / ภูมิใจ** — RBAC เป็นรากของทุกอย่างหลังจากนี้ (กิจกรรม การเงิน เอกสาร)
การวางให้ถูกตั้งแต่แรกทำให้เพิ่ม permission ใหม่ได้โดยไม่ต้องรื้อ

**Migration:** เพิ่มคอลัมน์ `permissions` JSONB
**อ้างอิง:** backend PR #12 · main `0ade717`
**Component tips:** backend `3e68447` · frontend_ts `8a325e7` · frontend_php `6517051` · bot `68eb30f`

---

## [1.2.1] — 2026-07-26 — Refactor log service + กฎของ AI agent เกิดขึ้น

**บริบท ณ ตอนนั้น** — audit log ถูกเขียนกระจายทุก service ด้วยรูปแบบต่างกัน
และเริ่มใช้ AI agent (Cursor/Claude) ช่วยเขียนโค้ดมากขึ้น จึงต้องมีกฎกลาง

**สิ่งที่ทำ** — แยก `core/logger.py` (`AuditLogger`) ให้เป็นที่เดียว, ให้ bot
ไม่เขียน log ซ้ำซ้อน, แก้ router/database ให้ใช้ logger ใหม่, และเพิ่ม
`.cursor/rules/*.mdc` (backend, frontend, discord-bot, website-php) +
`Refactor: logs services` ครบวงจร พร้อม commit `Backward one step` เมื่อพบว่าการ refactor
ไปไกลเกิน

**ตัดสินใจเพราะ** — log ที่รูปแบบไม่ตรงกันทำให้ตรวจย้อนหลังไม่ได้
และกฎ agent ต้องอยู่ใน repo ไม่ใช่ในหัวคน — `> ที่มา: ไฟล์ .cursor/rules ถูกเพิ่มในรอบนี้`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Cursor rules → ต่อมากลายเป็น `docs/rules/*.md` ที่ยังใช้อยู่

**พังแล้วแก้อย่างไร** — `Backward one step` คือการยอมถอยเมื่อ refactor ทำให้ behavior เปลี่ยน
— เป็นตัวอย่างที่ดีของการไม่ฝืนต่อ

**เปลี่ยน**
- โครง audit logging
- กฎการเขียนโค้ดสำหรับ agent

**แก้ไข**
- log ซ้ำเมื่อ action มาจาก bot

**สิ่งที่ยาก / ภูมิใจ** — การเขียนกฎให้ AI ทำตามคือการเขียนกฎให้ตัวเองทำตามด้วย
— `docs/rules` กลายเป็นเอกสารที่ทำให้โค้ดทั้ง repo พูดภาษาเดียวกัน

**Migration:** ไม่มี
**อ้างอิง:** commits `132bb59..93eee76` · main `93eee76`
**Component tips:** backend `9d827c9` · frontend_ts `5e91fb1` · frontend_php `6517051` · bot `68eb30f`

---

## [1.3.0] — 2026-07-28 — รวม 4 repo เป็น monorepo (subtree)

**บริบท ณ ตอนนั้น** — submodule ทำให้ PR ข้าม component เป็นไปไม่ได้
การอัปเดต pointer ลืมบ่อย และ `git clone` ต้อง `--recursive` ทุกครั้ง

**สิ่งที่ทำ** — ใช้ `git subtree` นำประวัติของทั้ง 4 repo เข้ามาเป็นโฟลเดอร์
`backend/`, `frontend/`, `bot_discord/` (และ `frontend_php/` ก่อน archive)
โดย **เก็บประวัติเดิมครบ** — import commit `3bdc233` (backend 114 commits),
`1f5a670` (frontend_ts 117), `474330e` (bot 32), `0042242` (frontend_php 41)
ลบ `.gitmodules` และปรับ Docker structure ให้ build จาก root เดียว

**ตัดสินใจเพราะ** — subtree ต่างจาก "copy ไฟล์" ตรงที่ commit เก่ายังตรวจย้อนได้
ซึ่งสำคัญมากเพราะนี่คือประวัติที่ต้องการ — `> ที่มา: import commits ทั้ง 4 อยู่ใน history`

**เทคโนโลยีที่เปลี่ยน/ลอง** — git subtree, Docker context เดียว, `.env` กลางที่ root

**พังแล้วแก้อย่างไร** — path ใน Dockerfile/CI อ้างโฟลเดอร์เก่า — แก้ทั้งชุด
(`Refactor: Edit Docker Structure`)

**เปลี่ยน**
- 4 repo → 1 monorepo
- Docker build context
- CI ทั้งหมด

**สิ่งที่ยาก / ภูมิใจ** — การรวมประวัติ 304 commits โดยไม่ทำให้หายไปแม้ตัวเดียว
คือเหตุที่ CHANGELOG นี้เขียนได้ละเอียดถึงเดือนมีนาคม

**Migration:** ไม่มี
**อ้างอิง:** main `a7c721c..fea3afe`

---

## [1.3.1] — 2026-07-29 — ลอง Adminer/Bytebase, replicas, DB memory

**บริบท ณ ตอนนั้น** — หลังรวม monorepo ต้องดูแล DB ด้วยตัวเองมากขึ้น และเครื่อง 12 GB
เริ่มตึงเมื่อ backend รัน 3 replicas

**สิ่งที่ทำ** — เพิ่ม Adminer และ Bytebase เข้า infra, ปรับ replicas 3 → 1,
แก้ "Backend database don't give memory back" (connection pool ค้าง),
แก้ finance dashboard ที่ใหญ่เกินจนพัง, archive `frontend_php` ไป branch
`archive/frontend_php` และลบออกจาก main, rename frontend, ปรับ readme/docker naming

**ตัดสินใจเพราะ** — Bytebase ถูกถอดออก **วันเดียวกัน** เพราะกินทรัพยากรเกินประโยชน์
เมื่อเทียบกับ Adminer ที่เบากว่า — `> ที่มา: commits "Feature: Add Bytebase" และ "Feature: Remove Bytebase"`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Adminer (เก็บ), Bytebase (ถอด), replicas tuning, pool tuning

**พังแล้วแก้อย่างไร** — memory ไม่คืนเพราะ pool ไม่ถูกปิดเมื่อ idle — แก้ด้วยการตั้งค่า pool
และลด replicas

**เพิ่ม**
- Adminer
- archive branch ของ PHP

**เปลี่ยน**
- replicas 3 → 1
- ชื่อ frontend

**ถอด**
- Bytebase

**สิ่งที่ยาก / ภูมิใจ** — การกล้าถอดสิ่งที่เพิ่งใส่เข้าไปในวันเดียว คือการเรียนรู้ที่ถูกที่สุด
— และการ archive PHP อย่างมีศักดิ์ศรี (เก็บ branch ไว้) ทำให้ย้อนดูได้ตลอด

**Migration:** ไม่มี
**อ้างอิง:** commits `65fb274..69a2365` · main `69a2365`

---

## [1.4.0] — 2026-07-30 — bot เป็น notification-only + Discord sync

**บริบท ณ ตอนนั้น** — bot ยังมีคำสั่งแอดมินซ้ำกับเว็บ ทำให้ต้องแก้สองที่ทุกครั้ง
และผู้ใช้ยังผูกบัญชี Discord กับระบบไม่ได้ด้วยตัวเอง

**สิ่งที่ทำ** — `refactor: remove admin commands and migrate to notification-only bot`
— bot เหลือหน้าที่แจ้งเตือนและลิงก์ไปเว็บ
เพิ่ม endpoint **Discord sync ผูกบัญชีด้วย `room_code`**, หน้า/โมดัล "คู่มือเชื่อมต่อ Discord"
(glassmorphism), ปุ่ม invite bot ที่ URL มาจาก env, และเพิ่ม db network ใน infra
พร้อมอัปเดตกฎ `.cursor/rules` ให้ตรงสถาปัตยกรรมใหม่

**ตัดสินใจเพราะ** — bot ไม่ควรเป็น UI คู่ขนาน — ทุกฟีเจอร์ต้องมีเจ้าของเดียว
และ bot ควรทำสิ่งที่เว็บทำไม่ได้: อยู่ในช่องแชทที่คนเห็นตลอดเวลา
— `> ที่มา: ชื่อ commit refactor: remove admin commands and migrate to notification-only bot`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Notification-only bot, room_code-based account linking,
glassmorphism UI

**พังแล้วแก้อย่างไร** — `add missing closing div tag` ทำให้หน้าคู่มือเพี้ยน — แก้ทันที

**เปลี่ยน**
- bot เป็น notification-only
- คู่มือเชื่อมต่อ Discord

**เพิ่ม**
- Discord sync endpoint
- ปุ่ม invite bot

**สิ่งที่ยาก / ภูมิใจ** — การลดขอบเขตของ bot ทำให้มันเชื่อถือได้ขึ้นมาก
และ sync ด้วย `room_code` ทำให้ผู้ใช้ผูกบัญชีเองได้โดยไม่ต้องรอแอดมิน

**Migration:** เพิ่มการผูก `discord_id` กับ user ผ่าน room_code
**อ้างอิง:** commits `e675af9..e0042dd` · main `e0042dd`

---

# ยุคที่ 4 — บัญชีคู่, กิจกรรม, consent (ส.ค. 2026)

> สิงหาคมคือเดือนที่ระบบเปลี่ยนจาก "จัดการห้อง" เป็น "บริหารห้อง"
> มีการเงินที่ตรวจสอบได้ มีกิจกรรมที่จัดคนได้ และมีโมเดลความเป็นส่วนตัวที่แท้จริง

---

## [1.5.0] — 2026-08-02 — เขียน test ใหม่ทั้งชุด + Roadmap + Onboarding

**บริบท ณ ตอนนั้น** — test suite แรกจาก v0.11.0 ล้าสมัยและผ่านแบบไม่จริงจัง
ขณะเดียวกันผู้ใช้ใหม่ยังไม่รู้ว่าต้องกรอกอะไร และทีมยังไม่มีแผนที่ว่ากำลังจะไปไหน

**สิ่งที่ทำ** — PR #5 `test/rewrite-test-suite` เขียน test ใหม่ทั้งชุด (auth, onboarding, profile),
PR #6 เพิ่มหน้า **Roadmap** + org chart ของห้อง, PR #7 เพิ่มข้อมูล Onboarding
(ฟิลด์โปรไฟล์ครบขึ้น, ที่อยู่ไทย autocomplete ด้วย `thailand-address`, guard การ onboard)
พร้อมเริ่ม `docs/skills.md` เป็นคลังบทเรียน และเพิ่มกฎ testing ลง `.cursor/rules/testing.mdc`

**ตัดสินใจเพราะ** — test ที่เขียนใหม่ต้องพิสูจน์ behavior จริง (ยิง HTTP + ตรวจ DB)
ไม่ใช่ mock หมด — และบทเรียนที่เจอระหว่างเขียนต้องถูกเก็บไว้ ไม่ใช่หายไปกับ session
— `> ที่มา: commits docs: add ... skills หลายรายการในรอบนี้`

**เทคโนโลยีที่เปลี่ยน/ลอง** — `thailand-address` autocomplete, onboarding guard,
skills.md ใน system prompt

**พังแล้วแก้อย่างไร** — onboarding form มีฟิลด์ required ไม่ตรงกับ backend หลายรอบ
แก้ทีละชุด (`onboarding form dynamic required fields`, `expanded profile fields`, `refactor`)

**เพิ่ม**
- test suite ใหม่
- Roadmap + org chart
- Onboarding ครบฟิลด์
- ที่อยู่ไทย autocomplete

**แก้ไข**
- guard การ onboard
- ฟิลด์โปรไฟล์

**สิ่งที่ยาก / ภูมิใจ** — การเขียน test ใหม่ทั้งชุดทั้งที่โค้ดยังเดินอยู่
คือการวางรากให้ทุกอย่างหลังจากนี้ — CI ในเดือนกันยายนจะยืนบนชุดนี้

**Migration:** ไม่มี
**อ้างอิง:** PR #5–#7 · main `dee4bbe`

---

## [1.6.0] — 2026-08-04 — งานเรียงตามความสำคัญ + Trans Export + เก็บหนี้ 9 จุด

**บริบท ณ ตอนนั้น** — หน้างานแสดงตามลำดับที่ insert ทำให้งานด่วนจมอยู่ล่าง
และมี bug การเงินสะสม 9 ตัวที่ยังไม่มีใครเก็บ

**สิ่งที่ทำ** — PR #8: เรียงงานตามสถานะ + กำหนดส่ง, badge จำนวนงานแต่ละแท็บ
PR #9: **Trans Export** (export รายการเงิน), แก้ finance bug 9 ตัว,
ถอดโมดูล maintenance ที่ไม่ได้ใช้, harden RBAC/auth, เพิ่ม `CLAUDE.md` 167 บรรทัด
และย้ายกฎจาก `.cursor/rules/` ไป `docs/rules/`

**ตัดสินใจเพราะ** — งานที่ยังไม่เสร็จต้องอยู่บนสุดเสมอ เพราะนั่นคือสิ่งที่ต้องทำต่อ
ไม่ใช่สิ่งที่เพิ่งสร้าง — `> ที่มา: PR #8 body`

**เทคโนโลยีที่เปลี่ยน/ลอง** — เริ่มมี `CLAUDE.md` เป็นแผนที่โปรเจกต์สำหรับ agent
และแยก rules ออกจาก tool-specific (Cursor) เป็น docs กลาง

**พังแล้วแก้อย่างไร** — `Fixs: Tasks not show` และ setup_room `updated_at` bug
จาก RBAC test — แก้พร้อมเพิ่ม regression test

**เพิ่ม**
- Task sorting + counts
- Trans Export
- CLAUDE.md + docs/rules

**แก้ไข**
- finance 9 bugs
- RBAC/auth

**ถอด**
- maintenance module

**ความปลอดภัย**
- harden RBAC

**สิ่งที่ยาก / ภูมิใจ** — การเก็บ bug การเงิน 9 ตัวในรอบเดียวโดยไม่ทำให้ยอดเพี้ยน
ต้องอาศัย test ที่เพิ่งเขียนใน v1.5.0 — คุ้มค่าทันที

**Migration:** ไม่มี — ลบ DDL ของ maintenance ออกจาก init_db
**อ้างอิง:** PR #8–#9 · main `6cf37a5`

---

## [1.7.0] — 2026-08-05 — บัญชีคู่ (double-entry) — refactor การเงินครั้งใหญ่ที่สุด

**บริบท ณ ตอนนั้น** — ระบบการเงินเป็น single-entry: เก็บรายการรับ/จ่ายและยอดคงเหลือ
แต่ตอบไม่ได้ว่า "เงินก้อนนี้มาจากไหน ไปเข้าบัญชีไหน" และกระทบยอดกับความจริงไม่ได้

**สิ่งที่ทำ** — PR #10 `refactor/finance_double_entry` แบ่ง 4 phase:
1. **Phase 1–2:** สร้างตาราง ledger/journal ใหม่ + สคริปต์ migrate
   (`migrate_phase2_ledgers.py` 124 บรรทัด)
2. **Phase 3:** refactor service ให้ทุกธุรกรรมเขียน debit/credit สองข้าง
3. **Phase 4:** data migration + opening balance
   (`migrate_phase2_5_opening_balance.py` 165 บรรทัด)
เพิ่ม `CUTOFF_DATE` เพื่อแยกรายการเก่า (legacy) กับใหม่ (double-entry)

**ตัดสินใจเพราะ** — ทางเลือกคือ "เขียนใหม่ทั้งหมด" หรือ "อยู่คู่กันชั่วคราวแล้วย้ายทีละช่วง"
— เลือกทางที่สองด้วย `CUTOFF_DATE` เพราะโรงเรียนยังต้องใช้งานทุกวัน
และข้อมูลเก่าต้องไม่หาย — `> ที่มา: ชื่อ phase + สคริปต์ migration`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Double-entry ledger, journal, opening balance,
cutoff-based migration, idempotent scripts

**พังแล้วแก้อย่างไร** — ยอดยกมาต้องตรงกับยอด legacy เป๊ะ — ใช้สคริปต์ reconcile
ตรวจซ้ำหลายรอบก่อนใช้จริง

**เพิ่ม**
- ตาราง ledger/journal
- สคริปต์ migration + opening balance
- CUTOFF_DATE

**เปลี่ยน**
- การเงินทั้งระบบเป็น double-entry

**Migration:** ✅ ครั้งแรกที่มีสคริปต์ migrate ข้อมูลจริง (ยังไม่ใช่ migration runner)
**อ้างอิง:** PR #10 · main `ce682b9`

---

## [1.7.1] — 2026-08-06 — เก็บภาษาไทยทั้งระบบ + แก้ Redis + กฎ git ของ agent

**บริบท ณ ตอนนั้น** — หลัง double-entry มี bug UI/ข้อความค้างเป็นอังกฤษจำนวนมาก
และ Redis pub/sub ระหว่าง backend กับ bot ยังไม่ทำงาน

**สิ่งที่ทำ** — PR #11 Thai export/prefix/date, PR #12 **แก้ Redis pub/sub**
(สาเหตุ: `docker-compose.app.yml` override `REDIS_URL` ให้เฉพาะ backend —
 bot ตกไปใช้ default `staging_infra_redis` คนละ instance) + เพิ่ม endpoint
ส่งข้อความจากเว็บไป Discord, PR #13–#14 เพิ่มกฎ Git workflow ใน `docs/system_prompt.md`
(ต้อง fetch/pull ก่อนเริ่มงาน, สร้าง branch, commit+push, เสนอ PR)
พร้อมเก็บกวาด `audit.py`/`utils.py` ที่ซ้ำซ้อน

**ตัดสินใจเพราะ** — Redis bug เป็นตัวอย่างของ "config drift" — ค่า default ฝังในโค้ด
กลายเป็นกับดักเมื่อ compose override ไม่ครบ — `> ที่มา: PR #12 body ระบุ root cause ตรง`

**พังแล้วแก้อย่างไร** — ใช้เวลาไล่หาสาเหตุเพราะทั้งสองฝั่ง "ทำงานปกติ" แยกกัน
— แก้โดยให้ bot ใช้ `REDIS_URL` เดียวกับ backend

**แก้ไข**
- Redis pub/sub คนละ instance
- ภาษาไทยทั้ง UI (role labels, dates, Swal, export)
- RBAC ในหน้า tasks/schedule

**เพิ่ม**
- endpoint web → Discord message
- กฎ git workflow ของ agent

**สิ่งที่ยาก / ภูมิใจ** — bug ที่ cause อยู่ที่ config ไม่ใช่โค้ด — บทเรียนที่ถูกบันทึกใน docs/skills.md

**Migration:** ไม่มี
**อ้างอิง:** PR #11–#14 · main `3b8c486`

---

## [1.8.0] — 2026-08-07 — หน้า "ประกาศเข้า Discord" และการไล่ล่า 404

**บริบท ณ ตอนนั้น** — backend มี endpoint `POST /classroom/{room_id}/messages` แล้ว
แต่ยังไม่มีหน้าเว็บ และ bot เรียก `GET /classroom/{server_id}?target_type=server` แล้วได้ 404
ทำให้ประกาศไม่ไปถึง Discord

**สิ่งที่ทำ** — PR #15 หน้าเว็บส่งประกาศ (frontend ล้วน), PR #16–#19 ไล่บั๊ก 404 เป็นชุด:
- #16 ให้ bot fetch room data ผ่าน target_type=server
- #17 ย้าย column-switch เข้า SQL ของ `get_room_data` ตรง ๆ
- #18 เขียน docs+test **พิสูจน์ว่า 404 มาจาก auth ไม่ใช่ query**
- #19 เพิ่ม `get_current_user_or_bot` ให้ bot identity ผ่าน auth ได้

**ตัดสินใจเพราะ** — แทนที่จะเดาและแก้ไปเรื่อย ๆ ทีมเลือก **เขียน test พิสูจน์ root cause**
ก่อนแก้ (#18) — `> ที่มา: PR #18 title "docs+test: prove ... 404 comes from auth, not server_id query"`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Bot system identity ใน auth layer,
dependency ที่แยก web/bot path

**พังแล้วแก้อย่างไร** — แก้ 3 รอบก่อนเจอ root cause จริง เพราะ FastAPI resolve dependency
ทุกตัวก่อนเข้า handler — bot ไม่มีแถวใน `users` จึง 404 ก่อนถึงโค้ด query

**เพิ่ม**
- หน้าประกาศเข้า Discord
- `get_current_user_or_bot`

**แก้ไข**
- 404 ของ bot
- column switch ตาม target_type

**สิ่งที่ยาก / ภูมิใจ** — นี่คือ bug ที่สอนว่า "แก้ตามอาการ" แพงกว่า "พิสูจน์ root cause" เสมอ
— หลังรอบนี้การ Debug ของโปรเจกต์เปลี่ยนวิธี

**Migration:** ไม่มี
**อ้างอิง:** PR #15–#19 · main `2bf07b6`

---

## [1.9.0] — 2026-08-07 — แจ้งเตือน Discord มีหมวดหมู่ + Excel 2 ชีต

**บริบท ณ ตอนนั้น** — ทุก event ยิง Discord เหมือนกันหมด ทำให้ช่องประกาศรก
และ export นักเรียนยังเป็นชีตเดียวอ่านยาก

**สิ่งที่ทำ** — PR #20: แจ้งเตือนทุกระบบพร้อม **@everyone vs แจ้งเฉย ๆ** และ
**หัวข้อหมวดหมู่** ก่อน embed, PR #21: ติด marker `[LOW-PRIORITY]` ให้ event ที่ควรลด
(งานเสร็จ, ธุรกรรม, ยืนยันชำระ, นักเรียนใหม่) เพื่อปิดทีหลังได้โดยไม่ลืมเจตนา
พร้อม Excel นักเรียน 2 ชีตภาษาไทยสวยงาม + test 227 บรรทัด

**ตัดสินใจเพราะ** — ไม่ปิด notification ทิ้งทันที แต่ติดธงไว้ก่อน เพื่อให้ตัดสินใจด้วยข้อมูล
— `> ที่มา: PR #21 body`

**เพิ่ม**
- Notification categories + mention control
- Excel 2 ชีต

**เปลี่ยน**
- รูปแบบ embed

**สิ่งที่ยาก / ภูมิใจ** — การออกแบบ notification ให้ "พอดี" ยากกว่าการส่งทุกอย่าง
— การติดธง low-priority คือการยอมรับว่ายังไม่รู้คำตอบ แต่เก็บข้อมูลไว้ตัดสิน

**Migration:** ไม่มี
**อ้างอิง:** PR #20–#21 · main `632254f`

---

## [1.10.0] — 2026-08-07 — ตำแหน่งครบ, โปรไฟล์ครบ, ห้องวันเกิด

**บริบท ณ ตอนนั้น** — ห้องเรียนมีตำแหน่งจริงมากกว่าที่ระบบรองรับ (เรขา รองหัวหน้า ฯลฯ)
และหน้าแก้โปรไฟล์แก้ได้แค่บางฟิลด์

**สิ่งที่ทำ** — PR #22 เพิ่ม 6 ตำแหน่ง (รองหัวหน้าห้อง, เลขานุการ/เรขา, รอง/กรรมการประชาสัมพันธ์,
สุขาภิบาล), PR #23 หน้าแก้โปรไฟล์ครบ **31 คอลัมน์** ตาม `StudentUpdateRequest`,
PR #24 ห้องแฮปปี้เบิร์ดเดย์ + ห้องแจ้งเตือนงานเล็ก + bot อวยพรวันเกิดอัตโนมัติ
(`rooms.birthday_channel_id`, `rooms.minor_notify_channel_id`)

**ตัดสินใจเพราะ** — แยกช่องแจ้งเตือนหลักกับช่อง "เสียงรบกวน" เพื่อให้ช่องประกาศ
ยังน่าเชื่อถือ — `> ที่มา: PR #24 body "route การแจ้งเตือนระดับสแปมไปห้องย่อย"`

**พังแล้วแก้อย่างไร** — migration ของคอลัมน์ใหม่ต้องมีทั้ง `CREATE TABLE` และ `ALTER TABLE`
เพื่อรองรับ DB ที่มีอยู่แล้ว — แพตเทิร์นที่ยังใช้ถึงวันนี้

**เพิ่ม**
- 6 ตำแหน่ง
- โปรไฟล์ครบ 31 ฟิลด์
- ช่องวันเกิด/ช่องแจ้งเตือนย่อย
- bot อวยพรวันเกิด

**สิ่งที่ยาก / ภูมิใจ** — การทำให้ข้อมูลส่วนตัว "ครบ" หมายถึงความรับผิดชอบมากขึ้น
— ซึ่งนำไปสู่การทบทวน PII ใน v1.16.0 โดยตรง

**Migration:** เพิ่ม 2 คอลัมน์บน `rooms` (CREATE + ALTER)
**อ้างอิง:** PR #22–#24 · main `c57c722`

---

## [1.11.0] — 2026-08-09 — รับเงินทีละหลายบิลใน transaction เดียว

**บริบท ณ ตอนนั้น** — การรับเงินหลายบิลของนักเรียนคนเดียวทำทีละ `PUT` ด้วย `Promise.all`
→ ถ้าบิลใดล้ม ข้อมูลครึ่ง ๆ กลาง ๆ และ bot ส่ง embed "ชำระเงิน" หลายรอบจนช่องรก

**สิ่งที่ทำ** — PR #25 batch debt settlement: endpoint เดียวประมวลผลทุกบิลใน transaction
เดียว + แจ้งเตือน Discord รอบเดียวสรุปทุกรายการ

**ตัดสินใจเพราะ** — atomicity สำคัญกว่าความสะดวกของหน้าจอ — เงินต้องไม่ถูกบันทึกครึ่งเดียว
— `> ที่มา: PR #25 body`

**พังแล้วแก้อย่างไร** — ต้องระวังการคำนวณยอดคงเหลือหลังชำระหลายบิลพร้อมกัน
— ใช้ transaction + ตรวจยอดจาก ledger

**เพิ่ม**
- batch settlement endpoint
- Discord สรุปรอบเดียว

**แก้ไข**
- partial failure ในการรับเงินหลายบิล

**สิ่งที่ยาก / ภูมิใจ** — การเปลี่ยนจาก "ยิงหลาย request" เป็น "หนึ่งธุรกรรม"
คือการยกระดับความถูกต้องของการเงินทั้งระบบ

**Migration:** ไม่มี
**อ้างอิง:** PR #25 · main `f16d5f6`

---

## [1.11.1] — 2026-08-09 — Mobile-first overhaul

**บริบท ณ ตอนนั้น** — ระบบถูกใช้บนมือถือเป็นหลัก แต่ `h-screen` ทำให้เนื้อหาล่างหาย
drawer ค้าง dropdown z-index สับสน และมี horizontal scroll

**สิ่งที่ทำ** — PR #26 ปรับทุกหน้าให้ mobile-first: `h-screen` → `h-dvh`,
`overflow-x-hidden`, Teleport + z-index ที่ถูกต้อง, drawer ปิดถูกจังหวะ,
ปุ่ม action มองเห็นบนมือถือ

**ตัดสินใจเพราะ** — นักเรียนใช้มือถือ 100% — desktop เป็นกรณียกเว้น
— `> อนุมานจาก diff: ทุกการแก้เป็น responsive utility`

**พังแล้วแก้อย่างไร** — z-index/dropdown เป็นปัญหาเรื้อรังเพราะไม่มีระบบ layer
— แก้ด้วย Teleport และค่า z ที่กำหนดชัด (ต่อมากลายเป็น design tokens ใน v1.27.0)

**แก้ไข**
- `h-dvh`
- horizontal scroll
- dropdown/drawer บนมือถือ

**สิ่งที่ยาก / ภูมิใจ** — การยอมรับว่า "เว็บนี้คือแอปมือถือ" เปลี่ยนวิธีตัดสินใจทุกอย่างหลังจากนี้

**Migration:** ไม่มี
**อ้างอิง:** PR #26 · main `f1a701d`

---

## [1.12.0] — 2026-08-14 — ระบบกิจกรรม 3 ชั้น

**บริบท ณ ตอนนั้น** — ระบบจัดการห้องเรียนได้ แต่จัดการ "กิจกรรม" (กีฬาสี ทัศนศึกษา)
ไม่ได้ — ต้องใช้ Excel และกลุ่มแชท ซึ่งข้อมูลหายทุกปี

**สิ่งที่ทำ** — PR #27–#29 สร้าง Activity & Role Management ครบ 3 เลเยอร์
(FastAPI / Vue / Discord bot):
- ตาราง `activities` + `activity_participants` พร้อม **JSONB metadata**
  (พิกัด, กำหนดการ, เบอร์รถ, ไซส์เสื้อ, เวลาเช็คอิน)
- Dynamic Smart Forms + Batch Apply (PR #28)
- ตำแหน่ง/หน้าที่กำหนดเองต่อกิจกรรม + หน้าแก้ไขเต็ม + คำไทย (PR #29)

**ตัดสินใจเพราะ** — ใช้ JSONB แทนการเพิ่มคอลัมน์ทุกฟิลด์ เพราะแต่ละกิจกรรมมีฟิลด์ไม่เหมือนกัน
และต้องต่อยอด QR check-in/certificate ในอนาคต — `> ที่มา: PR #27 body`

**เทคโนโลยีที่เปลี่ยน/ลอง** — JSONB dynamic schema, data dictionary กลาง
(`frontend/src/constants/activityFields.ts`), batch update

**พังแล้วแก้อย่างไร** — ฟิลด์ dynamic ทำให้ validation หลุด — แก้ด้วย Type A/B/C
ใน data dictionary และ guard ฝั่ง backend

**เพิ่ม**
- activities + participants
- dynamic smart forms
- ตำแหน่งต่อกิจกรรม

**Migration:** เพิ่ม 2 ตาราง + JSONB
**อ้างอิง:** PR #27–#29 · main `f4a76c7`

---

## [1.13.0] — 2026-08-16 — Activity UX, ฟอร์มอัจฉริยะ, roster

**บริบท ณ ตอนนั้น** — กิจกรรมทำงานได้ แต่ UI ยังยึดกีฬาสีเป็นค่าเริ่มต้น
และหน้า roster บนมือถือชื่อหาย

**สิ่งที่ทำ** — PR #30 UX เป็นกลาง (ตำแหน่ง default ทั่วไป, batch ตั้งหน้าที่,
StudentList roster), PR #31 แก้ multi-line template attribute ที่ทำให้
Vite/rolldown parse error, PR #32 หน้า ActivityDetail เป็น display-only roster,
PR #33 แก้การ์ด roster บนมือถือ (ชื่อไม่หาย, ปุ่มข้อมูลเพิ่มเติม compact)

**ตัดสินใจเพราะ** — ระบบต้องไม่สมมติว่าทุกกิจกรรมคือกีฬาสี — ค่าเริ่มต้นต้องเป็นกลาง
— `> ที่มา: PR #30 body`

**พังแล้วแก้อย่างไร** — rolldown ไม่รับ attribute หลายบรรทัด — ย้ายเป็น named handler
ใน `<script setup>` — bug นี้จะเจอซ้ำทุกครั้งที่เขียน template ยาว ๆ

**เพิ่ม**
- batch duty assignment
- read-only roster

**แก้ไข**
- build error จาก multi-line attribute
- ชื่อหายบนมือถือ

**สิ่งที่ยาก / ภูมิใจ** — การทำให้ฟีเจอร์ที่ซับซ้อน "ดูเรียบง่าย" บนมือถือ
คือการออกแบบที่แท้จริง

**Migration:** ไม่มี
**อ้างอิง:** PR #30–#33 · main `865b0c9`

---

## [1.14.0] — 2026-08-18 — English-primary identity

**บริบท ณ ตอนนั้น** — ชื่อไทยมีปัญหาการ match: "อำ" เขียนได้ 3 แบบ
(U+0E33 / อา+นิคหิต / นิคหิต+อา) ซึ่งเป็น codepoint คนละตัวแต่ความหมายเดียวกัน
ทำให้ค้นหา/dedupe ไม่เจอ

**สิ่งที่ทำ** — PR #34 refactor identity ให้ยึดอังกฤษเป็นหลัก: เพิ่ม
`first_name_en`, `last_name_en`, `nickname_en` บน `users` และ normalize การเทียบชื่อ
โดยชื่อไทยยังใช้แสดงผล

**ตัดสินใจเพราะ** — ชื่อเล่นอังกฤษคือชื่อที่เพื่อนเรียกจริงในห้อง และไม่มีปัญหา Unicode
แบบไทย — `> ที่มา: PR #34 body`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Unicode normalization ของภาษาไทย,
dual-name model

**พังแล้วแก้อย่างไร** — ข้อมูลเดิมไม่มีชื่ออังกฤษ — ต้อง fallback ไปชื่อไทย
และให้ผู้ใช้กรอกเพิ่มภายหลัง

**เพิ่ม**
- 3 คอลัมน์ชื่ออังกฤษ
- normalization

**เปลี่ยน**
- ตรรกะการค้นหา/เทียบชื่อ

**สิ่งที่ยาก / ภูมิใจ** — การแก้ปัญหา Unicode ภาษาไทยเป็นเรื่องที่คนนอกมองไม่เห็น
แต่กระทบทุกการค้นหาชื่อในระบบ

**Migration:** เพิ่ม 3 คอลัมน์บน `users`
**อ้างอิง:** PR #34 · main `27e139f`

---

## [1.15.0] — 2026-08-21 — จัดการผู้เข้าร่วม + เช็คชื่อหลายแผ่น

**บริบท ณ ตอนนั้น** — กิจกรรมมีรายชื่อแล้ว แต่การเช็คชื่อหน้างานจริงต้องแยกหลายรอบ
(เช็คขึ้นรถ, เช็คเข้าฐาน) และต้องเพิ่มคนหน้างานได้

**สิ่งที่ทำ** — PR #35 หน้า `/activities/:id/manage` พร้อม 4 ฟีเจอร์:
เช็คชื่อแยกแผ่นหลายชุด, Bulk Update, เพิ่มนักเรียน, Dynamic Fields
PR #36 refactor ActivityDetail เป็น 3-dot menu + badge ย่อ + grid
PR #37 ปรับ Export กิจกรรม (สถานะไทย, ชื่อไฟล์, ฟอร์แมต)

**ตัดสินใจเพราะ** — หน้างานต้องการความเร็วและการกดพลาดน้อยที่สุด
— รวม action รองในเมนู 3 จุด และเหลือ CTA หลักปุ่มเดียว — `> ที่มา: PR #36 body`

**พังแล้วแก้อย่างไร** — export ใช้ label ของ participant status ไปแปล activity status
ทำให้ได้ `ongoing` ติดมาเป็นอังกฤษ — แยก `ACTIVITY_STATUS_LABELS`

**เพิ่ม**
- manage page
- attendance sheets
- bulk update

**แก้ไข**
- export label ผิดชุด
- ชื่อไฟล์ export

**สิ่งที่ยาก / ภูมิใจ** — การออกแบบให้ใช้ได้จริงหน้างาน (มือเดียว ถือของ)
คือการออกแบบที่ทดสอบด้วยสถานการณ์จริง ไม่ใช่ด้วยสายตา

**Migration:** เพิ่มตาราง/JSONB สำหรับ attendance sheets
**อ้างอิง:** PR #35–#37 · main `e5a2ae2`

---

## [1.16.0] — 2026-08-25 — Consent Model: ปิดช่องโหว่ PII

**บริบท ณ ตอนนั้น** — พบช่องโหว่ร้ายแรง: ใครก็ได้สร้างห้อง → ได้เป็น admin ทันที
แล้วแอดชื่อที่ตรงกับบัญชีจริง → ระบบ **link บัญชีให้อัตโนมัติโดยไม่ยินยอม**
→ เห็น PII ครบ (เบอร์, อีเมล, ที่อยู่, กรุ๊ปเลือด, แพ้อาหาร, โรคประจำตัว, เบอร์ผู้ปกครอง,
วันเกิด, line_id, IG) ผ่าน 3 ทาง: add_student, bulk_add_students, search

**สิ่งที่ทำ** — PR #38 เพิ่ม **Consent Model** ด้วย `identity_claimed`:
การ link บัญชีต้องมีเจ้าของบัญชียืนยัน ไม่ใช่แค่ชื่อตรงกัน
และปรับ flow การเพิ่มนักเรียนให้ไม่ auto-link

**ตัดสินใจเพราะ** — ทางเลือกคือ "ปิดการเพิ่มนักเรียนชั่วคราว" ซึ่งทำลายการใช้งาน
หรือ "เพิ่ม consent" ซึ่งถูกต้องกว่า — `> ที่มา: PR #38 body ระบุช่องโหว่ 3 ทาง`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Consent-based identity linking

**พังแล้วแก้อย่างไร** — ต้องมีทางให้ admin ยืนยันแทนได้ในกรณีที่นักเรียนยืนยันเองไม่ได้
แต่ต้องมี audit

**ความปลอดภัย**
- ปิดช่องโหว่ PII
- บังคับ consent ก่อน link บัญชี

**สิ่งที่ยาก / ภูมิใจ** — นี่คือ vulnerability ที่อันตรายที่สุดที่เจอในโปรเจกต์
การเจอและปิดได้ก่อนมีคนใช้คือช่วงเวลาที่สำคัญที่สุดของเดือนนี้

**Migration:** เพิ่มคอลัมน์ `identity_claimed`
**อ้างอิง:** PR #38 · main `f5c7b3f`

---

# ยุคที่ 5 — การเงิน ERP-grade + audit (ก.ย. 2026)

> กันยายนคือเดือนที่ระบบการเงินกลายเป็น "ระบบบัญชี" จริง ๆ
> และเป็นเดือนที่ผลตรวจระบบภายนอก (2026-09-23) ถูกปิดทีละข้อจนครบ

---

## [1.17.0] — 2026-09-03 — General Journal, reconciliation, วันตัดยุค 1 ก.ย.

**บริบท ณ ตอนนั้น** — บัญชีคู่ (v1.7.0) ถูกใช้มาเกือบเดือน แต่ยังมีสองยุคข้อมูลคู่กัน
(legacy `finance_transactions` กับ `journal_entries`) ที่ยอดอาจหลุดจากกัน
และยัง export สมุดรายวันไม่ได้

**สิ่งที่ทำ** — PR #39 Export สมุดรายวัน (General Journal) + แก้ยอดสรุปรวมที่เอา
"โอนเงินระหว่างบัญชี" ไปนับเป็นรายจ่าย, PR #40 แก้ test summary 3 ตัวให้รองรับ
`CUTOFF_DATE = 2026-09-01`, PR #41 สร้าง `reconcile_finance.py` กระทบยอด
Legacy ↔ บัญชีคู่, PR #42 ให้การอ่านหลัง 1 ก.ย. ใช้บัญชีคู่ 100% + ปิดจุดรั่ว 2 จุด

**ตัดสินใจเพราะ** — ตั้ง `CUTOFF_DATE` เป็นเส้นแบ่งที่ชัดเจน แล้วให้ทั้ง read และ write
ตัดสินจากวันเดียวกัน — ก่อนหน้านี้ read path ตัดสินคนละที่กับ write ทำให้ยอดสลับยุค
— `> ที่มา: PR #42 body ระบุ 3 กลุ่มปัญหา read ผิดยุค`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Reconciliation script, cutoff-based dual-era accounting

**พังแล้วแก้อย่างไร** — test summary fail บน `main` เดิมอยู่แล้ว (ไม่ใช่ regression ใหม่)
— พิสูจน์ด้วยการรันบน HEAD เปล่า แล้วแก้ที่ test ให้สะท้อนความจริงของสองยุค

**เพิ่ม**
- General Journal export
- reconcile script
- อ่านหลัง 1 ก.ย. ด้วยบัญชีคู่ 100%

**แก้ไข**
- ยอดสรุปรวมนับโอนเงินเป็นรายจ่าย
- test summary

**Migration:** ไม่มี schema ใหม่ — เป็นการแก้ read/write path
**อ้างอิง:** PR #39–#42 · main `612717f`

---

## [1.18.0] — 2026-09-03 — reconcile --all + ตัด void ออกจากยอด

**บริบท ณ ตอนนั้น** — หลัง deploy ชุด reconcile ต้องไล่กระทบยอดทุกห้อง
แต่สคริปต์รันได้ทีละห้อง และเจอบั๊กที่ทำให้ทุกคำสั่งถูก reject

**สิ่งที่ทำ** — PR #43 เพิ่ม `--all` รันเรียงทุกห้อง, PR #44 แก้บั๊กเลือกโหมด
(`sum(1 for x in (...))` นับจำนวนสมาชิก = 3 เสมอ → `chosen != 1` ตลอด),
PR #45 ตัดบิล void ออกจากยอดคงเหลือ Excel + งบทดลอง (balances LEFT JOIN bug)

**ตัดสินใจเพราะ** — กระทบยอดต้องทำได้ทั้งระบบในคำสั่งเดียว เพราะหลัง deploy
ทุกห้องมีผลต่างค้างจากรอยรั่วเก่า — `> ที่มา: PR #43 body`

**พังแล้วแก้อย่างไร** — บั๊ก `chosen` เป็นบั๊กคลาสสิกของการนับ tuple ผิด
— แก้เป็น `sum(x is not None for x in ...)` พร้อมเพิ่ม test

**เพิ่ม**
- `reconcile --all`

**แก้ไข**
- เลือกโหมดถูก reject
- void ถูกนับในยอดคงเหลือ

**สิ่งที่ยาก / ภูมิใจ** — การกระทบยอดกับระบบที่รันอยู่จริงคือการพิสูจน์ว่า
"บัญชีคู่" ไม่ใช่แค่ทฤษฎี — ผลต่างเป็น 0 หลังแก้

**Migration:** ไม่มี
**อ้างอิง:** PR #43–#45 · main `e70be76`

---

## [1.19.0] — 2026-09-04 — Excel ระดับ ERP + ลูกหนี้รายคน

**บริบท ณ ตอนนั้น** — export Excel มีข้อมูลแต่ไม่ตอบคำถามผู้บริหาร:
ไม่รู้ว่าใครค้างเท่าไหร่ แยกตามโครงการอะไร และ format อ่านยาก

**สิ่งที่ทำ** — PR #46 ยกระดับ export เป็น ERP-grade (แยก data-fetch จาก builder,
real-time ณ วัน export), PR #47 export ไล่รายชื่อผู้ค้างรายคน (sheet โปรเจค + ทะเบียนลูกหนี้),
PR #48 แก้ path v2 ที่ทำให้ Sheet 4–5 ว่างหลัง CUTOFF_DATE

**ตัดสินใจเพราะ** — แยก "ดึงข้อมูล" กับ "สร้างไฟล์" ออกจากกัน ทำให้เพิ่ม sheet ใหม่
ได้โดยไม่แตะ SQL — `> ที่มา: PR #46 body "แยก data-fetch ออกจาก builder"`

**พังแล้วแก้อย่างไร** — หลัง CUTOFF_DATE export วิ่ง path v2 ซึ่งไม่ได้ส่งข้อมูลโปรเจค/ลูกหนี้
เข้า Sheet 4–5 — แก้ให้ v2 ส่งครบ

**เพิ่ม**
- ERP export
- ลูกหนี้รายคน

**แก้ไข**
- Sheet ว่างใน path v2

**สิ่งที่ยาก / ภูมิใจ** — ตัวเลขใน Excel ต้องตรงกับหน้าเว็บและ reconcile
— การทำงานกับตัวเลขสามที่พร้อมกันคือบททดสอบความถูกต้องที่แท้จริง

**Migration:** ไม่มี
**อ้างอิง:** PR #46–#48 · main `4a0c985`

---

## [1.19.1] — 2026-09-05 — แยก God class เป็น package

**บริบท ณ ตอนนั้น** — `finance_service.py` และ router โตจนไฟล์เดียวหลายพันบรรทัด
แก้ทีละนิดก็ต้องโหลดทั้งไฟล์

**สิ่งที่ทำ** — PR #49 แยก service/router ที่บวมเป็น package ย่อยตามหน้าที่
ด้วย **Mixin + Facade + re-export shim** — import path เดิมยังใช้ได้ 100%
โดยไม่แตะ SQL/business logic/public API

**ตัดสินใจเพราะ** — refactor แบบไม่ breaking: ของเก่ายัง import ได้
ทำให้ merge กับงานอื่นไม่ชน — `> ที่มา: PR #49 body`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Mixin composition, facade, compatibility shim

**พังแล้วแก้อย่างไร** — circular import ระหว่าง mixin — แก้ด้วยการแยก base ออก

**เปลี่ยน**
- โครงสร้าง service/router (พฤติกรรมเดิม)

**สิ่งที่ยาก / ภูมิใจ** — refactor ที่ไม่เปลี่ยน behavior แม้แต่บรรทัดเดียว
คือ refactor ที่กล้าหาญที่สุด — และมันทำให้เดือนถัดมาเพิ่มฟีเจอร์ได้เร็วขึ้นมาก

**Migration:** ไม่มี
**อ้างอิง:** PR #49 · main `ced8be8`

---

## [1.20.0] — 2026-09-12 — Design System "Academic Ledger"

**บริบท ณ ตอนนั้น** — แต่ละหน้าถูกออกแบบแยกกัน: gradient, glass, เงาสี, backdrop-blur
ปนกันจนระบบไม่มี "เสียง" เดียว

**สิ่งที่ทำ** — PR #50 ยกเครื่อง 46 ไฟล์ `.vue` เป็นธีมเดียว: โทนกระดาษ `stone`
+ น้ำเงินเข้ม SYNCROOM `#1D4ED8` เป็นสีเน้นเดียว, ตัด gradient/glass/เงาสี/blur ทั้งหมด
ใช้เส้นบางและพื้นเรียบแทน

**ตัดสินใจเพราะ** — ระบบราชการ/โรงเรียนต้องการความน่าเชื่อถือ ไม่ใช่ความหวือหวา
— "Academic Ledger" คือ metaphor ของสมุดบัญชีที่ตรวจสอบได้ — `> ที่มา: PR #50 body`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Design system แบบ token-based (ยังไม่เป็น CSS variables เต็มรูปแบบ
— จะสมบูรณ์ใน v1.27.0)

**พังแล้วแก้อย่างไร** — หน้าจอที่พึ่ง gradient เพื่อซ่อนขอบเกิดรอยต่อ — แก้ด้วยเส้นบาง

**เปลี่ยน**
- ธีมทั้งระบบ 46 ไฟล์

**สิ่งที่ยาก / ภูมิใจ** — การเลือก "สีเดียว" คือการบังคับวินัยให้ตัวเอง
— หลังจากนี้ทุกหน้าใหม่ถูกวัดด้วยมาตรฐานเดียวกัน

**Migration:** ไม่มี
**อ้างอิง:** PR #50 · main `1a29188`

---

## [1.20.1] — 2026-09-12 — แก้ UI มือถือทั้งระบบ

**บริบท ณ ตอนนั้น** — หลังเปลี่ยน design system หัวข้อหน้าบนมือถือเพี้ยน
เพราะ `flex-wrap` + `flex-1` + `min-w-0` คำนวณจาก outer hypothetical size

**สิ่งที่ทำ** — PR #51 แก้บั๊ก UI มือถือ 44 ไฟล์ + ลดความบวมของระยะห่าง

**ตัดสินใจเพราะ** — เลือกแก้ที่ `PageHeader` กลาง ไม่ใช่แก้ทีละหน้า
— `> ที่มา: PR #51 body ระบุ root cause ของ flex`

**พังแล้วแก้อย่างไร** — flex bug ที่เกิดจาก spec ไม่ใช่โค้ดผิด — แก้ด้วยการกำหนด
`min-width: 0` และไม่ให้ flex item ขยายเกิน

**แก้ไข**
- หัวข้อหน้าเพี้ยนบนมือถือ
- ระยะห่างบวม

**สิ่งที่ยาก / ภูมิใจ** — bug ที่ดูเหมือน "CSS งง" จริง ๆ แล้วคือ CSS ทำงานถูกต้อง
— เข้าใจ spec แล้วแก้ถูกจุดในครั้งเดียว

**Migration:** ไม่มี
**อ้างอิง:** PR #51 · main `ac4775e`

---

## [1.21.0] — 2026-09-14 — งบการเงิน F1–F3 + ใบเสร็จ/ใบแจ้งหนี้ + เวลาไทย

**บริบท ณ ตอนนั้น** — การเงินบันทึกได้ กระทบยอดได้ แต่ยัง "รายงาน" ไม่ได้
— ไม่มีงบการเงิน ไม่มีงบประมาณ และไม่มีเอกสารที่ส่งให้นักเรียน/ผู้ปกครองได้จริง

**สิ่งที่ทำ** — PR #52 ปิดงานการเงิน 4 เฟส:
- **F1 งบการเงิน** — `GET /finance/balance-sheet` + `response_model` ให้ trial-balance/income-statement
  (แก้ `_compose_balance_sheet` ที่ฮาร์ดโค้ดหนี้สินเป็น `0.0` ทำให้งบไม่ balance)
- **F2 งบประมาณ**
- **F3 ใบเสร็จ/ใบแจ้งหนี้**
- **F4 Discord notifications** + มาตรฐานเวลาไทย (`Asia/Bangkok` ทุกที่)
PR #53 แก้ dry-run ของ backfill ที่เขียน DB จริง (auto-provision ledger ถูก commit)

**ตัดสินใจเพราะ** — ใช้ Gotenberg สร้าง PDF จาก HTML เพื่อให้เอกสารหน้าตาควบคุมได้ด้วย CSS
และแยก stack `pdf` ออกจาก `app` — `> ที่มา: docker-compose.pdf.yml + PR #52 body`

**พังแล้วแก้อย่างไร** — dry-run ที่เขียนจริงคือ bug ที่อันตรายที่สุดของเดือน
เพราะมันทำลายความเชื่อในเครื่องมือ — แก้ให้ dry-run ไม่อยู่ใน transaction ที่ commit

**เพิ่ม**
- balance sheet / trial balance / income statement
- งบประมาณ
- ใบเสร็จ/ใบแจ้งหนี้ PDF
- Discord แจ้งเตือนการเงิน

**แก้ไข**
- งบไม่ balance (หนี้สิน hardcode 0)
- dry-run เขียน DB

**สิ่งที่ยาก / ภูมิใจ** — ระบบการเงินจาก "จดรายการ" กลายเป็น "ออกรายงานได้"
— นี่คือเส้นแบ่งระหว่างเครื่องมือส่วนตัวกับระบบที่โรงเรียนใช้แทน Excel ได้

**Migration:** เพิ่มตาราง/ฟิลด์เอกสารการเงิน
**อ้างอิง:** PR #52–#53 · main `747f428`

---

## [1.22.0] — 2026-09-14 — ใบแจ้งหนี้รวมยอด + เงินรับล่วงหน้า (F4)

**บริบท ณ ตอนนั้น** — ใบแจ้งหนี้ออกเป็นใบละบิล ทำให้นักเรียนค้าง 3 โครงการได้ 3 ฉบับ
ทั้งที่คำตอบที่ต้องการคือ "ค้างเท่าไหร่" คำตอบเดียว — และยังออกทั้งห้องไม่ได้

**สิ่งที่ทำ** — PR #54 ใบแจ้งหนี้รวมยอดต่อคน + ออกทั้งห้อง + ดาวน์โหลด PDF รวมหลายใบ,
PR #55 **F4 เงินรับล่วงหน้า** (เครดิตคงเหลือรายนักเรียน) + ใบแจ้งหนี้หักเครดิต

**ตัดสินใจเพราะ** — เอกสารต้องตอบคำถามของคนอ่าน ไม่ใช่สะท้อนโครงสร้างฐานข้อมูล
— `> ที่มา: PR #54 body`

**พังแล้วแก้อย่างไร** — PR #55 ต่อยอดจาก base ที่ merge ไปแล้ว (PR #54) และเจอปัญหา
การอ่าน `origin/main` ผิดจังหวะ — บันทึกเป็นบทเรียนใน docs/skills.md

**เพิ่ม**
- ใบแจ้งหนี้รวมยอด
- ออกทั้งห้อง + PDF รวม
- เงินรับล่วงหน้า/เครดิต

**สิ่งที่ยาก / ภูมิใจ** — เครดิตคือแนวคิดที่ทำให้การเงิน "ยุติธรรม" ขึ้น
— จ่ายเกินวันนี้ใช้ได้ครั้งหน้า โดยไม่ต้องคืนเงินสด

**Migration:** เพิ่มตาราง/ฟิลด์เครดิต
**อ้างอิง:** PR #54–#55 · main `4ac09cb`

---

## [1.23.0] — 2026-09-15 — ชุดเอกสาร F5 + ใบเสร็จอัตโนมัติ + PDF ไป Discord

**บริบท ณ ตอนนั้น** — เอกสารแต่ละชนิดต้องกดออกทีละใบ และการเคลียร์หนี้หลายบิล
ไม่ได้ออกใบเสร็จให้อัตโนมัติ

**สิ่งที่ทำ** — PR #56 แก้ id รายการยุคบัญชีคู่ที่ถูกทิ้งเพราะ metadata JSONB มาเป็นสตริง,
PR #57 ซ่อนการกระทำที่ทำลายข้อมูลในเมนู 3 จุด (`RowActionMenu`),
PR #58 ชุดเอกสาร + จัดกลุ่มเอกสารอัตโนมัติ (F5/PR-1),
PR #59 ออกใบเสร็จอัตโนมัติทุกรายการเมื่อเคลียร์หนี้ (F5/PR-2),
PR #60 แนบ PDF ใบเสร็จไปกับข้อความรับเงินใน Discord (F5/PR-3)

**ตัดสินใจเพราะ** — เอกสารควรเกิดจากเหตุการณ์ (เคลียร์หนี้) ไม่ใช่จากการกดออกทีละใบ
— `> ที่มา: PR #59 body quote ผู้ใช้`

**พังแล้วแก้อย่างไร** — JSONB คืนค่าเป็น string ทำให้ `id` ถูก parse ผิด
และปุ่มลบอยู่ติดปุ่มติ๊กเสร็จจนกดพลาด — แก้ทั้งสองเรื่องในรอบเดียวกัน

**เพิ่ม**
- ชุดเอกสาร/group
- ใบเสร็จอัตโนมัติ
- PDF แนบ Discord

**แก้ไข**
- id รายการหาย
- ปุ่มทำลายข้อมูลกดพลาด

**ความปลอดภัย/UX**
- ย้าย destructive action เข้าเมนู

**สิ่งที่ยาก / ภูมิใจ** — การทำ "เอกสารเกิดเอง" ต้องให้ transaction ครอบทั้งรายการเงิน
และเอกสาร — ถ้าใบเสร็จออกแต่รายการไม่บันทึก ถือว่าล้มเหลวทั้งคู่

**Migration:** ไม่มี schema ใหม่ (ใช้ตารางเอกสารเดิม)
**อ้างอิง:** PR #56–#60 · main `d205a43`

---

## [1.24.0] — 2026-09-16 — ใบสำคัญจ่าย/ใบรับเงิน F6 + mutation test

**บริบท ณ ตอนนั้น** — มีใบเสร็จสำหรับ "รับเงิน" แต่ยังไม่มีเอกสารสำหรับรายจ่ายที่บันทึกเอง
และใบเสร็จของคนเดียวกันหลายรายการยังแยกเป็นหลายหน้า

**สิ่งที่ทำ** — PR #61 ยุบใบเสร็จคนเดียวกันเป็นหน้าเดียวหลายบรรทัด (F6/PR-4),
PR #62 ใบสำคัญจ่าย + ใบรับเงิน ออกจากรายการที่บันทึกเองใน transaction เดียว (F6/PR-5),
PR #63 แนบ PDF เข้า Discord (F6/PR-6),
PR #64 ตามเก็บช่องว่าง test idempotency เครดิต + แก้ mutation harness,
PR #65 แก้หน้าขาวบนมือถือเพราะ `response_model` ตัดฟิลด์ทิ้ง

**ตัดสินใจเพราะ** — เอกสารต้อง atomic กับรายการ: ไม่มีเอกสารที่ไม่มีรายการ
และไม่มีรายการที่ไม่มีเอกสาร — `> ที่มา: PR #62 body`

**พังแล้วแก้อย่างไร** — `response_model` ที่เข้มเกินทำให้ฟิลด์ที่ frontend ต้องใช้หายไป
— หน้าจอค้างที่ skeleton โดยไม่มี error — แก้ response model ให้ครบ

**เพิ่ม**
- ใบสำคัญจ่าย/ใบรับเงิน
- PDF เอกสารเข้า Discord
- mutation test

**แก้ไข**
- ใบเสร็จแยกหน้า
- หน้าขาวบนมือถือ

**สิ่งที่ยาก / ภูมิใจ** — ชุดเอกสาร F1–F6 ครบภายในสองสัปดาห์
— จาก "จดรายการ" เป็น "ระบบเอกสารการเงินที่ตรวจสอบได้"

**Migration:** เพิ่มตาราง/ฟิลด์เอกสาร
**อ้างอิง:** PR #61–#65 · main `732198b`

---

## [1.25.0] — 2026-09-19 — เปรียบเทียบกิจกรรม + Venn + export รวม

**บริบท ณ ตอนนั้น** — กิจกรรมมีผู้เข้าร่วมแล้ว แต่ตอบไม่ได้ว่า "ใครอยู่ทั้งสองกิจกรรม"
หรือ "ใครอยู่ A แต่ไม่อยู่ B" ซึ่งเป็นคำถามที่ใช้จริงตอนจัดทัศนศึกษา/กีฬาสี

**สิ่งที่ทำ** — PR #66 เปรียบเทียบกิจกรรม (Intersection/Union/ลบ) + แผนภาพ Venn
ที่กดเลือกภูมิภาคได้ + Export Excel รวม, PR #67 แก้ Venn บนมือถือ + ชื่อในภูมิภาคตัดบรรทัด

**ตัดสินใจเพราะ** — Venn เป็นภาษาที่คนเข้าใจทันทีโดยไม่ต้องอธิบายเซต
— `> ที่มา: PR #66 body`

**พังแล้วแก้อย่างไร** — `<svg>` ถูกซ่อนด้วย `hidden md:block` ทำให้มือถือไม่เห็น
— และการย่อ SVG ทั้งวงทำให้ตัวอักษรเล็กอ่านไม่ออก — แก้ด้วย layout แยกบนมือถือ

**เพิ่ม**
- Activity compare
- Venn diagram
- combined export

**แก้ไข**
- Venn บนมือถือ

**สิ่งที่ยาก / ภูมิใจ** — ฟีเจอร์ที่ดู "เล่น" (Venn) จริง ๆ แล้วตอบคำถามบริหารจัดการ
ที่ Excel ทำได้ยากมาก

**Migration:** ไม่มี
**อ้างอิง:** PR #66–#67 · main `f95554f`

---

## [1.25.1] — 2026-09-25 — ปิดผลตรวจระบบ 2026-09-23 (16 PR)

**บริบท ณ ตอนนั้น** — มีการตรวจระบบแบบเจาะลึกเมื่อ 23 ก.ย. 2026 พบช่องโหว่และ
จุดอ่อนหลายระดับ ตั้งแต่ auth ที่เปิดโล่งไปจนถึงเอกสารที่ผิดความจริง

**สิ่งที่ทำ** — ปิดfinding เป็นชุด 16 PR (#68–#83):

**ความปลอดภัย (สำคัญที่สุด)**
- #68 `GET /classroom/{id}/summary` เป็น route เดียวจาก 127 ตัวที่ **ไม่มี auth** —
  ยิงจริงแล้วได้ข้อมูลโรงเรียนทั้ง production/staging ตอบ 200 โดยไม่ต้องส่ง credential
- #69 หยุดคัดลอก PII (สุขภาพ/เบอร์ผู้ปกครอง/วันเกิด/ที่อยู่) ลง `audit_logs`
- #70 ปิด XSS ผ่าน `innerHTML` ของ SweetAlert2
- #71 กรอง `status='active'` ตอนอ่านรายชื่อ (pending หลุดเข้ามาได้)

**โครงสร้าง/คุณภาพ**
- #72 `.dockerignore` ลด build context 374MB → 2.3MB
- #73 บังคับ `Asia/Bangkok` กับเวลาที่เป็นหลักฐาน
- #74 **CI จริงครั้งแรกของ repo** (ก่อนหน้านี้ workflow อยู่ใน subfolder ที่ GitHub ไม่เห็น)
- #75 บอกผู้ใช้เมื่อดึงโปรไฟล์ไม่สำเร็จ แทนฟอร์มว่างเงียบ ๆ

**บอท**
- #76 defer/error/timeout/เพดาน embed/redis leak/ephemeral (5 ข้อ)
- #77 แปลงข้อความตอบกลับ 44 จุดเป็น embed + จำกัดความยาว
- #79 แก้ CLAUDE.md ที่บอก "No tests" ทั้งที่มี 101 ตัว

**วินัยชั้น router/เอกสาร**
- #78 เก็บ `except:` เปล่า, fallback id ซ้ำ, โค้ดคอมเมนต์ค้าง
- #80 ลำดับ except, ข้อความที่รั่ว, `response_model`
- #81 คืนข้อความ error จาก backend ให้ผู้ใช้เห็น
- #82 บทเรียน 10 หัวข้อลง `docs/skills.md`
- #83 ถอด DDL ตาราง `mtn_*` ที่ค้างจากโมดูลที่ถูกลบแล้ว

**ตัดสินใจเพราะ** — ปิด finding ทีละข้อ เป็น PR เล็กที่ตรวจง่าย แทน mega-PR
— `> ที่มา: PR #82 body ระบุว่าบทเรียนค้างในเครื่อง ไม่เคยขึ้น repo`

**พังแล้วแก้อย่างไร** — หลาย finding ถูกแก้เสร็จแล้วแต่ไม่เคยขึ้น main (#81)
— การตรวจ cleanup พบว่ามีงานค้างในเครื่องที่ไม่มี PR

**ความปลอดภัย**
- ปิด auth hole
- หยุด PII ใน audit log
- ปิด XSS
- กรอง pending

**เพิ่ม**
- CI ครั้งแรก
- dockerignore
- บทเรียน 10 หัวข้อ

**สิ่งที่ยาก / ภูมิใจ** — การตรวจระบบภายนอกทำให้เห็นว่า "ผ่าน test 1,000 ตัว"
ไม่ได้แปลว่าปลอดภัย — ชั้น router และ config คือที่ที่ test ไม่เคยไปถึง

**Migration:** ถอด DDL `mtn_*` (ไม่ลบข้อมูลจริงในรอบนี้)
**อ้างอิง:** PR #68–#83 · main `38ec9e6`

---

## [1.25.2] — 2026-09-26 — healthcheck 503, กับดัก IMAGE_TAG, CI compose

**บริบท ณ ตอนนั้น** — `/health` คืน 200 พร้อม body "error" ทำให้ healthcheck
ใน compose ไม่ restart service ที่ DB ล่ม — และการ deploy ด้วยมือที่ลืม `export IMAGE_TAG`
จะเงียบ ๆ ใช้ `latest`

**สิ่งที่ทำ** — PR #84 healthcheck frontend + ปิดพอร์ต test DB (superuser) ไม่ให้ออกอินเทอร์เน็ต
+ ลบ workflow ตาย 3 ไฟล์, PR #85 `/health` คืน 503 เมื่อต่อ DB ไม่ได้,
PR #86 ใส่ `${IMAGE_TAG:?...}` ที่ต้นทางให้ลืมแล้วล้มดัง ๆ,
PR #87 แก้คำอธิบายกับดักให้ตรงความจริง (ขีด `-` เท่านั้นที่ฆ่า),
PR #88 ทดสอบ compose ต้องใช้ `docker stack config` ไม่ใช่ `docker compose config`,
PR #89 CI ตรวจ compose + กันกับดักหาย, PR #90 บทเรียนจากตัวตรวจเอง

**ตัดสินใจเพราะ** — "ล้มดัง ๆ" ดีกว่า "สำเร็จเงียบ ๆ ด้วยของผิด"
— `> ที่มา: PR #86 body`

**พังแล้วแก้อย่างไร** — ตัวตรวจ compose เองก็มีบั๊ก (ยิง probe ตอนกับดักยังติด)
— แก้และบันทึกบทเรียน

**แก้ไข**
- /health คืน 503
- test DB เปิดพอร์ต public
- IMAGE_TAG fallback `latest`

**เพิ่ม**
- CI compose gate

**ความปลอดภัย**
- ปิดพอร์ต DB

**สิ่งที่ยาก / ภูมิใจ** — กับดัก IMAGE_TAG คือการเปลี่ยนความผิดพลาดของคน
ให้กลายเป็นความล้มเหลวของระบบ — ไม่มีใคร deploy ผิดแบบเงียบได้อีก

**Migration:** ไม่มี
**อ้างอิง:** PR #84–#90 · main `9108613`

---

## [1.26.0] — 2026-09-27 — session ต่ออายุอัตโนมัติ + หลายห้องพร้อมกัน

**บริบท ณ ตอนนั้น** — ผู้ใช้ต้องล็อกอินใหม่แทบทุกวัน (token 24 ชม.)
และเปิดสองห้องพร้อมกันไม่ได้เพราะเก็บ `currentRoomId` ค่าเดียว

**สิ่งที่ทำ** — PR #92 ต่ออายุ session อัตโนมัติ (refresh token) +
รองรับเปิดหลายห้องพร้อมกัน, PR #93 บันทึกบทเรียน "pull_all.sh exit 0 แล้วยังตรวจไม่ได้"
(ระหว่าง rollout การยิง API ได้ 404 ค่าเดิม → เกือบสรุปว่า deploy ล้มเหลว)

**ตัดสินใจเพราะ** — อ่านค่าห้องจาก URL/route แทน global state เดียว
ทำให้แต่ละแท็บอยู่คนละห้องได้ — `> ที่มา: PR #92 body`

**พังแล้วแก้อย่างไร** — หลัง deploy ทันที service ยัง rollout ไม่ครบ —
ต้องรอ converge ก่อนตรวจ ไม่ใช่ยิงแล้วสรุปทันที

**เพิ่ม**
- refresh token
- multi-room ต่อแท็บ

**แก้ไข**
- ต้อง login บ่อย
- เปิดหลายห้องไม่ได้

**สิ่งที่ยาก / ภูมิใจ** — ฟีเจอร์นี้ดูเล็ก แต่เปลี่ยนวิธีใช้จริง: ครูเปิดห้อง A
เทียบกับห้อง B พร้อมกันได้ — เป็นสิ่งที่ผู้ใช้ขอและรอมาเดือนกว่า

**Migration:** ไม่มี
**อ้างอิง:** PR #92–#93 · main `7282e2f`

---

# ยุคที่ 6 — P0/P1 และ versioning (ต.ค. 2026)

> ตุลาคมคือเดือนที่โปรเจกต์หยุดเพิ่มฟีเจอร์ แล้วหันมาดู "ฐานราก"
> — migration, CI, design tokens และ finally: ระบบบอกเวอร์ชันตัวเองได้

---

## [1.27.0] — 2026-10-24 — P0 ฐานราก: migrations, CI 5 ด่าน, design tokens

**บริบท ณ ตอนนั้น** — ระบบโตจน `init_db.py` กลายเป็นแหล่ง DDL ก้อนเดียวที่ไม่มีประวัติ
การเปลี่ยน schema ทำได้แค่แก้ไฟล์แล้ว redeploy ซึ่งอันตรายกับ production
และ CI ยังไม่ครอบคลุม frontend build/e2e จริง

**สิ่งที่ทำ** — PR #94 ปิด P0 ทั้ง 5 ข้อ:
- **P0.1 Migration framework แบบ additive** — `backend/core/migrations/` + runner
  มีตาราง `schema_migrations(version, checksum, applied_at)`, advisory lock
  (`APPLY_LOCK_KEY = 824_631_907`) กัน backend 3 replica บูตพร้อมกัน,
  ไฟล์ละเวอร์ชันเป็น `SQL: list[str]` idempotent และ **ห้าม DROP/ALTER ทำลาย**
  `init_db` ยังสร้าง schema เต็มสำหรับ DB ใหม่
- **P0.2 CI ครบ 5 ด่าน** — frontend lint/build, backend pytest, bot unittest,
  compose gate, Playwright e2e จริง
- **P0.3 Design tokens** — สี/ระยะ/เงาเป็น token แทนค่าฮาร์ดโค้ด
- **P0.4 Router meta** — ข้อมูลหน้า/สิทธิ์/ทางกลับอยู่ที่ route
- **P0.5 เอกสารตรงจริง** — glossary/สถานะ/p้าย รวมเป็นแหล่งเดียว

**ตัดสินใจเพราะ** — migration runner ต้อง **additive เท่านั้น** เพราะ production
มีข้อมูลจริงและ rollback ที่ปลอดภัยคือ "ไม่ทำลาย" ไม่ใช่ "ย้อน schema"
— `> ที่มา: PR #94 body`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Migration runner + checksum + drift detection,
advisory lock, design tokens, Playwright e2e ใน CI

**พังแล้วแก้อย่างไร** — runner ต้องทนต่อการบูตพร้อมกันของ 3 replica
— ใช้ advisory lock และ checksum ตรวจไฟล์ที่ถูกแก้ย้อนหลัง

**เพิ่ม**
- migrations runner
- CI 5 ด่าน
- design tokens
- router meta

**เปลี่ยน**
- วิธีเปลี่ยน schema (จากแก้ init_db → migration file)

**สิ่งที่ยาก / ภูมิใจ** — การยอมหยุดเพิ่มฟีเจอร์เพื่อวางฐานราก คือวินัยที่ยากที่สุด
ของโปรเจกต์ที่กำลังโต — และมันทำให้ทุกอย่างหลังจากนี้ปลอดภัยขึ้น

**Migration:** ✅ มี runner แล้ว (ยังไม่มี migration file — schema ยังมาจาก init_db)
**อ้างอิง:** PR #94 · main `86d6ec7`

---

## [1.27.1] — 2026-10-27 — UX P1.1–P1.3: ป้ายสถานะ, ตัวอักษรไทย, สถานะว่าง

**บริบท ณ ตอนนั้น** — P0 วางฐานแล้ว P1 คือความสม่ำเสมอของ UX
และพบ bug ที่ร้ายกว่าเรื่องหน้าตา: นักเรียน "รออนุมัติ" ถูกแสดงเป็น "พ้นสภาพ" พร้อมป้ายแดง

**สิ่งที่ทำ** — PR #95 รวมป้ายสถานะเป็นแหล่งเดียว (`statusLabels.ts`) + แก้ ternary 2 ทาง
บนสถานะ 3 ค่า + เทสต์ล็อกคำกับ glossary,
PR #96 ถอด `uppercase`/`letter-spacing` จากข้อความไทย 41 บรรทัดใน 10 ไฟล์
และเพิ่ม `npm run lint:thai` เป็นด่าน,
PR #97 แยกสถานะว่างตามสาเหตุ ("ยังไม่มีข้อมูล" vs "กรองแล้วไม่เจอ") + ถอด `border-dashed` 14 จุด

**ตัดสินใจเพราะ** — ภาษาไทยไม่มีตัวพิมพ์ใหญ่ `uppercase` จึงไม่ทำอะไร
แต่ `letter-spacing` ดันสระ/วรรณยุกต์ให้ห่างจากพยัญชนะ ⇒ อ่านยากขึ้นโดยไม่มีใครสังเกต
— `> ที่มา: PR #96 body`

**เทคโนโลยีที่เปลี่ยน/ลอง** — lint เฉพาะภาษาไทย (`check-thai-typography.mjs`),
status label registry ที่ผูกกับ glossary

**พังแล้วแก้อย่างไร** — ternary 2 ทางบนสถานะ 3 ค่าคือ bug คลาสสิก —
แก้ด้วย lookup table + fallback "ไม่ทราบสถานะ"

**แก้ไข**
- ป้ายสถานะขัดกันทั้งระบบ
- ตัวอักษรไทยอ่านยาก

**เพิ่ม**
- `lint:thai`
- empty state แยกตามสาเหตุ

**สิ่งที่ยาก / ภูมิใจ** — การทำ lint สำหรับ "ความรู้สึกในการอ่าน" เป็นเรื่องที่
เครื่องมือทั่วไปไม่ทำให้ — ต้องเขียนเอง

**Migration:** ไม่มี
**อ้างอิง:** PR #95–#97 · main `dad8bec`

---

## [1.28.0] — 2026-10-27 — P1.4 แยก shell components + IA มือถือ 5 ช่อง

**บริบท ณ ตอนนั้น** — `MainLayout.vue` โตถึง 988 บรรทัด และเมนูมือถือมี 4 แท็บ
ที่ไม่ได้สะท้อนงานที่ใช้จริง (กิจกรรม/ตารางเรียนถูกซ่อน)

**สิ่งที่ทำ** — PR #98 แตก `MainLayout.vue` เป็น `layouts/shell/`:
`useAppShell.ts`, `useProfileDialogs.ts`, `AppSidebar.vue`, `AppHeader.vue`,
`AppBottomNav.vue`, `AppMoreSheet.vue`, `AppMenus.vue` — เหลือ ~150 บรรทัด
จัด IA มือถือเป็น **5 ช่อง**: หน้าหลัก · นักเรียน · งาน · การเงิน + "เพิ่มเติม"
(กิจกรรม/ตารางเรียน/Discord/แผนผัง/ตั้งค่า อยู่ในแผ่น)
เพิ่ม route meta `headerBack` 24 sub-routes และลบปุ่มย้อนซ้ำ 17 วิว

**ตัดสินใจเพราะ** — มือถือควรมีทางเข้าหลัก 4 ทาง + ทางเข้าอื่นในแผ่น
เพราะแถบล่างที่แน่นเกินไปทำให้กดพลาด — `> ที่มา: PR #98 body`

**เทคโนโลยีที่เปลี่ยน/ลอง** — Composables (`useAppShell`, `useProfileDialogs`),
single source ของ "ทางกลับ"

**พังแล้วแก้อย่างไร** — ปุ่มย้อนซ้ำสองที่ (ใน header + ในหน้า) ทำให้สับสน
— ลบออก 17 วิวแล้วใช้ route meta แทน

**เปลี่ยน**
- โครงสร้าง layout
- IA มือถือ

**สิ่งที่ยาก / ภูมิใจ** — การตัดสินใจว่า "5 ช่อง" คือการเลือกว่าจะซ่อนอะไร
— ซึ่งต้องเข้าใจงานจริงของผู้ใช้ ไม่ใช่แค่จัดของให้พอดี

**Migration:** ไม่มี
**อ้างอิง:** PR #98 · main `ab4daa7`

---

## [1.29.0] — 2026-10-31 — ระบบ versioning + ประวัติย้อนหลัง 55 versions

**บริบท ณ ตอนนั้น** — ระบบเดินมา 7 เดือนครึ่ง มี 741 commits, 95 PR, 4 ประวัติที่หลอมรวม
แต่ **ไม่มีเลขเวอร์ชันที่เชื่อถือได้**: `PROJECT_VERSION` เป็น `"1.0.0"` ที่ไม่มีใครใช้,
`package.json` เป็น `"0.0.0"`, ไม่มี tag, ไม่มี Release, และตอบไม่ได้ว่า production
รันโค้ดชุดไหน

**สิ่งที่ทำ** — งานนี้คือการสร้างระบบ versioning ที่ย้อนกลับไปเล่าประวัติทั้งหมด:
- **`CHANGELOG.md` 56 versions** — เขียนเชิงบรรยายทุกเวอร์ชัน (บริบท/สิ่งที่ทำ/ตัดสินใจ/
เทคโนโลยี/พังแล้วแก้/สิ่งที่ภูมิใจ) ไม่ใช่แค่รายการ commit
- **`scripts/version-manifest.tsv`** — แหล่งความจริงเดียวของ 56 versions + cut commit
  + PR coverage; ตรวจด้วย `scripts/version-manifest.mjs`
- **Backend** — `PROJECT_VERSION = 1.29.0`, `GIT_SHA` จาก build arg,
  `GET /api/version` (no-store)
- **Frontend** — `__APP_VERSION__` จาก package.json, แสดง `v1.29.0 · <sha>` ในเมนูโปรไฟล์,
  เรียก `/api/version` เพื่อยืนยัน sha ที่รันจริง
- **Root/deploy** — `VERSION`, `release.sh` (sync 4 ไฟล์ → commit → annotated tag →
  push → `gh release create`), `rollback.sh <image-tag>` (แทนการถอย 1 commit),
  `pull_all.sh` ส่ง `--build-arg GIT_SHA`
- **Tags + GitHub Releases ย้อนหลัง 55 อัน** — v0.x เป็น prerelease, `--latest=false`,
  body ระบุ component tips ของวันที่นั้น และบอกว่า backfilled
- **Branch cleanup** — backup bundle ก่อนลบ branch ที่ merge แล้ว
- **CI version gate** — `VERSION` = `PROJECT_VERSION` = `package.json` = `package-lock.json`
  และ CHANGELOG มี section ของ version นั้น

**ตัดสินใจเพราะ** — version ต้องตอบได้สามคำถาม: **โค้ดไหน** (tag/commit),
**อะไรเปลี่ยน** (CHANGELOG), **รันจริงหรือเปล่า** (`/api/version` + GIT_SHA)
— ทั้งสามต้องมาจากแหล่งเดียว ไม่ใช่จดมือ — `> ที่มา: แผนงาน versioning ที่อนุมัติ`

**เทคโนโลยีที่เปลี่ยน/ลอง** — SemVer แบบปรับให้เข้ากับ multi-root history,
GIT_SHA provenance ผ่าน Docker build arg, annotated tag + `gh release --verify-tag`,
advisory-lock migration ที่มีอยู่แล้ว

**พังแล้วแก้อย่างไร** — การนับ version ข้าม 4 root ต้องใช้ทั้ง ancestry และ PR state
(เพราะ squash merge ทำให้ ancestry ตรวจไม่ครบ) — และ PR component ใช้เลขซ้ำกับ
monorepo PR จึงต้องกำกับด้วย "bot PR #1", "backend PR #12" ไม่ใช่ "PR #12"

**เพิ่ม**
- CHANGELOG 56 versions
- manifest + verifier
- `/api/version` + GIT_SHA provenance
- `release.sh` / `rollback.sh`
- tags + Releases ย้อนหลัง
- CI version gate

**เปลี่ยน**
- `pull_all.sh` ส่ง GIT_SHA
- เอกสาร versioning เป็นทางการ

**สิ่งที่ยาก / ภูมิใจ** — การเขียนประวัติย้อนหลัง 7 เดือนจาก 741 commits
โดยไม่แต่งเรื่องที่ไม่มีหลักฐาน — ทุกข้อความ "ตัดสินใจ" มีที่มาหรือกำกับว่าเป็นการอนุมาน
และผลลัพธ์คือเอกสารที่เปิดกลับมาอ่านแล้วเห็นว่าตัวเองเดินผ่านอะไรมา

**Migration:** ไม่มี schema change
**อ้างอิง:** PR ถัดไป · release commit `v1.29.0` · manifest 56 แถว

---

## บทส่งท้าย

> 19 มีนาคม 2026 — 4 ไฟล์ 568 บรรทัด ในห้องมืด ๆ คืนหนึ่ง
> 31 ตุลาคม 2026 — 741 commits, 95 PR, 56 versions, ระบบที่โรงเรียนใช้จริงทุกวัน
>
> สิ่งที่เปลี่ยนไม่ใช่แค่จำนวนโค้ด แต่คือ **วิธีคิด**:
> จาก "เขียนให้ทำงาน" → "เขียนให้ตรวจสอบได้"
> จาก "แก้จนหาย" → "พิสูจน์ root cause ก่อนแก้"
> จาก "ของฉันเครื่องเดียว" → "ของโรงเรียนที่ต้องดูแลต่อ"
>
> และจากนี้ไป ทุกเวอร์ชันจะมีเลขของมันเอง — เพื่อให้วันหนึ่งที่กลับมาอ่าน
> จะรู้ว่าตอนนั้นเราอยู่ตรงไหน และเดินมาไกลแค่ไหนแล้ว

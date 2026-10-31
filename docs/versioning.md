# Versioning — นโยบายและวิธีปฏิบัติ

> เอกสารนี้ตอบสามคำถามที่ต้องตอบได้ทุกครั้งหลัง deploy:
> **โค้ดชุดไหน** (tag/commit) · **อะไรเปลี่ยน** (CHANGELOG) · **รันจริงหรือเปล่า** (`/api/version`)

---

## 1. หลักการ

ใช้ **Semantic Versioning** แบบปรับให้เข้ากับโปรเจกต์:

| ระดับ | ใช้เมื่อ |
|---|---|
| **MAJOR** | เปลี่ยนสถาปัตยกรรมหรือโครงสร้างข้อมูล จนของเดิมตีความด้วยกติกาใหม่ไม่ได้ — เลขหน้าเปลี่ยนทันที ประวัติมี 9 ครั้ง (1.0.0–9.0.0) |
| **MINOR** | ผู้ใช้เห็นความสามารถใหม่ หรือ milestone เชิงโครงสร้างที่เปลี่ยนวิธีพัฒนา (monorepo, migrations, versioning) |
| **PATCH** | fix / UI / docs / infra ล้วน |

**1 version = 1 ช่วงงานที่ coherent** — ตัดตามเหตุการณ์ ไม่ตัดตามปฏิทิน
รายละเอียดการนับและเหตุผลของทั้ง 56 versions อยู่ใน `CHANGELOG.md`

จุดที่ major เปลี่ยน (ตัดจาก CHANGELOG §นับเวอร์ชัน):

| major | ตัดที่ | เปลี่ยนอะไร |
|---|---|---|
| 1.0.0 | 2026-05-17 | bot → API client (backend เป็นเจ้าของ DB เดียว) |
| 2.0.0 | 2026-05-24 | PHP → Vue 3 + TypeScript SPA |
| 3.0.0 | 2026-06-01 | 4 repo + submodule → root repo เดียว |
| 4.0.0 | 2026-06-21 | `server_id` → `room_id` จบ |
| 5.0.0 | 2026-06-30 | ประกาศ V1 (major เพราะเป็น release ประกาศ publicly) |
| 6.0.0 | 2026-07-28 | 4 repo หลอมเป็น monorepo ด้วย git subtree |
| 7.0.0 | 2026-08-05 | บัญชีเดี่ยว → บัญชีคู่ |
| 8.0.0 | 2026-08-18 | English-primary identity + `nickname_en` |
| 9.0.0 | 2026-08-25 | Consent Model |

กฎนี้ใช้ย้อนหลังกับทั้ง 56 versions — tag ที่ตรงกันคือ `v1.0.0` … `v9.13.0`

### การนับเลขใหม่ย้อนหลัง (31 ต.ค. 2026)

รอบแรกที่ตั้งระบบนี้ (PR #99) นับ MAJOR แบบ "breaking change ของ API" เลยมี major ตัวเดียวคือ `1.0.0` (V1)
ต่อมาเปลี่ยนกติกาเป็น "เปลี่ยนรากของระบบ" (ภาษา/แพลตฟอร์ม, โครงสร้างข้อมูล, โครง repo) จึงนับใหม่ทั้งประวัติ:

- เลขเก่า `0.1.0`–`1.29.0` → เลขใหม่ `0.1.0`–`9.13.0` · major 9 ตัวตามตารางข้างบน
- tag + GitHub Release ชุดเก่า **ถูกลบทั้งหมด** แล้วสร้างใหม่ใต้เลขใหม่ (`gh release delete --cleanup-tag` ทุกอัน)
  เพราะ GitHub ไม่ให้เปลี่ยนชื่อ tag ของ Release ที่มีอยู่ — ทางเดียวคือลบแล้วสร้าง
- ด่าน linearity ของ manifest เริ่มที่ V1 release (`2026-06-30`) ไม่ใช่ `1.0.0` เพราะก่อนหน้านั้นมี 4 root
- tag `v9.13.0` ชี้ `41dee13` (merge ของ PR #101) — ไม่มี commit `chore(release)` แยก
  เพราะ `VERSION`/`config.py`/`package.json` ถูก sync ไปก่อนหน้าแล้ว `release.sh` จึงไม่ต้อง commit เพิ่ม

ถ้าต้องนับใหม่แบบนี้อีก: แก้ `scripts/version-manifest.tsv` → รัน `node scripts/version-manifest.mjs` ให้ผ่าน →
ลบ Release/tag เก่าทั้งหมด → `./release.sh` สำหรับตัวล่าสุด → `./scripts/backfill-releases.sh tags --push` → `... releases`

---

## 2. แหล่งความจริง

| ไฟล์ | บทบาท |
|---|---|
| `VERSION` (root) | เลขเวอร์ชันปัจจุบัน — แก้ **ที่นี่ที่เดียว** |
| `CHANGELOG.md` | เรื่องเล่าของทุก version + section ที่ใช้เป็น Release notes |
| `scripts/version-manifest.tsv` | ตาราง 56 versions: version / date / cut commit / bump / theme / refs |
| `scripts/version-manifest.mjs` | ตัวตรวจ manifest (จำนวนแถว, SemVer, วันที่, ancestry, PR coverage, CHANGELOG ครบ) |

ตัวเลขทั้งหมดต้อง **derive จาก manifest/git** ไม่ใช่พิมพ์มือ

---

## 3. ไฟล์ที่ต้องตรงกัน (CI บังคับ)

```
VERSION
  = backend/core/config.py :: PROJECT_VERSION
  = frontend/package.json :: version
  = frontend/package-lock.json :: version
  = frontend/package-lock.json :: packages[""].version
```

และต้องมี `## [<version>]` ใน `CHANGELOG.md`
ด่านนี้อยู่ใน `.github/workflows/ci-version.yml` — PR ที่แก้ไฟล์ใดไฟล์หนึ่งจะถูกจับทันที

`release.sh` เป็นตัว sync ทั้ง 4 ไฟล์ให้เอง (ไม่ต้องแก้มือ)

---

## 4. Provenance chain — "รันจริงหรือเปล่า"

```
git commit (HEAD)
   │  pull_all.sh: IMAGE_TAG=$(git rev-parse --short HEAD)
   ▼
docker build --build-arg GIT_SHA=${IMAGE_TAG}
   │  backend/Dockerfile: ARG GIT_SHA=unknown → ENV GIT_SHA
   ▼
backend/core/config.py :: GIT_SHA
   ▼
GET /api/version → { "version": "9.13.0", "git_sha": "ab4daa7", "service": "backend" }
   ▼
frontend (vite define __APP_VERSION__ = package.json.version)
   └─ เมนูโปรไฟล์แสดง  v9.13.0 · ab4daa7
```

กติกา:
- `Cache-Control: no-store` ที่ `/api/version` — ห้ามให้ proxy แคชข้าม deploy
- `ARG GIT_SHA` ต้องอยู่ **หลัง** `COPY . .` ใน Dockerfile เพื่อไม่ให้ layer cache พังทุก commit
- ถ้ารันนอก container `git_sha` = `unknown` — UI จะแสดง `dev`

---

## 5. ออกเวอร์ชันใหม่

```bash
# 1) เขียน CHANGELOG section ก่อน (## [1.30.0] — วันที่ — ธีม)
# 2) แก้ VERSION
echo 1.30.0 > VERSION
# 3) ตรวจก่อน (ไม่เขียน/ไม่ push)
./release.sh --dry-run
# 4) ออกจริง — sync 4 ไฟล์ → commit chore(release) → annotated tag → push → GitHub Release
./release.sh
```

`release.sh` จะ:
1. ตรวจ SemVer / อยู่บน `main` / working tree สะอาด / HEAD = origin/main
2. ตรวจว่ามี `## [x.y.z]` ใน CHANGELOG และยังไม่มี tag ซ้ำ
3. sync 4 ไฟล์
4. commit `chore(release): vX.Y.Z`
5. `git tag -a vX.Y.Z` (annotated เท่านั้น)
6. push `main` + tag
7. `gh release create --verify-tag --title vX.Y.Z --notes-file <CHANGELOG section> --latest`

ห้าม:
- สร้าง tag มือโดยไม่ผ่าน `release.sh` (ยกเว้น backfill ด้านล่าง)
- ใช้ lightweight tag
- แก้ `CHANGELOG` ย้อนหลังหลัง tag แล้วโดยไม่ bump ใหม่

---

## 6. Rollback

| สถานการณ์ | ใช้ |
|---|---|
| ถอย 1 commit (เช่น deploy แล้วพังทันที) | `./oh_shit.sh` |
| ถอยข้ามหลาย PR ไป image ที่รู้ว่าเสถียร | `./rollback.sh <image-tag>` |

`rollback.sh` ตรวจว่ามี image ครบทั้ง backend/frontend/bot ก่อน แล้ว
`docker stack deploy` ด้วย `IMAGE_TAG` ที่ระบุ — ไม่แตะ git

> Image สำหรับ rollback ต้องไม่ถูกลบ: อย่ารัน `docker image prune -a`
> โดยไม่ตรวจรายการ tag ที่ยังต้องใช้

---

## 7. Tag + Release ย้อนหลัง (backfill)

ประวัติก่อน 31 ต.ค. 2026 ไม่มี tag/Release เลย — backfill ตาม manifest:

```bash
./scripts/backfill-releases.sh tags            # สร้าง annotated tag ในเครื่อง
./scripts/backfill-releases.sh tags --push     # push tags
./scripts/backfill-releases.sh releases        # สร้าง GitHub Releases
```

กติกา:
- **idempotent** — มีแล้วข้าม
- body = section จาก CHANGELOG + บรรทัด `_Backfilled on 2026-10-31 ..._`
- v0.x ใส่ `--prerelease`, ทุกอัน `--latest=false` (ไม่ให้ release เก่าทับ "Latest")
- **ไม่ backdate** — วันที่สร้างคือวันนี้ แต่หัวข้อระบุวันที่เดิม

### ข้อจำกัดที่ต้องรู้: ก่อน 28 ก.ค. 2026 ประวัติไม่เป็นเส้นเดียว

มี 4 root (bot, backend, frontend_php, frontend_ts) + root ของ monorepo (1 มิ.ย.)
tag ช่วงนั้นจึงชี้ **snapshot ของ component เดียว** ที่ represent ที่สุดของวันนั้น
Release body ต้องบอกข้อนี้ และ `CHANGELOG` ระบุ component tips ของทุกตัว ณ วันนั้น

---

## 8. Migration กับ version

- `backend/core/migrations/` เป็น **additive เท่านั้น** — ห้าม DROP/ALTER ทำลาย
- ไฟล์ที่ apply แล้วห้ามแก้ (checksum ตรวจเจอ → บูตไม่ขึ้นโดยเจตนา)
- การเปลี่ยน schema ที่ breaking ต้องมี migration ใหม่ + บันทึกใน `**Migration:**` ของ version นั้น
- ณ v9.13.0 ยังไม่มี migration file — schema ยังมาจาก `init_db.py` (ดู `docs/rules/backend.md` §7)

---

## 9. Checklist ก่อน merge งานที่ไม่ใช่ release

- [ ] `node scripts/version-manifest.mjs` ผ่าน
- [ ] ถ้าเพิ่ม version ใหม่: แถวใน manifest + `## [x.y.z]` ใน CHANGELOG + `VERSION` sync
- [ ] `./release.sh --dry-run` ผ่าน (ถ้าเป็นงาน release)
- [ ] `/api/version` ยังคืนค่าได้ (backend test `test_version.py`)

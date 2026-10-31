#!/usr/bin/env bash
# ============================================================
# release.sh — ออกเวอร์ชันใหม่ (ทำที่เดียว ทุกอย่าง sync กัน)
# ============================================================
# ลำดับ:
#   1. ตรวจ VERSION เป็น SemVer + อยู่บน main ที่สะอาดและตรง origin
#   2. ตรวจว่ามี section `## [x.y.z]` ใน CHANGELOG แล้ว
#   3. sync VERSION → backend/core/config.py · frontend/package.json · package-lock.json
#   4. commit `chore(release): vX.Y.Z` → annotated tag → push main + tag
#   5. สร้าง GitHub Release จาก section ใน CHANGELOG
#
# ใช้:  ./release.sh            # ออกจริง
#       ./release.sh --dry-run  # ตรวจทุกอย่าง แต่ไม่เขียน/ไม่ push
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

die() { echo "❌ $*" >&2; exit 1; }
step() { echo "▶️  $*"; }

VERSION="$(tr -d '[:space:]' < VERSION)"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION ไม่ใช่ SemVer: '$VERSION'"

step "เวอร์ชันที่จะออก: v${VERSION}"

# ---- 1. สถานะ repo ----
[[ "$(git branch --show-current)" == "main" ]] || die "release ต้องทำบน main เท่านั้น"
[[ -z "$(git status --porcelain)" ]] || die "working tree ไม่สะอาด — commit หรือ stash ก่อน"
git fetch origin main --quiet
[[ "$(git rev-parse HEAD)" == "$(git rev-parse origin/main)" ]] \
  || die "HEAD ไม่ตรง origin/main — pull ก่อน"

# ---- 2. CHANGELOG ต้องมี section ----
grep -q "^## \[${VERSION}\]" CHANGELOG.md || die "CHANGELOG.md ยังไม่มี section ## [${VERSION}]"
git rev-parse -q --verify "refs/tags/v${VERSION}" >/dev/null && die "tag v${VERSION} มีอยู่แล้ว"

# ---- 3. sync 4 ไฟล์ ----
step "sync VERSION → config.py / package.json / package-lock.json"
# dry-run ต้องไม่ทิ้งไฟล์ที่ถูกแก้ — สำรองไว้แล้วคืนท้ายสคริปต์
BACKUP_DIR=""
if [[ $DRY_RUN -eq 1 ]]; then
  BACKUP_DIR="$(mktemp -d)"
  for f in backend/core/config.py frontend/package.json frontend/package-lock.json; do
    mkdir -p "$BACKUP_DIR/$(dirname "$f")"
    cp "$f" "$BACKUP_DIR/$f"
  done
fi

python3 - "$VERSION" <<'PY'
import json, re, sys
version = sys.argv[1]

p = 'backend/core/config.py'
s = open(p, encoding='utf-8').read()
s2, n = re.subn(r'PROJECT_VERSION: str = "[^"]+"',
                f'PROJECT_VERSION: str = "{version}"', s)
if n != 1:
    raise SystemExit('❌ config.py: ไม่พบ PROJECT_VERSION เพียง 1 จุด')
open(p, 'w', encoding='utf-8').write(s2)

for p, keys in (('frontend/package.json', True), ('frontend/package-lock.json', True)):
    j = json.load(open(p, encoding='utf-8'))
    j['version'] = version
    if 'packages' in j and '' in j['packages']:
        j['packages']['']['version'] = version
    open(p, 'w', encoding='utf-8').write(json.dumps(j, ensure_ascii=False, indent=2) + '\n')
PY

# ---- 4. notes จาก CHANGELOG (ทำก่อน tag — notes ว่างคือห้าม tag) ----
NOTES="$(mktemp)"
trap 'rm -f "$NOTES"; [[ -n "$BACKUP_DIR" ]] && rm -rf "$BACKUP_DIR"' EXIT
python3 - "$VERSION" "$NOTES" <<'PY'
import re, sys
version, out = sys.argv[1], sys.argv[2]
text = open('CHANGELOG.md', encoding='utf-8').read()
m = re.search(rf'^## \[{re.escape(version)}\].*?$', text, re.M)
if not m:
    raise SystemExit(f'ไม่พบ section {version}')
start = m.start()
nxt = re.search(r'^## \[', text[m.end():], re.M)
body = text[start:m.end() + (nxt.start() if nxt else len(text) - m.end())]
open(out, 'w', encoding='utf-8').write(body.strip() + '\n')
PY

[[ -s "$NOTES" ]] || die "notes จาก CHANGELOG ว่าง — ไม่ tag"

# ---- 5. commit + tag ----
if [[ $DRY_RUN -eq 1 ]]; then
  step "dry-run: จะ commit/tag/push แต่ยังไม่ทำ"
  git --no-pager diff --stat
  for f in backend/core/config.py frontend/package.json frontend/package-lock.json; do
    cp "$BACKUP_DIR/$f" "$f"
  done
  step "คืนไฟล์ที่ถูกแก้ระหว่าง dry-run แล้ว"
  exit 0
fi

git add VERSION CHANGELOG.md backend/core/config.py frontend/package.json frontend/package-lock.json
if ! git diff --cached --quiet; then
  git commit -m "chore(release): v${VERSION}"
fi
git tag -a "v${VERSION}" -m "v${VERSION}"

step "push main + tag"
git push origin main
git push origin "v${VERSION}"

step "สร้าง GitHub Release"
gh release create "v${VERSION}" \
  --verify-tag \
  --title "v${VERSION}" \
  --notes-file "$NOTES" \
  --latest

echo "✅ ออก v${VERSION} เรียบร้อย"

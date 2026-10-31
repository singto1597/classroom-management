#!/usr/bin/env bash
# ============================================================
# backfill-releases.sh — สร้าง tag + GitHub Release ย้อนหลังจาก manifest
# ============================================================
# ⚠️ outward-facing: จะไม่ push อะไรถ้าไม่ใส่ --push
#
# ใช้:
#   ./scripts/backfill-releases.sh tags            # สร้าง tag ในเครื่อง
#   ./scripts/backfill-releases.sh tags --push     # + push tags ขึ้น origin
#   ./scripts/backfill-releases.sh releases        # สร้าง GitHub Release (ต้องมี tag บน origin)
#
# idempotent: มี tag/release แล้วข้าม
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-}"
PUSH="${2:-}"
MANIFEST="scripts/version-manifest.tsv"
BACKFILL_DATE="2026-10-31"

[[ "$MODE" == "tags" || "$MODE" == "releases" ]] || {
  echo "ใช้: $0 tags [--push] | releases" >&2; exit 1; }

section_for() {
  python3 - "$1" <<'PY'
import re, sys
version = sys.argv[1]
text = open('CHANGELOG.md', encoding='utf-8').read()
m = re.search(rf'^## \[{re.escape(version)}\].*?$', text, re.M)
if not m:
    sys.exit(f'ไม่พบ section {version}')
nxt = re.search(r'^## \[', text[m.end():], re.M)
body = text[m.start():m.end() + (nxt.start() if nxt else len(text) - m.end())]
print(body.strip())
PY
}

rows() {
  grep -v '^#' "$MANIFEST" | grep -v '^$'
}

if [[ "$MODE" == "tags" ]]; then
  created=0
  new_tags=()
  while IFS=$'\t' read -r version date cut bump theme refs; do
    [[ "$cut" == "RELEASE" ]] && continue
    tag="v${version}"
    if git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
      echo "⏭️  ${tag} มีอยู่แล้ว"
      continue
    fi
    note="${version} — ${theme}
Backfilled ${BACKFILL_DATE} from commit ${cut}."
    if [[ "$date" < "2026-07-28" ]]; then
      note+=$'\n'"Pre-monorepo: tag นี้ชี้ snapshot ของ component ที่ represent ที่สุดของวันนั้น — ไม่ใช่ snapshot ของทั้งระบบ (ดู CHANGELOG)"
    fi
    git tag -a "$tag" "$cut" -m "$note"
    echo "🏷️  ${tag} → ${cut}"
    created=$((created + 1))
    new_tags+=("refs/tags/${tag}")
  done < <(rows)
  echo "✅ สร้าง tag ใหม่ ${created} อัน"

  if [[ "$PUSH" == "--push" ]]; then
    if [[ ${#new_tags[@]} -gt 0 ]]; then
      git push origin "${new_tags[@]}"
      echo "✅ push ${#new_tags[@]} tags ขึ้น origin แล้ว"
    else
      echo "ℹ️  ไม่มี tag ใหม่ให้ push"
    fi
  else
    echo "ℹ️  ยังไม่ push — ตรวจด้วย: git tag -l 'v0.*' | head"
  fi
  exit 0
fi

# ---- releases ----
missing=0
while IFS=$'\t' read -r version date cut bump theme refs; do
  [[ "$cut" == "RELEASE" ]] && continue
  tag="v${version}"
  git rev-parse -q --verify "refs/tags/${tag}" >/dev/null || {
    echo "❌ ไม่มี tag ${tag} — รัน '$0 tags --push' ก่อน" >&2; missing=1; continue; }

  if gh release view "$tag" >/dev/null 2>&1; then
    echo "⏭️  Release ${tag} มีอยู่แล้ว"
    continue
  fi

  notes="$(mktemp)"
  {
    section_for "$version"
    echo
    echo "---"
    echo "_Backfilled on ${BACKFILL_DATE} from pre-existing history. Tag points at \`${cut}\`._"
    if [[ "${version%%.*}" == "0" ]]; then
      echo "_Before monorepo (2026-07-28) history is multi-root; this tag is a snapshot of one component._"
    fi
  } > "$notes"

  args=(release create "$tag" --verify-tag --title "v${version} — ${theme}" --notes-file "$notes" --latest=false)
  [[ "${version%%.*}" == "0" ]] && args+=(--prerelease)
  gh "${args[@]}"
  rm -f "$notes"
done < <(rows)

[[ $missing -eq 0 ]] || exit 1
echo "✅ Release ครบทุก tag ใน manifest"

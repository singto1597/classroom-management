#!/usr/bin/env bash
# ============================================================
# rollback.sh — ถอยแอปกลับไป image tag ที่ระบุ
# ============================================================
# ต่างจาก oh_shit.sh (ถอย git 1 commit): หลัง deploy ข้ามหลาย PR
# image ที่ปลอดภัยอาจอยู่ไกลกว่าหนึ่ง commit — script นี้ระบุ tag ตรง ๆ
#
# ใช้:  ./rollback.sh <image-tag> [--yes]
# ตัวอย่าง: ./rollback.sh d6ef166 --yes
# ============================================================
set -euo pipefail

TAG="${1:-}"
YES="${2:-}"
[[ -n "$TAG" ]] || { echo "ใช้: ./rollback.sh <image-tag> [--yes]" >&2; exit 1; }
[[ -f .env ]] || { echo "❌ ไม่พบ .env" >&2; exit 1; }

set -a
# shellcheck disable=SC1091
source .env
set +a
[[ -n "${ENV_NAME:-}" ]] || { echo "❌ .env ไม่มี ENV_NAME" >&2; exit 1; }

for svc in backend frontend bot; do
  if ! docker image inspect "classroom-${ENV_NAME}-${svc}:${TAG}" >/dev/null 2>&1; then
    echo "❌ ไม่พบ image classroom-${ENV_NAME}-${svc}:${TAG}" >&2
    echo "   ตรวจด้วย: docker images | grep classroom-${ENV_NAME}" >&2
    exit 1
  fi
done

echo "จะ deploy stack ${ENV_NAME}_app ด้วย image tag: ${TAG}"
if [[ "$YES" != "--yes" ]]; then
  read -r -p "ยืนยัน? พิมพ์ 'yes': " answer
  [[ "$answer" == "yes" ]] || { echo "ยกเลิก"; exit 1; }
fi

export IMAGE_TAG="$TAG"
docker stack deploy -c docker-compose.app.yml "${ENV_NAME}_app"
echo "✅ สลับไป ${TAG} แล้ว — ตรวจด้วย: curl -s https://<domain>/api/version"

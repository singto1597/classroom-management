#!/bin/bash
#
# ⚠️ set -euo pipefail — กันบทเรียน 2026-11-25:
#    เดิมสคริปต์นี้ไม่มี `set -e` ⇒ ตอน `docker build` ล้ม (container แก้ DNS ไม่ได้)
#    มันยัง deploy ต่อและพิมพ์ "✅ เสร็จสมบูรณ์" — service ถูกชี้ไป image ที่ไม่มีอยู่
#    (task เก่ายังรันอยู่จึงดูเหมือนสำเร็จ; service ใหม่ขึ้น "No such image" วนไม่หยุด)
#    ทุกคำสั่งที่ล้มต้องหยุดทันที — "deploy ไม่ได้" ต้องดังกว่า "deploy เงียบ ๆ ผิด"
set -euo pipefail

# 1. โหลดตัวแปรจากไฟล์ .env นอกสุด
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo "⚙️ โหลด Environment: $ENV_NAME"
else
    echo "❌ ไม่พบไฟล์ .env"
    exit 1
fi

CURRENT_BRANCH=$(git branch --show-current)
if [ -z "$CURRENT_BRANCH" ]; then
    echo "❌ ไม่สามารถหาชื่อ Branch ได้"
    exit 1
fi

# 2. ดึงโค้ดล่าสุดจาก Monorepo
echo "⬇️ กำลังดึงโค้ดล่าสุดจาก Monorepo..."
git fetch origin
git reset --hard origin/$CURRENT_BRANCH

# --- 🚀 [NEW] ดึงเลข Commit 7 หลักล่าสุดมาใช้เป็นชื่อ Image ---
export IMAGE_TAG=$(git rev-parse --short HEAD)
echo "🏷️ ตรวจพบ Commit ล่าสุด: ${IMAGE_TAG}"

# 3. เตรียมไฟล์ .env ให้ Frontend (Vite) ก่อน Build
echo "📝 คัดลอก .env โยนให้ Frontend..."
cp .env frontend/.env

# 🐳 network ของ build — บนเครื่องนี้ container ปกติ resolve DNS ไม่ได้ (2026-11-25)
#    ⇒ ขั้น `apt-get`/`npm ci` ใน Dockerfile ออกเน็ตไม่ได้ทั้งที่ host ปกติ
#    ใช้ host network ให้ build เห็น resolv.conf ของ host · override ได้ถ้าย้ายเครื่อง:
#    DOCKER_BUILD_NETWORK=default ./pull_all.sh
BUILD_NETWORK="--network=${DOCKER_BUILD_NETWORK:-host}"

# 4. Build Image (ใช้เลข Commit เป็น Tag แทน latest)
echo "🔨 กำลังสร้าง Docker Image เวอร์ชัน: ${IMAGE_TAG} (build network: ${DOCKER_BUILD_NETWORK:-host})..."
docker build $BUILD_NETWORK --build-arg GIT_SHA=${IMAGE_TAG} -t classroom-${ENV_NAME}-backend:${IMAGE_TAG} ./backend
docker build $BUILD_NETWORK -t classroom-${ENV_NAME}-frontend:${IMAGE_TAG} ./frontend
docker build $BUILD_NETWORK -t classroom-${ENV_NAME}-bot:${IMAGE_TAG} ./bot_discord

# 4.1 ตรวจว่า image มีจริงก่อน deploy — `docker stack deploy` ไม่ตรวจให้
#     ถ้าขาดตัวใดตัวหนึ่งให้หยุดก่อนแตะของที่รันอยู่ (เดิมพลาดตรงนี้)
for component in backend frontend bot; do
    if ! docker image inspect classroom-${ENV_NAME}-${component}:${IMAGE_TAG} >/dev/null 2>&1; then
        echo "❌ ไม่พบ image classroom-${ENV_NAME}-${component}:${IMAGE_TAG} — หยุดก่อน deploy"
        exit 1
    fi
done
echo "✅ image ครบ 3 ตัวพร้อม deploy"

# 5. Deploy อัปเดตระบบแบบ Zero Downtime
echo "🚀 กำลังสลับสวิตช์ระบบ $ENV_NAME แบบ Zero Downtime (เวอร์ชัน ${IMAGE_TAG})..."

# 5.1 🖨️ Stack ของ PDF renderer (Gotenberg) — แยกไฟล์จาก infra โดยเจตนา
#     ⚠️ deploy "ก่อน" app เพราะ backend จะเรียกใช้ทันทีที่รับคำขอออกใบเสร็จ
#     ⚠️ ห้ามใช้ --prune กับ stack ไหนในสคริปต์นี้ — `docker stack deploy` ไม่ลบ service
#        ที่หายไปจากไฟล์อยู่แล้ว การเติม --prune คือการเปิดโหมด "ลบสิ่งที่ฉันลืมเขียน"
#     ⚠️ stack นี้ต้องไม่ถูกยุบไปรวมกับ infra: ดูเหตุผลในหัวไฟล์ docker-compose.pdf.yml
echo "🖨️  กำลัง deploy Stack PDF (${ENV_NAME}_pdf)..."
docker stack deploy -c docker-compose.pdf.yml ${ENV_NAME}_pdf

docker stack deploy -c docker-compose.app.yml ${ENV_NAME}_app

# 5.2 ⏳ รอ service ขึ้นครบตาม spec — กันกรณี deploy "สำเร็จ" แต่ task วิ่งไม่ขึ้น
#     (เช่น image หาย, health check ไม่ผ่าน) · ปรับเวลาได้ที่ DEPLOY_WAIT_SECONDS
#
#     ⚠️ นับ replica อย่างเดียวไม่พอ (บทเรียน 2026-11-25 จาก PR #140):
#     update เป็น start-first ⇒ ระหว่าง rollover "3/3" ยังเป็น task เก่าได้ และถ้า
#     FailureAction=pause (ค่าที่ stack นี้ใช้) task ใหม่ที่ขึ้นไม่ได้จะทำให้ swarm
#     "หยุด" การอัปเดต แต่ task เก่ายังรันครบ ⇒ `x/x` + คำว่า "สำเร็จ" = ภาพหลอก
#     ต้องอ่าน `UpdateStatus.State` ของ swarm ซึ่งจะบอกว่า rollover จบจริงหรือไม่
service_update_state() {
    docker service inspect "$1" --format '{{if .UpdateStatus}}{{.UpdateStatus.State}}{{else}}none{{end}}'
}

DEPLOY_WAIT_SECONDS="${DEPLOY_WAIT_SECONDS:-300}"
echo "⏳ รอ service ขึ้นครบและ rollover จบ (สูงสุด ${DEPLOY_WAIT_SECONDS}s)..."
deadline=$((SECONDS + DEPLOY_WAIT_SECONDS))
ready_streak=0
while :; do
    not_ready=""
    for stack in ${ENV_NAME}_pdf ${ENV_NAME}_app; do
        # เก็บผลลัพธ์ก่อนอ่าน — ถ้า docker ล้มต้อง abort ไม่ใช่เห็นเป็น "ว่าง = พร้อม"
        services_out=$(docker stack services "$stack" --format '{{.Name}} {{.Replicas}}')
        while read -r name replicas; do
            [ -z "$name" ] && continue
            # "4/3" ระหว่าง rollover ถือว่ายังไม่นิ่ง — ต้องได้ "x/x" เท่านั้น
            if [ -z "$replicas" ] || [ "${replicas%%/*}" != "${replicas##*/}" ]; then
                not_ready+="  ${name} replicas=${replicas}"$'\n'
            fi
            state=$(service_update_state "$name")
            case "$state" in
                none|completed)
                    ;;
                paused|rollback_started|rollback_paused|rollback_completed)
                    echo "❌ swarm หยุด/ย้อนการอัปเดต ${name} (UpdateStatus=${state})"
                    echo "   task ใหม่ขึ้นไม่ได้ ⇒ task เดิมอาจยังรันครบ (ดูเหมือนสำเร็จแต่เวอร์ชันใหม่ไม่ได้ขึ้น)"
                    echo "   ตรวจ: docker service ps ${name} --no-trunc"
                    echo "   แก้สาเหตุแล้วรัน ./pull_all.sh ใหม่อีกครั้ง — ระหว่างนี้ระบบเดิมยังให้บริการ"
                    exit 1
                    ;;
                *)
                    not_ready+="  ${name} update=${state}"$'\n'
                    ;;
            esac
        done <<< "$services_out"
    done

    if [ -z "$not_ready" ]; then
        # ต้องเห็น "พร้อม" สองครั้งติดกัน — กันจับจังหวะที่ docker stack deploy เพิ่งคืนค่า
        # และ service ยังไม่เริ่มสลับ task (UpdateStatus ยังเป็น completed ของรอบก่อน)
        ready_streak=$((ready_streak + 1))
        if [ "$ready_streak" -ge 2 ]; then
            echo "✅ ทุก service ขึ้นครบตาม spec และ rollover จบแล้ว"
            break
        fi
        sleep 5
        continue
    fi
    ready_streak=0
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "❌ service ไม่ขึ้นครบภายใน ${DEPLOY_WAIT_SECONDS}s:"
        printf '%s' "$not_ready"
        echo "   ตรวจต่อ: docker service ps <service> --no-trunc"
        echo "   ถ้าเห็น 'No such image' ⇒ image ถูก prune/ลบระหว่าง deploy ให้ตรวจ docker images"
        exit 1
    fi
    sleep 5
done

echo "✅ อัปเดตเสร็จสมบูรณ์ ระบบทำงานต่อเนื่องไม่มีสะดุด!"

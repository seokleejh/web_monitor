#!/bin/bash
# ──────────────────────────────────────────────
# Web Monitor - 실행 스크립트
# 사용법: ./run.sh
# ──────────────────────────────────────────────

# ── 설정 ──────────────────────────────────────
URL="http://www.korearandonneurs.kr/reg/register.php"          # 모니터링할 URL
SELECTOR='a[name="2261"] ~ .event-info .event-msg'                        # CSS 선택자 (필요 없으면 빈 칸)
INTERVAL=60                        # 체크 간격 (초)

SMTP_HOST="smtp.gmail.com"
SMTP_USER="arbji.shannon@gmail.com"
EMAIL_FROM="arbji.shannon@gmail.com"
EMAIL_TO="seokleejh@gmail.com"

COOKIES="cookies.json"                         # 필요한 쿠키 (예: "name=value; name2=value2")
#export SMTP_PASSWORD="your-app-password-here"

# SMS 설정 (Twilio) — 사용하지 않으면 주석 처리
TWILIO_ACCOUNT_SID="${TWILIO_ACCOUNT_SID:-}"  # export TWILIO_ACCOUNT_SID='ACxxx...'
SMS_FROM="+12764456574"     # Twilio 발신 번호
SMS_TO="+821023456945"      # 수신 번호
#export TWILIO_AUTH_TOKEN="your-twilio-auth-token"
# ──────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

source .venv/bin/activate

ARGS=(
    --url "$URL"
    --interval "$INTERVAL"
    --smtp-host "$SMTP_HOST"
    --smtp-user "$SMTP_USER"
    --email-from "$EMAIL_FROM"
    --email-to "$EMAIL_TO"
    --cookies "$COOKIES"
)

if [ -n "${TWILIO_ACCOUNT_SID:-}" ]; then
    ARGS+=(--twilio-account-sid "$TWILIO_ACCOUNT_SID" --sms-from "$SMS_FROM" --sms-to "$SMS_TO")
fi

if [ -n "$SELECTOR" ]; then
    ARGS+=(--selector "$SELECTOR")
fi

if [ "${DEBUG:-0}" = "1" ]; then
    echo "디버그 모드: VSCode에서 attach 하세요 (port 5678)"
    python -m debugpy --listen 5678 --wait-for-client src/web_monitor.py "${ARGS[@]}"
else
    python src/web_monitor.py "${ARGS[@]}"
fi

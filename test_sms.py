"""
test_sms.py - SMS 발송 테스트 스크립트
사용법: python test_sms.py
"""

import os
import sys

sys.path.insert(0, "src")
from web_monitor import send_sms_notification

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")  # export TWILIO_ACCOUNT_SID='ACxxx...'
SMS_FROM="+12764456574"     # Twilio 발신 번호
SMS_TO="+821023456945"   # 수신 번호 (본인 휴대폰)

auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
if not auth_token:
    print("오류: TWILIO_AUTH_TOKEN 환경변수가 설정되지 않았습니다.")
    print("  export TWILIO_AUTH_TOKEN='your-token'  후 다시 실행하세요.")
    sys.exit(1)

result = send_sms_notification(
    body="[web_monitor] SMS 테스트 메시지입니다.",
    twilio_account_sid=TWILIO_ACCOUNT_SID,
    twilio_auth_token=auth_token,
    sms_from=SMS_FROM,
    sms_to=SMS_TO,
)

print("발송 성공!" if result else "발송 실패. 위 로그를 확인하세요.")

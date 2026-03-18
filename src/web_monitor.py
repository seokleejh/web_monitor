"""
web_monitor.py - 웹페이지 변경 감지 & 알림 프로그램
=====================================================
사용법:
  python web_monitor.py --url "https://example.com" --interval 60
  python web_monitor.py --url "https://example.com" --selector "#content" --interval 30
  python web_monitor.py --config config.json

필수 패키지 설치:
  pip install requests beautifulsoup4 plyer
"""

import hashlib
import time
import argparse
import json
import logging
import smtplib
import sys
import os
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── 알림 백엔드 설정 ─────────────────────────────────────────
try:
    from plyer import notification as plyer_notification
    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False

# ── 로깅 설정 ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("web_monitor.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("web_monitor")


# ════════════════════════════════════════════════════════════
# 핵심 함수들
# ════════════════════════════════════════════════════════════

def load_cookies(cookies_file: str) -> dict:
    """JSON 쿠키 파일(EditThisCookie / Cookie-Editor 형식)을 dict로 변환합니다."""
    with open(cookies_file, encoding="utf-8") as f:
        raw = json.load(f)
    # EditThisCookie: list of {name, value, ...}
    # Cookie-Editor:  list of {name, value, ...}  (같은 구조)
    return {c["name"]: c["value"] for c in raw}


def fetch_content(url: str, selector: Optional[str], timeout: int, headers: dict,
                  cookies: Optional[dict] = None) -> Optional[str]:
    """URL을 가져와 텍스트(또는 선택자 일치 부분)를 반환합니다."""
    try:
        session = requests.Session()
        session.headers.update(headers)
        if cookies:
            session.cookies.update(cookies)
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        # 로그인 페이지로 리다이렉트됐는지 간단히 감지
        if cookies and resp.url != url and "login" in resp.url.lower():
            log.warning("로그인 페이지로 리다이렉트됨. 쿠키가 만료됐을 수 있습니다: %s", resp.url)
        soup = BeautifulSoup(resp.text, "html.parser")

        if selector:
            elements = soup.select(selector)
            if not elements:
                log.warning("선택자 '%s'에 해당하는 요소를 찾지 못했습니다.", selector)
                return None
            return "\n".join(el.get_text(strip=True) for el in elements)

        # 선택자 없으면 <body> 전체 텍스트 사용
        body = soup.find("body")
        return body.get_text(strip=True) if body else soup.get_text(strip=True)

    except requests.RequestException as e:
        log.error("요청 실패: %s", e)
        return None


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def send_notification(title: str, message: str, url: str):
    """데스크탑 알림 전송 (플랫폼 자동 감지)."""
    log.info("🔔 알림 발송: %s", message)

    if PLYER_AVAILABLE:
        try:
            plyer_notification.notify(
                title=title,
                message=message,
                app_name="Web Monitor",
                timeout=10,
            )
            return
        except Exception as e:
            log.warning("plyer 알림 실패 (%s). 다른 방법 시도...", e)

    # macOS
    if sys.platform == "darwin":
        os.system(f'osascript -e \'display notification "{message}" with title "{title}"\'')
    # Windows
    elif sys.platform == "win32":
        try:
            from win10toast import ToastNotifier
            ToastNotifier().show_toast(title, message, duration=10, threaded=True)
        except ImportError:
            log.warning("win10toast 미설치. 콘솔 출력으로 대체합니다.")
    # Linux
    elif sys.platform.startswith("linux"):
        os.system(f'notify-send "{title}" "{message}"')


def send_email_notification(
    subject: str,
    body: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    email_from: str,
    email_to: str,
    use_tls: bool = True,
) -> bool:
    """이메일 알림 전송 (smtplib 내장 모듈 사용)."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            if use_tls:
                server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(email_from, [email_to], msg.as_string())
        log.info("이메일 발송 완료 → %s", email_to)
        return True
    except Exception as e:
        log.error("이메일 발송 실패: %s", e)
        return False


def load_state(state_file: str) -> dict:
    """상태 파일에서 이전 해시를 불러옵니다."""
    if not os.path.exists(state_file):
        return {}
    with open(state_file, encoding="utf-8") as f:
        return json.load(f)


def save_state(state_file: str, data: dict):
    """상태를 JSON 파일에 저장합니다."""
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info("상태 저장: %s", state_file)


def save_snapshot(content: str, url: str, out_dir: str = "snapshots"):
    """변경 시점의 스냅샷을 파일로 저장합니다."""
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = url.replace("://", "_").replace("/", "_")[:60]
    path = os.path.join(out_dir, f"{ts}_{safe_name}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"URL : {url}\n")
        f.write(f"시각: {datetime.now()}\n")
        f.write("=" * 60 + "\n")
        f.write(content)
    log.info("스냅샷 저장: %s", path)


# ════════════════════════════════════════════════════════════
# 모니터 클래스
# ════════════════════════════════════════════════════════════

class WebMonitor:
    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }

    def __init__(
        self,
        url: str,
        interval: int = 60,
        selector: Optional[str] = None,
        timeout: int = 15,
        save_snapshots: bool = True,
        headers: Optional[dict] = None,
        alert_title: str = "웹페이지 변경 감지!",
        cookies_file: Optional[str] = None,
        smtp_host: Optional[str] = None,
        smtp_port: int = 587,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        email_from: Optional[str] = None,
        email_to: Optional[str] = None,
        use_tls: bool = True,
    ):
        self.url = url
        self.interval = interval
        self.selector = selector
        self.timeout = timeout
        self.save_snapshots = save_snapshots
        self.headers = headers or self.DEFAULT_HEADERS
        self.alert_title = alert_title
        self.cookies: Optional[dict] = None
        if cookies_file:
            try:
                self.cookies = load_cookies(cookies_file)
                log.info("쿠키 로드 완료: %s (%d개)", cookies_file, len(self.cookies))
            except Exception as e:
                log.error("쿠키 파일 로드 실패: %s", e)
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.email_from = email_from
        self.email_to = email_to
        self.use_tls = use_tls
        self._prev_hash: Optional[str] = None
        self._check_count = 0

    @property
    def _email_configured(self) -> bool:
        return all([self.smtp_host, self.smtp_user, self.smtp_password,
                    self.email_from, self.email_to])

    def run(self):
        log.info("=" * 60)
        log.info("모니터링 시작")
        log.info("  URL      : %s", self.url)
        log.info("  선택자   : %s", self.selector or "(전체 body)")
        log.info("  간격     : %d 초", self.interval)
        log.info("=" * 60)

        while True:
            self._check_count += 1
            log.info("[%d회차] 확인 중...", self._check_count)

            content = fetch_content(self.url, self.selector, self.timeout, self.headers, self.cookies)
            if content is None:
                log.warning("콘텐츠를 가져오지 못했습니다. %d초 후 재시도.", self.interval)
                time.sleep(self.interval)
                continue

            current_hash = compute_hash(content)

            if self._prev_hash is None:
                # 최초 실행: 기준값 설정
                self._prev_hash = current_hash
                log.info("기준 해시 등록 완료. 이후 변경 시 알림합니다.")
            elif current_hash != self._prev_hash:
                # 변경 감지!
                msg = f"변경 감지됨 ({datetime.now().strftime('%H:%M:%S')})\n{self.url}"
                send_notification(self.alert_title, msg, self.url)
                if self._email_configured:
                    assert self.smtp_host and self.smtp_user and self.smtp_password
                    assert self.email_from and self.email_to
                    send_email_notification(
                        subject=self.alert_title,
                        body=f"{msg}\n\n이전 해시: {self._prev_hash}\n현재 해시: {current_hash}",
                        smtp_host=self.smtp_host,
                        smtp_port=self.smtp_port,
                        smtp_user=self.smtp_user,
                        smtp_password=self.smtp_password,
                        email_from=self.email_from,
                        email_to=self.email_to,
                        use_tls=self.use_tls,
                    )
                log.warning("★ 변경 감지! 해시: %s → %s", self._prev_hash[:8], current_hash[:8])

                if self.save_snapshots:
                    save_snapshot(content, self.url)

                self._prev_hash = current_hash
            else:
                log.info("변경 없음 (해시: %s...)", current_hash[:12])

            time.sleep(self.interval)

    def run_once(self, state_file: str = "web_monitor_state.json"):
        """한 번만 실행 — GitHub Actions / cron 환경용. 상태 파일로 이전 해시를 유지합니다."""
        log.info("run_once 시작: %s", self.url)
        state = load_state(state_file)
        prev_hash = state.get("hash")

        content = fetch_content(self.url, self.selector, self.timeout, self.headers, self.cookies)
        if content is None:
            log.error("콘텐츠를 가져오지 못했습니다. 종료.")
            sys.exit(1)

        current_hash = compute_hash(content)

        if prev_hash is None:
            log.info("최초 실행: 기준 해시 등록. 알림 없음.")
        elif current_hash != prev_hash:
            log.warning("★ 변경 감지! 해시: %s → %s", prev_hash[:8], current_hash[:8])
            msg = f"변경 감지됨 ({datetime.now().strftime('%H:%M:%S')})\n{self.url}"
            send_notification(self.alert_title, msg, self.url)
            if self._email_configured:
                assert self.smtp_host and self.smtp_user and self.smtp_password
                assert self.email_from and self.email_to
                send_email_notification(
                    subject=self.alert_title,
                    body=f"{msg}\n\n이전 해시: {prev_hash}\n현재 해시: {current_hash}",
                    smtp_host=self.smtp_host,
                    smtp_port=self.smtp_port,
                    smtp_user=self.smtp_user,
                    smtp_password=self.smtp_password,
                    email_from=self.email_from,
                    email_to=self.email_to,
                    use_tls=self.use_tls,
                )
            if self.save_snapshots:
                save_snapshot(content, self.url)
        else:
            log.info("변경 없음 (해시: %s...)", current_hash[:12])

        save_state(state_file, {
            "hash": current_hash,
            "last_checked": datetime.now().isoformat(),
            "url": self.url,
        })


# ════════════════════════════════════════════════════════════
# CLI 진입점
# ════════════════════════════════════════════════════════════

def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description="웹페이지 변경 감지 & 알림 프로그램",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python web_monitor.py --url "https://www.example.com/notice" --interval 120
  python web_monitor.py --url "https://stock.co.kr" --selector ".price-board" --interval 10
  python web_monitor.py --config config.json
        """,
    )
    parser.add_argument("--url", help="모니터링할 URL")
    parser.add_argument("--interval", type=int, default=60, help="체크 간격 (초, 기본값: 60)")
    parser.add_argument("--selector", help="CSS 선택자 (특정 요소만 감지)")
    parser.add_argument("--timeout", type=int, default=15, help="요청 타임아웃 (초)")
    parser.add_argument("--no-snapshot", action="store_true", help="스냅샷 저장 비활성화")
    parser.add_argument("--config", help="JSON 설정 파일 경로")
    # 이메일 설정 (비밀번호는 환경변수 SMTP_PASSWORD 에서만 읽음)
    parser.add_argument("--smtp-host", default=os.environ.get("SMTP_HOST"), help="SMTP 서버 주소")
    parser.add_argument("--smtp-port", type=int, default=int(os.environ.get("SMTP_PORT", 587)), help="SMTP 포트 (기본값: 587)")
    parser.add_argument("--smtp-user", default=os.environ.get("SMTP_USER"), help="SMTP 로그인 계정")
    parser.add_argument("--email-from", default=os.environ.get("EMAIL_FROM"), help="발신 이메일 주소")
    parser.add_argument("--email-to", default=os.environ.get("EMAIL_TO"), help="수신 이메일 주소")
    parser.add_argument("--no-tls", action="store_true", help="TLS 비활성화")
    parser.add_argument("--cookies", help="쿠키 JSON 파일 경로 (로그인 필요 페이지용)")
    # GitHub Actions / cron 모드
    parser.add_argument("--once", action="store_true", help="한 번만 실행 (GitHub Actions 등 cron 환경용)")
    parser.add_argument("--state-file", default="web_monitor_state.json", help="run_once 상태 파일 경로")

    args = parser.parse_args()

    # config.json 우선
    if args.config:
        cfg = load_config(args.config)
    elif args.url:
        cfg = {
            "url": args.url,
            "interval": args.interval,
            "selector": args.selector,
            "timeout": args.timeout,
            "save_snapshots": not args.no_snapshot,
        }
    else:
        parser.print_help()
        sys.exit(1)

    # 이메일 설정 병합 (config.json에 없는 경우 CLI/환경변수 값 사용)
    cfg.setdefault("smtp_host", args.smtp_host)
    cfg.setdefault("smtp_port", args.smtp_port)
    cfg.setdefault("smtp_user", args.smtp_user)
    cfg.setdefault("smtp_password", os.environ.get("SMTP_PASSWORD"))
    cfg.setdefault("email_from", args.email_from)
    cfg.setdefault("email_to", args.email_to)
    cfg.setdefault("use_tls", not args.no_tls)
    cfg.setdefault("cookies_file", args.cookies)

    monitor = WebMonitor(**cfg)
    try:
        if args.once:
            monitor.run_once(state_file=args.state_file)
        else:
            monitor.run()
    except KeyboardInterrupt:
        log.info("사용자 중단. 프로그램을 종료합니다.")


if __name__ == "__main__":
    main()
"""
꿈을펴봐 — 정부 공공자료 자동 다운로드 스크립트

배경:
  Claude의 WebFetch 서비스(외부 IP)는 다수 한국 정부 사이트에서 차단되지만,
  사용자 본인 IP에서 적절한 헤더(User-Agent + Referer)로 요청하면 거의 다 통과한다.
  대한민국 정부 보도자료는 공공저작물(공공누리 1유형)로 자유 사용 가능하다.

목적:
  여가부·교육부·NYPI 등 보도자료 페이지에서 첨부 PDF·HWP·XLSX를 자동 추출·다운로드.
  KOSIS API는 PublicDataReader (인증키 필요).

사용:
  pip install requests beautifulsoup4 PublicDataReader
  python auto_download.py                # 모든 보도자료 페이지 시도
  python auto_download.py --url <PAGE>    # 특정 페이지 1회 시도
  python auto_download.py --kosis        # KOSIS API 데모 (KOSIS_API_KEY 필요)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

# ─────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[2]  # 07_논문/
DATA_ROOT = ROOT / "00_공통" / "데이터" / "원본"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEADERS_BASE = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# 알려진 보도자료 페이지 → 저장 폴더 매핑
TARGETS = [
    {
        "name": "여가부 2024 청소년 매체이용 실태조사",
        "url": "https://www.mogef.go.kr/nw/rpd/nw_rpd_s001d.do?mid=news405&bbtSn=710449",
        "folder": "여성가족부",
        "prefix": "2024_청소년매체이용_",
    },
    {
        "name": "여가부 2025 청소년 미디어 이용습관 진단",
        "url": "https://www.mogef.go.kr/nw/enw/nw_enw_s001d.do?mid=mda700&bbtSn=712710",
        "folder": "여성가족부",
        "prefix": "2025_미디어이용습관_",
    },
    {
        "name": "여가부 2024 청소년 미디어 이용습관 진단",
        "url": "https://www.mogef.go.kr/nw/enw/nw_enw_s001d.do?mid=mda700&bbtSn=712082",
        "folder": "여성가족부",
        "prefix": "2024_미디어이용습관_",
    },
    {
        "name": "교육부 2025 AI 디지털교과서 검정 결과",
        "url": "https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=294&boardSeq=101774&lev=0&m=020402",
        "folder": "교육부",
        "prefix": "2025_AI디지털교과서_",
    },
    {
        "name": "NIA 인터넷이용실태조사 게시판",
        "url": "https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=99870",
        "folder": "NIA",
        "prefix": "인터넷이용실태_",
        "is_list": True,  # 게시판 목록 — 개별 글 다시 들어가야 함
    },
    {
        "name": "NIA 스마트폰 과의존 실태조사 게시판",
        "url": "https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=65914",
        "folder": "NIA",
        "prefix": "과의존_",
        "is_list": True,
    },
]

# 첨부파일 링크로 인식할 패턴 (확장자·키워드)
ATTACH_HINT = re.compile(
    r"(?:download|attach|fileDown|atchfile|streFileNm)",
    re.IGNORECASE,
)
EXT_HINT = re.compile(r"\.(pdf|hwp|hwpx|xlsx?|docx?|zip)(?:\b|\?|$)", re.IGNORECASE)


# ─────────────────────────────────────────────────────────────
# 다운로드 유틸
# ─────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS_BASE)
    return s


def fetch_html(session: requests.Session, url: str, timeout: int = 30) -> str | None:
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return r.text
    except Exception as e:
        print(f"  [실패] HTML 가져오기: {url} — {e}")
        return None


def extract_attachments(html: str, base_url: str) -> list[dict]:
    """페이지 HTML에서 첨부파일 링크와 추정 파일명 추출."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, str] = {}  # url → name

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text(strip=True) or "").replace("/", "_")[:60]

        is_attach = ATTACH_HINT.search(href) or EXT_HINT.search(href)
        is_attach = is_attach or EXT_HINT.search(text)

        if not is_attach:
            continue

        full_url = urljoin(base_url, href)
        if full_url not in found:
            found[full_url] = text or os.path.basename(urlparse(href).path)

    # 첨부파일이 form/javascript: 같은 다른 패턴이라면 추가 휴리스틱
    for input_tag in soup.find_all("input"):
        href = input_tag.get("onclick", "")
        match = re.search(r"['\"]([^'\"]+\.(?:pdf|hwp|hwpx|xlsx?|docx?))['\"]", href, re.I)
        if match:
            full_url = urljoin(base_url, match.group(1))
            if full_url not in found:
                found[full_url] = match.group(1).split("/")[-1]

    return [{"url": u, "name": n} for u, n in found.items()]


def safe_filename(prefix: str, name: str) -> str:
    """파일명 안전화 + 접두어 부착."""
    name = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    if not name or len(name) < 3:
        name = "file"
    if not EXT_HINT.search(name):
        name += ".bin"
    return f"{prefix}{name}"


def download_file(
    session: requests.Session,
    url: str,
    out_path: Path,
    referer: str,
    timeout: int = 120,
) -> bool:
    headers = {**HEADERS_BASE, "Referer": referer}
    try:
        with session.get(url, headers=headers, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        size_mb = out_path.stat().st_size / 1024 / 1024
        print(f"  [성공] {out_path.name} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"  [실패] 다운로드: {url} — {e}")
        return False


# ─────────────────────────────────────────────────────────────
# 보도자료 페이지 처리
# ─────────────────────────────────────────────────────────────

def process_target(session: requests.Session, target: dict) -> tuple[int, int]:
    print(f"\n→ {target['name']}")
    print(f"  URL: {target['url']}")

    html = fetch_html(session, target["url"])
    if not html:
        return 0, 0

    attachments = extract_attachments(html, target["url"])
    print(f"  발견된 첨부파일 후보: {len(attachments)}")

    if not attachments:
        return 0, 0

    folder = DATA_ROOT / target["folder"]
    success = 0
    for a in attachments:
        # 파일명 결정
        name = a["name"]
        if not EXT_HINT.search(name):
            # URL에서 확장자 추출
            path_ext = urlparse(a["url"]).path.split(".")[-1].lower()
            if path_ext in {"pdf", "hwp", "hwpx", "xlsx", "xls", "docx", "zip"}:
                name = f"{name}.{path_ext}"
            else:
                # 확장자 미상 — 일단 시도, 저장 후 file로 판별
                name = f"{name}.bin"

        out_path = folder / safe_filename(target["prefix"], name)
        if out_path.exists() and out_path.stat().st_size > 1024:
            print(f"  [스킵] 이미 있음: {out_path.name}")
            continue

        ok = download_file(session, a["url"], out_path, referer=target["url"])
        if ok:
            success += 1
        time.sleep(1.0)  # 매너 있게

    return success, len(attachments)


# ─────────────────────────────────────────────────────────────
# KOSIS API 데모 (PublicDataReader)
# ─────────────────────────────────────────────────────────────

def kosis_demo() -> None:
    api_key = os.environ.get("KOSIS_API_KEY")
    if not api_key:
        print("⚠ KOSIS_API_KEY 환경변수 없음. https://kosis.kr/openapi/ 에서 발급 후 export.")
        return

    try:
        from PublicDataReader import Kosis
    except ImportError:
        print("⚠ PublicDataReader 미설치. pip install PublicDataReader")
        return

    kosis = Kosis(service_key=api_key)
    # 예시: 주요 통계 목록 조회 (실제 호출은 코드북 확인 후)
    print("✓ KOSIS 객체 생성 성공. 다음 단계: 통계코드 입력 후 get_data 호출.")
    print("  예) 청소년 인구 통계: stat_code='DT_1B040A3'")


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="단일 보도자료 페이지 URL")
    parser.add_argument("--folder", default="기타", help="저장 폴더 (단일 URL 모드)")
    parser.add_argument("--prefix", default="", help="파일명 접두어 (단일 URL 모드)")
    parser.add_argument("--kosis", action="store_true", help="KOSIS API 데모")
    args = parser.parse_args()

    if args.kosis:
        kosis_demo()
        return

    session = make_session()

    if args.url:
        target = {
            "name": "사용자 지정 URL",
            "url": args.url,
            "folder": args.folder,
            "prefix": args.prefix,
        }
        ok, total = process_target(session, target)
        print(f"\n✓ {ok}/{total} 다운로드")
        return

    # 모든 타겟 시도
    total_ok = total_attempted = 0
    for target in TARGETS:
        if target.get("is_list"):
            print(f"\n→ {target['name']} (게시판 목록 — 개별 글 자동 진입은 미구현)")
            print("  사용자 직접 방문 필요: " + target["url"])
            continue
        ok, total = process_target(session, target)
        total_ok += ok
        total_attempted += total

    print(f"\n{'=' * 50}")
    print(f"총 {total_ok}/{total_attempted} 다운로드 성공.")
    print("저장 위치: " + str(DATA_ROOT))


if __name__ == "__main__":
    main()

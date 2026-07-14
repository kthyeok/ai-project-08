from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_POSTS = ROOT / "data" / "sample_posts.json"
AUTH_STATE = ROOT / ".auth" / "naver_state.json"


def date_range(start_date: str, end_date: str) -> list[str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def in_date_range(value: str | None, start_date: str, end_date: str) -> bool:
    if not value:
        return False
    return start_date <= value <= end_date


def load_sample_posts(query: str, start_date: str, end_date: str) -> tuple[list[dict[str, Any]], list[str]]:
    posts = json.loads(SAMPLE_POSTS.read_text(encoding="utf-8"))
    matched = [
        post for post in posts
        if in_date_range(post.get("date"), start_date, end_date)
        and sample_matches_query(post, query)
    ]
    warnings = [
        "샘플 모드입니다. 실제 네이버 카페 데이터가 아니라 하네스 검증용 예시 데이터입니다."
    ]
    if matched:
        return matched, warnings

    generated = generate_query_sample(query, start_date, end_date)
    warnings.append(
        f"'{query}'와 일치하는 샘플 항목이 없어 검색어가 들어간 임시 샘플을 생성했습니다."
    )
    return generated, warnings


def sample_matches_query(post: dict[str, Any], query: str) -> bool:
    topic = str(post.get("topic", ""))
    haystack = " ".join(
        [
            topic,
            str(post.get("title", "")),
            str(post.get("content", "")),
            " ".join(str(comment) for comment in post.get("comments", [])),
        ]
    )
    return query in haystack


def generate_query_sample(query: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    templates = [
        (
            "positive",
            "{query} 지원 정책 반응이 좋습니다",
            "지원 확대와 부담 완화에 도움이 된다는 반응이 있습니다.",
            ["도움 됩니다.", "지원이 더 늘었으면 좋겠어요."],
        ),
        (
            "negative",
            "{query} 관련 조건이 여전히 어렵다는 의견",
            "절차가 어렵고 부담이 크다는 부정적인 반응도 있습니다.",
            ["조건이 까다롭습니다.", "부담이 아직 큽니다."],
        ),
        (
            "neutral",
            "{query} 정보 공유",
            "제도와 신청 방법을 정리한 글입니다.",
            ["정보 감사합니다."],
        ),
    ]
    posts: list[dict[str, Any]] = []
    index = 1
    for day in date_range(start_date, end_date):
        for sentiment, title, content, comments in templates:
            posts.append(
                {
                    "topic": query,
                    "post_id": f"generated-{day}-{index:02d}",
                    "url": f"sample://generated/{day}/{index}",
                    "title": title.format(query=query),
                    "content": content,
                    "comments": comments,
                    "date": day,
                    "observed_date_text": day,
                    "sample_sentiment_hint": sentiment,
                }
            )
            index += 1
    return posts


def collect_from_naver_cafe(
    cafe_url: str,
    query: str,
    start_date: str,
    end_date: str,
    max_posts: int,
    headless: bool = False,
    force_login: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright가 설치되어 있지 않습니다. `pip install -r requirements.txt` 후 "
            "`python -m playwright install chromium`을 실행하세요."
        ) from exc

    warnings: list[str] = []
    AUTH_STATE.parent.mkdir(parents=True, exist_ok=True)
    storage_state = None if force_login or not AUTH_STATE.exists() else str(AUTH_STATE)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(locale="ko-KR", storage_state=storage_state)
        page = context.new_page()

        if force_login or not AUTH_STATE.exists():
            login = context.new_page()
            login.goto("https://nid.naver.com/nidlogin.login", wait_until="domcontentloaded", timeout=60000)
            print("브라우저에서 네이버 로그인을 완료하세요. 로그인 세션이 확인되면 자동으로 다음 단계로 넘어갑니다.")
            _wait_for_naver_login(context, login)
            context.storage_state(path=str(AUTH_STATE))
            login.close()

        try:
            page.goto(cafe_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            _perform_search(page, query)
            page.wait_for_timeout(4000)
            _force_article_search_mode(page)
        except RuntimeError as exc:
            warnings.append(str(exc))

        raw_links = _extract_post_links(page, cafe_url, query=query)
        links = _extract_post_links(
            page,
            cafe_url,
            query=query,
            start_date=start_date,
            end_date=end_date,
        )
        if not raw_links:
            search_warnings = _goto_search_results(page, cafe_url, query)
            warnings.extend(search_warnings)
            page.wait_for_timeout(2500)
            raw_links = _extract_post_links(page, cafe_url, query=query)
            links = _extract_post_links(
                page,
                cafe_url,
                query=query,
                start_date=start_date,
                end_date=end_date,
            )
        if not links:
            if raw_links:
                warnings.append("검색 결과는 있었지만 입력 기간에 해당하는 게시글이 없어 모두 제외했습니다.")
            else:
                warnings.append("검색 결과에서 게시글 링크를 찾지 못했습니다. 네이버 카페 검색 결과 구조 확인이 필요합니다.")

        club_id = extract_club_id_from_url(page.url) or extract_club_id_from_html(page.content())
        posts: list[dict[str, Any]] = []
        for idx, link in enumerate(links[:max_posts], start=1):
            try:
                post = _extract_post(context, link, end_date, idx, club_id=club_id)
            except (PlaywrightError, PlaywrightTimeoutError) as exc:
                warnings.append(f"게시글 수집 실패: {link} ({exc})")
                continue

            parsed_date = post.get("date")
            if not parsed_date:
                warnings.append(f"날짜를 판독하지 못해 제외했습니다: {link}")
                continue
            if not in_date_range(parsed_date, start_date, end_date):
                warnings.append(f"기간 밖 게시글을 제외했습니다: {parsed_date} / {link}")
                continue
            if not post_matches_query(post, query):
                warnings.append(f"검색어가 상세 내용에서 확인되지 않아 제외했습니다: {link}")
                continue
            posts.append(post)

        browser.close()

    return posts, warnings


def _goto_search_results(page: Any, cafe_url: str, query: str) -> list[str]:
    warnings: list[str] = []
    cafe_slug = extract_cafe_slug(cafe_url)
    if not cafe_slug:
        warnings.append(f"카페 URL에서 카페 주소명을 추출하지 못했습니다: {cafe_url}")
        page.goto(cafe_url, wait_until="domcontentloaded", timeout=60000)
        _perform_search(page, query)
        return warnings

    search_url = (
        "https://search.naver.com/search.naver"
        f"?where=article&st=date&cafe_url={quote_plus(cafe_slug)}&query={quote_plus(query)}"
    )
    page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    return warnings


def extract_cafe_slug(cafe_url: str) -> str:
    parsed = urlparse(cafe_url)
    parts = [part for part in parsed.path.split("/") if part]
    return parts[0] if parts else ""


def extract_club_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    match = re.search(r"/cafes/(\d+)", parsed.path)
    if match:
        return match.group(1)
    match = re.search(r"(?:^|[?&])(?:clubid|clubId|cafeId)=(\d+)", parsed.query)
    return match.group(1) if match else ""


def _wait_for_naver_login(context: Any, page: Any, timeout_seconds: int = 180) -> None:
    started = time.time()
    while time.time() - started < timeout_seconds:
        cookies = context.cookies(["https://www.naver.com", "https://nid.naver.com"])
        names = {cookie.get("name") for cookie in cookies}
        if {"NID_AUT", "NID_SES"} & names:
            return
        page.wait_for_timeout(1000)
    raise RuntimeError("네이버 로그인 세션을 확인하지 못했습니다. 다시 실행하거나 --force-login으로 재시도하세요.")


def _perform_search(page: Any, query: str) -> None:
    input_selectors = [
        "#topLayerQueryInput",
        "input[placeholder*='검색']",
        "input[name='query']",
        "input[type='search']",
        "input[type='text']",
    ]
    button_selectors = [
        ".btn",
        "button:has-text('검색')",
        "a:has-text('검색')",
        "input[type='submit'][value*='검색']",
    ]

    search_input = _first_visible_locator(page, input_selectors)
    if search_input is None:
        raise RuntimeError("카페 검색 입력창을 찾지 못했습니다.")

    search_input.fill(query)
    search_button = _first_visible_locator(page, button_selectors)
    if search_button is not None:
        search_button.click()
    else:
        search_input.press("Enter")


def _force_article_search_mode(page: Any) -> None:
    current_url = page.url
    if "ta=ARTICLE_COMMENT" not in current_url:
        return
    article_url = current_url.replace("ta=ARTICLE_COMMENT", "ta=ARTICLE")
    page.goto(article_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)


def _first_visible_locator(page: Any, selectors: list[str]) -> Any | None:
    for frame in page.frames:
        for selector in selectors:
            try:
                locator = frame.locator(selector)
                count = min(locator.count(), 50)
                for index in range(count):
                    item = locator.nth(index)
                    if item.is_visible(timeout=300):
                        return item
            except Exception:
                continue
    return None


def _extract_post_links(
    page: Any,
    base_url: str,
    query: str = "",
    start_date: str = "",
    end_date: str = "",
) -> list[str]:
    candidates: list[str] = []
    cafe_slug = extract_cafe_slug(base_url)
    for frame in page.frames:
        try:
            links = frame.locator("a")
            count = min(links.count(), 600)
        except Exception:
            continue
        for index in range(count):
            link = links.nth(index)
            try:
                href = link.get_attribute("href")
                text = link.inner_text(timeout=500).strip()
                nearby_text = _nearby_text(link)
                row_text = _row_text(link)
            except Exception:
                continue
            if not href or not text:
                continue
            combined_text = f"{text} {nearby_text} {row_text}"
            if query and query not in combined_text:
                continue
            if start_date and end_date:
                result_date = parse_search_result_date(row_text or nearby_text, end_date)
                if result_date and not in_date_range(result_date, start_date, end_date):
                    continue
            lower = href.lower()
            absolute = urljoin(base_url, href)
            if _looks_like_article_url(absolute, cafe_slug):
                candidates.append(absolute)

    deduped: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        key = extract_article_id(url) or url
        if key not in seen:
            deduped.append(url)
            seen.add(key)
    return deduped


def _nearby_text(locator: Any) -> str:
    try:
        return locator.evaluate(
            """element => {
                let current = element;
                for (let depth = 0; depth < 4 && current; depth += 1, current = current.parentElement) {
                    const text = (current.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (text.length > 20) return text.slice(0, 700);
                }
                return (element.innerText || '').replace(/\\s+/g, ' ').trim();
            }"""
        )
    except Exception:
        return ""


def _row_text(locator: Any) -> str:
    try:
        return locator.evaluate(
            """element => {
                const row = element.closest('tr');
                if (row) return (row.innerText || '').replace(/\\s+/g, ' ').trim();
                const item = element.closest('li, [class*="item"], [class*="board-list"]');
                if (item) return (item.innerText || '').replace(/\\s+/g, ' ').trim();
                return '';
            }"""
        )
    except Exception:
        return ""


def parse_search_result_date(text: str, reference_date: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    full = re.search(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})", normalized)
    if full:
        return f"{int(full.group(1)):04d}-{int(full.group(2)):02d}-{int(full.group(3)):02d}"

    short_year = re.search(r"(?<!\d)(\d{2})[.]\s*(\d{1,2})[.]\s*(\d{1,2})[.]", normalized)
    if short_year:
        return f"20{int(short_year.group(1)):02d}-{int(short_year.group(2)):02d}-{int(short_year.group(3)):02d}"

    reference = date.fromisoformat(reference_date)
    month_day = re.search(r"(?<!\d)(\d{1,2})[.월/\-]\s*(\d{1,2})(?:[.일]|\s|$)", normalized)
    if month_day:
        return f"{reference.year:04d}-{int(month_day.group(1)):02d}-{int(month_day.group(2)):02d}"

    return None


def _looks_like_article_url(url: str, cafe_slug: str) -> bool:
    parsed = urlparse(url)
    if "cafe.naver.com" not in parsed.netloc:
        return False
    lower_path = parsed.path.lower()
    lower_query = parsed.query.lower()
    if "articleread" in lower_path or "articleid" in lower_query or "/articles/" in lower_path:
        return True
    if cafe_slug:
        pattern = rf"^/{re.escape(cafe_slug)}/\d+"
        return re.search(pattern, parsed.path) is not None
    return False


def post_matches_query(post: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        [
            str(post.get("title", "")),
            str(post.get("content", "")),
            " ".join(str(comment) for comment in post.get("comments", [])),
        ]
    )
    return query in haystack


def _extract_post(
    context: Any,
    url: str,
    reference_date: str,
    index: int,
    club_id: str = "",
) -> dict[str, Any]:
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1200)

    title, content, observed_date, comments = _extract_current_page_fields(page)

    mobile_url = build_mobile_article_url(url, page.content(), club_id=club_id)
    if mobile_url:
        page.goto(mobile_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        mobile_title, mobile_content, mobile_date, mobile_comments = _extract_current_page_fields(page)
        if mobile_title or mobile_content:
            title = mobile_title or title
            content = mobile_content or content
            observed_date = mobile_date or observed_date
            comments = mobile_comments or comments

    page.close()

    parsed_date = parse_date_text(observed_date, reference_date)
    return {
        "post_id": f"live-{index:03d}",
        "url": url,
        "title": title,
        "content": content,
        "comments": comments,
        "date": parsed_date or "",
        "observed_date_text": observed_date,
    }


def build_mobile_article_url(url: str, html_text: str, club_id: str = "") -> str | None:
    article_id = extract_article_id(url)
    club_id = club_id or extract_club_id_from_html(html_text)
    if not article_id or not club_id:
        return None
    return f"https://m.cafe.naver.com/ca-fe/web/cafes/{club_id}/articles/{article_id}"


def extract_article_id(url: str) -> str:
    parsed = urlparse(url)
    article_path_match = re.search(r"/articles/(\d+)", parsed.path)
    if article_path_match:
        return article_path_match.group(1)
    query_match = re.search(r"(?:^|&)articleid=(\d+)", parsed.query, flags=re.IGNORECASE)
    if query_match:
        return query_match.group(1)
    path_match = re.search(r"/(\d+)(?:$|[/?#])", parsed.path)
    return path_match.group(1) if path_match else ""


def extract_club_id_from_html(html_text: str) -> str:
    patterns = [
        r"clubid\s*[=:]\s*['\"]?(\d+)",
        r"clubId\s*[=:]\s*['\"]?(\d+)",
        r"g_sClubId\s*=\s*['\"]?(\d+)",
        r"cafeId\s*[=:]\s*['\"]?(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if match:
            return match.group(1)
    return ""


def _extract_current_page_fields(page: Any) -> tuple[str, str, str, list[str]]:
    title = _first_text(
        page,
        [
            "h2",
            ".tit",
            ".title_text",
            "h3.title_text",
            ".ArticleTitle",
            "h1",
        ],
    )
    content = _best_text(
        page,
        [
            ".se-main-container",
            "#tbody",
            ".article_viewer",
            ".ContentRenderer",
            ".article_container",
            "article",
            "[class*='ArticleContent']",
            "[class*='article_content']",
            "[class*='content']",
        ],
    )
    observed_date = _first_text(
        page,
        [
            ".ArticleWriter .date",
            ".date",
            ".article_info .date",
            "span[class*='date']",
            "time",
        ],
    )
    if not observed_date:
        body_text = _first_text(page, ["body"])
        observed_date = extract_date_from_text(body_text)
    comments = _many_texts(
        page,
        [
            ".comment_text_box .text_comment",
            ".CommentItem .text_comment",
            ".comment_text_view",
            "span.text_comment",
            "[class*='comment'] [class*='text']",
            "[class*='Comment']",
        ],
        limit=80,
    )
    return title, content, observed_date, comments


def _first_text(page: Any, selectors: list[str]) -> str:
    for frame in page.frames:
        for selector in selectors:
            try:
                locator = frame.locator(selector)
                count = min(locator.count(), 30)
                for index in range(count):
                    item = locator.nth(index)
                    text = item.inner_text(timeout=800).strip()
                    if text:
                        return text
            except Exception:
                continue
    return ""


def _best_text(page: Any, selectors: list[str]) -> str:
    best = ""
    for frame in page.frames:
        for selector in selectors:
            try:
                locator = frame.locator(selector)
                count = min(locator.count(), 30)
            except Exception:
                continue
            for index in range(count):
                try:
                    text = locator.nth(index).inner_text(timeout=700).strip()
                except Exception:
                    continue
                if not text or "네트워크 문제" in text or "로그인이 필요" in text:
                    continue
                if len(text) > len(best):
                    best = text
    return best


def _many_texts(page: Any, selectors: list[str], limit: int) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for frame in page.frames:
        for selector in selectors:
            try:
                locator = frame.locator(selector)
                count = min(locator.count(), limit)
            except Exception:
                continue
            for index in range(count):
                try:
                    text = locator.nth(index).inner_text(timeout=700).strip()
                except Exception:
                    continue
                if text and text not in seen:
                    values.append(text)
                    seen.add(text)
            if values:
                return values[:limit]
    return values[:limit]


def extract_date_from_text(text: str) -> str:
    if not text:
        return ""
    full = re.search(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})(?:[.\s일]|$)", text)
    if full:
        return f"{int(full.group(1)):04d}.{int(full.group(2)):02d}.{int(full.group(3)):02d}."
    short = re.search(r"(\d{2})[.]\s*(\d{1,2})[.]\s*(\d{1,2})[.]", text)
    if short:
        return f"20{int(short.group(1)):02d}.{int(short.group(2)):02d}.{int(short.group(3)):02d}."
    return ""


def parse_date_text(text: str, reference_date: str) -> str | None:
    if not text:
        return None
    value = re.sub(r"\s+", " ", text).strip()
    reference = date.fromisoformat(reference_date)

    if "오늘" in value or "분 전" in value or "시간 전" in value:
        return reference_date

    full = re.search(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})", value)
    if full:
        return f"{int(full.group(1)):04d}-{int(full.group(2)):02d}-{int(full.group(3)):02d}"

    short = re.search(r"(\d{1,2})[.월/\-]\s*(\d{1,2})", value)
    if short:
        return f"{reference.year:04d}-{int(short.group(1)):02d}-{int(short.group(2)):02d}"

    return None

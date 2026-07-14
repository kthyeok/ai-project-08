from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 fallback
    ZoneInfo = None

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from collector import collect_from_naver_cafe, load_sample_posts
from renderer import LABELS, render_outputs
from sentiment import analyze_posts, date_range, period_label


CAFE_URL = "https://cafe.naver.com/jihosoccer123"
WORKSPACE = ROOT / "_workspace"
OUTPUT = ROOT / "output"


def main() -> int:
    args = parse_args()
    start_date, end_date = resolve_period(args)
    result = run_pipeline(
        query=args.query,
        start_date=start_date,
        end_date=end_date,
        cafe_url=args.cafe_url,
        max_posts=args.max_posts,
        sample=args.sample,
        headless=args.headless,
        force_login=args.force_login,
    )

    analysis = result["analysis"]
    output_paths = result["output_paths"]
    print("하네스 실행 완료")
    print(f"- 기간: {analysis['period_label']}")
    print(f"- 실행 모드: {analysis['source_mode']}")
    print(f"- 우세 반응: {LABELS.get(analysis['dominant'], '중립/혼합')}")
    print(f"- HTML: {output_paths['html']}")
    print(f"- SVG: {output_paths['svg']}")
    print(f"- 검증: {WORKSPACE / '05_validation_report.md'}")
    return 0


def run_pipeline(
    query: str,
    start_date: str,
    end_date: str,
    cafe_url: str = CAFE_URL,
    max_posts: int = 30,
    sample: bool = False,
    headless: bool = False,
    force_login: bool = False,
) -> dict[str, Any]:
    validate_date(start_date)
    validate_date(end_date)
    if start_date > end_date:
        raise ValueError("from-date는 to-date보다 늦을 수 없습니다.")

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    args = SimpleNamespace(
        query=query,
        cafe_url=cafe_url,
        max_posts=max_posts,
        sample=sample,
        headless=headless,
        force_login=force_login,
    )
    write_input(args, start_date, end_date)

    if sample:
        posts, warnings = load_sample_posts(query, start_date, end_date)
        source_mode = "sample"
    else:
        posts, warnings = collect_from_naver_cafe(
            cafe_url=cafe_url,
            query=query,
            start_date=start_date,
            end_date=end_date,
            max_posts=max_posts,
            headless=headless,
            force_login=force_login,
        )
        source_mode = "live"

    collection = {
        "source_mode": source_mode,
        "cafe_url": cafe_url,
        "query": query,
        "start_date": start_date,
        "end_date": end_date,
        "period_label": period_label(start_date, end_date),
        "post_count": len(posts),
        "warnings": warnings,
        "posts": posts,
    }
    write_json(WORKSPACE / "01_collected_posts.json", collection)
    write_collection_report(collection)

    analysis = analyze_posts(posts, query, start_date, end_date)
    analysis["source_mode"] = source_mode
    analysis["warnings"] = warnings
    write_json(WORKSPACE / "02_sentiment_analysis.json", analysis)
    write_analysis_report(analysis)

    output_paths = render_outputs(analysis, OUTPUT)
    write_visualization_spec(analysis, output_paths)
    validation = validate_pipeline(collection, analysis, output_paths)
    write_validation_report(validation)
    write_output_report(analysis, output_paths, validation)

    return {
        "collection": collection,
        "analysis": analysis,
        "output_paths": output_paths,
        "validation": validation,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Naver Cafe keyword sentiment harness")
    parser.add_argument("--query", required=True, help="분석할 검색어")
    parser.add_argument("--cafe-url", default=CAFE_URL, help="네이버 카페 URL")
    parser.add_argument("--date", help="단일 분석 날짜(YYYY-MM-DD). --from-date/--to-date 대신 사용 가능")
    parser.add_argument("--from-date", help="분석 시작 날짜(YYYY-MM-DD)")
    parser.add_argument("--to-date", help="분석 종료 날짜(YYYY-MM-DD)")
    parser.add_argument("--max-posts", type=int, default=30, help="라이브 모드에서 수집할 최대 게시글 수")
    parser.add_argument("--sample", action="store_true", help="네이버 접속 없이 샘플 데이터로 실행")
    parser.add_argument("--headless", action="store_true", help="라이브 모드 브라우저를 headless로 실행")
    parser.add_argument("--force-login", action="store_true", help="저장된 네이버 세션을 무시하고 다시 로그인")
    return parser.parse_args()


def resolve_period(args: argparse.Namespace) -> tuple[str, str]:
    if args.date:
        start_date = args.date
        end_date = args.date
    else:
        today = today_seoul()
        start_date = args.from_date or args.to_date or today
        end_date = args.to_date or args.from_date or today

    validate_date(start_date)
    validate_date(end_date)
    if start_date > end_date:
        raise SystemExit("--from-date는 --to-date보다 늦을 수 없습니다.")
    return start_date, end_date


def validate_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit(f"날짜 형식이 올바르지 않습니다: {value} (예: 2026-07-14)") from exc


def today_seoul() -> str:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        except Exception:
            pass
    return datetime.now().date().isoformat()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_input(args: argparse.Namespace, start_date: str, end_date: str) -> None:
    lines = [
        "# 00 입력 정리",
        "",
        "- 하네스 주제: 네이버 카페 검색어 기간 반응 감성 분석",
        f"- 대상 카페: {args.cafe_url}",
        f"- 검색어: {args.query}",
        f"- 분석 기간: {period_label(start_date, end_date)}",
        f"- 실행 모드: {'sample' if args.sample else 'live'}",
        f"- 최대 게시글 수: {args.max_posts}",
        "",
        "## 입력 → 처리 → 검증 → 출력",
        "",
        "1. 입력: 카페 URL, 검색어, 시작일, 종료일, 최대 게시글 수를 받는다.",
        "2. 처리: 로그인 브라우저 또는 샘플 데이터로 제목/본문/댓글을 수집하고 기간으로 필터링한다.",
        "3. 분석: 기간 전체와 일자별 긍정/부정/중립 감성 점수를 계산한다.",
        "4. 검증: 수집 건수, 감성 카운트 합계, 일자별 카운트, 출력 파일 존재 여부를 확인한다.",
        "5. 출력: 기간 전체 가로바와 일자별 상세 결과가 포함된 HTML 리포트를 생성한다.",
    ]
    (WORKSPACE / "00_input.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_collection_report(collection: dict[str, Any]) -> None:
    lines = [
        "# 01 데이터 수집 보고서",
        "",
        f"- 수집 모드: {collection['source_mode']}",
        f"- 대상 카페: {collection['cafe_url']}",
        f"- 검색어: {collection['query']}",
        f"- 분석 기간: {collection['period_label']}",
        f"- 수집 게시글 수: {collection['post_count']}",
        "",
        "## 수집 항목",
        "",
        "- 제목(title)",
        "- 본문(content)",
        "- 댓글(comments)",
        "- 게시일(date)",
        "- 원문 URL(url)",
        "",
        "## 수집 결과 요약",
    ]
    for post in collection["posts"]:
        lines.append(
            f"- [{post.get('date', '-')}] {post.get('title', '(제목 없음)')} / 댓글 {len(post.get('comments', []))}개"
        )

    lines += ["", "## 제한 및 경고"]
    if collection["warnings"]:
        lines.extend([f"- {warning}" for warning in collection["warnings"]])
    else:
        lines.append("- 없음")

    (WORKSPACE / "01_data_collection.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_analysis_report(analysis: dict[str, Any]) -> None:
    counts = analysis["counts"]
    ratios = analysis["ratios"]
    lines = [
        "# 02 감성 분석 보고서",
        "",
        f"- 검색어: {analysis['query']}",
        f"- 분석 기간: {analysis['period_label']}",
        f"- 전체 게시글: {analysis['total_posts']}건",
        f"- 전체 댓글: {analysis['total_comments']}개",
        f"- 우세 반응: {LABELS.get(analysis['dominant'], '중립/혼합')}",
        "",
        "## 기간 전체 감성 분포",
        "",
        f"- 긍정: {counts['positive']}건 ({ratios['positive'] * 100:.1f}%)",
        f"- 부정: {counts['negative']}건 ({ratios['negative'] * 100:.1f}%)",
        f"- 중립: {counts['neutral']}건 ({ratios['neutral'] * 100:.1f}%)",
        "",
        "## 일자별 감성 분포",
    ]
    for day in analysis["daily"]:
        day_counts = day["counts"]
        lines.append(
            f"- {day['period_label']}: {LABELS.get(day['dominant'], '중립/혼합')} / "
            f"긍정 {day_counts['positive']}, 부정 {day_counts['negative']}, 중립 {day_counts['neutral']}, "
            f"게시글 {day['total_posts']}건"
        )

    lines += ["", "## 게시글별 판정"]
    for post in analysis["posts"]:
        terms = ", ".join(post["evidence_terms"]) if post["evidence_terms"] else "근거 키워드 없음"
        lines.append(f"- [{post['date']}] {post['sentiment']} / {post['score']}점 / {post['title']} / {terms}")

    lines += [
        "",
        "## 분석 방식",
        "",
        "- 검색어 자체가 감성 점수에 과도하게 반영되지 않도록 제목/본문/댓글에서 정확히 일치하는 검색어를 제거한 뒤 점수화한다.",
        "- 제목은 본문보다 의도가 강하게 드러난다고 보고 2배 가중치를 적용한다.",
        "- 댓글은 각 댓글의 감성 키워드를 합산해 게시글 점수에 반영한다.",
        "- 점수 2 이상은 긍정, -2 이하는 부정, 그 사이는 중립으로 분류한다.",
    ]
    (WORKSPACE / "02_analysis_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_visualization_spec(analysis: dict[str, Any], output_paths: dict[str, str]) -> None:
    dominant = analysis["dominant"]
    color_rule = {
        "positive": "초록색(#2f9e44)",
        "negative": "빨간색(#e03131)",
        "neutral": "회색(#868e96)",
    }
    lines = [
        "# 03 시각화 명세",
        "",
        "- 그래프 유형: 기간 전체 단일 가로바 + HTML 일자별 상세 바",
        f"- 기간 전체 막대 의미: 우세 반응 비율 {analysis['dominant_ratio'] * 100:.1f}%",
        f"- 색상 규칙: {color_rule.get(dominant, '회색')}",
        "- 일자별 보기: 날짜별 게시글 수, 댓글 수, 긍정/부정/중립 건수와 게시글 테이블",
        "",
        "## 출력 파일",
        "",
        f"- SVG 그래프: {output_paths['svg']}",
        f"- HTML 리포트: {output_paths['html']}",
        f"- JSON 요약: {output_paths['json']}",
    ]
    (WORKSPACE / "03_visualization_spec.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_pipeline(
    collection: dict[str, Any],
    analysis: dict[str, Any],
    output_paths: dict[str, str],
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    post_count = collection["post_count"]
    sentiment_sum = sum(analysis["counts"].values())
    daily_sum = sum(day["total_posts"] for day in analysis.get("daily", []))
    expected_days = len(date_range(collection["start_date"], collection["end_date"]))

    checks.append(
        {
            "name": "게시글 수집",
            "status": "pass" if post_count > 0 else "warning",
            "message": f"{post_count}건 수집",
        }
    )
    checks.append(
        {
            "name": "감성 카운트 합계",
            "status": "pass" if sentiment_sum == analysis["total_posts"] else "fail",
            "message": f"분류 합계 {sentiment_sum}, 전체 {analysis['total_posts']}",
        }
    )
    checks.append(
        {
            "name": "일자별 게시글 합계",
            "status": "pass" if daily_sum == analysis["total_posts"] else "fail",
            "message": f"일자별 합계 {daily_sum}, 전체 {analysis['total_posts']}",
        }
    )
    if post_count != analysis["total_posts"]:
        checks.append(
            {
                "name": "기간 분석 제외 게시글",
                "status": "warning",
                "message": f"수집 {post_count}건 중 날짜 확인 가능한 분석 대상 {analysis['total_posts']}건",
            }
        )
    checks.append(
        {
            "name": "일자별 구간 생성",
            "status": "pass" if len(analysis.get("daily", [])) == expected_days else "fail",
            "message": f"{len(analysis.get('daily', []))}일 생성, 기대 {expected_days}일",
        }
    )
    for label, path in output_paths.items():
        checks.append(
            {
                "name": f"출력 파일 존재: {label}",
                "status": "pass" if Path(path).exists() else "fail",
                "message": path,
            }
        )

    checks.extend(
        {
            "name": f"수집 경고: {index + 1}",
            "status": "warning",
            "message": warning,
        }
        for index, warning in enumerate(collection.get("warnings", []))
    )

    overall = "fail" if any(check["status"] == "fail" for check in checks) else "pass"
    if overall == "pass" and any(check["status"] == "warning" for check in checks):
        overall = "pass_with_warnings"
    return {"overall": overall, "checks": checks}


def write_validation_report(validation: dict[str, Any]) -> None:
    lines = [
        "# 05 검증 보고서",
        "",
        f"- 전체 상태: {validation['overall']}",
        "",
        "## 체크 결과",
    ]
    for check in validation["checks"]:
        lines.append(f"- [{check['status']}] {check['name']}: {check['message']}")

    required = [check for check in validation["checks"] if check["status"] == "fail"]
    recommended = [check for check in validation["checks"] if check["status"] == "warning"]
    lines += ["", "## 필수 수정"]
    lines.extend([f"- {check['name']}: {check['message']}" for check in required] or ["- 없음"])
    lines += ["", "## 권장 확인"]
    lines.extend([f"- {check['name']}: {check['message']}" for check in recommended] or ["- 없음"])
    (WORKSPACE / "05_validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_output_report(
    analysis: dict[str, Any],
    output_paths: dict[str, str],
    validation: dict[str, Any],
) -> None:
    lines = [
        "# 04 출력 보고서",
        "",
        f"- 검색어: {analysis['query']}",
        f"- 분석 기간: {analysis['period_label']}",
        f"- 최종 판정: {LABELS.get(analysis['dominant'], '중립/혼합')}",
        f"- 검증 상태: {validation['overall']}",
        "",
        "## 결과 파일",
        "",
        f"- HTML 리포트: {output_paths['html']}",
        f"- 가로바 SVG: {output_paths['svg']}",
        f"- JSON 요약: {output_paths['json']}",
    ]
    (WORKSPACE / "04_output_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

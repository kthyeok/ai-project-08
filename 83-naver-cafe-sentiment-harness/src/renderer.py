from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


LABELS = {
    "positive": "긍정 우세",
    "negative": "부정 우세",
    "neutral": "중립/혼합",
}

COLORS = {
    "positive": "#2f9e44",
    "negative": "#e03131",
    "neutral": "#868e96",
}


def render_outputs(analysis: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    svg_path = output_dir / "sentiment_bar.svg"
    html_path = output_dir / "index.html"
    json_path = output_dir / "sentiment_summary.json"

    svg = build_svg(analysis)
    svg_path.write_text(svg, encoding="utf-8")
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(build_html(analysis, svg_path.name), encoding="utf-8")

    return {
        "svg": str(svg_path),
        "html": str(html_path),
        "json": str(json_path),
    }


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_svg(analysis: dict[str, Any]) -> str:
    query = html.escape(str(analysis.get("query", "")))
    period = html.escape(str(analysis.get("period_label", "")))
    dominant = analysis.get("dominant", "neutral")
    label = LABELS.get(dominant, "중립/혼합")
    color = COLORS.get(dominant, COLORS["neutral"])
    ratio = float(analysis.get("dominant_ratio", 0) or 0)
    total_posts = int(analysis.get("total_posts", 0) or 0)
    counts = analysis.get("counts", {})

    width = 920
    bar_x = 80
    bar_y = 118
    bar_width = 720
    fill_width = int(bar_width * ratio) if total_posts else 0
    percent = round(ratio * 100, 1)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="240" viewBox="0 0 {width} 240" role="img" aria-label="{label} sentiment bar">
  <rect width="920" height="240" fill="#ffffff"/>
  <text x="40" y="42" font-family="Malgun Gothic, Arial, sans-serif" font-size="24" font-weight="700" fill="#1f2933">{query} 반응 분석</text>
  <text x="40" y="72" font-family="Malgun Gothic, Arial, sans-serif" font-size="15" fill="#5c6670">{period} · 게시글 {total_posts}건 · 댓글 {analysis.get("total_comments", 0)}개</text>
  <rect x="{bar_x}" y="{bar_y}" width="{bar_width}" height="36" rx="8" fill="#edf1f5"/>
  <rect x="{bar_x}" y="{bar_y}" width="{fill_width}" height="36" rx="8" fill="{color}"/>
  <text x="{bar_x}" y="107" font-family="Malgun Gothic, Arial, sans-serif" font-size="16" font-weight="700" fill="{color}">{label}</text>
  <text x="{bar_x + bar_width + 18}" y="{bar_y + 25}" font-family="Malgun Gothic, Arial, sans-serif" font-size="18" font-weight="700" fill="{color}">{percent}%</text>
  <text x="80" y="188" font-family="Malgun Gothic, Arial, sans-serif" font-size="14" fill="#334155">긍정 {counts.get("positive", 0)} · 부정 {counts.get("negative", 0)} · 중립 {counts.get("neutral", 0)}</text>
  <text x="80" y="214" font-family="Malgun Gothic, Arial, sans-serif" font-size="12" fill="#64748b">막대 색상: 긍정 우세는 초록, 부정 우세는 빨강, 혼합/동률은 회색</text>
</svg>
"""


def build_html(analysis: dict[str, Any], svg_file_name: str) -> str:
    dominant = analysis.get("dominant", "neutral")
    color = COLORS.get(dominant, COLORS["neutral"])
    label = LABELS.get(dominant, "중립/혼합")
    mode_note = ""
    if analysis.get("source_mode") == "sample":
        mode_note = "<p class=\"notice\">샘플 모드 결과입니다. 실제 네이버 카페 수집 결과가 아니라 하네스 검증용 예시 데이터입니다.</p>"

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Naver Cafe Sentiment Report</title>
  <style>
    body {{ margin: 0; font-family: "Malgun Gothic", Arial, sans-serif; color: #1f2933; background: #f6f8fa; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px; }}
    h1 {{ font-size: 32px; margin: 0 0 8px; letter-spacing: 0; }}
    h2 {{ font-size: 22px; margin: 0 0 12px; letter-spacing: 0; }}
    h3 {{ font-size: 18px; margin: 0 0 10px; letter-spacing: 0; }}
    p {{ color: #52606d; font-size: 16px; }}
    .notice {{ background: #fff4e6; border: 1px solid #ffd8a8; color: #8a4b08; border-radius: 8px; padding: 12px 14px; }}
    .summary {{ display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }}
    .metric {{ background: #fff; border: 1px solid #d9e2ec; border-radius: 8px; padding: 14px; }}
    .metric strong {{ display: block; font-size: 24px; color: {color}; margin-top: 4px; }}
    .panel {{ background: #fff; border: 1px solid #d9e2ec; border-radius: 8px; padding: 18px; margin-top: 18px; }}
    img {{ width: 100%; height: auto; display: block; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; margin-top: 14px; border: 1px solid #d9e2ec; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #e5eaf0; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ background: #eef2f6; }}
    .bar-row {{ display: grid; grid-template-columns: 120px 1fr 72px; gap: 12px; align-items: center; margin: 10px 0; }}
    .track {{ height: 24px; background: #edf1f5; border-radius: 8px; overflow: hidden; }}
    .fill {{ height: 100%; border-radius: 8px; }}
    details {{ background: #fff; border: 1px solid #d9e2ec; border-radius: 8px; margin-top: 10px; padding: 12px 14px; }}
    summary {{ cursor: pointer; font-weight: 700; }}
    .empty {{ color: #64748b; margin: 8px 0 0; }}
    @media (max-width: 760px) {{
      .summary {{ grid-template-columns: 1fr 1fr; }}
      .bar-row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>{html.escape(str(analysis.get('query', '')))} 반응 리포트</h1>
    <p>{html.escape(str(analysis.get('period_label', '')))} 기간 취합 분석 결과입니다.</p>
    {mode_note}
    <section class="summary">
      <div class="metric">전체 게시글<strong>{analysis.get('total_posts', 0)}</strong></div>
      <div class="metric">전체 댓글<strong>{analysis.get('total_comments', 0)}</strong></div>
      <div class="metric">우세 반응<strong>{label}</strong></div>
      <div class="metric">우세 비율<strong>{pct(float(analysis.get('dominant_ratio', 0) or 0))}</strong></div>
    </section>
    <section class="panel">
      <h2>기간 전체 취합</h2>
      <img src="{html.escape(svg_file_name)}" alt="sentiment bar graph">
    </section>
    <section class="panel">
      <h2>일자별 보기</h2>
      {build_daily_html(analysis)}
    </section>
    <section class="panel">
      <h2>전체 게시글 판정</h2>
      {build_post_table(analysis.get('posts', []), show_date=True)}
    </section>
  </main>
</body>
</html>
"""


def build_daily_html(analysis: dict[str, Any]) -> str:
    rows: list[str] = []
    for day in analysis.get("daily", []):
        dominant = day.get("dominant", "neutral")
        label = LABELS.get(dominant, "중립/혼합")
        color = COLORS.get(dominant, COLORS["neutral"])
        ratio = float(day.get("dominant_ratio", 0) or 0)
        counts = day.get("counts", {})
        width = pct(ratio)
        rows.append(
            f"""
            <details open>
              <summary>{html.escape(day.get('period_label', ''))} · {label} · 게시글 {day.get('total_posts', 0)}건</summary>
              <div class="bar-row">
                <strong>{label}</strong>
                <div class="track"><div class="fill" style="width:{width}; background:{color};"></div></div>
                <strong style="color:{color};">{width}</strong>
              </div>
              <p>긍정 {counts.get('positive', 0)} · 부정 {counts.get('negative', 0)} · 중립 {counts.get('neutral', 0)} · 댓글 {day.get('total_comments', 0)}개</p>
              {build_post_table(day.get('posts', []), show_date=False)}
            </details>
            """
        )
    return "\n".join(rows)


def build_post_table(posts: list[dict[str, Any]], show_date: bool) -> str:
    if not posts:
        return "<p class=\"empty\">해당 기간에 표시할 게시글이 없습니다.</p>"

    date_header = "<th>일자</th>" if show_date else ""
    rows = []
    for post in posts:
        date_cell = f"<td>{html.escape(str(post.get('date', '')))}</td>" if show_date else ""
        rows.append(
            "<tr>"
            f"{date_cell}"
            f"<td>{html.escape(str(post.get('sentiment', '')))}</td>"
            f"<td>{html.escape(str(post.get('score', '')))}</td>"
            f"<td>{html.escape(str(post.get('title', '')))}</td>"
            f"<td>{html.escape(', '.join(post.get('evidence_terms', [])))}</td>"
            "</tr>"
        )

    return f"""
    <table>
      <thead>
        <tr>{date_header}<th>분류</th><th>점수</th><th>제목</th><th>근거 키워드</th></tr>
      </thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    """

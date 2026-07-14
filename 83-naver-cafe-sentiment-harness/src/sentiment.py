from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta
from typing import Any


POSITIVE_TERMS: dict[str, int] = {
    "좋": 1,
    "좋아요": 2,
    "잘": 1,
    "개선": 2,
    "해결": 2,
    "완화": 2,
    "지원": 2,
    "도움": 2,
    "혜택": 2,
    "승인": 2,
    "가능": 1,
    "기대": 1,
    "긍정": 2,
    "만족": 2,
    "안정": 1,
    "회복": 2,
    "필요": 1,
    "유용": 2,
    "추천": 2,
    "괜찮": 1,
}

NEGATIVE_TERMS: dict[str, int] = {
    "나쁘": -2,
    "싫": -2,
    "별로": -2,
    "아쉽": -1,
    "불안": -2,
    "부담": -2,
    "어렵": -2,
    "힘들": -2,
    "거절": -3,
    "연체": -2,
    "위험": -2,
    "문제": -1,
    "비판": -2,
    "논란": -2,
    "실망": -2,
    "걱정": -1,
    "최악": -3,
    "부족": -1,
    "피해": -2,
    "한계": -1,
}


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def date_range(start_date: str, end_date: str) -> list[str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def remove_query_noise(text: str, query: str) -> str:
    cleaned = normalize_text(text)
    query = normalize_text(query)
    if query:
        cleaned = cleaned.replace(query, " ")
    return normalize_text(cleaned)


def _term_score(text: str, terms: dict[str, int]) -> tuple[int, list[str]]:
    lowered = text.lower()
    score = 0
    found: list[str] = []
    for term, weight in terms.items():
        count = lowered.count(term.lower())
        if count:
            score += weight * count
            found.extend([term] * count)
    return score, found


def classify_score(score: int) -> str:
    if score >= 2:
        return "positive"
    if score <= -2:
        return "negative"
    return "neutral"


def score_post(post: dict[str, Any], query: str) -> dict[str, Any]:
    title = normalize_text(post.get("title"))
    content = normalize_text(post.get("content"))
    comments = [normalize_text(comment) for comment in post.get("comments", [])]

    score_title = remove_query_noise(title, query)
    score_content = remove_query_noise(content, query)
    score_comments = [remove_query_noise(comment, query) for comment in comments]

    title_score, title_terms = _score_text(score_title)
    content_score, content_terms = _score_text(score_content)
    comment_score = 0
    comment_terms: list[str] = []
    for comment in score_comments:
        score, terms = _score_text(comment)
        comment_score += score
        comment_terms.extend(terms)

    # Title carries more intent than body snippets in cafe search results.
    total_score = title_score * 2 + content_score + comment_score
    sentiment = classify_score(total_score)

    return {
        "post_id": post.get("post_id") or post.get("url") or title[:30],
        "url": post.get("url", ""),
        "title": title,
        "date": post.get("date", ""),
        "observed_date_text": post.get("observed_date_text", ""),
        "comment_count": len(comments),
        "score": total_score,
        "sentiment": sentiment,
        "evidence_terms": sorted(set(title_terms + content_terms + comment_terms)),
        "field_scores": {
            "title": title_score,
            "content": content_score,
            "comments": comment_score,
        },
    }


def _score_text(text: str) -> tuple[int, list[str]]:
    positive_score, positive_terms = _term_score(text, POSITIVE_TERMS)
    negative_score, negative_terms = _term_score(text, NEGATIVE_TERMS)

    negation_bonus = 0
    if "나쁘지 않" in text or "나쁘지는 않" in text:
        negation_bonus += 2
    if "좋지 않" in text or "좋지는 않" in text or "안 좋" in text:
        negation_bonus -= 2

    return positive_score + negative_score + negation_bonus, positive_terms + negative_terms


def summarize_results(
    post_results: list[dict[str, Any]],
    query: str,
    start_date: str,
    end_date: str,
    label: str | None = None,
) -> dict[str, Any]:
    counts = Counter(result["sentiment"] for result in post_results)
    total_posts = len(post_results)
    positive = counts.get("positive", 0)
    negative = counts.get("negative", 0)
    neutral = counts.get("neutral", 0)
    dominant, dominant_ratio = dominant_sentiment(positive, negative, neutral, total_posts)

    return {
        "query": query,
        "start_date": start_date,
        "end_date": end_date,
        "period_label": label or period_label(start_date, end_date),
        "total_posts": total_posts,
        "total_comments": sum(result["comment_count"] for result in post_results),
        "counts": {
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
        },
        "ratios": {
            "positive": round(positive / total_posts, 4) if total_posts else 0,
            "negative": round(negative / total_posts, 4) if total_posts else 0,
            "neutral": round(neutral / total_posts, 4) if total_posts else 0,
        },
        "dominant": dominant,
        "dominant_ratio": round(dominant_ratio, 4),
        "posts": post_results,
    }


def dominant_sentiment(
    positive: int,
    negative: int,
    neutral: int,
    total_posts: int,
) -> tuple[str, float]:
    if total_posts == 0:
        return "neutral", 0.0

    values = {"positive": positive, "negative": negative, "neutral": neutral}
    max_count = max(values.values())
    winners = [name for name, count in values.items() if count == max_count]
    if len(winners) == 1:
        return winners[0], max_count / total_posts
    return "neutral", max_count / total_posts


def period_label(start_date: str, end_date: str) -> str:
    if start_date == end_date:
        return f"{start_date} 하루"
    return f"{start_date} ~ {end_date}"


def analyze_posts(posts: list[dict[str, Any]], query: str, start_date: str, end_date: str) -> dict[str, Any]:
    in_range_posts = [
        post for post in posts
        if post.get("date") and start_date <= str(post.get("date")) <= end_date
    ]
    post_results = [score_post(post, query) for post in in_range_posts]
    overall = summarize_results(post_results, query, start_date, end_date)

    daily = []
    for day in date_range(start_date, end_date):
        day_results = [result for result in post_results if result.get("date") == day]
        daily.append(summarize_results(day_results, query, day, day, label=day))

    overall["daily"] = daily
    return overall

from __future__ import annotations

import html
import argparse
import socket
import sys
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from renderer import LABELS
from run_harness import CAFE_URL, today_seoul, run_pipeline


HOST = "127.0.0.1"
DEFAULT_PORT = 8797


class LiveAppHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.startswith("/output/"):
            self.serve_output_file()
            return
        self.respond_html(render_page())

    def do_POST(self) -> None:
        if self.path != "/run":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        params = parse_qs(self.rfile.read(length).decode("utf-8"))
        query = first(params, "query").strip()
        from_date = first(params, "from_date").strip()
        to_date = first(params, "to_date").strip()
        max_posts = int(first(params, "max_posts") or "30")
        force_login = first(params, "force_login") == "on"

        if not query:
            self.respond_html(render_page(error="검색어를 입력하세요."))
            return

        try:
            result = run_pipeline(
                query=query,
                start_date=from_date,
                end_date=to_date,
                cafe_url=CAFE_URL,
                max_posts=max_posts,
                sample=False,
                headless=False,
                force_login=force_login,
            )
            self.respond_html(render_page(result=result))
        except Exception as exc:
            traceback.print_exc()
            self.respond_html(render_page(error=str(exc)))

    def serve_output_file(self) -> None:
        requested = self.path.removeprefix("/output/").split("?", 1)[0]
        safe_name = Path(requested).name
        path = ROOT / "output" / safe_name
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content_type = "text/html; charset=utf-8" if path.suffix == ".html" else "image/svg+xml"
        if path.suffix == ".json":
            content_type = "application/json; charset=utf-8"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


def first(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key, [""])
    return values[0] if values else ""


def render_page(result: dict | None = None, error: str | None = None) -> str:
    today = today_seoul()
    summary = ""
    if result:
        analysis = result["analysis"]
        validation = result["validation"]
        summary = f"""
        <section class="result">
          <h2>실행 결과</h2>
          <p><strong>검색어:</strong> {html.escape(analysis['query'])}</p>
          <p><strong>기간:</strong> {html.escape(analysis['period_label'])}</p>
          <p><strong>우세 반응:</strong> {html.escape(LABELS.get(analysis['dominant'], '중립/혼합'))}</p>
          <p><strong>게시글/댓글:</strong> {analysis['total_posts']}건 / {analysis['total_comments']}개</p>
          <p><strong>검증:</strong> {html.escape(validation['overall'])}</p>
          <p><a href="/output/index.html" target="_blank">최종 리포트 새 창으로 열기</a></p>
          <iframe src="/output/index.html" title="latest sentiment report"></iframe>
        </section>
        """

    error_block = f"<p class=\"error\">{html.escape(error)}</p>" if error else ""
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Naver Cafe Live Sentiment</title>
  <style>
    body {{ margin: 0; background: #f6f8fa; color: #1f2933; font-family: "Malgun Gothic", Arial, sans-serif; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px; }}
    h1 {{ margin: 0 0 10px; font-size: 30px; letter-spacing: 0; }}
    p {{ color: #52606d; }}
    form, .result {{ background: #fff; border: 1px solid #d9e2ec; border-radius: 8px; padding: 18px; margin-top: 18px; }}
    .grid {{ display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 12px; align-items: end; }}
    label {{ display: block; font-weight: 700; margin-bottom: 6px; }}
    input {{ width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 15px; }}
    button {{ padding: 11px 16px; border: 0; border-radius: 6px; background: #2f9e44; color: #fff; font-weight: 700; cursor: pointer; }}
    .options {{ display: flex; gap: 14px; align-items: center; margin-top: 12px; }}
    .options input {{ width: auto; }}
    .error {{ background: #fff5f5; border: 1px solid #ffc9c9; color: #c92a2a; padding: 12px; border-radius: 8px; }}
    iframe {{ width: 100%; height: 760px; border: 1px solid #d9e2ec; border-radius: 8px; margin-top: 14px; background: #fff; }}
    @media (max-width: 860px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <h1>네이버 카페 실제 검색어 반응 분석</h1>
    <p>검색어와 기간을 입력하면 네이버 카페에서 새로 수집한 뒤 기간 전체와 일자별 결과를 생성합니다.</p>
    {error_block}
    <form method="post" action="/run">
      <div class="grid">
        <div>
          <label for="query">검색어</label>
          <input id="query" name="query" value="신용취약" required>
        </div>
        <div>
          <label for="from_date">From</label>
          <input id="from_date" name="from_date" type="date" value="{today}" required>
        </div>
        <div>
          <label for="to_date">To</label>
          <input id="to_date" name="to_date" type="date" value="{today}" required>
        </div>
        <div>
          <label for="max_posts">최대 게시글</label>
          <input id="max_posts" name="max_posts" type="number" min="1" max="100" value="30">
        </div>
      </div>
      <div class="options">
        <label><input type="checkbox" name="force_login"> 로그인 다시 하기</label>
        <button type="submit">실제 카페에서 분석 실행</button>
      </div>
    </form>
    {summary}
  </main>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Naver Cafe sentiment local input app")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="로컬 입력 화면 포트")
    return parser.parse_args()


def find_free_port(preferred_port: int) -> int:
    for port in range(preferred_port, preferred_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"사용 가능한 포트를 찾지 못했습니다: {preferred_port}~{preferred_port + 49}")


def main() -> None:
    args = parse_args()
    port = find_free_port(args.port)
    server = ThreadingHTTPServer((HOST, port), LiveAppHandler)
    print(f"실제 검색어 입력 화면: http://{HOST}:{port}")
    if port != args.port:
        print(f"요청한 {args.port} 포트가 사용 중이라 {port} 포트를 사용합니다.")
    print("종료하려면 Ctrl+C를 누르세요.")
    server.serve_forever()


if __name__ == "__main__":
    main()

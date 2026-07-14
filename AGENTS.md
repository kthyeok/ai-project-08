# Codex Instructions

This project is a Codex harness for analyzing date-range reactions to a keyword in a Naver Cafe.

## Primary Workflow

When the user asks to collect, analyze, visualize, or report Naver Cafe reactions, use the local skill at:

`.codex/skills/naver-cafe-sentiment/SKILL.md`

## Output Location

All generated working files and final artifacts must be written under this project root:

- `_workspace/00_input.md`
- `_workspace/01_data_collection.md`
- `_workspace/02_analysis_report.md`
- `_workspace/03_visualization_spec.md`
- `_workspace/04_output_report.md`
- `_workspace/05_validation_report.md`
- `output/index.html`
- `output/sentiment_bar.svg`
- `output/sentiment_summary.json`

## Codex Execution Rules

- Emulate a multi-agent workflow as role passes: input planner, cafe collector, sentiment analyst, daily summarizer, visualizer, validator, output reporter.
- Use `_workspace/` files as the handoff mechanism between role passes.
- Prefer the sample mode for fast local verification and the live Playwright mode for actual Naver Cafe collection.
- Never store Naver credentials in source files. Browser cookies/session state may be saved only under `.auth/`, which is ignored.
- If live collection fails because Naver changes UI selectors or requires additional verification, keep the partial result and record the limitation in `_workspace/05_validation_report.md`.
- Final user-facing responses should list produced files, the dominant reaction, and any limitations.

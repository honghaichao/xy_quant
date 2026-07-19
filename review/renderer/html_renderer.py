"""HTML 报告渲染器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from interfaces.report_renderer import IReportRenderer


class HtmlRenderer(IReportRenderer):
    def render(self, data: dict[str, Any], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        html = self._render_html(data)
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def _render_html(self, data: dict[str, Any]) -> str:
        title = data["header"]["title"]
        subtitle = data["header"]["subtitle"]
        summary = data["header"]["summary"]
        findings = data["header"].get("findings", [])
        cards = data.get("cards", [])
        sections = data.get("sections", [])
        return f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{title}</title>
  <style>
    :root {{
      --bg: #efe6d7;
      --panel: #ffffff;
      --panel-soft: #f8f2ea;
      --border: #ded1bf;
      --text: #2b2218;
      --muted: #705847;
      --accent: #b86a2f;
      --accent-2: #8a4d23;
      --bar: #ead8bf;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
    }}
    .page {{ width: 1200px; margin: 0 auto; padding: 32px 40px 48px; }}
    .hero {{
      position: relative;
      border-radius: 28px;
      overflow: hidden;
      padding: 36px 36px 30px;
      color: #fff7ef;
      background: linear-gradient(135deg, #5e3218 0%, #9f5225 28%, #c77a35 58%, #e3a24e 78%, #f3cc7a 100%);
      box-shadow: 0 18px 42px rgba(89, 46, 13, 0.24);
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at 85% 20%, rgba(255,255,255,.18), transparent 28%),
        radial-gradient(circle at 20% 15%, rgba(255,255,255,.10), transparent 18%),
        linear-gradient(180deg, rgba(255,255,255,.08), rgba(0,0,0,.12));
      pointer-events: none;
    }}
    .hero h1 {{ position: relative; margin: 0; font-size: 38px; letter-spacing: .04em; }}
    .hero .sub {{ position: relative; margin-top: 8px; color: rgba(255,247,239,.88); font-size: 16px; }}
    .hero .summary {{ position: relative; margin-top: 16px; font-size: 18px; line-height: 1.7; max-width: 1000px; }}
    .hero .findings {{ position: relative; display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }}
    .find-pill {{
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,.14);
      border: 1px solid rgba(255,255,255,.18);
      backdrop-filter: blur(4px);
      font-size: 14px;
    }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 18px; }}
    .card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 22px; padding: 18px 18px 16px; box-shadow: 0 8px 28px rgba(68, 44, 20, .05); }}
    .card .label {{ color: var(--muted); font-size: 13px; letter-spacing: .08em; text-transform: uppercase; }}
    .card .value {{ margin-top: 8px; font-size: 24px; font-weight: 700; color: var(--accent-2); line-height: 1.25; }}
    .card .note {{ margin-top: 10px; color: var(--text); font-size: 14px; line-height: 1.6; }}
    .section {{ margin-top: 18px; }}
    .section-bar {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 16px;
      border-radius: 999px;
      background: var(--bar);
      color: #6f4c31;
      font-size: 15px;
      font-weight: 700;
      box-shadow: inset 0 0 0 1px rgba(129,94,62,.08);
    }}
    .section-box {{
      margin-top: 10px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 20px;
      padding: 18px 20px;
      line-height: 1.75;
      box-shadow: 0 6px 20px rgba(68, 44, 20, .04);
    }}
    .section-box p {{ margin: 0; }}
    .section-box ul {{ margin: 0; padding-left: 1.15em; }}
    .section-box li + li {{ margin-top: 6px; }}
  </style>
</head>
<body>
  <main class=\"page\">
    <section class=\"hero\">
      <h1>{title}</h1>
      <div class=\"sub\">{subtitle}</div>
      <div class=\"summary\">{summary}</div>
      <div class=\"findings\">{''.join(f'<span class="find-pill">{item}</span>' for item in findings)}</div>
    </section>
    <section class=\"summary-grid\">{''.join(self._render_card(card) for card in cards)}</section>
    {''.join(self._render_section(section) for section in sections)}
  </main>
</body>
</html>"""

    @staticmethod
    def _render_card(card: dict[str, Any]) -> str:
        return (
            '<article class="card">'
            f'<div class="label">{card["label"]}</div>'
            f'<div class="value">{card["value"]}</div>'
            f'<div class="note">{card["note"]}</div>'
            '</article>'
        )

    @staticmethod
    def _render_section(section: dict[str, Any]) -> str:
        items = ''.join(f'<li>{line}</li>' if line.startswith('•') else f'<p>{line}</p>' for line in section["lines"])
        content = f'<ul>{items}</ul>' if any(line.startswith('•') for line in section["lines"]) else f'<div class="section-box">{items}</div>'
        if content.startswith('<ul>'):
            content = f'<div class="section-box">{content}</div>'
        return (
            '<section class="section">'
            f'<div class="section-bar">{section["index"]} · {section["title"]}</div>'
            f'{content}'
            '</section>'
        )

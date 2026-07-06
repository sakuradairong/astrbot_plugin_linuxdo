PREVIEW_CARD_CSS = """
  :root {
    --color-canvas: #eef3f8;
    --color-card: #ffffff;
    --color-card-soft: #f7faff;
    --color-ink: #172033;
    --color-muted: #667085;
    --color-subtle: #98a2b3;
    --color-line: #dce6f2;
    --color-accent: #1f6feb;
    --color-accent-strong: #0b55c8;
    --color-accent-soft: #e9f2ff;
    --color-code-bg: #f4f7fb;
    --shadow-card: 0 18px 55px rgba(16, 42, 77, 0.16);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    min-width: 320px;
    padding: 32px;
    background:
      radial-gradient(circle at 18% 0%, rgba(31, 111, 235, 0.13), transparent 32%),
      linear-gradient(135deg, #f8fbff 0%, var(--color-canvas) 100%);
    color: var(--color-ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
      "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC",
      "Source Han Sans SC", "WenQuanYi Micro Hei", Arial, sans-serif;
    line-height: 1.72;
  }
  .card {
    position: relative;
    max-width: 780px;
    margin: 0 auto;
    overflow: hidden;
    background: var(--color-card);
    border: 1px solid rgba(220, 230, 242, 0.88);
    border-radius: 24px;
    box-shadow: var(--shadow-card);
  }
  .card::before {
    content: "";
    position: absolute;
    inset: 0 0 auto 0;
    height: 5px;
    background: linear-gradient(90deg, var(--color-accent), #6aa5ff 55%, #b9d7ff);
  }
  .header { padding: 30px 34px 24px; border-bottom: 1px solid var(--color-line); }
  .eyebrow {
    margin: 0 0 10px;
    color: var(--color-accent-strong);
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.14em;
    line-height: 1.4;
  }
  .title {
    margin: 0 0 18px;
    color: var(--color-ink);
    font-size: 28px;
    font-weight: 800;
    letter-spacing: -0.03em;
    line-height: 1.28;
    overflow-wrap: break-word;
    word-break: normal;
  }
  .meta { display: flex; align-items: center; gap: 10px; color: var(--color-muted); font-size: 13px; font-weight: 500; }
  .avatar-wrap { position: relative; width: 36px; height: 36px; flex: 0 0 36px; }
  .avatar-wrap img { position: absolute; inset: 0; z-index: 1; }
  img.avatar { width: 36px; height: 36px; border-radius: 50%; object-fit: cover; background: var(--color-accent-soft); }
  .avatar-fallback {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--color-accent), #7f56d9);
    color: #fff;
    font-size: 14px;
    font-weight: 800;
    text-transform: uppercase;
  }
  .name { color: var(--color-ink); font-weight: 700; }
  .dot { color: var(--color-subtle); }
  .stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    background: var(--color-line);
    border-bottom: 1px solid var(--color-line);
  }
  .stat { padding: 16px 24px; background: var(--color-card-soft); }
  .stat-label { display: block; color: var(--color-muted); font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
  .stat-value { display: block; margin-top: 3px; color: var(--color-ink); font-size: 18px; font-weight: 800; line-height: 1.2; }
  .tags { padding: 18px 34px 0; display: flex; gap: 8px; flex-wrap: wrap; }
  .tag {
    border: 1px solid rgba(31, 111, 235, 0.14);
    border-radius: 999px;
    background: var(--color-accent-soft);
    color: var(--color-accent-strong);
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 700;
    line-height: 1.4;
  }
  .content { padding: 22px 34px 12px; word-break: break-word; font-size: 16px; }
  .content p { margin: 0 0 18px; }
  .content h1, .content h2, .content h3 { margin: 24px 0 12px; line-height: 1.28; letter-spacing: -0.02em; }
  .content img { max-width: 100%; height: auto; border-radius: 18px; display: block; margin: 16px 0; border: 1px solid var(--color-line); }
  .content pre, .content code {
    background: var(--color-code-bg);
    border-radius: 8px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 14px;
  }
  .content code { padding: 2px 6px; }
  .content pre { padding: 14px 16px; overflow-x: auto; border: 1px solid var(--color-line); line-height: 1.55; }
  .content pre code { padding: 0; background: transparent; }
  .content blockquote {
    margin: 14px 0;
    padding: 12px 16px;
    border-left: 4px solid var(--color-accent);
    border-radius: 0 14px 14px 0;
    background: var(--color-code-bg);
    color: #475467;
  }
  .content a { color: var(--color-accent-strong); text-decoration: none; font-weight: 600; }
  .content ul, .content ol { padding-left: 24px; margin: 0 0 18px; }
  .footer {
    margin-top: 10px;
    padding: 16px 34px 22px;
    border-top: 1px solid var(--color-line);
    background: var(--color-card-soft);
    color: var(--color-muted);
    font-size: 12px;
    word-break: break-all;
  }
  .footer-label { display: block; margin-bottom: 4px; color: var(--color-subtle); font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; }
  .footer a { color: var(--color-accent-strong); text-decoration: none; font-weight: 600; }
  @media (max-width: 560px) {
    body { padding: 20px; }
    .header, .content, .footer { padding-left: 22px; padding-right: 22px; }
    .tags { padding-left: 22px; padding-right: 22px; }
    .title { font-size: 23px; }
    .stat { padding: 13px 16px; }
  }
""".strip()

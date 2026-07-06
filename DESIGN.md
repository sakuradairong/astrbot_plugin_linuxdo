# LinuxDo Preview Design System

## 1. Product Atmosphere

The preview card is a compact forum artifact rendered into chat. It should feel like a polished clipping from linux.do rather than a generic website card: dense enough for technical discussion, calm enough for a noisy group chat, and dimensional enough to read as a deliberate screenshot.

Design keywords: editorial forum card, warm technical paper, blue accent rail, quiet depth, readable long-form content.

## 2. Color Tokens

- `--color-canvas`: `#eef3f8` page background with a cool paper tone.
- `--color-card`: `#ffffff` card surface.
- `--color-card-soft`: `#f7faff` secondary surface for stats and footer.
- `--color-ink`: `#172033` primary text.
- `--color-muted`: `#667085` secondary text.
- `--color-subtle`: `#98a2b3` tertiary text and dividers.
- `--color-line`: `#dce6f2` border color.
- `--color-accent`: `#1f6feb` LinuxDo link blue.
- `--color-accent-strong`: `#0b55c8` active accent.
- `--color-accent-soft`: `#e9f2ff` tag and avatar wash.
- `--color-code-bg`: `#f4f7fb` code and quote surface.
- `--shadow-card`: `0 18px 55px rgba(16, 42, 77, 0.16)`.

## 3. Typography

Use system CJK/UI fonts for reliable server-side rendering:

```css
font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
  "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC",
  "Source Han Sans SC", "WenQuanYi Micro Hei", Arial, sans-serif;
```

- Title: 28px, 800 weight, 1.28 line-height, tight tracking.
- Body: 16px, 400 weight, 1.72 line-height.
- Metadata: 13px, 500 weight, 1.4 line-height.
- Stats: 12px uppercase label plus 18px value.
- Code: 14px monospace, 1.55 line-height.

## 4. Spacing And Shape

- Page padding: 32px desktop, 20px narrow fallback.
- Card width: max 780px.
- Card radius: 24px outer, 18px inner media.
- Header padding: 30px 34px 24px.
- Section padding: 22px 34px.
- Rhythm: 10px small, 14px control gap, 18px paragraph gap, 26px section gap.
- Border: 1px solid `--color-line`.

## 5. Component Anatomy

### Preview Card

The `.card` is a white rounded surface with a subtle top highlight and a blue accent strip. It must not rely on external fonts, JS, or remote decorative assets.

### Header

The header contains a small uppercase `LINUX.DO TOPIC` eyebrow, the escaped fancy title, and author metadata. The author row uses a circular avatar/fallback and a separator dot rendered with CSS/text, not emoji.

### Stat Bar

Stats are three compact metric cells for views, replies, and likes. Use text labels instead of emoji icons so the card is consistent across platforms and screenshot engines.

### Tags

Tags are rounded pills with an accent tint. Keep at most six tags from the renderer.

### Content

Cooked Discourse HTML is the main reading area. Preserve sanitized body tags, give blockquotes and code blocks distinct surfaces, and keep images full-width responsive with rounded corners.

### Footer

The footer shows `Source` and the escaped topic URL in a soft surface. It should be useful but lower priority than the title and content.

## 6. Motion And State

The screenshot renderer is static. Do not add animation. Hover/focus states are unnecessary because the card is captured as an image, but links should remain visually recognizable.

## 7. Accessibility And Rendering Constraints

- No emoji as icons; use text labels or CSS shapes.
- No external decorative assets or web fonts.
- Maintain readable contrast on all text.
- Preserve sanitizer boundaries: cooked HTML must pass through `_sanitize_cooked_html`; sanitizer failure must remain plain-text fail-closed.
- Keep the card useful as a standalone image in chat: title, author, date, stats, content, tags, and source must all remain visible.
- Avoid CSS that depends on browser features likely to be brittle in Playwright screenshots.

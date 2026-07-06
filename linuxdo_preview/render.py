from pathlib import Path


def _take_screenshot(session, url: str, save_path: Path, config, logger) -> Path | None:
    timeout_ms = config.get("screenshot_timeout", 15) * 1000
    try:
        ctx = session.context
        if not ctx:
            return None
        page = ctx.new_page()
        try:
            page.set_viewport_size({"width": 1280, "height": 900})
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            try:
                page.wait_for_selector("#post_1", timeout=min(timeout_ms, 10000))
            except Exception:
                page.wait_for_timeout(3000)
            _prepare_topic_page(page)
            _click_expand_buttons(page)
            _scroll_for_lazy_images(page)
            _wait_for_post_images(page)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
            page.screenshot(
                path=str(save_path),
                full_page=config.get("screenshot_full_page", True),
                timeout=timeout_ms,
            )
            sz = save_path.stat().st_size
            logger.info(f"[LinuxDoPreview] 截图保存: {save_path.name} ({sz / 1024:.1f} KB)")
            return save_path
        finally:
            try:
                page.close()
            except Exception as e:
                logger.warning(f"[LinuxDoPreview] 关闭页面失败: {type(e).__name__}: {e}")
    except Exception as e:
        logger.warning(f"[LinuxDoPreview] 截图失败: {type(e).__name__}: {e}")
        return None


def _render_html_screenshot(session, html: str, save_path: Path, config, logger) -> Path | None:
    timeout_ms = config.get("screenshot_timeout", 15) * 1000
    if not html:
        return None
    try:
        ctx = session.context
        if not ctx:
            return None
        page = ctx.new_page()
        try:
            page.set_viewport_size({"width": 820, "height": 1200})
            page.set_content(html, wait_until="domcontentloaded", timeout=timeout_ms)
            page.evaluate("""() => new Promise(resolve => {
                const imgs = document.querySelectorAll('img');
                if (!imgs.length) return resolve();
                let done = 0;
                const tick = (img) => {
                    done++;
                    if (img.complete && img.naturalWidth === 0) {
                        img.remove();
                    }
                    if (done >= imgs.length) resolve();
                };
                imgs.forEach(img => {
                    if (img.complete) tick(img);
                    else {
                        img.addEventListener('load', () => tick(img), { once: true });
                        img.addEventListener('error', () => tick(img), { once: true });
                    }
                });
                setTimeout(resolve, 3000);
            })""")
            page.wait_for_timeout(300)
            card_locator = page.locator(".card")
            full_page = config.get("screenshot_full_page", True)
            try:
                if card_locator.count() > 0:
                    card_locator.first.screenshot(path=str(save_path), timeout=timeout_ms)
                else:
                    page.screenshot(path=str(save_path), full_page=full_page, timeout=timeout_ms)
            except Exception:
                page.screenshot(path=str(save_path), full_page=full_page, timeout=timeout_ms)
            sz = save_path.stat().st_size
            logger.info(f"[LinuxDoPreview] 渲染截图: {save_path.name} ({sz / 1024:.1f} KB)")
            return save_path
        finally:
            try:
                page.close()
            except Exception as e:
                logger.warning(f"[LinuxDoPreview] 关闭页面失败: {type(e).__name__}: {e}")
    except Exception as e:
        logger.warning(f"[LinuxDoPreview] HTML 渲染失败: {type(e).__name__}: {e}")
        return None


def _prepare_topic_page(page) -> None:
    page.evaluate("""() => {
        const hide = (sel) => {
            const el = document.querySelector(sel);
            if (el) el.style.display = 'none';
        };
        hide('.d-header');
        hide('.sidebar-wrapper');
        hide('.topic-navigation-wrapper');
        hide('.footer-nav.visible');
        hide('.post-stream');
        const posts = document.querySelectorAll('.topic-post');
        posts.forEach((post, i) => { if (i > 0) post.style.display = 'none'; });
        window.scrollTo(0, 0);
    }""")
    page.evaluate("""() => {
        const removeSelectors = [
            '.expand-post', '.gap-bottom', '.gap', '.large-post-container .show-more',
            '.topic-body .show-more', '.cooked .show-more', '.lightbox',
        ];
        removeSelectors.forEach(sel => {
            document.querySelectorAll(sel).forEach(el => el.remove());
        });
        const unclampSelectors = [
            '.cooked', '.topic-body', '#post_1 .cooked', '#post_1 .topic-body',
            '#post_1 .contents', '.large-post-container',
        ];
        unclampSelectors.forEach(sel => {
            document.querySelectorAll(sel).forEach(el => {
                el.style.maxHeight = 'none';
                el.style.overflow = 'visible';
                el.style.height = 'auto';
            });
        });
        document.querySelectorAll('[data-expanded]').forEach(el => {
            el.setAttribute('data-expanded', 'true');
        });
        document.querySelectorAll('.truncated').forEach(el => {
            el.classList.remove('truncated');
        });
    }""")


def _click_expand_buttons(page) -> None:
    try:
        expand_buttons = page.query_selector_all(
            '#post_1 .expand-post, #post_1 .show-more, '
            '#post_1 button[class*="expand"], '
            '#post_1 a[class*="expand"]'
        )
        for btn in expand_buttons:
            try:
                btn.click()
                page.wait_for_timeout(300)
            except Exception:
                continue
    except Exception:
        return
    page.evaluate("""() => {
        ['#post_1 .cooked', '#post_1 .topic-body', '#post_1 .contents'].forEach(sel => {
            document.querySelectorAll(sel).forEach(el => {
                el.style.maxHeight = 'none';
                el.style.overflow = 'visible';
                el.style.height = 'auto';
            });
        });
        document.querySelectorAll('#post_1 .lightbox-wrapper').forEach(el => {
            el.style.maxHeight = 'none';
            el.style.overflow = 'visible';
        });
    }""")


def _scroll_for_lazy_images(page) -> None:
    post1_box = page.evaluate("""() => {
        const p1 = document.querySelector('#post_1');
        if (!p1) return null;
        const rect = p1.getBoundingClientRect();
        return { top: rect.top + window.scrollY, height: rect.height };
    }""")
    if post1_box:
        post_top = int(post1_box.get('top', 0))
        post_height = int(post1_box.get('height', 0))
        for y in range(post_top, post_top + post_height, 400):
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(200)
    else:
        total_height = page.evaluate("document.body.scrollHeight")
        for y in range(0, total_height, 400):
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(200)


def _wait_for_post_images(page) -> None:
    page.evaluate("""() => {
        return new Promise(resolve => {
            const imgs = document.querySelectorAll('#post_1 img');
            let loaded = 0;
            const total = imgs.length;
            if (total === 0) return resolve();
            imgs.forEach(img => {
                if (img.complete) {
                    loaded++;
                    if (loaded >= total) resolve();
                } else {
                    img.onload = img.onerror = () => {
                        loaded++;
                        if (loaded >= total) resolve();
                    };
                }
            });
            setTimeout(resolve, 3000);
        });
    }""")

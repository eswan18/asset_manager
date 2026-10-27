"""Phone layout checks for browser tests (docs/superpowers/specs/2026-10-26-mobile-design.md).

Open a page at phone width with `open_page(path, phone=390)`, then call
`assert_fits_phone(page)`. It checks the three rules every screen keeps:

- nothing scrolls sideways (the document is no wider than the screen);
- every visible tap target is at least 44x44 CSS px (a checkbox or radio
  counts by its label; links inside running text are exempt);
- every text field, select and textarea has a font size of at least 16px,
  below which iOS zooms the page in on focus.

`allow_small` takes CSS selectors for targets that are deliberately smaller;
each use should say why in the test.
"""

from playwright.sync_api import Page

PHONE_WIDTHS = (320, 390)
TARGET = 44
MIN_INPUT_FONT = 16

_PROBLEMS_JS = """([target, minFont, allow]) => {
  const vw = document.documentElement.clientWidth;
  const overflow = document.documentElement.scrollWidth - vw;
  const describe = (el) => {
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || el.name || '')
      .trim().replace(/\\s+/g, ' ').slice(0, 30);
    const cls = [...el.classList].join('.');
    return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''} "${text}"`;
  };
  const visible = (el) => {
    if (el.closest('[inert]')) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden';
  };
  const wide = [];
  if (overflow > 0) {
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      if (r.width && (r.right > vw + 1 || r.left < -1)) wide.push(`${describe(el)} ${Math.round(r.left)}..${Math.round(r.right)}`);
      if (wide.length >= 8) break;
    }
  }
  const small = [];
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary';
  for (const el of document.querySelectorAll(sel)) {
    if (!visible(el) || allow.some((a) => el.matches(a))) continue;
    let box = el.getBoundingClientRect();
    if (el.matches('input[type=checkbox], input[type=radio]')) {
      const label = el.closest('label') || (el.id && document.querySelector(`label[for="${el.id}"]`));
      if (label) box = label.getBoundingClientRect();
    }
    // Inline links inside running text are exempt (as in WCAG 2.5.8).
    if (el.tagName === 'A' && getComputedStyle(el).display === 'inline' && el.parentElement.closest('p, li')) continue;
    if (box.width < target - 0.5 || box.height < target - 0.5) {
      small.push(`${describe(el)} ${Math.round(box.width)}x${Math.round(box.height)}`);
    }
  }
  const tiny = [];
  for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea')) {
    if (!visible(el)) continue;
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (size < minFont) tiny.push(`${describe(el)} ${size}px`);
  }
  return {overflow, wide, small, tiny};
}"""


def layout_problems(page: Page, allow_small: tuple[str, ...] = ()) -> dict:
    """What breaks the phone rules on the page as it is now."""
    return page.evaluate(_PROBLEMS_JS, [TARGET, MIN_INPUT_FONT, list(allow_small)])


def assert_fits_phone(page: Page, allow_small: tuple[str, ...] = ()) -> None:
    p = layout_problems(page, allow_small)
    messages = []
    if p["overflow"] > 0:
        messages.append(f"scrolls sideways by {p['overflow']}px: {p['wide']}")
    if p["small"]:
        messages.append(f"tap targets under {TARGET}px: {p['small']}")
    if p["tiny"]:
        messages.append(
            f"fields under {MIN_INPUT_FONT}px (iOS zooms on focus): {p['tiny']}"
        )
    assert not messages, f"{page.url}\n" + "\n".join(messages)

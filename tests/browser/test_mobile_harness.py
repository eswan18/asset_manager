"""The phone harness itself: open_page(phone=...) and layout_problems."""

import pytest

from tests.browser.mobile import PHONE_WIDTHS, layout_problems
from tests.web_support import PAGES

pytestmark = [pytest.mark.browser, pytest.mark.db]


@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_a_phone_page_is_as_wide_as_the_phone(open_page, seeded, width):
    page = open_page(PAGES, phone=width)
    assert page.evaluate("window.innerWidth") == width
    assert page.evaluate("navigator.maxTouchPoints") > 0
    assert layout_problems(page)["overflow"] == 0


def test_layout_problems_finds_a_small_target_and_a_small_field(open_page, seeded):
    page = open_page(PAGES, phone=390)
    page.evaluate(
        """() => {
        const a = document.createElement('a');
        a.href = '#'; a.textContent = 'x'; a.className = 'probe';
        a.style.cssText = 'display:inline-block;width:20px;height:20px';
        const i = document.createElement('input');
        i.className = 'probe'; i.style.fontSize = '13px';
        document.querySelector('main').prepend(a, i);
    }"""
    )
    problems = layout_problems(page)
    assert any("a.probe" in s for s in problems["small"])
    assert any("input.probe" in s for s in problems["tiny"])
    assert not any("a.probe" in s for s in layout_problems(page, ("a.probe",))["small"])

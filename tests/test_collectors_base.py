"""collectors/base.py — strip_html(): the shared HTML-cleaning helper used by
all three collectors. Reproduces the exact real-world cases confirmed live.
"""

from collectors.base import strip_html


def test_none_stays_none():
    assert strip_html(None) is None


def test_plain_text_is_unchanged():
    assert strip_html("plain text") == "plain text"


def test_strips_wikipedia_search_highlight_spans():
    """Real case: MediaWiki's excerpt wraps matched terms for highlighting."""
    raw = (
        'for working with <span class="searchmatch">large</span> '
        '<span class="searchmatch">language</span> models'
    )
    assert strip_html(raw) == "for working with large language models"


def test_decodes_html_entities():
    raw = "Topics referred to as &quot;test&quot;"
    assert strip_html(raw) == 'Topics referred to as "test"'


def test_strips_guardian_inline_markup_and_trailing_br():
    """Real case: trailText can carry <strong> and a trailing <br><br>."""
    raw = "Company behind ChatGPT says agent ‘cheated’ an evaluation<br><br>"
    expected = "Company behind ChatGPT says agent ‘cheated’ an evaluation"
    assert strip_html(raw) == expected


def test_strips_gnews_link_and_font_wrapper():
    """Real case: Google News RSS's description is only a link + source
    wrapper, no real excerpt."""
    raw = (
        '<a href="https://news.google.com/rss/articles/xyz" target="_blank">'
        "What AI agents mean for CPA firms</a>&nbsp;&nbsp;"
        '<font color="#6f6f6f">Journal of Accountancy</font>'
    )
    result = strip_html(raw)
    assert "<a" not in result and "<font" not in result
    assert "What AI agents mean for CPA firms" in result
    assert "Journal of Accountancy" in result

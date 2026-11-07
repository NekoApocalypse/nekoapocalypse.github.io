from __future__ import annotations

import json
import pathlib
import re
import unittest
from unittest import mock

from scripts import sync_x_recent

ROOT = pathlib.Path(__file__).resolve().parent.parent


class SyncXRecentTest(unittest.TestCase):
    def test_discover_profile_status_ids_separates_pinned_and_sorts_recent(self) -> None:
        sample_html = """
        <a href="/NekoStranding/status/2042286373609365593">Pinned</a>
        <a href="/NekoStranding/status/1900000000000000000">Quoted inside pinned</a>
        <a href="/NekoStranding/status/2118933007688188241">Latest</a>
        <a href="/NekoStranding/status/2118871118618759374">Quoted inside latest</a>
        <a href="/NekoStranding/status/2118932031061303753">Second latest</a>
        """
        with mock.patch.object(
            sync_x_recent, "http_get", return_value=sample_html.encode("utf-8")
        ):
            pinned_id, recent_ids = sync_x_recent.discover_profile_status_ids(
                "NekoStranding"
            )

        self.assertEqual(pinned_id, "2042286373609365593")
        self.assertEqual(
            recent_ids,
            [
                "2118933007688188241",
                "2118932031061303753",
                "2118871118618759374",
                "1900000000000000000",
            ],
        )

    def test_render_latest_card_suppresses_duplicate_quote_media_when_main_has_media(
        self,
    ) -> None:
        recent = [
            {
                "id": "2118933007688188241",
                "url": "https://x.com/NekoStranding/status/2118933007688188241",
                "author_name": "毒猫猫 | 量化摸鱼师",
                "author_handle": "NekoStranding",
                "date_label": "Nov 7, 2026",
                "text": "这就是 multi-agent 的实力吗！",
                "media": {
                    "type": "photo",
                    "thumb_url": "https://pbs.twimg.com/media/main.jpg?name=medium",
                },
                "quote": {
                    "id": "2118871118618759374",
                    "url": "https://x.com/NekoStranding/status/2118871118618759374",
                    "author_name": "毒猫猫 | 量化摸鱼师",
                    "author_handle": "NekoStranding",
                    "text": "Quoted text",
                    "media": {
                        "type": "photo",
                        "thumb_url": "https://pbs.twimg.com/media/quote.jpg?name=medium",
                    },
                },
            }
        ]
        html_out = sync_x_recent.render_latest_card(recent)
        self.assertIn("https://pbs.twimg.com/media/main.jpg?name=medium", html_out)
        self.assertNotIn("https://pbs.twimg.com/media/quote.jpg?name=medium", html_out)
        self.assertIn("Quoted text", html_out)

    def test_render_latest_card_skips_quoted_tweet_in_secondary_slot(self) -> None:
        recent = [
            {
                "id": "300",
                "url": "https://x.com/NekoStranding/status/300",
                "author_name": "毒猫猫 | 量化摸鱼师",
                "author_handle": "NekoStranding",
                "date_label": "Nov 7, 2026",
                "text": "Top text without image",
                "media": None,
                "quote": {
                    "id": "200",
                    "url": "https://x.com/NekoStranding/status/200",
                    "author_name": "毒猫猫 | 量化摸鱼师",
                    "author_handle": "NekoStranding",
                    "text": "Self quoted text without image",
                    "media": None,
                },
            },
            {
                "id": "200",
                "url": "https://x.com/NekoStranding/status/200",
                "author_name": "毒猫猫 | 量化摸鱼师",
                "author_handle": "NekoStranding",
                "date_label": "Nov 6, 2026",
                "text": "Self quoted text without image",
                "media": None,
                "quote": None,
            },
            {
                "id": "100",
                "url": "https://x.com/NekoStranding/status/100",
                "author_name": "毒猫猫 | 量化摸鱼师",
                "author_handle": "NekoStranding",
                "date_label": "Nov 5, 2026",
                "text": "Distinct earlier post",
                "media": None,
                "quote": None,
            },
        ]
        html_out = sync_x_recent.render_latest_card(recent)
        self.assertIn("Distinct earlier post", html_out)
        self.assertEqual(html_out.count("Self quoted text without image"), 1)

    def test_content_fingerprint_ignores_volatile_counters(self) -> None:
        base = {
            "updated_at": "2026-11-07T00:00:00Z",
            "handle": "NekoStranding",
            "latest": {"id": "1", "text": "hello", "likes": 1, "retweets": 0, "replies": 0},
            "recent": [{"id": "1", "text": "hello", "likes": 1, "retweets": 0, "replies": 0}],
            "pinned": {"id": "2", "text": "pinned", "likes": 10, "retweets": 2, "replies": 1},
        }
        updated_counters = {
            "updated_at": "2026-11-07T02:00:00Z",
            "handle": "NekoStranding",
            "latest": {"id": "1", "text": "hello", "likes": 99, "retweets": 5, "replies": 8},
            "recent": [{"id": "1", "text": "hello", "likes": 99, "retweets": 5, "replies": 8}],
            "pinned": {"id": "2", "text": "pinned", "likes": 120, "retweets": 3, "replies": 4},
        }
        self.assertEqual(
            sync_x_recent._content_fingerprint(base),
            sync_x_recent._content_fingerprint(updated_counters),
        )

    def test_index_html_and_json_snapshot_invariants(self) -> None:
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")
        style_css = (ROOT / "style.css").read_text(encoding="utf-8")
        payload = json.loads((ROOT / "assets" / "x-recent.json").read_text(encoding="utf-8"))

        # 1. Appendix section placement after Contact Me
        contact_pos = index_html.index('id="contact-heading"')
        x_pos = index_html.index('id="x-heading"')
        self.assertGreater(x_pos, contact_pos)

        # 2. Markers and card IDs present
        self.assertIn("<!-- BEGIN_X_RECENT_CARDS -->", index_html)
        self.assertIn("<!-- END_X_RECENT_CARDS -->", index_html)
        self.assertIn('id="x-card-latest"', index_html)
        self.assertIn('id="x-card-pinned"', index_html)

        # 3. Static fallback in index.html matches assets/x-recent.json latest ID
        latest_id = payload["latest"]["id"]
        self.assertRegex(
            index_html,
            re.compile(
                rf'id="x-card-latest".*?/NekoStranding/status/{re.escape(latest_id)}',
                re.DOTALL,
            ),
        )

        # 4. Client-side live sync and monotonic Snowflake ID guard
        self.assertIn("isNewerOrEqualId", index_html)
        self.assertIn("'X-No-Cache': 'true'", index_html)
        self.assertIn("-webkit-line-clamp: 3;", style_css)


if __name__ == "__main__":
    unittest.main()

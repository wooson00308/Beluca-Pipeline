"""Tests for bpe.shotgrid.users."""

from __future__ import annotations

from bpe.shotgrid.users import normalize_human_user_search_query, search_human_users
from tests.shotgrid.mock_sg import MockShotgun


class TestNormalizeHumanUserSearchQuery:
    def test_empty(self) -> None:
        assert normalize_human_user_search_query("") == ""
        assert normalize_human_user_search_query("   ") == ""

    def test_plain_short_query_unchanged(self) -> None:
        assert normalize_human_user_search_query("yklee") == "yklee"
        assert normalize_human_user_search_query("김작가") == "김작가"

    def test_display_format_yields_email(self) -> None:
        s = "이영규 yklee yklee@lennon.co.kr (yklee@lennon.co.kr)"
        assert normalize_human_user_search_query(s) == "yklee@lennon.co.kr"


class TestSearchHumanUsers:
    def test_finds_by_normalized_email_from_display_string(self) -> None:
        sg = MockShotgun()
        sg._add_entity(
            "HumanUser",
            {
                "id": 1079,
                "name": "이영규 yklee",
                "login": "yklee@lennon.co.kr",
                "email": "yklee@lennon.co.kr",
            },
        )
        q = "이영규 yklee yklee@lennon.co.kr (yklee@lennon.co.kr)"
        hits = search_human_users(sg, q)
        assert len(hits) == 1
        assert hits[0]["id"] == 1079

    def test_name_search_still_works(self) -> None:
        sg = MockShotgun()
        sg._add_entity(
            "HumanUser",
            {
                "id": 1,
                "name": "Alice",
                "login": "alice",
                "email": "a@ex.com",
            },
        )
        hits = search_human_users(sg, "Ali")
        assert len(hits) == 1

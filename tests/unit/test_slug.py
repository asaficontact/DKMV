from __future__ import annotations

import re
from datetime import datetime

from dkmv.utils.slug import generate_run_id, slugify


class TestSlugify:
    def test_basic_lowercase(self) -> None:
        assert slugify("Hello World") == "hello-world"

    def test_special_characters(self) -> None:
        assert slugify("auth@module!v2") == "auth-module-v2"

    def test_consecutive_hyphens_collapsed(self) -> None:
        assert slugify("foo---bar") == "foo-bar"

    def test_leading_trailing_hyphens_stripped(self) -> None:
        assert slugify("--hello--") == "hello"

    def test_truncation(self) -> None:
        result = slugify("a" * 50, max_length=10)
        assert len(result) <= 10

    def test_truncation_strips_trailing_hyphen(self) -> None:
        # "hello-world-test" truncated at 6 would be "hello-", should become "hello"
        result = slugify("hello world test", max_length=6)
        assert not result.endswith("-")

    def test_empty_string(self) -> None:
        assert slugify("") == ""

    def test_all_special_chars(self) -> None:
        assert slugify("@#$%^&*") == ""

    def test_numbers_preserved(self) -> None:
        assert slugify("v2.0.1") == "v2-0-1"

    def test_underscores_replaced(self) -> None:
        assert slugify("my_feature_name") == "my-feature-name"

    def test_custom_max_length(self) -> None:
        result = slugify("very long feature name here", max_length=15)
        assert len(result) <= 15


class TestGenerateRunId:
    def test_format_with_feature(self) -> None:
        now = datetime(2026, 3, 1, 14, 30)
        rid = generate_run_id("dev", "auth-module", now=now)
        # YYMMDD-HHMM-dev-auth-module-XXXX
        assert rid.startswith("260301-1430-dev-auth-module-")
        assert len(rid.split("-")[-1]) == 4  # hex suffix

    def test_format_without_feature(self) -> None:
        now = datetime(2026, 3, 1, 14, 30)
        rid = generate_run_id("dev", now=now)
        # YYMMDD-HHMM-dev-XXXX
        assert rid.startswith("260301-1430-dev-")
        parts = rid.split("-")
        assert len(parts[-1]) == 4

    def test_uniqueness(self) -> None:
        now = datetime(2026, 3, 1, 14, 30)
        ids = {generate_run_id("dev", "auth", now=now) for _ in range(20)}
        assert len(ids) == 20

    def test_component_slugified(self) -> None:
        now = datetime(2026, 3, 1, 14, 30)
        rid = generate_run_id("My Custom Component", "test", now=now)
        assert "my-custom-component" in rid

    def test_feature_slugified(self) -> None:
        now = datetime(2026, 3, 1, 14, 30)
        rid = generate_run_id("dev", "User Auth Module!", now=now)
        assert "user-auth-module" in rid

    def test_empty_feature_omitted(self) -> None:
        now = datetime(2026, 3, 1, 14, 30)
        rid = generate_run_id("dev", "", now=now)
        # Should be YYMMDD-HHMM-dev-XXXX (no double hyphens)
        assert "--" not in rid.replace("260301-1430", "X")  # ignore date part

    def test_special_char_feature_treated_as_empty(self) -> None:
        now = datetime(2026, 3, 1, 14, 30)
        rid = generate_run_id("dev", "@#$%", now=now)
        # Feature slugifies to "", should omit
        assert rid.startswith("260301-1430-dev-")
        # Only 4 parts: date, time, comp, hex
        parts = rid.split("-")
        assert len(parts) == 4

    def test_default_uses_current_time(self) -> None:
        rid = generate_run_id("dev", "test")
        # Just verify it matches the expected pattern
        pattern = r"^\d{6}-\d{4}-dev-test-[0-9a-f]{4}$"
        assert re.match(pattern, rid)

    def test_hex_suffix_is_lowercase_hex(self) -> None:
        now = datetime(2026, 3, 1, 14, 30)
        rid = generate_run_id("dev", "test", now=now)
        hex_part = rid.split("-")[-1]
        assert re.match(r"^[0-9a-f]{4}$", hex_part)

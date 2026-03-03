from __future__ import annotations

import re
import uuid
from datetime import datetime


def slugify(text: str, max_length: int = 30) -> str:
    """Convert text to a URL-friendly slug.

    Lowercase, replace non-alphanumeric with hyphens, collapse consecutive
    hyphens, strip leading/trailing hyphens, truncate to max_length.
    """
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug


def generate_run_id(component: str, feature_name: str = "", *, now: datetime | None = None) -> str:
    """Generate a human-readable run ID.

    Format: YYMMDD-HHMM-{comp_slug}-{feat_slug}-{4hex}
    If feature_name is empty or slugifies to "", omit feature segment.
    """
    ts = now or datetime.now()
    date_part = ts.strftime("%y%m%d-%H%M")
    comp_slug = slugify(component, max_length=20)
    feat_slug = slugify(feature_name, max_length=30)
    hex_suffix = uuid.uuid4().hex[:4]

    if feat_slug:
        return f"{date_part}-{comp_slug}-{feat_slug}-{hex_suffix}"
    return f"{date_part}-{comp_slug}-{hex_suffix}"

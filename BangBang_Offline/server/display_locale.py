"""M31 display-only Vietnamese labels shared with the HTML5 client.

Original template rows, inventory IDs, account names and reward rules remain
unchanged. A label is applied only to the exact item ID AND source name that
was reviewed. No database or network access is needed by this module.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

LOCALE_PATH = Path(__file__).resolve().parent.parent / 'www' / 'html5' / 'm81331_locale_catalog.json'


@lru_cache(maxsize=1)
def _locale():
    try:
        value = json.loads(LOCALE_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if value.get('schemaVersion') != 1 or value.get('locale') != 'vi-VN':
        return {}
    return value


def item_name(item_id, source_name):
    """Use reviewed text only for its original static item identity/source."""
    source = str(source_name or '')
    row = _locale().get('itemNames', {}).get(str(item_id))
    if isinstance(row, dict) and row.get('source') == source and isinstance(row.get('text'), str):
        return row['text']
    return source

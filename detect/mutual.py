"""Directed revert pairs and mutual-war detection for one article."""

from __future__ import annotations

from datetime import datetime

from detect.models import DirectedCount
from detect.names import display_user, normalize_user


class PairGraph:
    """Edges are ``reverter → reverted`` inside one article's window."""

    def __init__(self) -> None:
        self._edges: list[tuple[str, str, str, str, datetime]] = []

    def add(self, reverter: str, reverted: str, timestamp: datetime) -> None:
        reverter_key = normalize_user(reverter)
        reverted_key = normalize_user(reverted)
        if not reverter_key or not reverted_key or reverter_key == reverted_key:
            return
        self._edges.append(
            (
                reverter_key,
                reverted_key,
                display_user(reverter),
                display_user(reverted),
                timestamp,
            )
        )

    def expire(self, cutoff: datetime) -> None:
        self._edges = [edge for edge in self._edges if edge[4] >= cutoff]

    def mutual_pairs(self) -> list[tuple[str, str]]:
        displays: dict[str, str] = {}
        forward: set[tuple[str, str]] = set()
        for reverter_key, reverted_key, reverter_name, reverted_name, _timestamp in self._edges:
            displays.setdefault(reverter_key, reverter_name)
            displays.setdefault(reverted_key, reverted_name)
            forward.add((reverter_key, reverted_key))
        found: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for reverter_key, reverted_key in forward:
            if (reverted_key, reverter_key) not in forward:
                continue
            key = _ordered_pair(reverter_key, reverted_key)
            if key in seen:
                continue
            seen.add(key)
            found.append((displays[key[0]], displays[key[1]]))
        found.sort(key=lambda pair: (pair[0].casefold(), pair[1].casefold()))
        return found

    def directed_counts(self) -> list[DirectedCount]:
        counts: dict[tuple[str, str], int] = {}
        labels: dict[tuple[str, str], tuple[str, str]] = {}
        for reverter_key, reverted_key, reverter_name, reverted_name, _timestamp in self._edges:
            key = (reverter_key, reverted_key)
            counts[key] = counts.get(key, 0) + 1
            labels.setdefault(key, (reverter_name, reverted_name))
        rows = [
            DirectedCount(reverter=labels[key][0], reverted=labels[key][1], count=count)
            for key, count in counts.items()
        ]
        rows.sort(key=lambda row: (-row.count, row.reverter.casefold(), row.reverted.casefold()))
        return rows

    def __len__(self) -> int:
        return len(self._edges)


def _ordered_pair(left: str, right: str) -> tuple[str, str]:
    if left <= right:
        return (left, right)
    return (right, left)

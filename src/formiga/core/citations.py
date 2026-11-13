"""Citation numbering, owned by code.

Numbers are assigned in order of first appearance of a note and frozen for the life of
the run, so re-rendering a report never renumbers (PRD §5, "Numbering"). The model
returns note ids; this module turns them into ``[n]`` markers.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CitationLedger:
    """Maps ``note_id -> n`` for one run."""

    _numbers: dict[int, int] = field(default_factory=dict)

    def number_of(self, note_id: int) -> int:
        """Return the frozen number of ``note_id``, assigning on first use."""
        existing = self._numbers.get(note_id)
        if existing is not None:
            return existing
        assigned = len(self._numbers) + 1
        self._numbers[note_id] = assigned
        return assigned

    def markers(self, note_ids: list[int]) -> str:
        """Render ``[1][3]`` for the distinct notes, in first-use order."""
        seen: list[int] = []
        for note_id in note_ids:
            if note_id not in seen:
                seen.append(note_id)
        return "".join(f"[{self.number_of(note_id)}]" for note_id in seen)

    def snapshot(self) -> dict[int, int]:
        return dict(self._numbers)

    def restore(self, numbers: dict[int, int]) -> None:
        self._numbers = dict(numbers)


__all__ = ["CitationLedger"]

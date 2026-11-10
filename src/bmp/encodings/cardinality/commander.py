"""Recursive commander at-most-one encoding with groups of at most three."""

from collections.abc import Callable, Sequence

from bmp.encodings.cardinality.base import AMOEncoder, VarAllocator, register_amo_encoder


def encode_commander_amo(
    literals: Sequence[int], new_var: Callable[[], int]
) -> list[list[int]]:
    """Return AMO clauses, allocating fresh positive variable IDs via ``new_var``.

    The caller must share one allocator across constraints and start it above all
    input variable IDs in the complete formula. A literal may be positive or
    negative; zero is not a valid DIMACS literal.
    """
    if any(literal == 0 for literal in literals):
        raise ValueError("literal 0 is invalid")

    used_ids = {abs(literal) for literal in literals}
    clauses: list[list[int]] = []

    def encode_level(level: Sequence[int]) -> None:
        if len(level) < 2:
            return
        if len(level) <= 3:
            for index, left in enumerate(level):
                for right in level[index + 1 :]:
                    clauses.append([-left, -right])
            return

        commanders: list[int] = []
        for start in range(0, len(level), 3):
            group = level[start : start + 3]
            for index, left in enumerate(group):
                for right in group[index + 1 :]:
                    clauses.append([-left, -right])
            commander = new_var()
            if not isinstance(commander, int) or commander <= 0 or commander in used_ids:
                raise ValueError("new_var must return a fresh positive variable ID")
            used_ids.add(commander)
            commanders.append(commander)
            for literal in group:
                clauses.append([-literal, commander])
        encode_level(commanders)

    encode_level(literals)
    return clauses


class CommanderAMOEncoder(AMOEncoder):
    """Adapter for the team's AMO registry and shared variable allocator."""

    def encode(
        self, literals: Sequence[int], allocator: VarAllocator
    ) -> tuple[list[list[int]], list[int]]:
        auxiliary_variables: list[int] = []

        def new_var() -> int:
            variable = allocator.allocate(1)[0]
            auxiliary_variables.append(variable)
            return variable

        return encode_commander_amo(literals, new_var), auxiliary_variables


register_amo_encoder("commander", CommanderAMOEncoder)

__all__ = ["CommanderAMOEncoder", "encode_commander_amo"]

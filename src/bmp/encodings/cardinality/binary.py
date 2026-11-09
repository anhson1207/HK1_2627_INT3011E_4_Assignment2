"""Binary (bitwise) at-most-one encoding."""

from collections.abc import Callable, Sequence

from bmp.encodings.cardinality.base import AMOEncoder, VarAllocator, register_amo_encoder


def encode_binary_amo(
    literals: Sequence[int], new_var: Callable[[], int]
) -> list[list[int]]:
    """Return AMO clauses, allocating fresh positive variable IDs via ``new_var``.

    The caller must share one allocator across constraints and start it above all
    input variable IDs in the complete formula. A literal may be positive or
    negative; zero is not a valid DIMACS literal.
    """
    if any(literal == 0 for literal in literals):
        raise ValueError("literal 0 is invalid")
    if len(literals) < 2:
        return []

    used_ids = {abs(literal) for literal in literals}
    bits: list[int] = []
    for _ in range((len(literals) - 1).bit_length()):
        bit = new_var()
        if not isinstance(bit, int) or bit <= 0 or bit in used_ids:
            raise ValueError("new_var must return a fresh positive variable ID")
        used_ids.add(bit)
        bits.append(bit)

    clauses: list[list[int]] = []
    for code, literal in enumerate(literals):
        for position, bit in enumerate(bits):
            required_bit = bit if code & (1 << position) else -bit
            clauses.append([-literal, required_bit])
    return clauses


class BinaryAMOEncoder(AMOEncoder):
    """Adapter for the team's AMO registry and shared variable allocator."""

    def encode(
        self, literals: Sequence[int], allocator: VarAllocator
    ) -> tuple[list[list[int]], list[int]]:
        auxiliary_variables: list[int] = []

        def new_var() -> int:
            variable = allocator.allocate(1)[0]
            auxiliary_variables.append(variable)
            return variable

        return encode_binary_amo(literals, new_var), auxiliary_variables


register_amo_encoder("binary", BinaryAMOEncoder)

__all__ = ["BinaryAMOEncoder", "encode_binary_amo"]

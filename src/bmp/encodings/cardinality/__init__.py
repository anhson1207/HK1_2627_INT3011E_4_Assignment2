"""Cardinality constraints expressed as CNF clauses."""

from bmp.encodings.cardinality.base import SimpleVarAllocator, get_amo_encoder
from bmp.encodings.cardinality.pairwise_amo import PairwiseAMOEncoder
from bmp.encodings.cardinality.sequential import SequentialCounterAMOEncoder
from bmp.encodings.cardinality.binary import BinaryAMOEncoder, encode_binary_amo
from bmp.encodings.cardinality.commander import CommanderAMOEncoder, encode_commander_amo

__all__ = [
    "BinaryAMOEncoder", "CommanderAMOEncoder", "PairwiseAMOEncoder",
    "SequentialCounterAMOEncoder", "SimpleVarAllocator", "get_amo_encoder",
    "encode_binary_amo", "encode_commander_amo",
]

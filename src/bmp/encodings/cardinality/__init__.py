"""Cardinality encodings for SAT."""

from bmp.encodings.cardinality.base import (
    AMOEncoder,
    SimpleVarAllocator,
    VarAllocator,
    get_amo_encoder,
    register_amo_encoder,
)
from bmp.encodings.cardinality.binary import BinaryAMOEncoder, encode_binary_amo
from bmp.encodings.cardinality.commander import CommanderAMOEncoder, encode_commander_amo
from bmp.encodings.cardinality.pairwise_amo import PairwiseAMOEncoder
from bmp.encodings.cardinality.sequential import SequentialCounterAMOEncoder

__all__ = [
    "AMOEncoder",
    "BinaryAMOEncoder",
    "CommanderAMOEncoder",
    "PairwiseAMOEncoder",
    "SequentialCounterAMOEncoder",
    "SimpleVarAllocator",
    "VarAllocator",
    "encode_binary_amo",
    "encode_commander_amo",
    "get_amo_encoder",
    "register_amo_encoder",
]

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
from bmp.encodings.cardinality.ladder import LadderAMOEncoder, encode_ladder_amo
from bmp.encodings.cardinality.pairwise_amo import PairwiseAMOEncoder
from bmp.encodings.cardinality.product import ProductAMOEncoder, encode_product_amo
from bmp.encodings.cardinality.sequential import SequentialCounterAMOEncoder

__all__ = [
    "AMOEncoder",
    "BinaryAMOEncoder",
    "CommanderAMOEncoder",
    "LadderAMOEncoder",
    "PairwiseAMOEncoder",
    "ProductAMOEncoder",
    "SequentialCounterAMOEncoder",
    "SimpleVarAllocator",
    "VarAllocator",
    "encode_binary_amo",
    "encode_commander_amo",
    "encode_ladder_amo",
    "encode_product_amo",
    "get_amo_encoder",
    "register_amo_encoder",
]

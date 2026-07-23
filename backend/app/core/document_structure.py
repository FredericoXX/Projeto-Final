"""Vocabulário estrutural partilhado pelo chunking e pela persistência.

Os valores são deliberadamente pequenos, determinísticos e independentes
do tipo de documento ou da instituição. As colunas correspondentes na base
aceitam ``NULL`` para preservar chunks históricos.
"""

from typing import Literal

StructureType = Literal[
    "heading",
    "paragraph",
    "table_row",
    "list_item",
    "list_block",
    "mixed",
    "fallback_fragment",
]

ChunkingStrategy = Literal["structured_v1", "character_fallback_v1"]

STRUCTURE_TYPES: tuple[StructureType, ...] = (
    "heading",
    "paragraph",
    "table_row",
    "list_item",
    "list_block",
    "mixed",
    "fallback_fragment",
)

CHUNKING_STRATEGIES: tuple[ChunkingStrategy, ...] = (
    "structured_v1",
    "character_fallback_v1",
)

STRUCTURED_STRATEGY: ChunkingStrategy = "structured_v1"
CHARACTER_FALLBACK_STRATEGY: ChunkingStrategy = "character_fallback_v1"

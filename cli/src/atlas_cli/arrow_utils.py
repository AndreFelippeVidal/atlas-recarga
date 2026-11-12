"""Utilitários de Arrow compartilhados pelos cenários."""

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from numpy.typing import NDArray


def set_rows(
    table: pa.Table, column: str, idx: NDArray[np.int64], values: pa.Array | pa.ChunkedArray
) -> pa.Table:
    """Substitui `column` nas linhas `idx` (ordenadas, sem repetição) por `values` (mesma ordem)."""
    if len(idx) == 0:
        return table
    if isinstance(values, pa.ChunkedArray):
        values = values.combine_chunks()
    mask = np.zeros(table.num_rows, dtype=bool)
    mask[idx] = True
    position = table.schema.get_field_index(column)
    field = table.schema.field(position)
    replaced = pc.replace_with_mask(
        table[column].combine_chunks(), pa.array(mask), values.cast(field.type)
    )
    return table.set_column(position, field, replaced)

# RAG and GRAG implementation
Data stored for RAG uses an optional key-value store, an optional vector store, and an optional property graph; if the property graph exists, there must be a vector store, and the property graph will link to a referenced text chunk in the vector store from each node. We call this hybrid data set a Z-Bundle. It has both a slug for the bundle itself (e.g. the slug for a Z-World) and for the type (e.g. "world")

## Specifications
When a [Process](Processes.md) requires access to a Z-Bundle, the type of the Z-Bundle is specified in the process definition, and the data structure of the type of Z-Bundle is specified in a separate file (e.g. [Z-World](Z-World.md), as a Z-World is a type of Z-Bundle referenced as an output of the World Generation process and an input to the Experience Generation process.)

Any Z-Bundle that contains a vector store **must** record the identity of the embedding model used to encode it in the KVP store (as `embedding_model_name` and `embedding_model_size_bytes`). This allows the application to detect when the currently configured embedding model differs from the one used at encoding time. See [Local LLM Execution](Local%20LLM%20Execution.md) for the mismatch policy.

## Implementation
Each Z-Bundle is stored in "bundles/{typeslug}/{slug}", e.g. "bundles/world/wayfarers". Henceforth, the "root path" or "root".

Key-Value data is recorded in "{root}/kvp.json", in JSON format.

Vector stores are recorded in a LanceDB database in "{root}/vector/". The LanceDB table within every Z-Bundle is named **`chunks`**. Each row has the following columns:
- `vector`: embedding array (produced by the [embedding model](Local%20LLM%20Execution.md))
- `entity_id`: stable string identifier, shared with the property graph node
- `entity_type`: string label (e.g., `"character"`, `"location"`)
- `text`: the serialized natural-language chunk text

Property graphs are recorded in a KùzuDB database file at `{root}/propertygraph`. The schema is managed entirely by `KuzuGraph.add_graph_documents` (from `langchain_community.graphs`), which creates:
- **Per-type node tables** — one node table per entity type in `allowed_nodes` (e.g., `Character`, `Location`, `Event`, `Faction`). Node properties include at minimum `id` and `text`.
- **Per-type-pair relationship tables** — one rel table per (source-type, relationship-type, target-type) triple encountered in the extracted data. The relationship type is encoded in the table name rather than stored as a column.
- **`Chunk` node table** (when `include_source=True`) — one node per source text chunk, with edges from every extracted entity node back to the chunk it was extracted from, enabling hybrid lookup: given any entity, retrieve the original passage.

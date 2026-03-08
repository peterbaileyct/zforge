# RAG and GRAG implementation
Data stored for RAG uses an optional key-value store, an optional vector store, and an optional property graph; if the property graph exists, there must be a vector store, and the property graph will link to a referenced text chunk in the vector store from each node. We call this hybrid data set a Z-Bundle. It has both a slug for the bundle itself (e.g. the slug for a Z-World) and for the type (e.g. "world")

## Specifications
When a [Process](Processes.md) requires access to a Z-Bundle, the type of the Z-Bundle is specified in the process definition, and the data structure of the type of Z-Bundle is specified in a separate file (e.g. [Z-World](Z-World.md), as a Z-World is a type of Z-Bundle referenced as an output of the World Generation process and an input to the Experience Generation process.)

Any Z-Bundle that contains a vector store **must** record the identity of the embedding model used to encode it in the KVP store (as `embedding_model_name` and `embedding_model_size_bytes`). This allows the application to detect when the currently configured embedding model differs from the one used at encoding time. See [Local LLM Execution](Local%20LLM%20Execution.md) for the mismatch policy.

## Implementation
Each Z-Bundle is stored in "bundles/{typeslug}/{slug}", e.g. "bundles/world/wayfarers". Henceforth, the "root path" or "root".

Key-Value data is recorded in "{root}/kvp.json", in JSON format.

Vector stores are recorded in a LanceDB database in "{root}/vector/". Each row has the following columns:
- `vector`: embedding array (produced by the [embedding model](Local%20LLM%20Execution.md))
- `entity_id`: stable string identifier, shared with the property graph node
- `entity_type`: string label (e.g., `"character"`, `"location"`)
- `text`: the serialized natural-language chunk text

Property graphs are recorded in a KùzuDB database in "{root}/propertygraph". All entities are stored in a single `Entity` node table (columns: `entity_id`, `entity_type`). Relationships are stored in a single `Relationship` rel table from `Entity` to `Entity` with a `type` string property, so arbitrary relationship types are stored as data rather than requiring schema changes. Each node's `entity_id` matches the corresponding vector store row.

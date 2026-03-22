# RAG and GRAG Implementation

A Z-Bundle is a hybrid data set consisting of up to four complementary stores: an optional raw text file, an optional key-value store, an optional vector store, and an optional property graph. If a vector store is present, a property graph must also be present; every vector entity links back to the node in the property graph. A Z-Bundle has both a type slug (e.g. `"world"`) and an instance slug (e.g. `"wayfarers"`).

The ontology for a bundle -- the specific entity types, relationship types, and KVP fields -- for any given Z-Bundle type are defined in that type's own spec (e.g. [Z-World](Z-World.md)). This document covers the structure, schema contracts, and retrieval patterns that apply to **all** Z-Bundle types.

## Z-Bundle Structure

Each Z-Bundle is stored at `bundles/{typeslug}/{slug}/` — e.g. `bundles/world/wayfarers`. All paths below are relative to this root.

| Path | Contents |
|---|---|
| `raw.txt` | Raw text |
| `kvp.json` | Key-value metadata in JSON format |
| `vector/` | LanceDB vector store |
| `propertygraph` | KùzuDB property graph file (not a directory) |

When a [Process](Processes.md) requires access to a Z-Bundle it declares the Z-Bundle type; the expected data structure for that type is specified in the type's own spec file.

Any Z-Bundle that contains a vector store **must** record the identity of the embedding model used to encode it in the KVP store (`embedding_model_name`, `embedding_model_size_bytes`). This allows the application to detect when the currently configured embedding model differs from the one used at encoding time. See [Local LLM Execution](Local%20LLM%20Execution.md) for the mismatch policy.

## Schema

### Vector

Two LanceDB tables are written per Z-Bundle. Both share the same column schema:

| Column | Type | Description |
|---|---|---|
| `vector` | `float32[]` | Embedding vector |
| `entity_id` | `STRING` | For `chunks`: the KuzuDB `Chunk.id` of the source chunk. For `entities`: the KuzuDB entity node `id` directly. |
| `entity_type` | `STRING` | snake_case node type (see [Z-World § entity_type Casing](Z-World.md#entity_type-casing-lancedb--kuzu)). For `entities` rows, the entity's own type (e.g. `character`). For `chunks` rows, the primary entity type of the source chunk. |
| `text` | `STRING` | The raw chunk text (`chunks`) or the LLM-synthesized entity summary (`entities`). |

**`chunks` table** — one row per retrieval sub-chunk from Phase 3 of the parsing pipeline. The `entity_id` is the KuzuDB `Chunk` node id. This is the ground-truth verbatim record and is used for precise source passage retrieval.

**`entities` table** — one row per entity node from Phase 5 (entity summarization). The `entity_id` is the entity's KuzuDB node `id` (e.g. a `Character` id). This table is used as the default for entity-centric queries — a single call to `query_world` returns a synthesized 1–5 paragraph summary of the entity plus its graph neighbourhood without a follow-up call. If Phase 5 is skipped (`entity_summarization_enabled = false`), this table is absent and `query_world` falls back to the `chunks` table.

### Graph

KuzuDB uses a strict typed schema managed by `_MultiTypeKuzuGraph` (see Implementation). The schema for a given Z-Bundle type is governed by the `allowed_nodes` and `allowed_relationships` lists declared in that type's spec. **These lists must be defined at design time and must not change after a Z-Bundle instance has been written** — any change requires re-parsing the source document.

**Node tables** — one table per entry in `allowed_nodes`. Every node table has at minimum:
- `id` (`STRING`, primary key) — stable entity identifier; must match `entity_id` in LanceDB for any chunk derived from this entity.
- `type` (`STRING`) — the node's type label (redundant with the table name; retained for compatibility with `LLMGraphTransformer`).
- `text` (`STRING`) — a brief natural-language description of the entity, populated when the LLM extraction provides one. May be empty.

**Relationship table groups** — one group per relationship type in `allowed_relationships`, spanning the full cross-product of `allowed_nodes` pairs. Relationship types encode domain semantics (e.g. `member_of`, `located_at`); they are defined per Z-Bundle type spec.

**`Chunk` node table** — always present when a property graph exists (`include_source=True`):
- `id` (`STRING`, primary key) — matches `entity_id` in the corresponding LanceDB row.
- `text` (`STRING`) — the chunk's prose text.
- `type` (`STRING`) — always `"Chunk"`.

**`MENTIONS` relationship table group** — edges from every `Chunk` node to every entity node extracted from that chunk. This is the structural bridge between the two stores.

### Cross-Reference Contract

`entity_id` in LanceDB and `id` in the KuzuDB `Chunk` table are the **same value** for the same source chunk. This contract enables joined retrieval without a secondary lookup layer:

```
LanceDB row (entity_id = "chunk-42")
    ↕  same id
KuzuDB Chunk node (id = "chunk-42")
    ↕  MENTIONS edges
KuzuDB entity nodes (Character, Location, …)
```

Code that writes to either store must preserve this contract. Code that queries either store may exploit it to avoid redundant LLM round-trips (see Retrieval Patterns).

## Retrieval Patterns

These patterns apply to any [Process](Processes.md) that queries a Z-Bundle. They are listed in order of increasing specificity and decreasing LLM round-trip cost.
0-p[pokl;'
][pop;[']p;'[]p;'/[p;'/[po;'/[pol;'/[]-pm ,'
]=[-p'/
]]]]]]
### Unified Entity Query (`query_world`) — primary tool

```
query_world(query: str, entity_type: str | None = None, take_top_matches: int = 1, include_neighbors: bool = False) → str
```

Resolves a natural-language question to a structured response in a single tool call by combining semantic entity matching, graph neighbourhood expansion, and optional neighbour summary hydration:

1. **Semantic match:** Run vector similarity search against the `entities` table to find the top-`take_top_matches` matching entity summaries. If `entity_type` is provided, apply a LanceDB `where` clause to restrict to that type. If the `entities` table is absent (Phase 5 was skipped), fall back to the `chunks` table.
2. **Graph expansion:** For each matched entity, look up its 1-hop graph neighbourhood in KuzuDB — all incoming and outgoing non-Chunk edges, including relationship type, direction, neighbour id, neighbour type, and any populated relationship properties.
3. **Neighbour hydration (optional):** If `include_neighbors=True`, fetch the `entities` table row for each unique neighbour to include its summary text alongside its own 1-hop relationships. Capped at `take_top_matches` neighbour summaries per matched entity to avoid context overflow.

Return format (structured text):

```
[Entity: "Ankh-Morpork" (location)]
Summary: Ankh-Morpork is the largest city on the Disc…

Relationships:
  → located_in → The Disc (region)
  ← based_in ← City Watch (organization)  [role: law enforcement]
  ← controls ← Havelock Vetinari (character)  [from_time: "the Interregnum"]

[Neighbour: "Havelock Vetinari" (character)]  ← only if include_neighbors=True
Summary: Havelock Vetinari is the Patrician of Ankh-Morpork…
Relationships:
  → controls → Ankh-Morpork (location)
  …
```

This is the default tool for all world-querying agents. A typical entity-centric question ("who is X?", "what does Y control?") resolves in a single call. Use `include_neighbors=True` for network questions ("who does X know?", "what is connected to Y?").

### Verbatim Source Retrieval (`retrieve_source`)

```
retrieve_source(query: str, entity_type: str | None = None, take_top_matches: int = 5) → list[str]
```

Semantic similarity search against the `chunks` table only. Returns raw source sub-chunks for verbatim fact retrieval. Use when the question requires exact wording (contradictions, rumours, specific quotes) or when entity summaries may over-synthesize details. The optional `entity_type` filter applies a LanceDB `where` clause to restrict to chunks whose primary entity is of that type.

### Relationship Query (`find_relationship`, `find_relationship_by_name`)

Two tools for answering questions of the form "what is the relationship between X and Y?"

```
find_relationship(entity_id_a: str, entity_id_b: str) → str
```

Pure graph traversal between two known entity IDs. Executes two complementary Cypher queries:

1. **Direct edges** — all edges in either direction between the two nodes, excluding `Chunk` nodes:
   `MATCH (a)-[r]-(b) WHERE a.id = $id_a AND b.id = $id_b AND NOT label(a) = 'Chunk' AND NOT label(b) = 'Chunk' RETURN type(r), label(a), a.id, label(b), b.id`
2. **Shared neighbours** — intermediate nodes that both entities connect to (1-hop common ground):
   `MATCH (a)-[r1]-(m)-[r2]-(b) WHERE a.id = $id_a AND b.id = $id_b AND NOT label(m) = 'Chunk' RETURN label(m), m.id, type(r1), type(r2)`

Return format (structured text):

```
[Relationship: "Havelock Vetinari" (character) ↔ "Ankh-Morpork" (location)]

Direct edges:
  Havelock Vetinari → controls → Ankh-Morpork

Shared neighbours:
  both connected via: Unseen University (organization)
    Havelock Vetinari → oversees → Unseen University
    Ankh-Morpork ← located_in ← Unseen University
```

If neither direct edges nor shared neighbours exist, returns a plain statement that no graph relationship was found.

---

```
find_relationship_by_name(
    name_a: str,
    name_b: str,
    entity_type_a: str | None = None,
    entity_type_b: str | None = None
) → str
```

Name-resolution wrapper around `find_relationship`. Performs two parallel vector similarity lookups against the `entities` table (one per name, each with `take_top_matches=1`) with optional `entity_type` filters, extracts the `entity_id` from each top result, then calls `find_relationship(entity_id_a, entity_id_b)`. Prepends the resolved entity identities to the output so the caller can confirm the intended entities were matched:

```
Resolved: "Vetinari" → "Havelock Vetinari" (character)
Resolved: "the city" → "Ankh-Morpork" (location)

[Relationship: …]
…
```

If either lookup returns no result, returns a plain statement that the named entity could not be resolved, and does not call `find_relationship`.

This is the default tool for relationship questions when the caller has plain-text names rather than stable entity IDs. Use `find_relationship` directly when IDs are already known (e.g. from a prior `query_world` response).

### Entity Catalog (`list_entities`)

```
list_entities(entity_type: str, limit: int = 20) → str
```

Deterministic catalog scan of a single KuzuDB node table. Returns up to `limit` entities of the given type, each with their `id`, `type`, and `text` fields. No vector search — pure graph read:

```cypher
MATCH (n:<EntityType>) RETURN n.id, n.type, n.text LIMIT $limit
```

Return format (structured text):

```
[Entity Catalog: character (20 results)]
- "Havelock Vetinari" (character): The Patrician of Ankh-Morpork…
- "Sam Vimes" (character): Commander of the City Watch…
…
```

Use for questions like "who are all the characters in this world?" or when building a complete scene roster at the start of experience generation. `entity_type` must be one of the `allowed_nodes` for the Z-Bundle (e.g. `character`, `location`, `organization`).

### Targeted Neighbour Traversal (`get_neighbors`)

```
get_neighbors(
    entity_id: str,
    relationship_type: str | None = None,
    neighbor_type: str | None = None
) → str
```

Targeted 1-hop graph traversal from a known entity ID. Returns all neighbouring entities with their relationship type and direction, optionally filtered by relationship type and/or neighbour type. No vector search — pure graph read. Excludes `Chunk` nodes.

Return format (structured text):

```
[Neighbours of "Ankh-Morpork" (location)]
  ← based_in ← City Watch (organization)
  ← controls ← Havelock Vetinari (character)
  → located_in → The Disc (region)
```

Use when iteratively building scene context from entities already identified — more surgical than `query_world` with neighbour hydration because it involves no vector search and no summary fetching. Also useful for "what characters are at this location?", "what items does this character carry?", etc.

### Path Query (`find_path`)

```
find_path(entity_id_a: str, entity_id_b: str, max_depth: int = 4) → str
```

Shortest-path traversal between two known entity IDs using KuzuDB's `shortestPath` algorithm, excluding `Chunk` nodes, up to `max_depth` hops. Answers "how is X connected to Y through the world graph?" where no direct or 1-hop shared relationship exists. Surfaces non-obvious narrative hooks and indirect power structures.

Executes:
```cypher
MATCH p = shortestPath((a)-[*1..$max_depth]-(b))
WHERE a.id = $id_a AND b.id = $id_b
AND ALL(n IN nodes(p) WHERE NOT label(n) = 'Chunk')
RETURN [n IN nodes(p) | {id: n.id, type: label(n)}],
       [r IN relationships(p) | type(r)]
```

Return format (structured text):

```
[Path: "Tiffany Aching" (character) → "The Long Man" (location)]
Depth: 3
  Tiffany Aching → lives_in → The Chalk (location)
  The Chalk → part_of → The Ramtops (region)
  The Ramtops → contains → The Long Man (location)
```

If no path exists within `max_depth`, returns a plain statement to that effect. Use `find_relationship` first for direct/1-hop queries; use `find_path` when those return no results or when the question explicitly asks about indirect connections.

### Entity Source Passages (`get_source_passages`)

```
get_source_passages(entity_id: str, take_top_matches: int = 5) → list[str]
```

Retrieves raw source chunks that mention a known entity by following `MENTIONS` edges in KuzuDB — no vector search. More precise and cheaper than `retrieve_source` when the entity is already identified, because it goes directly to the graph rather than re-running a similarity search.

Executes:
```cypher
MATCH (c:Chunk)-[:MENTIONS]->(n)
WHERE n.id = $entity_id
RETURN c.text
LIMIT $take_top_matches
```

Returns the raw `text` field of each matching `Chunk` node as a list of strings. Use when an agent needs verbatim source grounding for a specific entity it has already found via `query_world` or another graph tool, without paying the cost of a second vector round-trip.

### Vector-Seeded Graph Expansion (code pattern)

Use the vector store to find semantically relevant chunks, then expand their entity neighbourhood in the property graph. This is a code-level pattern for custom queries, not a bound LLM tool:

1. Run `retrieve_source` (optionally filtered) to obtain top-k chunk `entity_id` values.
2. Execute a Cypher query in KuzuDB: `MATCH (c:Chunk) WHERE c.id IN $ids MATCH (c)-[:MENTIONS]->(n)-[r]-(m) WHERE NOT label(m) = 'Chunk' RETURN …`

This surfaces the structured relationships *around* the semantically matching passages — useful for custom queries where the question involves connections between entities rather than descriptions of a single entity.

### Hybrid BM25 + Semantic Search (future)

LanceDB supports full-text (BM25) indexing alongside vector indexing on the same table. Combining both scores via Reciprocal Rank Fusion (RRF) improves precision for proper-noun-heavy queries (entity names that embed poorly relative to their importance). This pattern is not yet implemented but requires no schema changes — the existing `chunks` table supports it.

## Implementation

Each Z-Bundle is stored in `bundles/{typeslug}/{slug}/` on the local filesystem (see [File Storage](File%20Storage.md) for the resolved base path).

The `make_world_query_tools(z_bundle_root, allowed_node_labels, embedding_connector)` factory in `graph_utils.py` constructs and returns all eight tools as a tuple: `query_world`, `retrieve_source`, `find_relationship`, `find_relationship_by_name`, `list_entities`, `get_neighbors`, `find_path`, and `get_source_passages`. It takes `allowed_node_labels` as a parameter (the same `allowed_nodes` list used at ingest time) so the graph keyword branch can query the correct set of node tables without hardcoding them. **Each Z-Bundle type that uses these tools must pass its own `allowed_nodes` list when constructing them.**

### Pitfall: `query_world` graph expansion must execute queries, not just return the schema

A naive implementation that returns only `graph.get_schema` for the graph expansion step wastes a full LLM round-trip: the model receives schema with no data and retries. The schema dump is also misleading when the tool docstring advertises entity and relationship lookup.

**The correct pattern** (implemented as the graph expansion step in `graph_utils.make_world_query_tools`) has two branches:

1. **Cypher branch** — if the query begins with a Cypher keyword (`MATCH`, `WITH`, `CALL`, etc.), execute it via `KuzuGraph.query(cypher)`, which delegates to `kuzu.Connection.execute()`. Return the rows directly (up to 50). On error or empty results, append the schema so the model can correct the query.

2. **Keyword branch** — otherwise, search the `id` property of every node table in `allowed_node_labels` case-insensitively via `toLower(n.id) CONTAINS $kw`, using `KuzuGraph.query(cypher, params={"kw": keyword})` (parameterised queries are supported). For each matched entity, expand one hop of outgoing and incoming edges — excluding `Chunk` nodes — and include relationship type via `type(r)` and neighbour type via `label(m)`. Return schema only when no entities match.

This ensures that for factual questions (e.g. "who are the queens?"), the graph expansion returns matched entity nodes and their relationships directly as part of the `query_world` response, eliminating the need for a second tool call (~1–2 s saved on Groq).

# RAG and GRAG implementation
Data stored for RAG uses an optional key-value store, an optional vector store, and an optional property graph; if the property graph exists, there must be a vector store, and the property graph will link to a referenced text chunk in the vector store from each node. We call this hybrid data set a Z-Bundle. It has both a slug for the bundle itself (e.g. the slug for a Z-World) and for the type (e.g. "world")

## Specifications
When a [Process](Processes.md) requires access to a Z-Bundle, the type of the Z-Bundle is specified in the process definition, and the data structure of the type of Z-Bundle is specified in a separate file (e.g. [Z-World](Z-World.md), as a Z-World is a type of Z-Bundle referenced as an output of the World Generation process and an input to the Experience Generation process.)

## Implementation
Each Z-Bundle is stored in "bundles/{typeslug}/{slug}", e.g. "bundles/world/wayfarers". Henceforth, the "root path" or "root".

Key-Value data is recorded in "{root}/kvp.json", in JSON format.

Vector stores are recorded in a LanceDB database in "{root}/vector/".

Property graphs are recorded in a KùzuDB database in "{root}/propertygraph". Each node references a text chunk in the related vector store.

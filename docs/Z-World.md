# Z-World
A Z-Forge World specification is a Z-Bundle used for [RAG](RAG%20and%20GRAG%20Implementation.md). The type slug for it is "world". It contains the following elements:

## Key-Value
- Title (human-readable, full text, e.g. "Discworld")
- slug (dash-case, unique among Z-Worlds on the same device, e.g. "lord-of-the-rings")
- UUID
- Summary (1-3 paragraphs of plain text describing the world in diagetic terms, used to help unfamiliar users to pick a world for experience generation and to help kick-start experience generation, especially where no prompt is given)

## Vector
Lists of:
- Characters
- Locations (at any granularity, as long as there is a significance to the location, e.g. "Sto Plains", "Lancre", and "Ankh-Morpork", but also "Ramkin House", "Dragon Pens", and "Chubby's Pen").
- Events (includes a description and a time)
- Mechanics (e.g. "magic exists and its use is divided between academic but often silly wizards and rural, under-respected witches who function largely as doctors and midwives")
- Tropes (both for story elements and narrative style, e.g. "stories often feature found families" and "frequent, long footnotes detailing world history and languages")
- Species (if absent, assumed to map to Earth species)
- Occupations (may be real-world occupations often emphasized in the fictional world, or invented occupations specific to it)

## Property Graph
Describes relationships between the above elements in the vector store. Examples include, but are not limited to:
{character} friends_with {character}
{character} present_at {event}
{character} is_a {species}
{character} is_a {occupation}
{location} west_of {location}
{location} inside_of {location}

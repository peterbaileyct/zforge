# Z-Forge World Format (.zworld)
A Z-Forge World specification, recorded in JSON format with the .zworld extension, includes the following details:
- Id, a unique text identifier for the world used for cross-referencing and file organization, e.g. "discworld"
- Name, e.g. "Discworld"
- Locations, which can be indicated at nested levels of granularity
- Characters, who have a text id (to allow for unambiguous cross-reference), one or more Names, with each having a Context in the form of a brief free-text description in the case of multiple names, a History
- Relationships, which describe the personal history and current social/professional/emotional relationships between two characters, identified by their text ids
- Events, which are descriptions of significant occurrences within this World that greatly affected Characters and/or Locations; each has a "Date", though this can be a literal date according to an in-world numeric calendar or a description of approximate time relative to other events

### 1.1. Sample World JSON Schema
```json
{
  "id": "discworld",
  "name": "Discworld",
  "locations": [
    {
      "id": "ankh-morpork",
      "name": "Ankh-Morpork",
      "description": "A bustling, grimy city at the heart of Discworld.",
      "sublocations": [
        { "id": "bank", "name": "Royal Bank of Ankh-Morpork", "description": "The city bank." }
      ]
    }
  ],
  "characters": [
    {
      "id": "moist",
      "names": [
        { "name": "Moist von Lipwig", "context": "Birth name; used once again following his forced retirement from a life of crime." }, { "name": "Albert Spangler", "context": "Alias from a multi-year career as a conman." }
      ],
      "history": "A conman turned civil servant, Moist Von Lipwig is both the Postmaster General of Ankh-Morpork and chairman of its bank."
    }, 
    {
      "id": "vetinari",
      "names": [
        { "name": "Havelock Vetinari" }
      ],
      "history": "Patrician of the city of Ankh-Morpork, Havelock Vetinari is famed for his intelligence and his calculating manner. Vetinari's cold demeanor and occasionally brutal methods belie his powerful drive to uplift his society and ensure the safety of his city and its people."
    }
  ],
  "relationships": [
        { "character_a_id": "moist", "character_b_id": "vetinari", "description": "When Moist was scheduled to be hanged for his crimes, Vetinari arranged for his hanging to be faked and pressed him into service under his real name (unknown at the time in Ankh-Morpork) as Postmaster General. Moist's massive success in this endeavor led Vetinari to leverage him further as chairman of the bank. Moist reports directly to Vetinari in both roles. Due to Moist's criminal past, Vetinari leaves their relationship and Moist's safety intentionally tenuous despite his obvious admiration of Moist's unique skillset." }
      ],
  "events": [
    {
      "description": "The gold goes missing from the bank vault.",
      "date": "Year of the Prawn, 12th day" // or relative: "Shortly after Moist's appointment"
    }
  ]
}
```
- All fields are required unless otherwise specified.
- `locations` can be nested arbitrarily.
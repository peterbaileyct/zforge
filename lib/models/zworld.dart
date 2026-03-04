// Data model for a Z-Forge World (.zworld JSON format).
// See docs/ZWorld.md for the full specification.

class CharacterName {
  final String name;
  final String? context;

  const CharacterName({required this.name, this.context});

  factory CharacterName.fromJson(Map<String, dynamic> json) => CharacterName(
        name: json['name'] as String,
        context: json['context'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'name': name,
        if (context != null) 'context': context,
      };
}

class Character {
  final String id;
  final List<CharacterName> names;
  final String history;

  const Character({
    required this.id,
    required this.names,
    required this.history,
  });

  factory Character.fromJson(Map<String, dynamic> json) => Character(
        id: json['id'] as String,
        names: (json['names'] as List<dynamic>)
            .map((n) => CharacterName.fromJson(n as Map<String, dynamic>))
            .toList(),
        history: json['history'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'names': names.map((n) => n.toJson()).toList(),
        'history': history,
      };
}

class Location {
  final String id;
  final String name;
  final String description;
  final List<Location> sublocations;

  const Location({
    required this.id,
    required this.name,
    required this.description,
    this.sublocations = const [],
  });

  factory Location.fromJson(Map<String, dynamic> json) => Location(
        id: json['id'] as String,
        name: json['name'] as String,
        description: json['description'] as String,
        sublocations: (json['sublocations'] as List<dynamic>? ?? [])
            .map((l) => Location.fromJson(l as Map<String, dynamic>))
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'description': description,
        if (sublocations.isNotEmpty)
          'sublocations': sublocations.map((l) => l.toJson()).toList(),
      };
}

class Relationship {
  final String characterAId;
  final String characterBId;
  final String description;

  const Relationship({
    required this.characterAId,
    required this.characterBId,
    required this.description,
  });

  factory Relationship.fromJson(Map<String, dynamic> json) => Relationship(
        characterAId: json['character_a_id'] as String,
        characterBId: json['character_b_id'] as String,
        description: json['description'] as String,
      );

  Map<String, dynamic> toJson() => {
        'character_a_id': characterAId,
        'character_b_id': characterBId,
        'description': description,
      };
}

class WorldEvent {
  final String description;
  final String date;

  const WorldEvent({required this.description, required this.date});

  factory WorldEvent.fromJson(Map<String, dynamic> json) => WorldEvent(
        description: json['description'] as String,
        date: json['date'] as String,
      );

  Map<String, dynamic> toJson() => {
        'description': description,
        'date': date,
      };
}

class ZWorld {
  final String id;
  final String name;
  final List<Location> locations;
  final List<Character> characters;
  final List<Relationship> relationships;
  final List<WorldEvent> events;

  const ZWorld({
    required this.id,
    required this.name,
    required this.locations,
    required this.characters,
    required this.relationships,
    required this.events,
  });

  factory ZWorld.fromJson(Map<String, dynamic> json) => ZWorld(
        id: json['id'] as String,
        name: json['name'] as String,
        locations: (json['locations'] as List<dynamic>)
            .map((l) => Location.fromJson(l as Map<String, dynamic>))
            .toList(),
        characters: (json['characters'] as List<dynamic>)
            .map((c) => Character.fromJson(c as Map<String, dynamic>))
            .toList(),
        relationships: (json['relationships'] as List<dynamic>)
            .map((r) => Relationship.fromJson(r as Map<String, dynamic>))
            .toList(),
        events: (json['events'] as List<dynamic>)
            .map((e) => WorldEvent.fromJson(e as Map<String, dynamic>))
            .toList(),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'locations': locations.map((l) => l.toJson()).toList(),
        'characters': characters.map((c) => c.toJson()).toList(),
        'relationships': relationships.map((r) => r.toJson()).toList(),
        'events': events.map((e) => e.toJson()).toList(),
      };
}

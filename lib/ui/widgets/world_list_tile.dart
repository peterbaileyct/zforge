import 'package:flutter/material.dart';
import '../../models/zworld.dart';

/// A single row in the world list on [HomeScreen].
///
/// Implemented in: lib/ui/widgets/world_list_tile.dart
class WorldListTile extends StatelessWidget {
  final ZWorld world;
  final VoidCallback? onDelete;
  final VoidCallback? onTap;
  final bool selected;

  const WorldListTile({
    super.key,
    required this.world,
    this.onDelete,
    this.onTap,
    this.selected = false,
  });

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: const Icon(Icons.public),
      title: Text(world.name),
      subtitle: Text(
        '${world.characters.length} character(s) · '
        '${world.locations.length} location(s) · '
        '${world.events.length} event(s)',
      ),
      selected: selected,
      onTap: onTap,
      trailing: onDelete != null
          ? IconButton(
              icon: const Icon(Icons.delete_outline),
              tooltip: 'Delete world',
              onPressed: () async {
                final confirm = await showDialog<bool>(
                  context: context,
                  builder: (ctx) => AlertDialog(
                    title: const Text('Delete World'),
                    content: Text(
                        'Delete "${world.name}"? This cannot be undone.'),
                    actions: [
                      TextButton(
                          onPressed: () => Navigator.pop(ctx, false),
                          child: const Text('Cancel')),
                      FilledButton(
                          onPressed: () => Navigator.pop(ctx, true),
                          child: const Text('Delete')),
                    ],
                  ),
                );
                if (confirm == true) onDelete?.call();
              },
            )
          : null,
    );
  }
}

# File watcher behavior

## Decision: externally deleted items disappear from the tree

After a successful rebuild following an external item-file deletion, the deleted item is removed from
the item tree and is not kept as a “missing” placeholder. If it was selected, the editor clears that
item when it reloads. This describes the intended application result, not a guarantee of watcher-level
rebuild or rebuild-error recovery.

The filesystem and rebuilt Doorstop tree are the source of truth. Keeping a deleted item visible
would leave a stale object that could be edited or saved back to disk, implicitly recreating the
file. A missing-item state would also require distinct UI and save behavior that is not part of the
current tree model.

This decision covers the resulting UI state after a successful rebuild. Rebuild-error recovery and
transient delete/move sequences at the application boundary are not verified here.

## Event delivery

The watcher coalesces events within a 100 ms quiet period. It delivers each distinct content-change
filename (`True`); if the batch contains any structural event, it delivers one structural refresh
(`False`, empty filename), which takes precedence over content-only reloads in that batch. This avoids
using a potentially stale basename for a mixed batch. The watcher skips roots that are already missing
when watches are scheduled and tolerates a root disappearing during scheduling. It does not itself
guarantee that a deleted root is rediscovered or that a failed application rebuild is retried. Stopping
cancels pending delivery; `start()` creates a fresh Watchdog observer after a stop, so restart is safe.

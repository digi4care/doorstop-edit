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

The watcher coalesces events within a 100 ms quiet period and delivers one callback per batch:
`(modified_only, paths, generation)`. `paths` contains the distinct absolute paths seen in the batch.
If any event is structural, `modified_only` is false and the application performs one structural
refresh; otherwise all changed item paths are reloaded together. A monotonically increasing generation
lets the application reject callbacks queued for an earlier watch period. The watcher skips roots that
are already missing when watches are scheduled and tolerates a root disappearing during scheduling. It
does not itself guarantee that a deleted root is rediscovered or that a failed application rebuild is
retried. Stopping cancels pending delivery and waits for active callbacks; restarting creates a fresh
platform-appropriate Watchdog observer and restores the scheduled document roots.

## Platform observer

Windows uses Watchdog’s polling observer with a configured 100 ms interval; other
platforms retain their native observer. Polling compares filesystem snapshots rather
than receiving native notifications, so it adds periodic filesystem I/O proportional
to the watched tree. Detection latency includes the polling interval, snapshot scan
time, event debounce, and application processing; 100 ms is not a hard end-to-end
limit. The interval is selected to target the documented sub-second refresh behavior.
Observer replacement on restart uses the same platform-specific selection.

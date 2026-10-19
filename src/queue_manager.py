import time
from collections import defaultdict


class QueueManager:
    """Track confirmed queue membership and count confirmed transitions.

    A person is counted as entering only after remaining in a queue ROI for
    confirmation_seconds. A confirmed person is counted as exiting only after
    remaining outside all queue ROIs for exit_confirmation_seconds, or after
    being missing longer than lost_track_timeout.

    Counts depend on the stability of YOLO/ByteTrack IDs and are estimates,
    not guaranteed unique-person counts.
    """

    def __init__(
        self,
        queue_names,
        confirmation_seconds=2.5,
        exit_confirmation_seconds=1.5,
        lost_track_timeout=5.0,
    ):
        self.queue_names = list(queue_names)
        self.confirmation_seconds = float(confirmation_seconds)
        self.exit_confirmation_seconds = float(exit_confirmation_seconds)
        self.lost_track_timeout = float(lost_track_timeout)

        # Only confirmed queue memberships appear here.
        self.current_queue = {}       # track_id -> queue name
        self.entry_time = {}          # track_id -> monotonic time
        self.last_seen = {}           # track_id -> monotonic time
        self.pending_transition = {}  # track_id -> (candidate queue or None, since)

        self.entries = defaultdict(int)
        self.exits = defaultdict(int)

    def update(self, track_id, detected_queue, now=None):
        """Update one tracked person once per frame.

        detected_queue is a queue name if the person's foot point is in a
        queue polygon, otherwise None. Brief ROI-boundary flicker is debounced.
        """
        if now is None:
            now = time.monotonic()
        if track_id is None:
            return
        if detected_queue is not None and detected_queue not in self.queue_names:
            return

        self.last_seen[track_id] = now
        confirmed_queue = self.current_queue.get(track_id)

        # Same as confirmed assignment: cancel any temporary candidate.
        if detected_queue == confirmed_queue:
            self.pending_transition.pop(track_id, None)
            return

        pending = self.pending_transition.get(track_id)
        if pending is None or pending[0] != detected_queue:
            self.pending_transition[track_id] = (detected_queue, now)
            return

        candidate_queue, candidate_since = pending
        required_time = (
            self.exit_confirmation_seconds
            if candidate_queue is None
            else self.confirmation_seconds
        )
        if now - candidate_since < required_time:
            return

        # The new state persisted long enough: commit one transition.
        if confirmed_queue is not None:
            self.exits[confirmed_queue] += 1
            self.current_queue.pop(track_id, None)
            self.entry_time.pop(track_id, None)

        if candidate_queue is not None:
            self.current_queue[track_id] = candidate_queue
            self.entry_time[track_id] = now
            self.entries[candidate_queue] += 1

        self.pending_transition.pop(track_id, None)

    def cleanup(self, visible_track_ids, now=None):
        """Clean up IDs missing beyond lost_track_timeout.

        visible_track_ids must include all tracked people in the frame, even
        people outside the queue ROIs.
        """
        if now is None:
            now = time.monotonic()
        visible_track_ids = set(visible_track_ids)

        for track_id in list(self.last_seen):
            if track_id in visible_track_ids:
                continue
            if now - self.last_seen[track_id] <= self.lost_track_timeout:
                continue

            old_queue = self.current_queue.pop(track_id, None)
            if old_queue is not None:
                self.exits[old_queue] += 1

            self.entry_time.pop(track_id, None)
            self.last_seen.pop(track_id, None)
            self.pending_transition.pop(track_id, None)

    def get_statistics(self, now=None):
        """Return the existing dashboard/database statistics structure."""
        if now is None:
            now = time.monotonic()

        stats = {}
        for queue_name in self.queue_names:
            waiting_times = [
                now - self.entry_time[track_id]
                for track_id, assigned_queue in self.current_queue.items()
                if assigned_queue == queue_name and track_id in self.entry_time
            ]
            occupancy = sum(
                1 for assigned_queue in self.current_queue.values()
                if assigned_queue == queue_name
            )
            stats[queue_name] = {
                "occupancy": occupancy,
                "entries": self.entries[queue_name],
                "exits": self.exits[queue_name],
                "average_wait_seconds": (
                    sum(waiting_times) / len(waiting_times) if waiting_times else 0.0
                ),
            }
        return stats

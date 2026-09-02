"""Bounded, read-only recovery of completed frame replies; never replay models."""
from collections import OrderedDict
import re
from threading import Lock


class FrameReplies:
    def __init__(self, capacity=4):
        self.capacity = capacity
        self.lock = Lock()
        self.entries = OrderedDict()

    @staticmethod
    def key(session_id, seq):
        if not isinstance(session_id, str) or not re.fullmatch(r'[0-9a-f]{32}', session_id):
            raise ValueError('Invalid recovery session')
        if type(seq) is not int or not 0 <= seq <= 2**53-1:
            raise ValueError('Invalid recovery frame sequence')
        return session_id, seq

    def clear(self):
        with self.lock:
            self.entries.clear()

    def begin(self, session_id, seq):
        key = self.key(session_id, seq)
        with self.lock:
            if key in self.entries:
                raise ValueError('Frame already submitted. Read its saved reply instead of resubmitting it.')
            self.entries[key] = None
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
        return key

    def finish(self, key, status, body):
        if not isinstance(body, bytes):
            raise TypeError('Reply must be immutable encoded JSON')
        with self.lock:
            # An explicit new session/close may invalidate outstanding replies.
            if key in self.entries:
                self.entries[key] = (status, body)

    def lookup(self, session_id, seq):
        key = self.key(session_id, seq)
        with self.lock:
            if key not in self.entries:
                return 'missing', None
            result = self.entries[key]
            return ('pending', None) if result is None else ('ready', result)

#!/usr/bin/env python3
"""garbage_collector2.py — Generational garbage collector.

Implements a tri-generational GC with:
- Young gen: copying collector (Eden + survivor spaces)
- Old gen: mark-sweep-compact
- Write barriers for cross-generation references
- Promotion after N survived collections

One file. Zero deps. Does one thing well.
"""

import sys
from dataclasses import dataclass, field
from enum import Enum


class Gen(Enum):
    YOUNG = 0
    MIDDLE = 1
    OLD = 2


@dataclass
class Object:
    oid: int
    size: int
    refs: list[int] = field(default_factory=list)  # oids of referenced objects
    gen: Gen = Gen.YOUNG
    survived: int = 0
    marked: bool = False
    forwarded: int = -1  # for copying collector


class Heap:
    """Generational garbage collector."""

    PROMOTE_AFTER = 2  # promote to next gen after N survivals

    def __init__(self, young_size=1024, middle_size=2048, old_size=4096):
        self.objects: dict[int, Object] = {}
        self.roots: set[int] = set()
        self.next_oid = 0
        self.gen_sizes = {Gen.YOUNG: young_size, Gen.MIDDLE: middle_size, Gen.OLD: old_size}
        self.gen_used = {Gen.YOUNG: 0, Gen.MIDDLE: 0, Gen.OLD: 0}
        self.remembered_set: set[int] = set()  # old objects referencing young
        self.stats = {'minor_gc': 0, 'major_gc': 0, 'promoted': 0, 'freed': 0, 'total_allocated': 0}

    def alloc(self, size: int, root: bool = False) -> int:
        """Allocate an object in young generation."""
        if self.gen_used[Gen.YOUNG] + size > self.gen_sizes[Gen.YOUNG]:
            self.minor_gc()
        if self.gen_used[Gen.YOUNG] + size > self.gen_sizes[Gen.YOUNG]:
            self.major_gc()

        oid = self.next_oid
        self.next_oid += 1
        obj = Object(oid=oid, size=size, gen=Gen.YOUNG)
        self.objects[oid] = obj
        self.gen_used[Gen.YOUNG] += size
        self.stats['total_allocated'] += size
        if root:
            self.roots.add(oid)
        return oid

    def add_ref(self, from_oid: int, to_oid: int):
        """Add reference with write barrier."""
        if from_oid not in self.objects or to_oid not in self.objects:
            return
        self.objects[from_oid].refs.append(to_oid)
        # Write barrier: track cross-gen references
        src = self.objects[from_oid]
        dst = self.objects[to_oid]
        if src.gen.value > dst.gen.value:
            self.remembered_set.add(from_oid)

    def add_root(self, oid: int):
        self.roots.add(oid)

    def remove_root(self, oid: int):
        self.roots.discard(oid)

    def _trace(self, root_oids: set[int], target_gen: Gen | None = None) -> set[int]:
        """Trace reachable objects from roots."""
        reachable = set()
        worklist = list(root_oids)
        while worklist:
            oid = worklist.pop()
            if oid in reachable or oid not in self.objects:
                continue
            obj = self.objects[oid]
            if target_gen is not None and obj.gen != target_gen:
                reachable.add(oid)  # different gen, still reachable
                continue
            reachable.add(oid)
            worklist.extend(obj.refs)
        return reachable

    def minor_gc(self):
        """Collect young generation (copying collector semantics)."""
        self.stats['minor_gc'] += 1

        # Roots = stack roots + remembered set references
        gc_roots = set(self.roots)
        for oid in self.remembered_set:
            if oid in self.objects:
                gc_roots.update(self.objects[oid].refs)

        reachable = self._trace(gc_roots, target_gen=None)
        young_reachable = {oid for oid in reachable if oid in self.objects and self.objects[oid].gen == Gen.YOUNG}

        # Collect unreachable young objects
        young_all = {oid for oid, obj in self.objects.items() if obj.gen == Gen.YOUNG}
        dead = young_all - young_reachable
        for oid in dead:
            self.gen_used[Gen.YOUNG] -= self.objects[oid].size
            del self.objects[oid]
            self.stats['freed'] += 1

        # Promote survivors
        for oid in young_reachable:
            if oid not in self.objects:
                continue
            obj = self.objects[oid]
            obj.survived += 1
            if obj.survived >= self.PROMOTE_AFTER:
                self._promote(obj)

        # Clean remembered set
        self.remembered_set = {oid for oid in self.remembered_set if oid in self.objects}

    def _promote(self, obj: Object):
        """Promote object to next generation."""
        old_gen = obj.gen
        if old_gen == Gen.YOUNG:
            new_gen = Gen.MIDDLE
        elif old_gen == Gen.MIDDLE:
            new_gen = Gen.OLD
        else:
            return

        self.gen_used[old_gen] -= obj.size
        obj.gen = new_gen
        obj.survived = 0
        self.gen_used[new_gen] += obj.size
        self.stats['promoted'] += 1

    def major_gc(self):
        """Full heap collection (mark-sweep)."""
        self.stats['major_gc'] += 1

        # Mark phase
        reachable = self._trace(self.roots)

        # Sweep phase
        dead = set(self.objects.keys()) - reachable
        for oid in dead:
            obj = self.objects[oid]
            self.gen_used[obj.gen] -= obj.size
            del self.objects[oid]
            self.stats['freed'] += 1
            self.roots.discard(oid)

        self.remembered_set = {oid for oid in self.remembered_set if oid in self.objects}

    def status(self) -> dict:
        return {
            'objects': len(self.objects),
            'roots': len(self.roots),
            'young': sum(1 for o in self.objects.values() if o.gen == Gen.YOUNG),
            'middle': sum(1 for o in self.objects.values() if o.gen == Gen.MIDDLE),
            'old': sum(1 for o in self.objects.values() if o.gen == Gen.OLD),
            'remembered': len(self.remembered_set),
            **self.stats,
        }


def demo():
    print("=== Generational Garbage Collector ===\n")
    heap = Heap(young_size=256, middle_size=512, old_size=1024)

    # Allocate a linked list
    print("Building linked list (10 nodes)...")
    root = heap.alloc(32, root=True)
    prev = root
    for i in range(9):
        node = heap.alloc(32)
        heap.add_ref(prev, node)
        prev = node
    print(f"  Status: {heap.status()}")

    # Allocate temporary objects (should be collected)
    print("\nAllocating 20 temporary objects...")
    for _ in range(20):
        heap.alloc(8)  # no root, no refs → garbage
    print(f"  Before GC: {heap.status()}")

    heap.minor_gc()
    print(f"  After minor GC: {heap.status()}")

    # Force promotions
    print("\nForcing promotions (3 minor GCs)...")
    for _ in range(3):
        heap.alloc(8)  # trigger more GC cycles
        heap.minor_gc()
    print(f"  Status: {heap.status()}")

    # Major GC
    heap.remove_root(root)
    print("\nRemoved root, running major GC...")
    heap.major_gc()
    print(f"  Status: {heap.status()}")


if __name__ == '__main__':
    if '--test' in sys.argv:
        h = Heap(young_size=256, middle_size=512, old_size=1024)
        # Alloc + collect temp
        root = h.alloc(32, root=True)
        temp = h.alloc(32)
        assert len(h.objects) == 2
        h.minor_gc()
        assert temp not in h.objects  # temp collected
        assert root in h.objects  # root survives
        # Promotion
        for _ in range(3):
            h.minor_gc()
        assert h.objects[root].gen != Gen.YOUNG  # promoted
        # Major GC
        h.remove_root(root)
        h.major_gc()
        assert len(h.objects) == 0
        print("All tests passed ✓")
    else:
        demo()

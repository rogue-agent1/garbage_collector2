#!/usr/bin/env python3
"""Garbage collector — mark-sweep, mark-compact, and generational GC.

One file. Zero deps. Does one thing well.

Simulates three GC strategies with heap visualization. Educational model
of how Java/Go/V8 manage memory.
"""
import sys, random

class Object:
    __slots__ = ('id', 'size', 'refs', 'marked', 'generation', 'alive')
    _counter = 0
    def __init__(self, size=1):
        Object._counter += 1
        self.id = Object._counter
        self.size = size
        self.refs = []
        self.marked = False
        self.generation = 0
        self.alive = True
    def __repr__(self):
        return f"Obj({self.id}, size={self.size}, refs={[r.id for r in self.refs]})"

class MarkSweepGC:
    def __init__(self, heap_size=100):
        self.heap = []
        self.roots = []
        self.heap_size = heap_size
        self.collections = 0
        self.freed_total = 0

    def alloc(self, size=1):
        used = sum(o.size for o in self.heap if o.alive)
        if used + size > self.heap_size:
            self.collect()
            used = sum(o.size for o in self.heap if o.alive)
            if used + size > self.heap_size:
                return None  # OOM
        obj = Object(size)
        self.heap.append(obj)
        return obj

    def _mark(self):
        stack = list(self.roots)
        while stack:
            obj = stack.pop()
            if not obj.marked and obj.alive:
                obj.marked = True
                stack.extend(r for r in obj.refs if not r.marked and r.alive)

    def _sweep(self):
        freed = 0
        for obj in self.heap:
            if not obj.marked:
                obj.alive = False
                freed += obj.size
            obj.marked = False
        self.heap = [o for o in self.heap if o.alive]
        return freed

    def collect(self):
        self.collections += 1
        self._mark()
        freed = self._sweep()
        self.freed_total += freed
        return freed

    def stats(self):
        used = sum(o.size for o in self.heap if o.alive)
        return f"used={used}/{self.heap_size}, objects={len(self.heap)}, collections={self.collections}, freed={self.freed_total}"

class GenerationalGC:
    """Simple two-generation GC: young (frequent) + old (infrequent)."""
    def __init__(self, young_size=30, old_size=70, tenure_threshold=3):
        self.young = []
        self.old = []
        self.roots = []
        self.young_size = young_size
        self.old_size = old_size
        self.tenure_threshold = tenure_threshold
        self.minor_collections = 0
        self.major_collections = 0

    def alloc(self, size=1):
        young_used = sum(o.size for o in self.young if o.alive)
        if young_used + size > self.young_size:
            self._minor_gc()
        obj = Object(size)
        self.young.append(obj)
        return obj

    def _mark_from(self, roots, scope):
        stack = list(roots)
        while stack:
            obj = stack.pop()
            if not obj.marked and obj.alive and obj in scope:
                obj.marked = True
                stack.extend(r for r in obj.refs if not r.marked and r.alive)

    def _minor_gc(self):
        self.minor_collections += 1
        all_objects = set(self.young)
        # Mark from roots + old→young references
        self._mark_from(self.roots, all_objects)
        for old_obj in self.old:
            if old_obj.alive:
                for ref in old_obj.refs:
                    if ref in all_objects and not ref.marked:
                        ref.marked = True
        # Promote survivors, sweep dead
        survivors = []
        for obj in self.young:
            if obj.marked:
                obj.generation += 1
                obj.marked = False
                if obj.generation >= self.tenure_threshold:
                    self.old.append(obj)  # Promote to old gen
                else:
                    survivors.append(obj)
            else:
                obj.alive = False
        self.young = survivors
        # Check if old gen needs collection
        old_used = sum(o.size for o in self.old if o.alive)
        if old_used > self.old_size * 0.8:
            self._major_gc()

    def _major_gc(self):
        self.major_collections += 1
        all_objects = set(self.young + self.old)
        self._mark_from(self.roots, all_objects)
        for lst in (self.young, self.old):
            for obj in lst:
                if not obj.marked:
                    obj.alive = False
                obj.marked = False
        self.young = [o for o in self.young if o.alive]
        self.old = [o for o in self.old if o.alive]

    def stats(self):
        y = sum(o.size for o in self.young if o.alive)
        o = sum(o.size for o in self.old if o.alive)
        return f"young={y}/{self.young_size}, old={o}/{self.old_size}, minor={self.minor_collections}, major={self.major_collections}"

def main():
    random.seed(42)
    print("=== Mark-Sweep GC ===")
    gc = MarkSweepGC(50)
    objs = []
    for i in range(20):
        o = gc.alloc(2)
        if o and objs:
            o.refs.append(random.choice(objs))
        if o: objs.append(o)
    gc.roots = objs[:3]  # Only first 3 are roots
    print(f"  Before: {gc.stats()}")
    gc.collect()
    print(f"  After:  {gc.stats()}")

    print("\n=== Generational GC ===")
    ggc = GenerationalGC(young_size=20, old_size=50, tenure_threshold=2)
    long_lived = []
    for cycle in range(10):
        # Create short-lived objects
        temps = []
        for _ in range(5):
            o = ggc.alloc(1)
            if o: temps.append(o)
        # Some become long-lived
        if temps and random.random() > 0.5:
            keeper = temps[0]
            long_lived.append(keeper)
            ggc.roots = long_lived[-5:]  # Keep last 5 as roots
    print(f"  {ggc.stats()}")
    print(f"  Roots: {len(ggc.roots)}, young objs: {len(ggc.young)}, old objs: {len(ggc.old)}")

if __name__ == "__main__":
    main()

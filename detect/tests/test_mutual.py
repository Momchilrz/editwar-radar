from datetime import timedelta

from detect.mutual import PairGraph
from detect.tests.fixtures import T0


def test_one_direction_is_not_a_mutual_war() -> None:
    graph = PairGraph()
    graph.add("Alice", "Bob", T0)
    graph.add("Alice", "Bob", T0 + timedelta(minutes=1))
    assert graph.mutual_pairs() == []
    assert len(graph) == 2
    assert graph.directed_counts()[0].count == 2


def test_both_directions_are_a_mutual_pair() -> None:
    graph = PairGraph()
    graph.add("Alice", "Bob", T0)
    graph.add("Bob", "Alice", T0 + timedelta(minutes=2))
    assert graph.mutual_pairs() == [("Alice", "Bob")]


def test_pair_expires_outside_the_callers_cutoff() -> None:
    graph = PairGraph()
    graph.add("Alice", "Bob", T0)
    graph.add("Bob", "Alice", T0 + timedelta(hours=1))
    graph.expire(T0 + timedelta(seconds=1))
    assert graph.mutual_pairs() == []
    assert len(graph) == 1


def test_self_edge_is_ignored() -> None:
    graph = PairGraph()
    graph.add("Alice", "Alice", T0)
    graph.add("Alice", " alice ", T0)
    assert graph.mutual_pairs() == []
    assert len(graph) == 0

from dmb.matchers.base import Candidates, Matcher
from dmb.matchers.dummy import DummyMatcher
from dmb.matchers.rules import RulesMatcher

MATCHERS: dict[str, type[Matcher]] = {m.name: m for m in (DummyMatcher, RulesMatcher)}


def get_matcher(name: str) -> Matcher:
    try:
        return MATCHERS[name]()
    except KeyError:
        raise ValueError(f"Unknown matcher {name!r}. Available: {sorted(MATCHERS)}") from None


__all__ = ["MATCHERS", "Candidates", "Matcher", "get_matcher"]

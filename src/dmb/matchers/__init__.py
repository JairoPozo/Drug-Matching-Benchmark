from dmb.matchers.base import Candidates, Matcher
from dmb.matchers.dummy import DummyMatcher
from dmb.matchers.rules import RulesMatcher
from dmb.matchers.rxnav import RxNavMatcher, SapBERTMatcher

MATCHERS: dict[str, type[Matcher]] = {
    m.name: m for m in (DummyMatcher, RulesMatcher, RxNavMatcher, SapBERTMatcher)
}


def get_matcher(name: str, **params) -> Matcher:
    if name not in MATCHERS:
        raise ValueError(f"Unknown matcher {name!r}. Available: {sorted(MATCHERS)}")
    try:
        return MATCHERS[name](**params)
    except TypeError as exc:
        raise ValueError(f"Bad parameters for matcher {name!r}: {exc}") from None


__all__ = ["MATCHERS", "Candidates", "Matcher", "get_matcher"]

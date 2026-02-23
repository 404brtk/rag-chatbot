from dataclasses import dataclass, field


@dataclass
class _RuleGroup:
    user_agents: list[str] = field(
        default_factory=list
    )  # default_factory is used to create a new list for each instance
    # without it, all instances would share the same list, because lists are mutable objects in Python
    allow: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)
    crawl_delay: float | None = None

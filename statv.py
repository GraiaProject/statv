from __future__ import annotations

import asyncio
import inspect
from collections import deque
from typing import TYPE_CHECKING, Any, Callable, Generic, Protocol, TypeVar, overload

if TYPE_CHECKING:
    from typing_extensions import Self

T = TypeVar("T")

Statv_T = TypeVar("Statv_T", bound="Statv", contravariant=True)


class StatsValidator(Protocol[T]):
    def __call__(self, stats: Stats[T], past: T, current: T) -> T:
        ...


class UpdateMonitor(Protocol[Statv_T, T]):
    def __call__(self, statv: Statv_T, stats: Stats[T], past: T, current: T) -> Any:
        ...


class Stats(Generic[T]):
    id: str

    default: T | ellipsis = ...
    default_factory: Callable[[], T] | None = None

    _validator: StatsValidator[T] | None

    def __init__(
        self,
        id: str,
        *,
        default: T = ...,
        default_factory: Callable[[], T] | None = None,
        validator: StatsValidator[T] | None = None,
    ) -> None:
        self.id = id
        self.default = default
        self.default_factory = default_factory
        self._validator = validator

    @overload
    def __get__(self, instance: None, owner: None) -> Stats:
        ...

    @overload
    def __get__(self, instance: Statv, owner: type[Statv]) -> T:
        ...

    def __get__(self, instance: Statv | None, owner: type[Statv] | None = None) -> T | Stats:
        if instance is None:
            return self

        if self.id not in instance._stats:
            raise AttributeError(f"{self.id} is not defined or not initialized")

        return instance._stats[self.id]

    def __set__(self, instance: Statv, value: T) -> None:
        past_value: T = instance._stats[self.id]
        if self._validator:
            value = self._validator(self, past_value, value)
        if past_value != value:
            for monitor in instance._monitors.get(self.id, []):
                monitor(instance, self, past_value, value)
        instance._stats[self.id] = value

        for ftr in instance._waiters:
            if not ftr.done() and not ftr.cancelled():
                ftr.set_result(instance)

    def validator(self, validator: StatsValidator[T]):
        if self._validator:
            raise RuntimeError(f"{self.id} already has a validator")
        self._validator = validator
        return validator


def stats(id: str, *, default: Any = ..., default_factory: Callable[[], Any] | None = None) -> Stats[Any]:
    return Stats(id, default=default, default_factory=default_factory)


class Statv:
    _waiters: deque[asyncio.Future]
    _stats: dict[str, Any]
    _monitors: dict[str, list[UpdateMonitor[Self, Any]]]

    def __init__(self, *, init_stats: dict[str, Any] | None = None):
        self._waiters = deque()
        self._stats = {}
        self._monitors = {}

        for stat_define in self.defined_stats():
            if stat_define.default is not ...:
                self._stats[stat_define.id] = stat_define.default
            elif stat_define.default_factory is not None:
                self._stats[stat_define.id] = stat_define.default_factory()
            elif init_stats is not None and stat_define.id in init_stats:
                self._stats[stat_define.id] = init_stats[stat_define.id]
            else:
                raise ValueError(f"{stat_define.id} is required but not initialized")

    @classmethod
    def defined_stats(cls) -> list[Stats]:
        return [v for _, v in inspect.getmembers(cls, lambda x: isinstance(x, Stats))]

    def on_update(self, stats: Stats[T]) -> Callable[[UpdateMonitor[Self, T]], UpdateMonitor[Self, T]]:
        def inner(func: UpdateMonitor[Self, T]) -> UpdateMonitor[Self, T]:
            self._monitors.setdefault(stats.id, []).append(func)
            return func

        return inner

    @property
    def available(self) -> bool:
        return True

    def update_multi(self, mapping: dict[Stats[T], T]) -> None:
        stats = self.defined_stats()
        if not all(isinstance(k, Stats) and k in stats for k in mapping):
            raise TypeError(f"invalid ownership of Stats definition for {self.__class__.__name__}")

        for stat, value in mapping.items():
            past_value: T = self._stats[stat.id]
            if stat._validator:
                value = stat._validator(stat, past_value, value)
            if past_value != value:
                for monitor in self._monitors.get(stat.id, []):
                    monitor(self, stat, past_value, value)
            self._stats[stat.id] = value

        for ftr in self._waiters:
            if not ftr.done() and not ftr.cancelled():
                ftr.set_result(self)

    async def wait_for_update(self: Self) -> tuple[Self, Self]:
        waiter = asyncio.Future()
        self._waiters.append(waiter)
        try:
            return await waiter
        finally:
            self._waiters.remove(waiter)

    async def wait_for_available(self):
        while not self.available:
            await self.wait_for_update()

    async def wait_for_unavailable(self):
        while self.available:
            await self.wait_for_update()

import asyncio
from asyncio import AbstractEventLoop

import pytest

from statv import Stats, Statv, stats


def test_field():
    assert stats("stat.id").__dict__ == Stats("stat.id").__dict__


def test_define_extract():
    val_stat = stats("val", default=False)
    value_stat = stats("value", default_factory=lambda: 0)

    class AStat(Statv):
        val: Stats[bool] = val_stat
        value: Stats[int] = value_stat

    assert AStat.defined_stats() == [val_stat, value_stat]


def test_unknown_field():
    class FactoryStat(Statv):
        val: Stats[bool] = stats("val", default_factory=lambda: False)

    with pytest.raises(AttributeError):
        stats("$").__get__(FactoryStat(), FactoryStat)


def test_default_value():
    class FactoryStat(Statv):
        val: Stats[bool] = stats("val", default_factory=lambda: False)

    assert FactoryStat().available


def test_init_req():
    class DefaultStat(Statv):
        val: Stats[bool] = stats("val", default=False)

    assert DefaultStat().val == False

    class FactoryStat(Statv):
        val: Stats[bool] = stats("val", default_factory=lambda: False)

    assert FactoryStat().val == False

    class UnknownStat(Statv):
        val: Stats[int] = stats("val")

    assert UnknownStat(init_stats={"val": 0}).val == 0
    assert UnknownStat(init_stats={"val": 5}).val == 5
    with pytest.raises(ValueError):
        UnknownStat()


def test_basic_set():
    class DefaultStat(Statv):
        val: Stats[bool] = stats("val", default=False)

    d = DefaultStat()
    assert d.val is False
    d.val = True
    assert d.val
    d.val = False
    assert not d.val


@pytest.mark.asyncio
async def test_basic_async(event_loop: AbstractEventLoop):
    class DefaultStat(Statv):
        val: Stats[bool] = stats("val", default=False)

        @property
        def available(self) -> bool:
            return self.val

    d = DefaultStat()
    t = event_loop.create_task(d.wait_for_available())
    assert d.val is False
    t_d, t_p = await asyncio.wait({t}, timeout=0.01)
    assert t_p
    assert not t_d
    d.val = True
    d.val = False
    d.val = True
    assert d.val
    t_d, t_p = await asyncio.wait({t}, timeout=0.01)
    assert t_d
    assert not t_p
    assert t.done()
    assert d.val
    t = event_loop.create_task(d.wait_for_unavailable())
    t_d, t_p = await asyncio.wait({t}, timeout=0.01)
    assert t_p
    assert not t_d
    d.val = False
    assert not d.val
    t_d, t_p = await asyncio.wait({t}, timeout=0.01)
    assert t_d
    assert not t_p


def test_validator():
    class DefaultStat(Statv):
        val: Stats[int] = stats("val", default=0)

    @DefaultStat.val.validator
    def _(stats, past, current):
        return min(max(current, 0), 5)

    with pytest.raises(RuntimeError):

        @DefaultStat.val.validator
        @staticmethod
        def _(stats, past, current):
            return current <= 4

    d = DefaultStat()

    assert d.val == 0
    d.val = 5
    assert d.val == 5
    d.val = 7
    assert d.val == 5
    d.val = -1
    assert d.val == 0


@pytest.mark.asyncio
async def test_multi_basic(event_loop: AbstractEventLoop):
    class DefaultStat(Statv):
        val: Stats[bool] = stats("val", default=False)
        v: Stats[int] = stats("v", default=0)

        @property
        def available(self) -> bool:
            return self.val

    d = DefaultStat()
    t = event_loop.create_task(d.wait_for_available())
    d.update_multi({DefaultStat.v: 7})
    assert d.v == 7
    t_d, t_p = await asyncio.wait({t}, timeout=0.01)
    assert t_p
    assert not t_d
    d.update_multi({DefaultStat.val: False, DefaultStat.v: 2})
    assert not d.val
    assert d.v == 2
    d.update_multi({DefaultStat.val: True, DefaultStat.v: 7})
    assert d.val
    t_d, t_p = await asyncio.wait({t}, timeout=0.01)
    assert t_d
    assert not t_p
    assert t.done()
    assert d.val
    assert d.v == 7
    t = event_loop.create_task(d.wait_for_unavailable())
    t_d, t_p = await asyncio.wait({t}, timeout=0.01)
    assert t_p
    assert not t_d
    d.update_multi({DefaultStat.val: False, DefaultStat.v: 2})
    assert not d.val
    assert d.v == 2
    t_d, t_p = await asyncio.wait({t}, timeout=0.01)
    assert t_d
    assert not t_p


@pytest.mark.asyncio
async def test_multi_validate():
    class DStat(Statv):
        val: Stats[bool] = stats("val", default=False)
        v: Stats[int] = stats("v", default=0)

        @property
        def available(self) -> bool:
            return self.val

    @DStat.v.validator
    def _(stats, past, current):
        return min(max(current, 0), 5)

    q = DStat()
    q.update_multi({DStat.val: True, DStat.v: 7})
    assert q.val == True
    assert q.v == 5
    q.update_multi({DStat.val: False, DStat.v: -1})
    assert q.val == False
    assert q.v == 0


def test_multi_err():
    class DStat(Statv):
        val: Stats[bool] = stats("val", default=False)
        v: Stats[int] = stats("v", default=0)

    q = DStat()
    with pytest.raises(TypeError):
        q.update_multi({stats("val"): True})


@pytest.mark.asyncio
async def test_monitor(event_loop: AbstractEventLoop):
    trigger = []

    class IStat(Statv):
        v: Stats[int] = stats("v", default=0)

    i = IStat()

    @i.on_update(IStat.v)
    def _(statv, stats, past, current):
        assert statv is i
        assert stats is IStat.v
        assert past != current
        trigger.append(0)

    i.update_multi({IStat.v: 7})
    assert i.v == 7
    assert len(trigger) == 1
    i.v = 7
    assert len(trigger) == 1
    i.v = 8
    assert len(trigger) == 2

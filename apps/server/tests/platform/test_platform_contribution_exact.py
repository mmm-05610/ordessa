"""A selected publication is held without choosing among other owners."""
from __future__ import annotations

from threading import Event, Thread

import pytest
from server_plugin_api import AbsentContribution, ContributionAccessError, ContributionOwnerBusyError

from contribution_fakes import ContribPlugin, RecordingHandler, contribution, new_host
from ordessa_server.plugin_host import ResolvedContribution


POINT = "test.multi.exact"


def composed():
    host = new_host()
    host.register_contribution_point(POINT, "v1", handler=RecordingHandler(), exclusive=False)
    plugins = [ContribPlugin(owner, contributions=(contribution(POINT, payload={"owner": owner}),))
               for owner in ("fake.first", "fake.second")]
    host.activate_all(plugins)
    return host, plugins


def test_exact_selection_holds_only_the_selected_live_publication():
    host, _ = composed()
    first, second = host.contributions(POINT)
    assert isinstance(host.contribution(POINT), AbsentContribution)
    with host.use_contribution_exact(POINT, owner=second.owner,
                                     publication_token=second.publication_token) as held:
        assert isinstance(held, ResolvedContribution) and held == second
        assert host.owner_busy(second.owner) and not host.owner_busy(first.owner)
        with pytest.raises(ContributionOwnerBusyError):
            host.deactivate(second.owner)
        host.deactivate(first.owner)
        assert held.payload == {"owner": second.owner}
    host.deactivate(second.owner)


def test_exact_selection_fails_closed_for_wrong_identity_and_aba():
    host, plugins = composed()
    first, second = host.contributions(POINT)
    for point, owner, token in ((POINT, first.owner, second.publication_token),
                                (POINT, second.owner, first.publication_token),
                                ("test.other", first.owner, first.publication_token),
                                (POINT, "fake.absent", first.publication_token),
                                (POINT, first.owner, "")):
        with host.use_contribution_exact(point, owner=owner, publication_token=token) as view:
            assert isinstance(view, AbsentContribution)
        assert not host.owner_busy(first.owner) and not host.owner_busy(second.owner)
    host.deactivate(first.owner)
    host.activate(plugins[0])  # even the same payload is a new publication
    with host.use_contribution_exact(POINT, owner=first.owner,
                                     publication_token=first.publication_token) as stale:
        assert isinstance(stale, AbsentContribution)
    current = next(view for view in host.contributions(POINT) if view.owner == first.owner)
    assert current.publication_token != first.publication_token
    with host.use_contribution_exact(POINT, owner=first.owner,
                                     publication_token=current.publication_token) as held:
        assert held == current


def test_exact_selection_preserves_consumer_grant():
    host, _ = composed()
    host.activate(ContribPlugin("fake.child", requires=("fake.first",)))
    first, second = host.contributions(POINT)
    with host.use_contribution_exact(POINT, owner=first.owner,
                                     publication_token=first.publication_token,
                                     consumer="fake.child") as held:
        assert held == first
    with pytest.raises(ContributionAccessError):
        with host.use_contribution_exact(POINT, owner=second.owner,
                                         publication_token=second.publication_token,
                                         consumer="fake.child"):
            pass


def test_exact_selection_blocks_concurrent_unload_until_release():
    host, _ = composed()
    first = host.contributions(POINT)[0]
    entered = Event()
    release = Event()
    outcome: list[object] = []

    def reader():
        with host.use_contribution_exact(POINT, owner=first.owner,
                                         publication_token=first.publication_token) as held:
            outcome.append(held)
            entered.set()
            assert release.wait(3)

    thread = Thread(target=reader)
    thread.start()
    try:
        assert entered.wait(3)
        with pytest.raises(ContributionOwnerBusyError):
            host.deactivate(first.owner)
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert outcome == [first]
    host.deactivate(first.owner)


def test_exact_selection_and_acquire_are_atomic_against_unload(monkeypatch):
    host, _ = composed()
    selected = host.contributions(POINT)[0]
    selected_but_not_acquired = Event()
    continue_acquire = Event()
    held = Event()
    release = Event()
    unload_done = Event()
    unload_results: list[object] = []
    original = host.contribution_exact

    def paused_selection(*args, **kwargs):
        view = original(*args, **kwargs)
        selected_but_not_acquired.set()
        assert continue_acquire.wait(3)
        return view

    monkeypatch.setattr(host, "contribution_exact", paused_selection)

    def reader():
        with host.use_contribution_exact(POINT, owner=selected.owner,
                                         publication_token=selected.publication_token):
            held.set()
            assert release.wait(3)

    def unloader():
        try:
            host.deactivate(selected.owner)
            unload_results.append("unloaded")
        except ContributionOwnerBusyError as exc:
            unload_results.append(exc)
        finally:
            unload_done.set()

    reader_thread = Thread(target=reader)
    unload_thread = Thread(target=unloader)
    reader_thread.start()
    try:
        assert selected_but_not_acquired.wait(3)
        unload_thread.start()
        assert not unload_done.wait(0.05)
        continue_acquire.set()
        assert held.wait(3)
        assert unload_done.wait(3)
        assert isinstance(unload_results[0], ContributionOwnerBusyError)
    finally:
        continue_acquire.set()
        release.set()
        reader_thread.join(3)
        if unload_thread.ident is not None:
            unload_thread.join(3)
    assert not reader_thread.is_alive() and not unload_thread.is_alive()
    host.deactivate(selected.owner)


def test_rollback_callback_can_wait_for_another_thread_to_read_host():
    host = new_host()
    reader_done = Event()
    reader_threads: list[Thread] = []

    class ReadingRollback(RecordingHandler):
        def rollback(self, item, prepared, owner):
            def reader():
                assert host.contributions(POINT) == ()
                reader_done.set()

            thread = Thread(target=reader)
            reader_threads.append(thread)
            thread.start()
            assert reader_done.wait(1), "rollback retained the host lifecycle lock"
            super().rollback(item, prepared, owner)

    host.register_contribution_point(POINT, "v1", handler=ReadingRollback())
    host.activate(ContribPlugin("fake.owner", contributions=(contribution(POINT),)))
    host.deactivate("fake.owner")
    for thread in reader_threads:
        thread.join(1)
        assert not thread.is_alive()
    assert reader_done.is_set()


def test_disposal_callback_can_read_host_and_same_owner_cannot_reactivate():
    host = new_host()
    in_disposal = Event()
    release_disposal = Event()
    owner = ContribPlugin("fake.owner", contributions=(contribution(POINT),))

    def disposal():
        in_disposal.set()
        assert release_disposal.wait(2)

    class WithDisposal:
        def descriptor(self):
            return owner.descriptor()

        def build(self, context):
            registration = owner.build(context)
            from server_plugin_api import ServerPluginRegistration
            return ServerPluginRegistration(contributions=registration.contributions,
                                            disposal=disposal)

    host.register_contribution_point(POINT, "v1", handler=RecordingHandler())
    plugin = WithDisposal()
    host.activate(plugin)
    finished = Event()
    errors: list[BaseException] = []

    def unload():
        try:
            host.deactivate("fake.owner")
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    thread = Thread(target=unload)
    thread.start()
    try:
        assert in_disposal.wait(2)
        assert host.contributions(POINT) == ()
        with pytest.raises(Exception, match="retir|cleanup|active"):
            host.activate(plugin)
    finally:
        release_disposal.set()
        thread.join(2)
    assert finished.is_set() and not errors
    host.activate(plugin)
    release_disposal.set()
    host.deactivate("fake.owner")

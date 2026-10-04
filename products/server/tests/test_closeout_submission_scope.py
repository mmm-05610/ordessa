"""Cold journal scope is read-only and independent of current native binding."""
from ordessa_server_product.composition import create_composition


def test_authenticated_scope_survives_restart_without_native_binding(tmp_path):
    first = create_composition().default_runtime(tmp_path / 'data')
    try:
        first.start()
        before = first.wire.dispatch('agent.submission.scope', {})
        assert before == {'namespace': first.core_binding.environment.environment_id,
                          'principalScope': 'local'}
    finally:
        first.stop()
    second = create_composition().default_runtime(tmp_path / 'data')
    try:
        second.start()
        assert second.wire.dispatch('agent.submission.scope', {}) == before
        agent = next(plugin for plugin in second.plugin_selection if plugin.descriptor().id == 'ordessa.agent')
        assert agent._repository.connection.execute('SELECT COUNT(*) FROM agent_observed_records').fetchone()[0] == 0
    finally:
        second.stop()

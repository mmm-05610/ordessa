"""Product-approved credential source selection; no real credentials read."""
import pytest
from ordessa_environments import EnvironmentRefused
from ordessa_server.composition.temporary_process_capability import ExistingOpenCodeInput
from ordessa_server.composition import temporary_process_capability as source_module


def test_unapproved_source_refuses():
    with pytest.raises(EnvironmentRefused):
        ExistingOpenCodeInput('/unrelated/credential')


@pytest.mark.parametrize('separator', ['=', ':'])
def test_named_inputs_are_selected_independently_without_positional_fallback(tmp_path, monkeypatch, separator):
    source = tmp_path / '.env'
    source.write_text('unselected-historical-value\n'
        f'DEEPSEEK_API_KEY{separator}controlled-deepseek-value\n'
        f'OPENCODE_GO_API_KEY{separator}controlled-go-value\n')
    monkeypatch.setattr(source_module, 'APPROVED_OPENCODE_SOURCES', frozenset({str(source)}))
    official = ExistingOpenCodeInput(source, variable_name='DEEPSEEK_API_KEY')
    backup = ExistingOpenCodeInput(source, variable_name='OPENCODE_GO_API_KEY')
    assert official.read() == bytearray(b'controlled-deepseek-value')
    assert backup.read() == bytearray(b'controlled-go-value')
    assert 'controlled-deepseek-value' not in repr(official)
    assert 'controlled-go-value' not in repr(backup)
    with pytest.raises(EnvironmentRefused):
        ExistingOpenCodeInput(source).read()


@pytest.mark.parametrize('body', ['only-unnamed-value',
    'OPENCODE_GO_API_KEY=controlled-go-value',
    'DEEPSEEK_API_KEY=first\nDEEPSEEK_API_KEY:second'])
def test_missing_or_ambiguous_named_input_refuses_without_another_key(tmp_path, monkeypatch, body):
    source = tmp_path / '.env'
    source.write_text(body)
    monkeypatch.setattr(source_module, 'APPROVED_OPENCODE_SOURCES', frozenset({str(source)}))
    with pytest.raises(EnvironmentRefused):
        ExistingOpenCodeInput(source, variable_name='DEEPSEEK_API_KEY').read()

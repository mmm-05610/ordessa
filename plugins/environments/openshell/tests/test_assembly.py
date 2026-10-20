"""Assembly inputs: bounded configuration, endpoint form, proxy bypass, absence."""
import json
import os

import pytest

from ordessa_environments import EnvironmentRefused
from ordessa_environments_openshell import assembly


def test_missing_configuration_is_absence_not_error(tmp_path):
    assert assembly.read_configuration(tmp_path / 'openshell.json') == {}


def test_configuration_rejections_are_bounded(tmp_path):
    path = tmp_path / 'openshell.json'
    path.write_text('{not json')
    with pytest.raises(EnvironmentRefused):
        assembly.read_configuration(path)
    path.write_text('[]')
    with pytest.raises(EnvironmentRefused):
        assembly.read_configuration(path)
    path.write_text('{"a":' + '1' * 70000 + '}')
    with pytest.raises(EnvironmentRefused):
        assembly.read_configuration(path)


def test_endpoint_must_be_host_port_without_scheme():
    assert assembly._endpoint_host('127.0.0.1:17670') == '127.0.0.1'
    assert assembly._endpoint_host('[::1]:17670') == '::1'
    for bad in ('https://127.0.0.1:17670', '127.0.0.1', '127.0.0.1:notaport',
                ':17670', '127.0.0.1:0', 'host:70000'):
        with pytest.raises(EnvironmentRefused):
            assembly._endpoint_host(bad)


def test_loopback_removes_ambient_proxy_and_remote_keeps_it(monkeypatch):
    for name in ('http_proxy', 'HTTPS_PROXY', 'all_proxy', 'grpc_proxy'):
        monkeypatch.setenv(name, 'http://127.0.0.1:7897')
    assembly._bypass_ambient_proxy('127.0.0.1:17670')
    for name in ('http_proxy', 'HTTPS_PROXY', 'all_proxy', 'grpc_proxy'):
        assert name not in os.environ
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:7897')
    assembly._bypass_ambient_proxy('gateway.example.com:17670')
    assert os.environ['http_proxy'] == 'http://127.0.0.1:7897'


def test_validate_rejects_unknown_fields_and_bad_values():
    good = {'endpoint': '127.0.0.1:17670', 'workspace': 'w', 'fileRoot': '/sandbox',
            'fileHelper': 'python3', 'timeoutSeconds': 30, 'gatewayName': 'openshell'}
    assembly._validate(good)
    for key, value in (('endpoint', 'https://x:1'), ('fileRoot', '/sandbox/../etc'),
                       ('fileRoot', 'relative'), ('timeoutSeconds', 0),
                       ('timeoutSeconds', 9999), ('workspace', ''), ('fileHelper', 7)):
        payload = dict(good, **{key: value})
        with pytest.raises(EnvironmentRefused):
            assembly._validate(payload)
    with pytest.raises(EnvironmentRefused):
        assembly._validate(dict(good, unexpected=True))


def test_explicit_mtls_paths_must_be_complete_and_exist(tmp_path):
    with pytest.raises(EnvironmentRefused):
        assembly._mtls_paths({'caPath': str(tmp_path / 'ca.crt')}, 'openshell')
    with pytest.raises(EnvironmentRefused):
        assembly._mtls_paths({'caPath': str(tmp_path / 'ca.crt'),
                              'certPath': str(tmp_path / 'tls.crt'),
                              'keyPath': str(tmp_path / 'tls.key')}, 'openshell')


def test_unconfigured_build_is_an_explicit_refusal():
    with pytest.raises(EnvironmentRefused):
        assembly.build_binding({})

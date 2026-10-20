"""The real selected product binds one exact host assembly/storage authority."""
import pytest

from ordessa_server_product.composition import ServerProductComposition, ProductCompositionUnavailable


def test_selected_product_accepts_same_ports_and_refuses_foreign_factory():
    calls = []
    def registrar():
        calls.append("selected")
    def assembler(*_args, **_kwargs):
        raise AssertionError("binding must not execute runtime assembly")
    class Database:
        pass
    class ForeignDatabase(Database):
        pass

    composition = ServerProductComposition()
    with pytest.raises(ProductCompositionUnavailable, match="explicit host"):
        composition.database_type()
    composition.bind_host_execution_ports(migration_registrar=registrar,
        runtime_assembler=assembler, database_factory=Database)
    composition.bind_host_execution_ports(migration_registrar=registrar,
        runtime_assembler=assembler, database_factory=Database)
    with pytest.raises(ProductCompositionUnavailable, match="different composition"):
        composition.bind_host_execution_ports(migration_registrar=lambda: None,
            runtime_assembler=assembler, database_factory=Database)
    with pytest.raises(ProductCompositionUnavailable, match="different composition"):
        composition.bind_host_execution_ports(migration_registrar=registrar,
            runtime_assembler=lambda *_args: None, database_factory=Database)
    with pytest.raises(ProductCompositionUnavailable, match="different composition"):
        composition.bind_host_execution_ports(migration_registrar=registrar,
            runtime_assembler=assembler, database_factory=ForeignDatabase)
    assert composition.database_type() is Database
    assert calls == ["selected"]

"""Actual original Agent binding reads; no launch, send, role self-sign or model."""
from pathlib import Path
import importlib.util
from types import SimpleNamespace
from dataclasses import replace
import pytest
from ordessa_engineering.adapters.native_records.agent_execution import AgentExecutionConsumer
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.usecases.reviews.assignments import ReviewerAssignmentUseCases
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_infrastructure.encoding import canonical_bytes


def test_actual_agent_identity_read_requires_independently_authorized_original_lookup(tmp_path):
    path=Path(__file__).resolve().parents[3]/'execution/agents/tests/sdk/interaction_fixtures.py'
    spec=importlib.util.spec_from_file_location('original_reviewer_interaction_fixture',path)
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    source,authority,sender,reader=fixture.original_service(tmp_path/'agent.sqlite')
    library=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='reviewer-read',schema_version=17)
    try:
        factory=SQLiteUoWFactory(library);blobs=SQLiteBlobStore(library)
        consumer=AgentExecutionConsumer(source,blobs)
        methods=SimpleNamespace(factory=factory,guard=lambda *args:None)
        access=SimpleNamespace(require=lambda *args:None,guard_current_capability=lambda *args:None)
        selected=[reader];queries=[]
        def query(ctx,ref,plan,request,*,purpose):
            queries.append((ref,purpose));return selected[0]
        class AuthorResolver:
            def __init__(self):
                self.factory,self.access,self.records=factory,access,consumer
                self.override=None
            def __call__(self,context,ref,plan,request):
                return ref if self.override is None else self.override
        author_resolver=AuthorResolver()
        usecase=ReviewerAssignmentUseCases(factory,methods,consumer,expected_access=access,
            expected_scope=Scope('realm','project'),agent_query_factory=query,
            author_identity_resolver=author_resolver)
        ref=fixture.INSTANCE.projection();before=source.records._db.total_changes
        before_operations=source.records._db.execute("SELECT * FROM operations ORDER BY request_id,operation").fetchall()
        assert usecase._resolve_agent(None,ref,None,None,'reviewer')==canonical_bytes(ref)
        assert usecase._resolve_agent(None,ref,None,None,'author')==canonical_bytes(ref)
        assert [p for _,p in queries]==['reviewer','author']
        author_resolver.override=replace(fixture.INSTANCE,instance_id='foreign-author').projection()
        with pytest.raises(ApplicationError,match='AGENT_REVIEW_AUTHOR_BINDING_UNAVAILABLE'):
            usecase._resolve_agent(None,ref,None,None,'author')
        assert len(queries)==2
        author_resolver.override=None
        # Same caller attributes or a captured ref are insufficient authority.
        selected[0]=SimpleNamespace(subject=reader.subject,read=True,send=False)
        with pytest.raises(ApplicationError,match='AGENT_REVIEW_AUTHORITY_UNAVAILABLE'):
            usecase._resolve_agent(None,ref,None,None,'reviewer')
        selected[0]=None
        with pytest.raises(ApplicationError,match='AGENT_REVIEW_AUTHORITY_UNAVAILABLE'):
            usecase._resolve_agent(None,ref,None,None,'reviewer')
        selected[0]=reader
        changed=replace(fixture.INSTANCE,binding_digest='sha256:'+'c'*64).projection()
        with pytest.raises(ApplicationError,match='AGENT_REVIEW_AUTHORITY_UNAVAILABLE'):
            usecase._resolve_agent(None,changed,None,None,'reviewer')
        authority.denied.add('read')
        with pytest.raises(ApplicationError,match='AGENT_REVIEW_AUTHORITY_UNAVAILABLE'):
            usecase._resolve_agent(None,ref,None,None,'reviewer')
        assert source.records._db.total_changes==before
        assert source.records._db.execute('SELECT * FROM operations ORDER BY request_id,operation').fetchall()==before_operations
        assert source.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()==(0,)
        assert library._connection.execute('SELECT count(*) FROM eng_unit_reviewer_assignments').fetchone()==(0,)
    finally:
        library.close();source.records.close()

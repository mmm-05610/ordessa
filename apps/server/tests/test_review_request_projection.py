"""Authenticated projection of original pending request; fixture plan only."""
from pathlib import Path
from dataclasses import asdict
import runpy
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.domain.common.models.identity import Scope as DomainScope
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server.composition.product_runtime import build_product_runtime
import importlib.util
_slice=Path(__file__).with_name("test_engineering_slice.py")
_spec=importlib.util.spec_from_file_location("pending_projection_http_helper",_slice)
_helper=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_helper)
call=_helper.call
ROOT=Path(__file__).resolve().parents[3]


def test_read_original_pending_plan_and_refuse_foreign_scope(tmp_path):
    scope=Scope('pending-realm','pending-project');domain=DomainScope(scope.realm_id,scope.project_id)
    path=tmp_path/'pending.sqlite';library=EngineeringLibrary.create(path.resolve(),library_id='pending-fixture',schema_version=10)
    factory=SQLiteUoWFactory(library)
    helpers=runpy.run_path(str(ROOT/'packages/engineering/tests/application/test_review_usecases.py'))
    plan=helpers['_plan'](domain,helpers['_create_source'](factory,domain),'pending-review')
    with factory.begin(domain) as uow:
        uow.reviews.create_plan(plan);uow.commit()
    library.close()
    runtime=build_product_runtime(tmp_path/'server',library_path=path,library_id='pending-fixture',scope=scope,
        machine_capabilities=('engineering.capabilities','engineering.reviews.get_request'))
    runtime.start()
    try:
        value=call(runtime,'engineering.reviews.get_request',{'review_id':'pending-review'},scope=scope)['result']
        assert value['record_type']=='ReviewRequest'
        assert value['data']['request']['state']=='requested'
        assert value['data']['request']['version']==0 and value['data']['request']['fence']==1
        assert value['data']['plan']['review_id']=='pending-review'
        assert value['data']['plan']['check_keys']==[asdict(key) for key in plan.check_keys]
        assert 'approved' not in value['data'] and 'grant' not in value['data']
        assert call(runtime,'engineering.reviews.get_request',{'review_id':'pending-review'},scope=Scope('foreign',scope.project_id))['error']['code']=='FORBIDDEN'
    finally:runtime.stop()

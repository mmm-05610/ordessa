"""Native owner schema keeps all constraints; no assertion of apply support."""
import pytest
from assignment_source.composition import check_schema

SCHEMA={'type':'object','properties':{'model':{'type':'string','minLength':1,'maxLength':256},
    'model_reasoning_effort':{'enum':['none','low','medium','high']}},
    'additionalProperties':False,'minProperties':1}

@pytest.mark.parametrize('value,expected',[
    ({'model':'does-not-prove-model-exists'},'valid'),
    ({},'invalid'),({'model':''},'invalid'),({'model':'x'*257},'invalid'),
    ({'model_reasoning_effort':'high'},'valid'),({'model_reasoning_effort':'invented'},'invalid'),
    ({'model_reasoning_effort':True},'invalid'),({'extra':'x'},'invalid')])
def test_T62_original_owner_schema_constraints(value,expected):
    assert check_schema(value,SCHEMA)==expected

@pytest.mark.parametrize('schema',[
    {'type':'string','minLength':True},{'type':'object','maxProperties':-1},
    {'enum':['x'],'pattern':'x'}, {'type':'string','maxLength':'1'}])
def test_T62_unsupported_or_malformed_length_enum_declarations(schema):
    assert check_schema('x',schema)=='unverifiable'


def test_T62_unicode_codepoint_length_and_json_enum_types():
    assert check_schema('中文',{'type':'string','minLength':2,'maxLength':2})=='valid'
    assert check_schema(True,{'enum':[1]})=='invalid'
    assert check_schema(1.0,{'enum':[1]})=='valid'

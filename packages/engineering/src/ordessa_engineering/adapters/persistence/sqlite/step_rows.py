"""Read original material receipts and schema13 native rows without translation."""
from dataclasses import asdict
import json

from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_engineering.domain.artifacts.library_material_codec import material_ref_from_dict
from ordessa_engineering.application.contracts.errors import ApplicationError


def read_step_rows(connection,run_id):
    schema=connection.execute('SELECT schema_version FROM library_meta WHERE singleton=1').fetchone()[0]
    extra=(',dispatch_scope_json,binding_digest,binding_bytes,execution_operation_ref,dispatch_phase,'
           'dispatch_version,dispatch_fence,result_blob_json' if schema>=13 else '')
    rows=connection.execute('SELECT ordinal,step_id,operation,attempt,status,receipt_ref_json'+extra+
        ' FROM step_log WHERE run_id=? ORDER BY ordinal',(run_id,)).fetchall()
    result=[]
    for row in rows:
        value={'ordinal':row[0],'step_id':row[1],'operation':row[2],'attempt':row[3],'status':row[4]}
        if schema>=13 and row[7] is not None:
            from .dispatch_repository import SQLiteDispatchRepository
            try:
                scope=Scope(**json.loads(row[6]))
                dispatch=SQLiteDispatchRepository._row((row[0],row[2],row[4],row[5],*row[6:]),
                    scope,run_id,row[1],row[3])
                binding=decode_dispatch(dispatch['binding_bytes'])
                if (binding.scope!=scope or binding.run_id!=run_id or binding.step_id!=row[1]
                        or binding.attempt!=row[3] or binding.fence!=dispatch['dispatch_fence']
                        or binding.execution_operation_ref!=dispatch['execution_operation_ref']):
                    raise ApplicationError('DISPATCH_RECORD_CORRUPT')
            except (ValueError,TypeError,KeyError) as exc:
                raise ApplicationError('DISPATCH_RECORD_CORRUPT') from exc
            value.update(receipt_ref=None,dispatch={'binding_digest':asdict(binding.digest),
                'execution_operation_ref':binding.execution_operation_ref,'phase':dispatch['dispatch_phase'],
                'version':dispatch['dispatch_version'],'fence':dispatch['dispatch_fence'],
                'result_blob_ref':None if dispatch['result_blob_json'] is None else json.loads(dispatch['result_blob_json'])})
        else:
            value['receipt_ref']=material_ref_from_dict(json.loads(row[5]))
        result.append(value)
    return result

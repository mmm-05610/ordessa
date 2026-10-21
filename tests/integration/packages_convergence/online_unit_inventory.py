"""Bounded current-tree source/declaration inventory, not runtime reachability proof.

Git read-only enumeration includes nonignored untracked source. Never imports
product code, opens user data, visits another worktree or installs anything.
"""
from pathlib import Path
import ast,hashlib,json,re,subprocess,datetime

TOPS={'packages','plugins','apps','products','tooling','scripts','packaging'}
EXCLUDE={'tests','test','fixtures','examples','node_modules','dist','build','__pycache__',
    '.git','.evidence','evidence','vendor'}
SOURCE={'.py','.ts','.tsx','.js','.jsx','.mjs','.cjs','.sh','.ps1','.spec','.nix'}
DECLARATIONS={'.json','.toml','.yaml','.yml','.lock','.cfg','.ini'}
META={'Dockerfile','requirements.txt','pyproject.toml','package.json','package-lock.json','python-workspace.json'}
RULES={
    'units_distribution_or_module':r'\bordessa_units(?:\.[A-Za-z_][\w]*)*\b|\bordessa-units\b',
    'retired_agent_records_import':r'\bordessa_agents\.harness\.(?:records|transport)(?:\.[A-Za-z_][\w]*)*\b',
    'unit_owner_or_alias':r'\b(?:UnitRecords|UnitManager|UnitServices|UnitRuntimeProvider|AgentUnitRef|UnitRef|unit_services|agent_services|AgentServices|AgentOwnerPorts|InvocationIssuer|composed_profile_service|resolve_unit_reference|authorize_acp_turn_query|OperationJournal)\b',
    'unit_identity':r'\b(?:unit_ref|unit_ref_bytes|unitRef|unit_id|unitId|reviewer_unit_ref|author_unit_ref|ownerProviderRef)\b',
    'retired_kernel_dependency':r'\bpacthold(?:\.[A-Za-z_][\w]*)*\b|\bpacthold-runtime-compat\b',
}
PATTERNS={k:re.compile(v) for k,v in RULES.items()}
HISTORY_FUNCTIONS={'read_historical_dispatch','read_historical_execution_observation'}
HISTORY_CLASSES={'ExecutionRecordRef','HistoricalExecutionObservationRef','HistoricalReviewerAssignment','HistoricalNativeEvidenceReader'}


def classify(path,kind,context,symbol):
    if path.startswith('packages/execution/units/'):
        return 'retired_units_source_present'
    if any(name in context.split('.') for name in HISTORY_FUNCTIONS|HISTORY_CLASSES):
        return 'explicit_history_boundary_needs_review'
    if kind in {'comment','docstring'}:return 'text_only'
    if path.endswith(('reviewer_assignment_schema.py','dispatch_schema.py','submission_schema.py')):
        return 'persisted_schema_identifier_needs_review'
    if path.startswith(('tooling/','scripts/','packaging/')) or 'decision-tooling/' in path:
        return 'explicit_tool_or_assembly_candidate'
    if kind=='metadata':return 'distribution_or_assembly_candidate'
    return 'production_execution_or_contract_candidate'


def inventory(root):
    raw=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root)
    candidates=sorted(set(p.decode() for p in raw.split(b'\0') if p))
    findings=[];files={};excluded=[];failures=[];edges=[]
    for name in candidates:
        p=Path(name)
        if p.name not in META and (not p.parts or p.parts[0] not in TOPS):continue
        if any(part in EXCLUDE or part.endswith('.egg-info') for part in p.parts):
            excluded.append(name);continue
        metadata=p.name in META or p.suffix in DECLARATIONS or p.name.startswith('requirements') and p.suffix=='.txt'
        if not metadata and p.suffix not in SOURCE:continue
        full=root/p
        if not full.exists():continue
        if full.is_symlink():excluded.append(name);continue
        data=full.read_bytes()
        if len(data)>8*1024*1024:failures.append({'path':name,'reason':'source exceeds8MiB bound'});continue
        try:text=data.decode('utf-8')
        except UnicodeDecodeError:failures.append({'path':name,'reason':'not UTF8'});continue
        files[name]=hashlib.sha256(data).hexdigest()
        def add(value,line,kind,context=''):
            for family,pattern in PATTERNS.items():
                for match in pattern.finditer(value):
                    symbol=match.group()
                    findings.append({'path':name,'line':line,'kind':kind,'context':context,
                        'family':family,'symbol':symbol,'category':classify(name,kind,context,symbol)})
        if p.suffix=='.py':
            try:tree=ast.parse(text)
            except SyntaxError as exc:failures.append({'path':name,'reason':'parse','line':exc.lineno});continue
            def walk(node,context=()):
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):context=context+(node.name,)
                ctx='.'.join(context)
                if isinstance(node,ast.Import):
                    for item in node.names:add(item.name,node.lineno,'import',ctx);edges.append({'path':name,'line':node.lineno,'module':item.name,'names':[]})
                elif isinstance(node,ast.ImportFrom):
                    module='.'*node.level+(node.module or '')
                    add(module,node.lineno,'import',ctx)
                    edges.append({'path':name,'line':node.lineno,'module':module,'names':[a.name for a in node.names]})
                    for item in node.names:add(item.name,node.lineno,'imported_symbol',ctx)
                elif isinstance(node,ast.Name):add(node.id,node.lineno,'identifier',ctx)
                elif isinstance(node,ast.Attribute):add(node.attr,node.lineno,'attribute',ctx)
                elif isinstance(node,ast.arg):add(node.arg,node.lineno,'parameter',ctx)
                elif isinstance(node,ast.Constant) and type(node.value) is str:
                    kind='literal'
                    if isinstance(getattr(node,'parent',None),ast.Expr):kind='docstring'
                    add(node.value,node.lineno,kind,ctx)
                for child in ast.iter_child_nodes(node):
                    child.parent=node;walk(child,context)
            walk(tree)
        else:
            for line,value in enumerate(text.splitlines(),1):add(value,line,'metadata' if metadata else 'lexical_source')
    # Prove missing public imports against the ACTUAL current Agent public list.
    tree=ast.parse((root/'packages/execution/agents/src/ordessa_agents/public.py').read_text())
    exports=set(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__all__' for t in n.targets)))
    invalid=[{**e,'missing':[n for n in e['names'] if n!='*' and n not in exports]} for e in edges if e['module']=='ordessa_agents.public']
    invalid=[e for e in invalid if e['missing']]
    from collections import Counter
    actionable=[f for f in findings if f['category'] in {'production_execution_or_contract_candidate','distribution_or_assembly_candidate','explicit_tool_or_assembly_candidate'}]
    return {'schema':'ordessa-whole-production-unit-inventory/1','timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope':'All nonignored tracked/untracked production source + JSON/TOML/YAML/lock/cfg/ini/release declarations in current tree; tests/docs/evidence/vendor/build/user-data excluded before read. Not runtime reachability or installed closure proof.',
        'excludedPaths':excluded,'failures':failures,'files':files,'findings':findings,'invalidCurrentAgentPublicImports':invalid,
        'counts':{'files':len(files),'findings':len(findings),'candidateFiles':len(set(f['path'] for f in actionable)),
            'categories':dict(Counter(f['category'] for f in findings)),'invalidPublicImports':len(invalid),'failures':len(failures)},
        'unitRetirementReady':False}


if __name__=='__main__':
    root=Path(__file__).resolve().parents[3]
    output=root/'docs/implementation/packages-convergence-20261019/evidence/whole-production-unit-inventory.json'
    result=inventory(root);output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['counts']))

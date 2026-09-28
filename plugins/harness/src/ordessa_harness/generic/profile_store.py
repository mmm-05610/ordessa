"""The only official Harness profile authority."""
from __future__ import annotations
import hashlib, json, os, re
from pathlib import Path
from typing import Any, Callable
from pacthold_runtime_compat.api import ProfileEnvelope
from pacthold.work_core import Ref, RefType, ProviderDescriptor, ResourceResolutionContext
from pacthold_runtime_compat.resource_contracts import AgentBoxProfileV1

PROVIDER_ID = "harness-profile"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_SECRET = re.compile(r"(secret|token|api[_-]?key|password|private[_-]?key|authorization|cookie|credential_value|host_path)", re.I)
def _safe(value, size=65536):
    raw=json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=False)
    if len(raw.encode()) > size: raise ValueError("PROFILE_TOO_LARGE")
    if isinstance(value, dict):
        if len(value)>128: raise ValueError("FIELD_LIMIT_EXCEEDED")
        for k,v in value.items():
            if not isinstance(k,str) or len(k)>96 or _SECRET.search(k): raise ValueError("SECRET_FIELD_FORBIDDEN")
            _safe(v,size)
    elif isinstance(value,list):
        if len(value)>128: raise ValueError("FIELD_LIMIT_EXCEEDED")
        for v in value: _safe(v,size)
    elif isinstance(value,str) and len(value)>8192: raise ValueError("FIELD_TOO_LARGE")
    return value
def _digest(payload):
    body={k:v for k,v in payload.items() if k not in {"digest","revision"}}
    return "sha256:"+hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

class ProfileStore:
    provider_id=PROVIDER_ID; supported_contract_ids=frozenset({AgentBoxProfileV1.contract_id})
    def __init__(self, root: Path, *, validator: Callable[[str, Any], None] | None=None):
        self.root=Path(root).resolve(); self.validator=validator
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    def descriptor(self): return ProviderDescriptor(self.provider_id,"Harness Profile Store","2.0")
    def _dir(self,h,p):
        if not _ID.fullmatch(str(h)) or not _ID.fullmatch(str(p)): raise ValueError("INVALID_PROFILE_ID")
        d=(self.root/str(h)/str(p)).resolve()
        if d.parent.parent != self.root: raise ValueError("PROFILE_PATH_ESCAPE")
        return d
    def _read(self,h,p,r):
        path=self._dir(h,p)/"revisions"/str(int(r))/"envelope.json"
        if path.is_symlink(): raise ValueError("PROFILE_SYMLINK_FORBIDDEN")
        try: value=json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError: raise KeyError("PROFILE_NOT_FOUND")
        if value.get("digest") != _digest(value): raise ValueError("PROFILE_DIGEST_DRIFT")
        if value.get("harness_type")!=h or value.get("profile_id")!=p or int(value.get("revision",0))!=int(r) or value.get("provider_id")!=PROVIDER_ID: raise ValueError("PROFILE_IDENTITY_MISMATCH")
        return value
    def list(self,harness_type=None):
        roots=[self.root/harness_type] if harness_type else sorted(self.root.iterdir() if self.root.exists() else [],key=lambda x:x.name)
        result=[]
        for hroot in roots:
            if not hroot.is_dir() or hroot.is_symlink(): continue
            for p in sorted(hroot.iterdir(),key=lambda x:x.name):
                if not p.is_dir() or p.is_symlink(): continue
                revs=sorted((p/"revisions").iterdir(),key=lambda x:int(x.name)) if (p/"revisions").is_dir() else []
                if revs: result.append(self._read(hroot.name,p.name,revs[-1].name))
        return tuple(result)
    def get(self,harness_type,profile_id,revision=None):
        if revision is None:
            rows=self.list(harness_type); matches=[x for x in rows if x["profile_id"]==profile_id]
            if not matches: raise KeyError("PROFILE_NOT_FOUND")
            revision=matches[0]["revision"]
        return self._read(harness_type,profile_id,revision)
    def put(self,harness_type,data,expected_revision=None):
        if not _ID.fullmatch(str(harness_type)): raise ValueError("INVALID_HARNESS_TYPE")
        if not isinstance(data,dict): raise TypeError("profile must be an object")
        pid=str(data.get("profile_id") or data.get("name") or "").strip()
        if not _ID.fullmatch(pid): raise ValueError("INVALID_PROFILE_ID")
        native=data.get("native_payload",data.get("config",{})); _safe(native)
        if self.validator: self.validator(harness_type,native)
        try: current=self.get(harness_type,pid)
        except KeyError: current=None
        actual=int(current["revision"]) if current else 0
        if expected_revision is not None and actual != int(expected_revision): raise ValueError("REVISION_CONFLICT")
        payload={"profile_id":pid,"harness_type":harness_type,"provider_id":PROVIDER_ID,"name":str(data.get("name") or pid)[:128],"schema_version":1,"revision":actual+1,"disabled":bool(data.get("disabled",False)),"credential_source_ref":data.get("credential_source_ref"),"capability_refs":data.get("capability_refs",[]),"session_overlay_policy":data.get("session_overlay_policy",{"mode":"execution-local"}),"import_provenance":data.get("import_provenance"),"native_payload":native}
        _safe(payload["credential_source_ref"]); payload["digest"]=_digest(payload)
        target=self._dir(harness_type,pid)/"revisions"/str(payload["revision"]); target.mkdir(mode=0o700,parents=True,exist_ok=False)
        tmp=target/"envelope.json.tmp"; final=target/"envelope.json"; tmp.write_text(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n",encoding="utf-8"); os.chmod(tmp,0o600); os.replace(tmp,final)
        return payload
    def ref(self,harness_type,profile_id,revision=None):
        v=self.get(harness_type,profile_id,revision); return Ref(RefType.ARTIFACT,PROVIDER_ID,profile_id,metadata={"harness_type":harness_type,"revision":str(v["revision"]),"digest":v["digest"]})
    def resolve(self,contract_id,ref,*,context: ResourceResolutionContext|None=None):
        del context
        if contract_id!=AgentBoxProfileV1.contract_id or ref.provider!=PROVIDER_ID or ref.type is not RefType.ARTIFACT: raise ValueError("PROFILE_REF_MISMATCH")
        h=ref.metadata.get("harness_type",""); value=self._read(h,ref.native_id,int(ref.metadata.get("revision","0")))
        if value["digest"]!=ref.metadata.get("digest"): raise ValueError("PROFILE_DIGEST_DRIFT")
        if value["disabled"]: raise ValueError("PROFILE_DISABLED")
        return AgentBoxProfileV1(value["name"],h,value["digest"],value["revision"],PROVIDER_ID)

"""Pure stored-source reconstruction and exact program binding coordination."""
from pathlib import Path
from ...methods.definitions.models import LoadedMethod, MethodSource, SourceBundle
from ...methods.definitions.errors import MethodError, MethodFailure
from ...methods.loading.captured import rebuild_source_bundle
from ...methods.compilation.compiler import compile_program_from_source
from ...methods.compilation.encoding import program_to_canonical

def verify_stored_snapshot_source(snapshot, bundle: SourceBundle, *, historical_reconstructor=None) -> LoadedMethod:
    parsed = rebuild_source_bundle(bundle)
    loaded = LoadedMethod(MethodSource(Path(".")), bundle, parsed)
    version = snapshot.program.schema_version
    if version == 1:
        if historical_reconstructor is None:
            raise MethodFailure(MethodError("SNAPSHOT_PROGRAM_UNSUPPORTED", "historical source reconstruction requires its explicit adapter"))
        program = historical_reconstructor(loaded, snapshot.compiler_version)
    elif version == 2:
        program = compile_program_from_source(loaded, snapshot.compiler_version)
    else:
        raise MethodFailure(MethodError("SNAPSHOT_PROGRAM_UNSUPPORTED", "snapshot program version is unsupported"))
    if parsed.identity != snapshot.identity or program != program_to_canonical(snapshot.program):
        raise MethodFailure(MethodError("SNAPSHOT_SOURCE_MISMATCH", "captured source differs from stored snapshot program"))
    return loaded

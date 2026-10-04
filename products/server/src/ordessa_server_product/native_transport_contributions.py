"""Product declarations for its selected opaque native transport boundary."""
from dataclasses import dataclass
from pacthold.public import CoreContributionSet

@dataclass(frozen=True)
class NativeChannelStart:
    contract_id = 'native.channel-start@1'

@dataclass(frozen=True)
class NativeChannelWrite:
    contract_id = 'native.channel-write@1'

@dataclass(frozen=True)
class NativeChannelRelease:
    contract_id = 'native.channel-release@1'

def native_transport_contributions():
    return CoreContributionSet(contracts=(NativeChannelStart, NativeChannelWrite, NativeChannelRelease))

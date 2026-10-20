# Shared wire data contract

`@ordessa/interface-contracts` owns the existing WirePort, WireResult,
WireReason and AbsentWirePort shapes. Transport and channel packages consume
this public type entry. It has no runtime implementation or domain dependency.

Workbench's existing token/extension contract carrier exports these same types
while retaining its own tokens. Native ACP params, results and events do not
become another message DTO here.

export * from '../../commands/src/commands'
// Workbench public API lives in the @ordessa/workbench package (contract C4);
// foundation remains the runtime carrier that bundles the single shared copy.
export * from '../../../../workbench/api/workbench'
// Connections public API lives in the @ordessa/connections package (contract C6);
// foundation is likewise its runtime carrier for the single shared Token/kind copy.
export * from '../../../connections/api/connections'
// The browser import map sends this exact specifier to the shared C7 artifact.
// Keep the carrier external so it never constructs a second UI Token.
export * from '@ordessa/ui-components/api'
// 013 Desktop 产品化的公开插件契约（C-03 wire 口 / C-04 日志 / C-05 主题 /
// C-06 设置与诊断 / C-07 命令与快捷键 / C-08 Harness 可用性）。冻结文本在
// specs/013-desktop-product/contracts/**，这里只落 TS 类型与 DI Token 身份。
export * from './product/index'

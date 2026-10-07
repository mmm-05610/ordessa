export { runtime, scoped, OwnedResources } from './runtime'
export type { Host, RootView, Plugin } from './runtime'
export { Contributions } from '@ordessa/extension-api'
export { Shell } from './shell'
// 浏览器安全的平台服务（C-05 主题 / C-07 命令与快捷键）。主进程专用的
// 日志与诊断在 `@ordessa/extension-host/services`，不进渲染进程。
export * from './platform'

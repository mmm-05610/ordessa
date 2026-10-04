/** C08 immutable domain-type counterexamples moved with their unchanged assertions. */
import type { HarnessReport, HarnessState } from './harness-availability'
declare const report: HarnessReport
void report.state
// @ts-expect-error 可用性报告不可变。
report.state = 'available'
// @ts-expect-error 非法状态名：不得自造第四态。
const badState: HarnessState = 'ready'
void badState

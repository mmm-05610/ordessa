import { Component, type ReactNode } from 'react'
export class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <p role="alert">此内容加载失败，可关闭后重新打开。</p> : this.props.children }
}

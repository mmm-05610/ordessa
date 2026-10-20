import { beforeEach, expect, it, vi } from 'vitest'
const mock = vi.hoisted(() => ({ handlers: new Map<string, (event: unknown, value?: unknown) => void>(), options: undefined as any, bounds: {width:390,height:740}, resizable:true, pinned:false, closed:undefined as undefined | (()=>void), contents: {mainFrame:{}}, changes:0 }))
vi.mock('electron', () => ({ screen: {getPrimaryDisplay: () => ({workArea:{x:10,y:20,width:1200,height:800}})}, ipcMain: {handle: (name: string, fn: any) => mock.handlers.set(name,fn), removeHandler: (name:string) => mock.handlers.delete(name)}, BrowserWindow: class {
  webContents = mock.contents
  constructor(options:any) {mock.options=options}
  getBounds(){return mock.bounds}
  isDestroyed(){return false}
  setMinimumSize(){}
  setSize(width:number,height:number){mock.bounds={width,height};mock.changes++}
  setResizable(value:boolean){mock.resizable=value}
  setAlwaysOnTop(value:boolean){mock.pinned=value}
  once(_name:string,fn:()=>void){mock.closed=fn}
} }))
import { createStatusBoardWindow } from '../electron/windows/status-board'
beforeEach(() => {mock.handlers.clear(); mock.bounds={width:390,height:740}; mock.resizable=true; mock.pinned=false; mock.changes=0})
function event(url='ordessa://desktop/index.html'){return {sender:mock.contents,senderFrame:{...mock.contents.mainFrame,url}}}
function trustedEvent(){const frame=mock.contents.mainFrame as any; frame.url='ordessa://desktop/index.html';return {sender:mock.contents,senderFrame:frame}}
it('creates only a narrow sandboxed window with fullscreen disabled', () => {
  createStatusBoardWindow('/tmp/preload.cjs',false)
  expect(mock.options).toMatchObject({width:390,minWidth:360,maxWidth:420,frame:false,show:false,maximizable:false,fullscreenable:false,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true}})
})
it('collapses and restores height idempotently; pinning is explicit', () => {
  createStatusBoardWindow('/tmp/preload.cjs',false)
  const collapse=mock.handlers.get('status-board:collapse')!, pin=mock.handlers.get('status-board:pin')!
  collapse(trustedEvent(),true); expect(mock.bounds.height).toBe(60); expect(mock.resizable).toBe(false)
  collapse(trustedEvent(),true); expect(mock.changes).toBe(1)
  collapse(trustedEvent(),false); expect(mock.bounds.height).toBe(740); expect(mock.resizable).toBe(true)
  expect(mock.pinned).toBe(false); pin(trustedEvent(),true); expect(mock.pinned).toBe(true)
})
it('refuses forged sender/frame and malformed values and releases handlers', () => {
  createStatusBoardWindow('/tmp/preload.cjs',false)
  const pin=mock.handlers.get('status-board:pin')!
  expect(() => pin(event(),true)).toThrow('Untrusted')
  expect(() => pin({...trustedEvent(),sender:{}},true)).toThrow('Untrusted')
  expect(() => pin(trustedEvent(),'true')).toThrow('Invalid')
  mock.closed!(); expect(mock.handlers.size).toBe(0)
})

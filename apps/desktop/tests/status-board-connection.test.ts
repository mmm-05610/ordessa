import { expect, it } from 'vitest'
import { statusBoardConnection, isStatusBoardRead } from '../electron/windows/status-board-connection'
it('does not select another server implicitly', () => {expect(statusBoardConnection({},'/own')).toBeUndefined()})
it('accepts explicit loopback origin and a separate server data root', () => {expect(statusBoardConnection({ORDESSA_STATUS_BOARD_SERVER_ORIGIN:'http://127.0.0.1:1234',ORDESSA_STATUS_BOARD_SERVER_DATA_ROOT:'/selected'},'/own')).toEqual({origin:'http://127.0.0.1:1234',serverDataRoot:'/selected'})})
it.each(['http://example.com','http://127.0.0.1/x','http://user:pass@localhost:1234','http://localhost?token=secret'])('refuses origin %s', origin => {expect(()=>statusBoardConnection({ORDESSA_STATUS_BOARD_SERVER_ORIGIN:origin,ORDESSA_STATUS_BOARD_SERVER_DATA_ROOT:'/selected'},'/own')).toThrow()})
it('refuses partial config and shared data root',()=>{
 expect(()=>statusBoardConnection({ORDESSA_STATUS_BOARD_SERVER_ORIGIN:'http://localhost:1234'},'/own')).toThrow()
 expect(()=>statusBoardConnection({ORDESSA_STATUS_BOARD_SERVER_ORIGIN:'http://localhost:1234',ORDESSA_STATUS_BOARD_SERVER_DATA_ROOT:'/own'},'/own')).toThrow()
})

it.each(['engineering.work.get', 'engineering.work.current_condition', 'engineering.runs.get_wait'])('allows the published read method %s', method => { expect(isStatusBoardRead(method)).toBe(true) })
it.each(['engineering.work.start', 'engineering.work.record_command_step', 'engineering.runs.resume', 'engineering.acceptance.adopt'])('continues to deny write method %s', method => { expect(isStatusBoardRead(method)).toBe(false) })
it('keeps other published reads allowed and unrelated writes denied', () => { expect(isStatusBoardRead('engineering.artifacts.get')).toBe(true); expect(isStatusBoardRead('server.hello')).toBe(true); expect(isStatusBoardRead('engineering.artifacts.create')).toBe(false); expect(isStatusBoardRead('engineering.approvals.record_consent')).toBe(false); expect(isStatusBoardRead({})).toBe(false) })

it('accepts an explicit main-only token locator within the selected root', () => {
 expect(statusBoardConnection({ORDESSA_STATUS_BOARD_SERVER_ORIGIN:'http://localhost:1234',ORDESSA_STATUS_BOARD_SERVER_DATA_ROOT:'/selected',ORDESSA_STATUS_BOARD_TOKEN_LOCATOR:'/selected/machine-token'},'/own')?.tokenLocator).toBe('/selected/machine-token')
})
it.each(['/other/token','relative','/selected/../other/token'])('refuses token locator outside the selected root: %s', tokenLocator => {
 expect(()=>statusBoardConnection({ORDESSA_STATUS_BOARD_SERVER_ORIGIN:'http://localhost:1234',ORDESSA_STATUS_BOARD_SERVER_DATA_ROOT:'/selected',ORDESSA_STATUS_BOARD_TOKEN_LOCATOR:tokenLocator},'/own')).toThrow()
})

it('allows the explicit review read while keeping capture and dispatch writes denied',()=>{expect(isStatusBoardRead('engineering.reviews.get_request')).toBe(true);expect(isStatusBoardRead('engineering.reviews.capture_manual')).toBe(false);expect(isStatusBoardRead('engineering.implementation.start_run')).toBe(false)})

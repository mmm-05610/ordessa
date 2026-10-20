import assert from 'node:assert/strict'
import { classifyPairNetwork, credentialDestinationAllowed } from '../fixtures/pair-network-gate.mjs'

const fakeSecret = 'FAKE_BEARER_DO_NOT_RECORD'
const origin = 'http://127.0.0.1:43891'
const hash = value => [...value].reduce((n, c) => (n * 31 + c.charCodeAt(0)) % 138003713, 0)
const source = (type, id) => ({ type, id })
const base = 1700000000
const traces = {
  'electron-connect.trace.100': `${base}.000000 execve("/electron", ["electron"], 0x0) = 0\n${base}.010000 clone3({flags=CLONE_VM|CLONE_THREAD}, 88) = 101\n${base}.090000 socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 3\n${base}.100000 connect(3, {sa_family=AF_INET, sin_port=htons(43891), sin_addr=inet_addr("127.0.0.1")}, 16) = 0\n${base}.290000 socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 5\n${base}.300000 connect(5, {sa_family=AF_INET, sin_port=htons(8888), sin_addr=inet_addr("127.0.0.1")}, 16) = 0\n${base}.320000 sendto(0x5, 0x1234, 0x8, 0x0, 0x0, 0x0) = 8\n`,
  'electron-connect.trace.101': `${base}.190000 socket(AF_INET6, SOCK_DGRAM, IPPROTO_IP) = 4\n${base}.200000 connect(4, {sa_family=AF_INET6, sin6_port=htons(443), inet_pton(AF_INET6, "2001:4860:4860::8888", &sin6_addr)}, 28) = 0\n${base}.210000 getsockname(4, 0x123, 0x456) = 0\n`,
}
const constants = { timeTickOffset: 1699999999000,
  logEventTypes: { TCP_CONNECT: 7, UDP_CONNECT: 9, UDP_BYTES_SENT: 10, HOST_RESOLVER_MANAGER_IPV6_REACHABILITY_CHECK: 11, SOCKET_BYTES_SENT: 12,
    URL_REQUEST_REDIRECTED: 13 },
  logSourceType: { URL_REQUEST: 1, SOCKET: 3, UDP_SOCKET: 4 } }
const events = [
  { time: '1100', type: 7, source: source(3, 1), params: { address_list: ['127.0.0.1:43891'] } },
  { time: '1200', type: 9, source: source(4, 2), params: { address: '[2001:4860:4860::8888]:443' } },
  { time: '1201', type: 11, source: source(5, 2), params: {} },
  { time: '1300', type: 7, source: source(3, 3), params: { address_list: ['127.0.0.1:8888'] } },
  { time: '1310', type: 12, source: source(3, 3), params: { byte_count: 8 } },
  { time: '1110', type: 20, source: source(1, 1), params: { url: `${origin}/wire/v1/server.hello`, method: 'POST' } },
  { time: '1310', type: 20, source: source(1, 2), params: { url: `https://redirector.gvt1.com/edgedl/chrome/dict/en.bdic`, method: 'GET',
    traffic_annotation: hash('spellcheck_hunspell_dictionary'), source_dependency: source(3, 3) } },
]
const positive = classifyPairNetwork(traces, { constants, events }, origin)
assert.equal(positive.pass, true)
assert.deepEqual(positive.categories, { server: 1, udpProbe: 1, dictionaryProxy: 1, localUdp: 0, remoteTcp: 0, remoteSend: 0, unknown: 0 })
const noType = { ...traces, 'electron-connect.trace.101': traces['electron-connect.trace.101'].replace(/^.*socket\(AF_INET6.*\n/m, '') }
assert.equal(classifyPairNetwork(noType, { constants, events }, origin).categories.unknown, 1)
const tcpRemote = { ...traces, 'electron-connect.trace.100': traces['electron-connect.trace.100'].replace('sin_addr=inet_addr("127.0.0.1")}, 16) = 0\n1700000000.320000', 'sin_addr=inet_addr("192.0.2.2")}, 16) = 0\n1700000000.320000') }
const remoteEvents = events.map(e => e.source.id === 3 && e.type === 7 ? { ...e, params: { address_list: ['192.0.2.2:8888'] } } : e)
const remoteTcp = classifyPairNetwork(tcpRemote, { constants, events: remoteEvents }, origin)
assert.equal(remoteTcp.pass, false)
assert.equal(remoteTcp.categories.remoteTcp, 1)
const sentUdp = { ...traces, 'electron-connect.trace.101': traces['electron-connect.trace.101'] + `${base}.220000 sendto(0x4, 0x1234, 0x8, 0x0, 0x0, 0x0) = 8\n` }
const remoteSend = classifyPairNetwork(sentUdp, { constants, events }, origin)
assert.equal(remoteSend.pass, false)
assert.equal(remoteSend.categories.remoteSend, 1)
const unknownRequest = classifyPairNetwork(traces, { constants, events: [...events,
  { time: '1330', type: 20, source: source(1, 9), params: { url: 'https://other.invalid/unknown', method: 'GET' } }] }, origin)
assert.equal(unknownRequest.pass, false)
assert.equal(unknownRequest.unknownRequests, 1)
const resourceUrl = 'https://resource.invalid/dict/en.bdic?signature=FAKE_RESOURCE_SIGNATURE'
const withRedirect = location => [...events,
  { time: '1315', type: 13, source: source(1, 2), params: { location } },
  { time: '1320', type: 20, source: source(1, 2), params: { url: location, method: 'GET' } }]
const approvedRedirect = classifyPairNetwork(traces, { constants, events: withRedirect(resourceUrl) }, origin)
assert.equal(approvedRedirect.pass, true)
assert.equal(approvedRedirect.dictionaryRequests, 1)
const dictionaryRedirect = classifyPairNetwork(traces, { constants, events: [...events,
  { time: '1320', type: 20, source: source(1, 2), params: { url: 'https://unreviewed.invalid/dict/en.bdic' } }] }, origin)
assert.equal(dictionaryRedirect.pass, false)
assert.equal(dictionaryRedirect.unknownRequests, 1)
for (const location of ['http://resource.invalid/dict/en.bdic',
  'https://user:password@resource.invalid/dict/en.bdic',
  'https://resource.invalid/not-a-dictionary',
  'https://resource.invalid/dict/en.bdic?server_token=FAKE_BEARER']) {
  const refused = classifyPairNetwork(traces, { constants, events: withRedirect(location) }, origin)
  assert.equal(refused.pass, false)
  assert.equal(refused.unknownRequests, 1)
}
for (const params of [{ headers: ['Authorization: Bearer FAKE_BEARER'] },
  { request_body: 'FAKE_PROMPT' }, { upload_data: 'FAKE_PROMPT' }]) {
  const leaked = classifyPairNetwork(traces, { constants, events: [...withRedirect(resourceUrl),
    { time: '1325', type: 20, source: source(1, 2), params }] }, origin)
  assert.equal(leaked.pass, false)
  assert.equal(leaked.unknownRequests, 1)
}
const crossUsed = classifyPairNetwork(traces, { constants, events: events.map(event =>
  event.source?.type === 1 && event.source?.id === 2 ? { ...event, params: { ...event.params,
    url: `${origin}/wire/v1/sessions.createAndSend`, method: 'POST' } } : event) }, origin)
assert.equal(crossUsed.pass, false, 'dictionary annotation cannot relabel a business POST')
const serverRedirect = classifyPairNetwork(traces, { constants, events: [...events,
  { time: '1120', type: 13, source: source(1, 1), params: { location: resourceUrl } }] }, origin)
assert.equal(serverRedirect.pass, false, 'business Server fetch cannot borrow the dictionary redirect rule')
const missingLocation = classifyPairNetwork(traces, { constants, events: [...events,
  { time: '1315', type: 13, source: source(1, 2), params: {} }] }, origin)
assert.equal(missingLocation.pass, false)
const wrongDictionaryPath = classifyPairNetwork(traces, { constants, events: events.map(event =>
  event.source?.type === 1 && event.source?.id === 2 ? { ...event, params: { ...event.params,
    url: 'https://redirector.gvt1.com/unrelated/en.bdic' } } : event) }, origin)
assert.equal(wrongDictionaryPath.pass, false)
assert.equal(wrongDictionaryPath.unknownRequests, 1)
const destinationMissing = classifyPairNetwork(traces, { constants, events: [...events,
  { time: '1330', type: 20, source: source(1, 10), params: { method: 'GET', traffic_annotation: hash('spellcheck_hunspell_dictionary') } }] }, origin)
assert.equal(destinationMissing.pass, false)
assert.equal(destinationMissing.unknownRequests, 1)
assert.equal(classifyPairNetwork(traces, { constants }, origin).pass, false)
assert.equal(credentialDestinationAllowed(`${origin}/wire/v1/server.hello`, origin, true), true)
assert.equal(credentialDestinationAllowed(`https://example.invalid/${fakeSecret}`, origin, true), false)
assert.equal(credentialDestinationAllowed('http://127.0.0.1:43891/wire/v1/server.hello', 'https://example.invalid', true), false)
assert.ok(!JSON.stringify({ positive }).includes(fakeSecret))
console.log(JSON.stringify({ synthetic: 'PASS', udpProbeNotTcp: true, remoteTcpRejected: true,
  remoteSendRejected: true, unknownTypeRejected: true, unknownRequestRejected: true,
  credentialRemoteRejected: true, reviewedDictionaryRedirectAccepted: true, unexplainedRedirectRejected: true,
  downgradeUserinfoBodyAuthRejected: true, businessDictionaryCrossUseRejected: true,
  wrongDictionaryPathRejected: true, missingDestinationRejected: true,
  truncatedRejected: true, redacted: true }))

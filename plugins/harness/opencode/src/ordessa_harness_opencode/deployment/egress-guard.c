/*
 * 仅 loopback 出口守护（**仅供门使用的离线资产**，生产部署从不引用）。
 *
 * 生产 OpenCode 只与官方 DeepSeek 根地址通信；本文件的对象是"不得访问真实网络的
 * 本机假端点门"：把这段 C 编译成共享库后以 LD_PRELOAD 预载到 opencode 进程，
 * 非 loopback 目的地在解析与连接之前就失败，并把拒绝目的地写进审计文件。
 *
 * 这样门里"这次运行只到达 loopback"就不是从配置推断出来的，而是进程内被强制并
 * 留下证据的事实：审计里出现 `denied connect host:port` 或 `denied resolve name`
 * 就说明确实有非 loopback 企图，必须让门失败。
 *
 * 实测：OpenCode 1.18.21 是动态链接 ELF，LD_PRELOAD 会被加载；一次成功的两轮
 * 会话里除 loopback 外没有任何目的地被尝试，唯一被拒的是 `registry.npmjs.org`
 * 的解析（其内置 provider 实现已经本地可用）。
 *
 * 允许：AF_UNIX / AF_NETLINK 等没有远程目的地的族，以及 127.0.0.0/8、::1 和
 * v4-mapped 的 127.x。其余一律拒绝（errno=EACCES / EAI_AGAIN）。
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <netdb.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>

/* 审计文件路径来自门注入的环境变量；没有该变量就不记录（仍然阻断）。 */
static void agentbox_audit(const char *line)
{
    const char *path = getenv("AGENTBOX_EGRESS_AUDIT");
    FILE *handle;
    if (path == NULL || path[0] == '\0') {
        return;
    }
    handle = fopen(path, "a");
    if (handle == NULL) {
        return;
    }
    fprintf(handle, "%s\n", line);
    fclose(handle);
}

static int agentbox_is_loopback(const struct sockaddr *address)
{
    if (address == NULL) {
        return 1;
    }
    if (address->sa_family == AF_INET) {
        const struct sockaddr_in *v4 = (const struct sockaddr_in *)address;
        return (ntohl(v4->sin_addr.s_addr) >> 24) == 127;
    }
    if (address->sa_family == AF_INET6) {
        const struct sockaddr_in6 *v6 = (const struct sockaddr_in6 *)address;
        if (IN6_IS_ADDR_LOOPBACK(&v6->sin6_addr)) {
            return 1;
        }
        if (IN6_IS_ADDR_V4MAPPED(&v6->sin6_addr)) {
            const unsigned char *bytes = v6->sin6_addr.s6_addr;
            return bytes[12] == 127;
        }
        return 0;
    }
    return 1; /* AF_UNIX 等没有远程目的地 */
}

static void agentbox_describe(const struct sockaddr *address, char *buffer, size_t size)
{
    char host[INET6_ADDRSTRLEN] = "?";
    int port = 0;
    if (address != NULL && address->sa_family == AF_INET) {
        const struct sockaddr_in *v4 = (const struct sockaddr_in *)address;
        inet_ntop(AF_INET, &v4->sin_addr, host, sizeof(host));
        port = ntohs(v4->sin_port);
    } else if (address != NULL && address->sa_family == AF_INET6) {
        const struct sockaddr_in6 *v6 = (const struct sockaddr_in6 *)address;
        inet_ntop(AF_INET6, &v6->sin6_addr, host, sizeof(host));
        port = ntohs(v6->sin6_port);
    }
    snprintf(buffer, size, "%s:%d", host, port);
}

__attribute__((constructor)) static void agentbox_guard_loaded(void)
{
    agentbox_audit("guard-loaded");
}

int connect(int descriptor, const struct sockaddr *address, socklen_t length)
{
    static int (*real_connect)(int, const struct sockaddr *, socklen_t) = NULL;
    char target[128];
    char line[192];
    if (real_connect == NULL) {
        real_connect = dlsym(RTLD_NEXT, "connect");
    }
    if (!agentbox_is_loopback(address)) {
        agentbox_describe(address, target, sizeof(target));
        snprintf(line, sizeof(line), "denied connect %s", target);
        agentbox_audit(line);
        errno = EACCES;
        return -1;
    }
    return real_connect(descriptor, address, length);
}

int getaddrinfo(const char *node, const char *service, const struct addrinfo *hints,
                struct addrinfo **result)
{
    static int (*real_getaddrinfo)(const char *, const char *, const struct addrinfo *,
                                   struct addrinfo **) = NULL;
    char line[192];
    if (real_getaddrinfo == NULL) {
        real_getaddrinfo = dlsym(RTLD_NEXT, "getaddrinfo");
    }
    if (node != NULL && strcmp(node, "127.0.0.1") != 0 && strcmp(node, "::1") != 0
        && strcmp(node, "localhost") != 0 && strcmp(node, "ip6-localhost") != 0
        && strcmp(node, "0.0.0.0") != 0 && strcmp(node, "::") != 0) {
        snprintf(line, sizeof(line), "denied resolve %s", node);
        agentbox_audit(line);
        return EAI_AGAIN;
    }
    return real_getaddrinfo(node, service, hints, result);
}

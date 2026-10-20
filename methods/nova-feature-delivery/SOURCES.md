# 来源与许可记录

查阅日期：2026-10-12。`latest` 文档没有被固定为某一 Git tag 或 commit；下列页面地址、页面标题/版本、摘要和查阅日期共同标识本次核查，不声称是不可变源码快照。仅使用独立概括，不复制 Nova spec 模板、逐段原文或网页图片。

| ID | 来源与摘要 | 版本/日期信息 | 许可/使用方式 |
| --- | --- | --- | --- |
| nova-process | [Nova team process](https://docs.openstack.org/nova/latest/contributor/process.html)：Blueprint/spec 关系、API 变更需 spec、小型低影响补丁可不需 spec、Blueprint 周期批准、负评处理、feature freeze、延期以及 Nova 会议路径。 | 页面标题版本 `nova 34.1.0.dev61`；协调核查记录页面更新于 2026-07-19；链接为 latest，未固定 tag。 | 页脚声明 Creative Commons Attribution 3.0；本包自行概述并引用。 |
| nova-blueprints | [Blueprints, Specs and Priorities](https://docs.openstack.org/nova/latest/contributor/blueprints.html)：Blueprint/Spec 流程的补充说明。 | latest 文档自身标注最后更新 2023-10-02；查阅日期 2026-10-12，未固定 tag。 | 页面明示 Creative Commons Attribution 3.0 License；仅作事实核对。 |
| opendev-dev | [OpenDev Developer’s Guide — Automated Testing](https://docs.opendev.org/opendev/infra-manual/latest/developers.html#automated-testing)：Gerrit patchset 的 check、`Verified +/-1`、审批后的 gate、`Verified +/-2`、失败日志诊断、变更缺陷与基础设施问题分流，以及 recheck 限制。 | latest；可读页面没有最后更新时间；查阅日期 2026-10-12，未固定 tag。 | 页面页脚列 OpenDev Contributors，但该页面未显示明确的内容许可声明；本包未复制文字、图片或模板，仅独立概括流程事实并保留链接，故不主张复用其版权文本。 |
| nova-implemented-spec | [Allow Manila shares to be directly attached to an instance when using libvirt](https://specs.openstack.org/openstack/nova-specs/specs/2025.1/implemented/libvirt-virtiofs-attach-manila-shares.html)：实际 Nova spec 示例；页面路径为 2025.1/implemented，History 列出 Yoga 至 Epoxy 的提案/重提案记录，最后更新时间 2025-03-11。其正文链接到给定 Launchpad Blueprint。 | 固定发布周期 `2025.1`；页面提供更新时间，不另行声称具体合并 commit。 | 页面明示 Creative Commons Attribution 3.0；本包只作简要摘要。 |
| nova-blueprint-example | [Launchpad Blueprint: libvirt-virtiofs-attach-manila-shares](https://blueprints.launchpad.net/nova/+spec/libvirt-virtiofs-attach-manila-shares)：用户指定实例。 | 本次 Web 访问被 blueprints.launchpad.net robots.txt 拒绝；未从页面读取状态/完成日期。API/Web 替代访问同样不可用。不能把 `2025-03-06` 说成已独立核实日期。 | 不复制页面内容；仅保留标识 URL。 |
| nova-2025.1-release | [2025.1 Series Release Notes](https://docs.openstack.org/releasenotes/nova/2025.1.html)：Nova 的正式发行说明明确列出 Manila shares 可由新的 Nova shares API 直接附加到实例。 | 2025.1 / Nova 31.0.0；发行说明文档现持续更新，不能从当前页推断某个具体 patchset 的 CI 全绿。 | 页面明示 Creative Commons Attribution 3.0；独立概括。 |

## 可证实范围

实际案例支持：Nova spec 被归档于 2025.1 implemented，且 2025.1 Nova release notes 记载该功能。OpenDev 手册支持本文描述的常规 Gerrit/Zuul check/gate 行为。本文不推断客户部署、全部相关 CI 均成功、版本内所有补丁的完整历史，也不补写 Launchpad 无法访问部分的状态。

/**
 * DI Token：C-05 主题服务。
 *
 * 每个 Token **单独一个模块**：`token-single-instance` 门按"一个构造点 ↔ 一个源文件"
 * 核对单例身份，多 Token 合并在一个文件会让"越界直引源文件"的反例失去判别力。
 * 名称即 lumino 解析键（`application[token.name]`/provides 注册），不得随意改写。
 */
import { Token } from '@lumino/coreutils'
import type { ThemeService } from '../theme'

export const ThemeServiceToken = new Token<ThemeService>('ordessa.theme.v1')

import type { OperationResult, PatchRequest } from './types'

export type TabletLayerStatus = 'applied' | 'unavailable' | 'unknown' | 'disabled'

export function tabletStatusForRequest(
  request: PatchRequest,
  status: TabletLayerStatus | undefined
): TabletLayerStatus | undefined {
  if (
    request.operation !== 'update' ||
    request.gameVersion !== 'poe2' ||
    !['all', 'currency'].includes(request.patchScope)
  )
    return undefined
  return status === 'disabled' ? 'unknown' : (status ?? 'unknown')
}

export function operationWarning(result: OperationResult | undefined): string | undefined {
  if (!result || result.cancelled || result.skipped || result.exitCode !== 0) return undefined
  if (result.tabletAffixes === 'unavailable')
    return '物价已更新，但碑牌词缀未生效，请重试；详情见日志。'
  if (result.tabletAffixes === 'unknown')
    return '物价已更新，但未能确认碑牌词缀结果，请查看日志后重试。'
  if (result.wholeTablets === 'unavailable' || result.wholeTablets === 'unknown')
    return '物价已更新，但国服整件/暗金碑牌价格未完整生效，请查看日志后重试。'
  return undefined
}

export function wholeTabletStatusForRequest(
  request: PatchRequest,
  status: TabletLayerStatus | undefined
): TabletLayerStatus | undefined {
  if (request.operation !== 'update' || request.gameVersion !== 'poe2' || request.patchScope === 'none')
    return undefined
  return status === 'disabled' ? undefined : status
}

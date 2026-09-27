import type { AppSettings } from './types'

type ContentOptions = Pick<AppSettings, 'gameVersion' | 'patchScope' | 'islandRumourHints' | 'tabletPrices' | 'tabletAffixPrices'>

export function hasPriceContent(options: ContentOptions): boolean {
  return options.patchScope !== 'none' ||
    (options.gameVersion === 'poe2' && ((options.tabletPrices ?? true) || (options.tabletAffixPrices ?? true)))
}

export function hasPatchContent(options: ContentOptions): boolean {
  return hasPriceContent(options) || (options.gameVersion === 'poe2' && options.islandRumourHints)
}

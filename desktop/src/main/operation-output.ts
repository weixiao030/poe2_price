import type { TabletLayerStatus } from '../shared/operation-outcome'

// Collect the short, final result separately from the truncated display log.
export class OperationOutput {
  tabletAffixes?: TabletLayerStatus
  wholeTablets?: TabletLayerStatus
  private pending = ''

  write(chunk: string) {
    const lines = (this.pending + chunk).split('\n')
    this.pending = lines.pop()!.slice(-512)
    for (const line of lines) this.parse(line)
  }

  end() {
    this.parse(this.pending)
    this.pending = ''
  }

  private parse(line: string) {
    const match = /^__POE_TABLET_LAYER__(applied|unavailable|unknown|disabled)\r?$/.exec(line)
    if (match) this.tabletAffixes = match[1] as TabletLayerStatus
    const whole = /^__POE_WHOLE_TABLETS__(applied|unavailable|unknown|disabled)\r?$/.exec(line)
    if (whole) this.wholeTablets = whole[1] as TabletLayerStatus
  }
}

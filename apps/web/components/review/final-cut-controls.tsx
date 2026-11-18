'use client'

import { useEffect, useState, useSyncExternalStore } from 'react'
import { Clapperboard } from 'lucide-react'
import { Switch } from '@/components/ui/switch'

/**
 * The Final Cut Pro controls, shown only when this page is running inside the
 * Adborth panel in Final Cut. The panel offers a message channel named
 * `adborth`; in an ordinary browser there is none and this renders nothing.
 *
 * The page asks, the panel does the work:
 *   { controls: true | false }  these controls are on screen (the panel hides its own)
 *   { action: 'comments' }      send this video's comments to Final Cut as a marker clip
 *   { follow: boolean }         whether the timeline should follow the player
 * and the panel answers with an `adborth-panel` event carrying `follow` and/or
 * `note`, the line it would otherwise have shown in its own bar.
 */

type Channel = { postMessage: (message: unknown) => void }

function channel(): Channel | null {
  if (typeof window === 'undefined') return null
  const handlers = (window as unknown as { webkit?: { messageHandlers?: Record<string, Channel> } })
    .webkit?.messageHandlers
  return handlers?.adborth ?? null
}

export function FinalCutControls() {
  // False while rendering on the server, so the first paint matches either way.
  const inPanel = useSyncExternalStore(
    () => () => {},
    () => channel() !== null,
    () => false,
  )
  const [follow, setFollow] = useState(true)
  const [note, setNote] = useState('')

  useEffect(() => {
    const panel = channel()
    if (!panel) return
    const heard = (event: Event) => {
      const detail = (event as CustomEvent<{ follow?: boolean; note?: string }>).detail ?? {}
      if (typeof detail.follow === 'boolean') setFollow(detail.follow)
      if (typeof detail.note === 'string') setNote(detail.note)
    }
    window.addEventListener('adborth-panel', heard)
    panel.postMessage({ controls: true })
    return () => {
      window.removeEventListener('adborth-panel', heard)
      panel.postMessage({ controls: false })
    }
  }, [])

  if (!inPanel) return null

  return (
    <div className="mx-4 mb-2 shrink-0 rounded-xl bg-bg-tertiary px-3 py-2.5" data-testid="final-cut-controls">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-[12px] font-medium text-text-secondary">
          <Clapperboard className="h-4 w-4" />
          Final Cut Pro
        </span>
        <button
          type="button"
          className="rounded-full bg-accent px-3 py-1 text-[12px] font-semibold text-white transition-colors hover:bg-accent-hover"
          title="Puts these comments into Final Cut as a marker clip for the project open in the timeline. Drag the project onto this panel instead to also get a copy with the markers on its own clips."
          onClick={() => channel()?.postMessage({ action: 'comments' })}
        >
          Send comments
        </button>
      </div>
      <label className="mt-2 flex cursor-pointer items-center justify-between gap-3 text-[12px] text-text-secondary">
        Timeline follows the player
        <Switch
          checked={follow}
          onCheckedChange={(on) => {
            setFollow(on)
            channel()?.postMessage({ follow: on })
          }}
          className="h-5 w-9 [&>span]:h-4 [&>span]:w-4 [&>span]:data-[state=checked]:translate-x-[18px]"
          aria-label="Timeline follows the player"
        />
      </label>
      {note && (
        <p className="mt-2 whitespace-pre-line text-[11px] leading-snug text-text-tertiary" role="status">
          {note}
        </p>
      )}
    </div>
  )
}

'use client'

import * as React from 'react'
import { Download, Link as LinkIcon, Pencil, Share2, Trash2, Layers } from 'lucide-react'
import { copyToClipboard } from '@/lib/utils'
import { withBasePath } from '@/lib/base-path'
import { DownloadSubmenu } from '@/components/shared/download-menu'
import { MenuAction, MenuSeparator } from '@/components/shared/item-menu'
import type { Asset, DownloadOption } from '@/types'

export interface AssetMenuHandlers {
  onShare?: () => void
  /** `rendition` is a DownloadOption id; left out, the server picks. */
  onDownload?: (rendition?: string) => void
  /** With this, Download opens a submenu of what the asset can be downloaded as. */
  loadDownloadOptions?: () => Promise<DownloadOption[] | null>
  onRename?: () => void
  /** Opens the version housekeeping (tidy, delete, release, stack). Owners only. */
  onManageVersions?: () => void
  onDelete?: () => void
}

/**
 * An asset's menu, for its ⋯ button and its right-click alike. As with the
 * folder menu, an entry is shown only when its action is: Copy Asset URL
 * always, the rest when the page passes a handler.
 */
export function AssetMenuItems({
  asset,
  onShare,
  onDownload,
  loadDownloadOptions,
  onRename,
  onManageVersions,
  onDelete,
}: AssetMenuHandlers & { asset: Pick<Asset, 'id' | 'project_id'> }) {
  return (
    <>
      {onShare && (
        <>
          <MenuAction icon={Share2} onSelect={onShare}>
            Create Share Link
          </MenuAction>
          <MenuSeparator />
        </>
      )}
      {onDownload &&
        (loadDownloadOptions ? (
          <DownloadSubmenu load={loadDownloadOptions} onPick={onDownload} />
        ) : (
          <MenuAction icon={Download} onSelect={() => onDownload()} immediate>
            Download
          </MenuAction>
        ))}
      <MenuAction
        icon={LinkIcon}
        immediate
        onSelect={() => {
          void copyToClipboard(
            `${window.location.origin}${withBasePath(`/projects/${asset.project_id}/assets/${asset.id}`)}`,
          )
        }}
      >
        Copy Asset URL
      </MenuAction>
      {(onRename || onManageVersions || onDelete) && <MenuSeparator />}
      {onRename && (
        <MenuAction icon={Pencil} onSelect={onRename}>
          Rename
        </MenuAction>
      )}
      {onManageVersions && (
        <MenuAction icon={Layers} onSelect={onManageVersions}>
          Manage Versions
        </MenuAction>
      )}
      {onDelete && (
        <MenuAction icon={Trash2} onSelect={onDelete} danger>
          Delete
        </MenuAction>
      )}
    </>
  )
}

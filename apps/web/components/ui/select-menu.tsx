'use client'

/**
 * Adborth's own dropdown, in place of the browser's stock menu.
 *
 * A soft field that opens a rounded panel of options, each with an optional
 * second line and a tick on the one chosen, the same picker the Mac app uses.
 * With `searchable` the panel starts with a search box and Return picks the
 * first match, for lists long enough to need it.
 *
 * It is a combobox with a listbox to assistive technology: the field names
 * itself with `label`, announces whether it is open, and each option says
 * whether it is selected. Up and Down move through the options, Return or
 * Space chooses, Escape closes.
 */
import * as React from 'react'
import * as Popover from '@radix-ui/react-popover'
import { Check, ChevronsUpDown, Search } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface SelectMenuOption<T extends string = string> {
  value: T
  label: string
  /** A quieter second line under the label. */
  detail?: string
}

export interface SelectMenuProps<T extends string = string> {
  value: T | ''
  onChange: (value: T) => void
  options: SelectMenuOption<T>[]
  /** What the field is for, read out and used to find it. */
  label: string
  placeholder?: string
  disabled?: boolean
  searchable?: boolean
  /** Shown before the chosen label, inside the field. */
  icon?: React.ReactNode
  size?: 'sm' | 'md'
  /** `field` is a filled box; `quiet` has no fill until hovered, for toolbars. */
  variant?: 'field' | 'quiet'
  align?: 'start' | 'end'
  className?: string
  title?: string
}

export function SelectMenu<T extends string = string>({
  value, onChange, options, label, placeholder = 'Choose…', disabled, searchable,
  icon, size = 'md', variant = 'field', align = 'start', className, title,
}: SelectMenuProps<T>) {
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState('')
  const [active, setActive] = React.useState(0)
  const listId = React.useId()
  const selected = options.find((o) => o.value === value)

  const matches = React.useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    if (words.length === 0) return options
    // Every word typed has to appear in the label, in any order.
    return options.filter((o) => words.every((w) => o.label.toLowerCase().includes(w)))
  }, [options, query])

  const openChange = (next: boolean) => {
    setOpen(next)
    if (next) {
      setQuery('')
      setActive(Math.max(0, options.findIndex((o) => o.value === value)))
    }
  }

  const choose = (option: SelectMenuOption<T> | undefined) => {
    if (!option) return
    setOpen(false)
    if (option.value !== value) onChange(option.value)
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((i) => Math.min(matches.length - 1, i + 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((i) => Math.max(0, i - 1))
    } else if (event.key === 'Enter' || (event.key === ' ' && !searchable)) {
      event.preventDefault()
      choose(matches[Math.min(active, matches.length - 1)])
    }
  }

  return (
    <Popover.Root open={open} onOpenChange={openChange}>
      <Popover.Trigger asChild>
        <button
          type="button"
          role="combobox"
          aria-label={label}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          disabled={disabled}
          title={title}
          className={cn(
            'inline-flex min-w-0 items-center gap-2 text-left font-medium text-text-primary transition-colors',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60',
            size === 'sm' ? 'h-8 rounded-[10px] px-2.5 text-xs' : 'h-10 rounded-xl px-3 text-sm',
            variant === 'field' ? 'bg-bg-tertiary hover:bg-bg-hover' : 'border border-border hover:bg-bg-hover',
            className,
          )}
        >
          {icon}
          <span className={cn('min-w-0 flex-1 truncate', !selected && 'font-normal text-text-tertiary')}>
            {selected?.label ?? placeholder}
          </span>
          <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-text-tertiary" aria-hidden="true" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align={align}
          sideOffset={6}
          onKeyDown={onKeyDown}
          onOpenAutoFocus={(event) => {
            // Without a search box, focus the list itself so the arrow keys work.
            if (!searchable) {
              event.preventDefault()
              document.getElementById(listId)?.focus()
            }
          }}
          className={cn(
            'z-[100] overflow-hidden rounded-2xl border border-border bg-bg-elevated shadow-xl outline-none',
            'min-w-[var(--radix-popover-trigger-width)] max-w-[min(26rem,calc(100vw-2rem))]',
            'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
          )}
        >
          {searchable && (
            <div className="flex items-center gap-2 border-b border-border px-3">
              <Search className="h-4 w-4 shrink-0 text-text-tertiary" aria-hidden="true" />
              <input
                autoFocus
                value={query}
                onChange={(event) => { setQuery(event.target.value); setActive(0) }}
                aria-label={`Search ${label.toLowerCase()}`}
                placeholder="Search"
                className="h-10 w-full min-w-0 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none"
              />
            </div>
          )}
          <div id={listId} role="listbox" aria-label={label} tabIndex={-1} className="max-h-64 overflow-y-auto p-1.5 outline-none">
            {matches.length === 0 && (
              <p className="px-3 py-3 text-sm text-text-tertiary">Nothing matches “{query.trim()}”.</p>
            )}
            {matches.map((option, index) => {
              const isSelected = option.value === value
              return (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(option)}
                  className={cn(
                    'flex w-full items-center gap-3 rounded-[10px] px-2.5 py-2 text-left outline-none transition-colors',
                    index === active ? 'bg-bg-hover' : 'bg-transparent',
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className={cn('block truncate text-sm', isSelected ? 'font-semibold text-text-primary' : 'text-text-primary')}>
                      {option.label}
                    </span>
                    {option.detail && <span className="block truncate text-xs text-text-tertiary">{option.detail}</span>}
                  </span>
                  {isSelected && <Check className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />}
                </button>
              )
            })}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

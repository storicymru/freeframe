"use client";

import * as React from "react";
import useSWR from "swr";
import { Check, Copy, KeyRound } from "lucide-react";
import { api } from "@/lib/api";
import { copyToClipboard, formatRelativeTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

/** What GET /integrations/cylch answers: whether there is a key, never the key. */
interface CylchStatus {
  has_key: boolean;
  made_at: string | null;
  used_at: string | null;
}

interface CylchKeyMade extends CylchStatus {
  key: string;
}

/**
 * The key Cylch connects with. Cylch is where a client's logo and colours are
 * kept; with this key it can list projects, make one, and set a project's
 * branding here, and nothing else. The key is shown once, when it is made:
 * only its hash is stored, so there is nothing to show afterwards.
 */
export function CylchTab() {
  const { data, mutate, isLoading } = useSWR<CylchStatus>("/integrations/cylch", (p: string) => api.get<CylchStatus>(p));
  const [fresh, setFresh] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [confirm, setConfirm] = React.useState<"replace" | "remove" | null>(null);

  async function make() {
    setBusy(true);
    setError(null);
    try {
      const made = await api.post<CylchKeyMade>("/integrations/cylch/key");
      setFresh(made.key);
      setCopied(false);
      await mutate({ has_key: true, made_at: made.made_at, used_at: null }, { revalidate: false });
      setConfirm(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The key could not be made");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.delete("/integrations/cylch/key");
      setFresh(null);
      await mutate({ has_key: false, made_at: null, used_at: null }, { revalidate: false });
      setConfirm(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The key could not be removed");
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (fresh && (await copyToClipboard(fresh))) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    }
  }

  const has = data?.has_key === true;

  return (
    <div className="space-y-6 max-w-xl">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-text-primary">Cylch key</h2>
        <p className="text-sm text-text-secondary">
          Cylch is where each client&rsquo;s logo and colours are kept. With a key, Cylch can list the projects here,
          make a project, and set a project&rsquo;s logo and colours. It cannot see footage, comments or people.
        </p>

        {fresh && (
          <div className="rounded-lg border border-border bg-bg-secondary p-4 space-y-3" data-testid="cylch-new-key">
            <p className="text-sm font-medium text-text-primary">Copy this key now. It won&rsquo;t be shown again.</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 min-w-0 break-all rounded-md bg-bg-primary px-3 py-2 text-xs text-text-primary">{fresh}</code>
              <Button variant="secondary" size="sm" onClick={copy} aria-label="Copy the key">
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
            <p className="text-xs text-text-tertiary">
              In Cylch: Team &amp; settings → Adborth → paste the key → Connect.
            </p>
          </div>
        )}

        {!isLoading && (
          <p className="text-sm text-text-secondary" data-testid="cylch-status">
            {has
              ? `A key was made ${data?.made_at ? formatRelativeTime(data.made_at) : "earlier"}. ${
                  data?.used_at ? `Cylch last used it ${formatRelativeTime(data.used_at)}.` : "Cylch hasn’t used it yet."
                }`
              : "There is no key, so Cylch is not connected."}
          </p>
        )}

        {error && !confirm && <p className="text-xs text-status-error">{error}</p>}

        <div className="flex flex-wrap gap-2">
          <Button onClick={() => (has ? setConfirm("replace") : make())} loading={busy && !confirm} disabled={isLoading}>
            <KeyRound className="h-4 w-4" />
            {has ? "Make a new key" : "Make a key"}
          </Button>
          {has && (
            <Button variant="secondary" onClick={() => setConfirm("remove")}>
              Remove the key
            </Button>
          )}
        </div>
      </section>

      <ConfirmDialog
        open={confirm === "replace"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Make a new key?"
        description="The key Cylch has now stops working straight away. Cylch stays disconnected until you paste the new one into it."
        confirmLabel="Make a new key"
        loading={busy}
        error={error}
        onConfirm={make}
      />
      <ConfirmDialog
        open={confirm === "remove"}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="Remove the key?"
        description="Cylch is disconnected. Branding already sent to projects stays as it is."
        confirmLabel="Remove the key"
        variant="danger"
        loading={busy}
        error={error}
        onConfirm={remove}
      />
    </div>
  );
}

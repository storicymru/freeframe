"use client";

import * as React from "react";
import { Bell, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { SelectMenu } from "@/components/ui/select-menu";

const CHANNEL_OPTIONS = [
  { value: "all_on", label: "All On" },
  { value: "in_app", label: "In-App Only" },
  { value: "all_off", label: "All Off" },
];

const commentNotifications = [
  {
    id: "general_comments",
    title: "General Comments",
    description: "When someone comments on an asset",
  },
  {
    id: "comment_replies",
    title: "Comment Replies",
    description: "When someone replies to your comment",
  },
  {
    id: "mentions",
    title: "@Mentions",
    description: "When someone @mentions you in a comment",
  },
];

const assetNotifications = [
  {
    id: "other_uploads",
    title: "Other Uploads",
    description: "When other users upload assets",
  },
  {
    id: "status_updates",
    title: "Status Updates",
    description: "When someone changes an asset's status",
  },
  {
    id: "assigned_to_you",
    title: "Assigned to You",
    description: "When someone assigns an asset to you",
  },
];

interface NotifPrefs {
  email_frequency: string;
  general_comments: string;
  comment_replies: string;
  mentions: string;
  other_uploads: string;
  status_updates: string;
  assigned_to_you: string;
  [key: string]: string;
}

const defaults: NotifPrefs = {
  email_frequency: "instant",
  general_comments: "all_on",
  comment_replies: "all_on",
  mentions: "all_on",
  other_uploads: "all_on",
  status_updates: "all_on",
  assigned_to_you: "all_on",
};

export default function NotificationsPage() {
  const { user } = useAuthStore();
  const [prefs, setPrefs] = React.useState<NotifPrefs>(defaults);
  const [saving, setSaving] = React.useState(false);
  const [loaded, setLoaded] = React.useState(false);

  // Load from user preferences
  React.useEffect(() => {
    if (!user?.preferences) return;
    const notif = (user.preferences.notifications ?? {}) as Record<
      string,
      unknown
    >;
    const merged: NotifPrefs = { ...defaults };
    Object.entries(notif).forEach(([key, value]) => {
      if (typeof value === "string") {
        merged[key] = value;
      }
    });
    setPrefs(merged);
    setLoaded(true);
  }, [user?.preferences]);

  async function updatePref(key: string, value: string) {
    const updated = { ...prefs, [key]: value };
    setPrefs(updated);
    setSaving(true);
    try {
      await api.patch("/auth/me/preferences", { notifications: updated });
    } catch {}
    setSaving(false);
  }

  return (
    <div className="p-6 max-w-3xl space-y-8">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-muted">
          <Bell className="h-5 w-5 text-text-primary" />
        </div>
        <div className="flex-1">
          <h1 className="text-lg font-semibold text-text-primary">
            Notifications
          </h1>
          <p className="text-sm text-text-secondary">
            Manage your notification preferences
          </p>
        </div>
        {saving && (
          <Loader2 className="h-4 w-4 animate-spin text-text-tertiary" />
        )}
      </div>

      {/* Email Frequency */}
      <section className="space-y-4">
        <div className="flex items-start gap-3 p-4 rounded-lg border border-border bg-bg-secondary">
          <Bell className="h-5 w-5 text-text-secondary mt-0.5" />
          <div className="flex-1">
            <h3 className="text-sm font-medium text-text-primary">
              Email Notifications Frequency
            </h3>
            <p className="text-xs text-text-tertiary mt-1">
              Email updates will be sent to your email address
            </p>
            <SelectMenu
              label="Email notifications frequency"
              value={prefs.email_frequency}
              onChange={(next) => updatePref("email_frequency", next)}
              options={[
                { value: "instant", label: "Instantly" },
                { value: "15min", label: "15 Minutes" },
                { value: "hourly", label: "Hourly" },
                { value: "daily", label: "Daily" },
                { value: "never", label: "Never" },
              ]}
              className="mt-3 w-44"
            />
          </div>
        </div>
      </section>

      {/* Comments Section */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-text-primary">Comments</h2>
        <div className="space-y-3">
          {commentNotifications.map((item) => (
            <div
              key={item.id}
              className="flex items-center justify-between p-3 rounded-lg border border-border bg-bg-secondary"
            >
              <div>
                <h3 className="text-sm font-medium text-text-primary">
                  {item.title}
                </h3>
                <p className="text-xs text-text-tertiary mt-0.5">
                  {item.description}
                </p>
              </div>
              <SelectMenu
                label={item.title}
                value={prefs[item.id] || "all_on"}
                onChange={(next) => updatePref(item.id, next)}
                options={CHANNEL_OPTIONS}
                size="sm"
                align="end"
                className="w-36 shrink-0"
              />
            </div>
          ))}
        </div>
      </section>

      {/* Assets Section */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-text-primary">Assets</h2>
        <div className="space-y-3">
          {assetNotifications.map((item) => (
            <div
              key={item.id}
              className="flex items-center justify-between p-3 rounded-lg border border-border bg-bg-secondary"
            >
              <div>
                <h3 className="text-sm font-medium text-text-primary">
                  {item.title}
                </h3>
                <p className="text-xs text-text-tertiary mt-0.5">
                  {item.description}
                </p>
              </div>
              <SelectMenu
                label={item.title}
                value={prefs[item.id] || "all_on"}
                onChange={(next) => updatePref(item.id, next)}
                options={CHANNEL_OPTIONS}
                size="sm"
                align="end"
                className="w-36 shrink-0"
              />
            </div>
          ))}
        </div>
      </section>

      <div className="p-4 rounded-lg bg-bg-tertiary border border-border">
        <p className="text-xs text-text-secondary">
          You will always get important administrative emails, such as password
          resets and account billing.
        </p>
      </div>
    </div>
  );
}

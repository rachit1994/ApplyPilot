import { useState, type ReactNode } from "react";
import { PageCanvas } from "./layout/PageCanvas";
import { useAgentSettings, type AgentSaveStatus } from "../hooks/useAgentSettings";

type SettingsSection =
  | "agent"
  | "search"
  | "filters"
  | "sources"
  | "schedule"
  | "outreach"
  | "profile"
  | "advanced";

const SECTIONS: { id: SettingsSection; label: string }[] = [
  { id: "agent", label: "Agent" },
  { id: "search", label: "Search" },
  { id: "filters", label: "Filters" },
  { id: "sources", label: "Sources" },
  { id: "schedule", label: "Schedule & limits" },
  { id: "outreach", label: "Outreach" },
  { id: "profile", label: "Profile" },
  { id: "advanced", label: "Advanced" },
];

export function SettingsDashboardPage() {
  const [section, setSection] = useState<SettingsSection>("agent");

  return (
    <PageCanvas wide>
      <div className="settings-shell">
        <nav className="settings-nav" aria-label="Settings sections">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={section === s.id ? "settings-nav__btn on" : "settings-nav__btn"}
              onClick={() => setSection(s.id)}
            >
              {s.label}
            </button>
          ))}
        </nav>

        <div className="settings-main">
          {section === "agent" ? <AgentSettings /> : null}
          {section !== "agent" ? <PlaceholderSection section={section} /> : null}
        </div>
      </div>
    </PageCanvas>
  );
}

function AgentSettings() {
  const { settings, status, error, update } = useAgentSettings();

  if (!settings) {
    return (
      <div>
        <div className="set-section-title">Agent behavior</div>
        <p className="panel__sub">
          {status === "loading" ? "Loading settings…" : error ?? "Could not load settings."}
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="set-section-header">
        <div className="set-section-title">Agent behavior</div>
        <SaveIndicator status={status} error={error} />
      </div>
      <div className="set-group">
        <SetRow
          title="Auto-apply"
          sub="Submit applications without asking when score is high enough"
          right={
            <SettingsToggle
              on={settings.auto_apply_enabled}
              onChange={(on) => update({ auto_apply_enabled: on })}
              label="Auto-apply"
            />
          }
        />
        <SetRow
          title="Minimum score to auto-apply"
          sub="Below this, the job goes to your manual queue"
          right={
            <label className="select-val select-val--input">
              <span className="visually-hidden">Minimum score to auto-apply</span>
              <input
                type="number"
                className="select-val__field"
                min={0}
                max={10}
                step={0.5}
                value={settings.apply_min_score}
                onChange={(e) => {
                  const raw = e.target.value;
                  if (raw === "") return;
                  const n = Number(raw);
                  if (Number.isNaN(n)) return;
                  update({ apply_min_score: Math.max(0, Math.min(10, n)) });
                }}
              />
            </label>
          }
        />
        <SetRow
          title="Tailor resume per job"
          sub="Rewrites your resume to match each role"
          right={
            <SettingsToggle
              on={settings.tailor_per_job}
              onChange={(on) => update({ tailor_per_job: on })}
              label="Tailor resume per job"
            />
          }
        />
        <SetRow
          title="Write cover letter"
          sub="One-paragraph cover for every application"
          right={
            <SettingsToggle
              on={settings.cover_letter}
              onChange={(on) => update({ cover_letter: on })}
              label="Write cover letter"
            />
          }
        />
        <SetRow
          title="Cross-source dedup"
          sub="Same role on multiple boards counts once"
          right={
            <SettingsToggle
              on={settings.cross_source_dedup}
              onChange={(on) => update({ cross_source_dedup: on })}
              label="Cross-source dedup"
            />
          }
        />
      </div>

      <p className="panel__sub" style={{ marginTop: 24 }}>
        Changes save automatically to{" "}
        <code>~/.applypilot/dashboard_settings.json</code> and update the apply queue
        minimum score for new runs. Profile, search, and site lists still live in{" "}
        <code>profile.json</code>, <code>searches.yaml</code>, and <code>sites.yaml</code>.
      </p>
    </div>
  );
}

function SaveIndicator({
  status,
  error,
}: {
  status: AgentSaveStatus;
  error: string | null;
}) {
  if (status === "saving") {
    return <span className="set-save-status set-save-status--saving">Saving…</span>;
  }
  if (status === "saved") {
    return <span className="set-save-status set-save-status--saved">Saved</span>;
  }
  if (status === "error" && error) {
    return <span className="set-save-status set-save-status--error">{error}</span>;
  }
  return null;
}

function SettingsToggle({
  on,
  onChange,
  label,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={on ? "toggle toggle--on" : "toggle"}
      onClick={() => onChange(!on)}
    />
  );
}

function PlaceholderSection({ section }: { section: SettingsSection }) {
  const label = SECTIONS.find((s) => s.id === section)?.label ?? section;
  return (
    <div>
      <div className="set-section-title">{label}</div>
      <p className="panel__sub">
        Configuration for {label.toLowerCase()} lives under <code>~/.applypilot/</code>. Use the CLI or edit
        YAML/JSON directly for now.
      </p>
    </div>
  );
}

function SetRow({
  title,
  sub,
  right,
}: {
  title: string;
  sub: string;
  right: ReactNode;
}) {
  return (
    <div className="set-row">
      <div className="set-row__main">
        <div className="set-row__title">{title}</div>
        <div className="set-row__sub">{sub}</div>
      </div>
      <div className="set-row__right">{right}</div>
    </div>
  );
}

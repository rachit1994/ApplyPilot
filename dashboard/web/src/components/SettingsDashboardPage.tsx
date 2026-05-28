import { useState, type ReactNode } from "react";
import { PageCanvas } from "./layout/PageCanvas";

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
  return (
    <div>
      <div className="set-section-title">Agent behavior</div>
      <div className="set-group">
        <SetRow
          title="Auto-apply"
          sub="Submit applications without asking when score is high enough"
          right={<div className="toggle toggle--on" />}
        />
        <SetRow title="Minimum score to auto-apply" sub="Below this, the job goes to your manual queue" right={<div className="select-val">7.0</div>} />
        <SetRow title="Tailor resume per job" sub="Rewrites your resume to match each role" right={<div className="toggle toggle--on" />} />
        <SetRow title="Write cover letter" sub="One-paragraph cover for every application" right={<div className="toggle toggle--on" />} />
        <SetRow title="Cross-source dedup" sub="Same role on multiple boards counts once" right={<div className="toggle toggle--on" />} />
      </div>

      <p className="panel__sub" style={{ marginTop: 24 }}>
        Live settings are edited in <code>~/.applypilot/profile.json</code>,{" "}
        <code>searches.yaml</code>, and <code>sites.yaml</code>. This screen mirrors the finalized layout;
        wire-up to read/write those files is coming next.
      </p>
    </div>
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

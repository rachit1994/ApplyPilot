import type { ReactNode } from "react";
import type { ApplyRunSettings } from "../utils/applyCliCommand";
import { ToggleSwitch } from "./ToggleSwitch";

type Props = {
  settings: ApplyRunSettings;
  compact?: boolean;
};

function SetRow({
  title,
  sub,
  right,
}: {
  title: string;
  sub?: string;
  right: ReactNode;
}) {
  return (
    <div className="set-row">
      <div className="set-row__main">
        <div className="set-row__title">{title}</div>
        {sub ? <div className="set-row__sub">{sub}</div> : null}
      </div>
      <div className="set-row__right">{right}</div>
    </div>
  );
}

export function ApplyRunControls({ settings }: Props) {
  const disabled = settings.isRunning ?? false;

  return (
    <>
      <section className="run-plan-modal__section">
        <div className="set-section-title">Queue limits</div>
        <div className="set-group">
          <SetRow
            title="Application limit"
            sub="Leave blank to keep going until the queue is empty"
            right={
              <label className="select-val select-val--input select-val--wide">
                <span className="visually-hidden">Application limit</span>
                <input
                  type="number"
                  className="select-val__field"
                  min={1}
                  placeholder="No limit"
                  disabled={disabled}
                  value={settings.limit}
                  onChange={(e) =>
                    settings.setLimit(e.target.value === "" ? "" : Number(e.target.value))
                  }
                />
              </label>
            }
          />
          <SetRow
            title="Minimum score"
            sub="Only ready jobs at or above this fit score"
            right={
              <label className="select-val select-val--input">
                <span className="visually-hidden">Minimum score</span>
                <input
                  type="number"
                  className="select-val__field"
                  min={0}
                  max={10}
                  disabled={disabled}
                  value={settings.minScore}
                  onChange={(e) => settings.setMinScore(Number(e.target.value))}
                />
              </label>
            }
          />
          <SetRow
            title="Workers"
            sub="Parallel Chrome workers submitting applications"
            right={
              <label className="select-val select-val--input">
                <span className="visually-hidden">Workers</span>
                <input
                  type="number"
                  className="select-val__field"
                  min={1}
                  max={8}
                  disabled={disabled}
                  value={settings.workers}
                  onChange={(e) => settings.setWorkers(Number(e.target.value))}
                />
              </label>
            }
          />
        </div>
      </section>

      <section className="run-plan-modal__section">
        <div className="set-section-title">Browser behavior</div>
        <p className="run-plan-modal__section-hint">
          Visible Chrome is the default so you can watch fills and unblock login prompts.
        </p>
        <div className="set-group">
          <SetRow
            title="Browser mode"
            sub="Watch keeps Chrome on screen; headless runs in the background"
            right={
              <div className="segment" role="group" aria-label="Browser mode">
                <button
                  type="button"
                  className={settings.watch && !settings.headless ? "on" : ""}
                  disabled={disabled}
                  onClick={() => {
                    settings.setWatch(true);
                    settings.setHeadless(false);
                  }}
                >
                  Watch
                </button>
                <button
                  type="button"
                  className={settings.headless ? "on" : ""}
                  disabled={disabled}
                  onClick={() => {
                    settings.setHeadless(true);
                    settings.setWatch(false);
                  }}
                >
                  Headless
                </button>
              </div>
            }
          />
          <SetRow
            title="Drain the full queue"
            sub="Keep going until no ready jobs remain (--continuous)"
            right={
              <ToggleSwitch
                label="Drain the full queue"
                on={settings.continuous}
                disabled={disabled}
                onChange={settings.setContinuous}
              />
            }
          />
          <SetRow
            title="Slow pacing"
            sub="Extra delays between steps for easier watching (--pace)"
            right={
              <ToggleSwitch
                label="Slow pacing"
                on={settings.pace}
                disabled={disabled}
                onChange={settings.setPace}
              />
            }
          />
          <SetRow
            title="Dry run"
            sub="Walk forms without submitting applications"
            right={
              <ToggleSwitch
                label="Dry run"
                on={settings.dryRun}
                disabled={disabled}
                onChange={settings.setDryRun}
              />
            }
          />
        </div>
      </section>
    </>
  );
}

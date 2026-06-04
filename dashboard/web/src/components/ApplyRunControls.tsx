import type { ApplyRunSettings } from "../utils/applyCliCommand";

type Props = {
  settings: ApplyRunSettings;
  compact?: boolean;
};

export function ApplyRunControls({ settings, compact }: Props) {
  const disabled = settings.isRunning ?? false;

  if (compact) {
    return (
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap gap-3">
          <label className="flex items-center gap-1.5 text-ink-2">
            Limit
            <input
              type="number"
              min={1}
              placeholder="∞"
              disabled={disabled}
              value={settings.limit}
              onChange={(e) =>
                settings.setLimit(e.target.value === "" ? "" : Number(e.target.value))
              }
              className="w-16 rounded border border-panel-border bg-canvas px-1 py-0.5"
            />
          </label>
          <label className="flex items-center gap-1.5 text-ink-2">
            Min score
            <input
              type="number"
              min={0}
              max={10}
              disabled={disabled}
              value={settings.minScore}
              onChange={(e) => settings.setMinScore(Number(e.target.value))}
              className="w-14 rounded border border-panel-border bg-canvas px-1 py-0.5"
            />
          </label>
          <label className="flex items-center gap-1.5 text-ink-2">
            Workers
            <input
              type="number"
              min={1}
              max={8}
              disabled={disabled}
              value={settings.workers}
              onChange={(e) => settings.setWorkers(Number(e.target.value))}
              className="w-14 rounded border border-panel-border bg-canvas px-1 py-0.5"
            />
          </label>
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-ink-3">
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={settings.watch}
              disabled={disabled}
              onChange={(e) => settings.setWatch(e.target.checked)}
            />
            Watch (visible Chrome)
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={settings.continuous}
              disabled={disabled}
              onChange={(e) => settings.setContinuous(e.target.checked)}
            />
            Continuous
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={settings.pace}
              disabled={disabled}
              onChange={(e) => settings.setPace(e.target.checked)}
            />
            Pace
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={settings.headless}
              disabled={disabled}
              onChange={(e) => settings.setHeadless(e.target.checked)}
            />
            Headless
          </label>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={settings.dryRun}
              disabled={disabled}
              onChange={(e) => settings.setDryRun(e.target.checked)}
            />
            Dry run
          </label>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="control-grid">
        <label className="control">
          <span className="control__label">Limit</span>
          <input
            className="control__input"
            type="number"
            min={1}
            disabled={disabled}
            value={settings.limit}
            onChange={(e) =>
              settings.setLimit(e.target.value === "" ? "" : Number(e.target.value))
            }
            placeholder="no limit"
          />
        </label>
        <label className="control">
          <span className="control__label">Min score</span>
          <input
            className="control__input"
            type="number"
            min={0}
            max={10}
            disabled={disabled}
            value={settings.minScore}
            onChange={(e) => settings.setMinScore(Number(e.target.value))}
          />
        </label>
        <label className="control">
          <span className="control__label">Workers</span>
          <input
            className="control__input"
            type="number"
            min={1}
            max={8}
            disabled={disabled}
            value={settings.workers}
            onChange={(e) => settings.setWorkers(Number(e.target.value))}
          />
        </label>
      </div>
      <div className="mt-10 flex flex-wrap gap-8">
        <button
          type="button"
          className={settings.watch ? "chip chip--on" : "chip"}
          disabled={disabled}
          onClick={() => settings.setWatch(!settings.watch)}
        >
          Watch
        </button>
        <button
          type="button"
          className={settings.continuous ? "chip chip--on" : "chip"}
          disabled={disabled}
          onClick={() => settings.setContinuous(!settings.continuous)}
        >
          Continuous
        </button>
        <button
          type="button"
          className={settings.pace ? "chip chip--on" : "chip"}
          disabled={disabled}
          onClick={() => settings.setPace(!settings.pace)}
        >
          Pace
        </button>
        <button
          type="button"
          className={settings.headless ? "chip chip--on" : "chip"}
          disabled={disabled}
          onClick={() => settings.setHeadless(!settings.headless)}
        >
          Headless
        </button>
        <button
          type="button"
          className={settings.dryRun ? "chip chip--on" : "chip"}
          disabled={disabled}
          onClick={() => settings.setDryRun(!settings.dryRun)}
        >
          Dry run
        </button>
      </div>
    </>
  );
}

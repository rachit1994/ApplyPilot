import { useMemo } from "react";
import {
  applyRunSummaryLines,
  applySettingsToCliOptions,
  buildApplyCliCommand,
  type ApplyRunSettings,
} from "../utils/applyCliCommand";
import { ApplyRunControls } from "./ApplyRunControls";
import { RunPlanModal } from "./RunPlanModal";

type Props = {
  open: boolean;
  settings: ApplyRunSettings;
  readyCount?: number | string;
  onCancel: () => void;
  onConfirm: () => void;
};

export function ApplyRunPlanModal({
  open,
  settings,
  readyCount,
  onCancel,
  onConfirm,
}: Props) {
  const opts = useMemo(() => applySettingsToCliOptions(settings), [settings]);
  const cliCommand = useMemo(() => buildApplyCliCommand(opts), [opts]);
  const summaryLines = useMemo(
    () => applyRunSummaryLines(opts, readyCount),
    [opts, readyCount],
  );

  return (
    <RunPlanModal
      open={open}
      title="Start apply queue"
      cliCommand={cliCommand}
      summaryLines={summaryLines}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <ApplyRunControls settings={settings} compact />
    </RunPlanModal>
  );
}

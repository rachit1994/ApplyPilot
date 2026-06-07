type Props = {
  on: boolean;
  disabled?: boolean;
  label: string;
  onChange: (on: boolean) => void;
};

export function ToggleSwitch({ on, disabled, label, onChange }: Props) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      className={on ? "toggle toggle--on" : "toggle"}
      onClick={() => onChange(!on)}
    />
  );
}

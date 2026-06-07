import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteFieldOverride,
  fetchFieldOverrides,
  setFieldOverride,
  type FieldOverrideRow,
} from "../api";

export function GlobalFieldOverridesPanel() {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("");
  const [editingLabel, setEditingLabel] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");

  const { data, isPending, error } = useQuery({
    queryKey: ["field-overrides"],
    queryFn: fetchFieldOverrides,
  });

  const overrides = data?.overrides ?? [];

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["field-overrides"] });
  }, [queryClient]);

  const saveMutation = useMutation({
    mutationFn: ({ lbl, val }: { lbl: string; val: string }) => setFieldOverride(lbl, val),
    onSuccess: () => {
      setLabel("");
      setValue("");
      setEditingLabel(null);
      invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (lbl: string) => deleteFieldOverride(lbl),
    onSuccess: invalidate,
  });

  const startEdit = (row: FieldOverrideRow) => {
    setEditingLabel(row.label);
    setEditValue(row.value);
  };

  return (
    <section className="panel apps__overrides" aria-label="Global field overrides">
      <header className="panel__head panel__head--inset">
        <div>
          <h2 className="panel__title">Global field overrides</h2>
          <p className="panel__sub">
            Changes apply to all jobs on the next fill (Prepare or Submit).
          </p>
        </div>
      </header>
      <div className="panel__body apps__overrides-body">
        {error ? (
          <p className="panel__sub">{error instanceof Error ? error.message : "Failed to load"}</p>
        ) : isPending ? (
          <p className="panel__sub">Loading overrides…</p>
        ) : overrides.length === 0 ? (
          <p className="panel__sub">No overrides yet. Add a label and value below.</p>
        ) : (
          <ul className="apps__overrides-list">
            {overrides.map((row) => (
              <li key={row.label} className="apps__overrides-row">
                {editingLabel === row.label ? (
                  <>
                    <span className="apps__overrides-label">{row.label}</span>
                    <input
                      className="apps__controls-search"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      aria-label={`Value for ${row.label}`}
                    />
                    <button
                      type="button"
                      className="btn btn--sm btn--accent"
                      disabled={saveMutation.isPending}
                      onClick={() =>
                        void saveMutation.mutateAsync({ lbl: row.label, val: editValue })
                      }
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm btn--ghost"
                      onClick={() => setEditingLabel(null)}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <span className="apps__overrides-label">{row.label}</span>
                    <span className="apps__overrides-value">{row.value}</span>
                    <button
                      type="button"
                      className="btn btn--sm btn--ghost"
                      onClick={() => startEdit(row)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn btn--sm btn--ghost"
                      disabled={deleteMutation.isPending}
                      onClick={() => void deleteMutation.mutateAsync(row.label)}
                    >
                      Remove
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        <form
          className="apps__overrides-add"
          onSubmit={(e) => {
            e.preventDefault();
            const lbl = label.trim();
            if (!lbl) return;
            void saveMutation.mutateAsync({ lbl, val: value });
          }}
        >
          <input
            className="apps__controls-search"
            placeholder="Field label (e.g. Phone)"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            aria-label="Override field label"
          />
          <input
            className="apps__controls-search"
            placeholder="Value to fill on every form"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            aria-label="Override field value"
          />
          <button
            type="submit"
            className="btn btn--sm btn--accent"
            disabled={!label.trim() || saveMutation.isPending}
          >
            Add override
          </button>
        </form>
      </div>
    </section>
  );
}

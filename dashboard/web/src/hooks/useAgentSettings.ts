import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchAgentSettings,
  patchAgentSettings,
  type AgentSettings,
} from "../api";
import { useDebouncedValue } from "../utils/useDebouncedValue";

export const AGENT_SETTINGS_QUERY_KEY = "agent-settings";

export type AgentSaveStatus = "idle" | "loading" | "saving" | "saved" | "error";

const SAVE_DEBOUNCE_MS = 450;
const SAVED_CLEAR_MS = 2000;

export function useAgentSettings() {
  const [settings, setSettings] = useState<AgentSettings | null>(null);
  const [status, setStatus] = useState<AgentSaveStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const debounced = useDebouncedValue(settings, SAVE_DEBOUNCE_MS);
  const hydratedRef = useRef(false);
  const lastSavedRef = useRef<string>("");

  const load = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const res = await fetchAgentSettings();
      setSettings(res.agent);
      lastSavedRef.current = JSON.stringify(res.agent);
      hydratedRef.current = true;
      setStatus("idle");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!hydratedRef.current || debounced == null) return;
    const serialized = JSON.stringify(debounced);
    if (serialized === lastSavedRef.current) return;

    let cancelled = false;
    setStatus("saving");
    setError(null);

    patchAgentSettings(debounced)
      .then((res) => {
        if (cancelled) return;
        setSettings(res.agent);
        lastSavedRef.current = JSON.stringify(res.agent);
        setStatus("saved");
        window.setTimeout(() => {
          if (!cancelled) {
            setStatus((s) => (s === "saved" ? "idle" : s));
          }
        }, SAVED_CLEAR_MS);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to save settings");
        setStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [debounced]);

  const update = useCallback((patch: Partial<AgentSettings>) => {
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  return { settings, status, error, update, reload: load };
}

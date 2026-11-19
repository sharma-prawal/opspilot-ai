"use client";

// The active inference models come from the backend configuration (LLM_MODEL / EMBEDDING_MODEL), never from
// constants in the UI. Static copy uses the {LLM_MODEL} / {EMBEDDING_MODEL} tokens and is filled at render time.
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Overview } from "./types";

export interface ActiveModels {
  llm: string | null;
  embedding: string | null;
  embeddingDimensions: number | null;
  think: boolean | null;
  numCtx: number | null;
  temperature: number | null;
}

export const LLM_TOKEN = "{LLM_MODEL}";
export const EMBEDDING_TOKEN = "{EMBEDDING_MODEL}";

export function activeModelsFrom(overview: Overview | undefined): ActiveModels {
  const rt = overview?.runtime;
  const inf = rt?.inference;
  return {
    llm: inf?.llm_model ?? rt?.llm_model ?? null,
    embedding: inf?.embedding_model ?? rt?.embedding_model ?? null,
    embeddingDimensions: inf?.embedding_dimensions ?? null,
    think: inf?.think ?? null,
    numCtx: inf?.num_ctx ?? null,
    temperature: inf?.temperature ?? null,
  };
}

/** Replace model tokens; unknown values are marked unavailable (never guessed, never shown as a model name). */
export function fillModels(text: string, m: Pick<ActiveModels, "llm" | "embedding">): string {
  return text
    .replaceAll(LLM_TOKEN, m.llm ?? "LLM_MODEL (unavailable)")
    .replaceAll(EMBEDDING_TOKEN, m.embedding ?? "EMBEDDING_MODEL (unavailable)");
}

function useOverviewForModels() {
  return useQuery({ queryKey: ["overview"], queryFn: api.overview, staleTime: 30_000 });
}

export function useActiveModels(): ActiveModels {
  return activeModelsFrom(useOverviewForModels().data);
}

export function ModelName({ kind = "llm", className }: { kind?: "llm" | "embedding"; className?: string }) {
  const overview = useOverviewForModels();
  const m = activeModelsFrom(overview.data);
  const value = kind === "llm" ? m.llm : m.embedding;
  const setting = kind === "llm" ? "LLM_MODEL" : "EMBEDDING_MODEL";
  // While loading show an ellipsis; if the backend did not report the model (e.g. the BFF call failed), say so
  // rather than rendering the setting name where a model name is expected.
  const fallback = overview.isPending && !overview.isError ? "…" : "unavailable";
  return (
    <code
      suppressHydrationWarning
      className={className ?? "font-mono text-accent"}
      title={value ? setting : `${setting} not reported by the backend`}
    >
      {value ?? fallback}
    </code>
  );
}

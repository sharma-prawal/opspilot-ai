import { describe, expect, it } from "vitest";
import { activeModelsFrom, fillModels } from "../lib/models";
import type { Overview } from "../lib/types";

const overview = (runtime: Partial<Overview["runtime"]>) => ({ runtime }) as unknown as Overview;

describe("active model display", () => {
  it("renders the configured models into static copy", () => {
    const m = activeModelsFrom(
      overview({
        llm_model: "x",
        embedding_model: "y",
        inference: {
          provider: "ollama", llm_model: "family-a:9b", think: false, temperature: 0, num_ctx: 8192,
          num_predict: 1536, embedding_model: "embed-b:1b", embedding_dimensions: 1024,
        },
      }),
    );
    expect(fillModels("{LLM_MODEL} · {EMBEDDING_MODEL}", m)).toBe("family-a:9b · embed-b:1b");
  });

  it("falls back to the setting names instead of guessing a model", () => {
    expect(fillModels("{LLM_MODEL} / {EMBEDDING_MODEL}", activeModelsFrom(undefined))).toBe(
      "LLM_MODEL / EMBEDDING_MODEL",
    );
  });

  it("uses runtime fields when the inference block is absent (older API)", () => {
    expect(activeModelsFrom(overview({ llm_model: "m1", embedding_model: "e1" })).llm).toBe("m1");
  });
});

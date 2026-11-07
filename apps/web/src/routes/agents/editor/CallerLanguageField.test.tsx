import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { onePerBase, supportedLanguages, switchTargets } from "../../../api/languageSwitching";
import { voiceCatalog } from "../../../mocks/agents/catalog";
import { defaultConfig, validateConfig } from "../../../mocks/agents/rules";
import { store } from "../../../mocks/agents/store";
import { renderApp, signInDemo } from "../../../test/render";

const stack = (language: string, stt: string, tts: [string, string]) => ({
  language,
  stt: { provider: stt },
  tts: { provider: tts[0], model: tts[1] },
});
const codes = (langs: { code: string }[]) => langs.map((l) => l.code);

describe("supported caller languages (012)", () => {
  it("needs both the speech recognition provider and the voice model, never the agent's own language", () => {
    const targets = codes(switchTargets(voiceCatalog, stack("en-US", "deepgram", ["elevenlabs", "eleven_multilingual_v2"])));
    expect(targets).toEqual(expect.arrayContaining(["hi", "es", "es-419", "fr-CA", "zh-CN", "uk"]));
    // Tamil: the voice speaks it, Deepgram does not hear it. Norwegian: the reverse.
    for (const code of ["ta", "no", "bn", "multi", "en", "en-GB", "en-IN"]) expect(targets).not.toContain(code);
    // The agent's own language is supported (validation does not warn about it), just not offered.
    expect(codes(supportedLanguages(voiceCatalog, stack("en-US", "deepgram", ["elevenlabs", "eleven_multilingual_v2"])))).toContain("en-GB");
  });

  it("offers one code per base language when the list is empty, the bare code first", () => {
    const offered = codes(onePerBase(switchTargets(voiceCatalog, stack("en-US", "deepgram", ["elevenlabs", "eleven_multilingual_v2"]))));
    expect(offered).toHaveLength(19);
    expect(offered).toContain("es");
    expect(offered).not.toContain("es-419");
    expect(offered).toContain("zh");
    expect(offered).not.toContain("zh-CN");
  });

  it("reads an English-only voice model through its multilingual model", () => {
    expect(codes(switchTargets(voiceCatalog, stack("en-US", "deepgram", ["elevenlabs", "eleven_flash_v2"])))).toContain("no");
    expect(codes(switchTargets(voiceCatalog, stack("hi", "sarvam", ["elevenlabs", "eleven_multilingual_v2"])))).toEqual(["en-IN", "ta"]);
  });

  it("validates the list like the API: unknown codes are errors, unsupported ones warnings", () => {
    const config = defaultConfig("single_prompt");
    config.prompt = "Help callers.";
    config.advanced.language_switching = { enabled: true, languages: ["hi", "xx", "ta"] };
    const result = validateConfig("single_prompt", config);
    expect(result.errors).toEqual([
      { pointer: "/advanced/language_switching/languages", code: "not_in_catalog", message: "The language 'xx' is not offered." },
    ]);
    expect(result.warnings).toContainEqual({
      pointer: "/advanced/language_switching/languages",
      code: "language_unsupported",
      message: "Tamil is not supported by this agent's speech recognition and voice, so callers cannot switch to it.",
    });
    expect(defaultConfig("single_prompt").advanced.language_switching).toEqual({ enabled: true, languages: [] });
    expect(defaultConfig("single_prompt").tts.model).toBe("eleven_multilingual_v2");
  });
});

describe("CallerLanguageField (012)", () => {
  it("shows the chosen languages, hides them when switched off, and adds one from the picker", async () => {
    await signInDemo();
    const user = userEvent.setup();
    const agent = store().agents.find((a) => a.name === "Front desk agent")!;
    renderApp(`/agents/${agent.id}/edit`);

    const toggle = await screen.findByRole("switch", { name: "Let callers switch language" }, { timeout: 5000 });
    expect(toggle).toBeChecked();
    const chosen = screen.getByRole("list", { name: "Chosen caller languages" });
    expect(
      within(chosen)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["Hindi", "Spanish"]);
    expect(screen.getByText("Callers can switch to these 2 languages only.")).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(screen.queryByRole("list", { name: "Chosen caller languages" })).not.toBeInTheDocument();

    await user.click(toggle);
    await user.click(screen.getByRole("button", { name: "Edit languages" }));
    const picker = await screen.findByRole("dialog", { name: "Caller languages" });
    // Front desk speaks Flash v2.5, which also covers Norwegian.
    expect(within(picker).getByRole("checkbox", { name: "Norwegian" })).not.toBeChecked();
    expect(within(picker).queryByRole("checkbox", { name: "Tamil" })).not.toBeInTheDocument();
    await user.click(within(picker).getByRole("checkbox", { name: "French" }));
    await user.click(within(picker).getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(
        within(screen.getByRole("list", { name: "Chosen caller languages" }))
          .getAllByRole("listitem")
          .map((li) => li.textContent),
      ).toEqual(["French", "Hindi", "Spanish"]),
    );

    await user.click(screen.getByRole("button", { name: "Remove French" }));
    await user.click(screen.getByRole("button", { name: "Remove Hindi" }));
    await user.click(screen.getByRole("button", { name: "Remove Spanish" }));
    expect(await screen.findByText("All supported languages")).toBeInTheDocument();
    expect(screen.getByText(/Callers can switch to any of the 20 languages/)).toBeInTheDocument();
  }, 20_000);
});

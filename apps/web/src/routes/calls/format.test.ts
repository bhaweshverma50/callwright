import { describe, expect, it } from "vitest";
import { diagnosticText } from "./format";

describe("diagnosticText", () => {
  it("reads an unsupported vendor as not set up on this platform", () => {
    expect(diagnosticText("unsupported_vendor:stt/sarvam")).toBe("Sarvam AI speech recognition is not set up on this platform.");
    expect(diagnosticText("unsupported_vendor:llm/anthropic")).toBe("Anthropic language model is not set up on this platform.");
    expect(diagnosticText("unsupported_vendor:tts/elevenlabs/eleven_x")).toBe("ElevenLabs voice does not support the model eleven_x.");
  });

  it("reads other failures and stays silent for unknown codes", () => {
    expect(diagnosticText("stt_language_unsupported:assemblyai/ja")).toBe("AssemblyAI speech recognition has no model for ja.");
    expect(diagnosticText("vendor_error:tts/cartesia")).toBe("Cartesia voice failed during the call.");
    expect(diagnosticText("pricing_unavailable:tts")).toBeNull();
    expect(diagnosticText(null)).toBeNull();
  });
});

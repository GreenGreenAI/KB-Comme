import { beforeEach, describe, expect, it } from "vitest";

import { forget, load, save } from "./session.js";

describe("what the browser remembers between page loads", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("gives back what was told to it", () => {
    save({ view: "work", facts: { profile: { company_size: "small" } }, turns: [] });

    expect(load().view).toBe("work");
    expect(load().facts.profile.company_size).toBe("small");
  });

  it("marks restored turns so the answer does not write itself out again", () => {
    save({ turns: [{ who: "agent", kind: "result" }] });

    expect(load().turns[0].restored).toBe(true);
  });

  it("drops a payload an older build wrote", () => {
    // Migrating a shape nobody remembers risks a screen that half matches the
    // code. Re-typing one question is the cheaper failure.
    window.sessionStorage.setItem(
      "tradeflow.session",
      JSON.stringify({ v: 0, state: { view: "work" } }),
    );

    expect(load()).toBeNull();
  });

  it("survives a payload that is not JSON at all", () => {
    window.sessionStorage.setItem("tradeflow.session", "{ broken");

    expect(load()).toBeNull();
  });

  it("keeps the newest turns when the thread grows long", () => {
    save({ turns: Array.from({ length: 60 }, (_, n) => ({ who: "user", text: `${n}` })) });

    const kept = load().turns;

    expect(kept).toHaveLength(40);
    expect(kept.at(-1).text).toBe("59");
  });

  it("keeps every fact even when turns are trimmed", () => {
    // The thread is what the reader sees; the facts are what the rules read.
    // Trimming the first must never trim the second.
    save({
      turns: Array.from({ length: 60 }, () => ({ who: "user", text: "x" })),
      facts: { stated: { "company.ksure_exporter_grade": "C" } },
    });

    expect(load().facts.stated["company.ksure_exporter_grade"]).toBe("C");
  });

  it("forgets on request", () => {
    save({ view: "work" });
    forget();

    expect(load()).toBeNull();
  });

  it("reads nothing when there is nothing", () => {
    expect(load()).toBeNull();
  });
});

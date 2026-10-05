import { describe, expect, it } from "vitest";
import { formatRunDate, isIsoDate, latestRun, snapshotForDate, type RunIndex } from "./runs";

const entry = (run_id: string, snapshot = false, status = "completed") => ({
  run_id,
  city_code: "sp",
  started_at: `${run_id.slice(0, 10)}T10:00:00Z`,
  finished_at: `${run_id.slice(0, 10)}T10:01:00Z`,
  status,
  snapshot,
  path: `runs/${run_id}/`,
});

const index = (
  runs: ReturnType<typeof entry>[],
  latest: Record<string, string> = {},
): RunIndex => ({
  schema_version: 1,
  latest,
  runs,
});

describe("latestRun", () => {
  it("returns the run index.json names as latest for the city", () => {
    const i = index([entry("2026-10-06-bbbbbb"), entry("2026-10-05-aaaaaa")], {
      sp: "2026-10-05-aaaaaa",
    });
    expect(latestRun(i, "sp")?.run_id).toBe("2026-10-05-aaaaaa");
  });

  it("returns null when the city has no latest run or it is missing from runs", () => {
    expect(latestRun(index([entry("2026-10-05-aaaaaa")]), "sp")).toBeNull();
    expect(latestRun(index([], { sp: "2026-10-05-aaaaaa" }), "sp")).toBeNull();
  });
});

describe("snapshotForDate", () => {
  it("finds the single snapshot of a date", () => {
    const i = index([entry("2026-10-05-aaaaaa"), entry("2026-10-05-bbbbbb", true)]);
    expect(snapshotForDate(i, "2026-10-05")).toEqual({ kind: "found", entry: i.runs[1] });
  });

  it("ignores runs that are not snapshots", () => {
    expect(snapshotForDate(index([entry("2026-10-05-aaaaaa")]), "2026-10-05")).toEqual({
      kind: "none",
    });
  });

  it("refuses to choose between two snapshots of the same date", () => {
    const i = index([entry("2026-10-05-aaaaaa", true), entry("2026-10-05-bbbbbb", true)]);
    expect(snapshotForDate(i, "2026-10-05").kind).toBe("ambiguous");
  });
});

describe("dates", () => {
  it("accepts only YYYY-MM-DD", () => {
    expect(isIsoDate("2026-10-05")).toBe(true);
    expect(isIsoDate("2026-13-05")).toBe(false);
    expect(isIsoDate("05-10-2026")).toBe(false);
  });

  it("formats run timestamps in UTC", () => {
    expect(formatRunDate("2026-10-05T23:59:00Z")).toBe("5 Oct 2026");
  });
});

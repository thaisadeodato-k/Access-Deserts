import { QueryClient } from "@tanstack/react-query";
import { createRouter, rootRouteId } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import { routeTree } from "@/routeTree.gen";

// Match routes without running loaders or rendering: loaders may need a server or
// network the test run lacks, and jsdom never loads the stylesheets React waits on.
describe("App routing", () => {
  it("matches a page for / instead of falling back to not found", () => {
    const router = createRouter({ routeTree, context: { queryClient: new QueryClient() } });

    const matches = router.matchRoutes("/");

    expect(matches.at(-1)?.routeId).not.toBe(rootRouteId);
  });

  it("matches the snapshot route with its date parameter", () => {
    const router = createRouter({ routeTree, context: { queryClient: new QueryClient() } });

    const match = router.matchRoutes("/snapshot/2026-10-05").at(-1);

    expect(match?.routeId).toBe("/snapshot/$date");
    expect(match?.params).toEqual({ date: "2026-10-05" });
  });
});

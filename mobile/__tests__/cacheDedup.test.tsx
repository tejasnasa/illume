/**
 * Cache dedup test for the layout's :class:`QueryClient`.
 *
 * The plan's third acceptance criterion is "requesting the same data
 * twice hits cache, not the network". This test mounts two components
 * that issue the same query at the same time and asserts the underlying
 * ``fetch`` is only called once -- the second subscriber receives the
 * in-flight promise, the canonical TanStack behaviour. We rebuild the
 * :class:`QueryClient` here rather than reusing the one in
 * ``_layout.tsx`` so the test is not coupled to its module's top-level
 * evaluation order.
 */

import React from "react";
import { Text } from "react-native";
import { render, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";

interface FetchMock {
  (input: RequestInfo | URL): Promise<Response>;
  calls: number;
}

function makeFetch(): FetchMock {
  const fn = jest.fn(async () =>
    new Response(JSON.stringify({ hello: "world" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  ) as unknown as FetchMock;
  fn.calls = 0;
  const wrapped: FetchMock = ((input: RequestInfo | URL) => {
    wrapped.calls += 1;
    return fn(input);
  }) as FetchMock;
  wrapped.calls = 0;
  return wrapped;
}

function Hello() {
  const { data } = useQuery({
    queryKey: ["ping"],
    queryFn: async () => {
      const r = await wrappedFetch("/api/v1/ping");
      return r.json();
    },
  });
  return <Text>{data ? JSON.stringify(data) : "loading"}</Text>;
}

const wrappedFetch = makeFetch();

function Harness({ client }: { client: QueryClient }) {
  return (
    <QueryClientProvider client={client}>
      <Hello />
      <Hello />
    </QueryClientProvider>
  );
}

describe("QueryClient cache dedup", () => {
  beforeEach(() => {
    wrappedFetch.calls = 0;
  });

  it("coalesces two concurrent subscribers into one network call", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    await render(<Harness client={client} />);

    await waitFor(() => {
      expect(wrappedFetch.calls).toBe(1);
    });
  });
});

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

export async function waitForApiReady({
  url,
  fetchImpl = fetch,
  timeoutMs = 60_000,
  intervalMs = 150,
  requestTimeoutMs = 1_000,
  signal,
}) {
  const deadline = Date.now() + timeoutMs;
  let lastFailure = 'health endpoint did not report ready';

  while (Date.now() < deadline) {
    if (signal?.aborted) throw new Error(`API readiness check stopped before ${url} became ready.`);
    try {
      const requestSignal = signal ? AbortSignal.any([signal, AbortSignal.timeout(requestTimeoutMs)]) : AbortSignal.timeout(requestTimeoutMs);
      const response = await fetchImpl(url, { signal: requestSignal });
      if (response.ok) {
        const health = await response.json();
        if (health?.ok === true) return health;
        lastFailure = 'health endpoint returned an unexpected response';
      } else {
        lastFailure = `health endpoint returned HTTP ${response.status}`;
      }
    } catch (error) {
      if (signal?.aborted) throw new Error(`API readiness check stopped before ${url} became ready.`);
      lastFailure = error instanceof Error ? error.message : String(error);
    }
    await delay(Math.min(intervalMs, Math.max(0, deadline - Date.now())));
  }

  throw new Error(`API did not become ready at ${url} within ${timeoutMs} ms (${lastFailure}).`);
}

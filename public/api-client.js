export async function requestJson(path, options = {}, fetchImpl = fetch) {
  let response;
  try {
    response = await fetchImpl(`/api/v1${path}`, options);
  } catch (cause) {
    if (cause instanceof TypeError) {
      const error = new Error(`Cannot reach the AeroPKmech API for ${path}. Check that the local API is running at 127.0.0.1:8000, then retry.`);
      error.cause = cause;
      error.code = 'API_UNREACHABLE';
      throw error;
    }
    throw cause;
  }

  const text = await response.text();
  let data = {};
  let validJson = true;
  try { data = text ? JSON.parse(text) : {}; } catch { validJson = false; }
  if (!response.ok) {
    const detail = validJson ? data.detail : null;
    const rawMessage = Array.isArray(detail)
      ? detail.map((item) => item.msg || JSON.stringify(item)).join('; ')
      : (typeof detail === 'string' ? detail : validJson && typeof data.error === 'string' ? data.error : null);
    const unsafeDetail = typeof rawMessage === 'string' && /traceback \(most recent call last\)|\bFile "[^\"]+", line \d+|\b(?:password|passwd|secret|token|authorization)\s*[:=]|\bBearer\s+[A-Za-z0-9._~+/-]+=*/i.test(rawMessage);
    const message = rawMessage && !unsafeDetail
      ? rawMessage.slice(0, 1000)
      : `AeroPKmech API returned HTTP ${response.status} for ${path}. The error response could not be shown safely; check the local API log.`;
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  if (!validJson || !text) {
    const error = new Error(`AeroPKmech API returned an invalid JSON response for ${path}. Check that the API is running correctly, then retry.`);
    error.status = response.status;
    error.code = 'INVALID_API_RESPONSE';
    throw error;
  }
  return data;
}

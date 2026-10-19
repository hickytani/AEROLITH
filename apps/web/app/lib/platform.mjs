const methods = new Set(['get', 'post', 'patch', 'put', 'delete']);

export function listOpenApiOperations(openApi) {
  const paths = openApi?.paths || {};
  return Object.entries(paths).flatMap(([path, operations]) => Object.entries(operations || {})
    .filter(([method, operation]) => methods.has(method) && operation && typeof operation === 'object')
    .map(([method, operation]) => ({
      method: method.toUpperCase(),
      path,
      summary: operation.summary || operation.operationId || 'API operation',
      description: operation.description || '',
      parameters: operation.parameters || [],
      requestBody: operation.requestBody || null,
      responses: operation.responses || {},
    })));
}

export async function copyText(text, clipboard = globalThis.navigator?.clipboard) {
  if (!clipboard || typeof clipboard.writeText !== 'function') throw new Error('Clipboard access is unavailable. Use localhost or a secure browser context.');
  await clipboard.writeText(text);
}

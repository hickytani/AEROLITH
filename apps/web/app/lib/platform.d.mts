export interface EndpointOperation {
  method: string;
  path: string;
  summary: string;
  description: string;
  parameters: Array<{ name: string; in: string; required?: boolean; description?: string; schema?: { type?: string } }>;
  requestBody: { content?: Record<string, { schema?: { $ref?: string } }> } | null;
  responses: Record<string, unknown>;
}
export function listOpenApiOperations(openApi: unknown): EndpointOperation[];
export function copyText(text: string, clipboard?: { writeText: (value: string) => Promise<void> }): Promise<void>;

import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import WorkspaceShell from './WorkspaceShell';

export default async function Home() {
  const html = await readFile(join(process.cwd(), 'public', 'index.html'), 'utf8');
  const body = html.match(/<body>([\s\S]*?)<\/body>/i)?.[1] ?? '';
  const markup = body.replace(/<script\s+type="module"\s+src="\/app\.js"><\/script>/i, '');
  return <WorkspaceShell markup={markup} />;
}

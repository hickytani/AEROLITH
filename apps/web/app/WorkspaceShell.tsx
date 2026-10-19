'use client';

import { useEffect } from 'react';

export default function WorkspaceShell({ markup }: { markup: string }) {
  useEffect(() => {
    let disposed = false;
    const script = document.createElement('script');
    script.type = 'module';
    script.src = `/app.js?instance=${Math.random().toString(36).slice(2)}`;
    script.onload = () => {
      if (disposed) window.dispatchEvent(new Event('aeropkmech:studio-dispose'));
    };
    document.body.appendChild(script);
    return () => {
      disposed = true;
      window.dispatchEvent(new Event('aeropkmech:studio-dispose'));
      script.remove();
    };
  }, []);

  return <div dangerouslySetInnerHTML={{ __html: markup }} />;
}

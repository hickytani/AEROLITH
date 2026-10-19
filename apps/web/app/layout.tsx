import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import './experiences.css';

export const metadata: Metadata = {
  title: 'AeroPKmech Studio · Gear study',
  description: 'Revision-aware, evidence-grounded spur gear design study.',
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <link rel="stylesheet" href="/style.css" />
        <script type="importmap" dangerouslySetInnerHTML={{ __html: JSON.stringify({ imports: { three: '/vendor/build/three.module.js', 'three/addons/': '/vendor/examples/jsm/' } }) }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
